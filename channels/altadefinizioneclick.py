# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Altadefinizione Click (nuovo dominio: altadefinizionex.live)
#
# Build 2026-09-12-SERVER-DETACHED
#
# - mainlist / search / genres / peliculas / peliculas_genere : scraping (invariati)
# - episodios : righe sintetiche vidxgo -> url/season/episode
#               (fallback probe() del server se la pagina non espone episodi)
# - findvideos: iframe vidxgo (skip trailer) -> server='vidxgo'
# - play      : RIMOSSO. Il playback e' del server servers/vidxgo.py:
#               resolve /t/ con rotazione TLS, fallback XOR, proxy locale
#               (porta fissa, token refresh, heartbeat, FASTSTART) e watchdog
#               auto-spegnimento. Serve servers/vidxgo.py + vidxgo.json.
# ------------------------------------------------------------

from core import support
from platformcode import config, logger
import re, html, traceback, urllib.parse, time

host = 'https://altadefinizionex.live'
if host.endswith('/'):
    host = host[:-1]


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

    # [SCOPE] il patron va applicato SOLO al menu a tendina dei generi:
    # sulla pagina intera catturava nav/footer/link vari (da qui la
    # lista piena). Il blocco e' delimitato da dropdown-menu ... </div>
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

    # fallback: layout cambiato e blocco non trovato -> vecchio comportamento
    # generico con blacklist (meglio di una lista vuota)
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
# ---------------------------------- MAIN LISTING (film, serie-tv) ----------------------------------
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

    # un patron per layout: i nomi di gruppo non possono duplicarsi in un'unica regex
    if 'class="mlnew"' in data:
        # tabella (risultati ricerca / archivio)
        patron = (r'<tr class="mlnew"[^>]*>\s*<td>\d+</td>\s*<td[^>]*>\s*'
                  r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*>\s*'
                  r'<img[^>]+src="(?P<thumb>[^"]+)"'
                  r'[\s\S]*?<h2[^>]*>\s*<a href="[^"]+"[^>]*>(?P<title>[^<]+)</a>'
                  r'[\s\S]*?<td class="text-center d-none d-lg-table-cell">(?P<year>\d{4})</td>'
                  r'[\s\S]*?<span class="badge[^"]*">(?P<rating>[0-9.]+)</span>')
    else:
        # griglia card (listati /film/ e /serie-tv/)
        patron = (r'<a href="(?P<url>/(?P<type>[^"/]+)/[^"]+-streaming\.html)"[^>]*'
                  r'data-title="(?P<title>[^"]+)"[^>]*data-year="(?P<year>\d+)"[^>]*'
                  r'data-imdb="(?P<rating>[^"]+)"[^>]*>\s*<img[^>]+src="(?P<thumb>[^"]+)"')

    action = 'findvideos'                          # default per i film
    typeActionDict = {'episodios': ['serie-tv']}   # slug -> action per le serie
    typeContentDict = {'tvshow': ['serie-tv']}     # slug -> contentType (TMDB)
    pagination = 12                                # il wrapper taglia e aggiunge "pagina successiva"
    debug = False

    return locals()


# ---------------------------------- GENRE LISTING + Search ----------------------------------
@support.scrape
def peliculas_genere(item):
    logger.debug("peliculas_genere: %s", item)

    cat = getattr(item, 'cat_id', '').strip('/')
    tipo = getattr(item, 'type', '')

    # se il link del menu includeva gia' il tipo ('azione/film') separiamolo
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
        candidates = [item.url]          # chiamate successive (paginazione)

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

    actLike = 'peliculas'                        # TMDB: contentTitle + arricchimento
    action = 'findvideos'
    typeActionDict = {'episodios': ['serie-tv']}
    typeContentDict = {'tvshow': ['serie-tv']}

    # NIENTE variabile "pagination": tagliamo noi via itemlistHook
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

# ---------------------------------- EPISODES ----------------------------------
@support.scrape
def episodios(item):
    data = support.httptools.downloadpage(item.url, cloudscraper=True).data

    # token iframe vidxgo, saltando i player dei trailer se possibile
    token = None
    for m in re.finditer(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)[^"]*"', data):
        if 'trailer' in m.group(0).lower():
            continue
        token = m.group(1)
        break
    if token is None:
        m = re.search(r'<iframe[^>]+src="https://v\.vidxgo\.co/(\d+)', data)  # ultimo ricorso
        token = m.group(1) if m else None

    if not token:
        logger.error("Token not found in iframe src")
        data = ''              # dentro @support.scrape NON si fa "return []": serve locals()
    else:
        # coppie (stagione, episodio) reali dalla stagione embeddata
        pair_set = {(int(a), int(b)) for a, b in re.findall(r'data-episode="(\d+)-(\d+)"', data)}
        embedded = {s for s, _ in pair_set}

        # tutte le stagioni dal selettore
        seasons = sorted({int(x) for x in re.findall(r'Stagione\s*(?:<!--[^>]*-->\s*)?(\d+)', data)})

        # numeri episodio da riutilizzare per le stagioni non embeddate
        eps = sorted({e for _, e in pair_set}) or \
              sorted({int(x) for x in re.findall(r'Episodio\s*(?:<!--[^>]*-->\s*)?(\d+)', data)})

        tuples = sorted(pair_set)
        for s in seasons:
            if s not in embedded:
                tuples.extend((s, e) for e in eps)
        tuples.sort()

        # [SERVER] fallback: la pagina del sito non espone episodi -> leggiamoli
        # dal player vidxgo (seasonCache, sessione TLS-cleared del server)
        if not tuples:
            try:
                from servers import vidxgo as srv_v
                tuples = sorted(srv_v.probe(token)['episodes'])
                logger.info("episodios: fallback probe vidxgo -> %s" % tuples)
            except Exception:
                logger.error("episodios: probe fallback failed: " + traceback.format_exc())

        if tuples:
            # righe sintetiche: il dict le estrae come url/season/episode
            data = ''.join('<a href="https://v.vidxgo.co/%s/%d/%d" data-s="%d" data-e="%d"></a>'
                           % (token, s, e, s, e) for s, e in tuples)
        else:
            logger.error("episodios: nessun episodio trovato (sito + probe)")
            data = ''

    patron = (r'<a href="(?P<url>https://v\.vidxgo\.co/[^"]+)"'
              r'[^>]*data-s="(?P<season>\d+)"[^>]*data-e="(?P<episode>\d+)"')
    action = 'play'

    def itemHook(it):
        it.is_folder = False
        it.server = 'vidxgo'     # [SERVER] routing diretto: niente piu' play() nel canale
        return it

    return locals()


# ---------------------------------- FIND VIDEOS ----------------------------------
def findvideos(item):
    logger.info("=== findvideos: " + item.url)

    # [RETRY] fetch con 3 tentativi brevi: su Windows il DNS di sistema puo'
    # flappare -> downloadpage fallisce istantaneamente su alcuni titoli
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

    # iframe vidxgo: preferiscono quello del film, i trailer solo come ultima spiaggia
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

    # [SERVER] routing al server vidxgo: resolve + proxy + watchdog sono suoi.
    # (se per caso arriva una serie col token nudo, il server ha l'HEAL path)
    it = item.clone(action='play', url=embed_url, server='vidxgo')
    it.title = '[COLOR lime]vidxgo[/COLOR]'
    it.contentTitle = getattr(item, 'contentTitle', '') or getattr(item, 'fulltitle', '') or item.title
    return support.server(item, itemlist=[it])
