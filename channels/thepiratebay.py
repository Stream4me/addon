# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per The Pirate Bay
# ------------------------------------------------------------

import json
import urllib.parse
import re

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
    
    page = int(item.page) if hasattr(item, 'page') and item.page else 0
    
    # Usa l'API di The Pirate Bay
    if page > 0:
        api_url = "https://apibay.org/q.php?q=%s&page=%s" % (urllib.parse.quote(text), page)
    else:
        api_url = "https://apibay.org/q.php?q=%s" % urllib.parse.quote(text)
    
    logger.info("API URL: %s" % api_url)
    
    data = httptools.downloadpage(api_url).data
    
    if not data:
        logger.error("Nessun dato ricevuto dall'API")
        return itemlist
    
    try:
        torrents = json.loads(data)
        logger.info("Torrents trovati: %s" % len(torrents))
    except Exception as e:
        logger.error("Errore nel parsing del JSON: %s" % str(e))
        return itemlist
    
    if not isinstance(torrents, list):
        logger.error("Risposta API non valida")
        return itemlist
    
    for torrent in torrents:
        if not torrent.get('name'):
            continue
            
        title = torrent['name']
        info_hash = torrent.get('info_hash', '')
        seeds = int(torrent.get('seeders', 0))
        leech = int(torrent.get('leechers', 0))
        size_bytes = int(torrent.get('size', 0))
        
        magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, urllib.parse.quote(title))
        size = format_size(size_bytes)
        
        # Colore seeders
        if seeds >= 100:
            seed_color = '[COLOR green]%s[/COLOR]' % seeds
        elif seeds >= 50:
            seed_color = '[COLOR yellow]%s[/COLOR]' % seeds
        elif seeds >= 10:
            seed_color = '[COLOR orange]%s[/COLOR]' % seeds
        else:
            seed_color = '[COLOR red]%s[/COLOR]' % seeds
        
        title_formatted = "%s [S:%s L:%s] [%s]" % (title, seed_color, leech, size)
        
        new_item = item.clone(
            title=title_formatted,
            url=magnet,
            action="findvideos",
            server="torrent",
            folder=False,
            contentTitle=title,
            info_hash=info_hash,
            seeders=seeds,
            leechers=leech,
            size=size
        )
        
        itemlist.append(new_item)
    
    # Ordina per seeders
    itemlist.sort(key=lambda x: int(x.seeders) if hasattr(x, 'seeders') else 0, reverse=True)
    
    # Paginazione S4Me con support.nextPage
    if len(itemlist) > 0:
        next_page = page + 1
        next_url = "https://apibay.org/q.php?q=%s&page=%s" % (urllib.parse.quote(text), next_page)
        support.nextPage(itemlist, item, next_page=next_url, function_or_level='search')
    
    return itemlist


def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    
    size = float(size_bytes)
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return "%.1f %s" % (size, units[unit_index])


def findvideos(item):
    if hasattr(item, 'info_hash'):
        logger.info("Riproduzione torrent: %s" % item.info_hash)
    
    return support.server(item, item.url)