# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Mediaset Infinity
# ------------------------------------------------------------
import functools
import time
import re
import json
from platformcode import logger, config
import uuid, datetime, xbmc

import requests, sys
from core import jsontools, support, httptools

if sys.version_info[0] >= 3:
    from concurrent import futures
    from urllib.parse import urlencode, quote
else:
    from concurrent_py2 import futures
    from urllib import urlencode, quote

host = 'https://mediasetinfinity.mediaset.it'
loginUrl = 'https://api-ott-prod-fe.mediaset.net/PROD/play/idm/anonymous/login/v2.0'
recoUrl = 'https://api-ott-prod-fe.mediaset.net/PROD/play/reco/anonymous/v2.0'
clientid = 'f66e2a01-c619-4e53-8e7c-4761449dd8ee'

loginData = {"client_id": clientid, "platform": "pc", "appName": "web//mediasetplay-web/5.1.493-plus-da8885b"}

session = requests.Session()
session.request = functools.partial(session.request, timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT)
session.headers.update({
    'Content-Type': 'application/json',
    'User-Agent': support.httptools.get_user_agent(),
    'Referer': host
})

res = session.post(loginUrl, json=loginData, verify=False)
Token = res.json()['response']['beToken']
sid = res.json()['response']['sid']
session.headers.update({'authorization': 'Bearer ' + Token})

pagination = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100][config.get_setting('pagination', 'mediasetplay')]

feedBase = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-programs-v2'


@support.menu
def mainlist(item):
    top = [('Dirette {bold}', ['', 'live']),
           ('Replay {bold}', ['', 'restart'])]

    menu = [('Film ultimi arrivi {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmUltimiArrivi'}, 'movie']),
            ('Film più visti del giorno {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmPiuVisti24H'}, 'movie']),
            ('Film da non perdere {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmClustering'}, 'movie']),
            ('Fiction e Serie Tv del momento {submenu}', ['/fiction', 'peliculas', {'uxReference':'fictionSerieTvDelMomento'}, 'tvshow']),
            ('Soap del momento {submenu}', ['/cinema', 'peliculas', {'uxReference':'fictionSerieTvParamsGenre', 'params': 'genre≈Soap opera'}, 'tvshow']),
            ('Serie TV Piu Viste {submenu}', ['/fiction', 'peliculas', {'uxReference':'serieTvPiuViste24H'}, 'tvshow']),
            ('Programmi TV Prima serata{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniPrimaSerata'}, 'tvshow']),
            ('Programmi TV Daytime{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniDaytime'}, 'tvshow']),
            ('Talent e reality {submenu}', ['/talent', 'peliculas', {'uxReference':'multipleBlockProgrammiTv', 'userContext' :'iwiAeyJwbGF0Zm9ybSI6IndlYiJ9Aw'}, 'tvshow']),
            ('Kids Boing {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsBoing' }, 'undefined']),
            ('Kids Cartoonito {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsCartoonito' }, 'undefined']),
            ('Kids Evergreen {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsMediaset' }, 'undefined']),
            ('Documentari più visti {submenu}', ['/documentari', 'peliculas', {'uxReference': 'documentariPiuVisti24H'}, 'undefined']),
            ]

    search = ''
    return locals()


def live(item):
    itemlist = []

    epg_url = "https://api-ott-prod-fe.mediaset.net/PROD/play/feed/allListingFeedEpg/v2.0?byListingTime={0}~{0}&byCallSign={1}"
    res = session.get('https://static3.mediasetplay.mediaset.it/apigw/nownext/nownext.json').json()['response']
    allguide = res['listings']
    stations = res['stations']

    def find_high_res_image(arts, prefix):
        return max(
            (item for key, item in arts.items() if key.startswith(prefix)),
            key=lambda x: x.get('width', 0),
            default=None
        )
    
    def itArt(it):
        current_time_millis = int(time.time() * 1000)
        try:
            response = session.get(epg_url.format(current_time_millis, it['callSign'])).json()
            listings = response.get('response', {}).get('entries', [{}])[0].get('listings', [{}])
            for listing in listings:
                if listing['startTime'] < current_time_millis < listing['endTime']:
                    arts = listing.get('program', {}).get('thumbnails', {})
                    poster = find_high_res_image(arts, "image_horizontal_cover") or find_high_res_image(arts, "image_keyframe_poster")
                    it['fanart'] = poster.get('url', '')
                    break
        except:
            it['fanart'] = ""
    
    with futures.ThreadPoolExecutor() as executor:
        for it in stations.values():
            executor.submit(itArt, it)

    for it in stations.values():
        plot = ''
        title = it['title']
        url = 'https:' + it['mediasetstation$pageUrl']
        if 'SVOD' in it['mediasetstation$channelsRights']: continue
        thumb = it.get('thumbnails', {}).get('channel_logo-100x100', {}).get('url', '')

        if it['callSign'] in allguide:
            guide = allguide[it['callSign']]
            currentListing = guide.get('currentListing', {})
            programId = currentListing.get('programId', '')
            restart_contentId = programId.split('/')[-1] if programId else ''
            restart_title = currentListing.get('mediasetlisting$epgTitle', '')
            startTime = currentListing.get('startTime', '')
            endTime = currentListing.get('endTime', '')
            
            plot = '[B]{}[/B]\n{}'.format(
                currentListing.get('mediasetlisting$epgTitle', ''),
                currentListing.get('description', '')
            )
            if 'nextListing' in guide.keys():
                plot += '\n\nA Seguire:\n[B]{}[/B]\n{}'.format(
                    guide.get('nextListing', {}).get('mediasetlisting$epgTitle', ''),
                    guide.get('nextListing', {}).get('description', '')
                )
            
            itemlist.append(item.clone(
                title=support.typo(title, 'bold'),
                fulltitle=title,
                callSign=it['callSign'],
                plot=plot,
                url=url,
                action='findvideos',
                thumbnail=thumb,
                fanart=it.get('fanart', ''),
                forcethumb=True
            ))
            
            if restart_contentId and restart_title and startTime and endTime:
                itemlist.append(item.clone(
                    title=support.typo('{} - {}'.format(title, restart_title), 'bold'),
                    fulltitle='{} - {}'.format(title, restart_title),
                    plot=plot,
                    url=url + '?restart',
                    action='findvideos',
                    thumbnail=thumb,
                    fanart=it.get('fanart', ''),
                    forcethumb=True,
                    restart=True,
                    restart_contentId=restart_contentId,
                    restart_startTime=str(startTime),
                    restart_endTime=str(endTime),
                    callSign=it['callSign']
                ))

    itemlist.sort(key=lambda it: support.channels_order.get(it.fulltitle, 999))
    support.thumb(itemlist, live=True)
    return itemlist


def restart(item):
    itemlist = []
    live_items = live(item)
    for it in live_items:
        try:
            if it.restart_contentId:
                itemlist.append(it)
        except:
            pass
    return itemlist


def search(item, text):
    item.args = {'query': text}
    try:
        return peliculas(item)
    except:
        return []


def peliculas(item):
    itemlist = []
    
    search_text = item.args.get('query', '')
    page = item.page if item.page else 1
    
    if search_text:
        params = {
            'uxReference': 'filteredSearch',
            'query': search_text,
            'context': 'platform≈web',
            'sid': sid,
            'sessionId': sid,
            'hitsPerPage': pagination,
            'property': 'search',
            'tenant': 'play-prod-v2',
            'page': page
        }
    else:
        ux_ref = item.args.get('uxReference', 'filmPiuVisti24H')
        extra_params = item.args.get('params', '')
        user_context = item.args.get('userContext', '')
        
        params = {
            'uxReference': ux_ref,
            'context': 'platform≈web',
            'sid': sid,
            'sessionId': sid,
            'hitsPerPage': pagination,
            'property': 'play',
            'tenant': 'play-prod-v2',
            'page': page
        }
        
        if extra_params:
            params['params'] = extra_params
        
        if user_context:
            params['userContext'] = user_context
    
    res = session.get(recoUrl + '?' + urlencode(params)).json()
    
    blocks = res.get('response', {}).get('blocks', [])
    items = []
    for block in blocks:
        items.extend(block.get('items', []))
    
    if search_text and not items:
        for offset in range(0, 500, 100):
            feed_url = f'{feedBase}?range={offset+1}-{offset+100}&sort=:publishInfo_lastPublished|desc'
            try:
                feed_res = requests.get(feed_url).json()
                all_entries = feed_res.get('entries', [])
                items.extend([e for e in all_entries if search_text.lower() in e.get('title', '').lower()])
                if len(all_entries) < 100:
                    break
            except:
                break
        items = items[:pagination]
    
    for it in items:
        if not 'MediasetPlay_ANY' in it.get('mediasetprogram$channelsRights', ['MediasetPlay_ANY']):
            continue
        
        thumb = ''
        fanart = ''
        
        title = it.get('mediasetprogram$brandTitle', it.get('title', ''))
        title2 = it.get('title', '')
        if title and title2 and title != title2:
            title = '{} - {}'.format(title, title2)
        
        plot = it.get('longDescription', it.get('description', ''))
        url = 'https:' + it.get('mediasettvseason$pageUrl', it.get('mediasetprogram$videoPageUrl', it.get('mediasetprogram$pageUrl', '')))
        
        if it.get('seriesTitle') or it.get('seriesTvSeasons'):
            contentSerieName = it.get('seriesTitle', it.get('title', ''))
            contentType = 'tvshow'
            action = 'epmenu'
            video_id = ''
        else:
            contentType = 'movie'
            action = 'findvideos'
            video_id = it.get('guid', '')
            contentSerieName = ''
        
        for k, v in it.get('thumbnails', {}).items():
            if 'image_vertical' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
            if 'image_header_poster' in k and not fanart:
                fanart = v['url'].replace('.jpg', '@3.jpg')
        
        itemlist.append(item.clone(
            title=support.typo(title, 'bold'),
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
            seriesid=it.get('seriesTvSeasons', it.get('id', '')),
            disable_videolibrary=True,
            forcethumb=True
        ))
    
    pagination_data = res.get('response', {}).get('pagination', {})
    if pagination_data.get('hasNextPage'):
        item.page = page + 1
        support.nextPage(itemlist, item)
    
    return itemlist


def epmenu(item):
    itemlist = []
    epUrl = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-subbrands-v2?byTvSeasonId={}&sort=mediasetprogram$order'

    if item.seriesid:
        if type(item.seriesid) == list:
            for s in item.seriesid:
                itemlist.append(
                    item.clone(seriesid=s['id'],
                               title=support.typo(s['title'], 'bold')))
            if len(itemlist) == 1: return epmenu(itemlist[0])
        else:
            res = requests.get(epUrl.format(item.seriesid)).json()['entries']
            for it in res:
                itemlist.append(
                    item.clone(seriesid='',
                               title=support.typo(it['description'], 'bold'),
                               subbrand=it['mediasetprogram$subBrandId'],
                               action='episodios'))
            itemlist = sorted(itemlist, key=lambda it: it.title, reverse=True)
            if len(itemlist) == 1: return episodios(itemlist[0])

    return itemlist


def episodios(item):
    months = []
    try:
        for month in range(21, 33): months.append(xbmc.getLocalizedString(month))
    except:
        for month in range(21, 33): months.append('dummy')

    order = 'desc' if '/programmi-tv/' in item.url else 'asc'

    itemlist = []
    res = requests.get(
        f'{feedBase}?byCustomValue={{subBrandId}}{{{item.subbrand}}}&range=0-10000&sort=:publishInfo_lastPublished|{order},tvSeasonEpisodeNumber'
    ).json()['entries']

    for it in res:
        thumb = ''
        titleDate = ''
        if 'mediasetprogram$publishInfo_lastPublished' in it:
            date = datetime.date.fromtimestamp(it['mediasetprogram$publishInfo_lastPublished'] / 1000)
            titleDate = '  [{} {}]'.format(date.day, months[date.month - 1])
        title = '[B]{}[/B]{}'.format(it['title'], titleDate)
        for k, v in it['thumbnails'].items():
            if 'image_keyframe' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
                break
        if not thumb: thumb = item.thumbnail

        itemlist.append(item.clone(
            title=title,
            thumbnail=thumb,
            forcethumb=True,
            contentType='episode',
            action='findvideos',
            video_id=it['guid']
        ))

    return itemlist


def findvideos(item):
    logger.debug()
    item.no_return = True
    
    lic_url = 'https://widevine.entitlement.theplatform.eu/wv/web/ModularDrm/getRawWidevineLicense?releasePid={pid}&account=http://access.auth.theplatform.com/data/Account/2702976343&schema=1.0&token={token}|Accept=*/*&Content-Type=&User-Agent={ua}|R{{SSM}}|'

    is_restart = getattr(item, 'restart', False)
    callSign = getattr(item, 'callSign', None)
    restart_startTime = getattr(item, 'restart_startTime', None)
    restart_endTime = getattr(item, 'restart_endTime', None)
    
    if is_restart and callSign:
        payload = {
            "channelCode": callSign,
            "streamType": "RESTART",
            "delivery": "Streaming",
            "createDevice": "true",
            "overrideAppName": "web//mediasetplay-web/5.2.4-6ad16a4"
        }
        
        if restart_startTime and restart_endTime:
            payload["startTime"] = int(restart_startTime)
            payload["endTime"] = int(restart_endTime)
        
        try:
            res = session.post(
                f'https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid={sid}',
                json=payload
            ).json()
            
            if 'response' in res:
                mediaSelector = res['response']['mediaSelector']
                url = mediaSelector['url']
                is_mpd = 'dash' in mediaSelector['formats'].lower()
                
                sec_data = support.match(url + '?' + urlencode(mediaSelector)).data
                item.url = support.match(sec_data, patron=r'<video src="([^"]+)').match + '|User-Agent=' + support.httptools.get_user_agent()
                pid = support.match(sec_data, patron=r'pid=([^|]+)').match
                
                if is_mpd and pid:
                    item.manifest = 'mpd'
                    item.drm = 'com.widevine.alpha'
                    item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())
                else:
                    item.manifest = 'hls'
                
                return support.server(item, itemlist=[item], Download=False, Videolibrary=False)
        except:
            pass
        return []
    
    if getattr(item, 'video_id', None):
        payload = {
            "contentId": item.video_id,
            "streamType": "VOD",
            "delivery": "Streaming",
            "createDevice": "true",
            "overrideAppName": "web//mediasetplay-web/5.2.4-6ad16a4"
        }
        res = session.post(
            f'https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid={sid}',
            json=payload
        ).json()['response']['mediaSelector']
    elif callSign:
        payload = {
            "channelCode": callSign,
            "streamType": "LIVE",
            "delivery": "Streaming",
            "createDevice": "true",
            "overrideAppName": "web//mediasetplay-web/5.2.4-6ad16a4"
        }
        res = session.post(
            f'https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid={sid}',
            json=payload
        ).json()['response']['mediaSelector']
    else:
        return []

    url = res['url']
    is_mpd = 'dash' in res['formats'].lower()

    if url:
        sec_data = support.match(url + '?' + urlencode(res)).data
        item.url = support.match(sec_data, patron=r'<video src="([^"]+)').match + '|User-Agent=' + support.httptools.get_user_agent()
        pid = support.match(sec_data, patron=r'pid=([^|]+)').match

        if is_mpd and pid:
            item.manifest = 'mpd'
            item.drm = 'com.widevine.alpha'
            item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())
        else:
            item.manifest = 'hls'

        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)

    return []