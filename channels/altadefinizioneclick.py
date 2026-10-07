# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Altadefinizione Click (altadefinizionex.live)
# Build 2026-09-25-HYBRID
#
# - check(): UNA pagina scaricata, smista film/serie e riusa item.data
# - episodios IBRIDO:
#       livello 1: stagioni REALI via oracolo API vixsrc (404 = non esiste)
#       livello 2: episodi REALI della stagione, titoli dal parametro 'd'
#       fallback:  griglia 12x24 (modello altadefinizione01) se rete giu'
#       cache su disco 3 giorni -> istantaneo dalle volte successive
#   + TMDB enrichment (plot/still reali), Trakt, videolibrary
# - IMDb: var imdb del player DLE -> iframe vixsrc/vidxgo -> poster ttXXXX.jpg
# - Listing: 3 layout (attuale: card class="movie"); filtro nuovo tipo=1/2
# - findvideos: popup con vixsrc (diretto) e vixsrc_alt (proxy)
# ------------------------------------------------------------

from core import support, httptools
from platformcode import config, logger
import re, html, json, base64, os, tempfile, traceback, urllib.parse, time

host = support.config.get_channel_url()
if host and host.endswith('/'):
    host = host[:-1]

MAX_SEASONS  = 12        # bound dichiarato dal player DLE del sito
MAX_EPISODES = 24        # idem


# ---------------------------------- MAIN MENU ----------------------------------
@support.menu
def mainlist(item):
    film = ['/film/?tipo=1',
            ('Generi', ['/film/', 'genres', 'genres'])]

    tvshow = ['/film/?tipo=2',
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

    if '/serie-tv/' in item.url:
        tipo = 'serie-tv'
    else:
        tipo = 'film'

    data = support.httptools.downloadpage(host, cloudscraper=True).data
    if not data:
        return itemlist

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


@support.scrape
def paese(item):
    action = 'peliculas_genere'
    patronBlock = r'<span class="filter-name">Paese</span>.*?<div class="filter-values">(?P<block>.*?)</div></div></div>'
    patron = r'<input[^>]+name="paese"[^>]+value="(?P<url>[^"]+)"'

    def itemHook(it):
        it.cat_id = it.url
        it.title = it.url
        return it

    return locals()


# ------------------------- COMMON -------------------------

def _listing_hook(it):
    """Titolo unescape, thumbnail assoluta, IMDb dal poster ttXXXX.jpg."""
    try:
        t = html.unescape(it.title or '').strip()
        if t:
            it.title = t
        th = it.thumbnail or ''
        if th.startswith('//'):
            th = 'https:' + th
        elif th.startswith('/'):
            th = host + th
        it.thumbnail = th
        m = re.search(r'(tt\d+)\.jpg', th)
        if m:
            il = dict(getattr(it, 'infoLabels', {}) or {})
            il['imdb_id'] = m.group(1)
            it.infoLabels = il
    except Exception:
        pass
    return it


def _get_data(item):
    """UN solo download, riusabile: item.data se presente (stile check())."""
    if hasattr(item, 'data') and item.data:
        return item.data
    return support.httptools.downloadpage(item.url, cloudscraper=True).data or ''


def _estrai_imdb(data):
    """Gerarchia: var imdb del player DLE -> iframe -> poster."""
    for pat in (r"var\s+imdb\s*=\s*'(tt\d+)'",
                r'vixsrc\.to/(?:tv|movie)/(tt\d+)',
                r'v\.vidxgo\.co/(tt\d+)',
                r'/uploads/[^"\']*/(tt\d+)\.jpg'):
        m = re.search(pat, data or '')
        if m:
            return m.group(1)
    return ''


# ---------------------------------- MAIN LISTING ----------------------------------
@support.scrape
def peliculas(item):
    logger.debug(item)

    if item.args == 'search':
        url = item.url
    elif 'tipo=' in (item.url or ''):
        url = item.url                      # nuovo filtro tipo=1 (film) / tipo=2 (serie)
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
    elif 'data-title=' in data:
        patron = (r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*'
                  r'data-title="(?P<title>[^"]+)"[^>]*data-year="(?P<year>\d+)"[^>]*'
                  r'data-imdb="(?P<rating>[^"]+)"[^>]*>\s*<img[^>]+src="(?P<thumb>[^"]+)"')
    elif 'class="movie"' in data and 'data-link=' in data:
        patron = (r'<div class="movie"[^>]*?'
                  r'data-imdb="(?P<rating>[^"]*)"[^>]*?'
                  r'data-year="(?P<year>\d{4})"[^>]*?'
                  r'data-link="(?P<url>https?://[^"]+?/(?P<type>[^"/]+)/[^"]+-streaming\.html)"'
                  r'[\s\S]*?<img[^>]+src="(?P<thumb>[^"]+)"'
                  r'[\s\S]*?<h2 class="movie-title">\s*<a[^>]*>(?P<title>[^<]+)</a>')
    else:
        patron = ''
        logger.error('peliculas: layout non riconosciuto su ' + url)

    itemHook = _listing_hook
    action = 'check'                        # modello altadefinizione01
    typeActionDict = {'episodios': ['serie-tv']}
    typeContentDict = {'tvshow': ['serie-tv']}
    pagination = 12
    debug = False

    return locals()


# ---------------------------------- GENRE LISTING + Search ----------------------------------
@support.scrape
def peliculas_genere(item):
    logger.debug("peliculas_genere: %s", item)

    from urllib.parse import quote

    cat         = getattr(item, 'cat_id', '').strip('/')
    tipo        = getattr(item, 'type', '')
    filter_type = getattr(item, 'filter_type', '')

    if filter_type == 'paese':
        url = host + '/film/?paese=' + quote(cat)
        if 'serie-tv' in (item.url or ''):
            url = host + '/serie-tv/?paese=' + quote(cat)
        candidates = [url]
    else:
        for t in ('film', 'serie-tv'):
            if cat.endswith('/' + t):
                cat  = cat[:-(len(t) + 1)]
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
        if 'class="mlnew"' in data or 'data-title=' in data \
                or ('class="movie"' in data and 'data-link=' in data):
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
    elif 'class="movie"' in data and 'data-link=' in data:
        patronBlock = ''
        patron = (r'<div class="movie"[^>]*?'
                  r'data-imdb="(?P<rating>[^"]*)"[^>]*?'
                  r'data-year="(?P<year>\d{4})"[^>]*?'
                  r'data-link="(?P<url>https?://[^"]+?/(?P<type>[^"/]+)/[^"]+-streaming\.html)"'
                  r'[\s\S]*?<img[^>]+src="(?P<thumb>[^"]+)"'
                  r'[\s\S]*?<h2 class="movie-title">\s*<a[^>]*>(?P<title>[^<]+)</a>')
    else:
        patronBlock = ''
        patron = ''
        logger.error("peliculas_genere: layout non riconosciuto su " + url)

    itemHook = _listing_hook

    actLike = 'peliculas'
    action = 'check'
    typeActionDict  = {'episodios': ['serie-tv']}
    typeContentDict = {'tvshow':    ['serie-tv']}

    PAGE_SIZE = 12

    def itemlistHook(itemlist):
        pag   = int(getattr(item, 'page', 0) or 1)
        start = (pag - 1) * PAGE_SIZE
        paged = itemlist[start:start + PAGE_SIZE]
        if start + PAGE_SIZE < len(itemlist):
            nxt = item.clone(action='peliculas_genere')
            nxt.page        = pag + 1
            nxt.filter_type = filter_type
            nxt.title       = '[B][COLOR cyan]>> Pagina successiva <<[/COLOR][/B]'
            paged.append(nxt)
        return paged

    return locals()


# ---------------------------------- CHECK (stile altadefinizione01) ----------------------------------
def check(item):
    logger.info('check: %s' % item.url)
    item.data = _get_data(item)
    if not item.data:
        logger.error('check: pagina non scaricata')
        return []

    is_tvshow = False
    if 'var imdb' in item.data and 'vixsrc.to/tv/' in item.data:
        is_tvshow = True
    elif re.search(r"var\s+imdb\s*=", item.data) and (
            'se-dle-player' in item.data or 'Stagione' in item.data):
        is_tvshow = True
    elif 'vixsrc.to/tv/' in item.data:
        is_tvshow = True

    if is_tvshow:
        item.contentType = 'tvshow'
        logger.info('check: serie TV -> episodios')
        return episodios(item)
    item.contentType = 'movie'
    logger.info('check: film -> findvideos')
    return findvideos(item)


# ------------------------- VIXSRC: oracolo stagioni/episodi -------------------------

VIXSRC_API = 'https://vixsrc.to'
VIXSRC_UA  = ('Mozilla/5.0 (X11; Linux x86_64; rv:156.0) '
              'Gecko/20100101 Firefox/156.0')
API_SLEEP   = 0.8        # [POLITE] pausa tra sonde API
CACHE_TTL   = 3 * 86400
_SERIES_CACHE_FILE = os.path.join(tempfile.gettempdir(), 's4me_vixsrc_series.json')
_SERIES_CACHE = None
_VIX_SESS = None


def _vix_session():
    global _VIX_SESS
    if _VIX_SESS is None:
        try:
            import cloudscraper
            _VIX_SESS = cloudscraper.create_scraper()
        except Exception:
            _VIX_SESS = False
    return _VIX_SESS or None


def _b64(x):
    try:
        x = (x or '').strip()
        return base64.b64decode(x + '=' * (-len(x) % 4)).decode('utf-8', 'replace')
    except Exception:
        return ''


def _api_tv(imdb, se=None):
    """GET /api/tv/{imdb}[/{s}/{e}] -> (code, src, t, d).
    code inferito dal body se il framework non espone .code."""
    if se:
        url = '%s/api/tv/%s/%d/%d?lang=it' % (VIXSRC_API, imdb, se[0], se[1])
    else:
        url = '%s/api/tv/%s?lang=it' % (VIXSRC_API, imdb)
    code, body = 0, ''
    sess = _vix_session()
    try:
        if sess is not None:
            r = sess.get(url, headers={'User-Agent': VIXSRC_UA,
                                       'Accept': 'application/json'}, timeout=12)
            code, body = r.status_code, r.text or ''
        else:
            r = httptools.downloadpage(url, cloudscraper=True)
            code = int(getattr(r, 'code', 0) or 0)
            body = getattr(r, 'data', '') or ''
    except Exception:
        return 0, '', '', ''
    if code == 0:
        if '"src"' in body:
            code = 200
        elif '"message"' in body or not body.strip():
            code = 404
    if code != 200:
        return code, '', '', ''
    try:
        src = json.loads(body).get('src') or ''
    except Exception:
        return code, '', '', ''
    t, d = '', ''
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)
        t = _b64(q.get('t', [''])[0])
        d = _b64(q.get('d', [''])[0])
    except Exception:
        pass
    return code, src, t, d


def _scache_load():
    global _SERIES_CACHE
    if _SERIES_CACHE is None:
        try:
            with open(_SERIES_CACHE_FILE) as f:
                _SERIES_CACHE = json.load(f)
        except Exception:
            _SERIES_CACHE = {}
    return _SERIES_CACHE


def _scache_save():
    try:
        with open(_SERIES_CACHE_FILE, 'w') as f:
            json.dump(_SERIES_CACHE or {}, f)
    except Exception:
        pass


def _scopri_stagioni(imdb):
    """Probe /api/tv/{imdb}/{s}/1 per s=1..12, stop alla prima 404.
    Cache 3 giorni. Se la rete fallisce (non 404) NON cachare."""
    cache = _scache_load()
    ent = cache.get(imdb) or {}
    now = time.time()
    if ent.get('seasons') and (now - ent.get('ts', 0)) < CACHE_TTL:
        return ent['seasons']
    seasons, clean = [], True
    for sn in range(1, MAX_SEASONS + 1):
        code, src, t, d = _api_tv(imdb, (sn, 1))
        if code == 200 and '/embed/' in src:
            seasons.append(sn)
            logger.info('oracolo %s: S%d OK%s' % (imdb, sn,
                        (' (%s)' % t) if t else ''))
        elif code == 404:
            break
        else:
            clean = False               # rete giu': non cachare
            break
        time.sleep(API_SLEEP)
    if seasons and clean:
        ent = cache.setdefault(imdb, {})
        ent['ts'] = now
        ent['seasons'] = seasons
        ent.setdefault('eps', {})
        _scache_save()
        logger.info('oracolo %s: stagioni %s' % (imdb, seasons))
    return seasons


def _scopri_episodi(imdb, season):
    """Probe /api/tv/{imdb}/{s}/{e} per e=1..24, stop alla prima 404.
    Titolo episodio dal parametro 'd' ("S1:E1 Titolo")."""
    cache = _scache_load()
    ent = cache.get(imdb) or {}
    eps = (ent.get('eps') or {}).get(str(season))
    now = time.time()
    if eps and (now - ent.get('ts', 0)) < CACHE_TTL:
        return eps
    out, clean = [], True
    for e in range(1, MAX_EPISODES + 1):
        code, src, t, d = _api_tv(imdb, (season, e))
        if code == 200 and '/embed/' in src:
            title = ''
            if d:
                title = re.sub(r'^S\d+\s*:\s*E\d+\s*[:\-]?\s*', '', d).strip()
            out.append([e, title])
        elif code == 404:
            break
        else:
            clean = False
            break
        time.sleep(API_SLEEP)
    if out and clean:
        ent = cache.setdefault(imdb, {})
        ent['ts'] = now
        ent.setdefault('eps', {})[str(season)] = out
        _scache_save()
        logger.info('oracolo %s S%d: %d episodi' % (imdb, season, len(out)))
    return out


# ---------------------------------- EPISODES (ibrido: oracolo + fallback griglia) ----------------------------------
def episodios(item):
    logger.info('episodios: %s' % item.url)
    data = _get_data(item)

    imdb_id = _estrai_imdb(data)
    if not imdb_id:
        logger.error('episodios: IMDb non trovato su ' + item.url)
        return []
    logger.info('episodios: imdb=%s' % imdb_id)

    try:
        season = int(getattr(item, 'contentSeason', 0)
                     or getattr(item, 'seas', 0) or 0)
    except Exception:
        season = 0

    thumb = item.thumbnail or getattr(item, 'contentThumbnail', '')

    # --- livello 1: STAGIONI reali via oracolo ---
    if not season:
        seasons = _scopri_stagioni(imdb_id)
        if seasons:
            if len(seasons) == 1:
                return _episodi_stagione(item, imdb_id, seasons[0], thumb)
            itemlist = []
            for sn in seasons:
                it = item.clone(action='episodios', url=item.url)
                it.contentSeason = sn
                it.seas = sn
                it.title = 'Stagione %d' % sn
                if thumb:
                    it.thumbnail = thumb
                itemlist.append(it)
            return itemlist
        # oracolo KO (rete): fallback griglia completa
        logger.error('episodios: oracolo stagioni KO, fallback griglia 12x24')
        return _griglia_fallback(item, imdb_id, thumb)

    # --- livello 2: EPISODI reali della stagione ---
    return _episodi_stagione(item, imdb_id, season, thumb)


def _episodi_stagione(item, imdb_id, season, thumb):
    eps = _scopri_episodi(imdb_id, season)
    if not eps:
        logger.error('episodios: oracolo episodi S%d KO, fallback griglia'
                     % season)
        return _griglia_fallback(item, imdb_id, thumb, solo_stagione=season)
    itemlist = []
    for e, title in eps:
        t = 'Episodio %d%s' % (e, (' - %s' % title) if title else '')
        it = item.clone(action='findvideos', contentType='episode')
        it.season = season
        it.episode = e
        it.contentSeason = season
        it.contentEpisodeNumber = e
        it.contentEpisode = e
        it.title = t
        it.contentSerieName = getattr(item, 'fulltitle', '') or item.title
        if thumb:
            it.thumbnail = thumb
            it.contentThumbnail = thumb
        it.imdb_id = imdb_id
        it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb_id, season, e)
        itemlist.append(it)

    # TMDB sopra l'oracolo: plot/still reali (titoli gia' garantiti dal 'd')
    if config.get_setting('episode_info') and not support.stackCheck(['add_tvshow', 'get_newest']):
        try:
            support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        except Exception:
            logger.error('episodios: TMDB enrichment fallito')
    try:
        support.check_trakt(itemlist)
    except Exception:
        pass
    try:
        support.videolibrary(itemlist, item)
    except Exception:
        pass
    return itemlist


def _griglia_fallback(item, imdb_id, thumb, solo_stagione=None):
    """Rete giu': griglia 12x24 (o della sola stagione) come nel modello 01."""
    stagioni = [solo_stagione] if solo_stagione else range(1, MAX_SEASONS + 1)
    itemlist = []
    for season in stagioni:
        for episode in range(1, MAX_EPISODES + 1):
            it = item.clone(action='findvideos', contentType='episode')
            it.season = season
            it.episode = episode
            it.contentSeason = season
            it.contentEpisodeNumber = episode
            it.contentEpisode = episode
            it.title = '%dx%02d' % (season, episode)
            it.contentSerieName = getattr(item, 'fulltitle', '') or item.title
            if thumb:
                it.thumbnail = thumb
                it.contentThumbnail = thumb
            it.imdb_id = imdb_id
            it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb_id, season, episode)
            itemlist.append(it)
    return itemlist


# ---------------------------------- FIND VIDEOS ----------------------------------
def findvideos(item):
    logger.info('findvideos: %s' % item.url)

    # --- episodi: URL gia' sintetico vixsrc, dritto al server ---
    if getattr(item, 'contentType', '') == 'episode' or \
            'vixsrc.to/tv/' in (item.url or ''):
        return _offri_server(item, item.url)

    data = _get_data(item)

    imdb_id = _estrai_imdb(data)
    if not imdb_id:
        logger.error('findvideos: IMDb non trovato su ' + item.url)
        return []
    logger.info('findvideos: imdb=%s' % imdb_id)

    if item.contentType == 'episode' or getattr(item, 'season', 0):
        season = getattr(item, 'season', 1) or 1
        episode = getattr(item, 'episode', 1) or 1
        url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb_id, season, episode)
    else:
        url = 'https://vixsrc.to/movie/%s?lang=it' % imdb_id

    return _offri_server(item, url)


def _offri_server(item, url):
    """Popup con entrambi i server (diretto + proxy)."""
    itemlist = []
    for label, srv in (('vixsrc', 'vixsrc'), ('vixsrc ALT', 'vixsrc_alt')):
        it = item.clone(action='play', url=url, server=srv)
        it.title = '[COLOR lime]%s[/COLOR]' % label
        it.contentTitle = getattr(item, 'contentTitle', '') \
            or getattr(item, 'fulltitle', '') or item.title
        itemlist.append(it)
    return support.server(item, itemlist=itemlist)
