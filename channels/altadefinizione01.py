# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per altadefinizione01
# ------------------------------------------------------------

from core import scrapertools, httptools, support
from core.item import Item
from platformcode import config, logger

host = config.get_channel_url()
headers = [['Referer', host]]


@support.menu
def mainlist(item):
    menu = [
        ('Tutti', ['/lastnews/', 'peliculas', '', 'undefined']),
        ('Al Cinema {submenu}', ['/cinema/', 'peliculas', '', 'undefined']),
        ('Ultimi Aggiornati-Aggiunti {submenu}', ['', 'peliculas', 'update']),
        ('Generi {submenu}', ['', 'genres', 'genres', 'undefined']),
        ('Lettera {submenu}', ['/catalog/a', 'genres', 'orderalf', 'undefined']),
        ('Anni {submenu}', ['', 'genres', 'years', 'undefined']),
        ('Sub-ITA {submenu}', ['/sub-ita/', 'peliculas', '', 'undefined']),
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
        patronBlock = r'<div class="cover_kapsul ml-mask">(?P<block>.*)<div class="page_nav">'
        patron = (
            r'<div class="cover boxcaption"> +<h2>\s*<a href="(?P<url>[^"]+)">(?P<title>[^<]+).*?'
            r'src="(?P<thumb>[^"]+).*?'
            r'(?:<div class="trdublaj">|<span class="se_num">)(?P<quality>[^<]+).*?'
            r'<span class="ml-label">(?P<year>[0-9]+).*?'
            r'<span class="ml-label">(?P<duration>[^<]+).*?'
            r'<p>(?P<plot>[^<]+)'
        )
        patronNext = '<span>\d</span> <a href="([^"]+)">'

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


def episodios(item):
    """
    Genera la lista episodi 12x24 e replica il comportamento di StreamingCommunity:
    - contentSeason e contentEpisodeNumber sugli item
    - arricchimento TMDB
    - check Trakt
    - videoteca
    """
    support.info('episodios', item)

    # Scarica la pagina per ottenere IMDB ID
    data = item.data if hasattr(item, 'data') and item.data else httptools.downloadpage(item.url).data

    # Estrai IMDB ID
    imdb_id = None
    match = support.match(data, patron=r'<p id="imdb">(tt\d+)</p>').match
    if match:
        imdb_id = match
    if not imdb_id:
        match = support.match(data, patron=r"var imdb = '(tt\d+)'").match
        if match:
            imdb_id = match

    if not imdb_id:
        support.info('IMDB ID non trovato per la serie!')
        return []

    support.info(f'IMDB ID serie: {imdb_id}')

    # Genera la lista episodi 12x24 (come fa il sito)
    max_seasons = 12
    max_episodes = 24

    itemlist = []
    for season in range(1, max_seasons + 1):
        for episode in range(1, max_episodes + 1):
            new_item = item.clone()
            new_item.action = 'findvideos'
            new_item.contentType = 'episode'
            new_item.season = season
            new_item.episode = episode
            # Campi che Stream4Me usa per identificare l'episodio
            new_item.contentSeason = season
            new_item.contentEpisodeNumber = episode
            # Titolo in formato riconosciuto
            new_item.title = f"{season}x{episode:02d}"
            # Serie di appartenenza
            new_item.contentSerieName = item.fulltitle if item.fulltitle else item.title
            # Eredita thumbnail e fanart dalla serie
            new_item.thumbnail = item.thumbnail
            new_item.contentThumbnail = item.thumbnail
            new_item.fanart = item.fanart
            new_item.contentFanart = item.fanart
            new_item.imdb_id = imdb_id
            new_item.url = f"https://vixsrc.to/tv/{imdb_id}/{season}/{episode}?lang=it"
            itemlist.append(new_item)

    support.info(f'Generati {len(itemlist)} episodi (12x24)')

    # Stesso comportamento di StreamingCommunity:
    # 1) Arricchisci con TMDB (solo se abilitato nelle impostazioni)
    if config.get_setting('episode_info') and not support.stackCheck(['add_tvshow', 'get_newest']):
        support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # 2) Verifica Trakt
    support.check_trakt(itemlist)

    # 3) Abilita "Aggiungi alla videoteca"
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


def findvideos(item):
    """
    Server vixsrc.to
    """
    support.info('findvideos', item)

    urls = []

    if 'vixsrc.to' in item.url:
        urls.append(item.url)
        return support.server(item, urls)

    data = item.data if hasattr(item, 'data') and item.data else httptools.downloadpage(item.url).data

    imdb_id = None
    match = support.match(data, patron=r'<p id="imdb">(tt\d+)</p>').match
    if match:
        imdb_id = match
    if not imdb_id:
        match = support.match(data, patron=r"var imdb = '(tt\d+)'").match
        if match:
            imdb_id = match
    if not imdb_id:
        match = support.match(data, patron=r'itemprop="imdb"[^>]*content="(tt\d+)"').match
        if match:
            imdb_id = match

    if not imdb_id:
        support.info('IMDB ID non trovato!')
        return []

    support.info(f'IMDB ID trovato: {imdb_id}')

    if item.contentType == 'episode' or (hasattr(item, 'season') and item.season):
        season = getattr(item, 'season', 1) or 1
        episode = getattr(item, 'episode', 1) or 1
        url = f"https://vixsrc.to/tv/{imdb_id}/{season}/{episode}?lang=it"
    else:
        url = f"https://vixsrc.to/movie/{imdb_id}?lang=it"

    urls.append(url)
    support.info(f'URL generati: {urls}')
    return support.server(item, urls)