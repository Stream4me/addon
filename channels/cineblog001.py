# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'CineBlog001'  (https://cineblog001.center)
# ------------------------------------------------------------
# Rev: 1.4.7  (2026-09-19)
#
# Menu: Film / Serie TV / Sub-ITA / Generi / Cerca
#
# ROUTING (fondato sul segnale PROVATO: la categoria CB01):
#   - listati: url->categoria mappata dal data; serie ('Serie TV' nel
#     blocco) -> action='episodios' (invocazione diretta, stile
#     casacinema); film -> 'findvideos'
#   - generi: categoria letta direttamente dal match _CARD_RE
#   - check(): router di fallback con _is_tv_page
#   - episodios: guardia anti-falso-serie (cached_data film -> findvideos)
#
#   [FIX 1.4.7] FANART: i generi settavano infoLabels['fanart'] ma mai
#               item.fanart (ignorata dal renderer); i listati non avevano
#               alcun dato TMDB. Ora: generi -> it.fanart esplicito;
#               listati + serie -> arricchimento con tmdb.set_infoLabels
#               (pool condiviso + cache 2 livelli + dedup del core)
#   [FIX 1.4.7] generi: item instradati come SERIE non ricevono piu'
#               tmdb_id/plot del FILM omonimo trovato da discover/movie
#               (avvelenava la videoteca); ricevono una ricerca tv dedicata
#   [PERF 1.4.7] generi: ricerche CB01 in parallelo (ThreadPool, 4 worker
#               ~25s -> ~6-8s); chiamate TMDB via Tmdb.get_json (cache+rate
#               limit) invece di _fetch nudo
#   [TUNE 1.4.7] TMDB_GENRE_PAGE 12 -> 20 (ora sostenibile: se CB01/CF
#               protesta, riportare a 12)
#   [ADD 1.4.7] episodios: fallback fanart/infolabels con 1 chiamata TMDB
#               (cachata) se l'item non ne ha gia'
#   [KEEP 1.4.6] guardia falso-serie, menu top, routing da categoria
#   [KEEP 1.4.5] tier ADX->probe, videoteca
# ------------------------------------------------------------

from core import support, httptools
from platformcode import logger
import re, html, time, traceback, json, threading, sys

try:
    from urllib.parse import quote_plus
except Exception:
    quote_plus = None

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    ThreadPoolExecutor = None

host = 'https://cineblog001.center'
if host.endswith('/'):
    host = host[:-1]

ADX_HOST = 'https://altadefinizionex.live'
TMDB_API_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_GENRE_PAGE = 20          # [1.4.7] era 12: con le ricerche in parallelo si puo' alzare
PROBE_TIMEOUT = 15
_CB01_WORKERS = 4             # [1.4.7] parallelismo ricerche CB01 (prudente: Cloudflare)

headers = [['Referer', host]]

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
    """[1.4.7] GET API TMDB con cache/rate-limit del core (Tmdb.get_json),
    fallback a _fetch + json per robustezza."""
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


def _token_from_data(data):
    m = re.search(r"imdb\s*=\s*'(tt\d{6,10})'", data, re.I)
    if m:
        return m.group(1)[2:]
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data)
    return ('tm' + m.group(1)) if m else None


def _is_tv_page(data):
    """Serie SOLO se 'Serie TV' e' nel PRIMO blocco categoria della pagina
    dettaglio (i meta dicono 'serie tv' su tutte le pagine: boilerplate)."""
    m = re.search(r'class="text-uppercase">\s*<b>\s*([^<]{0,120})',
                  data[:40000])
    return bool(m and 'serie tv' in m.group(1).lower())


def _clean_tmdb_title(txt):
    """[1.4.7] Titolo ripulito per la ricerca TMDB: via tag [..], entita'
    html e (anno) — l'anno va in infoLabels['year'], non nella query."""
    txt = html.unescape(txt or '')
    txt = re.sub(r'\[[^\]]*\]', '', txt)
    txt = re.sub(r'\(\s*\d{4}\s*\)', '', txt)
    return txt.strip()


def _extract_year(txt):
    m = re.search(r'\((\d{4})\)', html.unescape(txt or ''))
    return m.group(1) if m else ''


def _set_fanart(it):
    """[1.4.7] Propaga fanart/thumbnail da infoLabels all'item (il renderer
    legge item.fanart, non infoLabels)."""
    try:
        il = it.infoLabels or {}
        if isinstance(il, dict):
            if il.get('fanart') and not getattr(it, 'fanart', ''):
                it.fanart = il['fanart']
            if il.get('thumbnail') and not getattr(it, 'thumbnail', ''):
                it.thumbnail = il['thumbnail']
    except Exception:
        pass


# ------------------------- tier 2: probe server -------------------------

_PROBE_CACHE = {}


def _get_vdx():
    try:
        from servers import vidxgo
        return vidxgo
    except Exception:
        logger.error('servers/vidxgo mancante o rotto: '
                     + traceback.format_exc()[-200:])
        return None


def _probe_timeout(token, timeout=PROBE_TIMEOUT):
    vdx = _get_vdx()
    if not vdx:
        return None
    result = {}

    def worker():
        try:
            result['info'] = vdx.probe(token)
        except Exception:
            logger.error('probe(%s): %s' % (token, traceback.format_exc()[-200:]))
            result['info'] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.error('probe(%s) appesa > %ds: abbandono' % (token, timeout))
        return None
    return result.get('info')


def _probe_cached(token, max_age=600):
    hit = _PROBE_CACHE.get(token)
    if hit and time.time() - hit[0] < max_age:
        logger.info('probe cache hit: ' + token)
        return hit[1]
    info = _probe_timeout(token)
    if info and (info.get('mode') != 'tv' or info.get('episodes')):
        _PROBE_CACHE[token] = (time.time(), info)
    return info


# ------------------------- tier 1: sito gemello ADX -------------------------

def _pairs_from_altadefinizione(title):
    """TIER PRIMARIO: la serie sul gemello ADX (stesso token imdb-based).
    Lista episodi nell'HTML: data-episode="s-e". Ritorna (pairs, token)."""
    try:
        if not title:
            return [], None
        title = title.strip()
        surl = (ADX_HOST + '/archivio?search=' + quote_plus(title)
                + '&f=tvshow&page=1')
        sdata = _fetch(surl)
        if not sdata:
            logger.info('ADX: search senza risposta per %r' % title)
            return [], None

        cands = re.findall(
            r'href="(/serie-tv/[^"]+\.html)"[^>]*data-title="([^"]+)"', sdata)
        if not cands:
            cands = [(u, '') for u in re.findall(
                r'href="(/serie-tv/[^"]+\.html)"', sdata)]
        if not cands:
            logger.info('ADX: nessun risultato serie per %r' % title)
            return [], None

        page_path = cands[0][0]
        tl = title.lower()
        for u, t in cands:
            if t and (tl in t.lower() or t.lower() in tl):
                page_path = u
                break

        pdata = _fetch(ADX_HOST + page_path)
        if not pdata:
            return [], None

        token = None
        for m in re.finditer(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)[^"]*"',
                             pdata):
            if 'trailer' in m.group(0).lower():
                continue
            token = m.group(1)
            break
        if token is None:
            m = re.search(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)', pdata)
            token = m.group(1) if m else None
        if not token:
            logger.info('ADX: token non trovato su ' + page_path)
            return [], None

        pair_set = {(int(a), int(b))
                    for a, b in re.findall(r'data-episode="(\d+)-(\d+)"', pdata)}
        embedded = {s for s, _ in pair_set}
        seasons = sorted({int(x) for x in
                          re.findall(r'Stagione\s*(?:<!--[^>]*-->\s*)?(\d+)', pdata)})
        eps = sorted({e for _, e in pair_set}) or \
              sorted({int(x) for x in
                      re.findall(r'Episodio\s*(?:<!--[^>]*-->\s*)?(\d+)', pdata)})
        tuples = sorted(pair_set)
        for s in seasons:
            if s not in embedded:
                tuples.extend((s, e) for e in eps)
        tuples = sorted(set(tuples))
        if not tuples:
            logger.info('ADX: nessun episodio su ' + page_path)
            return [], None

        logger.info('ADX: %d episodi via %s (token %s)'
                    % (len(tuples), page_path, token))
        return tuples, token
    except Exception:
        logger.error('_pairs_from_altadefinizione: '
                     + traceback.format_exc()[-300:])
        return [], None


# ------------------------- titoli episodio (TMDB) -------------------------

_TMDB_TV_CACHE = {}
_TMDB_SEASON_CACHE = {}


def _episode_titles(token, pairs):
    titles = {}
    if not (token and token.isdigit()):
        return titles
    imdb = 'tt' + token
    try:
        # [1.4.7] via _tmdb_get: cache di core/tmdb anche qui
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
    top = [('Film',     ['/film/',     'peliculas', '']),
           ('Serie TV', ['/serie-tv/', 'peliculas', '']),
           ('Sub-ITA',  ['/sub-ita/',  'peliculas', '']),
           ('Generi',   ['', 'genres', ''])]
    search = ''
    return locals()


# ------------------------- listati -------------------------

@support.scrape
def peliculas(item):
    raw = _fetch(item.url, attempts=3)
    data = raw or ''

    # mappa url->categoria (segnale PROVATO per il routing)
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
                it.contentType = 'tvshow'      # [1.4.7] serve a tmdb.set_infoLabels
                it.contentTitle = getattr(it, 'fulltitle', '') or it.title
            else:
                it.action = 'findvideos'
                it.contentType = 'movie'
            out.append(it)

        # [1.4.7] arricchimento TMDB di TUTTE le card (fanart, plot, anno,
        # voto, tmdb_id): ricerche in parallelo e cachiate dal core tmdb.
        # Salto la voce di paginazione (ricerca TMDB inutile).
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
        return peliculas(item)      # [1.4.7] contentType deciso per-card dall'itemlistHook
    except Exception:
        logger.error(traceback.format_exc())
    return []


# ------------------------- generi (TMDB + ricerca CB01) -------------------------

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
    """[1.4.7] Ricerca CB01 per un titolo TMDB. Ritorna il match _CARD_RE o None."""
    try:
        surl = (host + '/index.php?do=search&subaction=search&story='
                + quote_plus(title))
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
    # [1.4.7] via _tmdb_get: la discover finisce in cache del core
    results = _tmdb_get(api).get('results', [])
    if not results:
        logger.error('peliculas_genere: TMDB discover fallito')

    # [1.4.7] ricerche CB01 in PARALLELO (prima seriali: ~2s x titolo)
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
    serie_items = []                      # [1.4.7] da arricchire con ricerca tv
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
            # [1.4.7] FIX: e' una SERIE ma discover/movie ha restituito un FILM
            # omonimo: niente tmdb_id/plot/anno del film (avvelenavano la
            # videoteca). Fanart provvisoria dal discover, poi ricerca tv.
            it.action = 'episodios'
            it.contentType = 'tvshow'
            it.contentTitle = title
            it.infoLabels = {'tvshowtitle': title, 'title': title}
            if backdrop or poster:
                it.fanart = backdrop or poster
            serie_items.append(it)
        else:
            # infolabels TMDB dai risultati discover (zero chiamate extra)
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
                    # [1.4.7] FIX fanart: fallback al poster se manca il backdrop
                    'fanart': backdrop or poster,
                }
            except Exception:
                logger.error('infolabels discover: '
                             + traceback.format_exc()[-200:])

        # [1.4.7] FIX fanart: item.fanart esplicito (prima solo in infoLabels)
        if (it.infoLabels or {}).get('thumbnail'):
            it.thumbnail = it.infoLabels['thumbnail']
        elif thumb:
            it.thumbnail = thumb
        _set_fanart(it)
        itemlist.append(it)

    # [1.4.7] serie trovate nei generi: infolabels/fanart corretti (ricerca tv)
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
    """Router di fallback (entry indirette): _is_tv_page sul PRIMO
    blocco categoria della pagina dettaglio."""
    data = _fetch(item.url, attempts=3)
    if not data:
        return []
    token = _token_from_data(data)

    if _is_tv_page(data):
        item.cached_data = data
        item.vidxgo_token = token
        return episodios(item)

    item.cached_data = data
    return findvideos(item)


def episodios(item):
    """Lista episodi a TIER: 1) ADX 2) probe. + guardia anti-falso-serie."""
    logger.info()

    # guardia: se abbiamo la pagina e dichiara FILM, esci
    cd = getattr(item, 'cached_data', '') or ''
    if cd and not _is_tv_page(cd):
        logger.info('episodios: la pagina e\' un film -> findvideos')
        return findvideos(item)

    token = getattr(item, 'vidxgo_token', None)
    title = getattr(item, 'contentTitle', '') or \
            getattr(item, 'fulltitle', '') or item.title
    pairs = getattr(item, 'vidxgo_pairs', None)

    # [1.4.7] fallback infolabels/fanart con UNA chiamata TMDB (cachata):
    # serve quando si entra da path non arricchiti (es. check()). Se l'item
    # ha gia' fanart (listati/generi/enrichment) la chiamata si scherma da sola.
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

    if not pairs:
        # ---- TIER 1: PIANO B altadefinizionex ----
        logger.info('episodios tier 1: PIANO B (sito gemello ADX)')
        pairs, alt_token = _pairs_from_altadefinizione(title)
        if pairs and alt_token:
            token = alt_token
            _PROBE_CACHE[token] = (time.time(),
                                   {'mode': 'tv', 'episodes': pairs})

    if not pairs:
        # ---- TIER 2: probe server ----
        if not token:
            data = _fetch(item.url)
            token = _token_from_data(data) if data else None
        if token:
            logger.info('episodios tier 2: probe server')
            info = _probe_cached(token)
            if info and info.get('mode') == 'tv':
                pairs = info['episodes']
                logger.info('episodios tier 2: %d episodi' % len(pairs))

    if not pairs:
        logger.error('episodios: nessun episodio (ADX + probe)')
        _notify('episodi non disponibili ora, riprova')
        return []
    if not token:
        logger.error('episodios: token mancante')
        _notify('token non trovato')
        return []

    try:
        titles = _episode_titles(token, pairs)
    except Exception:
        logger.error(traceback.format_exc())
        titles = {}

    itemlist = []
    for s, e in pairs:
        it = item.clone(action='findvideos')   # eredita fanart/infolabels dall'item serie
        it.contentType = 'episode'
        it.contentSeason = s
        it.contentEpisode = e
        it.contentTitle = title
        it.url = 'https://v.vidxgo.co/%s/%d/%d' % (token, s, e)
        it.title = '%dx%02d' % (s, e)
        t = titles.get((s, e))
        if t:
            it.title += ' - ' + t
        itemlist.append(it)

    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = title
    cl.fulltitle = title
    cl.show = title
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    itemlist.append(cl)

    logger.info('episodios FINE (%d episodi)' % len(itemlist))
    return itemlist


def addToLibrary(item):
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])


# ------------------------- findvideos -------------------------

def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    if s and e and '/%d/%d' % (s, e) in (item.url or ''):
        it = item.clone(action='play', server='vidxgo')
        it.contentTitle = getattr(item, 'contentTitle', '') or item.title
        return support.server(item, itemlist=[it])

    data = getattr(item, 'cached_data', '') or _fetch(item.url, attempts=3)
    if not data:
        return []

    embed_url = None

    token = _token_from_data(data)
    if token:
        embed_url = 'https://v.vidxgo.co/' + token
        logger.info('findvideos: token: ' + token)

    if not embed_url:
        for mm in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', data, re.I):
            src = html.unescape(mm.group(1)).strip()
            if src.startswith('//'):
                src = 'https:' + src
            if 'vidxgo' in src and 'trailer' not in src.lower() \
               and re.search(r'/[a-zA-Z0-9]+$', src):
                embed_url = src
                break

    if not embed_url:
        logger.error('findvideos: nessun player vidxgo su ' + item.url)
        logger.error('findvideos: head pagina: %r' % data[:300])
        _notify('nessun player trovato')
        return []

    it = item.clone(action='play', url=embed_url, server='vidxgo')
    it.title = '[COLOR lime]vidxgo[/COLOR]'
    it.contentTitle = getattr(item, 'contentTitle', '') or \
                      getattr(item, 'fulltitle', '') or item.title
    return support.server(item, itemlist=[it])
