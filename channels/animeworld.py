# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per animeworld
# thanks to fatshotty
# ----------------------------------------------------------

from core import httptools, support, config, jsontools

host = support.config.get_channel_url()
__channel__ = 'animeworld'
cookie = support.config.get_setting('cookie', __channel__)
headers = [['Cookie', cookie]]


def get_cookie(data):
    global cookie, headers
    cookie = support.match(data, patron=r'document.cookie="([^\s]+)').match
    support.config.set_setting('cookie', cookie, __channel__)
    headers = [['Cookie', cookie]]


def get_data(item):
    # support.dbg()
    url = httptools.downloadpage(item.url, headers=headers, follow_redirects=True, only_headers=True).url
    data = support.match(url, headers=headers, follow_redirects=True).data
    if 'SecurityAW' in data:
        get_cookie(data)
        data = get_data(item)
    return data


def order():
    # Seleziona l'ordinamento dei risultati
    return str(support.config.get_setting("order", __channel__))


@support.menu
def mainlist(item):
    anime=['/filter?sort=',
           ('ITA',['/filter?dub=1&sort=', 'menu', 'dub=1']),
           ('SUB-ITA',['/filter?dub=0&sort=', 'menu', 'dub=0']),
           ('In Corso', ['/ongoing', 'peliculas','noorder']),
           ('Ultimi Episodi', ['/updated', 'peliculas', 'updated']),
           ('Nuove Aggiunte',['/newest', 'peliculas','noorder' ]),
           ('Generi',['/?d=1','genres',])]
    return locals()


@support.scrape
def genres(item):
    action = 'peliculas'
    data = get_data(item)

    patronBlock = r'dropdown[^>]*>\s*Generi\s*<span.[^>]+>(?P<block>.*?)</ul>'
    patronMenu = r'<input.*?name="(?P<name>[^"]+)" value="(?P<value>[^"]+)"\s*>[^>]+>(?P<title>[^<]+)</label>'

    def itemHook(item):
        item.url = host + '/filter?' + item.name + '=' + item.value + '&sort='
        return item
    return locals()


@support.scrape
def menu(item):
    action = 'submenu'
    data = get_data(item)
    patronMenu=r'<button[^>]+>\s*(?P<title>[A-Za-z0-9]+)\s*<span.[^>]+>(?P<other>.*?)</ul>'
    def itemlistHook(itemlist):
        itemlist.insert(0, item.clone(title=support.typo('Tutti','bold'), action='peliculas'))
        itemlist.append(item.clone(title=support.typo('Cerca...','bold'), action='search', search=True, thumbnail=support.thumb('search.png')))
        return itemlist
    return locals()


@support.scrape
def submenu(item):
    action = 'peliculas'
    data = item.other
    # debug=True
    patronMenu = r'<input.*?name="(?P<name>[^"]+)" value="(?P<value>[^"]+)"\s*>[^>]+>(?P<title>[^<]+)<\/label>'
    def itemHook(item):
        item.url = '{}/filter?{}={}&{}{}'.format(host, item.name, item.value, item.args, ('&sort=' if item.name != 'sort' else ''))
        return item
    return locals()


def newest(categoria):
    support.info(categoria)
    item = support.Item()
    lang = config.get_setting('lang', channel=item.channel)
    try:
        if categoria == "anime":
            item.url = host
            item.args = "updated"
            return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("{0}".format(line))
        return []


def search(item, text):
    support.info(text)
    if item.search:
        item.url = '{}/filter?{}&keyword={}&sort='.format(host, item.args, text)
    else:
        lang = ['?', '?dub=1&', '?dub=0&'][config.get_setting('lang', channel=item.channel)]
        item.url = '{}/filter{}&keyword={}&sort='.format(host, lang, text)
    item.contentType = 'tvshow'
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
    data = get_data(item)
    anime = True
    if item.args not in ['noorder', 'updated'] and not item.url[-1].isdigit(): item.url += order() # usa l'ordinamento di configura canale
    data = get_data(item)

    if item.args == 'updated':
        item.contentType='episode'
        patron=r'<div class="inner">\s*<a href="(?P<url>[^"]+)" class[^>]+>\s*<img.*?src="(?P<thumb>[^"]+)" alt?="(?P<title>[^\("]+)(?:\((?P<lang>[^\)]+)\))?"[^>]+>[^>]+>\s*(?:<div class="[^"]+">(?P<type>[^<]+)</div>)?(?:[^>]+>){2,4}\s*<div class="ep">[^\d]+(?P<episode>\d+)[^<]*</div>'
        action='findvideos'
    else:
        patron= r'<div class="inner">\s*<a href="(?P<url>[^"]+)" class[^>]+>\s*<img.*?src="(?P<thumb>[^"]+)" alt?="(?P<title>[^\("]+)(?:\((?P<year>\d+)\) )?(?:\((?P<lang>[^\)]+)\))?(?P<title2>[^"]+)?[^>]+>[^>]+>(?:\s*<div class="(?P<l>[^"]+)">[^>]+>)?\s*(?:<div class="[^"]+">(?P<type>[^<]+)</div>)?'
        action='check'

    # Controlla la lingua se assente
    patronNext=r'<a href="([^"]+)" class="[^"]+" id="go-next'
    #typeContentDict={'movie':['movie', 'special']}
    #typeActionDict={'findvideos':['movie', 'special']}
    def itemHook(item):
        if not item.contentLanguage:
            if 'dub=1' in item.url or item.l == 'dub':
                item.contentLanguage = 'ITA'
                item.title += support.typo(item.contentLanguage,'_ [] color std')
            else:
                item.contentLanguage = 'Sub-ITA'
                item.title += support.typo(item.contentLanguage,'_ [] color std')
        return item
    return locals()

def check(item):
    item.data = httptools.downloadpage(item.url).data
    if support.match(item.data, patron='Episodi.*1</dd>.*?Stato:.*?Finito</').match == '':
        item.contentType = 'tvshow'
        return episodios(item)
    else:
        return findvideos(item)


@support.scrape
def episodios(item):
    data = get_data(item)
    anime = True
    pagination = 50
    patronBlock= r'<div class="server\s*active\s*"(?P<block>.*?)(?:<div class="server|<link)'
    patron = r'<li[^>]*>\s*<a.*?href="(?P<url>[^"]+)"[^>]*>(?P<episode>[^-<]+)(?:-(?P<episode2>[^<]+))?'
    def itemHook(item):
        item.number = support.re.sub(r'\[[^\]]+\]', '', item.title)
        item.title += support.typo(item.fulltitle,'-- bold')
        return item
    action='findvideos'    
    return locals()


def findvideos(item):
    import time
    support.info(item)
    itemlist = []
    urls = []
    # resp = support.match(get_data(item), headers=headers, patron=r'data-name="(\d+)">([^<]+)<')
    resp = support.match(get_data(item), headers=headers, patron=r'data-name="(\d+)">([^<]+)<')
    data = resp.data

    for ID, name in resp.matches:
        if not item.number: item.number = support.match(item.title, patron=r'(\d+) -').match
        match = support.match(data, patronBlock=r'data-name="' + ID + r'"[^>]+>(.*?)(?:<div class="(?:server|download)|link)', patron=r'data-id="([^"]+)" data-episode-num="' + (item.number if item.number else '1') + '"' + r'.*?href="([^"]+)"').match
        if match:
            epID, epurl = match
            # if 'vvvvid' in name.lower():
            #     urls.append(support.match(host + '/api/episode/ugly/serverPlayerAnimeWorld?id=' + epID, headers=headers, patron=r'<a.*?href="([^"]+)"', debug=True).match)
            if 'animeworld' in name.lower():
                url = support.match(data, patron=r'href="([^"]+)"\s*id="alternativeDownloadLink"', headers=headers).match
                title = support.match(url, patron=r'http[s]?://(?:www.)?([^.]+)', string=True).match
                itemlist.append(item.clone(action="play", title=title, url=url, server='directo'))
            else:
                dataJson = support.match(host + '/api/episode/info?id=' + epID + '&alt=0', headers=headers).data
                json = jsontools.load(dataJson)

                title = support.match(json['grabber'], patron=r'server\d+.([^.]+)', string=True).match
                if title: itemlist.append(item.clone(action="play", title=title, url=json['grabber'].split('=')[-1], server='directo'))
                else: urls.append(json['grabber'])
    # support.info(urls)
    return support.server(item, urls, itemlist)
