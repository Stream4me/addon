# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per ToonItalia
# ------------------------------------------------------------

import re
from core import scrapertools, support, httptools
host = support.config.get_channel_url()
headers = [['Referer', host]]

@support.menu
def mainlist(item):
    menu = [('Anime',['/category/anime', 'peliculas', '', 'undefined']),
            ('Anime ITA {submenu}',['/anime-ita', 'peliculas', 'list', 'undefined']),
            ('Anime Sub-ITA {submenu}',['/contatti', 'peliculas', 'list', 'undefined']),
            ('Film Animazione',['/film-animazione', 'peliculas', 'list', 'undefined']),
            ('Serie TV',['/serie-tv/', 'peliculas', 'list', 'tvshow'])]
    search = ''
    return locals()

def search(item, text):
    item.contentType = 'undefined'
    item.url = "{}/?{}".format(host, support.urlencode({"s": text}))
    support.info(item.url)
    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)
        return []

@support.scrape
def peliculas(item):
    anime = True
    action = 'check'
    deflang = 'ITA' if ('sub' not in item.url and 'contatti' not in item.url) else 'Sub-ITA'
    if item.args == 'list':
        pagination = 20
        patron = r'<li><a href="(?P<url>[^"]+)">(?P<title>[^<]+)'
    else:
        patronBlock = r'<main[^>]+>(?P<block>.*)</main>'
        patron = r'<div class="entry-categories">(?P<categories>.*?)<!-- \.entry-categories -->.*?class="entry-title[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>.*?<p>(?P<plot>[^<]+)'
        patronNext = r'<a class="next page-numbers" href="([^"]+)">'
    
    def itemHook(item):
        support.info(item.title)
        if 'sub-ita' in item.categories.lower():
            item.title = item.title.replace('[ITA]', '[Sub-ITA]')
            item.contentLanguage = 'Sub-ITA'
        return item
    return locals()

def check(item):
    itemlist = episodios(item)
    if not itemlist:
        itemlist = findvideos(item)
    return itemlist

@support.scrape
def episodios(item):
    anime = True
    item.contentType = 'tvshow'
    html = httptools.downloadpage(item.url, headers=headers, ignore_response_code=True).data
    start_index = html.find("Trama:")
    data = html[start_index:].strip() if start_index > -1 else html
    patron = r'>\s*(?:(?P<season>\d+)(?:&#215;|x|×))?(?P<episode>\d+)(?P<letter>[a-z])?-*\d*(?:\s+&#8211;\s+)?[ –]+(?P<title>[^<]+)[ –]+<a (?P<data>.*?)(?:<br|</p)'
    
    def itemlistHook(itemlist):
        return renumber_episodes(itemlist)
    
    return locals()

def renumber_episodes(itemlist):
    seasons = {}
    for item in itemlist:
        season = item.contentSeason if hasattr(item, 'contentSeason') else 1
        if season not in seasons:
            seasons[season] = []
        seasons[season].append(item)
    
    renumbered_list = []
    for season_num in sorted(seasons.keys()):
        for index, item in enumerate(seasons[season_num], start=1):
            item.contentEpisodeNumber = index
            # Rimuove la lettera dal titolo (1x01a -> 1x01)
            item.title = re.sub(r'(\d+x\d+)[a-z]\b', r'\g<1>', item.title)
            # Rinumera l'episodio (corretto senza doppia 'x')
            item.title = re.sub(r'(\d+)x(\d+)', lambda m: '{}x{:02d}'.format(m.group(1), index), item.title, count=1)
            renumbered_list.append(item)
    
    return renumbered_list

def findvideos(item):
    return support.server(item, data=item.data)
