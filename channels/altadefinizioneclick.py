# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Altadefinizione Click (nuovo dominio: altadefinizionex.live)
#
# Build 2026-09-19-NEXT-ONLY
#
# - mainlist / search / genres / peliculas / peliculas_genere : invariati
# - episodios : SOLO parsing payload Next.js (self.__next_f).
#       Nessuna discovery, nessun Plan A, nessun TMDB, nessun probe.
#       Se Next.js non espone le seasons -> lista vuota.
# - findvideos: iframe vidxgo (skip trailer) -> server='vidxgo' (invariato)
# - play      : RIMOSSO. Playback di servers/vidxgo.py.
# ------------------------------------------------------------

from core import support
from platformcode import config, logger
import re, html, json, traceback, urllib.parse, time

host = support.config.get_channel_url()
if host and host.endswith('/'):
    host = host[:-1]

EP_CACHE = {}   # item.url -> {'token', 'pairs', 'titles', 'meta'}


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


# ------------------------- NEXT.JS: payload self.__next_f -------------------------

def _estrai_next_json(data):
    """
    Legge i chunk iniettati da Next.js (self.__next_f.push).
    Ritorna (token, seasons):
      - token: stringa numerica oppure None
      - seasons: lista di dict {number, name, episodes:[{number,title,plot,still}]}
    """
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
            ms = re.search(r'"seasons":(\[.*?\])\s*,\s*"turnstileSiteKey"',
                           chunk, re.S)
            if ms:
                try:
                    seasons = json.loads(ms.group(1))
                except Exception:
                    seasons = []

        if token and seasons:
            break

    return token, seasons


def _next_pairs_and_meta(seasons):
    """
    Converte le seasons Next.js in:
      - pairs: [(s,e), ...] ordinati
      - meta:  {(s,e): {'title':..., 'plot':..., 'still':...}}
    """
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


# ---------------------------------- EPISODES ----------------------------------
@support.scrape
def episodios(item):
    cached = EP_CACHE.get(item.url)
    if cached:
        token = cached['token']
        tuples = cached['pairs']
        TITLES = cached['titles']
        META = cached.get('meta', {})
    else:
        data = support.httptools.downloadpage(item.url, cloudscraper=True).data or ''

        token, seasons = _estrai_next_json(data)
        pairs, meta = _next_pairs_and_meta(seasons)

        if not (token and pairs):
            logger.error('episodios: Next.js senza token/seasons su ' + item.url)
            return []

        logger.info('episodios: NEXT.JS -> token=%s, %d episodi, %d stagioni'
                    % (token, len(pairs), len({s for s, _ in pairs})))

        tuples = pairs
        META = meta
        TITLES = {}
        for (s, e), m in meta.items():
            if m.get('title'):
                TITLES[(s, e)] = m['title']

        EP_CACHE[item.url] = {'token': token, 'pairs': tuples,
                              'titles': TITLES, 'meta': META}

    data = ''.join('<a href="https://v.vidxgo.co/%s/%d/%d" data-s="%d" data-e="%d"></a>'
                   % (token, s, e, s, e) for s, e in tuples)

    patron = (r'<a href="(?P<url>https://v\.vidxgo\.co/[^"]+)"'
              r'[^>]*data-s="(?P<season>\d+)"[^>]*data-e="(?P<episode>\d+)"')
    action = 'play'

    def itemHook(it):
        it.is_folder = False
        it.server = 'vidxgo'

        # s/e dall'URL sintetica: deterministico
        m = re.search(r'v\.vidxgo\.co/\d+/(\d+)/(\d+)', it.url or '')
        if m:
            s, e = int(m.group(1)), int(m.group(2))
        else:
            s = int(getattr(it, 'contentSeason', None) or getattr(it, 'season', 0) or 0)
            e = int(getattr(it, 'contentEpisode', None) or getattr(it, 'episode', 0) or 0)

        # titolo dal Next.js
        t = TITLES.get((s, e))
        if t:
            it.title = (it.title + ' - ' + t) if it.title else t

        # plot + still dal Next.js
        meta = META.get((s, e), {})
        plot = (meta.get('plot') or '').strip()
        if plot:
            it.plot = plot
            try:
                info = dict(getattr(it, 'info', {}) or {})
                info['plot'] = plot
                it.info = info
            except Exception:
                pass
        still = (meta.get('still') or '').strip()
        if still:
            it.thumbnail = still

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