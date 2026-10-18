# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Sky Video
# ------------------------------------------------------------

import requests
from core import support, httptools
from platformcode import logger

host = 'https://video.sky.it'
api_url = 'https://video.sky.it/api/v1'

@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live'])]

    search = ''
    return locals()

def live(item):
    itemlist = [item.clone(title=support.typo('TV8', 'bold'), fulltitle='TV8', url= api_url + '/getLivestream?id=7', action='findvideos', forcethumb = True, no_return=True),
                item.clone(title=support.typo('Cielo', 'bold'), fulltitle='Cielo', url= api_url + '/getLivestream?id=2', action='findvideos', forcethumb = True, no_return=True),
		item.clone(title=support.typo('Sky TG24', 'bold'), fulltitle='Sky TG24', url= api_url + '/getLivestream?id=1', action='findvideos', forcethumb = True, no_return=True)]

    return support.thumb(itemlist, live=True)

def findvideos(item):
    json = httptools.downloadpage(item.url).json

    item = item.clone(server='directo', url=json['streaming_url'], action='play', manifest='hls')
    return support.server(item, itemlist=[item], Download=False, Videolibrary=False)
