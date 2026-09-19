# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'CineBlog001'  (https://cineblog001.center)
# ------------------------------------------------------------
# Rev: 1.4.5  (2026-09-19)
#
# Flusso:
#   mainlist -> Film / Generi / Serie-TV / Sub-ITA
#   peliculas -> action='check'
#   check: fetch -> token; serie rilevata dal testo pagina (no probe)
#          serie -> episodios (tier) / film -> findvideos (cached_data)
#   episodios a TIER (stile guardaserie):
#     1) PIANO B: sito gemello altadefinizionex — lista episodi
#        NELL'HTML (data-episode="s-e") + token iframe; passa
#        cloudscraper (provato ogni giorno dal canale ADX)
#     2) probe() del server (fallback, 15s, cache 10min)
#   findvideos: episodio diretto (/token/s/e) / film (var imdb JS)
#       -> clone(server='vidxgo') -> support.server()
#   + titoli episodio da TMDB (cache per stagione)
#   + voce "Aggiungi alla Videoteca" in fondo agli episodi
#   + Generi: infolabels/locandina/fanart TMDB dai dati discover
#
#   [ADD 1.4.5] peliculas_genere: it.infoLabels compilati con i dati
#               discover GIA' in mano (plot/anno/rating/poster/fanart,
#               genre_ids convertiti in nomi) — zero richieste extra
#   [KEEP 1.4.4] tier ADX primo / probe fallback, titoli TMDB, videoteca
# ------------------------------------------------------------

from core import support, httptools
from platformcode import logger
import re, html, time, traceback, json, threading, sys

host = 'https://cineblog001.center'
if host.endswith('/'):
    host = host[:-1]

ADX_HOST = 'https://altadefinizionex.live'      # sito gemello (stesso vidxgo)
TMDB_API_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_GENRE_PAGE = 12
PROBE_TIMEOUT = 15                               # solo fallback tier 2

headers = [['Referer', host]]

# nomi TMDB per i genre_ids del discover (infolabels dei Generi)
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


def _token_from_data(data):
    """Token vidxgo: var imdb='tt...' prima, themoviedb fallback."""
    m = re.search(r"imdb\s*=\s*'(tt\d{6,10})'", data, re.I)
    if m:
        return m.group(1)[2:]
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', data)
    return ('tm' + m.group(1)) if m else None


def _is_tv_page(data):
    """Serie rilevata dal CONTENUTO pagina (niente probe per il routing)."""
    return bool(re.search(
        r'(?:serie\s*tv|stagione\s*\d|episodio\s*\d)', data[:30000], re.I))


# ------------------------- tier 2: probe server -------------------------

_PROBE_CACHE = {}          # token -> (timestamp, {'mode','episodes'})


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
    """TIER PRIMARIO: cerca la serie sul gemello ADX (stesso token
    imdb-based vidxgo). Lista episodi nell'HTML: data-episode.
    Ritorna (pairs, token)."""
    try:
        from urllib.parse import quote_plus
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

        # match titolo (containment, case-insensitive); altrimenti il primo
        page_path = cands[0][0]
        tl = title.lower()
        for u, t in cands:
            if t and (tl in t.lower() or t.lower() in tl):
                page_path = u
                break

        pdata = _fetch(ADX_HOST + page_path)
        if not pdata:
            return [], None

        # token dall'iframe (salta i trailer)
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

        # coppie (stagione, episodio) — stessa logica del canale ADX
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

_TMDB_TV_CACHE = {}        # imdb -> tmdb tv id
_TMDB_SEASON_CACHE = {}    # (tvid, season) -> {ep_number: title}


def _episode_titles(token, pairs):
    """Titoli episodio da TMDB (miglior sforzo): un errore qui non
    deve MAI cancellare la lista."""
    titles = {}
    if not (token and token.isdigit()):
        return titles                       # token tm<id>: skip
    imdb = 'tt' + token
    try:
        tvid = _TMDB_TV_CACHE.get(imdb)
        if not tvid:
            u = ('https://api.themoviedb.org/3/find/%s'
                 '?api_key=%s&external_source=imdb_id' % (imdb, TMDB_API_KEY))
            data = json.loads(_fetch(u) or '{}')
            tv = (data.get('tv_results') or [{}])[0]
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
                data = json.loads(_fetch(u) or '{}')
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

    patron = _CARD_RE.pattern
    patronNext = r'<a\s+href="([^"]+)"[^>]*>&raquo;</a>'
    action = 'check'
    return locals()


def search(item, text):
    logger.info('search: ' + text)
    item.contentType = 'movie'
    from urllib.parse import quote_plus
    item.url = host + "/index.php?do=search&subaction=search&story=" + quote_plus(text)
    try:
        item.args = 'search'
        return peliculas(item)
    except Exception:
        logger.error(traceback.format_exc())
    return []


# ------------------------- generi (TMDB + ricerca CB01) -------------------------

_GENRES = [
    ('Azione',        28),
    ('Animazione',    16),
    ('Avventura',     12),
    ('Commedia',      35),
    ('Crime',         80),
    ('Documentario',  99),
    ('Drammatico',    18),
    ('Famiglia',      10751),
    ('Fantascienza',  878),
    ('Fantasy',       14),
    ('Guerra',        10752),
    ('Horror',        27),
    ('Poliziesco',    9648),
    ('Romantico',     10749),
    ('Storico',       36),
    ('Thriller',      53),
    ('Western',       37),
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


def peliculas_genere(item):
    """TMDB discover MOVIE (solo film per definizione) -> ricerca
    per-titolo su CB01 -> primo match card.
    [1.4.5] infolabels/locandina/fanart TMDB dai dati discover GIA'
    in mano: zero richieste extra."""
    logger.info()
    gtid = getattr(item, 'gen_id', None)
    page = int(getattr(item, 'page', 1) or 1)
    if not gtid:
        return []

    results = []
    api = ('https://api.themoviedb.org/3/discover/movie'
           '?api_key=%s&with_genres=%s&sort_by=popularity.desc'
           '&language=it&include_adult=false&page=%d'
           % (TMDB_API_KEY, gtid, page))
    tdata = _fetch(api, attempts=3)
    try:
        results = json.loads(tdata).get('results', [])
    except Exception:
        logger.error('peliculas_genere: TMDB discover fallito')

    from urllib.parse import quote_plus
    itemlist = []
    for r in results[:TMDB_GENRE_PAGE]:
        title = (r.get('title') or r.get('original_title') or '').strip()
        if not title:
            continue
        surl = (host + '/index.php?do=search&subaction=search&story='
                + quote_plus(title))
        sdata = _fetch(surl)
        m = _CARD_RE.search(sdata)
        if not m:
            logger.info('peliculas_genere: no match su CB01: %s' % title)
            continue
        it = item.clone(action='check',
                        url=m.group('url'),
                        title=m.group('title'))
        it.contentTitle = m.group('title')

        # [1.4.5] infolabels TMDB dai risultati discover (zero chiamate)
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
                'thumbnail': ('https://image.tmdb.org/t/p/original'
                              + r['poster_path']) if r.get('poster_path') else '',
                'fanart': ('https://image.tmdb.org/t/p/original'
                           + r['backdrop_path']) if r.get('backdrop_path') else '',
            }
            # locandina TMDB (qualita' costante) con fallback CB01
            if it.infoLabels['thumbnail']:
                it.thumbnail = it.infoLabels['thumbnail']
            else:
                it.thumbnail = m.group('thumb') or ''
        except Exception:
            logger.error('infolabels discover: '
                         + traceback.format_exc()[-200:])
            it.thumbnail = m.group('thumb') or ''

        itemlist.append(it)

    if len(results) >= 20:
        nxt = item.clone(action='peliculas_genere')
        nxt.page = page + 1
        nxt.gen_id = gtid
        nxt.title = '[B][COLOR cyan]>> Pagina successiva <<[/COLOR][/B]'
        itemlist.append(nxt)
    return itemlist


# ------------------------- router serie/film -------------------------

def check(item):
    """Router: serie dal testo pagina -> episodios (tier); film -> findvideos."""
    data = _fetch(item.url, attempts=3)
    if not data:
        return []
    token = _token_from_data(data)

    if _is_tv_page(data):
        if not token:
            logger.error('check: serie senza token su ' + item.url)
            _notify('serie: token non trovato')
            return []
        item.cached_data = data
        item.vidxgo_token = token
        return episodios(item)

    item.cached_data = data
    return findvideos(item)


def episodios(item):
    """Lista episodi a TIER: 1) ADX (gemello, veloce) 2) probe (fallback).
    + titoli TMDB + voce videoteca."""
    logger.info()
    token = getattr(item, 'vidxgo_token', None)
    title = getattr(item, 'contentTitle', '') or \
            getattr(item, 'fulltitle', '') or item.title
    pairs = getattr(item, 'vidxgo_pairs', None)

    if not pairs:
        # ---- TIER 1: PIANO B altadefinizionex (veloce, affidabile) ----
        logger.info('episodios tier 1: PIANO B (sito gemello ADX)')
        pairs, alt_token = _pairs_from_altadefinizione(title)
        if pairs and alt_token:
            token = alt_token
            _PROBE_CACHE[token] = (time.time(),
                                   {'mode': 'tv', 'episodes': pairs})

    if not pairs and token:
        # ---- TIER 2: probe server (fallback) ----
        logger.info('episodios tier 2: probe server')
        info = _probe_cached(token)
        if info and info.get('mode') == 'tv':
            pairs = info['episodes']
            logger.info('episodios tier 2: %d episodi da probe' % len(pairs))

    if not pairs:
        logger.error('episodios: nessun episodio (ADX + probe)')
        _notify('episodi non disponibili ora, riprova')
        return []

    if not token:
        logger.error('episodios: token mancante a fine tier')
        _notify('token non trovato')
        return []

    # titoli episodio (TMDB, best effort)
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
        it.contentTitle = title
        it.url = 'https://v.vidxgo.co/%s/%d/%d' % (token, s, e)
        it.title = '%dx%02d' % (s, e)
        t = titles.get((s, e))
        if t:
            it.title += ' - ' + t
        itemlist.append(it)

    # voce videoteca in fondo (il canale espone addToLibrary)
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
    """Instradato dal launcher (getattr(channel, item.action))."""
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])


# ------------------------- findvideos -------------------------

def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    # episodio diretto (da episodios: URL gia' pronto)
    if s and e and '/%d/%d' % (s, e) in (item.url or ''):
        it = item.clone(action='play', server='vidxgo')
        it.contentTitle = getattr(item, 'contentTitle', '') or item.title
        return support.server(item, itemlist=[it])

    data = getattr(item, 'cached_data', '') or _fetch(item.url, attempts=3)
    if not data:
        return []

    embed_url = None

    # V1: token dal JS (solo cifre)
    token = _token_from_data(data)
    if token:
        embed_url = 'https://v.vidxgo.co/' + token
        logger.info('findvideos: token: ' + token)

    # V2: iframe vidxgo completo
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
