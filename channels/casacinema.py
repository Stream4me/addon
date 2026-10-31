# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'casacinema' (casa-cinema.cfd)
# Build 2026-09-25-VIXSRC2.0
#
# Modello altadefinizioneclick:
#   - listing: patron class="posts" (layout DLE attuale), IMDb dal
#     nome del poster (/uploads/.../ttXXXX.jpg) -> infoLabels
#   - check(): UNA pagina scaricata, smista film/serie e riusa
#     item.data. Discriminante: la pagina serie cita 'vixsrc.to/tv/'
#     e ha il selettore "Stagione"; i film citano 'vixsrc.to/movie/'.
#   - episodios IBRIDO: oracolo API vixsrc (stagioni/episodi reali,
#     cache 3 giorni, fallback griglia se rete giu') + TMDB enrichment
#   - playback: popup vixsrc (diretto) + vixsrc_alt (proxy)
#   - tm->tt: paracadute TMDB external_ids (dal vecchio FIX 1.3)
# ------------------------------------------------------------

from core import support, httptools
from platformcode import config, logger
import re, html, json, base64, os, tempfile, traceback, urllib.parse, time

host = support.config.get_channel_url()
if host and host.endswith('/'):
    host = host[:-1]

MAX_SEASONS  = 30        # bound di sicurezza (l'oracolo si ferma al primo 404)
MAX_EPISODES = 40

TMDB_API  = 'https://api.themoviedb.org/3'
TMDB_KEY  = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_ID_CACHE = {}

VIXSRC_API = 'https://vixsrc.to'
VIXSRC_UA  = ('Mozilla/5.0 (X11; Linux x86_64; rv:156.0) '
              'Gecko/20100101 Firefox/156.0')
API_SLEEP   = 0.8        # [POLITE]
CACHE_TTL   = 3 * 86400
_SERIES_CACHE_FILE = os.path.join(tempfile.gettempdir(),
                                  's4me_vixsrc_series_casacinema.json')
_SERIES_CACHE = None
_VIX_SESS = None


def _notify(msg):
    try:
        import xbmcgui
        xbmcgui.Dialog().notification('casacinema', msg,
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
    except Exception:
        pass


# ---------------------------------- MAIN MENU ----------------------------------
@support.menu
def mainlist(item):
    top = [('Generi', ['', 'genres'])]
    film = ['/film']
    tvshow = ['/serie-tv',
              ('Miniserie', ['/miniserie-tv', 'peliculas', ''])]
    search = ''
    return locals()


# ---------------------------------- GENRES ----------------------------------
@support.scrape
def genres(item):
    action = 'peliculas'
    blacklist = ['Serie TV', 'Miniserie TV']
    patronMenu = r'<li><a href="(?P<url>[^"]+)">(?P<title>[^<>]+)</a></li>'
    patronBlock = r'<a href="#">Categorie</a>(?P<block>.*?)<a href="#"'
    return locals()


# ---------------------------------- SEARCH ----------------------------------
def search(item, text):
    item.url = "{}/?{}".format(host, support.urlencode(
        {'story': text, 'do': 'search', 'subaction': 'search'}))
    try:
        return peliculas(item)
    except Exception:
        logger.error('search failed: ' + traceback.format_exc())
        return []


# ---------------------------------- LISTING ----------------------------------
@support.scrape
def peliculas(item):
    logger.debug(item)

    if item.args == 'search':
        url = item.url
    elif (item.url or '').startswith('http'):
        url = item.url
    else:
        url = host + (item.url or '/film/')

    data = support.httptools.downloadpage(url, cloudscraper=True).data

    patron = (r'<div class="posts">\s*<a href="(?P<url>https?://[^"]+?\.html)">\s*'
              r'<div style="background-image:\s*url\((?P<thumb>[^)]+)\);">\s*'
              r'<div class="title">(?P<title>[^<]+)</div>')
    patronNext = r'<a href="([^"]+)"\s*>Pagina'

    itemHook = _listing_hook
    action = 'check'                     # modello altadefinizioneclick
    debug = False

    return locals()


def _listing_hook(it):
    """Titolo pulito ([HD] -> quality), thumb assoluta, IMDb dal poster."""
    try:
        t = html.unescape(it.title or '').strip()
        q = ''
        m = re.search(r'^(.*?)\s*\[(HD[^\]]*)\]\s*$', t)
        if m:
            t, q = m.group(1).strip(), m.group(2)
        if t:
            it.title = t
        if q:
            it.quality = q
            it.title += support.typo(q, ' [] color std')
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


# ------------------------- COMMON -------------------------

def _get_data(item):
    """UN solo download, riusabile (stile check())."""
    if hasattr(item, 'data') and item.data:
        return item.data
    return support.httptools.downloadpage(item.url, cloudscraper=True).data or ''


def _estrai_imdb(data):
    """var imdb del player DLE -> themoviedb -> poster."""
    for pat in (r"imdb\s*=\s*'(tt\d+)'",
                r'themoviedb\.org/(?:movie|tv)/(\d+)',
                r'/uploads/[^"\']*/(tt\d+)\.jpg'):
        m = re.search(pat, data or '')
        if m:
            return m.group(1)
    return ''


def _imdb_from_tm(tm_id):
    """[paracadute] tmN -> tt via TMDB external_ids (movie poi tv)."""
    key = 'imdb:tm' + tm_id
    if key in TMDB_ID_CACHE:
        return TMDB_ID_CACHE[key]
    imdb = None
    for kind in ('movie', 'tv'):
        try:
            url = '%s/%s/%s/external_ids?api_key=%s' % (
                TMDB_API, kind, tm_id, TMDB_KEY)
            j = json.loads(httptools.downloadpage(url).data or '{}')
            v = j.get('imdb_id') or ''
            if v.startswith('tt'):
                imdb = v
                break
        except Exception:
            logger.error('_imdb_from_tm: ' + traceback.format_exc()[-200:])
    TMDB_ID_CACHE[key] = imdb
    return imdb


def _imdb_for_player(data, item=None):
    """tt garantito o None (con notifica se il tm non e' convertibile)."""
    imdb = _estrai_imdb(data)
    if imdb and imdb.startswith('tt'):
        return imdb
    if imdb and imdb.isdigit():
        imdb = _imdb_from_tm(imdb)
        if imdb:
            return imdb
    # ultimo ricorso: IMDb dal poster dell'item (listing hook)
    tt = ''
    try:
        tt = (getattr(item, 'infoLabels', {}) or {}).get('imdb_id', '') or ''
    except Exception:
        tt = ''
    if tt:
        return tt
    _notify('IMDb non disponibile per questo titolo')
    return None


# ---------------------------------- CHECK ----------------------------------
def check(item):
    logger.info('check: %s' % item.url)
    item.data = _get_data(item)
    if not item.data:
        logger.error('check: pagina non scaricata')
        return []

    if 'vixsrc.to/tv/' in item.data:
        item.contentType = 'tvshow'
        logger.info('check: serie TV -> episodios')
        return episodios(item)
    item.contentType = 'movie'
    logger.info('check: film -> findvideos')
    return findvideos(item)


# ------------------------- VIXSRC: oracolo stagioni/episodi -------------------------

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
    """GET /api/tv/{imdb}[/{s}/{e}] -> (code, src, t, d)."""
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
            clean = False
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


# ---------------------------------- EPISODES (ibrido) ----------------------------------
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
            itemlist.append(_add_library_item(item))
            return itemlist
        logger.error('episodios: oracolo stagioni KO, fallback griglia')
        return _griglia_fallback(item, imdb_id, thumb)

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
        it.contentTitle = getattr(item, 'contentTitle', '') or item.fulltitle
        it.title = t
        it.contentSerieName = getattr(item, 'fulltitle', '') or item.title
        if thumb:
            it.thumbnail = thumb
            it.contentThumbnail = thumb
        it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb_id, season, e)
        itemlist.append(it)

    if config.get_setting('episode_info') and not support.stackCheck(['add_tvshow', 'get_newest']):
        try:
            support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        except Exception:
            logger.error('episodios: TMDB enrichment fallito')

    itemlist.append(_add_library_item(item))
    return itemlist


def _griglia_fallback(item, imdb_id, thumb, solo_stagione=None):
    stagioni = [solo_stagione] if solo_stagione else range(1, MAX_SEASONS + 1)
    itemlist = []
    for season in stagioni:
        for episode in range(1, MAX_EPISODES + 1):
            it = item.clone(action='findvideos', contentType='episode')
            it.season = season
            it.episode = episode
            it.contentSeason = season
            it.contentEpisodeNumber = episode
            it.contentTitle = getattr(item, 'contentTitle', '') or item.fulltitle
            it.title = '%dx%02d' % (season, episode)
            it.contentSerieName = getattr(item, 'fulltitle', '') or item.title
            if thumb:
                it.thumbnail = thumb
                it.contentThumbnail = thumb
            it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb_id, season, episode)
            itemlist.append(it)
    itemlist.append(_add_library_item(item))
    return itemlist


def _add_library_item(item):
    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = getattr(item, 'contentTitle', '') or item.fulltitle
    cl.fulltitle = cl.contentTitle
    cl.show = cl.contentTitle
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    return cl


# ---------------------------------- FIND VIDEOS ----------------------------------
def findvideos(item):
    logger.info('findvideos: %s' % item.url)

    # episodio: URL gia' sintetico vixsrc
    if getattr(item, 'contentType', '') == 'episode' or \
            'vixsrc.to/tv/' in (item.url or ''):
        return _offri_server(item, item.url)

    data = _get_data(item)
    imdb_id = _imdb_for_player(data, item)
    if not imdb_id:
        return []

    url = 'https://vixsrc.to/movie/%s?lang=it' % imdb_id
    return _offri_server(item, url)


def _offri_server(item, url):
    itemlist = []
    for label, srv in (('vixsrc', 'vixsrc'), ('vixsrc ALT', 'vixsrc_alt')):
        it = item.clone(action='play', url=url, server=srv)
        it.title = '[COLOR lime]%s[/COLOR]' % label
        it.contentTitle = getattr(item, 'contentTitle', '') \
            or getattr(item, 'fulltitle', '') or item.title
        itemlist.append(it)
    return support.server(item, itemlist=itemlist)


# ---------------------------------- VIDEOTECA ----------------------------------
def addToLibrary(item):
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
