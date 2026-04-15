# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per StreamingCommunity
# ------------------------------------------------------------

import json, re, sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True

if PY3: import urllib.parse as urllib_parse
else: import urlparse as urllib_parse

from core import support, channeltools, httptools, jsontools
from platformcode import logger, config

if sys.version_info[0] >= 3:
    from concurrent import futures
else:
    from concurrent_py2 import futures

# def findhost(url):
#     return 'https://' + support.match(url, patron='var domain\s*=\s*"([^"]+)').match


host = support.config.get_channel_url()

# def getHeaders(forced=False):
#     global headers
#     global host
#     if not headers:
#         # try:
#         headers = {'User-Agent': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-GB; rv:1.8.1.14) Gecko/20080404 Firefox/2.0.0.14'}
#         response = httptools.downloadpage(host, headers=headers)
#         # if not response.url.startswith(host):
#         #     host = support.config.get_channel_url(findhost, forceFindhost=True)
#         csrf_token = support.match(response.data, patron='name="csrf-token" content="([^"]+)"').match
#         headers = {'User-Agent': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-GB; rv:1.8.1.14) Gecko/20080404 Firefox/2.0.0.14',
#                     # 'content-type': 'application/json;charset=UTF-8',
#                     'Referer': host,
#                     'x-csrf-token': csrf_token,
#                     'Cookie': '; '.join([x.name + '=' + x.value for x in response.cookies])}
        # except:
        #     host = support.config.get_channel_url(findhost, forceFindhost=True)
        #     if not forced: getHeaders(True)

# getHeaders()

@support.menu
def mainlist(item):
    film=['/it/movies',
          ('Aggiunti di recente',['/it/movies','peliculas',1]),
          ('Top 10 film di oggi',['/it/movies','peliculas',2])]
    tvshow=['/it/tv-shows',
            ('Aggiunti di recente', ['/it/tv-shows', 'peliculas', 1]),
            ('Top 10 serie TV di oggi', ['/it/tv-shows', 'peliculas', 2])]
    generi = [('Generi', ['','genres'])]
    menu = [
        ('Archivio', ['/it/archive', 'peliculas', -1]),
	('Archivio Film {submenu}', ['/it/archive?type=movie', 'peliculas', -1]),
    ('Archivio Serie TV {submenu}', ['/it/archive?type=tv', 'peliculas', -1]),
    ('Archivio per data aggiornamento {submenu}', ['/it/archive?sort=last_air_date', 'peliculas', -1]),
	('Archivio per data aggiunta {submenu}', ['/it/archive?sort=created_at', 'peliculas', -1]),
	('Archivio per valutazione {submenu}', ['/it/archive?sort=score', 'peliculas', -1]),
	('Archivio per numero visioni {submenu}', ['/it/archive?sort=views', 'peliculas', -1]),
	('Archivio per nome {submenu}', ['/it/archive?sort=name', 'peliculas', -1])
    ]
    search=''
    return locals()


def get_data(url):
    return jsontools.load(
        support.scrapertools.decodeHtmlentities(support.match(url, patron='data-page="([^"]+)', debug=False).match))


def genres(item):
    # getHeaders()
    # logger.debug()
    itemlist = []
    data_page = get_data(item.url)
    args = data_page['props']['genres']

    for arg in args:
        itemlist.append(item.clone(title=support.typo(arg['name'], 'bold'), url=host+'/it/archive?genre[]='+str(arg['id']), action='peliculas', genre=True))
    support.thumb(itemlist, genre=True)
    return itemlist


def search(item, text):
    logger.debug('search', text)
    item.search = True
    item.url = host + '/it/search?q=' + text

    try:
        return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error(line)
        return []


def newest(category):
    logger.debug(category)
    itemlist = []
    item = support.Item()
    item.args = 1
    item.newest = True
    if category == 'peliculas':
        item.contentType = 'movie'
        item.url = host + '/it/movies'
    else:
        item.contentType = 'tvshow'
        item.url = host + '/it/tv-shows'

    try:
        itemlist = peliculas(item)

        if itemlist[-1].action == 'peliculas':
            itemlist.pop()
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error(line)
        return []

    return itemlist


def peliculas(item):
    logger.debug()
    if item.mainThumb: item.thumbnail = item.mainThumb
    global host
    itemlist = []
    items = []
    recordlist = []
    page = item.page if item.page else 0
    data_page = get_data(item.url)

    if item.records:
        records = item.records
    elif item.genre or item.search or (item.args and item.args == -1):
        records = data_page['props']['titles']
    else:
        if not item.args:
            item.args = 0
        records = data_page['props']['sliders'][item.args]['titles']

    if records and type(records[0]) == list:
        js = []
        for record in records:
            js += record
    else:
        js = records

    for i, it in enumerate(js):
        if i < 20:
            items.append(it)
        else:
            recordlist.append(it)

    # itlist = [makeItem(i, it, item) for i, it in enumerate(items)]

    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(makeItem, i, it, item) for i, it in enumerate(items)]
        for res in futures.as_completed(itlist):
            if res.result():
                itemlist.append(res.result())

    itemlist.sort(key=lambda item: item.n)
    if not item.newest:
        item.mainThumb = item.thumbnail
        if recordlist:
            itemlist.append(item.clone(action='peliculas',title=support.typo(support.config.get_localized_string(30992), 'color std bold'), thumbnail=support.thumb(), page=page, records=recordlist))
        elif len(itemlist) >= 20:
            itemlist.append(item.clone(action='peliculas',title=support.typo(support.config.get_localized_string(30992), 'color std bold'), thumbnail=support.thumb(), records=[], page=page + 1))

    support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    support.check_trakt(itemlist)
    return itemlist


def makeItem(n, it, item):
    logger.debug(it)
    title = it['name']
    lang = 'Sub-ITA' if it.get('sub_ita', 0) == 1 else 'ITA'
    itm = item.clone(title=support.typo(title,'bold') + support.typo(lang,'_ [] color std bold'))
    itm.contentType = it['type'].replace('tv', 'tvshow')
    itm.language = lang
    
    # FIX ANNO - usa release_date invece di last_air_date
    if it.get('release_date'):
        itm.year = it['release_date'].split('-')[0]

    if itm.contentType == 'movie':
        # itm.contentType = 'movie'
        itm.fulltitle = itm.show = itm.contentTitle = title
        itm.action = 'findvideos'
        itm.url = host + '/it/watch/%s' % it['id']

    else:
        # itm.contentType = 'tvshow'
        itm.contentTitle = ''
        itm.fulltitle = itm.show = itm.contentSerieName = title
        itm.action = 'episodios'
        itm.season_count = it['seasons_count']
        itm.url = host + '/it/titles/%s-%s' % (it['id'], it['slug'])
    itm.n = n
    return itm


def episodios(item):
    # getHeaders()
    logger.debug()
    itemlist = []

    data_page = get_data(item.url)    
    seasons = data_page['props']['title']['seasons']
    # episodes = data_page['props']['loadedSeason']['episodes']
    # support.dbg()

    for se in seasons:
        data_page = get_data(item.url + '/season-' + str(se['number']))
        episodes = data_page['props']['loadedSeason']['episodes']

        for ep in episodes:
            itemlist.append(
                item.clone(title=support.typo(str(se['number']) + 'x' + str(ep['number']).zfill(2) + ' - ' + support.cleantitle(ep['name']), 'bold'),
                           episode=ep['number'],
                           season=se['number'],
                           contentSeason=se['number'],
                           contentEpisodeNumber=ep['number'],
                           thumbnail=ep['images'][0].get('original_url', item.thumbnail) if ep['images'] else item.thumbnail,
                           contentThumbnail=item.thumbnail,
                           fanart=item.fanart,
                           contentFanart=item.fanart,
                           plot=ep['plot'],
                           action='findvideos',
                           contentType='episode',
                           contentSerieName=item.fulltitle,
                           url='{}/it/iframe/{}?episode_id={}'.format(host, se['title_id'], ep['id'])))

    if config.get_setting('episode_info') and not support.stackCheck(['add_tvshow', 'get_newest']):
        support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    support.check_trakt(itemlist)
    support.videolibrary(itemlist, item)
    #support.download(itemlist, item)
    return itemlist


def findvideos(item):
    support.callAds('https://thaudray.com/5/3523301', host)

    itemlist = [item.clone(title=channeltools.get_channel_parameters(item.channel)['title'],
                           url=item.url.replace('/watch/', '/iframe/'), server='streamingcommunityws')]
    return support.server(item, itemlist=itemlist, referer=False)
