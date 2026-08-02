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
    support.info(item)

    search = ''
    return locals()


def search(item, text):
    support.info('search', text)
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
        imdb = torrent.get('imdb', '')
        
        magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, urllib.parse.quote(title))
        
        size = format_size(size_bytes)
        
        title_formatted = "%s [S:%s L:%s] [%s]" % (title, seeds, leech, size)
        
        clean_title, content_type, season, episode = parse_title(title)
        
        info_labels = {
            'title': clean_title,
            'tvshowtitle': clean_title,
            'size': size
        }
        
        if imdb:
            info_labels['imdbnumber'] = imdb
        
        if season is not None:
            info_labels['season'] = season
        if episode is not None:
            info_labels['episode'] = episode
        
        new_item = item.clone(
            title=title_formatted,
            fulltitle=clean_title,
            url=magnet,
            action="play",
            server="torrent",
            infoLabels=info_labels,
            contentType=content_type
        )
        
        itemlist.append(new_item)
    
    return itemlist


def parse_title(title):
    title = title.strip()
    
    season = None
    episode = None
    
    match = re.search(r'[Ss](\d+)[Ee](\d+)', title)
    if not match:
        match = re.search(r'(\d+)x(\d+)', title)
    
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        content_type = 'tvshow'
    elif any(x in title.lower() for x in ['stagione', 'season', 'complete serie']):
        content_type = 'tvshow'
    else:
        content_type = 'movie'
    
    clean_title = re.sub(r'\s*[\[\(]?\d{4}[\]\)]?\s*', '', title)
    clean_title = re.sub(r'\s*\d{3,4}p\s*', '', clean_title)
    clean_title = re.sub(r'\s*[Ss]\d+[Ee]\d+\s*', '', clean_title)
    clean_title = re.sub(r'\s*\d+x\d+\s*', '', clean_title)
    clean_title = re.sub(r'\s*(?:ITA|ENG|SUB|AC3|HEVC|H265|H264|XviD|BRRip|BluRay|WEBRip|DVDrip|MULTI)\s*', ' ', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    
    return clean_title, content_type, season, episode


def format_size(size_bytes):
    size = float(size_bytes)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return "%.1f %s" % (size, units[unit_index])


def play(item):
    support.info('play ->', item)
    return [item.clone(server="torrent", url=item.url)]


def findvideos(item):
    support.info('findvideos ->', item)
    return support.server(item, item.url)