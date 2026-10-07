# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'CineBlog001'  (https://cineblog001.download)
# ------------------------------------------------------------
# Rev: 1.5.0  (2026-09-25)
#
# Menu: Film / Serie TV / Sub-ITA / Generi / Cerca
#
# [1.5.0] MIGRAZIONE vidxgo -> vixsrc (dopo lo spegnimento di v.vidxgo.co):
#   - il sito espone imdb='ttXXXXXXX' nelle pagine dettaglio (DLE):
#     playback = vixsrc.to/movie|tv/{tt} con popup vixsrc (diretto) +
#     vixsrc_alt (proxy)
#   - episodios: ORACOLO API vixsrc (stagioni/episodi reali, 404 = stop,
#     cache su disco 3 giorni, fallback griglia se rete giu')
#   - titoli episodio: TMDB (come prima) sopra l'oracolo
#   - RITIRATI: TIER ADX (data-episode/data-title non esistono piu') e
#     probe vidxgo (server morto): sostituiti dall'oracolo
#   - tm->tt via TMDB external_ids resta come paracadute
# [KEEP 1.4.7] _CARD_RE, routing per categoria, check/_is_tv_page,
#   generi TMDB + ricerca CB01 parallela, enrichment listati/serie,
#   guardia anti-falso-serie, videoteca
# ------------------------------------------------------------

from core import support, httptools
from platformcode import logger
import re, html, time, traceback, json, threading, sys, os, tempfile, base64, urllib.parse

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    ThreadPoolExecutor = None

host = support.config.get_channel_url() or 'https://cineblog001.download'
if host.endswith('/'):
    host = host[:-1]

TMDB_API_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_GENRE_PAGE = 20
_CB01_WORKERS = 4

headers = [['Referer', host]]

VIXSRC_API = 'https://vixsrc.to'
VIXSRC_UA  = ('Mozilla/5.0 (X11; Linux x86_64; rv:156.0) '
              'Gecko/20100101 Firefox/156.0')
API_SLEEP   = 0.8        # [POLITE]
CACHE_TTL   = 3 * 86400
MAX_SEASONS  = 30
MAX_EPISODES = 40

_SERIES_CACHE_FILE = os.path.join(tempfile.gettempdir(),
                                  's4me_vixsrc_series_cb01.json')
_SERIES_CACHE = None
_VIX_SESS = None

TMDB_GENRE_NAMES = {
    28: 'Azione', 12: 'Avventura', 16: 'Animazione', 35: 'Commedia',
    80: 'Crime', 99: 'Documentario', 18: 'Drammatico', 10751: 'Famiglia',
    14: 'Fantasy', 10752: 'Guerra', 27: 'Horror', 9648: 'Poliziesco',
    10749: 'Romantico', 878: 'Fantascienza', 53: 'Thriller', 37: 'Western',
    36: 'Storico', 10402: 'Musical',
}

_CARD_RE = re.compile(
    r'<article\s+class="short\s+block-list">\s*'
    r'<div\s+class="story-cover">\s*'
    r'<a\s+href="(?P<url>[^"]+)"\s+title="(?P<title>[^"]*)"[^>]*>\s*'
    r'<img[^>]+data-src="(?P<thumb>[^"]+)"'
    r'(?:[\s\S]*?<div\s+class="text-uppercase">\s*<b>(?P<category>[^<]*))?'
)


# ------------------------- helper -------------------------

def _notify(msg):
    try:
        import xbmcgui
        xbmcgui.Dialog().notification('cineblog001', msg,
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
    except Exception:
        pass


def _fetch(url, attempts=2):
    if not url:
        return ''
    data = ''
    for attempt in range(1, attempts + 1):
        try:
            data = httptools.downloadpage(url, cloudscraper=True).data or ''
        except Exception:
            logger.error('_fetch %d/%d: %s'
                         % (attempt, attempts, traceback.format_exc()[-200:]))
            data = ''
        if data:
            return data
        time.sleep(1)
    return ''


def _tmdb_get(url):
    try:
        from core import tmdb as core_tmdb
        d = core_tmdb.Tmdb.get_json(url)
        if isinstance(d, dict) and d:
            return d
    except Exception:
        pass
    try:
        return json.loads(_fetch(url) or '{}')
    except Exception:
        return {}


def _imdb_from_data(data):
    """[1.5.0] IMDb COMPLETO (tt...) dalla pagina dettaglio.
    Prima: imdb='tt...' (player DLE). Poi: themoviedb -> tm (paracadute)."""
    m = re.search(r"imdb\s*=\s*'(tt\d{6,10})'", data or '', re.I)
    if m:
        return m.group(1)
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data or '')
    if m:
        return _imdb_from_tm(m.group(1))
    return ''


def _imdb_from_tm(tm_id):
    """tmN -> tt via TMDB external_ids (movie poi tv)."""
    key = 'imdb:tm' + tm_id
    if key in _TMDB_ID_CACHE:
        return _TMDB_ID_CACHE[key]
    imdb = None
    for kind in ('movie', 'tv'):
        try:
            url = '%s/%s/%s/external_ids?api_key=%s' % (
                TMDB_API, kind, tm_id, TMDB_API_KEY)
            j = _tmdb_get(url)
            v = j.get('imdb_id') or ''
            if v.startswith('tt'):
                imdb = v
                break
        except Exception:
            logger.error('_imdb_from_tm: ' + traceback.format_exc()[-200:])
    _TMDB_ID_CACHE[key] = imdb
    if imdb:
        logger.info('tm->tt: tm%s -> %s' % (tm_id, imdb))
    return imdb

TMDB_API = 'https://api.themoviedb.org/3'
_TMDB_ID_CACHE = {}


def _is_tv_page(data):
    """Serie SOLO se 'Serie TV' e' nel PRIMO blocco categoria della pagina
    dettaglio (i meta dicono 'serie tv' su tutte le pagine: boilerplate)."""
    m = re.search(r'class="text-uppercase">\s*<b>\s*([^<]{0,120})',
                  (data or '')[:40000])
    return bool(m and 'serie tv' in m.group(1).lower())


def _clean_tmdb_title(txt):
    txt = html.unescape(txt or '')
    txt = re.sub(r'\[[^\]]*\]', '', txt)
    txt = re.sub(r'\(\s*\d{4}\s*\)', '', txt)
    return txt.strip()


def _extract_year(txt):
    m = re.search(r'\((\d{4})\)', html.unescape(txt or ''))
    return m.group(1) if m else ''


def _set_fanart(it):
    try:
        il = it.infoLabels or {}
        if isinstance(il, dict):
            if il.get('fanart') and not getattr(it, 'fanart', ''):
                it.fanart = il['fanart']
            if il.get('thumbnail') and not getattr(it, 'thumbnail', ''):
                it.thumbnail = il['thumbnail']
    except Exception:
        pass


# ------------------------- ORACOLO vixsrc (stagioni/episodi) -------------------------

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
            out.append(e)
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


# ------------------------- titoli episodio (TMDB, 1.4.7 intatto) -------------------------

_TMDB_TV_CACHE = {}
_TMDB_SEASON_CACHE = {}


def _episode_titles(imdb, pairs):
    titles = {}
    if not (imdb and imdb.startswith('tt')):
        return titles
    try:
        tvid = _TMDB_TV_CACHE.get(imdb)
        if not tvid:
            u = ('https://api.themoviedb.org/3/find/%s'
                 '?api_key=%s&external_source=imdb_id' % (imdb, TMDB_API_KEY))
            tv = (_tmdb_get(u).get('tv_results') or [{}])[0]
            tvid = tv.get('id')
            if tvid:
                _TMDB_TV_CACHE[imdb] = tvid
        if not tvid:
            return titles
        for sn in sorted({s for s, _ in pairs}):
            key = (tvid, sn)
            eps = _TMDB_SEASON_CACHE.get(key)
            if eps is None:
                u = ('https://api.themoviedb.org/3/tv/%d/season/%d'
                     '?api_key=%s&language=it' % (tvid, sn, TMDB_API_KEY))
                data = _tmdb_get(u)
                eps = {}
                for ep in data.get('episodes', []):
                    try:
                        eps[int(ep.get('episode_number', 0))] = ep.get('name') or ''
                    except Exception:
                        continue
                _TMDB_SEASON_CACHE[key] = eps
            for e, t in eps.items():
                if t and (sn, e) in pairs:
                    titles[(sn, e)] = t
    except Exception:
        logger.error('_episode_titles: ' + traceback.format_exc()[-200:])
    return titles


# ------------------------- menu (1.4.7 intatto) -------------------------

@support.menu
def mainlist(item):
    top = [('Film',     ['/film/',     'peliculas', '']),
           ('Serie TV', ['/serie-tv/', 'peliculas', '']),
           ('Sub-ITA',  ['/sub-ita/',  'peliculas', '']),
           ('Generi',   ['', 'genres', ''])]
    search = ''
    return locals()


# ------------------------- listati (1.4.7 intatto) -------------------------

@support.scrape
def peliculas(item):
    raw = _fetch(item.url, attempts=3)
    data = raw or ''

    urlmap = {}
    for m in _CARD_RE.finditer(data):
        urlmap[m.group('url')] = (m.group('category') or '')

    patron = _CARD_RE.pattern
    patronNext = r'<a\s+href="([^"]+)"[^>]*>&raquo;</a>'

    def itemHook(it):
        it.cb01_category = urlmap.get(it.url, '')
        return it

    def itemlistHook(itemlist):
        out = []
        for it in itemlist:
            cat = (getattr(it, 'cb01_category', '') or '').lower()
            if 'serie tv' in cat:
                it.action = 'episodios'
                it.contentType = 'tvshow'
                it.contentTitle = getattr(it, 'fulltitle', '') or it.title
            else:
                it.action = 'findvideos'
                it.contentType = 'movie'
            out.append(it)

        targets = [it for it in out
                   if 'pagina successiva' not in (it.title or '').lower()]
        if targets:
            try:
                from core import tmdb as core_tmdb
                for it in targets:
                    raw_title = getattr(it, 'fulltitle', '') or it.title or ''
                    clean = _clean_tmdb_title(raw_title)
                    yr = _extract_year(raw_title)
                    if yr and not it.infoLabels.get('year'):
                        it.infoLabels['year'] = yr
                    if it.contentType == 'tvshow':
                        if not it.infoLabels.get('tvshowtitle'):
                            it.infoLabels['tvshowtitle'] = clean
                    if not it.infoLabels.get('title'):
                        it.infoLabels['title'] = clean
                core_tmdb.set_infoLabels(targets, seekTmdb=True)
            except Exception:
                logger.error('tmdb enrichment listati: '
                             + traceback.format_exc()[-200:])
            for it in targets:
                _set_fanart(it)
        return out

    return locals()


def search(item, text):
    logger.info('search: ' + text)
    from urllib.parse import quote_plus as _qp
    item.url = host + "/index.php?do=search&subaction=search&story=" + _qp(text)
    try:
        item.args = 'search'
        return peliculas(item)
    except Exception:
        logger.error(traceback.format_exc())
    return []


# ------------------------- generi (1.4.7 intatto) -------------------------

_GENRES = [
    ('Azione', 28), ('Animazione', 16), ('Avventura', 12), ('Commedia', 35),
    ('Crime', 80), ('Documentario', 99), ('Drammatico', 18), ('Famiglia', 10751),
    ('Fantascienza', 878), ('Fantasy', 14), ('Guerra', 10752), ('Horror', 27),
    ('Poliziesco', 9648), ('Romantico', 10749), ('Storico', 36),
    ('Thriller', 53), ('Western', 37),
]


def genres(item):
    logger.info()
    itemlist = []
    for name, gtid in _GENRES:
        it = item.clone()
        it.action = 'peliculas_genere'
        it.title = name
        it.gen_id = gtid
        itemlist.append(it)
    return itemlist


def _cb01_match(title):
    try:
        surl = (host + '/index.php?do=search&subaction=search&story='
                + urllib.parse.quote_plus(title))
        sdata = _fetch(surl)
        return _CARD_RE.search(sdata) if sdata else None
    except Exception:
        logger.error('_cb01_match(%r): %s' % (title, traceback.format_exc()[-200:]))
        return None


def peliculas_genere(item):
    logger.info()
    gtid = getattr(item, 'gen_id', None)
    page = int(getattr(item, 'page', 1) or 1)
    if not gtid:
        return []

    api = ('https://api.themoviedb.org/3/discover/movie'
           '?api_key=%s&with_genres=%s&sort_by=popularity.desc'
           '&language=it&include_adult=false&page=%d'
           % (TMDB_API_KEY, gtid, page))
    results = _tmdb_get(api).get('results', [])
    if not results:
        logger.error('peliculas_genere: TMDB discover fallito')

    titles = []
    for r in results[:TMDB_GENRE_PAGE]:
        t = (r.get('title') or r.get('original_title') or '').strip()
        if t:
            titles.append((r, t))

    if ThreadPoolExecutor and len(titles) > 1:
        try:
            with ThreadPoolExecutor(max_workers=_CB01_WORKERS) as ex:
                matches = list(ex.map(lambda tt: _cb01_match(tt[1]), titles))
        except Exception:
            logger.error('pool CB01 fallito, fallback seriale: '
                         + traceback.format_exc()[-200:])
            matches = [_cb01_match(t) for _, t in titles]
    else:
        matches = [_cb01_match(t) for _, t in titles]

    itemlist = []
    serie_items = []
    for (r, title), m in zip(titles, matches):
        if not m:
            logger.info('peliculas_genere: no match su CB01: %s' % title)
            continue

        cat = (m.group('category') or '').lower()
        it = item.clone(action='findvideos',
                        url=m.group('url'),
                        title=m.group('title'))
        thumb = m.group('thumb') or ''

        poster = ('https://image.tmdb.org/t/p/original' + r['poster_path']) \
                 if r.get('poster_path') else ''
        backdrop = ('https://image.tmdb.org/t/p/original' + r['backdrop_path']) \
                   if r.get('backdrop_path') else ''

        if 'serie tv' in cat:
            it.action = 'episodios'
            it.contentType = 'tvshow'
            it.contentTitle = title
            it.infoLabels = {'tvshowtitle': title, 'title': title}
            if backdrop or poster:
                it.fanart = backdrop or poster
            serie_items.append(it)
        else:
            try:
                names = ', '.join(TMDB_GENRE_NAMES.get(g, '')
                                  for g in r.get('genre_ids', [])[:3])
                names = ', '.join(x for x in names.split(', ') if x)
                it.infoLabels = {
                    'title': r.get('title') or '',
                    'originaltitle': r.get('original_title') or '',
                    'plot': r.get('overview') or '',
                    'year': int((r.get('release_date') or '0000')[:4] or 0),
                    'rating': r.get('vote_average') or '',
                    'tmdb_id': r.get('id') or '',
                    'genre': names,
                    'thumbnail': poster,
                    'fanart': backdrop or poster,
                }
            except Exception:
                logger.error('infolabels discover: '
                             + traceback.format_exc()[-200:])

        if (it.infoLabels or {}).get('thumbnail'):
            it.thumbnail = it.infoLabels['thumbnail']
        elif thumb:
            it.thumbnail = thumb
        _set_fanart(it)
        itemlist.append(it)

    if serie_items:
        try:
            from core import tmdb as core_tmdb
            core_tmdb.set_infoLabels(serie_items, seekTmdb=True)
            for it in serie_items:
                _set_fanart(it)
        except Exception:
            logger.error('tmdb enrichment serie (generi): '
                         + traceback.format_exc()[-200:])

    if len(results) >= 20:
        nxt = item.clone(action='peliculas_genere')
        nxt.page = page + 1
        nxt.gen_id = gtid
        nxt.title = '[B][COLOR cyan]>> Pagina successiva <<[/COLOR][/B]'
        itemlist.append(nxt)
    return itemlist


# ------------------------- router di fallback -------------------------

def check(item):
    """Router di fallback (entry indirette)."""
    data = _fetch(item.url, attempts=3)
    if not data:
        return []
    if _is_tv_page(data):
        item.cached_data = data
        return episodios(item)
    item.cached_data = data
    return findvideos(item)


def episodios(item):
    """[1.5.0] Oracolo vixsrc (stagioni -> episodi) + TMDB titles
    + fallback griglia. Guardia anti-falso-serie mantenuta."""
    logger.info()

    cd = getattr(item, 'cached_data', '') or ''
    if cd and not _is_tv_page(cd):
        logger.info('episodios: la pagina e\' un film -> findvideos')
        return findvideos(item)

    data = cd or _fetch(item.url, attempts=3)
    imdb = _imdb_from_data(data)
    if not imdb:
        logger.error('episodios: IMDb non trovato su ' + item.url)
        _notify('IMDb non disponibile per questa serie')
        return []
    logger.info('episodios: imdb=%s' % imdb)

    title = getattr(item, 'contentTitle', '') or \
            getattr(item, 'fulltitle', '') or item.title

    # [1.4.7] fallback infolabels/fanart con UNA chiamata TMDB (cachata)
    try:
        if not getattr(item, 'fanart', ''):
            from core import tmdb as core_tmdb
            if not item.infoLabels.get('tvshowtitle'):
                item.infoLabels['tvshowtitle'] = title
            if not item.infoLabels.get('title'):
                item.infoLabels['title'] = title
            core_tmdb.set_infoLabels(item, seekTmdb=True)
    except Exception:
        logger.error('episodios tmdb fallback: ' + traceback.format_exc()[-200:])

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
        logger.error('episodios: oracolo stagioni KO, fallback griglia')
        return _griglia_fallback(item, imdb, title, thumb)

    return _episodi_stagione(item, imdb, season, title, thumb)


def _episodi_stagione(item, imdb, season, title, thumb):
    eps = _scopri_episodi(imdb, season)
    if not eps:
        logger.error('episodios: oracolo episodi S%d KO, fallback griglia'
                     % season)
        return _griglia_fallback(item, imdb, title, thumb, solo_stagione=season)

    pairs = [(season, e) for e in eps]
    try:
        titles = _episode_titles(imdb, pairs)
    except Exception:
        titles = {}

    itemlist = []
    for s, e in pairs:
        it = item.clone(action='findvideos')
        it.contentType = 'episode'
        it.contentSeason = s
        it.contentEpisodeNumber = e
        it.contentTitle = title
        it.title = '%dx%02d' % (s, e)
        t = titles.get((s, e))
        if t:
            it.title += ' - ' + t
        if thumb:
            it.thumbnail = thumb
        it.url = 'https://vixsrc.to/tv/%s/%d/%d?lang=it' % (imdb, s, e)
        itemlist.append(it)

    itemlist.append(_add_library_item(item, title))
    logger.info('episodios FINE (%d episodi)' % len(itemlist))
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


def addToLibrary(item):
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])


# ------------------------- findvideos -------------------------

def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    # episodio: URL gia' sintetico vixsrc
    if getattr(item, 'contentType', '') == 'episode' or \
            'vixsrc.to/tv/' in (item.url or ''):
        return _offri_server(item, item.url)

    data = getattr(item, 'cached_data', '') or _fetch(item.url, attempts=3)
    if not data:
        return []

    imdb = _imdb_from_data(data)
    if not imdb:
        logger.error('findvideos: nessun IMDb su ' + item.url)
        _notify('nessun player trovato')
        return []
    logger.info('findvideos: imdb=' + imdb)

    url = 'https://vixsrc.to/movie/%s?lang=it' % imdb
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
