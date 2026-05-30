# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per streamingITA
# ------------------------------------------------------------

from core import httptools, support
from platformcode import logger, config

host = config.get_channel_url()
headers = [['Referer', host]]


@support.menu
def mainlist(item):
    film = ['/film']
    top = [('Generi', ['/film', 'menu', 'genres']),
            ('Anno', ['/film', 'menu', 'releases'])]
    tvshow = ['/tv']
    search = ''
    return locals()


def search(item, text):
    logger.info('search', text)
    item.url = item.url + "/?s=" + text
    try:
        return support.dooplay_search(item)
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


def peliculas(item):
    mixed = True if item.contentType == 'undefined' else False
    return support.dooplay_peliculas(item, mixed)


def episodios(item):
    itemlist = support.dooplay_get_episodes(item)
    return itemlist


def findvideos(item):
    data = []
    for link in support.dooplay_get_links(item, host):
        url = httptools.downloadpage(link['url'], only_headers=True, headers=headers).url
        if url:
            data.append(url)
    return support.server(item, data)


@support.scrape
def menu(item):
    action = 'peliculas'
    item.contentType = 'undefined'
    if item.args in ['genres', 'releases']:
        patronBlock = r'<nav class="' + item.args + r'">(?P<block>.*?)</nav'
        patronMenu = r'<a href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)<'
    else:
        patronBlock = r'class="main-header">(?P<block>.*?)headitems'
        patronMenu = r'(?P<url>' + host + r'quality/[^/]+/\?post_type=movies)">(?P<title>[^<]+)'
    return locals()