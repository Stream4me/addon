# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per ilgeniodellostreaming_cam
# ------------------------------------------------------------


from core import support
from core.support import info
from core.item import Item
from platformcode import config

host = config.get_channel_url()
headers = [['Referer', host]]

@support.menu
def mainlist(item):
    film = ['/film/',
           ('In Sala', ['', 'peliculas', 'sala']),
           ('Generi',['', 'genres', 'genres']),
           ('Per Lettera',['/catalog/all', 'genres', 'az']),
           ('Anni',['', 'genres', 'year'])]

    return locals()


@support.scrape
def peliculas(item):
    if item.text:
        data = support.httptools.downloadpage(host + '/?s=' + item.text, post={'story': item.text, 'do': 'search', 'subaction': 'search'}).data
        patron = '<img src="(?P<thumb>[^"]+)(?:[^>]+>){8}\s*<a href="(?P<url>[^"]+)[^>]+>(?P<title>[^<]+)(?:[^>]+>){4}IMDb\s(?P<rating>[^<]+)(?:[^>]+>){2}(?P<year>\d+)'
    else:
        if item.args == 'sala':
            patronBlock = r'insala(?P<block>.*?)<header>'
            patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<rating>[^<]+)[^>]+>[^>]+>(?P<quality>[^<]+)[^>]+>[^>]+>[^>]+>[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)[^>]+>[^>]+>[^>]+>(?P<year>\d{4})'
        elif item.args == 'az':
            patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+><a href="(?P<url>[^"]+)[^>]+>(?P<title>[^<]+)<[^>]+>[^>]+>[^>]+>.*?<span class="labelimdb">(?P<rating>[^>]+)<'
        else:
            patron = r'<img src="(?P<thumb>[^"]+)[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<rating>[^<]+)[^>]+>[^>]+>(?P<quality>[^<]+)[^>]+>[^>]+>[^>]+>[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)[^>]+>[^>]+>[^>]+>(?P<year>\d{4})[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*(?P<plot>[^<]+)<[^>]+>'

        patronNext = 'href="([^>]+)">»'

    return locals()


@support.scrape
def genres(item):
    action='peliculas'
    if item.args == 'genres':
        patronBlock = r'<div class="sidemenu">\s*<h2>Genere</h2>(?P<block>.*?)</ul'
    elif item.args == 'year':
        item.args = 'genres'
        patronBlock = r'<div class="sidemenu">\s*<h2>Anno di uscita</h2>(?P<block>.*?)</ul'
    elif item.args == 'az':
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

def newest(categoria):
    info(categoria)
    itemlist = []
    item = Item()

    if categoria == 'peliculas':
        item.contentType = 'movie'
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
    urls = []
    data = support.match(item).data
    urls += support.match(data, patron=r'id="urlEmbed" value="([^"]+)').matches
    matches = support.match(data, patron=r'<iframe.*?src="([^"]+)').matches
    for m in matches:
        if 'youtube' not in m and not m.endswith('.js'):
            urls += support.match(m, patron=r'data-link="([^"]+)').matches
    return support.server(item, urls)