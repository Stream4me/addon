# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per AnimeSaturn
# ----------------------------------------------------------

from core import support
from platformcode import logger
import pyaes

host = support.config.get_channel_url()
__channel__ = 'animesaturn'
cookie = support.config.get_setting('cookie', __channel__)
headers = {'X-Requested-With': 'XMLHttpRequest', 'Cookie': cookie}


def get_cookie(data, cookie_name):
    global cookie, headers
    a = support.match(data, patron=r'a=toNumbers\("([^"]+?)"\)').match 
    b = support.match(data, patron=r'b=toNumbers\("([^"]+?)"\)').match 
    c = support.match(data, patron=r'c=toNumbers\("([^"]+?)"\)').match

    aes = pyaes.AESModeOfOperationCBC(bytes.fromhex(a), iv = bytes.fromhex(b))

    cookie = cookie_name + "=" + aes.decrypt(bytes.fromhex(c)).hex()
    logger.debug("cookie = " + cookie)
    support.config.set_setting('cookie', cookie, __channel__)
    headers = [['Cookie', cookie]]


def get_data(url):
    global headers

    data = support.match(url, headers=headers, follow_redirects=True).data
    cookie_name = support.match(data, patron=r'cookie="(.*?)="\+toHex\(slowAES').match
    if cookie_name:
        get_cookie(data, cookie_name)
        return get_data(url)
    
    cookie = support.match(data, patron=r'document.cookie=\"(.*?)\s').match
    if cookie:        
        headers['Cookie'] = cookie
        support.config.set_setting('cookie', cookie, __channel__)
        return get_data(url)
    
    return data


@support.menu
def mainlist(item):

    menu = [ ('Anime', ['/filter?', 'peliculas','filter']),
             ('ITA',['', 'submenu', '/filter?language%5B0%5D=1']),
             ('SUB-ITA',['', 'submenu', '/filter?language%5B0%5D=0']),
             ('Più Votati',['/toplist','menu', 'top']),
             ('In Corso',['/animeincorso','peliculas','incorso']),
             ('Ultimi Episodi',['/fetch_pages.php?request=episodes&d=1','peliculas','updated'])]
    search = ''

    return locals()


def search(item, texto):
    support.info(texto)
    item.url = host + '/animelist?search=' + texto
    item.contentType = 'tvshow'
    try:
        return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)
        return []


def newest(categoria):
    support.info()
    itemlist = []
    item = support.Item()
    try:
        if categoria == "anime":
            item.url = host + '/fetch_pages.php?request=episodes&d=1'
            item.args = "updated"
            return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("{0}".format(line))
        return []

    return itemlist


@support.scrape
def submenu(item):
    data = get_data(item.url + item.args) #support.match(item.url + item.args).data
    action = 'filter'
    patronMenu = r'<h5 class="[^"]+">(?P<title>[^<]+)[^>]+>[^>]+>\s*<select id="(?P<parameter>[^"]+)"[^>]+>(?P<data>.*?)</select>'
    def itemlistHook(itemlist):
        itemlist.insert(0, item.clone(title=support.typo('Tutti','bold'), url=item.url + item.args, action='peliculas'))
        return itemlist[:-1]
    return locals()


def filter(item):
    itemlist = []
    data = item.data if item.data else get_data(item.url)
    matches = support.match(data, patron=r'<option value="(?P<value>[^"]+)"[^>]*>(?P<title>[^<]+)',  headers=headers).matches
    for value, title in matches:
        itemlist.append(item.clone(title= support.typo(title,'bold'), url='{}{}&{}%5B0%5D={}'.format(host, item.args, item.parameter, value), action='peliculas', args='filter'))
    support.thumb(itemlist, genre=True)
    return itemlist


@support.scrape
def menu(item):
    data = item.data if item.data else get_data(item.url)
    patronMenu = r'<div class="col-md-9 pl-0 mobile-padding margin-top-anime-page float-left pr-0">.*?href="(?P<url>[^"]+)".*?</div>(?P<title>.*?)<'
    action = 'check'

    return locals()


@support.scrape
def peliculas(item):
    anime = True

    deflang= 'Sub-ITA'
    action = 'check'
    page = None
    post = "page=" + str(item.page if item.page else 1) if item.page and int(item.page) > 1 else None
    data = get_data(item.url)

    if item.args == 'top':
        data = item.other
        patron = r'light">(?P<title2>[^<]+)</div>\s*(?P<title>[^<]+)[^>]+>[^>]+>\s*<a href="(?P<url>[^"]+)">(?:<a[^>]+>|\s*)<img.*?src="(?P<thumb>[^"]+)"'
    else:
        data = support.match(item, post=post, headers=headers).data
        if item.args == 'updated':
            page = support.match(data, patron=r'data-page="(\d+)" title="Next">').match
            patron = r'<a href="(?P<url>[^"]+)" title="(?P<title>[^"(]+)(?:\s*\((?P<year>\d+)\))?(?:\s*\((?P<lang>[A-Za-z-]+)\))?">\s*<img src="(?P<thumb>[^"]+)"[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s\s*(?P<type>[^\s]+)\s*(?P<episode>\d+)'
            typeContentDict = {'Movie':'movie', 'Episodio':'episode'} #item.contentType='episode'
            action = 'findvideos'
            def itemlistHook(itemlist):
                if page:
                    itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),page= page, thumbnail=support.thumb()))
                return itemlist
        elif 'filter' in item.args:
            page = support.match(data, patron=r'totalPages:\s*(\d+)').match
            patron = r'<a href="(?P<url>[^"]+)" title="(?P<title>[^"(]+)(?:\s*\((?P<year>\d+)\))?(?:\s*\((?P<lang>[A-Za-z-]+)\))?">\s*<img src="(?P<thumb>[^"]+)"'
            def itemlistHook(itemlist):
                if item.nextpage: item.nextpage += 1
                else: item.nextpage = 2
                if page and item.nextpage < int(page):
                    itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'), url= '{}&page={}'.format(item.url, item.nextpage), infoLabels={}, thumbnail=support.thumb()))
                return itemlist

        else:
            # pagination = ''
            if item.args == 'incorso':
                patron = r'<a href="(?P<url>[^"]+)"[^>]+>(?P<title>[^<(]+)(?:\s*\((?P<year>\d+)\))?(?:\s*\((?P<lang>[A-za-z-]+)\))?</a>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*<img width="[^"]+" height="[^"]+" src="(?P<thumb>[^"]+)"[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>(?P<plot>[^<]+)<'
            else:
                patron = r'<img src="(?P<thumb>[^"]+)" alt="(?P<title>[^"\(]+)(?:\((?P<lang>[Ii][Tt][Aa])\))?(?:\s*\((?P<year>\d+)\))?[^"]*"[^>]+>[^>]+>[^>]+>[^>]+>[^>]+>\s*<a class="[^"]+" href="(?P<url>[^"]+)">[^>]+>[^>]+>[^>]+>\s*<p[^>]+>(?:(?P<plot>[^<]+))?<'

    return locals()


def check(item):
    movie = support.match(item, patron=r'Episodi:</b> (\d*) Movie',  headers=headers)
    if movie.match:
        episodes = episodios(item)
        if len(episodes) > 0:
            it = episodes[0].clone(contentType = 'movie', contentTitle=item.fulltitle, contentSerieName='')
        return findvideos(it)
    else:
        item.contentType = 'tvshow'
        return episodios(item)


@support.scrape
def episodios(item):
    if item.contentType != 'movie': anime = True
    patron = r'episodi-link-button">\s*<a href="(?P<url>[^"]+)"[^>]+>\s*(?P<title>[^\d<]+(?P<episode>\d+))\s*</a>'
    return locals()


def findvideos(item):
    support.info()
    itemlist = []
    links = []

    main_url = support.match(item, patron=r'<a href="([^"]+)">[^>]+>[^>]+>G',  headers=headers).match
    urls = support.match(support.match(main_url, headers=headers).data, patron=r'<a class="dropdown-item"\s*href="([^"]+)', headers=headers).matches
    itemlist.append(item.clone(action="play", title='Primario', url=main_url, server='directo'))
    #itemlist.append(item.clone(action="play", title='Secondario', url=main_url + '&s=alt', server='directo'))
    for url in urls:
        link = support.match(url, patron=r'<a href="([^"]+)"[^>]+><button', headers=headers).match
        if link:
            links.append(link)
    return support.server(item, data=links, itemlist=itemlist)


def play(item):
    if item.server == 'directo':
        item.url = support.match(item.url, patron=r'(?:source type="[^"]+"\s*src=|file:[^"]+)"([^"]+)',  headers=headers).match
    return[item]
