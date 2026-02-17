# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Mediaset Play
# ------------------------------------------------------------
import functools

from platformcode import logger, config
import uuid, datetime, xbmc

import requests, sys
from core import jsontools, support, httptools

if sys.version_info[0] >= 3:
    from urllib.parse import urlencode, quote
else:
    from urllib import urlencode, quote

host = 'https://www.mediasetplay.mediaset.it'
loginUrl = 'https://api-ott-prod-fe.mediaset.net/PROD/play/idm/anonymous/login/v2.0'

clientid = 'f66e2a01-c619-4e53-8e7c-4761449dd8ee'


loginData = {"client_id": clientid, "platform": "pc", "appName": "web//mediasetplay-web/5.1.493-plus-da8885b"}
sessionUrl = "https://api.one.accedo.tv/session?appKey=59ad346f1de1c4000dfd09c5&uuid={uuid}&gid=default"

session = requests.Session()
session.request = functools.partial(session.request, timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT)
session.headers.update({'Content-Type': 'application/json', 'User-Agent': support.httptools.get_user_agent(), 'Referer': host})

entry = 'https://api.one.accedo.tv/content/entry/{id}?locale=it'
entries = 'https://api.one.accedo.tv/content/entries?id={id}&locale=it'

# login anonimo
res = session.post(loginUrl, json=loginData, verify=False)
Token = res.json()['response']['beToken']
sid = res.json()['response']['sid']
session.headers.update({'authorization': 'Bearer ' + Token})

# sessione
#sessionKey = session.get(sessionUrl.format(uuid=str(uuid.uuid4())), verify=False).json()['sessionKey']
#session.headers.update({'x-session': sessionKey})

pagination = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100][config.get_setting('pagination', 'mediasetplay')]


@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live'])]

    menu = [('Film Più Visti {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmPiuVisti24H'}, 'movie']),
            ('Film ultimi arrivi {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmUltimiArrivi'}, 'movie']),
            ('Film Da Non Perdere {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmClustering'}, 'movie']),
            ('Fiction e Serie Tv del momento {submenu}', ['/fiction', 'peliculas', {'uxReference':'fictionSerieTvDelMomento'}, 'tvshow']),
            ('Serie TV Piu Viste {submenu}', ['/fiction', 'peliculas', {'uxReference':'serieTvPiuViste24H'}, 'tvshow']),
            ('Soap del momento {submenu}', ['/cinema', 'peliculas', {'uxReference':'fictionSerieTvParamsGenre', 'params': 'genre≈Soap opera'}, 'tvshow']),
            ('Programmi TV Prima serata{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniPrimaSerata'}, 'tvshow']),
            ('Programmi TV Daytime{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniDaytime'}, 'tvshow']),
	    ('Talent e reality {submenu}', ['/talent', 'peliculas', {'uxReference':'multipleBlockProgrammiTv', 'userContext' :'iwiAeyJwbGF0Zm9ybSI6IndlYiJ9Aw'}, 'tvshow']),
            ('Kids Evergreen {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsMediaset' }, 'undefined']),
            ('Kids Boing {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsBoing' }, 'undefined']),
            ('Kids Cartoonito {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsCartoonito' }, 'undefined']),
            ('Documentari più visti {submenu}', ['/documentari', 'peliculas', {'uxReference': 'documentariPiuVisti24H'}, 'undefined']),
            ]

    search = ''
    return locals()

def menu(item):
    logger.debug()
    itemlist = []
    res = get_from_id(item)
    for it in res:
        if 'uxReference' in it:
            itemlist.append(item.clone(title=support.typo(it['title'], 'bullet bold'),
                            url= it['landingUrl'],
                            args={'uxReference':it.get('uxReferenceV2', ''), 'params':it.get('uxReferenceV2Params', ''), 'feed':it.get('feedurlV2','')},
                            action='peliculas'))
    return itemlist


def live(item):
    itemlist = []

    res = session.get('https://static3.mediasetplay.mediaset.it/apigw/nownext/nownext.json').json()['response']
    allguide = res['listings']
    stations = res['stations']

    for it in stations.values():
        logger.debug(jsontools.dump(it))
        plot = ''
        title = it['title']
        url = 'https:' + it['mediasetstation$pageUrl']
        if 'SVOD' in it['mediasetstation$channelsRights']: continue
        thumb = it.get('thumbnails',{}).get('channel_logo-100x100',{}).get('url','')
        if it['callSign'] in allguide:

            guide = allguide[it['callSign']]
            plot = '[B]{}[/B]\n{}'.format(guide.get('currentListing', {}).get('mediasetlisting$epgTitle', ''),guide.get('currentListing', {}).get('description', ''))
            if 'nextListing' in guide.keys():
                plot += '\n\nA Seguire:\n[B]{}[/B]\n{}'.format(guide.get('nextListing', {}).get('mediasetlisting$epgTitle', ''),guide.get('nextListing', {}).get('description', ''))
            itemlist.append(item.clone(title=support.typo(title, 'bold'),
                                       fulltitle=title, callSign=it['callSign'],
                                    #    urls=[guide['publicUrl']],
                                       plot=plot,
                                       url=url,
                                       action='findvideos',
                                       thumbnail=thumb,
                                       forcethumb=True))

    itemlist.sort(key=lambda it: support.channels_order.get(it.fulltitle, 999))
    support.thumb(itemlist, live=True)
    return itemlist


def search(item, text):
    item.args = {'uxReference':'main', 'params':'channel≈', 'query':text}

    try:
        return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)
        return []


def peliculas(item):
    itemlist = []
    res = get_programs(item)
    video_id= ''

    for it in res['items']:
        if not 'MediasetPlay_ANY' in it.get('mediasetprogram$channelsRights',['MediasetPlay_ANY']): continue
        thumb = ''
        fanart = ''
        contentSerieName = ''
        url = 'https:'+ it.get('mediasettvseason$pageUrl', it.get('mediasetprogram$videoPageUrl', it.get('mediasetprogram$pageUrl')))
        title = it.get('mediasetprogram$brandTitle', it.get('title'))
        title2 = it['title']
        if title != title2:
            title = '{} - {}'.format(title, title2)
        plot = it.get('longDescription', it.get('description', it.get('mediasettvseason$brandDescription', '')))

        if it.get('seriesTitle') or it.get('seriesTvSeasons'):
            contentSerieName = it.get('seriesTitle', it.get('title'))
            contentType = 'tvshow'
            action = 'epmenu'
        else:
            contentType = 'movie'
            video_id = it['guid']
            action = 'findvideos'
        for k, v in it['thumbnails'].items():
            if 'image_vertical' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
            if 'image_header_poster' in k and not fanart:
                fanart = v['url'].replace('.jpg', '@3.jpg')
            if thumb and fanart:
                break

        itemlist.append(item.clone(title=support.typo(title, 'bold'),
                                   fulltitle=title,
                                   contentTitle=title,
                                   contentSerieName=contentSerieName,
                                   action=action,
                                   contentType=contentType,
                                   thumbnail=thumb,
                                   fanart=fanart,
                                   plot=plot,
                                   url=url,
                                   video_id=video_id,
                                   seriesid = it.get('seriesTvSeasons', it.get('id','')),
                                   disable_videolibrary = True,
                                   forcethumb=True))
    if res['next']:
        item.page = res['next']
        support.nextPage(itemlist, item)

    return itemlist

def epmenu(item):
    logger.debug()
    itemlist = []

    epUrl = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-subbrands-v2?byTvSeasonId={}&sort=mediasetprogram$order'

    if item.seriesid:
        if type(item.seriesid) == list:
            res = []
            for s in item.seriesid:
                itemlist.append(
                    item.clone(seriesid = s['id'],
                               title=support.typo(s['title'], 'bold')))
            if len(itemlist) == 1: return epmenu(itemlist[0])
        else:
            res = requests.get(epUrl.format(item.seriesid)).json()['entries']
            for it in res:
                itemlist.append(
                    item.clone(seriesid = '',
                               title=support.typo(it['description'], 'bold'),
                               subbrand=it['mediasetprogram$subBrandId'],
                               action='episodios'))
            itemlist = sorted(itemlist, key=lambda it: it.title, reverse=True)
            if len(itemlist) == 1: return episodios(itemlist[0])

    return itemlist

def episodios(item):
    # create month list
    months = []
    try:
        for month in range(21, 33): months.append(xbmc.getLocalizedString(month))
    except:  # per i test, xbmc.getLocalizedString non è supportato
        for month in range(21, 33): months.append('dummy')

    # i programmi tv vanno ordinati per data decrescente, gli episodi delle serie per data crescente
    order = 'desc' if '/programmi-tv/' in item.url else 'asc'

    itemlist = []
    res = requests.get('https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-programs-v2?byCustomValue={subBrandId}{' + item.subbrand +'}&range=0-10000&sort=:publishInfo_lastPublished|' + order + ',tvSeasonEpisodeNumber').json()['entries']

    for it in res:
        thumb = ''
        titleDate = ''
        if 'mediasetprogram$publishInfo_lastPublished' in it:
            date = datetime.date.fromtimestamp(it['mediasetprogram$publishInfo_lastPublished'] / 1000)
            titleDate ='  [{} {}]'.format(date.day, months[date.month-1])
        title = '[B]{}[/B]{}'.format(it['title'], titleDate)
        for k, v in it['thumbnails'].items():
            if 'image_keyframe' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
                break
        if not thumb: thumb = item.thumbnail

        itemlist.append(item.clone(title=title,
                                   thumbnail=thumb,
                                   forcethumb=True,
                                   contentType='episode',
                                   action='findvideos',
                                   video_id=it['guid']))

    return itemlist


def findvideos(item):
    logger.debug()
    item.no_return=True
    # support.dbg()
    mpd = config.get_setting('mpd', item.channel)


    lic_url = 'https://widevine.entitlement.theplatform.eu/wv/web/ModularDrm/getRawWidevineLicense?releasePid={pid}&account=http://access.auth.theplatform.com/data/Account/2702976343&schema=1.0&token={token}|Accept=*/*&Content-Type=&User-Agent={ua}|R{{SSM}}|'
    url = ''
    # support.dbg()
    if item.urls:
        url = ''
        pid = ''
        # Format = 'dash+xml' if mpd else 'x-mpegURL'
        # for it in item.urls:
        #     if Format in it['format']:
        item.url = requests.head(item.urls[0], headers={'User-Agent': support.httptools.get_user_agent()}).headers['Location']
        # pid = it['releasePids'][0]
        # if mpd and 'widevine' in it['assetTypes']:
        #     break

        if mpd:
            item.manifest = 'mpd'
            item.drm = 'com.widevine.alpha'
            item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())

        else:
            item.manifest = 'hls'
        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)

    elif item.video_id:
        payload = {"contentId":item.video_id, "streamType":"VOD", "delivery":"Streaming", "createDevice":"true", "overrideAppName":"web//mediasetplay-web/5.2.4-6ad16a4"}
        res = session.post('https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid=' + sid, json=payload).json()['response']['mediaSelector']

    else:
        payload = {"channelCode":item.callSign, "streamType":"LIVE", "delivery":"Streaming", "createDevice":"true", "overrideAppName":"web//mediasetplay-web/5.2.4-6ad16a4"}
        res = session.post('https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid=' + sid, json=payload).json()['response']['mediaSelector']

    url = res['url']
    mpd = True if 'dash' in res['formats'].lower() else False

    if url:

        sec_data = support.match(url + '?' + urlencode(res)).data
        item.url = support.match(sec_data, patron=r'<video src="([^"]+)').match  + '|User-Agent=' + support.httptools.get_user_agent()
        pid = support.match(sec_data, patron=r'pid=([^|]+)').match

        if mpd and pid:
            item.manifest = 'mpd'
            item.drm = 'com.widevine.alpha'
            item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())
        else:
            item.manifest = 'hls'

        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)


def get_from_id(item):
    #sessionKey = session.get(sessionUrl.format(uuid=str(uuid.uuid4())), verify=False).json()['sessionKey']
    #session.headers.update({'x-session': sessionKey})
    res = session.get(entry.format(id=item.args)).json()
    if 'components' in res:
        id = quote(",".join(res["components"]))
        res = session.get(entries.format(id=id)).json()
    if 'entries' in res:
        return res['entries']
    return {}

def get_programs(item):
    url = ''
    pag = item.page if item.page else 1
    ret = {}

    if item.args.get('feed'):
        pag = item.page if item.page else 1
        url='{}&range={}-{}'.format(item.args.get('feed'), pag, pag + pagination - 1)
        ret['next'] = pag + pagination
        res = requests.get(url).json()

    else:
        args = {key:value for key, value in item.args.items()}
        args['context'] = 'platform≈web'
        args['sid'] = sid
        args['sessionId'] = sid
        args['hitsPerPage'] = pagination
        args['property'] = 'search' if args.get('query') else 'play'
        args['tenant'] = 'play-prod-v2'
        args['page'] = pag
        args['deviceId'] = '017ac511182d008322c989f3aac803083002507b00bd0'
        url="https://api-ott-prod-fe.mediaset.net/PROD/play/reco/anonymous/v2.0?" + urlencode(args)

        res = session.get(url).json()

    if res:
        res = res.get('response', res)
        if 'entries' in res:
            ret['items'] = res['entries']
        elif 'blocks' in res:
            items = []
            for block in res['blocks']:
                items += block['items']
            ret['items'] = items
        if not 'next' in ret:
            next = res.get('pagination',{}).get('hasNextPage', False)
            ret['next'] = pag + 1 if next else 0
    return ret






