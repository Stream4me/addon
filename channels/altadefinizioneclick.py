# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Altadefinizione Click (nuovo dominio: altadefinizionex.live)
#
# Build 2026-09-19-NO-PROBE-2
#
# - mainlist / search / genres / peliculas / peliculas_genere : invariati
# - episodios : [UPGRADE vs NO-PROBE]
#       * stagioni non embeddate: discovery REALE dal player (cap 20s,
#         cache negativa per le assenti) invece di fabbricarle
#       * fallback probe() RIMOSSO -> Plan A (get_embed_page + discovery)
#       * titoli TMDB: IMDb id preso da data-imdb della pagina (il token
#         vidxgo NON e' necessariamente IMDb su questo sito)
#       * s/e in itemHook letti dall'URL sintetica (i gruppi 'season'/
#         'episode' del dict non diventano contentSeason/contentEpisode)
#       * cache di sessione per url serie -> riapertura istantanea
# - findvideos: iframe vidxgo (skip trailer) -> server='vidxgo' (invariato)
# - play      : RIMOSSO. Playback di servers/vidxgo.py.
# ------------------------------------------------------------

from core import support
from platformcode import config, logger
import re, html, json, traceback, urllib.parse, time, threading

host = support.config.get_channel_url()
if host and host.endswith('/'):
    host = host[:-1]

FETCH_TIMEOUT = 45          # prima fetch embed (puo' includere sweep TLS a freddo)
DISCOVERY_TIMEOUT = 20      # fetch stagioni in discovery (a TLS caldo bastano ~1s)
MAX_SEASON = 30

EP_CACHE = {}               # item.url -> {'token', 'pairs', 'titles'}
DISCOVERY_CACHE = {}        # token -> {s: [(s,e),...]} solo stagioni confermate


# ---------------------------------- MAIN MENU ----------------------------------
@support.menu
def mainlist(item):
    logger.debug(item)
    film = ['/film/',
            ('Generi', ['/film/', 'genres', 'genres'])]
    tvshow = ['/serie-tv/',
              ('Generi', ['/serie-tv/', 'genres', 'genres'])]
    search = ''
    return locals()


# ---------------------------------- SEARCH ----------------------------------
def search(item, texto):
    logger.debug("search: " + texto)
    item.args = 'search'
    f = item.contentType if item.contentType in ['movie', 'tvshow'] else 'all'
    item.url = host + "/archivio?search=" + urllib.parse.quote(texto) + "&f=" + f + "&page=1"
    try:
        return peliculas_genere(item)
    except Exception:
        logger.error("search failed: " + traceback.format_exc())
        return []


# ---------------------------------- GENRES ----------------------------------
def genres(item):
    logger.debug("genres called with item.url: %s", item.url)
    itemlist = []

    if '/film/' in item.url:
        tipo = 'film'
    elif '/serie-tv/' in item.url:
        tipo = 'serie-tv'
    else:
        tipo = 'film'

    data = support.httptools.downloadpage(host, cloudscraper=True).data
    if not data:
        return itemlist

    # [SCOPE] il patron va applicato SOLO al menu a tendina dei generi
    mb = re.search(r'<div class="dropdown-menu[^"]*">(?P<block>.*?)</div>', data, re.S)
    if mb:
        block = mb.group('block')
        patron = r'<a href="/([^"]+)"[^>]*>(?P<title>[^<]+)</a>'
        for url, title in re.findall(patron, block):
            it = item.clone()
            it.cat_id = url.strip('/')
            it.type = tipo
            it.action = 'peliculas_genere'
            it.is_folder = True
            it.title = title.strip()
            itemlist.append(it)
        return itemlist

    logger.error("genres: dropdown-menu non trovato, uso parse generico")
    patron = r'<a href="/([^"]+)"[^>]*>(?P<title>[^<]+)</a>'
    blacklist = ['', 'serie-tv', 'film', 'home', 'contatti', 'login', 'register',
                 'archivio', 'recensioni', 'random', 'cinema', 'prossimamente']
    for url, title in re.findall(patron, data):
        if url in blacklist:
            continue
        it = item.clone()
        it.cat_id = url.strip('/')
        it.type = tipo
        it.action = 'peliculas_genere'
        it.is_folder = True
        it.title = title.strip()
        itemlist.append(it)
    return itemlist


# ---------------------------------- MAIN LISTING ----------------------------------
@support.scrape
def peliculas(item):
    logger.debug(item)

    if item.args == 'search':
        url = item.url
    elif '/serie-tv/' in item.url or (hasattr(item, 'contentType') and item.contentType == 'tvshow'):
        url = host + '/serie-tv/'
    else:
        url = host + '/film/'

    data = support.httptools.downloadpage(url, cloudscraper=True).data

    if 'class="mlnew"' in data:
        patron = (r'<tr class="mlnew"[^>]*>\s*<td>\d+</td>\s*<td[^>]*>\s*'
                  r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*>\s*'
                  r'<img[^>]+src="(?P<thumb>[^"]+)"'
                  r'[\s\S]*?<h2[^>]*>\s*<a href="[^"]+"[^>]*>(?P<title>[^<]+)</a>'
                  r'[\s\S]*?<td class="text-center d-none d-lg-table-cell">(?P<year>\d{4})</td>'
                  r'[\s\S]*?<span class="badge[^"]*">(?P<rating>[0-9.]+)</span>')
    else:
        patron = (r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*'
                  r'data-title="(?P<title>[^"]+)"[^>]*data-year="(?P<year>\d+)"[^>]*'
                  r'data-imdb="(?P<rating>[^"]+)"[^>]*>\s*<img[^>]+src="(?P<thumb>[^"]+)"')

    action = 'findvideos'
    typeActionDict = {'episodios': ['serie-tv']}
    typeContentDict = {'tvshow': ['serie-tv']}
    pagination = 12
    debug = False

    return locals()


# ---------------------------------- GENRE LISTING + Search ----------------------------------
@support.scrape
def peliculas_genere(item):
    logger.debug("peliculas_genere: %s", item)

    cat = getattr(item, 'cat_id', '').strip('/')
    tipo = getattr(item, 'type', '')

    for t in ('film', 'serie-tv'):
        if cat.endswith('/' + t):
            cat = cat[:-(len(t) + 1)]
            tipo = t
            break

    if cat and ('/' + cat) not in item.url:
        candidates = []
        if tipo in ('film', 'serie-tv'):
            candidates.append(host + '/' + cat + '/' + tipo)
        candidates.append(host + '/' + cat + '/')
    else:
        candidates = [item.url]

    data = ''
    url = candidates[-1]
    for u in candidates:
        data = support.httptools.downloadpage(u, cloudscraper=True).data or ''
        if 'class="mlnew"' in data or 'data-title=' in data:
            url = u
            break
    logger.info("peliculas_genere uso: " + url)

    if 'class="mlnew"' in data:
        patronBlock = r'<tr class="mlnew"[^>]*>(?P<block>[\s\S]*?)</tr>'
        patron = (r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*>\s*'
                  r'<img[^>]+src="(?P<thumb>[^"]+)"'
                  r'[\s\S]*?<h2[^>]*>\s*<a[^>]*>(?P<title>[^<]+)</a>'
                  r'(?:[\s\S]*?<td class="text-center d-none d-lg-table-cell">(?P<year>\d{4})</td>)?'
                  r'(?:[\s\S]*?<span class="badge[^"]*">(?P<rating>[0-9.]+)</span>)?')
    elif 'data-title=' in data:
        patronBlock = ''
        patron = (r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*'
                  r'data-title="(?P<title>[^"]+)"[^>]*data-year="(?P<year>\d+)"[^>]*'
                  r'data-imdb="(?P<rating>[^"]+)"[^>]*>\s*<img[^>]+src="(?P<thumb>[^"]+)"')
    else:
        patronBlock = ''
        patron = ''
        logger.error("peliculas_genere: layout non riconosciuto su " + url)

    actLike = 'peliculas'
    action = 'findvideos'
    typeActionDict = {'episodios': ['serie-tv']}
    typeContentDict = {'tvshow': ['serie-tv']}

    PAGE_SIZE = 12

    def itemlistHook(itemlist):
        pag = int(getattr(item, 'page', 0) or 1)
        start = (pag - 1) * PAGE_SIZE
        paged = itemlist[start:start + PAGE_SIZE]
        if start + PAGE_SIZE < len(itemlist):
            nxt = item.clone(action='peliculas_genere')
            nxt.page = pag + 1
            nxt.title = '[B][COLOR cyan]>> Pagina successiva <<[/COLOR][/B]'
            paged.append(nxt)
        return paged

    return locals()


# ---------------------------------- helper vidxgo (motore comune) ----------------------------------

def _get_embed(url, seconds=FETCH_TIMEOUT):
    """get_embed_page del server: sessione TLS-rotata, la via del playback."""
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
    th.join(seconds)
    if not result.get('done'):
        logger.error('get_embed_page TIMEOUT ({}s) su {}'.format(seconds, url))
        return ''
    page = result.get('page', '')
    if page:
        logger.info('get_embed_page OK: {} bytes'.format(len(page)))
    return page


def _pairs_from_html(data):
    """Pattern italiani del sito."""
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
    for s, eps_s in re.findall(r'"season"\s*:\s*(\d+)\s*,\s*"episodes"\s*:\s*\[([^\]]*)\]', page):
        pairs.update((int(s), int(e)) for e in re.findall(r'\d+', eps_s))
    if not pairs:
        pairs = {(int(a), int(b)) for a, b in
                 re.findall(r'"season"\s*:\s*(\d+)\s*,\s*"episode"\s*:\s*(\d+)', page)}
    if not pairs:
        pairs = {(int(a), int(b)) for a, b in
                 re.findall(r'/' + re.escape(token) + r'/(\d+)/(\d+)', page)}
    if not pairs:
        pairs = set(_pairs_from_html(page))
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


def _discover_season(token, s):
    """Episodi REALI della stagione s dal player. Cap 20s + cache:
    le stagioni confermate assenti non vengono richieste due volte."""
    cache = DISCOVERY_CACHE.setdefault(token, {})
    if s in cache:
        return cache[s]

    p = _get_embed('https://v.vidxgo.co/%s/%d/1' % (token, s), seconds=DISCOVERY_TIMEOUT)
    if not p:
        return []                      # timeout/errore: NON in cache, ritentabile
    if 'Access Denied' in p[:3000] or ('/%s/%d/' % (token, s)) not in p:
        logger.info('discovery: stagione {} assente sul player'.format(s))
        cache[s] = []                  # confermato assente
        return []
    pairs = [(ps, pe) for ps, pe in _parse_page_pairs(p, token, quiet=True) if ps == s]
    cache[s] = pairs
    return pairs


def _pairs_via_server(token, quiet=False):
    """PIANO A: pagina embed via TLS del server + DISCOVERY stagioni.
    Sostituisce probe() (appeso anche a TLS caldo su questa box)."""
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
            new = _discover_season(token, s)
            if not new:
                break
            logger.info('discovery: stagione {} -> {} episodi'.format(s, len(new)))
            pairs |= new

    out = sorted(pairs)
    if out:
        logger.info('PIANO A: {} episodi, {} stagioni'.format(
            len(out), len({s for s, _ in out})))
    return out


# ---------------------------------- titoli episodi (TMDB) ----------------------------------
TMDB_API = 'https://api.themoviedb.org/3'
TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_LANG = 'it'

TMDB_ID_CACHE = {}
SEASON_TITLES = {}


def _imdb_from_page(data):
    """IMDb id dalla pagina del sito (data-imdb, link imdb.com, o tt nudo)."""
    if not data:
        return None
    m = re.search(r'data-imdb=["\'](tt\d{6,10})["\']', data)
    if not m:
        m = re.search(r'imdb\.com/title/(tt\d{6,10})', data)
    if not m:
        m = re.search(r'(tt\d{7,10})', data)
    return m.group(1)[2:] if m else None


def _tmdb_series_id(candidates):
    """TMDB id provando i candidati IMDb in ordine ('tt...' senza prefisso
    o token 'tmN' diretto). False se nessuno matcha una serie."""
    for c in candidates:
        if not c:
            continue
        c = str(c)
        if c in TMDB_ID_CACHE:
            if TMDB_ID_CACHE[c]:
                return TMDB_ID_CACHE[c]
            continue
        tmdb_id = False
        try:
            if c.startswith('tm'):
                tmdb_id = int(c[2:])
            else:
                url = '%s/find/tt%s?api_key=%s&external_source=imdb_id&language=%s' % (
                    TMDB_API, c, TMDB_KEY, TMDB_LANG)
                j = json.loads(support.httptools.downloadpage(url).data or '{}')
                if j.get('tv_results'):
                    tmdb_id = j['tv_results'][0]['id']
        except Exception:
            logger.error(traceback.format_exc())
        TMDB_ID_CACHE[c] = tmdb_id
        if tmdb_id:
            logger.info('tmdb id %s (da %s)' % (tmdb_id, c))
            return tmdb_id
    return False


def _season_titles(tmdb_id, s):
    key = (tmdb_id, s)
    if key in SEASON_TITLES:
        return SEASON_TITLES[key]
    out = {}
    try:
        url = '%s/tv/%d/season/%d?api_key=%s&language=%s' % (
            TMDB_API, tmdb_id, s, TMDB_KEY, TMDB_LANG)
        for ep in json.loads(support.httptools.downloadpage(url).data or '{}').get('episodes', []):
            n, name = ep.get('episode_number'), (ep.get('name') or '').strip()
            if n is not None and name and not re.match(r'^(episodio|episode)\s*\d+$', name, re.I):
                out[int(n)] = name
    except Exception:
        logger.error(traceback.format_exc())
    SEASON_TITLES[key] = out
    return out


def _episode_titles(candidates, pairs):
    """{(s, e): titolo} da TMDB; {} se la serie non e' mappata."""
    titles = {}
    tmdb_id = _tmdb_series_id(candidates)
    if not tmdb_id:
        logger.info('titoli TMDB: serie non mappata (candidati %s)' % (candidates,))
        return titles
    for s in sorted({s for s, _ in pairs}):
        for n, name in _season_titles(tmdb_id, s).items():
            titles[(s, n)] = name
    logger.info('titoli TMDB: {} su {} episodi'.format(len(titles), len(pairs)))
    return titles


# ---------------------------------- EPISODES ----------------------------------
@support.scrape
def episodios(item):
    data = support.httptools.downloadpage(item.url, cloudscraper=True).data
    TITLES = {}

    cached = EP_CACHE.get(item.url)
    if cached:
        # riapertura: tutto dalla cache di sessione, zero rete
        token = cached['token']
        tuples = cached['pairs']
        TITLES = cached['titles']
        data = ''.join('<a href="https://v.vidxgo.co/%s/%d/%d" data-s="%d" data-e="%d"></a>'
                       % (token, s, e, s, e) for s, e in tuples)
    else:
        # token iframe vidxgo, saltando i trailer
        token = None
        for m in re.finditer(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)[^"]*"', data):
            if 'trailer' in m.group(0).lower():
                continue
            token = m.group(1)
            break
        if token is None:
            m = re.search(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)', data)
            token = m.group(1) if m else None

        pair_set = set()
        if not token:
            logger.error("Token not found in iframe src")
            data = ''
        else:
            # [1] coppie reali dalla stagione embeddata
            pair_set = {(int(a), int(b)) for a, b in
                        re.findall(r'data-episode="(\d+)-(\d+)"', data)}
            embedded = {s for s, _ in pair_set}

            # tutte le stagioni dichiarate dal selettore
            seasons = sorted({int(x) for x in
                              re.findall(r'Stagione\s*(?:<!--[^>]*-->\s*)?(\d+)', data)
                              if int(x) <= MAX_SEASON})

            # [2] stagioni NON embeddate: discovery REALE (cap 20s, cache negativa)
            for s in seasons:
                if s in embedded:
                    continue
                disc = _discover_season(token, s)
                if disc:
                    logger.info('stagione {} (non embeddata): {} episodi reali dal player'.format(
                        s, len(disc)))
                    pair_set.update(disc)
                else:
                    # rete di sicurezza: fabbrica dai numeri noti (meglio del vuoto)
                    eps_fb = sorted({e for _, e in pair_set}) or \
                             sorted({int(x) for x in re.findall(
                                 r'Episodio\s*(?:<!--[^>]*-->\s*)?(\d+)', data)})
                    pair_set.update((s, e) for e in eps_fb)

            # [3] sito senza episodi -> Plan A completo (NIENTE probe())
            if not pair_set:
                logger.info('episodios: sito senza episodi -> Plan A')
                pair_set = set(_pairs_via_server(token))

        tuples = sorted(pair_set)

        if tuples:
            # [4] titoli TMDB: IMDb id dalla pagina (data-imdb), poi il token
            try:
                TITLES = _episode_titles([_imdb_from_page(data), token], tuples)
            except Exception:
                logger.error(traceback.format_exc())
                TITLES = {}

            data = ''.join('<a href="https://v.vidxgo.co/%s/%d/%d" data-s="%d" data-e="%d"></a>'
                           % (token, s, e, s, e) for s, e in tuples)
            EP_CACHE[item.url] = {'token': token, 'pairs': tuples, 'titles': TITLES}
        else:
            logger.error("episodios: nessun episodio trovato (sito + player)")
            data = ''

    patron = (r'<a href="(?P<url>https://v\.vidxgo\.co/[^"]+)"'
              r'[^>]*data-s="(?P<season>\d+)"[^>]*data-e="(?P<episode>\d+)"')
    action = 'play'

    def itemHook(it):
        it.is_folder = False
        it.server = 'vidxgo'
        # s/e dall'URL sintetica: deterministico, indipendente dal mapping
        # dei gruppi del dict (season/episode non finiscono su content*)
        m = re.search(r'v\.vidxgo\.co/\d+/(\d+)/(\d+)', it.url or '')
        if m:
            s, e = int(m.group(1)), int(m.group(2))
        else:
            s = int(getattr(it, 'contentSeason', None) or getattr(it, 'season', 0) or 0)
            e = int(getattr(it, 'contentEpisode', None) or getattr(it, 'episode', 0) or 0)
        t = TITLES.get((s, e))
        if t:
            it.title = (it.title + ' - ' + t) if it.title else t
        return it

    return locals()


# ---------------------------------- FIND VIDEOS ----------------------------------
def findvideos(item):
    logger.info("=== findvideos: " + item.url)

    page = ''
    for attempt in (1, 2, 3):
        try:
            page = support.httptools.downloadpage(item.url, cloudscraper=True).data or ''
        except Exception:
            logger.error("findvideos fetch attempt %d failed: %s"
                         % (attempt, traceback.format_exc()[-300:]))
            page = ''
        if page:
            break
        time.sleep(1)

    if not page:
        logger.error("detail page not loaded (3 tentativi)")
        return []

    embed_url = None
    fallback_url = None
    for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', page, re.I):
        src = html.unescape(m.group(1)).strip()
        if src.startswith('//'):
            src = 'https:' + src
        if 'vidxgo' not in src:
            continue
        if 'trailer' in src.lower():
            if fallback_url is None:
                fallback_url = src
            continue
        embed_url = src
        break
    if not embed_url:
        m = re.search(r'["\'](https?://[^"\']*vidxgo[^"\']+)["\']', page)
        embed_url = html.unescape(m.group(1)) if m else fallback_url

    logger.info("embed_url = " + str(embed_url))
    if not embed_url:
        logger.error("nessun embed vidxgo su " + item.url)
        return []

    it = item.clone(action='play', url=embed_url, server='vidxgo')
    it.title = '[COLOR lime]vidxgo[/COLOR]'
    it.contentTitle = getattr(item, 'contentTitle', '') or getattr(item, 'fulltitle', '') or item.title
    return support.server(item, itemlist=[it])
