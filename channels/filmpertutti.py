# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per filmpertutti.py
# ------------------------------------------------------------

from core import httptools, support, scrapertools
from core.item import Item
from platformcode import config, logger

def findhost(url):
    try:
        page = httptools.downloadpage(url).data
        new_url = scrapertools.find_single_match(page, r'Il nuovo indirizzo di FILMPERTUTTI è ?\<a href="([^"]+)')
        if new_url:
            return new_url
    except:
        pass
    return url

host = config.get_channel_url(findhost)
headers = [['Referer', host]]


@support.menu
def mainlist(item):
    film = ['/film/',
            ('Al Cinema', ['/cinema/', 'peliculas']),
            ('Generi', ['', 'genres', 'film']),
           ]

    tvshow = ['/serie-tv/',
             ]

    search = ''
    return locals()


@support.scrape
def peliculas(item):
    import re as regex_module
    action = 'check'
    
    patron = r'<div class="posts"[^>]*>\s*<a href="(?P<url>[^"]+)"[^>]*>\s*'
    patron += r'<div[^>]*style="[^"]*background-image:\s*url\((?P<thumb>[^\)]+)\)[^"]*"[^>]*>.*?'
    patron += r'<div class="title">(?P<title>[^\[(<]+?)(?:\s*\[(?P<quality>[^\]]+)\])?\s*(?:\((?P<year>\d{4})[^\)]*\))?\s*</div>'
    
    patronNext = r'<a href="([^"]+)">Pagina successiva'
    
    def defPreprocess(data):
        data = regex_module.sub(r'\[episode-num\].*?\[/episode-num\]', '', data)
        data = regex_module.sub(r'\[season-num\].*?\[/season-num\]', '', data)
        data = regex_module.sub(r'\{season-num\}', '', data)
        data = regex_module.sub(r'\{episode-num\}', '', data)
        return data
    
    def itemHook(item):
        if item.thumbnail and not item.thumbnail.startswith('http'):
            item.thumbnail = host + item.thumbnail
        return item
    
    return locals()


def genres(item):
    support.info('genres', item)
    itemlist = []
    
    data = httptools.downloadpage(host, headers=headers).data
    
    patron = r'<ul[^>]*class="table-list"[^>]*>(.*?)</ul>'
    block = scrapertools.find_single_match(data, patron)
    
    if block:
        genre_pattern = r'<li>\s*<a href="([^"]+)"[^>]*>\s*(?:<span[^>]*></span>)?\s*([^<]+)</a>'
        matches = scrapertools.find_multiple_matches(block, genre_pattern)
        
        for url, title in matches:
            title = title.strip()
            if title and '/generi/' not in url and title.lower() not in ['serie tv', 'film', 'home']:
                itemlist.append(item.clone(
                    action='peliculas',
                    title=support.cleantitle(title),
                    url=url if url.startswith('http') else host + url
                ))
    
    return itemlist


def check(item):
    support.info('check', item)
    item.data = httptools.downloadpage(item.url, headers=headers).data
    
    if 'single-season' in item.data or 'stagione' in item.data.lower() or 'season_' in item.data.lower():
        item.contentType = 'tvshow'
        return episodios(item)
    else:
        item.contentType = 'movie'
        return findvideos(item)


def episodios(item):
    support.info('episodios', item)
    item.quality = ''
    data = item.data if item.data else httptools.downloadpage(item.url, headers=headers).data
    itemlist = []

    season_tabs = scrapertools.find_multiple_matches(data, r'<a[^>]*href="#(season-\d+)"[^>]*data-toggle="tab"[^>]*>(\d+)</a>')
    
    if not season_tabs:
        season_tabs = scrapertools.find_multiple_matches(data, r'id="(season-(\d+))"[^>]*class="[^"]*tab-pane')
    
    for season_id, season_num in season_tabs:
        season_pattern = r'id="' + season_id + r'"[^>]*>\s*<ul[^>]*>(.*?)</ul>\s*</div>'
        season_block = scrapertools.find_single_match(data, season_pattern)
        
        if not season_block:
            season_pattern = r'id="' + season_id + r'"[^>]*>(.*?)</div>\s*(?:<div class="tab-pane|</div>\s*</div>)'
            season_block = scrapertools.find_single_match(data, season_pattern)
        
        if season_block:
            episode_pattern = r'<li[^>]*>.*?data-num="(\d+)x(\d+)"[^>]*>(\d+)</a>.*?</li>'
            episodes = scrapertools.find_multiple_matches(season_block, episode_pattern)
            
            for ep_season, ep_num, ep_display in episodes:
                mirror_pattern = r'data-num="' + ep_season + 'x' + ep_num + r'".*?<div class="mirrors">(.*?)</div>'
                mirrors_block = scrapertools.find_single_match(season_block, mirror_pattern)
                
                if mirrors_block:
                    link_pattern = r'data-link="([^"]+)"'
                    links = scrapertools.find_multiple_matches(mirrors_block, link_pattern)
                    
                    if links:
                        itemlist.append(item.clone(
                            contentType='episode',
                            action='findvideos', 
                            episode=ep_num,
                            season=ep_season,
                            contentSeason=int(ep_season),
                            contentEpisodeNumber=int(ep_num),
                            title=support.format_longtitle('Episodio ' + ep_num, season=ep_season, episode=ep_num),
                            url=item.url,
                            other='\n'.join(links),
                            data=''
                        ))

    if not itemlist:
        return findvideos(item)

    if config.get_setting('episode_info') and not support.stackCheck(['add_tvshow', 'get_newest']):
        support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    support.check_trakt(itemlist)
    support.videolibrary(itemlist, item)
    if config.get_setting('downloadenabled'):
        support.download(itemlist, item)

    return itemlist


def search(item, text):
    support.info('search', item, text)
    
    search_url = "{}/?story={}&do=search&subaction=search".format(host, text.replace(' ', '+'))
    item.url = search_url
    item.args = 'search'

    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            logger.error("search except: %s" % line)
        return []


def newest(categoria):
    support.info('newest', categoria)
    itemlist = []
    item = Item()
    
    try:
        if categoria == "peliculas":
            item.url = host + "/film/"
            item.action = "peliculas"
            item.extra = "movie"
            item.contentType = 'movie'
            itemlist = peliculas(item)
        else:
            item.url = host + "/serie-tv/"
            item.action = "peliculas"
            item.contentType = 'tvshow'
            itemlist = peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            support.info("{0}".format(line))
        return []

    return itemlist


def findvideos(item):
    logger.debug()
    
    if item.other:
        return support.server(item, data=item.other)
    
    data = item.data if item.data else httptools.downloadpage(item.url, headers=headers).data
    
    imdb_id = scrapertools.find_single_match(data, r'imdb\.com/title/(tt\d+)')
    if imdb_id:
        data += httptools.downloadpage("https://guardahd.stream/ldl/" + imdb_id, headers=headers).data
    
    return support.server(item, data=data)




