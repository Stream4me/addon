# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per StreamingCommunity
# ------------------------------------------------------------

import json, re, sys, unicodedata 
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

host = support.config.get_channel_url()


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


def _norm(s):
    s = unicodedata.normalize('NFKD', s or u'')
    s = s.encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _pick_tmdb_tv(title, site_year):
    try:
        from lib.fuzzy_match import algorithims
        results = support.tmdb.Tmdb(searched_text=title, search_type='tv').results
    except Exception:
        return None
    if not results:
        return None

    text = title.lower()
    best, best_score = None, 0
    for r in results:
        names = [n for n in (r.get('name'), r.get('original_name')) if n]
        score = max([algorithims.trigram(text, n) for n in names] or [0])
        if any(_norm(n) == _norm(title) for n in names):
            score += 1.0                                  
        fa = (r.get('first_air_date') or '')[:4]
        if site_year and fa.isdigit():
            diff = site_year - int(fa)                    
            score += (0.3 - 0.05 * diff) if 0 <= diff <= 6 else -0.3
        score += min((r.get('popularity') or 0) / 500.0, 0.2)
        if score > best_score:
            best, best_score = r, score

    return best.get('id') if best is not None and best_score >= 0.6 else None


def makeItem(n, it, item):
    logger.debug(it)
    title = it['name']
    lang = 'Sub-ITA' if it.get('sub_ita', 0) == 1 else 'ITA'

    itm = item.clone(title=support.typo(title, 'bold') + support.typo(lang, '_ [] color std bold'))
    itm.contentType = it['type'].replace('tv', 'tvshow')
    itm.language = lang

    year_str = (it.get('release_date') or
                next((tr['value'] for tr in it.get('translations', [])
                      if tr.get('key') == 'release_date' and tr.get('value')), None))
    site_year = None
    if year_str:
        try:
            site_year = int(str(year_str)[:4])
            itm.year = site_year
        except:
            pass

    if itm.contentType == 'movie':
        itm.fulltitle = itm.show = itm.contentTitle = title
        itm.action = 'findvideos'
        itm.url = host + '/it/watch/%s' % it['id']
    else:
        itm.contentTitle = ''
        itm.fulltitle = itm.show = itm.contentSerieName = title
        itm.action = 'episodios'
        itm.season_count = it['seasons_count']
        itm.url = host + '/it/titles/%s-%s' % (it['id'], it['slug'])

        if config.get_setting('tmdb_active'):
            tmdb_id = _pick_tmdb_tv(title, site_year)
            if tmdb_id:
                itm.infoLabels['tmdb_id'] = str(tmdb_id)

    itm.n = n
    return itm


def episodios(item):
    logger.debug()
    itemlist = []

    data_page = get_data(item.url)    
    seasons = data_page['props']['title']['seasons']

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
    return itemlist


def findvideos(item):
    support.callAds('https://thaudray.com/5/3523301', host)

    itemlist = [item.clone(title=channeltools.get_channel_parameters(item.channel)['title'],
                           url=item.url.replace('/watch/', '/iframe/'), server='streamingcommunityws')]
    return support.server(item, itemlist=itemlist, referer=False)