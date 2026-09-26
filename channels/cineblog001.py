# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'CineBlog001'  (https://cineblog001.download)
# ------------------------------------------------------------
# Rev: 1.5.5a  (2026-09-26)
#
# Menu: Film / Serie TV / Sub-ITA / Al Cinema / Per paese / Generi / Cerca
#
# [1.5.5a] FIX CATALOGO:
#   - version-tag nella cache (_CATALOG_PV): il bump del tag invalida
#     automaticamente le vecchie cache OVUNQUE vivano (Kodi/osmc
#     imposta spesso TMPDIR proprio: la cache NON era in /tmp!)
#   - log del percorso cache reale
#   - sanitizzazione BBCode ([B]...) sui titoli scrapati del menu paesi
#     (il framework incollava [B]Giappone[/B] -> match fallito)
#   - _COUNTRY_ALIASES estesi coi nomi en visti NEL CATALOGO REALE
#     (Hungary, Yugoslavia, Serbia and Montenegro, Switzerland...)
# [1.5.5] PER PAESE SCAN-BASED: verificate le pagine /xfsearch/country/
#   (esistono ma NON filtrano: elencano la home) e il modulo sfilter
#   (DOM puro, nessun endpoint) -> il paese si legge dalla CARD:
#   la categoria cattura l'INTERO blocco <b> (che include i paesi:
#   "Avventura/Drammatico – DURATA 97' – Germania, Hungary, Greece").
#   Menu paesi scrapato dal filtro home (radio name="country").
#   Paginazione client-side 12/page, catalogo scan cache 24h.
# [1.5.3/1.5.3b] GENERI SCAN-BASED + paginazione client-side
# [1.5.0] MIGRAZIONE vidxgo -> vixsrc: oracolo API (stagioni/episodi
#   reali, cache 3 giorni, fallback griglia), playback vixsrc + ALT,
#   titoli episodi TMDB, tm->tt paracadute
# [KEEP 1.4.7] _CARD_RE, routing per categoria, check/_is_tv_page,
#   enrichment listati, guardia anti-falso-serie, videoteca
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

TMDB_API = 'https://api.themoviedb.org/3'
TMDB_API_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
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

# ------------------------- catalogo scan -------------------------

_CATALOG_CACHE_FILE = os.path.join(tempfile.gettempdir(),
                                   's4me_cb01_catalog.json')
_CATALOG_TTL = 24 * 3600
_CATALOG_PV = 'v2'       # bump quando cambia _CARD_RE: invalida cache ovunque
_CATALOG = None

_SERIES_GENRES_FILE = os.path.join(tempfile.gettempdir(),
                                   's4me_cb01_series_genres.json')
_SERIES_GENRES = None

_TMDB_TV_GENRE_NAMES = {
    10759: ['Azione', 'Avventura'], 16: ['Animazione'], 35: ['Commedia'],
    80: ['Crime'], 99: ['Documentario'], 18: ['Drammatico'],
    10751: ['Famiglia'], 10762: ['Bambini'], 9648: ['Poliziesco', 'Mistero'],
    10763: ['News'], 10764: ['Reality'], 10765: ['Fantascienza', 'Fantasy'],
    10766: ['Soap'], 10767: ['Talk'], 10768: ['Guerra', 'Politica'],
    37: ['Western'],
}

_GENRE_ALIASES = {
    'crime': ['crime', 'poliziesco', 'gangster'],
    'fantasy': ['fantasy', 'fantastico'],
    'fantascienza': ['fantascienza', 'science fiction', 'sci-fi'],
    'poliziesco': ['poliziesco', 'mistero', 'giallo'],
    'guerra': ['guerra', 'bellico'],
}

# [1.5.5a] le card usano nomi it/en MISTI (visti nel catalogo reale:
# "Germania, Hungary, Greece", "Yugoslavia", "Serbia and Montenegro",
# "Switzerland", "Belgium", "Paesi Bassi", "stati uniti"...)
_COUNTRY_ALIASES = {
    'italia':      ['italia'],
    'stati uniti': ['usa', 'united states', 'stati uniti', 'american'],
    'regno unito': ['regno unito', 'united kingdom', 'uk', 'gran bretagna',
                    'british'],
    'spagna':      ['spagna', 'spain'],
    'francia':     ['francia', 'france'],
    'germania':    ['germania', 'germany'],
    'canada':      ['canada'],
    'giappone':    ['giappone', 'japan'],
    'india':       ['india'],
    'australia':   ['australia'],
    'russia':      ['russia'],
    'belgio':      ['belgio', 'belgium'],
    'messico':     ['messico', 'mexico'],
    'brasile':     ['brasile', 'brazil'],
    'polonia':     ['polonia', 'poland'],
    'norvegia':    ['norvegia', 'norway'],
    # extra visti nel catalogo reale
    'svizzera':    ['svizzera', 'switzerland'],
    'ungheria':    ['ungheria', 'hungary'],
    'grecia':      ['grecia', 'greece'],
    'turchia':     ['turchia', 'turkey'],
    'serbia':      ['serbia', 'yugoslavia', 'serbia and montenegro'],
    'paesi bassi': ['paesi bassi', 'netherlands', 'holland'],
}

# [1.5.5] TUTTO il blocco <b> (include generi E paesi dentro <a>)
_CARD_RE = re.compile(
    r'<article\s+class="short\s+block-list">\s*'
    r'<div\s+class="story-cover">\s*'
    r'<a\s+href="(?P<url>[^"]+)"\s+title="(?P<title>[^"]*)"[^>]*>\s*'
    r'<img[^>]+data-src="(?P<thumb>[^"]+)"'
    r'(?:[\s\S]*?<div\s+class="text-uppercase">\s*<b>(?P<category>.*?)</b>)?'
)


def _clean_cat(cat):
    """[1.5.5] blocco <b> grezzo -> testo pulito (via tag, entita',
    spazi doppi): 'Avventura/Drammatico – DURATA 97' – Germania, Hungary'."""
    if not cat:
        return ''
    cat = re.sub(r'<[^>]+>', ' ', cat)
    cat = html.unescape(cat)
    cat = re.sub(r'\s+', ' ', cat)
    return cat.strip()


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


TMDB_ID_CACHE = {}


def _imdb_from_tm(tm_id):
    """tmN -> tt via TMDB external_ids (movie poi tv)."""
    key = 'imdb:tm' + tm_id
    if key in TMDB_ID_CACHE:
        return TMDB_ID_CACHE[key]
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
    TMDB_ID_CACHE[key] = imdb
    if imdb:
        logger.info('tm->tt: tm%s -> %s' % (tm_id, imdb))
    return imdb


def _imdb_from_data(data):
    """IMDb COMPLETO (tt...) dalla pagina dettaglio."""
    m = re.search(r"imdb\s*=\s*'(tt\d{6,10})'", data or '', re.I)
    if m:
        return m.group(1)
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data or '')
    if m:
        return _imdb_from_tm(m.group(1))
    return ''


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


def _cb01_listing_hook(it):
    """Thumbnail assoluta, IMDb dal poster ttXXXX.jpg; [ITA] [HD] (anno)
    -> quality/anno."""
    try:
        t = html.unescape(it.title or '').strip()
        m = re.match(r'^(.*?)\s*\[(ITA[^\]]*)\]\s*\[(HD[^\]]*)\]\s*\((\d{4})\)\s*$', t)
        if m:
            t, q1, q2, anno = m.groups()
            it.title = t.strip()
            try:
                it.infoLabels['year'] = int(anno)
            except Exception:
                pass
            it.title += support.typo(q1 + ' ' + q2, ' [] color std')
        th = it.thumbnail or ''
        if th.startswith('//'):
            th = 'https:' + th
        elif th.startswith('/'):
            th = host + th
        it.thumbnail = th
        m2 = re.search(r'(tt\d+)\.jpg', th)
        if m2:
            il = dict(getattr(it, 'infoLabels', {}) or {})
            il['imdb_id'] = m2.group(1)
            it.infoLabels = il
    except Exception:
        pass
    return it


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


# ------------------------- CATALOGO SCAN -------------------------

def _ccache_load():
    global _CATALOG
    if _CATALOG is None:
        try:
            with open(_CATALOG_CACHE_FILE) as f:
                _CATALOG = json.load(f)
            logger.info('cb01 catalogo: cache in %s' % _CATALOG_CACHE_FILE)
        except Exception:
            _CATALOG = {}
    return _CATALOG


def _ccache_save(cat):
    try:
        with open(_CATALOG_CACHE_FILE, 'w') as f:
            json.dump(cat, f)
    except Exception:
        pass


def _scan_catalog(force=False):
    """Scansione di /film/ e /serie-tv/ (tutte le pagine).
    Ritorna {url: {title, thumb, category pulita}}. Cache su disco 24h.
    [1.5.5a] version-tag (_CATALOG_PV): il bump invalida le cache vecchie
    ovunque vivano (Kodi imposta spesso TMPDIR proprio)."""
    cat = _ccache_load()
    now = time.time()
    if not force and cat.get('pv') == _CATALOG_PV \
            and cat.get('ts') and (now - cat.get('ts', 0)) < _CATALOG_TTL \
            and cat.get('items'):
        return cat['items']

    items = {}
    for base in ('/film/', '/serie-tv/'):
        page = 1
        while page <= 30:                       # limite difensivo
            url = host + base if page == 1 \
                else '%s%spage/%d/' % (host, base, page)
            data = _fetch(url, attempts=2)
            if not data:
                break
            found = 0
            for m in _CARD_RE.finditer(data):
                u = m.group('url')
                if u in items:
                    continue
                items[u] = {'title': html.unescape(m.group('title') or ''),
                            'thumb': m.group('thumb') or '',
                            'category': _clean_cat(m.group('category'))}
                found += 1
            logger.info('scan catalogo %s p%d: +%d (tot %d)'
                        % (base, page, found, len(items)))
            if not found:
                break
            page += 1

    if items:
        _CATALOG = {'ts': now, 'pv': _CATALOG_PV, 'items': items}
        _ccache_save(_CATALOG)
        logger.info('scan catalogo COMPLETO: %d titoli' % len(items))
    return items or (cat.get('items') or {})


def _sgenres_load():
    global _SERIES_GENRES
    if _SERIES_GENRES is None:
        try:
            with open(_SERIES_GENRES_FILE) as f:
                _SERIES_GENRES = json.load(f)
        except Exception:
            _SERIES_GENRES = {}
    return _SERIES_GENRES


def _sgenres_save():
    try:
        with open(_SERIES_GENRES_FILE, 'w') as f:
            json.dump(_SERIES_GENRES or {}, f)
    except Exception:
        pass


def _sgenres_for(prov_items):
    """Generi TMDB (nomi italiani) per le serie: ricerca parallela,
    cache persistente. Ritorna {url: [nomi]}."""
    sg = _sgenres_load()
    todo = [it for it in prov_items if it.url not in sg]

    def worker(it):
        try:
            t = _clean_tmdb_title(getattr(it, 'fulltitle', '') or it.title)
            u = ('https://api.themoviedb.org/3/search/tv?api_key=%s'
                 '&query=%s&language=it&include_adult=false&page=1'
                 % (TMDB_API_KEY, urllib.parse.quote_plus(t)))
            res = (_tmdb_get(u).get('results') or [{}])[0]
            names = []
            for gid in res.get('genre_ids', []):
                names.extend(_TMDB_TV_GENRE_NAMES.get(gid, []))
            sg[it.url] = names
        except Exception:
            sg[it.url] = []

    if todo:
        if ThreadPoolExecutor and len(todo) > 1:
            try:
                with ThreadPoolExecutor(max_workers=_CB01_WORKERS) as ex:
                    list(ex.map(worker, todo))
            except Exception:
                for it in todo:
                    worker(it)
        else:
            for it in todo:
                worker(it)
        _sgenres_save()
        logger.info('generi serie TMDB: %d risolte' % len(todo))
    return sg


def _genre_hit(text, gname):
    """Match del genere sul testo della categoria (con alias)."""
    t = (text or '').lower()
    if not t:
        return False
    gl = gname.lower()
    if gl in t:
        return True
    for alias in _GENRE_ALIASES.get(gl, []):
        if alias in t:
            return True
    return False


def _country_hit(text, cname):
    """[1.5.5a] Match del paese sul testo categoria (con alias it/en)."""
    t = (text or '').lower()
    if not t:
        return False
    for alias in _COUNTRY_ALIASES.get(cname.lower(), [cname.lower()]):
        if alias in t:
            return True
    return False


# ------------------------- titoli episodio (TMDB) -------------------------

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


# ------------------------- menu -------------------------

@support.menu
def mainlist(item):
    top = [('Film',      ['/film/',     'peliculas', '']),
           ('Serie TV',  ['/serie-tv/', 'peliculas', '']),
           ('Sub-ITA',   ['/sub-ita/',  'peliculas', '']),
           ('Al Cinema', ['/cinema/',   'peliculas', '']),
           ('Per paese', ['', 'paese', '']),
           ('Generi',    ['', 'genres', ''])]
    search = ''
    return locals()


# ------------------------- listati -------------------------

@support.scrape
def peliculas(item):
    raw = _fetch(item.url, attempts=3)
    data = raw or ''

    urlmap = {}
    for m in _CARD_RE.finditer(data):
        urlmap[m.group('url')] = _clean_cat(m.group('category'))

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


# ------------------------- PER PAESE [1.5.5] -------------------------

@support.scrape
def paese(item):
    """Paesi SCRAPATI dal blocco filtro della home (sfilter: radio
    name="country"). Nessuna lista hardcodata."""
    logger.info()
    action = 'peliculas_paese'
    patronBlock = (r'<div class="filter-name">\s*Paese\s*</div>'
                   r'(?P<block>.*?)<div class="filter-btn">')
    patron = (r'<input[^>]+name="country"[^>]+value="(?P<url>[^"]+)"'
              r'[^>]*>\s*<label[^>]*>(?P<title>[^<]+)</label>')

    def itemHook(it):
        slug = (it.url or '').strip().lower().replace(' ', '-')
        it.paese_slug = slug
        # [1.5.5a] il framework puo' incollare BBCode al titolo scrapato
        name = re.sub(r'\[/?(?:B|I|COLOR[^\]]*)\]', '', (it.title or ''),
                      flags=re.I).strip()
        it.paese_name = name
        it.title = name
        return it

    return locals()


def peliculas_paese(item):
    """[1.5.5] FILTRO LOCALE: le card portano il paese nel testo categoria
    ('Avventura/Drammatico – DURATA 97' – Germania, Hungary, Greece').
    Le pagine /xfsearch/country/ esistono ma NON filtrano (elencano la
    home). Paginazione client-side 12/page, catalogo scan cache 24h."""
    logger.info()
    gname = (getattr(item, 'paese_name', '') or '').strip()
    # [1.5.5a] sanitizza BBCode eventualmente incollato dal framework
    gname = re.sub(r'\[/?(?:B|I|COLOR[^\]]*)\]', '', gname,
                   flags=re.I).strip()
    if not gname:
        return []

    try:
        gpage = int(getattr(item, 'gpage', 1) or 1)
    except Exception:
        gpage = 1

    catalog = _scan_catalog()
    if not catalog:
        logger.error('peliculas_paese: catalogo vuoto (scan fallito)')
        return []

    full = []
    for url, rec in catalog.items():
        if _country_hit(rec.get('category'), gname):
            it = item.clone(action='findvideos', url=url,
                            title=rec.get('title', ''))
            th = rec.get('thumb') or ''
            if th.startswith('//'):
                th = 'https:' + th
            elif th.startswith('/'):
                th = host + th
            it.thumbnail = th
            cat = (rec.get('category') or '').lower()
            if 'serie tv' in cat:
                it.action = 'episodios'
                it.contentType = 'tvshow'
                it.contentTitle = getattr(it, 'fulltitle', '') or it.title
            else:
                it.contentType = 'movie'
            full.append(it)

    logger.info('peliculas_paese [%s]: %d titoli'
                % (gname, len(full)))

    # ---- paginazione client-side (12 per pagina) ----
    PAGE_SIZE = 12
    start = (gpage - 1) * PAGE_SIZE
    page_items = full[start:start + PAGE_SIZE]

    # TMDB enrichment solo sulla pagina visibile
    if page_items:
        try:
            from core import tmdb as core_tmdb
            for it in page_items:
                if not it.infoLabels.get('title'):
                    it.infoLabels['title'] = _clean_tmdb_title(it.title)
                if it.contentType == 'tvshow' and \
                        not it.infoLabels.get('tvshowtitle'):
                    it.infoLabels['tvshowtitle'] = it.infoLabels['title']
            core_tmdb.set_infoLabels(page_items, seekTmdb=True)
            for it in page_items:
                _set_fanart(it)
        except Exception:
            logger.error('tmdb enrichment paese: '
                         + traceback.format_exc()[-200:])

    if start + PAGE_SIZE < len(full):
        nxt = item.clone(action='peliculas_paese',
                         url=getattr(item, 'url', ''))
        nxt.paese_name = gname
        nxt.gpage = gpage + 1
        nxt.title = '[B][COLOR cyan]>> Pagina successiva (%d) <<[/COLOR][/B]' \
                    % (len(full) - start - PAGE_SIZE)
        page_items.append(nxt)

    return page_items


# ------------------------- generi (scan catalogo + filtro locale) -------------------------

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
        it.gname = name
        itemlist.append(it)
    return itemlist


def peliculas_genere(item):
    """GENERI VERI: scan del catalogo CB01 + filtro locale.
    Film: categoria scritta sulla card ("Drammatico/Thriller...").
    Serie: generi via TMDB (cache persistente, ricerca parallela).
    Paginazione client-side 12/page."""
    logger.info()
    gname = (getattr(item, 'gname', '') or '').strip()
    if not gname:
        return []
    gl = gname.lower()

    try:
        gpage = int(getattr(item, 'gpage', 1) or 1)
    except Exception:
        gpage = 1

    catalog = _scan_catalog()
    if not catalog:
        logger.error('peliculas_genere: catalogo vuoto (scan fallito)')
        return []

    film_recs = [(u, r) for u, r in catalog.items()
                 if 'serie tv' not in (r.get('category') or '').lower()
                 and _genre_hit(r.get('category'), gname)]
    serie_recs = [(u, r) for u, r in catalog.items()
                  if 'serie tv' in (r.get('category') or '').lower()]

    full = []

    # ---- film: match diretto sulla categoria della card ----
    for url, rec in film_recs:
        it = item.clone(action='findvideos', url=url,
                        title=rec.get('title', ''))
        it.contentType = 'movie'
        th = rec.get('thumb') or ''
        if th.startswith('//'):
            th = 'https:' + th
        elif th.startswith('/'):
            th = host + th
        it.thumbnail = th
        full.append(it)

    # ---- serie: generi via TMDB (cache persistente) ----
    if serie_recs:
        prov = []
        for url, rec in serie_recs:
            it = item.clone(url=url, title=rec.get('title', ''))
            prov.append(it)
        sgmap = _sgenres_for(prov)
        for it in prov:
            names = [n.lower() for n in (sgmap.get(it.url) or [])]
            if gl in names:
                it2 = item.clone(action='episodios', url=it.url,
                                 title=it.title)
                it2.contentType = 'tvshow'
                it2.contentTitle = getattr(it, 'fulltitle', '') or it.title
                rec = catalog.get(it.url) or {}
                th = rec.get('thumb') or ''
                if th.startswith('//'):
                    th = 'https:' + th
                elif th.startswith('/'):
                    th = host + th
                if th:
                    it2.thumbnail = th
                full.append(it2)

    logger.info('peliculas_genere [%s]: %d titoli (film %d, serie %d)'
                % (gname, len(full), len(film_recs), len(serie_recs)))

    # ---- paginazione client-side (12 per pagina) ----
    PAGE_SIZE = 12
    start = (gpage - 1) * PAGE_SIZE
    page_items = full[start:start + PAGE_SIZE]

    # TMDB enrichment solo sulla pagina visibile (veloce)
    if page_items:
        try:
            from core import tmdb as core_tmdb
            for it in page_items:
                if not it.infoLabels.get('title'):
                    it.infoLabels['title'] = _clean_tmdb_title(it.title)
            core_tmdb.set_infoLabels(page_items, seekTmdb=True)
            for it in page_items:
                _set_fanart(it)
        except Exception:
            logger.error('tmdb enrichment generi: '
                         + traceback.format_exc()[-200:])

    if start + PAGE_SIZE < len(full):
        nxt = item.clone(action='peliculas_genere',
                         url=getattr(item, 'url', ''))
        nxt.gname = gname
        nxt.gpage = gpage + 1
        nxt.title = '[B][COLOR cyan]>> Pagina successiva (%d) <<[/COLOR][/B]' \
                    % (len(full) - start - PAGE_SIZE)
        page_items.append(nxt)

    return page_items


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
    """Oracolo vixsrc (stagioni -> episodi) + TMDB titles
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
