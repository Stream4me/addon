# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per guardaserieclick
# ------------------------------------------------------------

from core import support
from core.item import Item
from platformcode import logger, config
from core.support import info

host = config.get_channel_url()
headers = [['Referer', host]]

@support.menu
def mainlist(item):
    tvshow = ['',
              ('Aggiornamenti', ['/aggiornamento-serietv/', 'updates', '']),
              ('Serie TV', ['/serie-tv-archive/', 'peliculas', '']),
              ('Animazione', ['/animazione/', 'peliculas', '']),
              ('Generi', ['', 'genres', 'genres'])
              ]

    return locals()

@support.scrape
def peliculas(item):
    action = 'episodios'
    patronBlock = r'<div class="recent-posts">(?P<block>.*?)<div id="sidebar">'
    patron = r'post-thumb.*?href="(?P<url>[^"]+).*?title="(?P<title>.*?)streaming.*?src="(?P<thumb>[^"]+)'
    patronNext = r'"next".*?"([^"]+)'
    item.contentType = 'tvshow'
    return locals()

@support.scrape
def episodios(item):
    action = 'findvideos'
    patronBlock = r'<div class="tab-pane fade" id="season-(?P<season>.)"(?P<block>.*?)</ul>\s*</div>'
    patron = r'<a href="#" allowfullscreen data-link="(?P<url>[^"]+).*?title="(?P<title>[^"]+)(?P<lang>[sS][uU][bB]-?[iI][tT][aA])?\s*">(?P<episode>[^<]+)'
    return locals()

@support.scrape
def genres(item):
    action = 'peliculas'
    data = support.match(item, patron=r'<ul class="sub-menu">(.*?)</ul>').match
    patron = r'<li><a href="(?P<url>[^"]+)">(?P<title>[^<]+)'
    return locals()

@support.scrape
def updates(item):
    action = 'episodios'
    patron = r'serieTitle.*?[^>]+>(?P<title>.*?)\s.\s<.*?="(?P<url>[^"]+)">(?P<season>[0-9]{1,2})x(?P<episode>[0-9]{1,2})'
    item.contentType = 'tvshow'
    return locals()

def search(item, text):
    support.info(item, text)
 
    itemlist = []
    text = text.replace(" ", "+")
    item.url = host + "/index.php?do=search&story=%s&subaction=search" % (text)
    item.args = "search"
    try:
        return peliculas(item)
    # Cattura la eccezione così non interrompe la ricerca globle se il canale si rompe!
    except:
        import sys
        for line in sys.exc_info():
            logger.error("search except: %s" % line)
        return []

def findvideos(item):
    logger.debug()
    return support.server(item, item.url)