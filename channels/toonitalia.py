# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per ToonItalia
# ------------------------------------------------------------

import re
from core import scrapertools, support, httptools, servertools

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

    deflang = 'ITA' if 'sub' not in item.url else 'Sub-ITA'
    if item.args == 'list':
        pagination = 20
        patron = r'<li><a href="(?P<url>[^"]+)">(?P<title>[^<]+)'
    else:
        patronBlock = r'<main[^>]+>(?P<block>.*)</main>'
        patron = r'class="entry-title[^>]+><a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>.*?<p>(?P<plot>[^<]+)'
        patronNext = r'<a class="next page-numbers" href="([^"]+)">'

    def itemHook(item):
        support.info(item.title)
        if 'sub/ita' in item.cat.lower():
            item.title = item.title.replace('[ITA]', '[Sub-ITA]')
            item.contentLanguage = 'Sub-ITA'
        return item
    return locals()


def check(item):
    itemlist = episodios(item)
    if not itemlist:
        data = httptools.downloadpage(item.url, headers=headers, timeout=20).data
        if 'Link Streaming' in data:
            itemlist = findvideomovie(item, data)
        else:
            itemlist = findvideos(item)
    return itemlist


@support.scrape
def episodios(item):
    anime = True
    item.contentType = 'tvshow'
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
            item.title = re.sub(r'(\d+x\d+)[a-z]\b', r'\g<1>', item.title)
            item.title = re.sub(r'(\d+x)(\d+)', lambda m: '{}{:02d}'.format(m.group(1), index), item.title, count=1)
            renumbered_list.append(item)
    
    return renumbered_list


def findvideomovie(item, data):
    support.info("Detected movie page. Using findvideomovie logic.")
    itemlist = []
    
    for line in data.splitlines():
        if 'link streaming' in line.lower():
            support.info("Found 'Link Streaming' line: " + line.strip())
            patron_intermediate = r'<a[^>]+href="([^"]+)"'
            intermediate_links = scrapertools.find_multiple_matches(line, patron_intermediate)
            
            for link in intermediate_links:
                if not link.startswith(host):
                    try:
                        support.info("Testing streaming link: " + link)
                        response = httptools.downloadpage(link, allow_redirects=True, only_headers=True)
                        final_url = response.url
                        if final_url and final_url != link:
                            support.info("Redirect detected. Resolving: %s -> %s" % (link, final_url))
                            final_item = item.clone(url=final_url)
                            final_item.referer = link
                            all_video_items = support.server(final_item)
                            valid_video_items = [video for video in all_video_items if not (video.server == 'voe' and ('api2' in video.url or 'session' in video.url))]
                            if valid_video_items:
                                itemlist.extend(valid_video_items)
                    except Exception as e:
                        support.logger.error("Failed to process movie link %s: %s" % (link, e))
            break
            
    return itemlist


def findvideos(item):
    patron_intermediate = r'(https?://[^\s"\'<>]+)'
    intermediate_links = scrapertools.find_multiple_matches(item.data, patron_intermediate)
    
    for link in intermediate_links:
        if not link.startswith(host):
            try:
                support.info("Testing external link: " + link)
                response = httptools.downloadpage(link, allow_redirects=True, only_headers=True)
                final_url = response.url
                
                if final_url and final_url != link:
                    support.info("Redirect detected. Resolving: %s -> %s" % (link, final_url))
                    final_item = item.clone(url=final_url)
                    final_item.referer = link
                    all_video_items = support.server(final_item)
                    valid_video_items = [video for video in all_video_items if video.server == 'voe' and 'api2' not in video.url and 'session' not in video.url]
                    return valid_video_items

            except Exception as e:
                support.logger.error("Failed to process link %s: %s" % (link, e))

    support.info("No redirects were processed, falling back to default support.server")
    return support.server(item, data=item.data)


def clean_title(title):
    title = scrapertools.unescape(title)
    title = title.replace('_',' ').replace('–','-').replace('  ',' ')
    title = title.strip(' - ')
    return title
