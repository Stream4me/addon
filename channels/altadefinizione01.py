# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per altadefinizione01
# Il sito alterna due player: vidxgo e vixsrc. Il canale legge la
# pagina, riconosce quale dei due e' presente e usa il metodo giusto
# per episodi e video. Se non riconosce nulla ripiega su vixsrc.
# Formato URL:
#   vixsrc film    https://vixsrc.to/movie/<imdb>?lang=it
#   vixsrc episodio https://vixsrc.to/tv/<imdb>/<s>/<e>?lang=it
#   vidxgo film    https://v.vidxgo.co/<token>
#   vidxgo episodio https://v.vidxgo.co/<token>/<s>/<e>
# dove <token> e' l'imdb senza "tt".
# ------------------------------------------------------------

import html as _html
import json
import os
import re
import threading
import time

from core import scrapertools, httptools, support
from core.item import Item
from platformcode import config, logger

host = config.get_channel_url()
headers = [['Referer', host]]

VIX_BASE = 'https://vixsrc.to'
VDX_BASE = 'https://v.vidxgo.co'

PROBE_TIMEOUT = 5
PROBE_OK_TTL = 1800
PROBE_FAIL_TTL = 600
MAX_SEASONS = 12
MAX_EPISODES = 24
DURATA_CACHE = 12 * 3600

_RE_VDX = re.compile(r'vidxgo\.co/([A-Za-z0-9]+)', re.I)
_RE_VIX = re.compile(r'vixsrc\.to/(?:movie|tv)/(tt\d+)', re.I)
_RE_VDX_URL = re.compile(r'vidxgo\.co/([A-Za-z0-9]+)(?:/(\d+)/(\d+))?', re.I)
_RE_VIX_URL = re.compile(r'vixsrc\.to/(movie|tv)/([A-Za-z0-9]+)(?:/(\d+)/(\d+))?', re.I)
_RE_TMDB = re.compile(r'themoviedb\.org/(?:movie|tv)/(\d+)', re.I)


@support.menu
def mainlist(item):
    menu = [
        ('Tutti', ['/lastnews/', 'peliculas', '', 'movie']),
        ('Al Cinema {submenu}', ['/cinema/', 'peliculas', '', 'movie']),
        ('Ultimi Aggiornati-Aggiunti {submenu}', ['', 'peliculas', 'update']),
        ('Generi {submenu}', ['', 'genres', 'genres', 'movie']),
        ('Lettera {submenu}', ['/catalog/a', 'genres', 'orderalf', 'movie']),
        ('Anni {submenu}', ['', 'genres', 'years', 'movie']),
        ('Sub-ITA {submenu}', ['/sub-ita/', 'peliculas', '', 'movie']),
        ('Serie TV', ['/serie-tv/', 'peliculas', '', 'tvshow']),
    ]
    search = ''
    return locals()


@support.scrape
def peliculas(item):
    support.info('peliculas', item)
    action = "check"

    if item.text:
        url = host + "/?do=search&subaction=search&titleonly=3&story=" + item.text
        data = httptools.downloadpage(
            url,
            post={'story': item.text, 'do': 'search', 'subaction': 'search'}
        ).data
        patron = r'<div class="cover boxcaption"> +<h2>\s*<a href="(?P<url>[^"]+)">(?P<title>[^<]+).*?src="(?P<thumb>[^"]+).*?(?:<div class="trdublaj">(?P<quality>[^<]+)|<span class="se_num">(?P<episode>[^<]+)).*?<span class="ml-label">(?P<year>[0-9]+).*?<span class="ml-label">(?P<duration>[^<]+).*?<p>(?P<plot>[^<]+)'

    elif item.args == "search":
        patronBlock = r'</script> <div class="boxgrid caption">(?P<block>.*)<div id="right_bar">'
        patron = (
            r'<div class="cover boxcaption"> +<h2>\s*<a href="(?P<url>[^"]+)">(?P<title>[^<]+).*?'
            r'src="(?P<thumb>[^"]+).*?'
            r'(?:<div class="trdublaj">(?P<quality>[^<]+)|<span class="se_num">(?P<quality>[^<]+)).*?'
            r'<span class="ml-label">(?P<year>[0-9]+).*?'
            r'<span class="ml-label">(?P<duration>[^<]+).*?'
            r'<p>(?P<plot>[^<]+)'
        )

    elif item.args == 'update':
        patronBlock = r'<div class="widget-title">Ultimi Film Aggiunti/Aggiornati</div>(?P<block>.*?)<div id="alt_menu">'
        patron = (
            r'<li> <a href="(?P<url>https?://[^"]+)" class="ml-mask">(?P<title>[^<]+)</a>.*?'
            r'<div class="ml-item-body" style="background-image:url\((?P<thumb>[^\)]+)\);">.*?'
            r'<li> <span class="ml-imdb"><b>(?P<rating>[^<]+)</b>.*?'
            r'<li><span class="ml-label">(?P<year>\d{4})</span></li>.*?'
            r'<li><span class="ml-label">(?P<duration>[^<]+)</span></li>.*?'
            r'<p class="ml-cat">(?P<genre>.*?)</p>.*?'
            r'<p>(?P<plot>[^<]+)</p>'
        )
        patronNext = ''

    elif item.args == 'orderalf':
        patron = (
            r'<tr class="mlnew">\s*<td class="mlnh-1">\d+</td>\s*'
            r'<td class="mlnh-thumb"><a href="(?P<url>[^"]+)"[^>]*>.*?data-src="(?P<thumb>[^"]+)".*?'
            r'<td class="mlnh-2"><h2>\s*<a[^>]*>(?P<title>[^<]+)</a>.*?'
            r'<td class="mlnh-3">.*?(?P<year>\d{4}).*?</td>.*?'
            r'<td class="mlnh-4">(?P<quality>[^<]*)</td>.*?'
            r'<td class="mlnh-5">(?P<genre>.*?)</td>'
        )
        patronNext = r'<div[^>]*class="[^"]*page[^"]*"[^>]*>.*?<a href="([^"]+)"[^>]*>(?:Next|Avanti|\d+|>)</a>'

    else:
        # film o serie lo dice l'etichetta della locandina: trdublaj (qualita') o se_num (stagione ed episodio)
        typeContentDict = {'movie': ['trdublaj'], 'tvshow': ['se_num']}
        patronBlock = r'<div class="cover_kapsul ml-mask">(?P<block>.*)<div class="page_nav">'
        patron = (
            r'<div class="cover boxcaption"> +<h2>\s*<a href="(?P<url>[^"]+)">(?P<title>[^<]+).*?'
            r'src="(?P<thumb>[^"]+).*?'
            r'<(?:div|span) class="(?P<type>trdublaj|se_num)">(?P<quality>[^<]+).*?'
            r'<span class="ml-label">(?P<year>[0-9]+).*?'
            r'<span class="ml-label">(?P<duration>[^<]+).*?'
            r'<p>(?P<plot>[^<]+)'
        )
        patronNext = r'<span>\d+</span>\s*<a href="([^"]+)">'

    return locals()


def search(item, text):
    support.info(item, text)
    item.text = text
    try:
        return peliculas(item)
    except:
        import sys
        from core.support import info
        for line in sys.exc_info():
            info("%s" % line)
    return []


@support.scrape
def genres(item):
    support.info('genres', item)
    action = "peliculas"
    blacklist = ['Altadefinizione01']

    if item.args == 'genres':
        patronBlock = r'<ul class="kategori_list">(?P<block>.*?)<div class="tab-pane fade" id="wtab2">'
        patronMenu = '<li><a href="(?P<url>[^"]+)">(?P<title>.*?)</a>'
    elif item.args == 'years':
        patronBlock = r'<ul class="anno_list">(?P<block>.*?)</li> </ul> </div>'
        patronMenu = '<li><a href="(?P<url>[^"]+)">(?P<title>.*?)</a>'
    elif item.args == 'orderalf':
        patronBlock = r'<div class="movies-letter">(?P<block>.*?)<div class="clearfix">'
        patronMenu = '<a title=.*?href="(?P<url>[^"]+)"><span>(?P<title>.*?)</span>'

    return locals()


# ------------------------- rilevamento player -------------------------

def _imdb_from_data(data):
    for patron in (r'<p id="imdb">(tt\d+)</p>',
                   r"var imdb = '(tt\d+)'",
                   r'itemprop="imdb"[^>]*content="(tt\d+)"'):
        m = support.match(data, patron=patron).match
        if m:
            return m
    return None


def _attr_tag(tag, nome):
    """Valore di un attributo di un tag HTML (o '' se manca); src non si confonde con data-src."""
    m = re.search(r'(?<![\w-])' + re.escape(nome) + r'\s*=\s*["\']([^"\']*)["\']', tag or '', re.I)
    return m.group(1).strip() if m else ''


def _corpo(data):
    """La pagina del titolo senza la barra laterale (id=right_bar), che contiene le
    stagioni di altri titoli."""
    d = data or ''
    i = d.find('id="right_bar"')
    if i < 0:
        i = d.find("id='right_bar'")
    return d[:i] if i > 0 else d


def _episodi_sito(data):
    """Episodi elencati dalla pagina stessa (tab delle stagioni, struttura classica del sito
    e di StreamFlix): pannelli id="season-N" con <li><a allowfullscreen data-link data-num
    data-title> e i mirror (a[data-link], senza 4K). Ritorna una lista di dict con
    s, e, title, plot e links; vuota se la pagina non ha questa struttura."""
    out = []
    corpo = _corpo(data)
    for pezzo in re.split(r'(?=<div\b[^>]*\bid=["\']season-\d+["\'])', corpo):
        ms = re.match(r'<div\b[^>]*\bid=["\']season-(\d+)["\']', pezzo, re.I)
        if not ms:
            continue
        stagione = int(ms.group(1))
        for li in re.findall(r'<li\b[^>]*>(.*?)</li>', pezzo, re.S | re.I):
            principale = None
            for a in re.finditer(r'<a\b([^>]*)>(.*?)</a>', li, re.S | re.I):
                if 'allowfullscreen' in a.group(1) and _attr_tag(a.group(1), 'data-link'):
                    principale = a
                    break
            if not principale:
                continue
            num = _attr_tag(principale.group(1), 'data-num')
            mn = re.search(r'(\d+)\s*$', num.split('x')[-1]) if num else None
            if not mn:
                mn = re.search(r'\d+', re.sub(r'<[^>]+>', '', principale.group(2)))
            if not mn:
                continue
            episodio = int(mn.group(1) if mn.lastindex else mn.group(0))

            titolo, trama = '', ''
            dt = _html.unescape(_attr_tag(principale.group(1), 'data-title')).strip()
            if ':' in dt:
                titolo, trama = [x.strip() for x in dt.split(':', 1)]
            else:
                titolo = dt

            links = []
            for a in re.finditer(r'<a\b([^>]*)>(.*?)</a>', li, re.S | re.I):
                link = _attr_tag(a.group(1), 'data-link')
                if not link:
                    continue
                if '4k' in re.sub(r'<[^>]+>', '', a.group(2)).lower():
                    continue
                if link.startswith('//'):
                    link = 'https:' + link
                if link not in links:
                    links.append(link)
            if links:
                out.append({'s': stagione, 'e': episodio, 'title': titolo, 'plot': trama, 'links': links})
    return out


def _tmdb_from_data(data):
    """Id TMDB della pagina, dalla riga fonteTrama (themoviedb.org/movie/<id>)."""
    m = _RE_TMDB.search(data or '')
    return m.group(1) if m else None


def _vix_scarica(tipo):
    """Elenco dei titoli di VixSrc (movie, tv, episode), tenuto in un file
    temporaneo per qualche ora, come nel canale vixsrc. Lista vuota se non
    raggiungibile."""
    nome = os.path.join(config.get_temp_file(''), 'vixsrc_%s.json' % tipo)
    try:
        if os.path.isfile(nome) and time.time() - os.path.getmtime(nome) < DURATA_CACHE:
            with open(nome, 'r') as f:
                return json.load(f)
    except Exception:
        logger.error('vixsrc: cache non letta')
    try:
        dati = json.loads(httptools.downloadpage('%s/api/list/%s?lang=it' % (VIX_BASE, tipo)).data)
    except Exception:
        logger.error('vixsrc: elenco %s non disponibile' % tipo)
        return []
    try:
        with open(nome, 'w') as f:
            json.dump(dati, f)
    except Exception:
        logger.error('vixsrc: cache non scritta')
    return dati


def _su_vixsrc(tmdb_id, tipo):
    """True se il titolo e' nell'elenco di VixSrc, False se non c'e',
    None se l'elenco non e' disponibile o manca l'id TMDB."""
    if not tmdb_id:
        return None
    elenco = _vix_scarica(tipo)
    if not elenco:
        return None
    return any(str(x.get('tmdb_id')) == str(tmdb_id) for x in elenco)


def _vix_episodi(tmdb_id):
    """Episodi realmente presenti su VixSrc: lista ordinata di (stagione, episodio)."""
    if not tmdb_id:
        return []
    coppie = set()
    for x in _vix_scarica('episode'):
        if str(x.get('tmdb_id')) == str(tmdb_id):
            try:
                coppie.add((int(x['s']), int(x['e'])))
            except Exception:
                continue
    return sorted(coppie)


def _tmdb_episodi(tmdb_id):
    """Stagioni ed episodi reali (con titolo, trama, immagine) da TMDB.
    Ritorna dict {(s, e): {name, overview, still}}; vuoto se non disponibile."""
    if not tmdb_id:
        return {}
    chiave = 'a01_tmdb_ep_%s' % tmdb_id
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        cached = win.getProperty(chiave)
        if cached:
            return {tuple(map(int, k.split('x'))): v for k, v in json.loads(cached).items()}
    except Exception:
        win = None
    out = {}
    try:
        from core import tmdb
        base = '{}/tv/{}'.format(tmdb.host, tmdb_id)
        lang = tmdb.def_lang
        serie = json.loads(httptools.downloadpage(
            '%s?api_key=%s&language=%s' % (base, tmdb.api, lang)).data)
        for sn in serie.get('seasons') or []:
            n = sn.get('season_number')
            if not n:  # salta gli speciali (stagione 0)
                continue
            st = json.loads(httptools.downloadpage(
                '%s/season/%s?api_key=%s&language=%s' % (base, n, tmdb.api, lang)).data)
            for ep in st.get('episodes') or []:
                still = ep.get('still_path')
                out[(int(n), int(ep['episode_number']))] = {
                    'name': ep.get('name') or '',
                    'overview': ep.get('overview') or '',
                    'still': ('https://image.tmdb.org/t/p/w500' + still) if still else ''}
    except Exception as e:
        logger.error('TMDB episodi: %s' % e)
        return {}
    try:
        if win and out:
            win.setProperty(chiave, json.dumps({'%dx%d' % k: v for k, v in out.items()}))
    except Exception:
        pass
    return out


def _detect_player(data):
    """Guarda quale player e' presente nella pagina. Prima cerca l'URL
    scritto per intero; se manca (l'iframe e' creato da JavaScript, come
    'https://v.vidxgo.co/' + key) usa il solo nome del player. Se ce ne
    sono due vince quello che compare per primo.
    Ritorna (nome, riferimento, incerto): incerto e' True quando non ne
    compare nessuno oppure compaiono entrambi."""
    page = (data or '').replace('\\/', '/')
    mv = _RE_VDX.search(page)
    mx = _RE_VIX.search(page)
    if mv or mx:
        incerto = bool(mv and mx)
        if mv and (not mx or mv.start() < mx.start()):
            return 'vidxgo', mv.group(1), incerto
        return 'vixsrc', mx.group(1), incerto

    nv = re.search(r'vidxgo', page, re.I)
    nx = re.search(r'vixsrc', page, re.I)
    if nv or nx:
        incerto = bool(nv and nx)
        if nv and (not nx or nv.start() < nx.start()):
            return 'vidxgo', None, incerto
        return 'vixsrc', None, incerto
    return None, None, True


def _player_info(data, tipo='movie'):
    """Raccoglie player, imdb, id TMDB e token vidxgo (imdb senza 'tt',
    oppure 'tm' + id TMDB se manca l'imdb, come fa il sito)."""
    imdb_id = _imdb_from_data(data)
    tmdb_id = _tmdb_from_data(data)
    player, ref, incerto = _detect_player(data)
    token = None

    if player == 'vidxgo':
        token = ref
        if not imdb_id and ref and ref.isdigit():
            imdb_id = 'tt' + ref
    elif player == 'vixsrc':
        imdb_id = imdb_id or ref

    # Pagina non chiara (nessun player o tutti e due): decide l'elenco di VixSrc
    if incerto:
        presente = _su_vixsrc(tmdb_id, tipo)
        if presente is True:
            player = 'vixsrc'
        elif presente is False and (imdb_id or tmdb_id):
            player = 'vidxgo'
        elif not player:
            player = 'vixsrc'
        support.info('Pagina incerta, VixSrc la ha: %s, scelgo %s' % (presente, player))

    if not token:
        if imdb_id:
            token = imdb_id[2:]
        elif tmdb_id:
            token = 'tm' + tmdb_id

    support.info('Player: %s, imdb: %s, tmdb: %s, token: %s' % (player, imdb_id, tmdb_id, token))
    return {'player': player, 'imdb': imdb_id, 'tmdb': tmdb_id, 'token': token}


def _vixsrc_url(ident, season=None, episode=None):
    """ident puo' essere un imdb (tt...) o un id TMDB."""
    if season and episode:
        return '%s/tv/%s/%s/%s?lang=it' % (VIX_BASE, ident, season, episode)
    return '%s/movie/%s?lang=it' % (VIX_BASE, ident)


def _vidxgo_url(token, season=None, episode=None):
    if season and episode:
        return '%s/%s/%s/%s' % (VDX_BASE, token, season, episode)
    return '%s/%s' % (VDX_BASE, token)


def _probe_cache_get(token):
    """Cache del probe in una proprietà della finestra di Kodi (ogni apertura
    del canale e' un processo nuovo, una variabile di modulo non resterebbe).
    Ritorna (trovato, info): info None = probe fallito di recente."""
    try:
        import xbmcgui
        v = xbmcgui.Window(10000).getProperty('altadef01_probe_%s' % token)
        if not v:
            return False, None
        d = json.loads(v)
        eta = time.time() - d.get('t', 0)
        if d.get('ok') and eta < PROBE_OK_TTL:
            return True, d.get('info')
        if not d.get('ok') and eta < PROBE_FAIL_TTL:
            return True, None
    except Exception:
        pass
    return False, None


def _probe_cache_set(token, info):
    try:
        import xbmcgui
        d = {'t': time.time(), 'ok': bool(info), 'info': info or None}
        xbmcgui.Window(10000).setProperty('altadef01_probe_%s' % token, json.dumps(d))
    except Exception:
        pass


def _probe_vidxgo(token, timeout=PROBE_TIMEOUT):
    """Chiede al server vidxgo la lista reale degli episodi. Gira in un
    thread con attesa massima perche' puo' bloccarsi. Il risultato (anche il
    fallimento) resta in cache, cosi' riaprire la serie non rifà l'attesa."""
    trovato, cache = _probe_cache_get(token)
    if trovato:
        support.info('vidxgo: probe da cache (%s)' % ('ok' if cache else 'fallito di recente'))
        return cache

    try:
        from servers import vidxgo
    except Exception:
        logger.error('servers/vidxgo mancante o rotto')
        return None

    result = {}

    def worker():
        try:
            info = None
            api = getattr(vidxgo, 'episodes_api', None)
            if api:
                info = api(token)
            if not (info and info.get('episodes')):
                info = vidxgo.probe(token)
            result['info'] = info
        except Exception:
            import traceback
            logger.error('probe(%s): %s' % (token, traceback.format_exc()[-200:]))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.error('probe(%s) appesa oltre %ds, abbandono' % (token, timeout))
        _probe_cache_set(token, None)
        return None
    info = result.get('info')
    good = bool(info and info.get('mode') == 'tv' and info.get('episodes'))
    _probe_cache_set(token, info if good else None)
    return info


def episodios(item):
    support.info('episodios', item)

    item.duration = ''
    if hasattr(item, 'infoLabels') and isinstance(item.infoLabels, dict):
        item.infoLabels.pop('duration', None)

    data = item.data if hasattr(item, 'data') and item.data else httptools.downloadpage(item.url).data

    # Prima gli episodi elencati dalla pagina del sito (titoli, trame e mirror reali),
    # come fa StreamFlix: vale per le serie che non sono su vidxgo o vixsrc.
    sito = _episodi_sito(data)
    if sito:
        itemlist = []
        for ep in sito:
            new_item = item.clone()
            new_item.data = ''
            new_item.action = 'findvideos'
            new_item.contentType = 'episode'
            new_item.season = ep['s']
            new_item.episode = ep['e']
            new_item.contentSeason = ep['s']
            new_item.contentEpisodeNumber = ep['e']
            new_item.title = f"{ep['s']}x{ep['e']:02d}" + (f" - {ep['title']}" if ep['title'] else '')
            if ep['plot']:
                new_item.plot = ep['plot']
            new_item.contentSerieName = item.fulltitle if item.fulltitle else item.title
            new_item.thumbnail = item.thumbnail
            new_item.contentThumbnail = item.thumbnail
            new_item.fanart = item.fanart
            new_item.contentFanart = item.fanart
            new_item.links_sito = ep['links']
            new_item.duration = ''
            if hasattr(new_item, 'infoLabels') and isinstance(new_item.infoLabels, dict):
                new_item.infoLabels.pop('duration', None)
            itemlist.append(new_item)
        support.info(f'Episodi dalla pagina del sito: {len(itemlist)}')
        support.check_trakt(itemlist)
        support.videolibrary(itemlist, item)
        return itemlist

    info = _player_info(data, 'tv')
    imdb_id = info['imdb']
    tmdb_id = info['tmdb']
    token = info['token']
    player = info['player']

    if not imdb_id and not token:
        support.info('IMDB ID non trovato per la serie!')
        return []

    pairs = []
    dettagli = {}
    vix_ident = imdb_id

    if player == 'vidxgo' and token:
        probe = _probe_vidxgo(token)
        if probe and probe.get('mode') == 'tv' and probe.get('episodes'):
            pairs = [tuple(x) for x in probe['episodes']]
            for d in probe.get('details') or []:
                dettagli[(d['s'], d['e'])] = d
            support.info('vidxgo: %d episodi reali' % len(pairs))
        else:
            support.info('vidxgo: probe senza episodi, ripiego su vixsrc')
            player = 'vixsrc'

    if player == 'vixsrc':
        reali = _vix_episodi(tmdb_id)
        if not reali:
            dettagli = _tmdb_episodi(tmdb_id)
            reali = sorted(dettagli) if dettagli else []
            if reali:
                support.info('TMDB: %d episodi' % len(reali))
        if reali:
            # episodi che esistono davvero su VixSrc, con l'id TMDB come nel canale vixsrc
            pairs = reali
            vix_ident = tmdb_id
            support.info('vixsrc: %d episodi reali' % len(pairs))
        else:
            if not imdb_id:
                support.info('vixsrc: IMDB ID mancante')
                return []
            pairs = [(s, e) for s in range(1, MAX_SEASONS + 1)
                     for e in range(1, MAX_EPISODES + 1)]
            support.info('vixsrc: griglia %dx%d' % (MAX_SEASONS, MAX_EPISODES))

    if pairs and not dettagli:
        dettagli = _tmdb_episodi(tmdb_id)
    itemlist = []
    for season, episode in pairs:
        new_item = item.clone()
        new_item.action = 'findvideos'
        new_item.contentType = 'episode'
        new_item.season = season
        new_item.episode = episode
        new_item.contentSeason = season
        new_item.contentEpisodeNumber = episode
        det = dettagli.get((season, episode)) or {}
        nome_ep = (det.get('name') or '').strip()
        new_item.title = f"{season}x{episode:02d}" + (f" - {nome_ep}" if nome_ep else '')
        if det.get('overview'):
            new_item.plot = det['overview']
        new_item.contentSerieName = item.fulltitle if item.fulltitle else item.title
        still = det.get('still') or ''
        new_item.thumbnail = still if still.startswith('http') else item.thumbnail
        new_item.contentThumbnail = new_item.thumbnail
        new_item.fanart = item.fanart
        new_item.contentFanart = item.fanart
        new_item.imdb_id = imdb_id
        if player == 'vidxgo':
            new_item.url = _vidxgo_url(token, season, episode)
        else:
            new_item.url = _vixsrc_url(vix_ident, season, episode)

        new_item.duration = ''
        if hasattr(new_item, 'infoLabels') and isinstance(new_item.infoLabels, dict):
            new_item.infoLabels.pop('duration', None)

        itemlist.append(new_item)

    support.info(f'Generati {len(itemlist)} episodi con {player}')

    support.check_trakt(itemlist)

    support.videolibrary(itemlist, item)

    return itemlist


def check(item):
    support.info('CHECK chiamata per:', item)
    item.data = httptools.downloadpage(item.url).data

    is_tvshow = False
    if 'show_id' in item.data:
        is_tvshow = True
    elif 'Serie TV' in item.data and 'Durata episodio' in item.data:
        is_tvshow = True
    elif 'vixsrc.to/tv/' in item.data:
        is_tvshow = True
    elif re.search(r'vidxgo\.co/[A-Za-z0-9]+/\d+/\d+', item.data.replace('\\/', '/')):
        is_tvshow = True
    elif _episodi_sito(item.data):
        # la pagina elenca gli episodi nei tab delle stagioni
        is_tvshow = True
    elif re.search(r'id=["\']vidxgo-player["\']', item.data):
        # iframe delle serie (quello dei film e' vidxgo-player-film)
        is_tvshow = True

    if is_tvshow:
        item.contentType = 'tvshow'
        support.info('Rilevata serie TV, chiamando episodios')
        return episodios(item)
    else:
        item.contentType = 'movie'
        support.info('Rilevato film, chiamando findvideos')
        return findvideos(item)


def newest(categoria):
    support.info(categoria)
    itemlist = []
    item = Item()
    try:
        if categoria == "peliculas":
            item.url = host
            item.action = "peliculas"
            item.contentType = 'movie'
            itemlist = peliculas(item)
            if itemlist and itemlist[-1].action == "peliculas":
                itemlist.pop()
    except:
        import sys
        for line in sys.exc_info():
            logger.error("{0}".format(line))
        return []
    return itemlist


def _url_player(imdb_id, tmdb_id, token, season=None, episode=None, primo='vidxgo'):
    """Gli URL di tutti e due i player, il preferito per primo."""
    vdx = _vidxgo_url(token, season, episode) if token else None
    ident = imdb_id or tmdb_id
    vix = _vixsrc_url(ident, season, episode) if ident else None
    ordine = [vix, vdx] if primo == 'vixsrc' else [vdx, vix]
    return [u for u in ordine if u]


def findvideos(item):
    support.info('findvideos', item)

    # episodio preso dalla pagina del sito: i link dei mirror sono gia' nell'item
    if getattr(item, 'links_sito', None):
        return support.server(item, item.links_sito)

    # Passo 1: l'URL dell'item e' gia' quello di un player (episodi creati da
    # episodios): si ricava l'altro e si offrono entrambi, come StreamFlix.
    mv = _RE_VDX_URL.search(item.url or '')
    mx = _RE_VIX_URL.search(item.url or '')
    if mv or mx:
        imdb_id = getattr(item, 'imdb_id', None)
        tmdb_id = None
        if mv:
            primo = 'vidxgo'
            token = mv.group(1)
            season, episode = mv.group(2), mv.group(3)
            if not imdb_id and token.isdigit():
                imdb_id = 'tt' + token
            if token.startswith('tm'):
                tmdb_id = token[2:]
        else:
            primo = 'vixsrc'
            ident = mx.group(2)
            season, episode = mx.group(3), mx.group(4)
            if ident.startswith('tt'):
                imdb_id = ident
            else:
                tmdb_id = ident
            token = imdb_id[2:] if imdb_id else 'tm' + ident
        urls = _url_player(imdb_id, tmdb_id, token, season, episode, primo)
        support.info(f'URL dei due player: {urls}')
        return support.server(item, urls)

    # Passo 2: URL del sito, si legge la pagina e si riconosce il player.
    data = item.data if hasattr(item, 'data') and item.data else httptools.downloadpage(item.url).data

    is_episode = item.contentType == 'episode' or (hasattr(item, 'season') and item.season)

    info = _player_info(data, 'tv' if is_episode else 'movie')
    imdb_id = info['imdb']
    token = info['token']

    if not imdb_id and not token:
        support.info('IMDB ID non trovato!')
        return []

    season = (getattr(item, 'season', 1) or 1) if is_episode else None
    episode = (getattr(item, 'episode', 1) or 1) if is_episode else None

    urls = _url_player(imdb_id, info['tmdb'], token, season, episode, info['player'])
    support.info(f'URL generati: {urls}')
    return support.server(item, urls)
