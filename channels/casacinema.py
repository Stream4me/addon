# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'casacinema'
#
# Rev: 1.4
# Update: 2026-09-20
#
# Flusso:
#   - film    : peliculas -> findvideos -> play (token vidxgo da IMDb/TMDB)
#   - serie   : peliculas -> episodios (TIER: Next.js ADX -> PIANO A)
#               -> findvideos -> play
#   - libreria: "Aggiungi alla videoteca" in fondo alla lista episodi
#
# FIX 1.3 [tm->tt]: i token 'tmN' appendo il server: converte in IMDb
#   via TMDB external_ids prima di passare al server; notifica se no.
#
# NUOVO 1.4 [TIER ADX]: per gli episodi, prima il PAYLOAD NEXT.JS del
#   sito gemello altadefinizionex (stessa serie = stesso token imdb-based;
#   stagioni/episodi/titoli/plot/still STRUTTURATI in pagina, zero
#   chiamate al server vidxgo). Fallback: PIANO A (get_embed_page +
#   discovery stagioni). Metodo a cura del collega (via altadefinizionex).
# ------------------------------------------------------------

from core import support, httptools
from platformcode import logger
import re, sys, json, threading, traceback, urllib.parse

host = support.config.get_channel_url()
headers = [['Referer', host]]

ADX_HOST = 'https://altadefinizionex.live'

FETCH_TIMEOUT = 45
MAX_SEASON = 30
PAIRS_CACHE = {}      # token -> [(s, e), ...]
NEXT_CACHE = {}       # titolo.lower() -> (token, pairs, titles, meta)


def _notify(msg):
    try:
        import xbmcgui
        xbmcgui.Dialog().notification('casacinema', msg,
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
    except Exception:
        pass


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
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


@support.scrape
def peliculas(item):
    action = 'findvideos'
    patron = r'<div class="posts".*?<a href="(?P<url>[^"]+)[^>]+>[^>]+>[^>]+>(?P<title>[^\(\[<]+)(?:\[(?P<quality1>HD)\])?'
    patronNext = r'<a href="([^"]+)"\s*>Pagina'

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
                it.action = 'episodios'
                it.context = "['addToLibrary']"
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


def _imdb_from_tm(token):
    """[FIX 1.3] 'tmN' -> cifre IMDb via TMDB external_ids (movie poi tv)."""
    key = 'imdb:' + token
    if key in TMDB_ID_CACHE:
        return TMDB_ID_CACHE[key]
    tmdb_id = token[2:]
    imdb = None
    for kind in ('movie', 'tv'):
        try:
            url = '%s/%s/%s/external_ids?api_key=%s' % (
                TMDB_API, kind, tmdb_id, TMDB_KEY)
            j = json.loads(httptools.downloadpage(url).data or '{}')
            v = j.get('imdb_id') or ''
            if v.startswith('tt') and v[2:].isdigit():
                imdb = v[2:]
                break
        except Exception:
            logger.error('_imdb_from_tm: ' + traceback.format_exc()[-200:])
    TMDB_ID_CACHE[key] = imdb
    logger.info('tm->tt: %s -> %s' % (token, imdb))
    return imdb


def _token_for_server(token):
    """[FIX 1.3] tm -> IMDb (il server appende su tm). None se non convertibile."""
    if not token.startswith('tm'):
        return token
    imdb = _imdb_from_tm(token)
    if imdb:
        return imdb
    logger.error('token tm non convertibile in IMDb: ' + token)
    _notify('player non disponibile per questo titolo (tm)')
    return None


def _get_embed(url):
    """get_embed_page del server: sessione TLS-rotata (PIANO A)."""
    result = {}

    def worker():
        try:
            from servers import vidxgo as srv_v
            result['page'] = srv_v.get_embed_page(url, referer=host + '/') or ''
        except Exception:
            logger.error('get_embed_page EXCEPTION su ' + url)
            result['page'] = ''
        result['done'] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(FETCH_TIMEOUT)
    if not result.get('done'):
        logger.error('get_embed_page TIMEOUT su {}'.format(url))
        return ''
    return result.get('page', '')


# ------------------------- TIER 1: payload Next.js di ADX -------------------------

def _estrai_next_json(data):
    """Chunk self.__next_f di Next.js -> (token, seasons).
    (metodo del collega, via altadefinizionex)"""
    token = None
    seasons = []
    if not data:
        return token, seasons
    for m in re.finditer(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', data, re.S):
        raw = m.group(1)
        try:
            chunk = json.loads('"' + raw + '"')
        except Exception:
            continue
        if token is None:
            mt = re.search(r'"token":"(\d+)"', chunk)
            if mt:
                token = mt.group(1)
        if not seasons:
            ms = re.search(r'"seasons":(\[.*?\])\s*,\s*"turnstileSiteKey"', chunk, re.S)
            if ms:
                try:
                    seasons = json.loads(ms.group(1))
                except Exception:
                    seasons = []
        if token and seasons:
            break
    return token, seasons


def _next_pairs_and_meta(seasons):
    """seasons Next.js -> (pairs [(s,e)...], meta {(s,e): {...}})."""
    pairs = []
    meta = {}
    for st in seasons or []:
        s = st.get('number')
        if not s:
            continue
        for ep in st.get('episodes', []) or []:
            e = ep.get('number')
            if not e:
                continue
            key = (int(s), int(e))
            pairs.append(key)
            meta[key] = {
                'title': (ep.get('title') or '').strip(),
                'plot':  (ep.get('plot') or '').strip(),
                'still': (ep.get('still') or '').strip(),
            }
    pairs.sort()
    return pairs, meta


def _pairs_via_next(title):
    """TIER 1: cerca la serie su ADX (Next.js) e legge il payload:
    token + stagioni/episodi/titoli/plot/still in una fetch.
    Ritorna (token, pairs, titles, meta) o (None, [], {}, {})."""
    try:
        if not title:
            return None, [], {}, {}
        title = title.strip()
        surl = (ADX_HOST + '/archivio?search='
                + urllib.parse.quote(title) + '&f=tvshow&page=1')
        sdata = httptools.downloadpage(surl, cloudscraper=True).data or ''
        if not sdata:
            logger.info('ADX-next: search senza risposta per %r' % title)
            return None, [], {}, {}

        cands = re.findall(
            r'href="(/serie-tv/[^"]+\.html)"[^>]*data-title="([^"]+)"', sdata)
        if not cands:
            cands = [(u, '') for u in
                     re.findall(r'href="(/serie-tv/[^"]+\.html)"', sdata)]
        if not cands:
            logger.info('ADX-next: nessun risultato per %r' % title)
            return None, [], {}, {}

        page_path = cands[0][0]
        tl = title.lower()
        for u, t in cands:
            if t and (tl in t.lower() or t.lower() in tl):
                page_path = u
                break

        pdata = httptools.downloadpage(ADX_HOST + page_path,
                                       cloudscraper=True).data or ''
        if not pdata:
            return None, [], {}, {}

        token, seasons = _estrai_next_json(pdata)
        pairs, meta = _next_pairs_and_meta(seasons)
        if not (token and pairs):
            logger.info('ADX-next: payload senza token/seasons su ' + page_path)
            return None, [], {}, {}

        titles = {k: m['title'] for k, m in meta.items() if m.get('title')}
        logger.info('ADX-next: %d episodi, %d stagioni (titoli %d) via %s'
                    % (len(pairs), len({s for s, _ in pairs}), len(titles),
                       page_path))
        return token, pairs, titles, meta
    except Exception:
        logger.error('_pairs_via_next: ' + traceback.format_exc()[-300:])
        return None, [], {}, {}


# ------------------------- TIER 2: PIANO A (server) -------------------------

TMDB_API = 'https://api.themoviedb.org/3'
TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
TMDB_LANG = 'it'

TMDB_ID_CACHE = {}
SEASON_TITLES = {}


def _tmdb_id_from_token(token):
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
    return tmdb_id


def _season_titles(tmdb_id, s):
    key = (tmdb_id, s)
    if key in SEASON_TITLES:
        return SEASON_TITLES[key]
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
    SEASON_TITLES[key] = out
    return out


def _episode_titles(token, pairs):
    titles = {}
    tmdb_id = _tmdb_id_from_token(token)
    if not tmdb_id:
        return titles
    for s in sorted({s for s, _ in pairs}):
        for n, name in _season_titles(tmdb_id, s).items():
            titles[(s, n)] = name
    return titles


def _pairs_from_site_html(data):
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
        pairs = set(_pairs_from_site_html(page))
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
        logger.error('pagina player: formato episodi non riconosciuto')
    return []


def _pairs_via_server(token, quiet=False):
    """PIANO A (fallback): embed via TLS del server + discovery stagioni."""
    page = _get_embed('https://v.vidxgo.co/' + token)
    if not page:
        return []
    if 'Access Denied' in page[:3000]:
        return []
    pairs = set(_parse_page_pairs(page, token, quiet=quiet))
    seasons = sorted({s for s, _ in pairs})
    if seasons and seasons[-1] < MAX_SEASON:
        s = seasons[-1]
        while s < MAX_SEASON:
            s += 1
            p2 = _get_embed('https://v.vidxgo.co/%s/%d/1' % (token, s))
            if not p2 or 'Access Denied' in p2[:3000]:
                break
            if ('/%s/%d/' % (token, s)) not in p2:
                break
            new = {(ps, pe) for ps, pe in
                   _parse_page_pairs(p2, token, quiet=True) if ps == s}
            if not new:
                break
            pairs |= new
    out = sorted(pairs)
    if out:
        logger.info('PIANO A: {} episodi'.format(len(out)))
    return out


def _episode_list(item, pairs, token=None, titles=None, meta=None):
    """Directory episodi (action='findvideos'). Titoli da Next.js se
    presenti, altrimenti da TMDB."""
    if titles is None:
        try:
            titles = _episode_titles(token, pairs) if token else {}
        except Exception:
            titles = {}
    meta = meta or {}

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
        m = meta.get((s, e), {})
        if m.get('plot'):
            it.plot = m['plot']
        if m.get('still'):
            it.thumbnail = m['still']
        itemlist.append(it)

    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = item.contentTitle or item.fulltitle
    cl.fulltitle = cl.contentTitle
    cl.show = cl.contentTitle
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    itemlist.append(cl)
    return itemlist


# ------------------------- azioni -------------------------

def episodios(item):
    """Enumerazione episodi a TIER:
    1) payload Next.js di ADX (titoli+plot+still, zero server vidxgo)
    2) PIANO A (get_embed_page + discovery) — fallback"""
    logger.info()
    data = httptools.downloadpage(item.url, cloudscraper=True).data or ''
    token = _token_from_data(data)
    if not token:
        logger.error('episodios: token non trovato su ' + item.url)
        return []

    token = _token_for_server(token)
    if not token:
        return []

    title = getattr(item, 'contentTitle', '') or getattr(item, 'fulltitle', '') or item.title

    pairs = PAIRS_CACHE.get(token)
    if pairs is None:
        # ---- TIER 1: ADX Next.js ----
        ntoken, npairs, ntitles, nmeta = _pairs_via_next(title)
        if ntoken and npairs:
            # il token ADX è imdb-based come il nostro: usiamo il suo
            token = ntoken
            pairs = npairs
            PAIRS_CACHE[token] = pairs
            return _episode_list(item, pairs, token, ntitles, nmeta)
        # ---- TIER 2: PIANO A ----
        pairs = _pairs_via_server(token)
        if pairs:
            PAIRS_CACHE[token] = pairs
    if not pairs:
        logger.info('episodios: nessun episodio (%s)' % token)
        _notify('episodi non disponibili ora, riprova')
        return []
    return _episode_list(item, pairs, token)


def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    data = support.httptools.downloadpage(item.url, cloudscraper=True).data or ''
    if not data:
        return []

    token = _token_from_data(data)
    if not token:
        logger.error('findvideos: token non trovato su ' + item.url)
        return []

    token = _token_for_server(token)
    if not token:
        return []

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    # episodio diretto (da _episode_list): via play
    if s and e:
        it = item.clone(action='play', server='vidxgo',
                        url='https://v.vidxgo.co/%s/%d/%d' % (token, s, e))
        it.contentTitle = item.contentTitle or item.fulltitle
        return support.server(item, itemlist=[it])

    # niente s/e: serie o film? PIANO A (quiet) per decidere
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

    # film (o pagina non leggibile): play del token nudo
    it = item.clone(action='play', url='https://v.vidxgo.co/' + token)
    it.contentTitle = item.contentTitle or item.fulltitle
    return support.server(item, itemlist=[it])


def addToLibrary(item):
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
