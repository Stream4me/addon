import base64
import re
from urllib.parse import quote_plus, quote, unquote, urlsplit

from core import support, httptools, scrapertools
from core.item import Item

host = base64.b64decode('aHR0cHM6Ly9sb29uZXguZXUvY2FydG9uaQ==').decode().rstrip('/')
_p = urlsplit(host)
RADICE = '%s://%s' % (_p.scheme, _p.netloc)
PREFISSO = _p.path
headers = [['Referer', host + '/']]


def _abs(url):

    if not url or url.startswith('http'):
        return url
    if url.startswith(PREFISSO + '/'):
        return RADICE + url
    return host + '/' + url.lstrip('/')


CATEGORIE = [('Animali', 'Animali'), ('Animazione', 'Animazione'), ('Otaku', 'Anime'),
             ('Fandub', 'Fandub'), ('Fanmade', 'Fanmade'), ('Film', 'Film'),
             ('Gli introvabili', 'Gli introvabili'), ('Horror', 'Horror'), ('Indie', 'Indie'),
             ('Made in Italy', 'Made in Italy'), ('SUB ITA', 'SUB ITA'),
             ('Umani', 'Umani'), ('Umani e Animali', 'Umani e Animali')]


@support.menu
def mainlist(item):
    top = [('Tutti i cartoni', ['/index.php?sort=title', 'peliculas', '', 'undefined']),
           ('Più recenti', ['/index.php?sort=newest', 'peliculas', '', 'undefined']),
           ('Più visti', ['/index.php?sort=views', 'peliculas', '', 'undefined'])]

    categorie = [(t, ['/index.php?cat=' + quote_plus(v), 'peliculas', '',
                      'movie' if v == 'Film' else 'undefined'])
                 for t, v in CATEGORIE]
    search = ''
    return locals()


ICONE = {
    'più recenti': 'news',
    'più visti': 'popular',
    'animali': 'children',
    'otaku': 'anime',
    'fandub': 'music',
    'fanmade': 'community',
    'gli introvabili': 'favorites',
    'indie': 'alternative',
    'made in italy': 'italian',
    'sub ita': 'vos',
    'umani': 'star',
    'umani e animali': 'family',
}

_mainlist_base = mainlist


def mainlist(item):
    from channelselector import get_thumb
    itemlist = _mainlist_base(item)
    for it in itemlist:
        nome = re.sub(r'\[[^\]]*\]', '', it.title or '').strip().lower()
        if nome in ICONE:
            it.thumbnail = get_thumb(ICONE[nome] + '.png')
        if nome in ('tutti i cartoni', 'più recenti', 'più visti'):

            it.title = re.sub(r'\[[^\]]*\]', '', it.title).strip()
    dona = Item(channel=item.channel, action='open_browser', url=host + '/dona.php',
                title=support.typo('Sostieni il sito', 'bold'),
                thumbnail=get_thumb('star.png'), folder=False)
    pos = len(itemlist)
    for i, it in enumerate(itemlist):
        if it.channel == 'setting' or it.action == 'channel_config' or 'onfigurazione' in (it.title or ''):
            pos = i
            break
    itemlist.insert(pos, dona)
    return itemlist


def _titolo_tmdb(titolo):

    t = titolo or ''
    anno = ''
    m = re.search(r'\((?:19|20)\d{2}\)|\s(?:19|20)\d{2}\s*$', t)
    if m:
        anno = re.search(r'(?:19|20)\d{2}', m.group(0)).group(0)
    t = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', t)
    t = re.sub(r'\s(?:19|20)\d{2}\s*$', '', t)
    t = re.split(r'\s[|/]\s', t)[0]
    t = re.sub(r'\b(?:SUB\s*)?ITA\b', '', t, flags=re.I)
    return re.sub(r'\s+', ' ', t).strip(' -:'), anno


@support.scrape
def peliculas(item):

    patron = (r'<a href="(?P<url>index\.php\?(?:scheda|cartone)=[^"]+)"[^>]*>\s*'
              r'<div class="cartoon-card-cinematic[^"]*">\s*'
              r'<img src="(?P<thumb>[^"]+)"[^>]*alt="(?P<title>[^"]*)".*?'
              r'<div class="card-title-cine-v2')

    patronNext = r'href="([^"#]+)(?:#archivio)?" aria-label="Pagina successiva"'

    action = 'check'
    typeContentDict = {}

    def itemHook(it):
        it.url = _abs(it.url)
        it.thumbnail = _abs(it.thumbnail)
        it.contentType = 'movie' if item.contentType == 'movie' else 'undefined'

        nome, anno = _titolo_tmdb(it.title)
        if nome:
            it.contentSerieName = nome
            it.contentTitle = nome
            it.fulltitle = nome
            it.show = nome
            if anno:
                it.infoLabels['year'] = anno
        return it


    return locals()


def search(item, text):
    support.info('search', item, text)
    item.url = host + '/index.php?search=' + text.replace(' ', '+')
    item.contentType = 'undefined'
    try:
        return peliculas(item)
    except Exception:
        import sys
        for line in sys.exc_info():
            support.info('search log:', line)
        return []


def newest(categoria):
    support.info('newest ->', categoria)
    item = Item()
    try:
        if categoria == 'series':
            item.url = host + '/index.php?sort=newest'
            item.action = 'peliculas'
            return peliculas(item)
    except Exception:
        import sys
        for line in sys.exc_info():
            support.info('newest log:', line)
    return []


_M = 0xFFFFFFFF


def _rk(seed):
    h = (seed * 0x01000193) & _M
    k = []
    for i in range(32):
        h = ((h ^ ((i * 109 + 89) & _M)) * 0x01000193) & _M
        k.append((h >> ((i % 4) * 8)) & 0xFF)
    return k


def _rdec(b64, seed):
    try:
        k = _rk(seed)
        b = base64.b64decode(b64 + '=' * (-len(b64) % 4))
        return ''.join(chr(c ^ k[i % 32] ^ ((i * 19 + 53) & 0xFF)) for i, c in enumerate(b))
    except Exception:
        return ''


def _valid(u):
    return len(u) >= 8 and (u[0] == '/' or u.startswith('http')) \
        and re.fullmatch(r'[\x21-\x7E]+', u) is not None


def _real(val, seed):
    r = _rdec(val, seed)
    if _valid(r):
        return r
    for s in list(range(17, 90)) + [x for x in range(1, 129) if not 17 <= x <= 89]:
        r = _rdec(val, s)
        if _valid(r):
            return r
    return ''


def _url_episodio(a, data):

    enc = scrapertools.find_single_match(a, r'data-lx-play="([^"]+)"')
    if enc:
        m = re.search(r'var _seed = (\d+)', data)
        default_seed = int(m.group(1)) if m else 44
        seed = scrapertools.find_single_match(a, r'data-s="(\d+)"')
        url = _real(enc, int(seed) if seed else default_seed)
    else:
        url = scrapertools.find_single_match(a, r'href="([^"]+)"')
    if url and url.startswith('/'):
        url = RADICE + url
    return url


def _tutte(data):

    import html
    data = re.sub(r'\s+|&nbsp;', ' ', data)
    righe = []
    for blk in re.split(r'(?=<div class="episode-item-row)', data)[1:]:
        blk = blk[:blk.find('</a>') + 4] if '</a>' in blk else blk
        title = html.unescape(scrapertools.find_single_match(blk, r'data-ep-title="([^"]*)"') or 'Episodio')
        gruppo = html.unescape(scrapertools.find_single_match(blk, r'data-season="([^"]*)"'))
        a = scrapertools.find_single_match(blk, r'(<a [^>]*btn-play-action[^>]*>)')
        righe.append((title.strip(), gruppo.strip(), _url_episodio(a, data) if a else ''))
    if not righe:

        a = scrapertools.find_single_match(data, r'(<a [^>]*data-lx-play=[^>]*>)')
        url = _url_episodio(a, data) if a else ''
        if not url:
            url = scrapertools.find_single_match(data, r'<a id="cartoonResumeBtn" href="([^"]+guarda\.php[^"]*)"')
        if url:
            righe.append(('Film completo', 'Film', url))
    return righe


def _righe(item, data):
    return [r for r in _tutte(data) if r[2]]


def _e_film(titolo, gruppo):
    return '[film]' in (titolo + ' ' + gruppo).lower()


def _stagione_gruppo(g):

    m = re.search(r'(?i)\b(?:stagione|season)\s*(\d+)', g or '')
    return int(m.group(1)) if m else None


def _serie_gruppo(base, g):

    base = (base or '').strip()
    anno = ''
    m = re.search(r'(?:19|20)\d{2}', g)
    if m:
        anno = m.group(0)
    speciale = re.search(r'(?i)\b(?:films?|episodi|speciali|speciale|special|extra|oav|ova)\b', g) is not None
    tag = [x.strip() for x in re.findall(r'\[([^\]]*)\]', g)
           if re.match(r'(?i)^[a-z][a-z ]*$', x.strip())
           and not re.search(r'(?i)\b(?:film|sub|ita|ai|hd)\b', x)]
    t = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', g)
    t = re.sub(r'(?i)\b(?:stagione|season)\s*\d+\b', ' ', t)
    t = re.sub(r'(?i)\b(?:films?|episodi|speciali|speciale|special|serie completa|completa)\b', ' ', t)
    t = re.sub(r'\b(?:19|20)\d{2}\b', ' ', t)
    t = re.sub(r'(?i)^\s*e\s+|\s+e\s*$', ' ', t)
    t = re.sub(r'\s+', ' ', ' '.join(tag + [t])).strip(' -:')
    if not t:
        t = base
    elif base and base.lower() not in t.lower():
        t = base + ' ' + t
    return t, anno, speciale


def _titolo_gruppo(base, g):

    t = re.sub(r'\((?=[^)]*(?:\d{3,4}p|loghi))[^)]*\)', ' ', g)
    t = re.sub(r'\[([^\]]*)\]', r' \1 ', t)
    t = re.sub(r'\s+', ' ', t).strip(' -:')
    if base and g.lstrip().startswith('[') and base.lower() not in t.lower():
        t = base + ' ' + t
    return t


def _resto(titolo, fine):
    r = titolo[fine:].strip()
    return re.sub(r'^[\s\-:.]+', '', r).strip()


def _numeri(titolo):

    m = re.match(r'\s*S(\d+)\s*[eE](\d+)\b', titolo)
    if m:
        return int(m.group(1)), int(m.group(2)), _resto(titolo, m.end())
    m = re.search(r'\bN\s*(\d+)x(\d+)', titolo) or re.search(r'\bV\s*(\d+)x(\d+)', titolo) \
        or re.match(r'\s*(\d+)x(\d+)\b', titolo)
    if m:
        return int(m.group(1)), int(m.group(2)), _resto(titolo, m.end())
    m = re.match(r'\s*(\d+)\s*-\s*(.*)$', titolo)
    if m:
        return None, int(m.group(1)), m.group(2)
    return None, None, titolo


_CACHE = {}
_NOMI = {}


def _nome_player(url):
    if url in _NOMI:
        return _NOMI[url]
    nome = ''
    try:
        import html as _h
        pagina = httptools.downloadpage(url, headers=headers, ignore_response_code=True).data
        t = scrapertools.find_single_match(pagina, r'<title>(.*?)</title>')
        t = _h.unescape(t.split('|')[0]).strip()
        nome = _numeri(t)[2] if _numeri(t)[1] else ''
    except Exception:
        nome = ''
    _NOMI[url] = nome
    return nome


def _precarica_nomi(tutte, gruppo):
    from concurrent import futures
    da_fare = [u for t, g, u in tutte
               if u and (not gruppo or g == gruppo) and not _e_film(t, g)
               and not _numeri(t)[2] and u not in _NOMI]
    if da_fare:
        with futures.ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(_nome_player, da_fare))


def check(item):


    support.info('check', item.url)
    data = httptools.downloadpage(item.url, headers=headers, ignore_response_code=True).data
    righe = _righe(item, data)
    if len(righe) == 1:
        item.contentType = 'movie'
        item.url = righe[0][2]
        return findvideos(item)
    gruppi = []
    for r in righe:
        if r[1] not in gruppi:
            gruppi.append(r[1])
    if len(gruppi) > 1:
        item.action = 'peliculas'
        return gruppi_menu(item, righe, gruppi)
    anni = [r for r in righe if _titolo_tmdb(r[0])[1]]
    serie = any(_numeri(r[0])[1] is not None for r in righe if not _e_film(r[0], r[1]))
    if not serie and (item.contentType == 'movie' or (item.contentType == 'undefined' and anni)):
        item.contentType = 'movie'
        item.action = 'peliculas'
        return film(item, righe)
    item.contentType = 'tvshow'
    for k in ('tmdb_id', 'imdb_id', 'tvdb_id', 'code', 'selected_tmdb_id'):
        item.infoLabels[k] = ''
    item.url = _pseudo(item.url)
    _CACHE[item.url] = data
    return stagioni(item, righe)


def _diversa(thumb, n):

    return '%s#%d' % (thumb, n) if thumb else thumb


def gruppi_menu(item, righe, gruppi):

    itemlist = []
    film_list = []
    base = _titolo_tmdb(item.fulltitle or item.contentSerieName or item.title or '')[0]
    for g in gruppi:
        rg = [r for r in righe if r[1] == g]
        solo_film = (re.search(r'(?i)\bfilms?\b', g) and not re.search(r'(?i)\bepisodi', g)
                     and all(_titolo_tmdb(r[0])[1] for r in rg))
        if solo_film or all(_e_film(r[0], r[1]) for r in rg):
            film_list.extend(rg)
            continue
        nome, anno, speciale = _serie_gruppo(base, g)
        it = Item(channel=item.channel, action='episodios', url=_pseudo(item.url, g), gruppo=g, speciale=speciale,
                  contentType='tvshow', title=support.typo(_titolo_gruppo(base, g), 'bold'),
                  fulltitle=nome or g, show=nome or g, contentSerieName=nome or g,
                  thumbnail=_diversa(item.thumbnail, len(itemlist) + 1),
                  infoLabels={'year': anno} if anno else {})
        itemlist.append(it)
    if itemlist:
        thumbs = [i.thumbnail for i in itemlist]
        try:
            from core import tmdb
            tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        except Exception:
            pass
        for i, t in zip(itemlist, thumbs):
            i.thumbnail = t
    itemlist.extend(film(item, film_list, gruppo_nome=True))
    return itemlist


def film(item, righe, gruppo_nome=False):

    itemlist = []
    for title, season, url in righe:
        generico = re.match(r'(?i)\s*film completo', title) is not None
        base = re.sub(r'(?i)\s*\[film\]', '', season if (gruppo_nome and generico) else title).strip()
        nome, anno = _titolo_tmdb(base)
        nome = nome or base
        it = Item(channel=item.channel, action='findvideos', url=url,
                  contentType='movie', title=base, fulltitle=nome,
                  show=nome, contentTitle=nome, thumbnail=_diversa(item.thumbnail, len(itemlist) + 1),
                  infoLabels={'year': anno} if anno else {})
        it.order = (int(anno or 9999), len(itemlist))
        itemlist.append(it)
    itemlist.sort(key=lambda x: x.order)
    try:
        from core import tmdb
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    except Exception:
        pass
    return itemlist


def _pulisci(url):

    url = (url or '').strip()
    if not url:
        return url
    url = _abs(url)
    url = url.replace(PREFISSO + PREFISSO + '/', PREFISSO + '/')
    return re.sub(r'(?<!:)/{2,}', '/', url)


def _pseudo(url, gruppo=''):

    m = re.search(r'[?&](scheda|cartone)=([^&#]+)', url or '')
    if not m:
        return url
    return '%s/lx/%s/%s/%s' % (host, m.group(1), m.group(2), quote(gruppo or '', safe=''))


def _reale(url, gruppo):

    m = re.search(r'/lx/(scheda|cartone)/([^/]+)/([^/?#]*)', url or '')
    if not m:
        return _pulisci(url), gruppo or ''
    g = unquote(m.group(3)) if m.group(3) else ''
    return '%s/index.php?%s=%s' % (host, m.group(1), m.group(2)), gruppo or g


def stagioni(item, righe):

    trovate = []
    for titolo, g, url in righe:
        if not url or _e_film(titolo, g):
            continue
        s = _numeri(titolo)[0]
        s = s if s is not None else (_stagione_gruppo(g) or (0 if item.speciale else 1))
        if s not in trovate:
            trovate.append(s)
    trovate.sort()
    if not trovate:
        return episodios(item)
    itemlist = []
    for s in trovate:
        itemlist.append(item.clone(title=support.typo('Stagione %d' % s if s else 'Speciali', 'bold'),
                                   action='episodios', contentType='season', season=s,
                                   contentSeason=s, thumbnail=item.thumbnail))
    support.videolibrary(itemlist, item)
    return itemlist


def episodios(item):

    chiave = item.url
    reale, gruppo = _reale(item.url, item.gruppo)
    item.gruppo = gruppo
    support.info('loonex episodios:', gruppo, item.contentChannel)

    data = _CACHE.get(chiave, '') or httptools.downloadpage(
        reale, headers=headers, ignore_response_code=True).data
    tutte = _tutte(data)
    _precarica_nomi(tutte, gruppo)
    conta = {}
    itemlist = []
    solo = item.season if item.contentType == 'season' else None

    for titolo, g, url in tutte:
        if not url or (gruppo and g != gruppo):
            continue
        s, e, nome = _numeri(titolo)
        if not nome:
            nome = _NOMI.get(url, '')
        conta[g] = conta.get(g, 0) + 1
        s = s if s is not None else (_stagione_gruppo(g) or (0 if item.speciale else 1))
        e = e or conta[g]
        if solo is not None and not _e_film(titolo, g) and s != solo:
            continue
        if _e_film(titolo, g):
            base = re.sub(r'(?i)\s*\[film\]', '', titolo).strip()
            n2, anno = _titolo_tmdb(base)
            it = item.clone(title=support.typo(base, 'bold'), url=url, action='findvideos',
                            contentType='movie', fulltitle=n2 or base, show=n2 or base,
                            contentTitle=n2 or base, thumbnail=item.thumbnail)
            if anno:
                it.infoLabels['year'] = anno
            itemlist.append(it)
            continue
        nome = support.cleantitle(nome).strip()
        itemlist.append(item.clone(
            title=support.typo('%dx%02d' % (s, e) + (' - ' + nome if nome else ''), 'bold'),
            url=url, action='findvideos', contentType='episode',
            season=s, episode=e, contentSeason=s, contentEpisodeNumber=e,
            contentTitle=nome, fulltitle=item.fulltitle or item.contentSerieName,
            show=item.fulltitle or item.contentSerieName,
            contentSerieName=item.contentSerieName,
            thumbnail=item.thumbnail))

    itemlist.sort(key=lambda x: (x.contentSeason or 0, x.contentEpisodeNumber or 0))
    if itemlist and not support.stackCheck(['add_tvshow', 'get_newest']):
        from core import tmdb
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        for i in itemlist:
            if i.contentType != 'episode':
                continue
            tn = (i.infoLabels.get('title') or '').strip()
            serie = (i.contentSerieName or i.fulltitle or '').strip().lower()
            if not tn or tn.lower() == serie:
                tn = _NOMI.get(i.url, '') or i.contentTitle or ''
            tn = support.cleantitle(tn).strip()
            i.title = support.typo('%dx%02d' % (i.contentSeason, i.contentEpisodeNumber)
                                   + (' - ' + tn if tn else ''), 'bold')
    if item.contentType != 'season':
        support.videolibrary(itemlist, item)
    return itemlist


def findvideos(item):

    item.url = _pulisci(item.url)
    video = Item(channel=item.channel, server='loonex', url=item.url, title='Loonex')
    return support.server(item, itemlist=[video], referer=False)
