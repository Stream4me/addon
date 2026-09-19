# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'casacinema'
#
# Rev: 1.2
# Update: 2026-09-19
#
# Flusso:
#   - film    : peliculas -> findvideos -> play (token vidxgo da IMDb/TMDB)
#   - serie   : peliculas -> episodios (PIANO A) -> findvideos -> play
#   - libreria: "Aggiungi alla videoteca" in fondo alla lista episodi
#
# Patch vidxgo (identica a guardaserieicu 1.4):
#   - probe() di servers/vidxgo.py appeso ANCHE a TLS caldo -> RIMOSSO.
#   - Lista episodi via get_embed_page() del server (sessione TLS-rotata,
#     la stessa via del playback) + discovery stagioni /{token}/{s}/1.
#   - check() rimosso: le serie arrivano gia' DIRETTE a episodios (typing
#     per URL in itemlistHook); la distinzione serie/film in findvideos
#     avviene col parse della pagina embed, senza probe().
#   - Titoli episodi da TMDB (lingua it); degrada a '1x01' se non mappata.
# ------------------------------------------------------------

from core import support, httptools
from platformcode import logger
import re, sys, json, threading, traceback

host = support.config.get_channel_url()
headers = [['Referer', host]]

FETCH_TIMEOUT = 45
MAX_SEASON = 30
PAIRS_CACHE = {}                # token -> [(s, e), ...] (solo sessione)


@support.menu
def mainlist(item):

    top = [('Generi', ['', 'genres'])]
    film = ['/film']

    tvshow = ['/serie-tv',
          ('Miniserie ', ['/miniserie-tv', 'peliculas', ''])]

    search = ''

    return locals()


@support.scrape
def genres(item):
    action = 'peliculas'
    blacklist = ['Serie TV', 'Miniserie TV']
    patronMenu = r'<li><a href="(?P<url>[^"]+)">(?P<title>[^<>]+)</a></li>'
    patronBlock = r'<a href="#">Categorie</a>(?P<block>.*?)<a href="#"'
    return locals()


def search(item, text):
    item.url = "{}/?{}".format(host, support.urlencode({'story': text, 'do': 'search', 'subaction': 'search'}))
    try:
        item.args = 'search'
        return peliculas(item)

    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


@support.scrape
def peliculas(item):
    action = 'findvideos'        # era 'check': rimane solo la via senza probe
    patron = r'<div class="posts".*?<a href="(?P<url>[^"]+)[^>]+>[^>]+>[^>]+>(?P<title>[^\(\[<]+)(?:\[(?P<quality1>HD)\])?'
    patronNext = r'<a href="([^"]+)"\s*>Pagina'

    # il listato corrente: se e' serie-tv/miniserie-tv, TUTTI gli item sono serie
    # (le pagine dettaglio stanno sotto /gratis/, quindi l'URL del listato e'
    # l'unica fonte affidabile per il typing)
    src = (getattr(item, 'url', '') or '') + ' '

    def itemHook(item):
        if item.quality1:
            item.quality = item.quality1
            item.title += support.typo(item.quality, '_ [] color std')
        if item.lang2:
            item.contentLanguage = item.lang2
            item.title += support.typo(item.lang2, '_ [] color std')
        return item

    def itemlistHook(itemlist):
        out = []
        for it in itemlist:
            is_series = ('/serie-tv' in src or '/miniserie-tv' in src
                         or '/serie-tv/' in (it.url or '')
                         or '/miniserie-tv/' in (it.url or ''))
            if is_series:
                it.contentType = 'tvshow'
                it.contentTitle = (it.fulltitle or it.title).strip()
                it.fulltitle = it.contentTitle
                it.action = 'episodios'          # invocazione diretta dal launcher
                it.context = "['addToLibrary']"  # voce anche nel context menu
            out.append(it)
        return out

    return locals()


# ------------------------- helper vidxgo -------------------------

def _token_from_data(data):
    """Token vidxgo dal JS della pagina casa-cinema: imdb prima, tmdb come fallback."""
    m = re.search(r"imdb\s*=\s*'(tt\d+)'", data, re.I)
    if m:
        return m.group(1)[2:]
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data)
    return ('tm' + m.group(1)) if m else None


def _get_embed(url):
    """get_embed_page del server: sessione TLS-rotata, la via del playback.
    L'unica fetch verso v.vidxgo.co che funziona."""
    result = {}

    def worker():
        try:
            from servers import vidxgo as srv_v
            result['page'] = srv_v.get_embed_page(url, referer=host + '/') or ''
        except Exception:
            logger.error('get_embed_page EXCEPTION su ' + url)
            logger.error(traceback.format_exc())
            result['page'] = ''
        result['done'] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(FETCH_TIMEOUT)
    if not result.get('done'):
        logger.error('get_embed_page TIMEOUT ({}s) su {}'.format(FETCH_TIMEOUT, url))
        return ''
    page = result.get('page', '')
    if page:
        logger.info('get_embed_page OK: {} bytes'.format(len(page)))
    return page


# ------------------------- titoli episodi (TMDB) -------------------------
TMDB_API = 'https://api.themoviedb.org/3'
TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228'   # la stessa chiave gia' usata dal fork
TMDB_LANG = 'it'

TMDB_ID_CACHE = {}      # token vidxgo -> tmdb id (o False)
SEASON_TITLES = {}      # (tmdb_id, stagione) -> {n_episodio: titolo}


def _tmdb_id_from_token(token):
    """TMDB id della serie: diretto per token 'tmN',
    lookup find() per token IMDb ('20516590' -> 'tt20516590')."""
    if token in TMDB_ID_CACHE:
        return TMDB_ID_CACHE[token]
    tmdb_id = False
    try:
        if token.startswith('tm'):
            tmdb_id = int(token[2:])
        else:
            url = '%s/find/tt%s?api_key=%s&external_source=imdb_id&language=%s' % (
                TMDB_API, token, TMDB_KEY, TMDB_LANG)
            j = json.loads(httptools.downloadpage(url).data or '{}')
            if j.get('tv_results'):
                tmdb_id = j['tv_results'][0]['id']
    except Exception:
        logger.error(traceback.format_exc())
    TMDB_ID_CACHE[token] = tmdb_id
    logger.info('tmdb id per token %s -> %s' % (token, tmdb_id))
    return tmdb_id


def _season_titles(tmdb_id, s):
    """{numero_episodio: titolo} della stagione s (cache di sessione)."""
    key = (tmdb_id, s)
    if key in SEASON_TITLES:
        return SEASON_TITLES[key]
    out = {}
    try:
        url = '%s/tv/%d/season/%d?api_key=%s&language=%s' % (
            TMDB_API, tmdb_id, s, TMDB_KEY, TMDB_LANG)
        for ep in json.loads(httptools.downloadpage(url).data or '{}').get('episodes', []):
            n, name = ep.get('episode_number'), (ep.get('name') or '').strip()
            # scarta i segnaposto "Episodio 3" / "Episode 3": sono solo rumore
            if n is not None and name and not re.match(r'^(episodio|episode)\s*\d+$', name, re.I):
                out[int(n)] = name
    except Exception:
        logger.error(traceback.format_exc())
    SEASON_TITLES[key] = out
    return out


def _episode_titles(token, pairs):
    """{(s, e): titolo} da TMDB; {} se la serie non e' mappata."""
    titles = {}
    tmdb_id = _tmdb_id_from_token(token)
    if not tmdb_id:
        return titles
    for s in sorted({s for s, _ in pairs}):
        for n, name in _season_titles(tmdb_id, s).items():
            titles[(s, n)] = name
    logger.info('titoli TMDB: {} su {} episodi'.format(len(titles), len(pairs)))
    return titles


# ------------------------- parsing episodi -------------------------

def _pairs_from_site_html(data):
    """Pattern italiani, se mai comparissero nell'HTML del sito."""
    pairs = {(int(a), int(b)) for a, b in
             re.findall(r'data-episode="(\d+)-(\d+)"', data)}
    if pairs:
        return sorted(pairs)
    seasons = sorted({int(x) for x in
                      re.findall(r'Stagione\s*(?:<!--[^>]*-->\s*)?(\d+)', data)})
    eps = sorted({int(x) for x in
                  re.findall(r'Episodio\s*(?:<!--[^>]*-->\s*)?(\d+)', data)})
    if seasons and eps and len(seasons) <= 30 and len(eps) <= 100:
        return [(s, e) for s in seasons for e in eps]
    return []


def _parse_page_pairs(page, token, quiet=False):
    """Estrae (s, e) da una pagina player. [] se formato ignoto."""
    pairs = set()
    # JSON "season":N,"episodes":[...]
    for s, eps_s in re.findall(r'"season"\s*:\s*(\d+)\s*,\s*"episodes"\s*:\s*\[([^\]]*)\]', page):
        pairs.update((int(s), int(e)) for e in re.findall(r'\d+', eps_s))
    # JSON piatto
    if not pairs:
        pairs = {(int(a), int(b)) for a, b in
                 re.findall(r'"season"\s*:\s*(\d+)\s*,\s*"episode"\s*:\s*(\d+)', page)}
    # path /token/s/e
    if not pairs:
        pairs = {(int(a), int(b)) for a, b in
                 re.findall(r'/' + re.escape(token) + r'/(\d+)/(\d+)', page)}
    # pattern del sito
    if not pairs:
        pairs = set(_pairs_from_site_html(page))
    # oggetto stagioni {"1":[...],"2":[...]}
    if not pairs:
        m = re.search(
            r'\{"\d{1,2}"\s*:\s*\[[\d\s,]+\](?:\s*,\s*"\d{1,2}"\s*:\s*\[[\d\s,]+\])*\}',
            page)
        if m:
            try:
                obj = json.loads(m.group(0))
                for s, eps in obj.items():
                    pairs.update((int(s), int(e)) for e in eps)
            except Exception:
                pass

    if pairs:
        return sorted(pairs)

    if not quiet:
        logger.error('pagina player: formato episodi non riconosciuto, excerpt:')
        mm = re.search(r'season|episode', page, re.I)
        start = max(0, mm.start() - 200) if mm else 0
        logger.error(page[start:start + 2000].replace('\n', ' '))
    return []


def _pairs_via_server(token, quiet=False):
    """PIANO A: pagina embed via TLS del server + DISCOVERY stagioni.
    1) /{token} -> parse (di norma la stagione 1)
    2) finche' esiste, /{token}/{s+1}/1 -> parse della stagione successiva
    Nessuna coppia -> probabilmente film ([]), findvideos fa il play nudo."""
    page = _get_embed('https://v.vidxgo.co/' + token)
    if not page:
        return []
    if 'Access Denied' in page[:3000]:
        logger.error('server: pagina embed -> 403 applicativo')
        return []

    pairs = set(_parse_page_pairs(page, token, quiet=quiet))
    seasons = sorted({s for s, _ in pairs})
    logger.info('parse pagina 1: {} episodi, stagioni {}'.format(len(pairs), seasons))

    if seasons and seasons[-1] < MAX_SEASON:
        s = seasons[-1]
        while s < MAX_SEASON:
            s += 1
            p2 = _get_embed('https://v.vidxgo.co/%s/%d/1' % (token, s))
            if not p2 or 'Access Denied' in p2[:3000]:
                break
            if ('/%s/%d/' % (token, s)) not in p2:
                logger.info('discovery: stagione {} assente, mi fermo'.format(s))
                break
            new = {(ps, pe) for ps, pe in
                   _parse_page_pairs(p2, token, quiet=True) if ps == s}
            if not new:
                break
            logger.info('discovery: stagione {} -> {} episodi'.format(s, len(new)))
            pairs |= new

    out = sorted(pairs)
    if out:
        logger.info('PIANO A: {} episodi, {} stagioni'.format(
            len(out), len({s for s, _ in out})))
    return out


def _episode_list(item, pairs, token=None):
    """Directory episodi: action='findvideos' (non 'play', altrimenti il
    launcher fa autoplay/popup invece di mostrare la pagina)."""
    # titoli TMDB: un problema qui non deve mai cancellare la lista
    titles = {}
    if token:
        try:
            titles = _episode_titles(token, pairs)
        except Exception:
            logger.error(traceback.format_exc())

    itemlist = []
    for s, e in pairs:
        it = item.clone(action='findvideos')
        it.contentType = 'episode'
        it.contentSeason = s
        it.contentEpisode = e
        it.contentTitle = item.contentTitle or item.fulltitle
        it.title = '%dx%02d' % (s, e)
        t = titles.get((s, e))
        if t:
            it.title += ' - ' + t
        itemlist.append(it)

    # "Aggiungi alla videoteca" in fondo: il launcher di questo fork non
    # appende mai la voce da solo; il canale la fornisce e ne espone l'azione
    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = item.contentTitle or item.fulltitle
    cl.fulltitle = cl.contentTitle
    cl.show = cl.contentTitle                    # nome cartella in videoteca
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    itemlist.append(cl)
    return itemlist


# ------------------------- azioni -------------------------

def episodios(item):
    """Enumerazione episodi: PIANO A (get_embed_page + discovery stagioni),
    senza probe(). Usata anche dal servizio videoteca."""
    logger.info()
    data = httptools.downloadpage(item.url, cloudscraper=True).data or ''
    token = _token_from_data(data)
    if not token:
        logger.error('episodios: token non trovato su ' + item.url)
        return []

    pairs = PAIRS_CACHE.get(token)
    if pairs is None:
        pairs = _pairs_via_server(token)
        if pairs:
            PAIRS_CACHE[token] = pairs
    if not pairs:
        logger.info('episodios: nessun episodio su vidxgo (%s)' % token)
        return []
    return _episode_list(item, pairs, token)


def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    data = support.httptools.downloadpage(item.url, cloudscraper=True).data or ''
    if not data:
        return []

    # token dal JS della pagina (imdb, altrimenti tmdb)
    token = _token_from_data(data)
    if not token:
        logger.error('findvideos: token non trovato su ' + item.url)
        return []

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    # episodio diretto (arriva da _episode_list): NESSUN probe, via play
    if s and e:
        it = item.clone(action='play', server='vidxgo',
                        url='https://v.vidxgo.co/%s/%d/%d' % (token, s, e))
        it.contentTitle = item.contentTitle or item.fulltitle
        return support.server(item, itemlist=[it])

    # niente s/e: serie o film? parse della pagina embed (senza probe)
    pairs = _pairs_via_server(token, quiet=True)
    if pairs:
        itemlist = []
        for ps, pe in pairs:
            it = item.clone(action='play', server='vidxgo',
                            url='https://v.vidxgo.co/%s/%d/%d' % (token, ps, pe))
            it.contentSeason = ps
            it.contentEpisode = pe
            it.contentTitle = item.contentTitle or item.fulltitle
            it.title = '%dx%02d' % (ps, pe)
            itemlist.append(it)
        return itemlist

    # film (o pagina non leggibile): play del token nudo, il server decide
    it = item.clone(action='play', url='https://v.vidxgo.co/' + token)
    it.contentTitle = item.contentTitle or item.fulltitle
    return support.server(item, itemlist=[it])


def addToLibrary(item):
    """'Aggiungi alla videoteca': il launcher instrada l'azione al canale
    (getattr(channel, item.action)), quindi il canale deve esporla."""
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
