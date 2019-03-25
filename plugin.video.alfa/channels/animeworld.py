# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per animeworld
# ----------------------------------------------------------
import re, urlparse

from core import httptools, scrapertoolsV2, servertools, tmdb
from core.item import Item
from platformcode import logger, config
from channels import autoplay, filtertools, support



host = "https://www.animeworld.it"

headers = [['Referer', host]]

IDIOMAS = {'Italiano': 'Italiano'}
list_language = IDIOMAS.values()
list_servers = ['diretto']
list_quality = []

__comprueba_enlaces__ = config.get_setting('comprueba_enlaces', 'animeworld')
__comprueba_enlaces_num__ = config.get_setting('comprueba_enlaces_num', 'animeworld')


def mainlist(item):
    logger.info("[animeworld.py] mainlist")

    autoplay.init(item.channel, list_servers, list_quality)
    itemlist =[]
    menu = support.menu
    menu(itemlist, item, '[B]Anime ITA[/B]', 'build_menu', host+'/filter?language[]=1')
    menu(itemlist, item, '[B]Anime SUB[/B]', 'build_menu', host+'/filter?language[]=0')
    menu(itemlist, item, 'Anime A-Z', 'alfabetico', host+'/az-list')
    menu(itemlist, item, 'Anime - Ultimi Aggiunti', 'alfabetico', host+'/newest')
    menu(itemlist, item, 'Anime - Ultimi Episodi', 'alfabetico', host+'/newest')
    menu(itemlist, item, '[COLOR blue]Cerca...[/COLOR]', 'search')

    # itemlist = [        
    #     Item(
    #         channel=item.channel,
    #         action="build_menu",
    #         title="[B]Anime ITA[/B]",
    #         url=host+'/filter?language[]=1',
    #         thumbnail=CategoriaThumbnail,
    #         fanart=CategoriaFanart),
    #     Item(
    #         channel=item.channel,
    #         action="build_menu",
    #         title="[B]Anime SUB[/B]",
    #         url=host+'/filter?language[]=0',
    #         thumbnail=CategoriaThumbnail,
    #         fanart=CategoriaFanart),
    #     Item(
    #         channel=item.channel,
    #         action="alfabetico",
    #         title="Anime A-Z",
    #         url=host + "/az-list",
    #         thumbnail=CategoriaThumbnail,
    #         fanart=CategoriaFanart),
    #     Item(
    #         channel=item.channel,
    #         action="video",
    #         title="Ultime Aggiunte",
    #         url=host + "/newest",
    #         thumbnail=CategoriaThumbnail,
    #         fanart=CategoriaFanart),
    #     Item(
    #         channel=item.channel,
    #         action="video",
    #         title="Ultimi Episodi",
    #         url=host + "/updated",
    #         thumbnail=CategoriaThumbnail,
    #         fanart=CategoriaFanart),
    #     Item(
    #         channel=item.channel,
    #         action="search",
    #         title="[B]Cerca ...[/B]",
    #         thumbnail=
    #         "http://dc467.4shared.com/img/fEbJqOum/s7/13feaf0c8c0/Search")
    # ]

    autoplay.show_option(item.channel, itemlist)

    return itemlist


# Crea Menu Filtro ======================================================

def build_menu(item):
    itemlist = []
    itemlist.append(Item(
                    channel=item.channel,
                    action="video",
                    title="[B]Tutti[/B]",
                    url=item.url,
                    thumbnail=CategoriaThumbnail,
                    fanart=CategoriaFanart))

    data = httptools.downloadpage(item.url).data
    data = re.sub(r'\n|\t','',data)
    data = re.sub(r'>\s*<','><',data)
 
    block = scrapertoolsV2.get_match(data, r'<form class="filters.*?>(.*?)<\/form>')
    
    matches = re.compile(r'<button class="btn btn-sm btn-default dropdown-toggle" data-toggle="dropdown"> (.*?) <span.*?>(.*?)<\/ul>', re.DOTALL).findall(block)

    for title, html in matches:
        itemlist.append(
            Item(channel=item.channel,
                 action='build_sub_menu',
                 contentType="tvshow",
                 title='[B]' + title + ' >[/B]',
                 fulltitle=title,
                 show=title,
                 url=item.url,
                 html=html))

    # Elimina FLingua dal Menu
    itemlist.pop(5)

    return itemlist

# Crea SottoMenu Filtro ======================================================

def build_sub_menu(item):
    itemlist = []
    matches = re.compile(r'<input.*?name="(.*?)" value="(.*?)".*?><label.*?>(.*?)<\/label>', re.DOTALL).findall(item.html)
    for name, value, title in matches:
        itemlist.append(
            Item(channel=item.channel,
                 action='video',
                 contentType="tvshow",
                 title='[B]' + title + ' >[/B]',
                 fulltitle=title,
                 show=title,
                 url=item.url + '&' + name + '=' + value,
                 plot=""))

    return itemlist

# Novità ======================================================

def newest(categoria):
    logger.info("[animeworld.py] newest")
    itemlist = []
    item = Item()
    try:
        if categoria == "anime":
            item.url = host + '/newest'
            item.action = "video"
            itemlist = video(item)

            if itemlist[-1].action == "video":
                itemlist.pop()
    # Continua la ricerca in caso di errore 
    except:
        import sys
        for line in sys.exc_info():
            logger.error("{0}".format(line))
        return []

    return itemlist


# Cerca ===========================================================

def search(item, texto):
    logger.info(texto)
    item.url = host + '/search?keyword=' + texto
    try:
        return video(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []




# Lista A-Z ====================================================

def alfabetico(item):
    logger.info("[animeworld.py] alfabetico")
    itemlist = []

    data = httptools.downloadpage(item.url).data
    data = re.sub(r'\n|\t','',data)
    data = re.sub(r'>\s*<','><',data)

    block = scrapertoolsV2.get_match(data, r'<span>.*?A alla Z.<\/span>.*?<ul>(.*?)<\/ul>')

    matches = re.compile('<a href="([^"]+)" title="([^"]+)">', re.DOTALL).findall(block)
    scrapertoolsV2.printMatches(matches)

    for url, title in matches:
        itemlist.append(
            Item(channel=item.channel,
                 action='lista_anime',
                 contentType="tvshow",
                 title=title,
                 fulltitle=title,
                 show=title,
                 url=url,
                 plot=""))

    return itemlist

def lista_anime(item):
    logger.info("[animeworld.py] lista_anime")

    itemlist = []

    # Carica la pagina
    data = httptools.downloadpage(item.url).data
    data = re.sub(r'\n|\t','',data)
    data = re.sub(r'>\s*<','><',data)

    # Estrae i contenuti
    patron = r'<div class="item"><a href="([^"]+)".*?src="([^"]+)".*?data-jtitle="([^"]+)".*?>([^<]+)<\/a><p>(.*?)<\/p>'
    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedurl, scrapedthumb, scrapedoriginal, scrapedtitle, scrapedplot in matches:
        
        if scrapedoriginal == scrapedtitle:
            scrapedoriginal=''
        else:
            scrapedoriginal = ' - [ ' + scrapedoriginal + ' ]'

        year = ''
        lang = ''
        if '(' in scrapedtitle:
            year = scrapertoolsV2.find_single_match(scrapedtitle, r'(\([0-9]+\))')
            lang = scrapertoolsV2.find_single_match(scrapedtitle, r'(\([a-zA-Z]+\))')
        
        title = scrapedtitle.replace(year,'').replace(lang,'')
        original = scrapedoriginal.replace(year,'').replace(lang,'')
        title = '[B]' + title + '[/B]' + year + lang + original
        itemlist.append(
                Item(channel=item.channel,
                     extra=item.extra,
                     contentType="tvshow",
                     action="episodios",
                     text_color="azure",
                     title=title,
                     url=scrapedurl,
                     thumbnail=scrapedthumb,
                     fulltitle=title,
                     show=title,
                     plot=scrapedplot,
                     folder=True))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # Next page
    next_page = scrapertoolsV2.find_single_match(data, '<a class="page-link" href="([^"]+)" rel="next"')

    if next_page != '':
        itemlist.append(
            Item(channel=item.channel,
                 action='lista_anime',
                 title='[B]' + config.get_localized_string(30992) + ' &raquo;[/B]',
                 url=next_page,
                 contentType=item.contentType,
                 thumbnail='http://2.bp.blogspot.com/-fE9tzwmjaeQ/UcM2apxDtjI/AAAAAAAAeeg/WKSGM2TADLM/s1600/pager+old.png'))


    return itemlist


def video(item):
    logger.info("[animeworld.py] video")
    itemlist = []

    data = httptools.downloadpage(item.url).data
    data = re.sub(r'\n|\t','',data)
    data = re.sub(r'>\s*<','><',data)

    patron = r'<a href="([^"]+)" class="poster.*?><img src="([^"]+)"(.*?)data-jtitle="([^"]+)" .*?>(.*?)<\/a>'
    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedurl, scrapedthumb ,scrapedinfo, scrapedoriginal, scrapedtitle in matches:
        # Cerca Info come anno o lingua nel Titolo
        year = ''
        lang = ''
        if '(' in scrapedtitle:
            year = scrapertoolsV2.find_single_match(scrapedtitle, r'( \([0-9]+\))')
            lang = scrapertoolsV2.find_single_match(scrapedtitle, r'( \([a-zA-Z]+\))')
        
        # Rimuove Anno e Lingua nel Titolo
        title = scrapedtitle.replace(year,'').replace(lang,'')
        original = scrapedoriginal.replace(year,'').replace(lang,'')
        
        # Compara Il Titolo con quello originale
        if original == title:
            original=''
        else:
            original = ' - [ ' + scrapedoriginal + ' ]'

        # cerca info supplementari
        ep = ''
        ep = scrapertoolsV2.find_single_match(scrapedinfo, '<div class="ep">(.*?)<')
        if  ep != '':
            ep = ' - ' + ep

        ova = ''
        ova = scrapertoolsV2.find_single_match(scrapedinfo, '<div class="ova">(.*?)<')
        if  ova != '':
            ova = ' - (' + ova + ')'
        
        ona = ''
        ona = scrapertoolsV2.find_single_match(scrapedinfo, '<div class="ona">(.*?)<')
        if  ona != '':
            ona = ' - (' + ona + ')'

        movie = ''
        movie = scrapertoolsV2.find_single_match(scrapedinfo, '<div class="movie">(.*?)<')
        if  movie != '':
            movie = ' - (' + movie + ')'

        special = ''
        special = scrapertoolsV2.find_single_match(scrapedinfo, '<div class="special">(.*?)<')
        if  special != '':
            special = ' - (' + special + ')'


        # Concatena le informazioni
        info = ep + lang + year + ova + ona + movie + special

        # Crea il title da visualizzare
        long_title = '[B]' + title + '[/B]' + info + original

        # Controlla se sono Episodi o Film
        if movie == '':
            contentType = 'tvshow'
            action = 'episodios'
        else:
            contentType = 'movie'
            action = 'findvideos'
        
        itemlist.append(
                Item(channel=item.channel,
                     contentType=contentType,
                     action=action,
                     title=long_title,
                     url=scrapedurl,
                     fulltitle=title,
                     show=title,
                     thumbnail=scrapedthumb))
    
    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

    # Next page
    next_page = scrapertoolsV2.find_single_match(data, '<a class="page-link" href=".*?page=([^"]+)" rel="next"')

    if next_page != '':
        itemlist.append(
            Item(channel=item.channel,
                 action='video',
                 title='[B]' + config.get_localized_string(30992) + ' &raquo;[/B]',
                 url=re.sub('&page=([^"]+)', '', item.url) + '&page=' + next_page,
                 contentType=item.contentType,
                 thumbnail='http://2.bp.blogspot.com/-fE9tzwmjaeQ/UcM2apxDtjI/AAAAAAAAeeg/WKSGM2TADLM/s1600/pager+old.png'))

    return itemlist


def episodios(item):
    logger.info("[animeworld.py] episodios")
    itemlist = []

    data = httptools.downloadpage(item.url).data.replace('\n', '')
    data = re.sub(r'>\s*<', '><', data)
    block = scrapertoolsV2.find_single_match(data, r'<div class="widget servers".*?>(.*?)<div id="download"')
    block = scrapertoolsV2.find_single_match(block,r'<div class="server.*?>(.*?)<div class="server.*?>')
   
    patron = r'<li><a.*?href="([^"]+)".*?>(.*?)<\/a>'
    matches = re.compile(patron, re.DOTALL).findall(block)

    for scrapedurl, scrapedtitle in matches:
        scrapedtitle = '[B] Episodio ' + scrapedtitle + '[/B]'
        itemlist.append(
            Item(
                channel=item.channel,
                action="findvideos",
                contentType="episode",
                title=scrapedtitle,
                url=urlparse.urljoin(host, scrapedurl),
                fulltitle=scrapedtitle,
                show=scrapedtitle,
                plot=item.plot,
                fanart=item.thumbnail,
                thumbnail=item.thumbnail))

    # Aggiungi a Libreria
    if config.get_videolibrary_support() and len(itemlist) != 0:
        itemlist.append(
            Item(
                channel=item.channel,
                title="[COLOR lightblue]%s[/COLOR]" % config.get_localized_string(30161),
                url=item.url,
                action="add_serie_to_library",
                extra="episodios",
                show=item.show))

    return itemlist


def findvideos(item):
    logger.info("[animeworld.py] findvideos")

    itemlist = []
   
    anime_id = scrapertoolsV2.find_single_match(item.url, r'.*\..*?\/(.*)')
    data = httptools.downloadpage(host + "/ajax/episode/serverPlayer?id=" + anime_id).data
    patron = '<source src="([^"]+)"'

    matches = re.compile(patron, re.DOTALL).findall(data)
    for video in matches:
        itemlist.append(
            Item(
                channel=item.channel,
                action="play",
                title=item.title + " [[COLOR orange]Diretto[/COLOR]]",
                url=video,
                server='directo',
                contentType=item.contentType,
                folder=False))

    # Requerido para Filtrar enlaces

    if __comprueba_enlaces__:
        itemlist = servertools.check_list_links(itemlist, __comprueba_enlaces_num__)

    # Requerido para FilterTools

    itemlist = filtertools.get_links(itemlist, item, list_language)

    # Requerido para AutoPlay

    autoplay.start(itemlist, item)

    return itemlist



# riferimenti di servizio ====================================================
AnimeThumbnail = "http://img15.deviantart.net/f81c/i/2011/173/7/6/cursed_candies_anime_poster_by_careko-d3jnzg9.jpg"
AnimeFanart = "https://i.ytimg.com/vi/IAlbvyBdYdY/maxresdefault.jpg"
CategoriaThumbnail = "http://static.europosters.cz/image/750/poster/street-fighter-anime-i4817.jpg"
CategoriaFanart = "https://i.ytimg.com/vi/IAlbvyBdYdY/maxresdefault.jpg"
CercaThumbnail = "http://dc467.4shared.com/img/fEbJqOum/s7/13feaf0c8c0/Search"
CercaFanart = "https://i.ytimg.com/vi/IAlbvyBdYdY/maxresdefault.jpg"
AvantiTxt = config.get_localized_string(30992)
AvantiImg = "http://2.bp.blogspot.com/-fE9tzwmjaeQ/UcM2apxDtjI/AAAAAAAAeeg/WKSGM2TADLM/s1600/pager+old.png"
