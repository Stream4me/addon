# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per SerieTVU
# Thanks to Icarus crew & Alfa addon
# ----------------------------------------------------------
import re

import channelselector
from core import httptools, tmdb, scrapertools, support
from core.item import Item
from platformcode import logger, config
from specials import autoplay

__channel__ = 'serietvu'
host = config.get_setting("channel_host", __channel__)
headers = [['Referer', host]]

IDIOMAS = {'Italiano': 'IT'}
list_language = IDIOMAS.values()
list_servers = ['speedvideo']
list_quality = ['default']

# checklinks = config.get_setting('checklinks', __channel__)
# checklinks_number = config.get_setting('checklinks_number', __channel__)



def mainlist(item):
    support.log(item.channel + 'mainlist')
    itemlist = []
    support.menu(itemlist, 'Serie TV bold', 'lista_serie', "%s/category/serie-tv" % host,'tvshow')
    support.menu(itemlist, 'Novità submenu', 'latestep', "%s/ultimi-episodi" % host,'tvshow')
    # support.menu(itemlist, 'Nuove serie color azure', 'lista_serie', "%s/category/serie-tv" % host,'tvshow')
    support.menu(itemlist, 'Categorie', 'categorie', host,'tvshow')
    support.menu(itemlist, 'Cerca', 'search', host,'tvshow')

    autoplay.init(item.channel, list_servers, list_quality)
    autoplay.show_option(item.channel, itemlist)

    itemlist.append(
        Item(channel='setting',
             action="channel_config",
             title=support.typo("Configurazione Canale color lime"),
             config=item.channel,
             folder=False,
             thumbnail=channelselector.get_thumb('setting_0.png'))
    )

    return itemlist


# ----------------------------------------------------------------------------------------------------------------
def cleantitle(scrapedtitle):
    scrapedtitle = scrapertools.decodeHtmlentities(scrapedtitle.strip())
    scrapedtitle = scrapedtitle.replace('[HD]', '').replace('’', '\'').replace('– Il Trono di Spade','').replace('Flash 2014','Flash')
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
                 contentType='episode',
                 folder=True))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # Pagine
    support.nextPage(itemlist,item,data,'<li><a href="([^"]+)">Pagina successiva')

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

            title = value + "x" + number.zfill(2)


            itemlist.append(
                Item(channel=item.channel,
                     action="findvideos",
                     title=title,
                     fulltitle=scrapedtitle,
                     contentType="episode",
                     url=scrapedurl,
                     thumbnail=scrapedimg,
                     extra=scrapedextra,
                     folder=True))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    support.videolibrary(itemlist,item,'bold color kod')

    return itemlist

# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def findvideos(item):
    support.log(item.channel + " findvideos")

    itemlist = support.server(item, data=item.url)

    # itemlist = filtertools.get_links(itemlist, item, list_language)

    # Controlla se i link sono validi
    # if checklinks:
    #     itemlist = servertools.check_list_links(itemlist, checklinks_number)
    #
    # autoplay.start(itemlist, item)

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
    # itemlist = filtertools.get_links(itemlist, item, list_language)

    # Controlla se i link sono validi
    # if checklinks:
    #     itemlist = servertools.check_list_links(itemlist, checklinks_number)
    #
    # autoplay.start(itemlist, item)

    return itemlist


# ================================================================================================================


# ----------------------------------------------------------------------------------------------------------------
def latestep(item):
    support.log(item.channel + " latestep")
    itemlist = []
    titles = []

    #recupero gli episodi in home nella sezione Ultimi episodi aggiunti
    data = httptools.downloadpage(host, headers=headers).data

    block = scrapertools.find_single_match(data,r"Ultimi episodi aggiunti.*?<h2>")
    regex = r'<a href="([^"]*)"\sdata-src="([^"]*)"\sclass="owl-lazy.*?".*?class="title">(.*?)<small>\((\d*?)x(\d*?)\s(Sub-Ita|Ita)'
    matches = re.compile(regex, re.DOTALL).findall(block)

    for scrapedurl, scrapedimg, scrapedtitle, scrapedseason, scrapedepisode, scrapedlanguage in matches:
        infoLabels = {}
        year = scrapertools.find_single_match(scrapedtitle, '\((\d{4})\)')
        if year:
            infoLabels['year'] = year
        infoLabels['episode'] = scrapedepisode
        infoLabels['season'] = scrapedseason
        episode = scrapedseason+"x"+scrapedepisode

        scrapedtitle = cleantitle(scrapedtitle)
        title = scrapedtitle+" - "+episode
        contentlanguage = ""
        if scrapedlanguage.strip().lower() != 'ita':
            title +=" Sub-ITA"
            contentlanguage = 'Sub-ITA'

        titles.append(title)
        itemlist.append(
            Item(channel=item.channel,
                 action="findepisodevideo",
                 title=title,
                 fulltitle=title,
                 url=scrapedurl,
                 extra=[[scrapedseason,scrapedepisode]],
                 thumbnail=scrapedimg,
                 contentSerieName=scrapedtitle,
                 contentLanguage=contentlanguage,
                 contentType='episode',
                 infoLabels=infoLabels,
                 folder=True))

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
        infoLabels['episode'] = episodio[0][1]
        infoLabels['season'] = episodio[0][0]

        episode = infoLabels['season'] + "x" + infoLabels['episode']
        title = "%s - %s" % (scrapedtitle, episode)
        title = title.strip()
        contentlanguage = ""
        if 'sub-ita' in scrapedinfo.lower():
            title+=" Sub-ITA"
            contentlanguage = 'Sub-ITA'

        if title in titles: continue
        itemlist.append(
            Item(channel=item.channel,
                 action="findepisodevideo",
                 title=title,
                 fulltitle=title,
                 url=scrapedurl,
                 extra=episodio,
                 thumbnail=scrapedimg,
                 contentSerieName=scrapedtitle,
                 contentLanguage=contentlanguage,
                 infoLabels=infoLabels,
                 contentType='episode',
                 folder=True))



    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # logger.debug("".join(map(str,itemlist)))

    return itemlist


# ================================================================================================================

# ----------------------------------------------------------------------------------------------------------------
def newest(categoria):
    logger.info(__channel__ + " newest" + categoria)
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
                 contentType="tvshow",
                 url="%s%s" % (host, scrapedurl),
                 thumbnail=item.thumbnail,
                 folder=True))

    return itemlist

# ================================================================================================================
