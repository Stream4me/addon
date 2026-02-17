# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per ToonItalia
# ------------------------------------------------------------

from core import scrapertools, support

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
    # Continua la ricerca in caso di errore
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
        itemlist = findvideos(item)
    return itemlist


@support.scrape
def episodios(item):
    anime = True
    item.contentType = 'tvshow'
    patron = r'>\s*(?:(?P<season>\d+)(?:&#215;|x|×))?(?P<episode>\d+)-*\d*(?:\s+&#8211;\s+)?[ –]+(?P<title>[^<]+)[ –]+<a (?P<data>.*?)(?:<br|</p)'
    
    return locals()


def findvideos(item):
    return support.server(item, data=item.data)


def clean_title(title):
    title = scrapertools.unescape(title)
    title = title.replace('_',' ').replace('–','-').replace('  ',' ')
    title = title.strip(' - ')
    return title
