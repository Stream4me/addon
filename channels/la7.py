# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per La7 (nuovo sito la7play.it, riscritto da Timmy89 e Androide)
# ------------------------------------------------------------

import base64
import functools
import html as _html
import json
import re
from datetime import datetime, timedelta

from core import support, httptools
from platformcode import logger

DRM = 'com.widevine.alpha'
host = 'https://www.la7play.it'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
headers = {'User-Agent': UA, 'Referer': host + '/', 'Origin': host}


def _senza_videoteca(f):
    @functools.wraps(f)
    def interno(*a, **k):
        itemlist = f(*a, **k)
        for it in itemlist or []:
            it.disable_videolibrary = True
        return itemlist
    return interno


GQL_PROGRAMMI = ['75b0227f0361abcf', 'f7034d55158fc906']
GQL_RICERCA = '4da1e384f8a63808'
GQL_PROGRAMMAZIONE = '69f0b39066b90b25'
LIVE = [('La7', '/dirette/la7'), ('La7Cinema', '/dirette/la7-cinema')]
RIVEDI = [('La7', '/guida-tv-rivedi/la7'), ('La7Cinema', '/guida-tv-rivedi/la7-cinema')]


@support.menu
def mainlist(item):
    top = [('Dirette {bold}', ['', 'live']),
           ('Replay {bold}', ['', 'replay_channels'])]

    menu = [('Programmi TV {bullet bold}', ['/programmi', 'peliculas', '', 'tvshow']),
            ('Film {bullet bold}', ['/film', 'peliculas', '', 'movie']),
            ('Documentari {bullet bold}', ['/documentari', 'peliculas', '', 'movie']),
            ('Tg La7 {bullet bold} {teen}', ['/tgla7/puntate', 'episodios', '', 'tvshow']),
            ('Coffee Tech {bullet bold} {teen}', ['/coffee-tech', 'episodios', '', 'tvshow'])]

    search = ''
    return locals()


def _scarica(url):
    try:
        return httptools.downloadpage(url, headers=headers).data or ''
    except Exception as e:
        logger.error('la7: download fallito %s %s' % (url, e))
        return ''


def _pulisci(h):
    return h.replace('\\"', '"').replace('\\u0026', '&').replace('\\/', '/')


def _ld(h):
    nodi = []
    for blocco in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        try:
            j = json.loads(blocco)
        except Exception:
            continue
        nodi.extend(j.get('@graph', [j]) if isinstance(j, dict) else j)
    return nodi


def _elementi(h, tipi=None):
    out = []
    for nodo in _ld(h):
        if nodo.get('@type') != 'ItemList':
            continue
        for el in nodo.get('itemListElement', []):
            it = el.get('item', el)
            if isinstance(it, dict) and (not tipi or it.get('@type') in tipi):
                out.append(it)
        if out:
            break
    return out


def _img(it):
    i = it.get('image', '')
    if isinstance(i, dict):
        i = i.get('url', '')
    return i or ''


def _roma(iso):
    try:
        d = datetime.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S')
    except Exception:
        return ''
    def ultima_domenica(anno, mese):
        g = datetime(anno, mese, 31)
        return g - timedelta(days=(g.weekday() + 1) % 7)
    inizio = ultima_domenica(d.year, 3).replace(hour=1)
    fine = ultima_domenica(d.year, 10).replace(hour=1)
    d = d + timedelta(hours=2 if inizio <= d < fine else 1)
    return d.strftime('%H:%M')


def _programmi():
    for ident in GQL_PROGRAMMI:
        try:
            j = json.loads(_scarica('%s/api/gql/%s' % (host, ident)))
            righe = j['data']['graphqlTuttiProgrammi']['results']
            if righe:
                return righe
        except Exception:
            continue
    return []


def _titolo_visibile(itemlist):
    for it in itemlist:
        if it.fulltitle == 'La7d':
            it.fulltitle = 'La7Cinema'
    return itemlist


def _logo_cinema(h):
    m = re.search(r'(/_next/static/media/logo-la7-cinema\.[^"\\]+\.png)', h)
    return host + m.group(1) if m else ''


def _logo_cinema_replay():
    return _logo_cinema(_pulisci(_scarica(host + '/dirette/la7-cinema')))


def _prog_api(chiave):
    try:
        j = json.loads(_scarica('%s/api/gql/%s/%s' % (host, GQL_PROGRAMMAZIONE, _codifica({'canale': chiave, 'limit': 4}))))
        elenco = j['data']['guidaTvProgrammazione']['programmi'] or []
    except Exception as e:
        logger.error('la7: palinsesto non letto %s' % e)
        return []
    prog = []
    for p in elenco:
        try:
            img = p.get('immagineProgramma') or p.get('immagineScena') or ''
            prog.append((int(p['timestamp']), int(p['durata']), _html.unescape(p['titolo']).strip(), img,
                         str(p.get('isOnAir')).lower() == 'true', p.get('ora', '')))
        except Exception:
            continue
    return prog


def _prog_pagina(h, chiave):
    prog = []
    for blocco in h.split('{"ora":"')[1:]:
        m = re.match(r'(\d{2}:\d{2})","titolo":"([^"]*)","durata":(\d+)', blocco)
        ts = re.search(r'"timestamp":(\d+)', blocco)
        if not m or not ts or ('guidatv/%s/' % chiave) not in blocco:
            continue
        img = re.search(r'"immagineProgramma":"([^"]+)"', blocco) or re.search(r'"immagineScena":"([^"]+)"', blocco)
        prog.append((int(ts.group(1)), int(m.group(3)), _html.unescape(m.group(2)).strip(),
                     img.group(1) if img else '', '"isOnAir":true' in blocco, m.group(1)))
    return prog


def _in_onda(url):
    from time import time
    chiave = url.rstrip('/').split('/')[-1].replace('-', '').upper()
    prog = _prog_api(chiave)
    h = ''
    logo = ''
    if chiave == 'LA7CINEMA' or not prog:
        h = _pulisci(_scarica(url))
        logo = _logo_cinema(h)
    if not prog:
        prog = _prog_pagina(h, chiave)
    adesso = time()
    iniziati = [p for p in prog if p[0] <= adesso < p[0] + p[1] + 3600]
    scelto = max(iniziati, key=lambda p: p[0]) if iniziati else next((p for p in prog if p[4]), None)
    if not scelto:
        return '', '', logo
    testo = scelto[2]
    dopo = [p for p in sorted(prog) if p[0] > scelto[0]]
    if dopo:
        testo += '\nA seguire: %s %s' % (dopo[0][5], dopo[0][2])
    return testo, scelto[3], logo


def live(item):
    from concurrent.futures import ThreadPoolExecutor
    itemlist = []
    for nome, percorso in LIVE:
        f_title = 'La7d' if nome == 'La7Cinema' else nome
        itemlist.append(item.clone(title=support.typo(nome, 'bold'), fulltitle=f_title, url=host + percorso,
                                   action='findvideos', forcethumb=True, no_return=True))
    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            onda = list(ex.map(lambda it: _in_onda(it.url), itemlist))
    except Exception as e:
        logger.error('la7: palinsesto delle dirette non letto %s' % e)
        onda = [('', '', '')] * len(itemlist)
    for it, (t, img, logo) in zip(itemlist, onda):
        if t:
            it.plot = t
            it.infoLabels['plot'] = t
        if img:
            it.fanart = img
    itemlist = _titolo_visibile(support.thumb(itemlist, live=True))
    for it, (t, img, logo) in zip(itemlist, onda):
        if it.fulltitle == 'La7Cinema' and logo:
            it.thumbnail = logo
    return itemlist


def replay_channels(item):
    itemlist = []
    for nome, percorso in RIVEDI:
        f_title = 'La7d' if nome == 'La7Cinema' else nome
        itemlist.append(item.clone(title=support.typo(nome, 'bold'), fulltitle=f_title, url=host + percorso,
                                   action='replay_giorni', forcethumb=True))
    itemlist = _titolo_visibile(support.thumb(itemlist, live=True))
    logo = _logo_cinema_replay()
    for it in itemlist:
        if it.fulltitle == 'La7Cinema' and logo:
            it.thumbnail = logo
    return itemlist


GIORNI = ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']
MESI = ['', 'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre',
        'ottobre', 'novembre', 'dicembre']


def _guida(h):
    h = _pulisci(h)
    marcatori = list(re.finditer(r'"data":"(\d{2}-\d{2}-\d{4})"\},"programma":\[', h))
    giorni = []
    for n, m in enumerate(marcatori):
        fine = marcatori[n + 1].start() if n + 1 < len(marcatori) else len(h)
        programmi = []
        for blocco in h[m.end():fine].split('{"ora":"')[1:]:
            pth = re.search(r'"pathname":"(/[^"]+)"', blocco)
            if not pth:
                continue
            def f(rx):
                r = re.search(rx, blocco)
                return r.group(1) if r else ''
            programmi.append({'ora': blocco[:5], 'titolo': _html.unescape(f(r'"titolo":"([^"]*)"')),
                              'plot': _html.unescape(f(r'"sinossi":"([^"]*)"')),
                              'thumb': f(r'"immagine_scena":"([^"]+)"'), 'url': host + pth.group(1)})
        giorni.append((m.group(1), programmi))
    return giorni


@_senza_videoteca
def replay_giorni(item):
    itemlist = []
    for data, programmi in reversed(_guida(_scarica(item.url))):
        if not programmi:
            continue
        g, me, an = data.split('-')
        try:
            nome = GIORNI[datetime(int(an), int(me), int(g)).weekday()].capitalize()
        except Exception:
            nome = ''
        try:
            if datetime(int(an), int(me), int(g)).date() == datetime.now().date():
                nome = 'Oggi'
        except Exception:
            pass
        itemlist.append(item.clone(title=support.typo('%s %d %s' % (nome, int(g), MESI[int(me)]), 'bold'),
                                   day=data, action='replay', thumbnail=support.thumb()))
    return itemlist


@_senza_videoteca
def replay(item):
    itemlist = []
    for data, programmi in _guida(_scarica(item.url)):
        if data != item.day:
            continue
        for pr in programmi:
            itemlist.append(item.clone(title=support.typo('%s - %s' % (pr['ora'], pr['titolo']), 'bold'),
                                       contentTitle=pr['titolo'], fulltitle=pr['titolo'], show=pr['titolo'],
                                       url=pr['url'], plot=pr['plot'], thumbnail=pr['thumb'], fanart=pr['thumb'],
                                       action='findvideos', forcethumb=True))
    return itemlist


@_senza_videoteca
def peliculas(item):
    if item.url.rstrip('/').endswith('/film'):
        return film(item)
    if item.url.rstrip('/').endswith('/documentari'):
        return documentari(item)
    itemlist = []
    for r in _programmi():
        titolo = _html.unescape(r.get('titolo', '')).strip()
        percorso = r.get('pathname', '')
        if not titolo or not percorso:
            continue
        plot = _html.unescape(re.sub(r'<[^>]+>', '', r.get('occhiello', '') or '')).replace('\xa0', ' ').strip()
        thumb = r.get('img', '') or ''
        if thumb.startswith('/'):
            thumb = host + thumb
        itemlist.append(item.clone(title=support.typo(titolo, 'bold'), fulltitle=titolo, show=titolo, contentSerieName=titolo,
                                   plot=plot, thumbnail=thumb, fanart=thumb, url=host + percorso, action='episodios'))
    _immagini_mancanti(itemlist)
    itemlist.sort(key=lambda i: i.fulltitle.lower())
    return itemlist


def _dati_programma(it):
    h = _pulisci(_scarica(it.url))
    descr = ''
    m = re.search(r'<meta name="description" content="([^"]*)"', h)
    if m:
        descr = _html.unescape(m.group(1)).strip()
    if not descr:
        m = re.search(r'(Prossimamente su [A-Za-z0-9]+)', re.sub(r'<[^>]+>', ' ', h))
        descr = m.group(1) if m else ''
    img = ''
    m = re.search(r'<meta property="og:image" content="([^"]+)"', h)
    if m and 'la7-logo-og' not in m.group(1):
        img = m.group(1)
    else:
        m = re.search(r'(https://images\.la7play\.it/video/[^"\s\\]+/scena-\d+x\d+\.webp)', h)
        img = m.group(1) if m else ''
    testata = ''
    slug = it.url.rstrip('/').rsplit('/', 1)[-1]
    m = re.search(r'(https://images\.la7play\.it/media/c/t\d+/%s[^/"\s\\]*\.\w+/img/1280x720\.webp)' % re.escape(slug), h)
    testata = m.group(1) if m else ''
    return descr, img, testata, not it.plot


def _immagini_mancanti(itemlist):
    from concurrent.futures import ThreadPoolExecutor
    vuoti = [it for it in itemlist if not it.thumbnail or not it.plot]
    if not vuoti:
        return
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            dati = list(ex.map(_dati_programma, vuoti))
    except Exception as e:
        logger.error('la7: dati dei programmi non letti %s' % e)
        return
    for it, (descr, img, testata, senza_descr) in zip(vuoti, dati):
        if descr and not it.plot:
            it.plot = descr
            it.infoLabels['plot'] = descr
        if not it.thumbnail and img:
            it.thumbnail = img
            it.fanart = img
        if senza_descr and testata:
            it.thumbnail = testata
            it.fanart = testata


@_senza_videoteca
def episodios(item):
    url = item.url
    pagina = int(item.page or 1) if hasattr(item, 'page') and item.page else 1
    if '/puntate' not in url:
        url = url.rstrip('/') + '/puntate'
    base = url.split('?')[0]
    h = _scarica(base + ('?page=%d' % pagina if pagina > 1 else ''))
    elementi = _elementi(h, ('TVEpisode',))
    if not elementi and pagina == 1:
        elementi = _elementi(_scarica(base.replace('/puntate', '')), ('TVEpisode', 'TVClip'))
    itemlist = []
    for ep in elementi:
        titolo = _html.unescape(ep.get('name', '')).strip()
        if not ep.get('url'):
            continue
        data = ep.get('datePublished', '')[:10]
        itemlist.append(item.clone(title=support.typo(titolo, 'bold'), fulltitle=titolo, show=item.fulltitle or titolo,
                                   contentTitle=titolo, url=ep['url'], thumbnail=_img(ep), fanart=_img(ep),
                                   plot=data, action='findvideos', forcethumb=True))
    _dettagli(itemlist)
    if len(elementi) >= 20:
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),
                                   url=base, page=pagina + 1, action='episodios', nextPage=True, thumbnail=support.thumb()))
    return itemlist


def _dettagli(itemlist):
    from concurrent.futures import ThreadPoolExecutor

    def leggi(it):
        if it.action != 'findvideos':
            return {}
        h = _scarica(it.url)
        unito = {}
        for nodo in _ld(h):
            if nodo.get('@type') in ('Movie', 'TVEpisode', 'VideoObject'):
                for k, v in nodo.items():
                    if v and k not in unito:
                        unito[k] = v
        return unito

    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            nodi = list(ex.map(leggi, itemlist))
    except Exception as e:
        logger.error('la7: dettagli non letti %s' % e)
        return itemlist
    for it, n in zip(itemlist, nodi):
        trama = _html.unescape(re.sub(r'<[^>]+>', ' ', n.get('description', ''))).replace('\xa0', ' ').strip()
        if trama:
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})$', it.plot or '')
            if m:
                trama = '%s/%s/%s\n\n%s' % (m.group(3), m.group(2), m.group(1), trama)
            it.plot = trama
            it.infoLabels['plot'] = trama
        if re.match(r'\d{4}$', str(n.get('dateCreated', ''))):
            it.infoLabels['year'] = int(n['dateCreated'])
        it.infoLabels.pop('duration', None)
        gen = n.get('genre', '')
        gen = [g for g in (gen if isinstance(gen, list) else [gen]) if g and g != 'Film']
        if gen:
            it.infoLabels['genre'] = ', '.join(gen)
        reg = n.get('director')
        reg = reg.get('name', '') if isinstance(reg, dict) else ''
        if reg:
            it.infoLabels['director'] = reg
    return itemlist


@_senza_videoteca
def film(item):
    itemlist = []
    for f in _elementi(_scarica(host + '/film'), ('Movie',)):
        titolo = _html.unescape(f.get('name', '')).strip()
        if not f.get('url'):
            continue
        itemlist.append(item.clone(title=support.typo(titolo, 'bold'), fulltitle=titolo, contentTitle=titolo,
                                   url=f['url'], thumbnail=_img(f), fanart=_img(f), contentType='movie',
                                   action='findvideos', forcethumb=True))
    return _dettagli(itemlist)


@_senza_videoteca
def documentari(item):
    itemlist = []
    for d in _elementi(_scarica(host + '/documentari'), ('Movie', 'TVEpisode')):
        titolo = _html.unescape(d.get('name', '')).strip()
        if not d.get('url'):
            continue
        itemlist.append(item.clone(title=support.typo(titolo, 'bold'), fulltitle=titolo, contentTitle=titolo,
                                   url=d['url'], thumbnail=_img(d), fanart=_img(d), contentType='movie',
                                   action='findvideos', forcethumb=True))
    return _dettagli(itemlist)


def _codifica(variabili):
    t = json.dumps(variabili, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    return base64.urlsafe_b64encode(t.encode('utf-8')).decode('ascii').rstrip('=')


@_senza_videoteca
def search(item, text):
    q = str(getattr(item, 'search', '') or text).strip()
    if not q:
        return []
    pagina = int(getattr(item, 'page', 0) or 1)
    var = {'q': q}
    if pagina > 1:
        var['page'] = pagina
    try:
        j = json.loads(_scarica('%s/api/gql/%s/%s' % (host, GQL_RICERCA, _codifica(var))))
        dati = j['data']['siteSearch']
    except Exception as e:
        logger.error('la7: ricerca fallita %s' % e)
        return []
    itemlist = []
    for gruppo in dati.get('groups', []):
        if gruppo.get('contentType') == 'article':
            continue
        for h in gruppo.get('hits', []):
            url = h.get('url')
            if not url:
                continue
            titolo = _html.unescape(h.get('title', '')).strip()
            programma = h.get('propertyName') or ''
            thumb = h.get('imageUrl') or ''
            video = bool(re.search(r'-\d{5,}$', url))
            plot = _html.unescape(h.get('excerpt') or '')
            itemlist.append(item.clone(
                title=support.typo(titolo + (' (%s)' % programma if programma and video else ''), 'bold'),
                fulltitle=titolo, contentTitle=titolo, show=programma or titolo, url=host + url,
                thumbnail=thumb, fanart=thumb, plot=plot, forcethumb=True,
                action='findvideos' if video else 'episodios'))
    if pagina < int(dati.get('totalPages') or 1):
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),
                                   search=q, page=pagina + 1, action='search_page', nextPage=True,
                                   thumbnail=support.thumb()))
    return itemlist


@_senza_videoteca
def search_page(item):
    return search(item, item.search)


def _token(endpoint, ident, tipo):
    try:
        data = httptools.downloadpage('%s?id=%s&contentType=%s' % (endpoint, ident, tipo), headers=headers).data
        j = json.loads(data)
        return j.get('preAuthToken') or j.get('token') or j.get('auth') or ''
    except Exception as e:
        logger.error('la7: token non ottenuto %s' % e)
        return ''


def _licenza(server, token):
    for parte in server.split(';'):
        if parte.lower().startswith(DRM):
            url = parte.split('|', 1)[1]
            return '%s|preAuthorization=%s&Origin=%s&Referer=%s/|R{SSM}|' % (url, token, host, host + '/')
    return ''


def findvideos(item):
    h = _pulisci(_scarica(item.url))

    def g(rx):
        m = re.search(rx, h)
        return m.group(1) if m else ''

    endpoint = g(r'"drmTokenEndpoint":"([^"]+)"')
    ident = g(r'"drmContentId":"([^"]+)"')
    server = g(r'"drmLicenseServer":"([^"]+)"')
    url = ''
    drm = False
    tipo = 'VOD'

    if '/dirette/' in item.url:
        principale = g(r'"mainLiveUrl":"([^"]+)"').split('|')[0]
        url = principale
        drm = True
        tipo = 'LIVE'
    else:
        remoto = g(r'"cf_remote_url":"([^"]+)"')
        if not remoto:
            logger.error('la7: video non trovato in %s' % item.url)
            return []
        vecchio = g(r'"cf_old_entry_id":"([^"]+)"')
        drm = g(r'"drm":(true|false)') == 'true'
        if drm:
            base = g(r'"hostnameCdnDrm":"([^"]+)"').rstrip('/')
            nome = remoto.lstrip('/').split('/')[-1]
            url = '%s/%s/DASH/%s.mpd' % (base, nome, nome)
        else:
            base = g(r'"hostnameCdn":"([^"]+)"').rstrip('/')
            percorso = (remoto if remoto.startswith('/') else '/' + remoto).replace('.mp4', '')
            if not vecchio:
                parti = []
                for p in percorso.split(','):
                    p = p.strip()
                    parti.append(p if not p or p.startswith('/nk/') else ('/nk' + p if p.startswith('/') else '/nk/' + p))
                percorso = ','.join(parti)
            url = '%s/local/hls/,%s,.mp4.urlset/master.m3u8' % (base, percorso)

    if not url:
        return []
    it = item.clone(title='Direct', server='directo', url=url, action='play')
    if drm:
        token = _token(endpoint, ident, tipo)
        it.drm = DRM
        it.license = _licenza(server, token)
    return support.server(it, itemlist=[it], Download=False, Videolibrary=False)
