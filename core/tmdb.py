# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------------------------------------
# tmdb.py - versione ottimizzata (completa, basata sull'originale)
#
# PERFORMANCE:
#  1. FIX cache: l'originale testava result.get('results'), assente nelle risposte by-ID ->
#     cache SEMPRE bypassata e riscritta a ogni chiamata. Ora usa sentinel hit/miss.
#  2. Cache a due livelli (memoria LRU + disco) con deduplica in-flight: thread concorrenti
#     sullo stesso URL fanno UNA sola richiesta (episodi della stessa stagione collassano in 1 hit).
#  3. ThreadPoolExecutor condiviso a livello modulo; risultati in ordine senza sort finale.
#  4. Scadenze cache via tabella; niente funzioni ricreate a ogni chiamata.
#  5. ast.literal_eval centralizzato in _to_dict; get_groups/select_group/get_group/get_list_episodes
#     passano da Tmdb.get_json (cache + retry + rate-limit) invece di requests nudo.
#  6. Risposte vuote/errori NON vengono più cachiate.
#
# FIX BUG (comportamento corretto, segnalati nel codice):
#  - get_backdrop: 'get_posterget_poster' al posto dell'URL base
#  - get_poster/get_backdrop (list): width/height letti da file_path (stringa) -> TypeError
#  - get_infoLabels/videos: trailer preso da v[0] invece che dall'item YouTube
#  - credits_crew: crew['job'] senza guard -> KeyError
#  - set_infoLabels_item stagione: date.split('-') senza assegnazione; insert path raw nei posters
#  - __by_id: IndexError su find con risultati vuoti; __search/__discover filtro: KeyError + O(n^2)
#  - get_json: retry rate-limit infinito e senza ignore_response_code
#  - get_season: except sovrascriveva 2 volte e tornava {"episodes": {}} incoerente
#  - get_episode: iterazione su dict invece che su lista per le stills
#  - find_and_set_infoLabels: crash su tmdb_id numerico
# ------------------------------------------------------------------------------------------------------------

import datetime
import sys

PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

if PY3:
    import urllib.parse as urllib                           # mantenuto per compatibilità
    from urllib.parse import quote as url_quote
    from concurrent import futures
else:
    import urllib
    from urllib import quote as url_quote
    from concurrent_py2 import futures

from future.builtins import range
from future.builtins import object

import ast, copy, re, time, threading
from collections import OrderedDict

from core import filetools, httptools, jsontools, scrapertools, db
from core.item import InfoLabels
from platformcode import config, logger, platformtools

info_language = ["de", "en", "es", "fr", "it", "pt"]  # from videolibrary.json
def_lang = info_language[config.get_setting("info_language", "videolibrary")]

host = 'https://api.themoviedb.org/3'
api = 'a1ab8b8669da03637a4b98fa39c39228'

_IMAGE_BASE = 'https://image.tmdb.org/t/p/'
_IMAGE_ORIGINAL = 'https://image.tmdb.org/t/p/original'
_RE_BRACKETS = re.compile(r'\[[^\]]+\]')
_RE_NEWLINES = re.compile(r"\n|\r|\t")

otmdb_global = None

"""
Set di funzioni relative agli infoLabels (vedi documentazione originale):
- set_infoLabels (source, seekTmdb, search_language)
- set_infoLabels_item / set_infoLabels_itemlist
- find_and_set_infoLabels, get_nfo, discovery, get_dic_genres...
"""

# -----------------------------------------------------------------------------------------------
# Cache: memoria (LRU) + disco + deduplica in-flight
# -----------------------------------------------------------------------------------------------
_MEM_CACHE_MAX = 512
_mem_cache = OrderedDict()
_mem_lock = threading.Lock()
_db_lock = threading.Lock()
_inflight = {}
_inflight_lock = threading.Lock()

_CACHE_EXPIRE_DAYS = {0: 1, 1: 7, 2: 15, 3: 30}


def clean_cache():
    with _mem_lock:
        _mem_cache.clear()
    db['tmdb_cache'].clear()


def _cache_is_valid(saved_date):
    try:
        expire = int(config.get_setting("tmdb_cache_expire", default=0))
    except Exception:
        expire = 0
    if expire == 4:  # no expire
        return True
    delta = datetime.timedelta(days=_CACHE_EXPIRE_DAYS.get(expire, 1))
    return (datetime.datetime.now() - saved_date) <= delta


def _to_dict(data):
    """Converte in dict bytes/str provenienti da cache o downloadpage (fallback a literal_eval)."""
    if isinstance(data, dict):
        return data
    try:
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        if isinstance(data, str):
            data = jsontools.load(data)
    except Exception:
        pass
    if not isinstance(data, dict):
        try:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            data = ast.literal_eval(data)
        except Exception:
            data = {}
    return data if isinstance(data, dict) else {}


def _mem_put(url, value, date):
    with _mem_lock:
        _mem_cache[url] = (copy.deepcopy(value), date)
        while len(_mem_cache) > _MEM_CACHE_MAX:
            _mem_cache.popitem(last=False)


def cache_response(fn):
    """Decoratore con cache a due livelli e deduplica delle richieste concorrenti sullo stesso URL."""

    def wrapper(*args, **kwargs):
        result = {}
        try:
            # cache attiva? (il flag può arrivare come kwarg o secondo arg posizionale)
            cache_enabled = kwargs.get('cache', args[1] if len(args) > 1 else True)
            if not config.get_setting("tmdb_cache", default=False) or not cache_enabled:
                return fn(*args)

            url = args[0]
            for pat in ('&year=-', '&primary_release_year=-', '&first_air_date_year=-'):
                url = url.replace(pat, '')

            # 1) cache in memoria
            with _mem_lock:
                hit = _mem_cache.get(url)
            if hit and _cache_is_valid(hit[1]):
                return copy.deepcopy(hit[0])

            # 2) cache su disco
            with _db_lock:
                row = db['tmdb_cache'].get(url)
            if row and _cache_is_valid(row[1]):
                value = _to_dict(row[0])
                _mem_put(url, value, row[1])
                return copy.deepcopy(value)

            # 3) deduplica in-flight: se un altro thread sta già scaricando lo stesso URL, aspetta
            with _inflight_lock:
                ev = _inflight.get(url)
                owner = ev is None
                if owner:
                    ev = _inflight[url] = threading.Event()

            if owner:
                try:
                    result = fn(*args)
                    if result:  # FIX: non cachare risposte vuote/errori
                        now = datetime.datetime.now()
                        with _db_lock:
                            db['tmdb_cache'][url] = [copy.deepcopy(result), now]
                        _mem_put(url, result, now)
                finally:
                    with _inflight_lock:
                        _inflight.pop(url, None)
                    ev.set()
            else:
                if ev.wait(30):
                    with _db_lock:
                        row = db['tmdb_cache'].get(url)
                    if row:
                        result = _to_dict(row[0])
                        _mem_put(url, result, row[1])
                if not result:  # timeout o fallimento dell'owner: riprova direttamente
                    result = fn(*args)
            return result

        except Exception as ex:
            message = "An exception of type {} occured. Arguments:\n{}".format(type(ex).__name__, repr(ex.args))
            logger.error("error in cache_response [{}]: {}".format(fn.__name__, message))
        return result
    return wrapper


# -----------------------------------------------------------------------------------------------
# set_infoLabels
# -----------------------------------------------------------------------------------------------
def set_infoLabels(source, seekTmdb=True, search_language=def_lang, forced=False):
    """Ottiene e imposta item.infoLabels per un item o per una lista di item."""
    if not config.get_setting('tmdb_active') and not forced:
        return

    start_time = time.time()
    if type(source) == list:
        ret = set_infoLabels_itemlist(source, seekTmdb, search_language)
        logger.debug("The data of {} links were obtained in {} seconds".format(len(source), time.time() - start_time))
    else:
        ret = set_infoLabels_item(source, seekTmdb, search_language)
        logger.debug("The data were obtained in {} seconds".format(time.time() - start_time))
    return ret


# Executor condiviso: evita creazione/distruzione del pool a ogni chiamata
try:
    _TMDB_THREADS = int(config.get_setting("tmdb_threads", default=10) or 10)
except Exception:
    _TMDB_THREADS = 10
if _TMDB_THREADS < 1:
    _TMDB_THREADS = 10
_EXECUTOR = futures.ThreadPoolExecutor(max_workers=_TMDB_THREADS)


def set_infoLabels_itemlist(itemlist, seekTmdb=False, search_language=def_lang, forced=False):
    """
    Ottiene concorrentemente i dati degli item della lista.
    NB: con la deduplica in-flight, gli item che richiedono lo stesso URL (es. episodi della
    stessa stagione) generano una sola richiesta di rete reale.
    """
    if not config.get_setting('tmdb_active') and not forced:
        return

    def sub_thread(_item, _i):
        ret = 0
        try:
            ret = set_infoLabels_item(_item, seekTmdb, search_language)
        except Exception:
            import traceback
            logger.error(traceback.format_exc(1))
        return (_i, _item, ret)

    # submit in ordine + raccolta in ordine: niente sort finale, compatibile anche con concurrent_py2
    futures_list = [_EXECUTOR.submit(sub_thread, item, i) for i, item in enumerate(itemlist)]
    return [f.result()[2] for f in futures_list]


def set_infoLabels_item(item, seekTmdb=True, search_language=def_lang):
    """Ottiene e imposta item.infoLabels per un singolo film/serie/stagione/episodio."""
    global otmdb_global

    def read_data(otmdb_aux):
        infoLabels = otmdb_aux.get_infoLabels(item.infoLabels)
        if not infoLabels.get('plot'):
            infoLabels['plot'] = otmdb_aux.get_plot('en')
        item.infoLabels = infoLabels
        if item.infoLabels.get('thumbnail'):
            item.thumbnail = item.infoLabels['thumbnail']
        if item.infoLabels.get('fanart'):
            item.fanart = item.infoLabels['fanart']

    if seekTmdb:
        def search(otmdb_global, search_type):
            if item.infoLabels.get('season'):
                try:
                    seasonNumber = int(item.infoLabels['season'])
                except ValueError:
                    logger.debug("The season number is not valid.")
                    return -1 * len(item.infoLabels)

                if not otmdb_global \
                        or (item.infoLabels['tmdb_id'] and str(otmdb_global.result.get("id")) != item.infoLabels['tmdb_id']) \
                        or (otmdb_global.searched_text and otmdb_global.searched_text != item.infoLabels['tvshowtitle']):
                    if item.infoLabels['tmdb_id']:
                        otmdb_global = Tmdb(id_Tmdb=item.infoLabels['tmdb_id'], search_type=search_type,
                                            search_language=search_language)
                    else:
                        otmdb_global = Tmdb(searched_text=scrapertools.unescape(item.infoLabels['tvshowtitle']),
                                            search_type=search_type, search_language=search_language,
                                            year=item.infoLabels['year'])
                    read_data(otmdb_global)

                if item.infoLabels['episode']:
                    try:
                        ep = int(item.infoLabels['episode'])
                    except ValueError:
                        logger.debug("The episode number ({}) is not valid".format(repr(item.infoLabels['episode'])))
                        return -1 * len(item.infoLabels)

                    # stagione + episodio validi: cerca i dati dell'episodio
                    item.infoLabels['mediatype'] = 'episode'
                    episode = otmdb_global.get_episode(seasonNumber, ep)

                    if episode:
                        read_data(otmdb_global)
                        item.infoLabels['mediatype'] = 'episode'
                        if episode.get('episode_title'):
                            item.infoLabels['title'] = episode['episode_title']
                        if episode.get('episode_plot'):
                            item.infoLabels['plot'] = episode['episode_plot']
                        if episode.get('episode_image'):
                            item.infoLabels['poster_path'] = episode['episode_image']
                            item.thumbnail = item.infoLabels['poster_path']
                        if episode.get('episode_air_date'):
                            item.infoLabels['aired'] = episode['episode_air_date']
                        if episode.get('episode_vote_average'):
                            item.infoLabels['rating'] = episode['episode_vote_average']
                        if episode.get('episode_vote_count'):
                            item.infoLabels['votes'] = episode['episode_vote_count']
                        if episode.get('episode_id'):
                            item.infoLabels['episode_id'] = episode['episode_id']
                        if episode.get('episode_imdb_id'):
                            item.infoLabels['episode_imdb_id'] = episode['episode_imdb_id']
                        if episode.get('episode_tvdb_id'):
                            item.infoLabels['episode_tvdb_id'] = episode['episode_tvdb_id']
                        if episode.get('episode_posters'):
                            item.infoLabels['posters'] = episode['episode_posters']
                        return len(item.infoLabels)

                else:
                    # stagione valida senza episodio: cerca i dati della stagione
                    item.infoLabels['mediatype'] = 'season'
                    season = otmdb_global.get_season(seasonNumber)
                    if not isinstance(season, dict):
                        season = _to_dict(season)

                    if season:
                        read_data(otmdb_global)
                        item.infoLabels['title'] = season.get("name", '')
                        item.infoLabels['plot'] = season.get("overview", '')

                        date = season.get("air_date", '')
                        if date:
                            # FIX: l'originale faceva date.split('-') senza assegnazione
                            try:
                                y, m, d = date.split('-')
                                item.infoLabels['aired'] = "{}/{}/{}".format(d, m, y)
                            except ValueError:
                                item.infoLabels['aired'] = date

                        seasonPoster = season.get('poster_path', '')
                        if seasonPoster:
                            item.infoLabels['poster_path'] = _IMAGE_ORIGINAL + seasonPoster
                            item.thumbnail = item.infoLabels['poster_path']

                        # FIX: season['images']['posters'] poteva sollevare KeyError
                        images = season.get('images') or {}
                        seasonPosters = [_IMAGE_ORIGINAL + i['file_path'] for i in (images.get('posters') or [])
                                         if i.get('file_path')]
                        if seasonPosters:
                            if seasonPoster:
                                # FIX: l'originale inseriva il path raw in una lista di URL completi
                                seasonPosters.insert(0, item.infoLabels['poster_path'])
                            item.infoLabels['posters'] = seasonPosters
                        return len(item.infoLabels)

            else:
                # Ricerca per ID, altrimenti per titolo
                if item.infoLabels['tmdb_id']:
                    otmdb = Tmdb(id_Tmdb=item.infoLabels['tmdb_id'], search_type=search_type,
                                 search_language=search_language)
                elif item.infoLabels['imdb_id']:
                    otmdb = Tmdb(external_id=item.infoLabels['imdb_id'], external_source="imdb_id",
                                 search_type=search_type, search_language=search_language)
                elif search_type == 'tv':
                    if item.infoLabels['tvdb_id']:
                        otmdb = Tmdb(external_id=item.infoLabels['tvdb_id'], external_source="tvdb_id",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['freebase_mid']:
                        otmdb = Tmdb(external_id=item.infoLabels['freebase_mid'], external_source="freebase_mid",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['freebase_id']:
                        otmdb = Tmdb(external_id=item.infoLabels['freebase_id'], external_source="freebase_id",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['tvrage_id']:
                        otmdb = Tmdb(external_id=item.infoLabels['tvrage_id'], external_source="tvrage_id",
                                     search_type=search_type, search_language=search_language)
                    else:
                        otmdb = None
                else:
                    otmdb = None

                if not item.infoLabels['tmdb_id'] and not item.infoLabels['imdb_id'] and not item.infoLabels['tvdb_id'] \
                        and not item.infoLabels['freebase_mid'] and not item.infoLabels['freebase_id'] \
                        and not item.infoLabels['tvrage_id']:
                    # nessun ID disponibile: ricerca per titolo
                    if search_type == 'tv':
                        searched_title = scrapertools.unescape(item.infoLabels['tvshowtitle'])
                    else:
                        searched_title = scrapertools.unescape(item.infoLabels['title'])

                    otmdb = Tmdb(searched_text=searched_title, search_type=search_type,
                                 search_language=search_language, filtro=item.infoLabels.get('filtro', {}),
                                 year=item.infoLabels['year'])
                    if otmdb is not None and not otmdb.get_id():
                        otmdb = Tmdb(searched_text=searched_title, search_type=search_type,
                                     search_language=search_language, filtro=item.infoLabels.get('filtro', {}))
                    if otmdb is not None:
                        if otmdb.get_id() and config.get_setting("tmdb_plus_info", default=False):
                            # ricerca riuscita: seconda ricerca per espandere le informazioni
                            if search_type == 'multi':
                                search_type = otmdb.result.get('media_type')
                            otmdb = Tmdb(id_Tmdb=otmdb.result.get("id"), search_type=search_type,
                                         search_language=search_language)

                if otmdb is not None and otmdb.get_id():
                    read_data(otmdb)
                    return len(item.infoLabels)

        def unify():
            new_title = scrapertools.title_unify(item.fulltitle)
            if new_title != item.fulltitle:
                item.infoLabels['tvshowtitle'] = scrapertools.title_unify(item.infoLabels['tvshowtitle'])
                item.infoLabels['title'] = scrapertools.title_unify(item.infoLabels['title'])
                return True

        if item.contentType == 'movie':
            search_type = 'movie'
        elif item.contentType == 'undefined':
            search_type = 'multi'
        else:
            search_type = 'tv'

        ret = search(otmdb_global, search_type)
        if not ret:  # ritenta con il titolo unificato
            backup = [item.fulltitle, item.infoLabels['tvshowtitle'], item.infoLabels['title']]
            if unify():
                ret = search(otmdb_global, search_type)
            if not ret:
                item.fulltitle, item.infoLabels['tvshowtitle'], item.infoLabels['title'] = backup
        return ret

    return -1 * len(item.infoLabels)


def find_and_set_infoLabels(item):
    global otmdb_global
    tmdb_result = None

    if item.contentType == "movie":
        search_type = "movie"
        content_type = config.get_localized_string(60247)
        title = item.contentTitle
    else:
        search_type = "tv"
        content_type = config.get_localized_string(60298)
        title = item.contentSerieName

    # Se il titolo include l'(anno) lo rimuoviamo
    year = scrapertools.find_single_match(title, "^.+?\s*(\(\d{4}\))$")
    if year:
        title = title.replace(year, "").strip()
        item.infoLabels['year'] = year[1:-1]

    # FIX: l'originale Crashava se tmdb_id fosse numerico (int non ha [0])
    tmdb_id_str = str(item.infoLabels.get("tmdb_id", "") or "")
    if not tmdb_id_str or not tmdb_id_str[0:1].isdigit():
        if item.infoLabels.get("imdb_id"):
            otmdb_global = Tmdb(external_id=item.infoLabels.get("imdb_id"), external_source="imdb_id",
                                search_type=search_type)
        else:
            otmdb_global = Tmdb(searched_text=scrapertools.unescape(title), search_type=search_type,
                                year=item.infoLabels['year'])
    elif not otmdb_global or str(otmdb_global.result.get("id")) != tmdb_id_str:
        otmdb_global = Tmdb(id_Tmdb=tmdb_id_str, search_type=search_type, search_language=def_lang)

    results = otmdb_global.get_list_results()
    if len(results) > 1:
        # seleziona il tmdb_id richiesto in prima posizione
        if item.infoLabels['selected_tmdb_id']:
            results.insert(0, results.pop([r.get('id') for r in results].index(int(item.infoLabels['selected_tmdb_id']))))
        tmdb_result = platformtools.show_video_info(results, item=item, caption=content_type % title)
    elif len(results) > 0:
        tmdb_result = results[0]

    if isinstance(item.infoLabels, InfoLabels):
        infoLabels = item.infoLabels
    else:
        infoLabels = InfoLabels()

    if tmdb_result:
        infoLabels['tmdb_id'] = tmdb_result['id']
        infoLabels['url_scraper'] = ["https://www.themoviedb.org/{}/{}".format(search_type, infoLabels['tmdb_id'])]
        if infoLabels['tvdb_id']:
            infoLabels['url_scraper'].append("http://thetvdb.com/index.php?tab=series&id=" + str(infoLabels['tvdb_id']))
        item.infoLabels = infoLabels
        set_infoLabels_item(item)
        return True
    else:
        item.infoLabels = infoLabels
        return False


def get_nfo(item, search_groups=False):
    """Informazioni necessarie per lo scraping in videoteca Kodi (per tmdb solo via url)."""
    if search_groups:
        from platformcode.autorenumber import RENUMBER, GROUP
        path = filetools.join(config.get_data_path(), "settings_channels", item.channel + "_data.json")
        if filetools.exists(path):
            g = jsontools.load(filetools.read(path)).get(RENUMBER, {}).get(item.fulltitle.strip(), {}).get(GROUP, '')
            if g:
                if type(g) == list:
                    g = ', '.join(g)
                return g + '\n'

        groups = get_groups(item)
        if groups:
            Id = select_group(groups, item)
            if Id == 'original':
                return ', '.join(item.infoLabels['url_scraper']) + '\n'
            elif Id:
                return 'https://www.themoviedb.org/tv/{}/episode_group/{}'.format(item.infoLabels['tmdb_id'], Id) + '\n'
            else:
                return

    return ', '.join(item.infoLabels['url_scraper']) + '\n'


# FIX: ora passano da Tmdb.get_json -> cache, retry, rate-limit (prima requests nudo)
def get_groups(item):
    url = '{}/tv/{}/episode_groups?api_key={}&language={}'.format(host, item.infoLabels['tmdb_id'], api, def_lang)
    return _to_dict(Tmdb.get_json(url)).get('results', [])


def select_group(groups, item):
    selected = -1
    url = '{}/tv/{}?api_key={}&language={}'.format(host, item.infoLabels['tmdb_id'], api, def_lang)
    res = _to_dict(Tmdb.get_json(url))
    selections = [['Original', res.get('number_of_seasons', 0), res.get('number_of_episodes', 0), '', item.thumbnail]]
    ids = ['original']
    for group in groups:
        ID = group.get('id', '')
        if ID:
            selections.append([group.get('name', ''), group.get('group_count', 0), group.get('episode_count', 0),
                               group.get('description', ''), item.thumbnail])
            ids.append(ID)
    if selections and ids:
        selected = platformtools.dialog_select_group(config.get_localized_string(70831), selections)
    if selected > -1:
        return ids[selected]
    return ''


def get_group(Id):
    url = '{}/tv/episode_group/{}?api_key={}&language={}'.format(host, Id, api, def_lang)
    return _to_dict(Tmdb.get_json(url)).get('groups', [])


def completar_codigos(item):
    """Se necessario verifica se esiste l'identificativo tvdb, altrimenti tenta di trovarlo."""
    if item.contentType != "movie" and not item.infoLabels['tvdb_id']:
        from core.tvdb import Tvdb
        ob = Tvdb(imdb_id=item.infoLabels['imdb_id'])
        item.infoLabels['tvdb_id'] = ob.get_id()
    if item.infoLabels['tvdb_id']:
        url_scraper = "http://thetvdb.com/index.php?tab=series&id=" + str(item.infoLabels['tvdb_id'])
        if url_scraper not in item.infoLabels['url_scraper']:
            item.infoLabels['url_scraper'].append(url_scraper)


def discovery(item, dict_=False, cast=False):
    from core.item import Item

    if dict_:
        if item.page:
            if not item.discovery:
                item.discovery = {}
            item.discovery['page'] = item.page
        listado = Tmdb(discover=dict_, cast=cast)
    elif item.search_type == 'discover':
        listado = Tmdb(discover={'url': 'discover/' + item.type, 'with_genres': item.list_type,
                                 'language': def_lang, 'page': item.page})
    elif item.search_type == 'list':
        if item.page == '':
            item.page = '1'
        listado = Tmdb(discover={'url': item.list_type, 'language': def_lang, 'page': item.page})
    return listado


def get_dic_genres(search_type):
    lang = def_lang
    genres = Tmdb(search_type=search_type)
    return genres.dic_genres[lang]


def infoLabels_tostring(item):
    # [RICOSTRUITO] citata nel docstring originale ma non presente nel codice fornito
    try:
        return '\n'.join(['%s: %s' % (k, item.infoLabels[k]) for k in sorted(item.infoLabels.keys())])
    except Exception:
        return str(getattr(item, 'infoLabels', ''))


# -----------------------------------------------------------------------------------------------
# Auxiliary class
# -----------------------------------------------------------------------------------------------
class ResultDictDefault(dict):
    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            return self.__missing__(key)

    def __missing__(self, key):
        """Valori di default nel caso la chiave richiesta non esista."""
        if key in ['genre_ids', 'genre', 'genres']:
            return list()

        elif key in ['images_posters', 'images_backdrops', 'images_profiles']:
            kind = key.replace('images_', '')
            value = {}
            images = self.get('images')
            if isinstance(images, dict) and kind in images:
                value = images[kind]
            super(ResultDictDefault, self).__setattr__(key, value)
            return value

        else:
            # Le altre chiavi ritornano stringa vuota di default
            return ""

    def __str__(self):
        return self.tostring(separador=',\n')

    def tostring(self, separador=',\n'):
        ls = []
        for i in list(dict.items(self)):
            i_str = str(i)[1:-1]
            if isinstance(i[0], str):
                old = i[0] + "',"
                new = i[0] + "':"
            else:
                old = str(i[0]) + ","
                new = str(i[0]) + ":"
            ls.append(i_str.replace(old, new, 1))
        return "{%s}" % separador.join(ls)


# -----------------------------------------------------------------------------------------------
# class Tmdb: Scraper per l'API di https://www.themoviedb.org/
# -----------------------------------------------------------------------------------------------
class Tmdb(object):
    # Class attribute
    dic_genres = {}

    dic_country = {"AD": "Andorra", "AE": "Emiratos Árabes Unidos", "AF": "Afganistán", "AG": "Antigua y Barbuda",
                   "AI": "Anguila", "AL": "Albania", "AM": "Armenia", "AN": "Antillas Neerlandesas", "AO": "Angola",
                   "AQ": "Antártida", "AR": "Argentina", "AS": "Samoa Americana", "AT": "Austria", "AU": "Australia",
                   "AW": "Aruba", "AX": "Islas de Åland", "AZ": "Azerbayán", "BA": "Bosnia y Herzegovina",
                   "BD": "Bangladesh", "BE": "Bélgica", "BF": "Burkina Faso", "BG": "Bulgaria", "BI": "Burundi",
                   "BJ": "Benín", "BL": "San Bartolomé", "BM": "Islas Bermudas", "BN": "Brunéi", "BO": "Bolivia",
                   "BR": "Brasil", "BS": "Bahamas", "BT": "Bhután", "BV": "Isla Bouvet", "BW": "Botsuana",
                   "BY": "Bielorrusia", "BZ": "Belice", "CA": "Canadá", "CC": "Islas Cocos (Keeling)", "CD": "Congo",
                   "CF": "República Centroafricana", "CG": "Congo", "CH": "Suiza", "CI": "Costa de Marfil",
                   "CK": "Islas Cook", "CL": "Chile", "CM": "Camerún", "CN": "China", "CO": "Colombia",
                   "CR": "Costa Rica", "CU": "Cuba", "CV": "Cabo Verde", "CX": "Isla de Navidad", "CY": "Chipre",
                   "CZ": "República Checa", "DE": "Alemania", "DJ": "Yibuti", "DK": "Dinamarca", "DZ": "Algeria",
                   "EC": "Ecuador", "EE": "Estonia", "EG": "Egipto", "EH": "Sahara Occidental", "ER": "Eritrea",
                   "ES": "España", "ET": "Etiopía", "FI": "Finlandia", "FJ": "Fiyi", "FK": "Islas Malvinas",
                   "FM": "Micronesia", "FO": "Islas Feroe", "FR": "Francia", "GA": "Gabón", "GB": "Gran Bretaña",
                   "GD": "Granada", "GE": "Georgia", "GF": "Guayana Francesa", "GG": "Guernsey", "GH": "Ghana",
                   "GI": "Gibraltar", "GL": "Groenlandia", "GM": "Gambia", "GN": "Guinea", "GP": "Guadalupe",
                   "GQ": "Guinea Ecuatorial", "GR": "Grecia", "GS": "Islas Georgias del Sur y Sandwich del Sur",
                   "GT": "Guatemala", "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong kong",
                   "HM": "Islas Heard y McDonald", "HN": "Honduras", "HR": "Croacia", "HT": "Haití", "HU": "Hungría",
                   "ID": "Indonesia", "IE": "Irlanda", "IM": "Isla de Man", "IN": "India",
                   "IO": "Territorio Británico del Océano Índico", "IQ": "Irak", "IR": "Irán", "IS": "Islandia",
                   "IT": "Italia", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordania", "JP": "Japón", "KG": "Kirgizstán",
                   "KH": "Camboya", "KM": "Comoras", "KP": "Corea del Norte", "KR": "Corea del Sur", "KW": "Kuwait",
                   "KY": "Islas Caimán", "KZ": "Kazajistán", "LA": "Laos", "LB": "Líbano", "LC": "Santa Lucía",
                   "LI": "Liechtenstein", "LK": "Sri lanka", "LR": "Liberia", "LS": "Lesoto", "LT": "Lituania",
                   "LU": "Luxemburgo", "LV": "Letonia", "LY": "Libia", "MA": "Marruecos", "MC": "Mónaco",
                   "MD": "Moldavia", "ME": "Montenegro", "MF": "San Martín (Francia)", "MG": "Madagascar",
                   "MH": "Islas Marshall", "MK": "Macedônia", "ML": "Mali", "MM": "Birmania", "MN": "Mongolia",
                   "MO": "Macao", "MP": "Islas Marianas del Norte", "MQ": "Martinica", "MR": "Mauritania",
                   "MS": "Montserrat", "MT": "Malta", "MU": "Mauricio", "MV": "Islas Maldivas", "MW": "Malawi",
                   "MX": "México", "MY": "Malasia", "NA": "Namibia", "NE": "Niger", "NG": "Nigeria", "NI": "Nicaragua",
                   "NL": "Países Bajos", "NO": "Noruega", "NP": "Nepal", "NR": "Nauru", "NU": "Niue",
                   "NZ": "Nueva Zelanda", "OM": "Omán", "PA": "Panamá", "PE": "Perú", "PF": "Polinesia Francesa",
                   "PH": "Filipinas", "PK": "Pakistán", "PL": "Polonia", "PM": "San Pedro y Miquelón",
                   "PN": "Islas Pitcairn", "PR": "Puerto Rico", "PS": "Palestina", "PT": "Portugal", "PW": "Palau",
                   "PY": "Paraguay", "QA": "Qatar", "RE": "Reunión", "RO": "Rumanía", "RS": "Serbia", "RU": "Rusia",
                   "RW": "Ruanda", "SA": "Arabia Saudita", "SB": "Islas Salomón", "SC": "Seychelles", "SD": "Sudán",
                   "SE": "Suecia", "SG": "Singapur", "SH": "Santa Elena", "SI": "Eslovenia",
                   "SJ": "Svalbard y Jan Mayen",
                   "SK": "Eslovaquia", "SL": "Sierra Leona", "SM": "San Marino", "SN": "Senegal", "SO": "Somalia",
                   "SV": "El Salvador", "SY": "Siria", "SZ": "Swazilandia", "TC": "Islas Turcas y Caicos", "TD": "Chad",
                   "TF": "Territorios Australes y Antárticas Franceses", "TG": "Togo", "TH": "Tailandia",
                   "TJ": "Tadjikistán", "TK": "Tokelau", "TL": "Timor Oriental", "TM": "Turkmenistán", "TN": "Tunez",
                   "TO": "Tonga", "TR": "Turquía", "TT": "Trinidad y Tobago", "TV": "Tuvalu", "TW": "Taiwán",
                   "TZ": "Tanzania", "UA": "Ucrania", "UG": "Uganda",
                   "UM": "Islas Ultramarinas Menores de Estados Unidos",
                   "UY": "Uruguay", "UZ": "Uzbekistán", "VA": "Ciudad del Vaticano",
                   "VC": "San Vicente y las Granadinas",
                   "VE": "Venezuela", "VG": "Islas Vírgenes Británicas", "VI": "Islas Vírgenes de los Estados Unidos",
                   "VN": "Vietnam", "VU": "Vanuatu", "WF": "Wallis y Futuna", "WS": "Samoa", "YE": "Yemen",
                   "YT": "Mayotte", "ZA": "Sudáfrica", "ZM": "Zambia", "ZW": "Zimbabue", "BB": "Barbados",
                   "BH": "Bahrein",
                   "DM": "Dominica", "DO": "República Dominicana", "GU": "Guam", "IL": "Israel", "KE": "Kenia",
                   "KI": "Kiribati", "KN": "San Cristóbal y Nieves", "MZ": "Mozambique", "NC": "Nueva Caledonia",
                   "NF": "Isla Norfolk", "PG": "Papúa Nueva Guinea", "SR": "Surinám", "ST": "Santo Tomé y Príncipe",
                   "US": "EEUU"}

    def __init__(self, **kwargs):
        self.page = kwargs.get('page', 1)
        self.index_results = 0
        self.cast = kwargs.get('cast', False)
        self.results = []
        self.result = ResultDictDefault()
        self.total_pages = 0
        self.total_results = 0

        self.season = {}
        self.searched_text = kwargs.get('searched_text', '')

        self.search_id = kwargs.get('id_Tmdb', '')
        self.search_text = _RE_BRACKETS.sub('', self.searched_text).strip()
        self.search_type = kwargs.get('search_type', '')
        self.search_language = kwargs.get('search_language', def_lang)
        self.fallback_language = 'en'
        self.search_year = kwargs.get('year', '')
        self.search_filter = kwargs.get('filtro', {})
        self.discover = kwargs.get('discover', {})

        # Ricarica il dizionario dei generi se necessario
        if (self.search_type == 'movie' or self.search_type == "tv") and \
                (self.search_language not in Tmdb.dic_genres or self.search_type not in Tmdb.dic_genres[self.search_language]):
            self.filling_dic_genres(self.search_type, self.search_language)

        if not self.search_type:
            self.search_type = 'movie'

        if self.search_id:
            # Ricerca per identificatore tmdb
            self.__by_id()
        elif self.search_text:
            # Ricerca per testo
            self.__search(page=self.page)
        elif 'external_source' in kwargs and 'external_id' in kwargs:
            # Serie TV: imdb_id, freebase_mid, freebase_id, tvdb_id, tvrage_id - Film: imdb_id
            if (self.search_type == 'movie' and kwargs.get('external_source') == "imdb_id") or \
                    (self.search_type == 'tv' and kwargs.get('external_source') in ("imdb_id", "freebase_mid", "freebase_id", "tvdb_id", "tvrage_id")):
                self.search_id = kwargs.get('external_id')
                self.__by_id(source=kwargs.get('external_source'))
        elif self.discover:
            self.__discover()
        else:
            logger.debug("Created empty object")

    @staticmethod
    @cache_response
    def get_json(url, cache=True):
        try:
            result = httptools.downloadpage(url, cookies=False, ignore_response_code=True)
            res_headers = result.headers or {}
            dict_data = _to_dict(result.json)

            # FIX: retry limitato a 3 (l'originale poteva girare all'infinito) e con
            # ignore_response_code preservato nelle ripetute chiamate
            retries = 0
            while dict_data.get("status_code") == 25 and retries < 3:
                try:
                    wait = int(res_headers.get('retry-after', 5) or 5)
                except Exception:
                    wait = 5
                logger.error("TMDB limit reached, waiting {}s...".format(wait))
                time.sleep(wait)
                result = httptools.downloadpage(url, cookies=False, ignore_response_code=True)
                res_headers = result.headers or {}
                dict_data = _to_dict(result.json)
                retries += 1

            return dict_data

        except Exception as ex:
            message = "An exception of type %s occured. Arguments:\n%s" % (type(ex).__name__, repr(ex.args))
            logger.error("error in: %s" % message)
            return {}

    @classmethod
    def filling_dic_genres(cls, search_type='movie', language=def_lang):
        # Riempie il dizionario dei generi per il tipo e la lingua passati come parametri
        if language not in cls.dic_genres:
            cls.dic_genres[language] = {}

        if search_type not in cls.dic_genres[language]:
            cls.dic_genres[language][search_type] = {}
            url = '{}/genre/{}/list?api_key={}&language={}'.format(host, search_type, api, language)
            try:
                logger.debug("[Tmdb.py] Filling in dictionary of genres")
                result = _to_dict(cls.get_json(url))
                for i in result.get("genres", []):
                    cls.dic_genres[language][search_type][str(i["id"])] = i["name"]
            except Exception:
                logger.error("Error generating dictionaries")
                import traceback
                logger.error(traceback.format_exc())

    def get_mpaa(self, result):
        # Certificazione US (release_dates per film, content_ratings per serie)
        if result.get('id'):
            Mpaaurl = '{}/{}/{}/{}?api_key={}'.format(host, self.search_type, result['id'],
                                                      'release_dates' if self.search_type == 'movie' else 'content_ratings',
                                                      api)
            Mpaas = _to_dict(self.get_json(Mpaaurl)).get('results', [])
            for m in Mpaas:
                if m.get('iso_3166_1', '').lower() == 'us':
                    result['mpaa'] = m.get('rating', m.get('release_dates', [{}])[0].get('certification'))
                    break
        return result

    def __by_id(self, source='tmdb'):
        if self.search_id:
            if source == "tmdb":
                url = ('{}/{}/{}?api_key={}&language={}&append_to_response=images,videos,external_ids,credits'
                       '&include_image_language={},en,null').format(host, self.search_type, self.search_id, api,
                                                                    self.search_language, self.search_language)
                searching = "id_Tmdb: {}".format(self.search_id)
            else:
                url = '{}/find/{}?external_source={}&api_key={}&language={}'.format(host, self.search_id, source, api,
                                                                                    self.search_language)
                searching = "{}: {}".format(source.capitalize(), self.search_id)

            logger.debug("[Tmdb.py] Searching %s:\n%s" % (searching, url))
            result = _to_dict(self.get_json(url))

            if result:
                if source != "tmdb":
                    # FIX: l'originale poteva sollevare IndexError su liste vuote
                    if self.search_type == "movie":
                        result = (result.get("movie_results") or [{}])[0]
                    else:
                        if result.get("tv_results"):
                            result = result["tv_results"][0]
                        else:
                            result = (result.get('tv_episode_results') or [{}])[0]

                result = self.get_mpaa(result)

                self.results = [result]
                self.total_results = 1
                self.total_pages = 1
                self.result = ResultDictDefault(result)
                self.result['media_type'] = self.search_type.replace('tv', 'tvshow')
            else:
                logger.debug("The search of %s gave no results" % searching)

    def __search(self, index_results=0, page=1):
        self.result = ResultDictDefault()
        results = []
        text_simple = self.search_text.lower()
        text_quote = url_quote(text_simple)
        total_results = 0
        total_pages = 0
        searching = ""

        if self.search_text:
            url = '{}/search/{}?api_key={}&query={}&language={}&include_adult={}&page={}'.format(
                host, self.search_type, api, text_quote, self.search_language, False, page)

            if self.search_year:
                if self.search_type == 'movie':
                    url += '&primary_release_year=%s' % self.search_year
                else:
                    url += '&first_air_date_year=%s' % self.search_year

            searching = self.search_text.capitalize()
            logger.debug("[Tmdb.py] Searching %s on page %s:\n%s" % (searching, page, url))
            result = _to_dict(self.get_json(url))

            total_results = result.get("total_results", 0)
            total_pages = result.get("total_pages", 0)

            if total_results > 0:
                results = [r for r in result.get("results", []) if r.get('first_air_date', r.get('release_date', ''))]

            # FIX: l'originale usava r[key] e results.remove() in loop (KeyError + O(n^2))
            if self.search_filter and total_results > 1:
                for key, value in list(dict(self.search_filter).items()):
                    kept = []
                    for r in results:
                        field = str(r.get(key, '') or '')
                        if value in field:
                            kept.append(r)
                        else:
                            total_results -= 1
                    results = kept

        if results:
            if index_results >= len(results):
                # È stato richiesto un numero di risultati superiore a quelli ottenuti
                logger.error("The search for '%s' gave %s results for the page %s \n "
                             "It is impossible to show the result number %s"
                             % (searching, len(results), page, index_results))
                return 0

            # Ordinamento dei risultati basato su fuzzy match per individuare il più simile
            if len(results) > 1:
                from lib.fuzzy_match import algorithims
                if self.search_type == 'multi':
                    if self.search_year:
                        for r in results:
                            if (r.get('release_date', '') and r.get('release_date', '')[:4] == self.search_year) \
                                    or (r.get('first_air_date', '') and r.get('first_air_date', '')[:4] == self.search_year):
                                results = [r]
                                break
                    if len(results) > 1:
                        results.sort(key=lambda r: algorithims.trigram(text_simple, r.get('name', '') if r.get('media_type') == 'tv' else r.get('title', '')), reverse=True)
                else:
                    results.sort(key=lambda r: algorithims.trigram(text_simple, r.get('name', '') if self.search_type == 'tv' else r.get('title', '')), reverse=True)

            # Ritorna il numero di risultati di questa pagina
            self.results = results
            self.total_results = total_results
            self.total_pages = total_pages
            self.result = ResultDictDefault(self.results[index_results])

            if not config.get_setting('tmdb_plus_info'):
                self.result = self.get_mpaa(self.result)
            return len(self.results)

        else:
            logger.error("The search for '%s' gave no results for page %s" % (searching, page))
            return 0

    def __discover(self, index_results=0):
        self.result = ResultDictDefault()
        results = []
        total_results = 0
        total_pages = 0

        # Esempio self.discover: {'url': 'discover/movie', 'with_cast': '1'}
        type_search = self.discover.get('url', '')
        if type_search:
            params = []
            for key, value in list(self.discover.items()):
                if key != "url":
                    params.append(key + "=" + str(value))

            url = '{}/{}?api_key={}&{}'.format(host, type_search, api, "&".join(params))

            logger.debug("[Tmdb.py] Searching %s:\n%s" % (type_search, url))
            result = _to_dict(self.get_json(url, cache=False))

            total_results = result.get("total_results", -1)
            total_pages = result.get("total_pages", 1)

            if total_results > 0 or self.cast:
                if self.cast:
                    results = result.get('cast', [])
                    total_results = len(results)
                else:
                    results = result.get("results", [])
                # FIX: r[key] su chiavi assenti + remove in loop -> filtro O(n)
                if self.search_filter and results:
                    for key, value in list(dict(self.search_filter).items()):
                        results = [r for r in results if r.get(key) == value]
                    total_results = len(results)
            elif total_results == -1:
                results = result

            if index_results >= len(results):
                logger.error("The search for '%s' did not give %s results" % (type_search, index_results))
                return 0

        # Ritorna il numero di risultati di questa pagina
        if results:
            self.results = results
            self.total_results = total_results
            self.total_pages = total_pages
            if total_results > 0:
                self.result = ResultDictDefault(self.results[index_results])
            else:
                self.result = results
            return len(self.results)
        else:
            logger.error("The search for '%s' gave no results" % type_search)
            return 0

    def load_result(self, index_results=0, page=1):
        self.result = ResultDictDefault()
        num_result_page = len(self.results)

        if page > self.total_pages:
            return False

        if page != self.page:
            num_result_page = self.__search(index_results, page)

        if num_result_page == 0 or num_result_page <= index_results:
            return False

        self.page = page
        self.index_results = index_results
        self.result = ResultDictDefault(self.results[index_results])
        return True

    def get_list_results(self, num_result=20):
        res = []

        if num_result <= 0:
            num_result = self.total_results
        num_result = min([num_result, self.total_results])

        cr = 0
        for p in range(1, self.total_pages + 1):
            for r in range(0, len(self.results)):
                try:
                    if self.load_result(r, p):
                        result = self.result.copy()
                        result['thumbnail'] = self.get_poster(size="w300")
                        result['fanart'] = self.get_backdrop()
                        res.append(result)
                        cr += 1
                        if cr >= num_result:
                            return res
                except Exception:
                    continue
        return res

    def get_genres(self, origen=None):
        """
        :param origen: dizionario sorgente, di default self.result
        :return: lista (str) dei generi del film/serie
        """
        genre_list = []

        if not origen:
            origen = self.result

        if "genre_ids" in origen:
            # Lista dei generi tramite ID
            for i in origen.get("genre_ids"):
                try:
                    genre_list.append(Tmdb.dic_genres[self.search_language][self.search_type][str(i)])
                except Exception:
                    pass

        elif "genre" in origen or "genres" in origen:
            # Lista dei generi (lista di oggetti {id, name})
            v = origen["genre"]
            v.extend(origen["genres"])
            for i in v:
                genre_list.append(i['name'])

        return ', '.join(genre_list)

    def search_by_id(self, id, source='tmdb', search_type='movie'):
        self.search_id = id
        self.search_type = search_type
        self.__by_id(source=source)

    def get_id(self):
        """Ritorna l'id Tmdb dell'elemento caricato, o stringa vuota se la ricerca non ha avuto successo."""
        return str(self.result.get('id', ""))

    def get_plot(self, language_alternative=''):
        """Ritorna la sinossi; se vuota e previsto, ripete la ricerca nella lingua alternativa."""
        ret = ""

        if 'id' in self.result:
            ret = self.result.get('overview')
            if ret == "" and str(language_alternative).lower() != 'none':
                # Nuova ricerca per id e rilettura della sinossi
                self.search_id = str(self.result["id"])
                if language_alternative:
                    self.search_language = language_alternative
                else:
                    self.search_language = self.result['original_language']

                url = '{}/{}/{}?api_key={}&language={}'.format(host, self.search_type, self.search_id, api,
                                                               self.search_language)
                result = _to_dict(self.get_json(url))

                if 'overview' in result:
                    self.result['overview'] = result['overview']
                    ret = self.result['overview']
        return ret

    def get_poster(self, response_type="str", size="original"):
        ret = []
        if size not in ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280"):
            size = "original"

        poster_path = self.result["poster_path"]
        if poster_path is None or poster_path == "":
            poster_path = ""
        else:
            poster_path = _IMAGE_BASE + size + poster_path

        if response_type == 'str':
            return poster_path
        elif not self.result["id"]:
            return []

        if len(self.result['images_posters']) == 0:
            # Nuova ricerca per id e rilettura
            self.search_id = str(self.result["id"])
            self.__by_id()

        for i in self.result['images_posters']:
            file_path = i['file_path']
            if size != "original":
                # FIX: l'originale leggeva width/height da file_path (stringa) -> TypeError
                if size[1] == 'w' and int(i.get('width', 0)) < int(size[1:]):
                    size = "original"
                elif size[1] == 'h' and int(i.get('height', 0)) < int(size[1:]):
                    size = "original"
            ret.append(_IMAGE_BASE + size + file_path)

        if not ret:
            ret.append(poster_path)
        return ret

    def get_backdrop(self, response_type="str", size="original"):
        ret = []
        if size not in ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280"):
            size = "original"

        backdrop_path = self.result["backdrop_path"]
        if backdrop_path is None or backdrop_path == "":
            backdrop_path = ""
        else:
            # FIX: l'originale concatenava 'get_posterget_poster' invece dell'URL base
            backdrop_path = _IMAGE_BASE + size + backdrop_path

        if response_type == 'str':
            return backdrop_path
        elif not self.result["id"]:
            return []

        if len(self.result['images_backdrops']) == 0:
            self.search_id = str(self.result["id"])
            self.__by_id()

        for i in self.result['images_backdrops']:
            file_path = i['file_path']
            if size != "original":
                if size[1] == 'w' and int(i.get('width', 0)) < int(size[1:]):
                    size = "original"
                elif size[1] == 'h' and int(i.get('height', 0)) < int(size[1:]):
                    size = "original"
            ret.append(_IMAGE_BASE + size + file_path)

        if not ret:
            ret.append(backdrop_path)
        return ret

    def get_season(self, seasonNumber=1, language=''):
        """Ritorna un dict con i dati della stagione richiesta."""
        if not self.result["id"] or self.search_type != "tv":
            return {}

        try:
            seasonNumber = int(seasonNumber)
        except (ValueError, TypeError):
            return {}
        if seasonNumber < 0:
            seasonNumber = 1
        search_language = language if language else self.search_language

        if not self.season.get(seasonNumber, {}) or language:
            # Se non ci sono informazioni sulla stagione richiesta, interroga il sito
            url = ("{}/tv/{}/season/{}?api_key={}&language={}&append_to_response=videos,images,credits,external_ids"
                   "&include_image_language={},en,null").format(host, self.result["id"], seasonNumber, api,
                                                                search_language, search_language)
            searching = "id_Tmdb: " + str(self.result["id"]) + " season: " + str(seasonNumber) + "\nURL: " + url
            logger.debug("[Tmdb.py] Searching " + searching)
            try:
                self.season[seasonNumber] = _to_dict(self.get_json(url))
            except Exception:
                logger.error("Unable to get the season")
                # FIX: l'originale impostava {"episodes": {}} (incoerente e causava KeyError a valle)
                self.season[seasonNumber] = {}

            if "status_code" in self.season[seasonNumber]:
                # Si è verificato un errore
                msg = config.get_localized_string(70496) + searching + config.get_localized_string(70497)
                msg += "\nTmdb error: %s %s" % (self.season[seasonNumber]["status_code"],
                                                self.season[seasonNumber]["status_message"])
                logger.debug(msg)
                self.season[seasonNumber] = {}

        return self.season[seasonNumber]

    def get_collection(self, _id=''):
        ret = {}
        if not _id:
            collection = self.result.get('belongs_to_collection', {})
            if collection:
                _id = collection.get('id')
        if _id:
            translation = {}
            url = ('{}/collection/{}?api_key={}&language={}&append_to_response=images'
                   '&include_image_language={},en,null').format(host, _id, api, self.search_language,
                                                                self.search_language)
            tanslationurl = '{}/collection/{}/translations?api_key={}'.format(host, _id, api)
            info = _to_dict(self.get_json(url))
            for t in _to_dict(self.get_json(tanslationurl)).get('translations', []):
                if t.get('iso_639_1') == self.fallback_language:
                    translation = t.get('data', {})
                    break
            ret['set'] = info.get('name') if info.get('name') else translation.get('name')
            ret['setid'] = _id
            ret['setoverview'] = info.get('overview') if info.get('overview') else translation.get('overview', '')
            posters = [_IMAGE_ORIGINAL + info['poster_path']] if info.get('poster_path') else []
            fanarts = [_IMAGE_ORIGINAL + info['backdrop_path']] if info.get('backdrop_path') else []
            for image in (info.get('images') or {}).get('posters') or []:
                posters.append(_IMAGE_ORIGINAL + image['file_path'])
            for image in (info.get('images') or {}).get('backdrops') or []:
                fanarts.append(_IMAGE_ORIGINAL + image['file_path'])
            ret['setposters'] = posters
            ret['setfanarts'] = fanarts
        return ret

    def get_episode(self, seasonNumber=1, chapter=1):
        """
        Ritorna un dict con i dati dell'episodio (campi episode_*).
        Con chapter <= 0 ritorna un dict vuoto (solo dati stagione, gestiti da get_season).
        """
        if not self.result["id"] or self.search_type != "tv":
            return {}

        try:
            chapter = int(chapter)
            season = int(seasonNumber)
        except (ValueError, TypeError):
            logger.debug("The episode or season number is not valid")
            return {}

        ret_dic = {}
        if chapter > 0:
            url = ("{}/tv/{}/season/{}/episode/{}?api_key={}&language={}&append_to_response=videos,images,credits,"
                   "external_ids&include_image_language={},en,null").format(host, self.result["id"], season, chapter,
                                                                            api, self.search_language,
                                                                            self.search_language)
            episode = _to_dict(self.get_json(url))

            episodeTitle = episode.get("name", '')
            episodeId = episode.get('id', '')
            episodePlot = episode.get('overview', '')
            episodeDate = episode.get('air_date', '')
            episodeImage = episode.get('still_path', '')
            episodeCrew = episode.get('crew', [])
            episodeStars = episode.get('guest_stars', [])
            episodeVoteCount = episode.get('vote_count', 0)
            episodeVoteAverage = episode.get('vote_average', 0)
            externalIds = episode.get('external_ids', {})

            # FIX: l'originale iterava su un dict (.get('stills', {})) invece che su una lista
            posters = []
            for image in (episode.get('images') or {}).get('stills') or []:
                if image.get('file_path'):
                    posters.append(_IMAGE_ORIGINAL + image['file_path'])

            ret_dic["episode_title"] = episodeTitle
            ret_dic["episode_plot"] = episodePlot
            ret_dic["episode_image"] = (_IMAGE_ORIGINAL + episodeImage) if episodeImage else ""
            if episodeDate:
                try:
                    y, m, d = episodeDate.split("-")
                    ret_dic["episode_air_date"] = d + "/" + m + "/" + y
                except ValueError:
                    ret_dic["episode_air_date"] = episodeDate
            else:
                ret_dic["episode_air_date"] = ""
            if posters:
                ret_dic['episode_posters'] = posters

            ret_dic["episode_crew"] = episodeCrew
            if episodeStars:
                ret_dic["episode_actors"] = [[k['name'], k['character'],
                                              _IMAGE_ORIGINAL + '/' + k['profile_path'] if k.get('profile_path') else '',
                                              k['order']] for k in episodeStars]
            ret_dic["episode_vote_count"] = episodeVoteCount
            ret_dic["episode_vote_average"] = episodeVoteAverage
            ret_dic["episode_id"] = episodeId
            ret_dic["episode_imdb_id"] = externalIds.get('imdb_id')
            ret_dic["episode_tvdb_id"] = externalIds.get('tvdb_id')

        return ret_dic

    def get_list_episodes(self):
        # FIX: ora passa da Tmdb.get_json (cache/retry) invece di requests nudo
        url = '{}/tv/{}?api_key={}&language={}'.format(host, self.search_id, api, self.search_language)
        results = _to_dict(Tmdb.get_json(url)).get('seasons', [])
        seasons = []
        if results and 'Error' not in results:
            for season in results:
                url = '{}/tv/{}/season/{}?api_key={}&language={}'.format(host, self.search_id,
                                                                         season['season_number'], api,
                                                                         self.search_language)
                try:
                    start_from = _to_dict(Tmdb.get_json(url))['episodes'][0]['episode_number']
                except Exception:
                    start_from = 1
                seasons.append({'season_number': season['season_number'],
                                'episode_count': season['episode_count'],
                                'start_from': start_from})
        return seasons

    def get_videos(self):
        """Lista ordinata (lingua/risoluzione/tipo) di trailer/teaser/clip di YouTube."""
        ret = []

        if self.result['id']:
            if self.result['videos']:
                self.result["videos"] = self.result["videos"]['results']
            else:
                self.result["videos"] = []
                # Prima ricerca video nella lingua di ricerca
                url = "{}/{}/{}/videos?api_key={}&language={}".format(host, self.search_type, self.result['id'], api,
                                                                      self.search_language)
                dict_videos = _to_dict(self.get_json(url))
                if dict_videos.get('results'):
                    dict_videos['results'] = sorted(dict_videos['results'], key=lambda x: (x['type'], x['size']))
                    self.result["videos"] = dict_videos['results']

            # Se la lingua di ricerca non è inglese, seconda ricerca video in inglese
            if self.search_language != 'en':
                url = "{}/{}/{}/videos?api_key={}".format(host, self.search_type, self.result['id'], api)
                dict_videos = _to_dict(self.get_json(url))
                if dict_videos.get('results'):
                    dict_videos['results'] = sorted(dict_videos['results'], key=lambda x: (x['type'], x['size']))
                    self.result["videos"].extend(dict_videos['results'])

            for i in self.result['videos']:
                if i['site'] == "YouTube":
                    ret.append({'name': i['name'],
                                'url': "plugin://plugin.video.youtube/play/?video_id={}".format(i['key']),
                                'size': str(i['size']),
                                'type': i['type'],
                                'language': i['iso_639_1']})
        return ret

    def get_infoLabels(self, infoLabels=None, origen=None):
        """
        :param infoLabels: informazioni extra di partenza del film/serie/stagione/episodio
        :param origen: dizionario sorgente, di default self.result
        :return: InfoLabels aggiornati con i dati ottenuti
        """
        if infoLabels:
            ret_infoLabels = InfoLabels(infoLabels)
        else:
            ret_infoLabels = InfoLabels()
        # Inizio liste
        l_country = [i.strip() for i in ret_infoLabels['country'].split(',') if ret_infoLabels['country']]
        l_director = [i.strip() for i in ret_infoLabels['director'].split(',') if ret_infoLabels['director']]
        l_director_image = ret_infoLabels.get('director_image', [])
        l_director_id = ret_infoLabels.get('director_id', [])
        l_writer = [i.strip() for i in ret_infoLabels['writer'].split(',') if ret_infoLabels['writer']]
        l_writer_image = ret_infoLabels.get('writer_image', [])
        l_writer_id = ret_infoLabels.get('writer_id', [])
        l_castandrole = ret_infoLabels.get('castandrole', [])

        if not origen:
            origen = self.result

        if 'credits' in list(origen.keys()):
            dic_origen_credits = origen['credits']
            origen['credits_cast'] = dic_origen_credits.get('cast', [])
            origen['credits_crew'] = dic_origen_credits.get('crew', [])
            del origen['credits']

        if 'images' in list(origen.keys()):
            dic_origen_images = origen['images']
            origen['posters'] = dic_origen_images.get('posters', [])
            origen['fanarts'] = dic_origen_images.get('backdrops', [])
            del origen['images']

        items = list(origen.items())

        # Informazioni stagione / episodio
        if ret_infoLabels['season'] and self.season.get(ret_infoLabels['season']):
            # Se ci sono dati caricati per la stagione indicata
            episodio = -1
            if ret_infoLabels['episode']:
                episodio = ret_infoLabels['episode']
            items.extend(list(self.get_episode(ret_infoLabels['season'], episodio).items()))

        for k, v in items:
            if not v:
                continue
            elif isinstance(v, str):
                v = _RE_NEWLINES.sub("", v)
                if v == "None":
                    continue

            if k == 'media_type':
                ret_infoLabels['mediatype'] = v if v in ['tv', 'tvshow'] else 'movie'

            elif k == 'overview':
                ret_infoLabels['plot'] = v

            elif k == 'runtime':                                # Durata per i film
                ret_infoLabels['duration'] = int(v) * 60

            elif k == 'episode_run_time':                       # Durata per gli episodi
                try:
                    for v_alt in v:                             # Arriva come lista (?!)
                        ret_infoLabels['duration'] = int(v_alt) * 60
                except Exception:
                    pass

            elif k == 'release_date':
                ret_infoLabels['year'] = int(v[:4])
                ret_infoLabels['premiered'] = v

            elif k == 'first_air_date':
                ret_infoLabels['year'] = int(v[:4])
                ret_infoLabels['aired'] = v
                ret_infoLabels['premiered'] = ret_infoLabels['aired']

            elif k == 'original_title' or k == 'original_name':
                ret_infoLabels['originaltitle'] = v

            elif k == 'vote_average':
                ret_infoLabels['rating'] = float(v)

            elif k == 'vote_count':
                ret_infoLabels['votes'] = v

            elif k in ['poster_path', 'profile_path']:
                ret_infoLabels['thumbnail'] = _IMAGE_ORIGINAL + v

            elif k == 'backdrop_path':
                ret_infoLabels['fanart'] = _IMAGE_ORIGINAL + v

            elif k == 'id':
                ret_infoLabels['tmdb_id'] = v

            elif k == 'imdb_id':
                ret_infoLabels['imdb_id'] = v

            elif k == 'external_ids':
                if 'tvdb_id' in v:
                    ret_infoLabels['tvdb_id'] = v['tvdb_id']
                if 'imdb_id' in v:
                    ret_infoLabels['imdb_id'] = v['imdb_id']

            elif k in ['genres', "genre_ids", "genre"]:
                ret_infoLabels['genre'] = self.get_genres(origen)

            elif k == 'name' or k == 'title':
                ret_infoLabels['title'] = v

            elif k == 'tagline':
                ret_infoLabels['tagline'] = v

            elif k == 'production_companies':
                ret_infoLabels['studio'] = ", ".join(i['name'] for i in v)

            elif k == 'credits_cast' or k == 'season_cast' or k == 'episode_guest_stars':
                dic_aux = dict((name, [character, thumb, order, id])
                               for (name, character, thumb, order, id) in l_castandrole)
                l_castandrole.extend([(p['name'], p.get('character', '') or p.get('character_name', ''),
                                       _IMAGE_ORIGINAL + p.get('profile_path', '') if p.get('profile_path', '') else '',
                                       p.get('order'), p.get('id'))
                                      for p in v if 'name' in p and p['name'] not in list(dic_aux.keys())])

            elif k == 'videos':
                if not isinstance(v, list):
                    v = v.get('results', [])
                for i in v:
                    if i.get("site", "") == "YouTube":
                        # FIX: l'originale usava v[0]["key"] anche se il primo video non era YouTube
                        ret_infoLabels['trailer'] = "plugin://plugin.video.youtube/play/?video_id=" + i["key"]
                        break

            elif k == 'posters':
                ret_infoLabels['posters'] = [_IMAGE_ORIGINAL + p["file_path"] for p in v]

            elif k == 'fanarts':
                ret_infoLabels['fanarts'] = [_IMAGE_ORIGINAL + p["file_path"] for p in v]

            elif k == 'belongs_to_collection':
                c = Tmdb.get_collection(self, v.get('id', ''))
                # FIX: rinominato kk/vv (l'originale ombreggiava k, v del loop esterno)
                for kk, vv in c.items():
                    ret_infoLabels[kk] = vv

            elif k == 'production_countries' or k == 'origin_country':
                if isinstance(v, str):
                    l_country = list(set(l_country + v.split(',')))
                elif isinstance(v, list) and len(v) > 0:
                    if isinstance(v[0], str):
                        l_country = list(set(l_country + v))
                    elif isinstance(v[0], dict):
                        # {'iso_3166_1': 'FR', 'name':'France'}
                        for i in v:
                            if 'name' in i:
                                l_country = list(set(l_country + [i['name']]))

            elif k == 'credits_crew' or k == 'episode_crew' or k == 'season_crew':
                for crew in v:
                    # FIX: l'originale usava crew['job'] senza guard -> KeyError
                    job = (crew.get('job') or '').lower()
                    if job == 'director':
                        l_director = list(set(l_director + [crew['name']]))
                        l_director_image += [_IMAGE_ORIGINAL + crew['profile_path'] if crew.get('profile_path') else '']
                        l_director_id += [crew['id']]
                    elif job in ('screenplay', 'writer'):
                        l_writer = list(set(l_writer + [crew['name']]))
                        l_writer_image += [_IMAGE_ORIGINAL + crew['profile_path'] if crew.get('profile_path') else '']
                        l_writer_id += [crew['id']]

            elif k == 'created_by':
                for crew in v:
                    l_writer = list(set(l_writer + [crew['name']]))

            elif isinstance(v, str) or isinstance(v, int) or isinstance(v, float):
                ret_infoLabels[k] = v

            else:
                # Attributi non aggiunti
                pass

        # Ordina le liste e convertile in str se necessario
        if l_castandrole:
            ret_infoLabels['castandrole'] = sorted(l_castandrole, key=lambda tup: tup[0])
        if l_country:
            ret_infoLabels['country'] = ', '.join(sorted(l_country))
        if l_director:
            ret_infoLabels['director'] = ', '.join(l_director)
            ret_infoLabels['director_image'] = l_director_image
            ret_infoLabels['director_id'] = l_director_id
        if l_writer:
            ret_infoLabels['writer'] = ', '.join(l_writer)
            ret_infoLabels['writer_image'] = l_writer_image
            ret_infoLabels['writer_id'] = l_writer_id

        return ret_infoLabels


# -----------------------------------------------------------------------------------------------
# Funzioni a livello modulo
# -----------------------------------------------------------------------------------------------
def get_season_dic(season):
    ret_dic = dict()
    # Ottiene i dati per questa stagione
    seasonTitle = season.get("name", '')
    seasonPlot = season.get("overview", '')
    seasonId = season.get("id", '')
    seasonEpisodes = len(season.get("episodes", []))
    seasonDate = season.get("air_date", '')
    seasonPoster = season.get('poster_path', '')
    seasonCredits = season.get('credits', {})
    seasonPosters = season.get('images', {}).get('posters', {})
    seasonFanarts = season.get('images', {}).get('backdrops', {})
    seasonTrailers = season.get('videos', {}).get('results', [])

    ret_dic["season_title"] = seasonTitle
    ret_dic["season_plot"] = seasonPlot
    ret_dic["season_id"] = seasonId
    ret_dic["season_episodes_number"] = seasonEpisodes

    if seasonDate:
        try:
            y, m, d = seasonDate.split("-")
            ret_dic["season_air_date"] = d + "/" + m + "/" + y
        except ValueError:
            ret_dic["season_air_date"] = seasonDate
    else:
        ret_dic["season_air_date"] = ''
    if seasonPoster:
        ret_dic["season_poster"] = _IMAGE_ORIGINAL + seasonPoster
    else:
        ret_dic["season_poster"] = ''

    if seasonPosters:
        ret_dic['season_posters'] = [_IMAGE_ORIGINAL + p["file_path"] for p in seasonPosters]
    if seasonFanarts:
        ret_dic['season_fanarts'] = [_IMAGE_ORIGINAL + p["file_path"] for p in seasonFanarts]
    if seasonTrailers:
        ret_dic['season_trailer'] = []
        # FIX: l'originale usava seasonTrailers[0]["key"] anche se il primo non era YouTube
        for i in seasonTrailers:
            if i.get("site", "") == "YouTube":
                ret_dic['season_trailer'] = "plugin://plugin.video.youtube/play/?video_id=" + i["key"]
                break

    dic_aux = seasonCredits if seasonCredits else {}
    ret_dic["season_cast"] = dic_aux.get('cast', [])
    ret_dic["season_crew"] = dic_aux.get('crew', [])
    return ret_dic


def parse_fallback_info(info, fallbackInfo):
    info_dict = {}
    for key, value in info.items():
        if not value:
            value = fallbackInfo[key]
        info_dict[key] = value
    episodes = info_dict['episodes']

    episodes_list = []
    for i, episode in enumerate(episodes):
        episode_dict = {}
        for key, value in episode.items():
            if not value:
                value = fallbackInfo['episodes'][i][key]
            episode_dict[key] = value
        episodes_list.append(episode_dict)

    info_dict['episodes'] = episodes_list
    return info_dict
