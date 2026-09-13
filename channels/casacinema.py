# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 'casacinema'
#
# Flusso:
#   - film    : check -> findvideos -> play (token vidxgo dall'IMDb/TMDB)
#   - serie   : check/peliculas -> episodios (probe vidxgo) -> lista episodi
#               -> findvideos -> play
#   - libreria: "Aggiungi alla videoteca" in fondo alla lista episodi;
#               l'azione e' esposta dal canale (il launcher instrada
#               getattr(channel, item.action) -> casacinema.addToLibrary)
# ------------------------------------------------------------


from core import support, httptools
from platformcode import logger
import re, html, sys

host = support.config.get_channel_url()
headers = [['Referer', host]]


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

    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


@support.scrape
def peliculas(item):
    action = 'check'
    patron = r'<div class="posts".*?<a href="(?P<url>[^"]+)[^>]+>[^>]+>[^>]+>(?P<title>[^\(\[<]+)(?:\[(?P<quality1>HD)\])?'
    patronNext = r'<a href="([^"]+)"\s*>Pagina'

    # il listato corrente: se e' serie-tv/miniserie-tv, TUTTI gli item sono serie
    # (le pagine dettaglio stanno sotto /gratis/, quindi l'URL del listato e'
    # l'unica fonte affidabile per il typing)
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
                it.action = 'episodios'          # invocazione diretta dal launcher
                it.context = "['addToLibrary']"  # voce anche nel context menu
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


def _episode_list(item, token, pairs):
    """Directory episodi: action='findvideos' (non 'play', altrimenti il
    launcher fa autoplay/popup invece di mostrare la pagina)."""
    itemlist = []
    for s, e in pairs:
        it = item.clone(action='findvideos')
        it.contentType = 'episode'
        it.contentSeason = s
        it.contentEpisode = e
        it.contentTitle = item.contentTitle or item.fulltitle
        it.title = '%dx%02d' % (s, e)
        itemlist.append(it)

    # "Aggiungi alla videoteca" in fondo: il launcher di questo fork non
    # appende mai la voce da solo; il canale la fornisce e ne espone l'azione
    cl = item.clone(action='addToLibrary')
    cl.contentType = 'tvshow'
    cl.contentTitle = item.contentTitle or item.fulltitle
    cl.fulltitle = cl.contentTitle
    cl.show = cl.contentTitle                    # nome cartella in videoteca
    cl.from_action = 'episodios'
    cl.title = '[B][COLOR cyan]Aggiungi alla Videoteca[/COLOR][/B]'
    itemlist.append(cl)
    return itemlist


# ------------------------- azioni -------------------------

def check(item):
    """Router: serie -> episodios (con probe gia' fatto), film -> findvideos."""
    data = httptools.downloadpage(item.url, cloudscraper=True).data or ''
    token = _token_from_data(data)
    if token:
        from servers import vidxgo as srv_v
        info = srv_v.probe(token)
        if info['mode'] == 'tv':
            item.contentType = 'tvshow'
            item.contentTitle = item.contentTitle or item.fulltitle
            if not info['episodes']:
                logger.info('serie %s senza episodi su vidxgo' % token)
                return []
            item.vidxgo_pairs = info['episodes']    # passa il risultato...
            return episodios(item)                  # ...a episodios
    return findvideos(item)


def episodios(item):
    """Enumerazione episodi (lista canale e servizio videoteca).
    Se arriva da check, il probe e' gia' stato fatto: usa l'handoff."""
    logger.info()
    pairs = getattr(item, 'vidxgo_pairs', None)
    if not pairs:
        data = httptools.downloadpage(item.url, cloudscraper=True).data or ''
        token = _token_from_data(data)
        if not token:
            logger.error('episodios: token non trovato su ' + item.url)
            return []
        from servers import vidxgo as srv_v
        pairs = srv_v.probe(token)['episodes']
    if not pairs:
        logger.info('episodios: nessun episodio')
        return []
    return _episode_list(item, None, pairs)


def findvideos(item):
    logger.info()

    if getattr(item, 'server_links', ''):
        return support.server(item, data=item.server_links)

    data = support.httptools.downloadpage(item.url, cloudscraper=True).data or ''
    if not data:
        return []

    # token dal JS della pagina (imdb, altrimenti tmdb)
    token = _token_from_data(data)
    if not token:
        logger.error('findvideos: token non trovato su ' + item.url)
        return []

    s = int(getattr(item, 'contentSeason', 0) or 0)
    e = int(getattr(item, 'contentEpisode', 0) or 0)

    from servers import vidxgo as srv_v

    # episodio diretto (arriva da _episode_list con contentSeason/contentEpisode)
    if s and e:
        it = item.clone(action='play', server='vidxgo',
                        url='https://v.vidxgo.co/%s/%d/%d' % (token, s, e))
        it.contentTitle = item.contentTitle or item.fulltitle
        return support.server(item, itemlist=[it])

    # niente s/e -> chiediamo a vidxgo se il token e' una serie
    # (rete di sicurezza per entry dirette che saltano check)
    info = srv_v.probe(token)
    if info['mode'] == 'tv':
        if not info['episodes']:
            logger.info('serie %s senza episodi su vidxgo' % token)
            return []                      # niente popup destinato al 404
        itemlist = []
        for ps, pe in info['episodes']:
            it = item.clone(action='play', server='vidxgo',
                            url='https://v.vidxgo.co/%s/%d/%d' % (token, ps, pe))
            it.contentSeason = ps
            it.contentEpisode = pe
            it.contentTitle = item.contentTitle or item.fulltitle
            it.title = '%dx%02d' % (ps, pe)
            itemlist.append(it)
        return itemlist

    # film
    it = item.clone(action='play', url='https://v.vidxgo.co/' + token)
    it.contentTitle = item.contentTitle or item.fulltitle
    return support.server(item, itemlist=[it])


def addToLibrary(item):
    """'Aggiungi alla videoteca': il launcher instrada l'azione al canale
    (getattr(channel, item.action)), quindi il canale deve esporla."""
    from core import videolibrarytools
    return videolibrarytools.add_to_videolibrary(item, sys.modules[__name__])
