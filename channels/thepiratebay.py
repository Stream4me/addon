# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per The Pirate Bay
# ------------------------------------------------------------

import json
import urllib.parse

from core import support, httptools
from platformcode import logger

host = ''


@support.menu
def mainlist(item):

    search = ''
    return locals()


def search(item, text):
    logger.info("text=" + text)
    itemlist = []
    
    api_url = "https://apibay.org/q.php?q=%s" % urllib.parse.quote(text)
    
    data = httptools.downloadpage(api_url).data
    
    if not data:
        return itemlist
    
    torrents = json.loads(data)
    
    for torrent in torrents:
        title = torrent['name']
        info_hash = torrent['info_hash']
        seeds = torrent['seeders']
        leech = torrent['leechers']
        size_bytes = int(torrent['size'])
        
        magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, urllib.parse.quote(title))
        
        size = format_size(size_bytes)
        
        title_formatted = "%s [S:%s L:%s] [%s]" % (title, seeds, leech, size)
        
        new_item = item.clone(
            title=title_formatted,
            url=magnet,
            action="findvideos",
            server="torrent"
        )
        
        itemlist.append(new_item)
    
    return itemlist


def format_size(size_bytes):
    size = float(size_bytes)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return "%.1f %s" % (size, units[unit_index])


def findvideos(item):
    return support.server(item, item.url)