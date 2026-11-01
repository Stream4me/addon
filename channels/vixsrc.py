# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per VixSrc: elenco dei titoli di VixSrc, copertine e dati da TMDB
# ------------------------------------------------------------

import json
import os
import time

from core import support, httptools, tmdb
from core.item import Item
from platformcode import config, logger

host = support.config.get_channel_url()
PAGE = 20
DURATA_CACHE = 12 * 3600


@support.menu
def mainlist(item):
    film = ['',
            ('Di tendenza oggi', ['', 'peliculas', 'trending/movie/day', 'movie']),
            ('Di tendenza questa settimana', ['', 'peliculas', 'trending/movie/week', 'movie']),
            ('Popolari', ['', 'peliculas', 'movie/popular', 'movie']),
            ('Più votati', ['', 'peliculas', 'movie/top_rated', 'movie']),
            ('Ultime uscite', ['', 'peliculas', 'discover/movie?sort_by=primary_release_date.desc&primary_release_date.lte={oggi}&vote_count.gte=5', 'movie']),
            ('Per piattaforma', ['', 'piattaforme', 'movie', 'movie']),
            ('Generi', ['', 'generi', 'movie', 'movie']),
            ('Per anno', ['', 'anni', 'movie', 'movie']),
            ('Per lingua', ['', 'lingue', 'movie', 'movie'])]
    tvshow = ['',
              ('Di tendenza oggi', ['', 'peliculas', 'trending/tv/day', 'tvshow']),
              ('Di tendenza questa settimana', ['', 'peliculas', 'trending/tv/week', 'tvshow']),
              ('Popolari', ['', 'peliculas', 'tv/popular', 'tvshow']),
              ('Più votate', ['', 'peliculas', 'tv/top_rated', 'tvshow']),
              ('Ultime uscite', ['', 'peliculas', 'discover/tv?sort_by=first_air_date.desc&first_air_date.lte={oggi}&vote_count.gte=5', 'tvshow']),
              ('Per piattaforma', ['', 'piattaforme', 'tv', 'tvshow']),
              ('Generi', ['', 'generi', 'tv', 'tvshow']),
              ('Per anno', ['', 'anni', 'tv', 'tvshow']),
              ('Per lingua', ['', 'lingue', 'tv', 'tvshow'])]
    search = ''
    return locals()


def _scarica(tipo):
    # elenco dei titoli di VixSrc (solo identificativi), tenuto in un file temporaneo per qualche ora
    nome = os.path.join(config.get_temp_file(''), 'vixsrc_%s.json' % tipo)
    try:
        if os.path.isfile(nome) and time.time() - os.path.getmtime(nome) < DURATA_CACHE:
            with open(nome, 'r') as f:
                return json.load(f)
    except Exception:
        logger.error('vixsrc: cache non letta')
    dati = json.loads(httptools.downloadpage('%s/api/list/%s?lang=it' % (host, tipo)).data)
    try:
        with open(nome, 'w') as f:
            json.dump(dati, f)
    except Exception:
        logger.error('vixsrc: cache non scritta')
    return dati


def _id_validi(tipo):
    return [x['tmdb_id'] for x in _scarica(tipo) if x.get('tmdb_id')]


def _titoli(ids, tipo, item):
    """Elementi con solo l'identificativo TMDB: titolo, trama e copertina arrivano da TMDB."""
    itemlist = []
    for i in ids:
        if tipo == 'movie':
            itemlist.append(Item(channel=item.channel, action='findvideos', contentType='movie', title=str(i),
                                 fulltitle=str(i), show=str(i), contentTitle=str(i),
                                 infoLabels={'tmdb_id': str(i)}, url='%s/movie/%s' % (host, i)))
        else:
            itemlist.append(Item(channel=item.channel, action='episodios', contentType='tvshow', title=str(i),
                                 fulltitle=str(i), show=str(i), contentSerieName=str(i),
                                 infoLabels={'tmdb_id': str(i)}, url='%s/tv/%s' % (host, i)))
    try:
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    except Exception:
        logger.error('vixsrc: TMDB non disponibile')
    out = []
    for it in itemlist:
        info = it.infoLabels
        nome = info.get('title') or info.get('tvshowtitle') or info.get('originaltitle')
        if not nome or nome == it.fulltitle:
            continue  # titolo non trovato su TMDB: senza titolo non si mostra
        it.title = support.typo(nome, 'bold')
        it.fulltitle = it.show = nome
        if tipo == 'movie':
            it.contentTitle = nome
        else:
            it.contentSerieName = nome
        out.append(it)
    return out


def peliculas(item):
    logger.debug()
    if item.args and not item.ids:
        # sezioni TMDB (tendenze, piattaforme, generi): la lista resta di tipo film o serie TV per la vista di Kodi
        return sezione(item)
    tipo = 'movie' if item.contentType == 'movie' else 'tv'
    pagina = int(item.page or 0)
    if item.ids:
        ids = item.ids
    else:
        ids = _id_validi(tipo)
    parte = ids[pagina * PAGE:(pagina + 1) * PAGE]
    itemlist = _titoli(parte, tipo, item)
    if len(ids) > (pagina + 1) * PAGE:
        itemlist.append(item.clone(title=support.typo(config.get_localized_string(30992), 'color kod bold'),
                                   action='peliculas', page=pagina + 1, thumbnail=support.thumb()))
    return itemlist


PIATTAFORME = [('Amazon Prime Video', 119), ('Apple TV', 2), ('Apple TV+', 350), ('Chili', 40), ('Discovery+', 524),
               ('Disney+', 337), ('Google Play Film', 3), ('Mediaset Infinity', 359), ('MUBI', 11), ('Netflix', 8),
               ('NOW', 39), ('Paramount+', 531), ('Plex', 538), ('Pluto TV', 300), ('RaiPlay', 222),
               ('Rakuten TV', 35), ('Sky Go', 29), ('TIMVISION', 109)]


def _tmdb(percorso):
    sep = '&' if '?' in percorso else '?'
    return '%s/%s%sapi_key=%s&language=%s' % (tmdb.host, percorso, sep, tmdb.api, tmdb.def_lang)


def sezione(item):
    # elenco TMDB (tendenze, popolari, piattaforme, generi) tenuto solo per i titoli presenti su VixSrc, nell'ordine di TMDB
    logger.debug()
    percorso = (item.args or 'trending/movie/day').replace('{oggi}', time.strftime('%Y-%m-%d'))
    tipo = 'movie' if 'movie' in percorso.split('?')[0] else 'tv'
    validi = set(_id_validi(tipo))
    ids = []
    for pagina in range(1, 9):
        try:
            dati = tmdb.Tmdb.get_json('%s&page=%d' % (_tmdb(percorso), pagina))
        except Exception:
            logger.error('vixsrc: elenco TMDB non disponibile')
            break
        risultati = (dati or {}).get('results', [])
        for r in risultati:
            if r.get('id') in validi and r['id'] not in ids:
                ids.append(r['id'])
        if not risultati or len(ids) >= 60:
            break
    if not ids:
        return []
    return peliculas(item.clone(ids=ids, page=0, contentType='movie' if tipo == 'movie' else 'tvshow'))


def piattaforme(item):
    logger.debug()
    tipo = item.args or 'movie'
    itemlist = []
    for nome, codice in PIATTAFORME:
        percorso = 'discover/%s?watch_region=IT&with_watch_providers=%d&sort_by=popularity.desc' % (tipo, codice)
        itemlist.append(item.clone(title=support.typo(nome, 'bold'), action='peliculas', args=percorso,
                                   thumbnail=support.thumb(), folder=True))
    return itemlist


def generi(item):
    logger.debug()
    tipo = item.args or 'movie'
    itemlist = []
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('genre/%s/list' % tipo))
    except Exception:
        logger.error('vixsrc: generi TMDB non disponibili')
        return itemlist
    for g in sorted((dati or {}).get('genres', []), key=lambda x: x.get('name', '')):
        percorso = 'discover/%s?with_genres=%s&sort_by=popularity.desc' % (tipo, g['id'])
        itemlist.append(item.clone(title=support.typo(g['name'], 'bold'), action='peliculas', args=percorso,
                                   thumbnail=support.thumb(), folder=True))
    return itemlist


LINGUE = [('Italiano', 'it'), ('Inglese', 'en'), ('Giapponese', 'ja'), ('Coreano', 'ko'), ('Francese', 'fr'),
          ('Spagnolo', 'es'), ('Tedesco', 'de'), ('Cinese', 'zh'), ('Hindi', 'hi'), ('Turco', 'tr'),
          ('Portoghese', 'pt'), ('Russo', 'ru'), ('Svedese', 'sv'), ('Danese', 'da'), ('Polacco', 'pl')]


def anni(item):
    logger.debug()
    tipo = item.args or 'movie'
    campo = 'primary_release_year' if tipo == 'movie' else 'first_air_date_year'
    itemlist = []
    for anno in range(int(time.strftime('%Y')), 2005, -1):
        percorso = 'discover/%s?%s=%d&sort_by=popularity.desc' % (tipo, campo, anno)
        itemlist.append(item.clone(title=support.typo(str(anno), 'bold'), action='peliculas', args=percorso,
                                   thumbnail=support.thumb(), folder=True))
    return itemlist


def lingue(item):
    logger.debug()
    tipo = item.args or 'movie'
    itemlist = []
    for nome, codice in LINGUE:
        percorso = 'discover/%s?with_original_language=%s&sort_by=popularity.desc' % (tipo, codice)
        itemlist.append(item.clone(title=support.typo(nome, 'bold'), action='peliculas', args=percorso,
                                   thumbnail=support.thumb(), folder=True))
    return itemlist


def search(item, text):
    logger.debug(text)
    try:
        trovati = []
        for tipo, tm in (('movie', 'movie'), ('tv', 'tv')):
            if item.contentType in ('movie', 'tvshow') and ('movie' if item.contentType == 'movie' else 'tv') != tipo:
                continue
            validi = set(_id_validi(tipo))
            ricerca = tmdb.Tmdb(searched_text=text, search_type=tm)
            for r in ricerca.results or []:
                if r.get('id') in validi:
                    trovati.append((tipo, r['id']))
        itemlist = []
        for tipo in ('movie', 'tv'):
            ids = [i for t, i in trovati if t == tipo]
            if ids:
                itemlist += _titoli(ids, tipo, item)
        return itemlist
    except Exception:
        import sys
        for line in sys.exc_info():
            logger.error('%s' % line)
        return []


def episodios(item):
    logger.debug()
    itemlist = []
    id_serie = item.infoLabels.get('tmdb_id') or item.url.rstrip('/').split('/')[-1]
    nome = item.fulltitle or item.contentSerieName
    # episodi disponibili su VixSrc: stagione -> numeri
    disponibili = {}
    try:
        for x in _scarica('episode'):
            if str(x.get('tmdb_id')) == str(id_serie):
                disponibili.setdefault(x['s'], set()).add(x['e'])
    except Exception:
        logger.error('vixsrc: elenco episodi non disponibile')
    otmdb = tmdb.Tmdb(id_Tmdb=id_serie, search_type='tv')
    if disponibili:
        numeri = sorted(disponibili)
    else:
        numeri = list(range(1, int((otmdb.result or {}).get('number_of_seasons') or 1) + 1))
    for n in numeri:
        dati = otmdb.get_season(n) or {}
        da_tmdb = dict((e.get('episode_number'), e) for e in (dati.get('episodes') or []))
        for e in (sorted(disponibili[n]) if disponibili else sorted(da_tmdb)):
            d = da_tmdb.get(e) or {}
            titolo = d.get('name') or ''
            img = ('https://image.tmdb.org/t/p/original' + d['still_path']) if d.get('still_path') else item.thumbnail
            itemlist.append(item.clone(title=support.typo('%dx%02d' % (n, e) + (' - ' + titolo if titolo else ''), 'bold'),
                                       action='findvideos', contentType='episode', contentSeason=n,
                                       contentEpisodeNumber=e, season=n, episode=e, thumbnail=img,
                                       fulltitle=nome, show=nome, contentSerieName=nome,
                                       plot=d.get('overview') or item.plot,
                                       url='%s/tv/%s/%d/%d' % (host, id_serie, n, e)))
    support.videolibrary(itemlist, item)
    return itemlist


def findvideos(item):
    return support.server(item, data=item.url, referer=False)


def play(item):
    # avvio diretto da un player esterno (TMDb Helper): l'indirizzo si costruisce dall'ID TMDb
    if item.direct:
        from core import db
        db['player']['itemlist'] = []
        db.close()
    if not (item.url or '').startswith('http'):
        tmdb_id = item.tmdb or item.infoLabels.get('tmdb_id') or item.infoLabels.get('tmdb_id_show')
        if item.season and item.episode:
            item.url = '%s/tv/%s/%s/%s' % (host, tmdb_id, item.season, item.episode)
        else:
            item.url = '%s/movie/%s' % (host, tmdb_id)
    return [item]
