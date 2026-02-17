# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per ilgeniodellostreaming_cam
# ------------------------------------------------------------


from core import support, httptools
from core.support import info
from core.item import Item
from platformcode import config, logger

host = config.get_channel_url()
headers = [['Referer', host]]

@support.menu
def mainlist(item):
    menu = [('Tutti',['/catalog/all', 'peliculas', 'template-az', 'undefined']),
            ('Generi {submenu}',['', 'genres', 'genres', 'undefined']),
            ('Per Lettera {submenu}',['/catalog/all', 'genres', 'template-az', 'undefined']),
            ('Anni {submenu}',['', 'genres', 'year', 'undefined']),
            ('Serie Tv',['/serie-tv/', 'peliculas', '', 'tvshow']),
    ]

    search = ''
    return locals()

@support.scrape
def peliculas(item):
    if item.text:
        data = support.httptools.downloadpage(host + '/?s=' + item.text, post={'story': item.text, 'do': 'search', 'subaction': 'search'}).data
        patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<rating>[^<]+)[^>]+>[^>]+>((?P<quality>[^<]+)[^>]+>[^>]+>)?[^>]+>[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)[^>]+>[^>]+>[^>]+>.*?[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<plot>[^<]+)<[^>]+>'
    else:
        if item.args == 'template-az':
            patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+><a href="(?P<url>[^"]+)[^>]+>(?P<title>[^<]+)<[^>]+>[^>]+>[^>]+>(?P<year>[0-9]{4}).*?<[^>]+>[^>]+>(?P<categories>.*?)</td>.*?<span class="labelimdb">(?P<rating>[^>]+)<'
        else:
            patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<rating>[^<]+)[^>]+>[^>]+>(?P<quality>[^<]+)[^>]+>[^>]+>[^>]+>[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)[^>]+>[^>]+>[^>]+>(?P<year>\d{4})[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<plot>[^<]+)<[^>]+>'

        patronNext = 'href="([^>]+)">»'

    # imposto come azione il controllo del tipo di contenuto
    action = 'check'

    return locals()

# metodo di comodo per controllare se si è selezionato un film o serie tv
def check(item):
    item.data = httptools.downloadpage(item.url).data
    if 'stagione' in item.data.lower():
        item.contentType = 'tvshow'
        return episodios(item)
    else:
        return findvideos(item)

@support.scrape
def genres(item):
    action='peliculas'
    if item.args == 'genres':
        patronBlock = r'<div class="sidemenu">\s*<h2>Genere</h2>(?P<block>.*?)</ul'
    elif item.args == 'year':
        item.args = 'genres'
        patronBlock = r'<div class="sidemenu">\s*<h2>Anno di uscita</h2>(?P<block>.*?)</ul'
    elif item.args == 'template-az':
        patronBlock = r'<div class="movies-letter">(?P<block>.*?)<div class="clearfix">'

    patronMenu = r'<a(?:.+?)?href="(?P<url>.*?)"[ ]?>(?P<title>.*?)<\/a>'

    return locals()

def search(item, text):
    info(text)
    item.text = text
    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            info("%s" % line)

    return []
    
@support.scrape
def episodios(item):
    patronBlock = r'<div class="tab-pane fade" id="season-(?P<season>\d+)"(?P<block>.*?)</ul>\s*</div>'
    patron = r'(?P<data><a.*?data-num="(?P<season>.*?)x(?P<episode>.*?)".*?data-title="(?P<title>.+?)(?:: (?P<plot>.*?))?">.*?</li>)'
    action = 'findvideos'
    return locals()

def newest(categoria):
    info(categoria)
    itemlist = []
    item = Item()

    if categoria == 'peliculas':
        item.contentType = 'undefined'
        item.url = host + '/film/'
    try:
        item.action = 'peliculas'
        itemlist = peliculas(item)

    except:
        import sys
        for line in sys.exc_info():
            info("{0}".format(line))
        return []

    return itemlist
    
def findvideos(item):
    info()
    
    # sto cercando di avviare un episodio di una serie tv
    if item.contentType == 'episode': 
        return support.server(item, item.data)

    # sto cercando di avviare un film
    urls = []
    data = support.match(item).data

    urls += support.match(data, patron=r'id="urlEmbed" value="([^"]+)').matches
    matches = support.match(data, patron=r'<iframe.*?src="([^"]+)').matches
    for m in matches:
        if 'youtube' not in m and not m.endswith('.js'):
            urls += support.match(m, patron=r'data-link="([^"]+)').matches
    return support.server(item, urls)
