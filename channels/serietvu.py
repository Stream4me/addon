# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per SerieTVU
# ----------------------------------------------------------
import re

from core import httptools, scrapertoolsV2, servertools, tmdb, scrapertools
from core.item import Item
from lib import unshortenit
from platformcode import logger, config
from channels import autoplay, support, filtertools
from channelselector import thumb

host = "https://www.serietvu.club/"
headers = [['Referer', host]]

IDIOMAS = {'Italiano': 'IT'}
list_language = IDIOMAS.values()
list_servers = ['speedvideo']
list_quality = ['default']



def mainlist(item):
    support.log(item.channel + 'mainlist')
    itemlist = []
    # support.menu(itemlist, "Cerca Film... color kod", 'search', '', 'movie')
    support.menu(itemlist, 'Novità color azure', 'latestep', "%s/ultimi-episodi" % host,'tvshow')
    support.menu(itemlist, 'Nuove serie color azure', 'lista_serie', "%s/category/serie-tv" % host,'tvshow')
    support.menu(itemlist, 'Categorie color azure', 'categorie', host,'tvshow')
    support.menu(itemlist, 'Cerca', 'search', host,'tvshow')

    # autoplay.init(item.channel, list_servers, list_quality)
    # autoplay.show_option(item.channel, itemlist)

    return itemlist


# ----------------------------------------------------------------------------------------------------------------
def cleantitle(scrapedtitle):
    scrapedtitle = scrapertools.decodeHtmlentities(scrapedtitle.strip())
    scrapedtitle = scrapedtitle.replace('[HD]', '').replace('’', '\'').replace('Game of Thrones –','')
    year = scrapertools.find_single_match(scrapedtitle, '\((\d{4})\)')
    if year:
        scrapedtitle = scrapedtitle.replace('(' + year + ')', '')


    return scrapedtitle.strip()


# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def lista_serie(item):
    support.log(item.channel + " lista_serie")
    itemlist = []

    data = httptools.downloadpage(item.url, headers=headers).data

    patron = r'<div class="item">\s*<a href="([^"]+)" data-original="([^"]+)" class="lazy inner">'
    patron += r'[^>]+>[^>]+>[^>]+>[^>]+>([^<]+)<'
    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedurl, scrapedimg, scrapedtitle in matches:
        infoLabels = {}
        year = scrapertools.find_single_match(scrapedtitle, '\((\d{4})\)')
        if year:
            infoLabels['year'] = year
        scrapedtitle = cleantitle(scrapedtitle)

        itemlist.append(
            Item(channel=item.channel,
                 action="episodios",
                 title=scrapedtitle,
                 fulltitle=scrapedtitle,
                 url=scrapedurl,
                 thumbnail=scrapedimg,
                 show=scrapedtitle,
                 infoLabels=infoLabels,
                 folder=True))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # Pagine
    support.nextPage(itemlist,item,data,'<a href="([^"]+)"[^>]+>Pagina')

    return itemlist

# ================================================================================================================


# ----------------------------------------------------------------------------------------------------------------
def episodios(item):
    support.log(item.channel + " episodios")
    itemlist = []

    data = httptools.downloadpage(item.url, headers=headers).data

    patron = r'<option value="(\d+)"[\sselected]*>.*?</option>'
    matches = re.compile(patron, re.DOTALL).findall(data)

    for value in matches:
        patron = r'<div class="list [active]*" data-id="%s">(.*?)</div>\s*</div>' % value
        blocco = scrapertools.find_single_match(data, patron)

        patron = r'(<a data-id="\d+[^"]*" data-href="([^"]+)" data-original="([^"]+)" class="[^"]+">)[^>]+>[^>]+>([^<]+)<'
        matches = re.compile(patron, re.DOTALL).findall(blocco)
        for scrapedextra, scrapedurl, scrapedimg, scrapedtitle in matches:
            number = scrapertools.decodeHtmlentities(scrapedtitle.replace("Episodio", "")).strip()
            itemlist.append(
                Item(channel=item.channel,
                     action="findvideos",
                     title=value + "x" + number.zfill(2),
                     fulltitle=scrapedtitle,
                     contentType="episode",
                     url=scrapedurl,
                     thumbnail=scrapedimg,
                     extra=scrapedextra,
                     folder=True))

    support.videolibrary(itemlist,item,'bold color kod')

    return itemlist

# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def findvideos(item):
    support.log(item.channel + " findvideos")

    itemlist = support.server(item, data=item.url)
    itemlist = filtertools.get_links(itemlist, item, list_language)

    autoplay.start(itemlist, item)

    return itemlist

# ================================================================================================================


# ----------------------------------------------------------------------------------------------------------------
def findepisodevideo(item):
    support.log(item.channel + " findepisodevideo")

    # Download Pagina
    data = httptools.downloadpage(item.url, headers=headers).data

    # Prendo il blocco specifico per la stagione richiesta
    patron = r'<div class="list [active]*" data-id="%s">(.*?)</div>\s*</div>' % item.extra[0][0]
    blocco = scrapertools.find_single_match(data, patron)

    # Estraggo l'episodio
    patron = r'<a data-id="%s[^"]*" data-href="([^"]+)" data-original="([^"]+)" class="[^"]+">' % item.extra[0][1].lstrip("0")
    matches = re.compile(patron, re.DOTALL).findall(blocco)

    itemlist = support.server(item, data=matches[0][0])
    itemlist = filtertools.get_links(itemlist, item, list_language)

    autoplay.start(itemlist, item)

    return itemlist


# ================================================================================================================


# ----------------------------------------------------------------------------------------------------------------
def latestep(item):
    support.log(item.channel + " latestep")
    itemlist = []

    data = httptools.downloadpage(item.url, headers=headers).data

    patron = r'<div class="item">\s*<a href="([^"]+)" data-original="([^"]+)" class="lazy inner">'
    patron += r'[^>]+>[^>]+>[^>]+>[^>]+>([^<]+)<small>([^<]+)<'
    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedurl, scrapedimg, scrapedtitle, scrapedinfo in matches:
        infoLabels = {}
        year = scrapertools.find_single_match(scrapedtitle, '\((\d{4})\)')
        if year:
            infoLabels['year'] = year
        scrapedtitle = cleantitle(scrapedtitle)

        infoLabels['tvshowtitle'] = scrapedtitle

        episodio = re.compile(r'(\d+)x(\d+)', re.DOTALL).findall(scrapedinfo)
        title = "%s %s" % (scrapedtitle, scrapedinfo)
        itemlist.append(
            Item(channel=item.channel,
                 action="findepisodevideo",
                 title=title,
                 fulltitle=scrapedtitle,
                 url=scrapedurl,
                 extra=episodio,
                 thumbnail=scrapedimg,
                 show=scrapedtitle,
                 contentTitle=scrapedtitle,
                 infoLabels=infoLabels,
                 folder=True))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    return itemlist


# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def newest(categoria):
    logger.info('serietvu' + " newest" + categoria)
    itemlist = []
    item = Item()
    try:
        if categoria == "series":
            item.url = host + "/ultimi-episodi"
            item.action = "latestep"
            itemlist = latestep(item)

            if itemlist[-1].action == "latestep":
                itemlist.pop()

    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("{0}".format(line))
        return []

    return itemlist


# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def search(item, texto):
    logger.info(item.channel + " search")
    item.url = host + "/?s=" + texto
    try:
        return lista_serie(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def categorie(item):
    logger.info(item.channel +" categorie")
    itemlist = []

    data = httptools.downloadpage(item.url, headers=headers).data
    blocco = scrapertools.find_single_match(data, r'<h2>Sfoglia</h2>\s*<ul>(.*?)</ul>\s*</section>')
    patron = r'<li><a href="([^"]+)">([^<]+)</a></li>'
    matches = re.compile(patron, re.DOTALL).findall(blocco)

    for scrapedurl, scrapedtitle in matches:
        if scrapedtitle == 'Home Page' or scrapedtitle == 'Calendario Aggiornamenti':
            continue
        itemlist.append(
            Item(channel=item.channel,
                 action="lista_serie",
                 title=scrapedtitle,
                 contentType="tv",
                 url="%s%s" % (host, scrapedurl),
                 thumbnail=item.thumbnail,
                 folder=True))

    return itemlist

# ================================================================================================================
