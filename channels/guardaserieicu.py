# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'GuardaSerieX' (guardaseriex.pics) — SOLO SERIE TV
# Rev: 2.0  (2026-09-25)
#
# [2.0] MIGRAZIONE vidxgo -> vixsrc:
#   - episodios: ORACOLO API vixsrc (stagioni/episodi reali, 404=stop,
#     cache disco 3 giorni, fallback griglia se rete giu')
#   - IMDb: meta keywords (tt...) / var imdb / themoviedb (tt via TMDB)
#   - playback: popup vixsrc (diretto) + vixsrc_alt (proxy)
#   - titoli episodi: TMDB (come 1.4)
#   - RITIRATI: PIANO A/B/bypass vidxgo (server morto), ADX data-episode
# [KEEP 1.4] listing movieItem, generi, search, videoteca
# ------------------------------------------------------------

import re, sys, json, os, time, base64, tempfile, traceback, urllib.parse

from core import support, httptools
from platformcode import config, logger

host = 'https://guardaseriex.pics'
if host.endswith('/'):
    host = host[:-1]

headers = [['Referer', host]]

MAX_SEASONS  = 30
MAX_EPISODES = 40

TMDB_API = 'https://api.themoviedb.org/3'
TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_LANG = 'it'
TMDB_TV_CACHE = {}
TMDB_SEASON_CACHE = {}

VIXSRC_API = 'https://vixsrc.to'
VIXSRC_UA  = ('Mozilla/5.0 (X11; Linux x86_64; rv:156.0) '
              'Gecko/20100101 Firefox/156.0')
API_SLEEP   = 0.8        # [POLITE]
CACHE_TTL   = 3 * 86400
_SERIES_CACHE_FILE = os.path.join(tempfile.gettempdir(),
                                  's4me_vixsrc_series_guardaserie.json')
_SERIES_CACHE = None
_VIX_SESS = None


@support.menu
def mainlist(item):
    tvshow = ['/serietv-streaming/page/1/',
              ('Generi', ['/serietv-streaming/page/1/', 'genres', 'genres'])]
    return locals()


@support.scrape
def genres(item):
    """Generi dal dropdown 'Genere'. Blacklist per slug nell'hook."""
    action = 'peliculas'
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
            it.action = 'episodios'
            out.append(it)
        return out

    return locals()


def search(item, text):
    logger.info(text)
    item.contentType = 'tvshow'
    item.url = host + "/index.php?do=search&subaction=search&story=" + text
    try:
        return peliculas(item)
    except Exception:
        logger.error(traceback.format_exc())
    return []


# ------------------------- IMDb -------------------------

def _get_data(item):
    try:
        return httptools.downloadpage(item.url, headers=headers,
                                      cloudscraper=True).data or ''
    except Exception:
        logger.error('downloadpage EXCEPTION su ' + str(item.url))
        return ''


def _imdb_from_tm(tm_id):
    key = 'imdb:tm' + tm_id
    if key in TMDB_TV_CACHE:
        return TMDB_TV_CACHE[key]
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
    TMDB_TV_CACHE[key] = imdb
    if imdb:
        logger.info('tm->tt: tm%s -> %s' % (tm_id, imdb))
    return imdb


def _estrai_imdb(data):
    """tt COMPLETO: meta keywords -> var imdb -> themoviedb -> qualunque tt."""
    for pat in (r'<meta\s+name="keywords"\s+content="[^"]*?(tt\d+)"',
                r"imdb\s*=\s*'(tt\d+)'",
                r'themoviedb\.org/(?:movie|tv)/(\d+)',
                r'(tt\d{7,10})'):
        m = re.search(pat, data or '')
        if m:
            v = m.group(1)
            if v.startswith('tt'):
                return v
            imdb = _imdb_from_tm(v)
            if imdb:
                return imdb
    return ''


# ------------------------- ORACOLO vixsrc -------------------------

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


# ------------------------- titoli TMDB (1.4 intatto) -------------------------

def _season_titles(tmdb_id, s):
    key = (tmdb_id, s)
    if key in TMDB_SEASON_CACHE:
        return TMDB_SEASON_CACHE[key]
    out = {}
    try:
        url = '%s/tv/%d/season/%d?api_key=%s&language=%s' % (
            TMDB_API, tmdb_id, s, TMDB_KEY, TMDB_LANG)
        for ep in json.loads(httptools.downloadpage(url).data or '{}').get('episodes', []):
            n, name = ep.get('episode_number'), (ep.get('name') or '').strip()
            if n is not None and name and not re.match(r'^(episodio|episode)\s*\d+$', name, re.I):
                out[int(n)] = name
    except Exception:
        logger.error(traceback.format_exc())
    TMDB_SEASON_CACHE[key] = out
    return out


def _episode_titles(imdb, pairs):
    titles = {}
    if not (imdb and imdb.startswith('tt')):
        return titles
    tmdb_id = TMDB_TV_CACHE.get(imdb)
    if not tmdb_id:
        try:
            url = '%s/find/%s?api_key=%s&external_source=imdb_id&language=%s' % (
                TMDB_API, imdb, TMDB_KEY, TMDB_LANG)
            j = json.loads(httptools.downloadpage(url).data or '{}')
            if j.get('tv_results'):
                tmdb_id = j['tv_results'][0]['id']
                TMDB_TV_CACHE[imdb] = tmdb_id
        except Exception:
            logger.error(traceback.format_exc())
    if not tmdb_id:
        return titles
    for s in sorted({s for s, _ in pairs}):
        for n, name in _season_titles(tmdb_id, s).items():
            titles[(s, n)] = name
    logger.info('titoli TMDB: {} su {} episodi'.format(len(titles), len(pairs)))
    return titles


# ------------------------- azioni -------------------------

def episodios(item):
    logger.info('episodios INIZIO url={}'.format(item.url))
    data = _get_data(item)

    imdb = _estrai_imdb(data)
    if not imdb:
        logger.error('episodios: IMDb non trovato su ' + item.url)
        return []
    logger.info('episodios: imdb=' + imdb)

    title = getattr(item, 'contentTitle', '') or \
            getattr(item, 'fulltitle', '') or item.title
    thumb = item.thumbnail or getattr(item, 'contentThumbnail', '')

    try:
        season = int(getattr(item, 'contentSeason', 0)
                     or getattr(item, 'seas', 0) or 0)
    except Exception:
        season = 0

    if not season:
        seasons = _scopri_stagioni(imdb)
        if seasons:
            if len(seasons) == 1:
                return _episodi_stagione(item, imdb, seasons[0], title, thumb)
            itemlist = []
            for sn in seasons:
                it = item.clone(action='episodios', url=item.url)
                it.contentSeason = sn
                it.seas = sn
                it.title = 'Stagione %d' % sn
                if thumb:
                    it.thumbnail = thumb
                itemlist.append(it)
            itemlist.append(_add_library_item(item, title))
            return itemlist
        logger.error('episodios: oracolo KO, fallback griglia')
        return _griglia_fallback(item, imdb, title, thumb)

    return _episodi_stagione(item, imdb, season, title, thumb)


def _episodi_stagione(item, imdb, season, title, thumb):
    eps = _scopri_episodi(imdb, season)
    if not eps:
        logger.error('episodios: oracolo episodi S%d KO, fallback griglia' % season)
        return _griglia_fallback(item, imdb, title, thumb, solo_stagione=season)

    pairs = [(season, e) for e, _t in eps]
    try:
        titles = _episode_titles(imdb, pairs)
    except Exception:
        titles = {}

    itemlist = []
    for e, dtitle in eps:
        t = titles.get((season, e)) or dtitle or ''
        it = item.clone(action='findvideos')
        it.contentType = 'episode'
        it.contentSeason = season
        it.contentEpisodeNumber = e
        it.contentTitle = title
        it.title = '%dx%02d%s' % (season, e, (' - ' + t) if t else '')
        if thumb:
            it.thumbnail = thumb
        it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb, season, e)
        itemlist.append(it)

    itemlist.append(_add_library_item(item, title))
    logger.info('episodios FINE ({} episodi)'.format(len(itemlist) - 1))
    return itemlist


def _griglia_fallback(item, imdb, title, thumb, solo_stagione=None):
    stagioni = [solo_stagione] if solo_stagione else range(1, MAX_SEASONS + 1)
    itemlist = []
    for season in stagioni:
        for episode in range(1, MAX_EPISODES + 1):
            it = item.clone(action='findvideos')
            it.contentType = 'episode'
            it.contentSeason = season
            it.contentEpisodeNumber = episode
            it.contentTitle = title
            it.title = '%dx%02d' % (season, episode)
            if thumb:
                it.thumbnail = thumb
            it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb, season, episode)
            itemlist.append(it)
    itemlist.append(_add_library_item(item, title))
    return itemlist


def _add_library_item(item, title):
    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = title
    cl.fulltitle = title
    cl.show = title
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    return cl


def findvideos(item):
    logger.info('findvideos s={} e={}'.format(
        getattr(item, 'contentSeason', None),
        getattr(item, 'contentEpisode', None)))

    # episodio: URL gia' sintetico vixsrc
    if getattr(item, 'contentType', '') == 'episode' or \
            'vixsrc.to/tv/' in (item.url or ''):
        return _offri_server(item, item.url)

    data = _get_data(item)
    imdb = _estrai_imdb(data)
    if not imdb:
        logger.error('findvideos: IMDb non trovato')
        return []
    return _offri_server(item, 'https://vixsrc.to/movie/%s?lang=it' % imdb)


def _offri_server(item, url):
    itemlist = []
    for label, srv in (('vixsrc', 'vixsrc'), ('vixsrc ALT', 'vixsrc_alt')):
        it = item.clone(action='play', url=url, server=srv)
        it.title = '[COLOR lime]%s[/COLOR]' % label
        it.contentTitle = getattr(item, 'contentTitle', '') \
            or getattr(item, 'fulltitle', '') or item.title
        itemlist.append(it)
    return support.server(item, itemlist=itemlist)


def addToLibrary(item):
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
