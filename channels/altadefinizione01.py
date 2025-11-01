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

    if item.text:  # ricerca
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
            r'style="background-image:url\((?P<thumb>[^\)]+).+?'
            r'<p class="h4">(?P<title>.*?)</p>[^>]+> [^>]+> [^>]+>'
            r'[^>]+>[^>]+>[^>]+>[^>]+>[^>]+> [^>]+> [^>]+>[^>]+>'
            r'(?P<year>\d{4})[^>]+>[^>]+> [^>]+>[^>]+>'
            r'(?P<duration>\d+|N/A)?.+?>.*?(?:>Film (?P<quality>Sub ITA)</a></p> )?'
            r'<p>(?P<plot>[^<]+)<.*?href="(?P<url>[^"]+)'
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

    else:  # lista normale
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

    #debug = True
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


@support.scrape
def episodios(item):
    patronBlock = r'<div class="tab-pane fade" id="season-(?P<season>\d+)"(?P<block>.*?)</ul>\s*</div>'
    patron = (
        r'(?P<data><a href="#" allowfullscreen data-link="[^"]+.*?'
        r'title="(?P<title>[^"]+)(?P<lang>[sS][uU][bB]-?[iI][tT][aA])?\s*">'
        r'(?P<episode>[^<]+).*?</li>)'
    )
    action = 'findvideos'

    def itemHook(item):
        item.contentType = 'episode'
        if item.episode:
            item.title = f"{item.title} - {item.episode}"
        return item

    return locals()


def check(item):
    support.info('CHECK chiamata per:', item)
    item.data = httptools.downloadpage(item.url).data
    # Controlla se ci sono stagioni nella pagina
    if 'tab-pane fade' in item.data and 'season-' in item.data:
        item.contentType = 'tvshow'
        support.info('Rilevata serie TV (trovate stagioni), chiamando episodios')
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
            if itemlist[-1].action == "peliculas":
                itemlist.pop()
    except:
        import sys
        for line in sys.exc_info():
            logger.error("{0}".format(line))
        return []
    return itemlist

def findvideos(item):
    support.info('findvideos', item)

    if item.contentType == 'episode':
        # Per gli episodi, usa i dati della pagina per trovare i link
        data = item.data if hasattr(item, 'data') else httptools.downloadpage(item.url).data
        urls = support.match(data, patron=r'data-link="([^"]+)').matches
        return support.server(item, urls)

    # Per i film
    data = httptools.downloadpage(item.url).data
    urls = []

    # Trova tutti gli iframe
    matches = support.match(data, patron=r'<iframe.*?src="([^"]+)').matches
    for m in matches:
        if 'youtube' not in m and not m.endswith('.js'):
            urls += support.match(m, patron=r'data-link="([^"]+)').matches

    urls += support.match(data, patron=r'id="urlEmbed" value="([^"]+)').matches
    return support.server(item, urls)
