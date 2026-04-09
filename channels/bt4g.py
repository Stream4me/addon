# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per bt4g
# ------------------------------------------------------------

from core import support, httptools

host = support.config.get_channel_url()
headers = [['Referer', host]]

@support.menu
def mainlist(item):

    search = ''
    return locals()

@support.scrape
def peliculas(item):
    debug = False
    action = 'findvideos'
    sceneTitle = True

    def itemHook(item):
        item.title = support.scrapertools.decodeHtmlentities(support.urlparse.unquote(item.title))

        return item

    if not item.nextpage:
        item.page = 1
    else:
        item.page = item.nextpage

    if not item.parent_url:
        item.parent_url = item.url

    item.nextpage = item.page + 1
    nextPageUrl = "{}/search?{}".format(host, support.urlencode({'q': item.args,'category': 'movie', 'page': 'rss', 'orderby' : 'seeders', 'p' : item.nextpage}))
    resp = httptools.downloadpage(nextPageUrl)
    if ('item' not in resp.data.lower()): # no more elements
        nextPageUrl = ''

    patron = r'<item>.*?<title>(?P<title>.*?)</title><link>(?P<url>.*?)</link>'
    return locals()

def search(item, text):
    item.url = "{}/search?{}".format(host, support.urlencode({'q': text,'category': 'movie', 'page': 'rss', 'orderby' : 'seeders'}))
    item.args = text

    try:
        return peliculas(item)

    except:
        import sys
        for line in sys.exc_info():
            logger.error("search except: %s" % line)
        return []

def findvideos(item):
    return support.server(item, item.url)
