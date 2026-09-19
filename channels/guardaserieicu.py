# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'GuardaSerieX'
# By: Napster32 (adattato)
# ------------------------------------------------------------
# Rev: 1.4
# Update: 2026-09-19
# Note:
#   - Token dal meta "keywords" (es. tt20516590), formato server: '20516590'.
#   - v.vidxgo.co: accesso diretto = challenge CF; via proxy workers.dev =
#     403 applicativo. L'UNICA via che funziona e' get_embed_page() di
#     servers/vidxgo.py (sessione TLS-rotata, la stessa del playback).
#   - probe() del server: appeso ANCHE a TLS caldo -> RIMOSSO da ogni flusso.
#   - Stratiglia episodios:
#       1) data-episode / Stagione / Episodio dalla pagina del sito
#       2) PIANO A: get_embed_page + parse locale; se copre una sola
#          stagione, DISCOVERY: /{token}/{s}/1 fino alla prima assente
#       3) PIANO B: sito gemello altadefinizionex (HTML data-episode)
#       4) fetch diretto del player via bypass CF del fork
#   - Titoli episodi da TMDB (lingua it); degrada a '1x01' se non mappata.
#   - Click episodio: url diretta v.vidxgo.co/{token}/{s}/{e} ->
#     server='vidxgo' (la via del play che funziona).
# ------------------------------------------------------------

import re, sys, json, time, threading, traceback
import urllib.parse

from core import support, httptools
from platformcode import logger

host = 'https://guardaseriex.cyou'
if host.endswith('/'):
    host = host[:-1]

headers = [['Referer', host]]

# ------------------------- cache / timing -------------------------
TOKEN_CACHE = {}            # url pagina sito -> token
PAIRS_CACHE = {}            # token -> [(s, e), ...]
FETCH_TIMEOUT = 45          # bypass CF del fork: ~15-20s nel peggiore dei casi
MAX_SEASON = 30             # discovery: limite difensivo

ALT_HOST = 'https://altadefinizionex.live'


@support.menu
def mainlist(item):
    tvshow = ['/serietv-streaming/page/1/',
              ('Generi', ['/serietv-streaming/page/1/', 'genres', 'genres'])]
    return locals()


@support.scrape
def genres(item):
    """Menu generi: dal dropdown 'Genere' del sito.
    Esclusi Netflix (netflix-gratis) e In Arrivo (coming-soon):
    blacklist per titolo + filtro per slug nell'hook."""
    action = 'peliculas'
    blacklist = ['Netflix', 'In Arrivo']
    patronBlock = r'>Genere</span>(?P<block>.*?)</ul>'
    patronMenu = r'<a class="dropdown-item" href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>'

    def itemlistHook(itemlist):
        out = []
        for it in itemlist:
            slug = (it.url or '').rstrip('/').rsplit('/', 1)[-1].lower()
            if slug in ('netflix-gratis', 'coming-soon'):
                continue
            out.append(it)
        return out

    return locals()


@support.scrape
def peliculas(item):
    patron = (
        r'<div class="movieItem"\s+data-tip="true"\s+'
        r'data-title="(?P<title>[^"]*)"\s+'
        r'data-year="(?P<year>\d+)"'
        r'(?:\s+data-rate="(?P<rating>[^"]*)")?\s+'
        r'data-text="(?P<plot>[^"]*)"\s+'
        r'data-category="(?P<category>[^"]*)"\s+'
        r'data-sound="(?P<audio>[^"]*)"\s+'
        r'data-time="(?P<duration>[^"]*)"\s*>'
        r'.*?<a href="(?P<url>[^"]+)"[^>]*>'
        r'.*?<img\s+src="\s*(?P<thumbnail>[^"]+?)\s*"'
    )
    patronNext = r'<div id="nav-load"><a href="([^"]+)"'

    def itemlistHook(itemlist):
        out = []
        for it in itemlist:
            it.contentType = 'tvshow'
            it.contentTitle = (it.fulltitle or it.title).strip()
            it.fulltitle = it.contentTitle
            it.action = 'episodios'      # invocazione diretta dal launcher
            out.append(it)
        return out

    return locals()


def search(item, text):
    logger.info(text)
    item.contentType = 'tvshow'
    item.url = host + "/index.php?do=search&subaction=search&story=" + text
    try:
        item.args = 'search'
        return peliculas(item)
    except:
        for line in sys.exc_info():
            logger.error("%s" % line)
    return []


# ------------------------- rete -------------------------

def _get_data(item):
    """Pagina del sito (non bloccata: fetch normale)."""
    try:
        res = httptools.downloadpage(item.url, headers=headers, cloudscraper=True)
        data = res.data or ''
        logger.info('GET {} -> {} bytes'.format(item.url, len(data)))
        return data
    except Exception:
        logger.error('downloadpage EXCEPTION su ' + str(item.url))
        logger.error(traceback.format_exc())
        return ''


def _fetch_with_timeout(url, seconds=FETCH_TIMEOUT):
    """downloadpage con watchdog (per tier 3 e 4)."""
    result = {}
    t0 = time.time()

    def worker():
        try:
            result['data'] = httptools.downloadpage(
                url, headers=headers, cloudscraper=True).data or ''
        except Exception:
            logger.error('fetch EXCEPTION su ' + url)
            result['data'] = ''
        result['done'] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(seconds)

    if not result.get('done'):
        logger.error('fetch TIMEOUT ({}s) su {}'.format(seconds, url))
        return ''
    data = result.get('data', '')
    logger.info('GET {} -> {} bytes in {:.1f}s'.format(url, len(data), time.time() - t0))
    return data


def _get_embed(url):
    """get_embed_page del server (sessione TLS-rotata, la via del playback).
    L'UNICA fetch verso v.vidxgo.co che funziona."""
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


# ------------------------- token -------------------------

def _token_from_data(item, data):
    """Token: cache -> meta keywords (tt...) -> tmdb -> qualsiasi tt."""
    token = TOKEN_CACHE.get(item.url)
    if token:
        return token

    token = None
    m = re.search(r'<meta\s+name="keywords"\s+content="[^"]*?(tt\d+)"', data)
    if m:
        token = m.group(1)[2:]
    else:
        m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data)
        if m:
            token = 'tm' + m.group(1)
        else:
            m = re.search(r'(tt\d+)', data)
            if m:
                token = m.group(1)[2:]

    if token:
        TOKEN_CACHE[item.url] = token
    logger.info('token estratto: {}'.format(token))
    return token


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

def _pairs_from_html(data):
    """Pattern del sito (italiano) + varianti generiche."""
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
        pairs = set(_pairs_from_html(page))
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


def _pairs_via_server(token):
    """PIANO A: pagina embed via TLS del server + DISCOVERY stagioni.
    1) /{token} -> parse (di norma la stagione 1)
    2) finche' esiste, /{token}/{s+1}/1 -> parse della stagione successiva
       (la pagina deve citare '/{token}/{s}/', altrimenti ci fermiamo)"""
    page = _get_embed('https://v.vidxgo.co/' + token)
    if not page:
        return []
    if 'Access Denied' in page[:3000]:
        logger.error('server: pagina embed -> 403 applicativo')
        return []

    pairs = set(_parse_page_pairs(page, token))
    seasons = sorted({s for s, _ in pairs})
    logger.info('parse pagina 1: {} episodi, stagioni {}'.format(len(pairs), seasons))

    if seasons and seasons[0] >= 1 and seasons[-1] < MAX_SEASON:
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
    logger.info('PIANO A: {} episodi, {} stagioni'.format(
        len(out), len({s for s, _ in out})))
    return out


def _pairs_from_altadefinizione(title):
    """PIANO B: episodi dal sito gemello (HTML data-episode, stesso backend
    vidxgo). Ritorna (pairs, token)."""
    try:
        queries = []
        for q in (title.strip(), title.split('(')[0].strip()):
            if q and q not in queries:
                queries.append(q)
        for q in queries:
            sdata = _fetch_with_timeout(ALT_HOST + '/archivio?search=' +
                                        urllib.parse.quote(q) + '&f=tvshow&page=1')
            m = re.search(r'href="(/serie-tv/[^"]+-streaming\.html)"', sdata or '')
            if not m:
                logger.info('piano B: nessun risultato per "{}"'.format(q))
                continue
            ddata = _fetch_with_timeout(ALT_HOST + m.group(1))
            pairs = {(int(a), int(b)) for a, b in
                     re.findall(r'data-episode="(\d+)-(\d+)"', ddata or '')}
            if pairs:
                tm = re.search(r'v\.vidxgo\.co/(\d+)', ddata)
                logger.info('piano B: {} episodi (token {})'.format(
                    len(pairs), tm and tm.group(1)))
                return sorted(pairs), (tm.group(1) if tm else None)
    except Exception:
        logger.error(traceback.format_exc())
    return [], None


def _pairs_from_player(token):
    """Tier 4: fetch diretto del player via bypass CF del fork."""
    data = _fetch_with_timeout('https://v.vidxgo.co/' + token)
    if not data:
        return []
    return _parse_page_pairs(data, token)


# ------------------------- azioni -------------------------

def episodios(item):
    logger.info('episodios INIZIO url={}'.format(item.url))

    data = _get_data(item)
    token = _token_from_data(item, data)
    if not token:
        return []

    if token in PAIRS_CACHE:
        pairs = PAIRS_CACHE[token]
        logger.info('episodi da cache: {} coppie'.format(len(pairs)))
    else:
        # 1) pagina del sito
        pairs = _pairs_from_html(data)

        # 2) PIANO A: embed via TLS del server + discovery stagioni
        if not pairs:
            logger.info('tier 2: PIANO A (get_embed_page + discovery)')
            pairs = _pairs_via_server(token)

        # 3) PIANO B: sito gemello
        if not pairs:
            logger.info('tier 3: piano B altadefinizionex')
            alt_pairs, alt_token = _pairs_from_altadefinizione(
                item.contentTitle or item.fulltitle or item.title)
            if alt_pairs:
                pairs = alt_pairs
                if alt_token:
                    token = alt_token

        # 4) player via bypass del fork
        if not pairs:
            logger.info('tier 4: fetch diretto player (bypass CF)')
            pairs = _pairs_from_player(token)

        if pairs:
            PAIRS_CACHE[token] = pairs

    if not pairs:
        logger.error('episodios: nessun episodio (sito+server+gemello+player)')
        return []

    # titoli TMDB: un problema qui non deve mai cancellare la lista
    try:
        titles = _episode_titles(token, pairs)
    except Exception:
        logger.error(traceback.format_exc())
        titles = {}

    itemlist = []
    for s, e in pairs:
        it = item.clone(action='findvideos')
        it.contentType = 'episode'
        it.contentSeason = s
        it.contentEpisode = e
        it.contentTitle = item.contentTitle or item.fulltitle
        it.vidxgo_token = token
        it.title = '%dx%02d' % (s, e)
        t = titles.get((s, e))
        if t:
            it.title += ' - ' + t
        itemlist.append(it)

    # voce videoteca (commentare per escluderla)
    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = item.contentTitle or item.fulltitle
    cl.fulltitle = cl.contentTitle
    cl.show = cl.contentTitle
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    itemlist.append(cl)

    logger.info('episodios FINE ({} episodi)'.format(len(itemlist) - 1))
    return itemlist


def findvideos(item):
    logger.info('findvideos s={} e={} token={}'.format(
        getattr(item, 'contentSeason', None),
        getattr(item, 'contentEpisode', None),
        getattr(item, 'vidxgo_token', None)))

    token = getattr(item, 'vidxgo_token', None)
    if not token:
        token = _token_from_data(item, _get_data(item))
    if not token:
        return []

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    # episodio: URL diretta, NESSUN probe, play via server vidxgo
    if s and e:
        it = item.clone(action='play', server='vidxgo',
                        url='https://v.vidxgo.co/%s/%d/%d' % (token, s, e))
        it.contentTitle = item.contentTitle or item.fulltitle
        return support.server(item, itemlist=[it])

    # niente s/e (entry dirette/videoteca): tv o film SENZA probe()
    pairs = _pairs_via_server(token)
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
    logger.info('findvideos: play token nudo (token {})'.format(token))
    return support.server(item, itemlist=[it])


def addToLibrary(item):
    """Esposta l'azione per la voce 'Aggiungi alla Videoteca'."""
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
