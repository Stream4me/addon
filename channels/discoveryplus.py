# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Discovery Plus
# ------------------------------------------------------------
import functools

import requests, uuid
from core import jsontools, support, httptools
from platformcode import logger, config


typo = support.typo
session = requests.Session()
session.request = functools.partial(session.request, timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT)
host = support.config.get_channel_url()
deviceId = uuid.uuid4().hex

# domain = 'https://eu1-prod-direct.discoveryplus.com'
domain = 'https://' + session.get("https://prod-realmservice.mercury.dnitv.com/realm-config/www.discoveryplus.com%2Fit%2Fepg").json()["domain"]
token = session.get('{}/token?deviceId={}&realm=dplay&shortlived=true'.format(domain, deviceId)).json()['data']['attributes']['token']
session.headers = {'User-Agent': httptools.get_user_agent(), #'Mozilla/50.0 (Windows NT 10.0; WOW64; rv:45.0) Gecko/20100101 Firefox/45.0',
                   'Referer': host,
                   'Origin': host,
                   'Cookie': 'st={}'.format(token),
                   'content-type': 'application/json',
                   'x-disco-client': 'WEB:UNKNOWN:dplus_us:2.46.0',
                   'x-disco-params': 'realm=dplay,siteLookupKey=dplus_it'}

@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live']),
            ('Programmi {bullet bold tv}', ['', 'programs', 'programmi'])]

    search = ''

    return locals()


def search(item, text):
    itemlist = []

    item.text = text

    try:
        itemlist = peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            logger.error(line)

    return itemlist


def live(item):
    logger.debug()

    itemlist =[]
    # data = session.get(domain + '/cms/routes/epg?include=default').json()['included']
    data = session.get(domain + '/cms/routes/home?include=default&decorators=playbackAllowed').json()['included']

    for key in data:

        if key['type'] == 'channel' and key.get('attributes',{}).get('hasLiveStream', '') and 'Free' in key.get('attributes',{}).get('packages', []):
            itemlist.append(item.clone(title = typo(key['attributes']['name'], 'bold'),
                                       fulltitle = key['attributes']['name'],
                                       plot = key['attributes'].get('description', ''),
                                       url = "{}/canali/{}".format(host, key['attributes']['alternateId']),
                                       id = key['id'],
                                       action = 'findvideos'))
    return support.thumb(itemlist, live=True)


def programs(item):
    logger.debug()

    itemlist = []
    data = session.get(domain + '/cms/routes/browse?include=default').json()['included']
    images = {key['id'] : key['attributes']['src'] for key in data if key['type'] == 'image'}

    channels = {}
    for key in data:
        if key['type'] == 'link' and 'Free' in key['attributes']['packages']:
            logger.debug(jsontools.dump(key))
            _title = key['attributes'].get('title', key['attributes'].get('name',''))
            _id = key['relationships']['linkedContent']['data']['id']
            _thumb = images.get(key['relationships'].get('images', {}).get('data',[{}])[0].get('id'))
            channels[_title] ={'id':_id, 'thumb':_thumb}

    itemlist = [item.clone(title='Tutti', id=channels['Tutti']['id'], action='peliculas'),
                item.clone(title='Generi', id=channels['Tutti']['id'], action='genres'),
                item.clone(title='Per canale', channels=channels, action='channels')]

    return support.thumb(itemlist)


def genres(item):
    logger.debug()

    itemlist = []
    data = session.get('{}/cms/collections/{}?include=default'. format(domain, item.id)).json()['included']
    collection = {k['id']: k['relationships'].get('show', k['relationships'].get('collection'))['data']['id'] for k in data if k['type'] == 'collectionItem'}

    included = {}
    for key in data:
        if key.get('relationships', {}).get('items') and key['type'] == 'collection' and key['attributes']['title'] not in ['A-Z', 'I più visti']:
            included[key['attributes']['title']] = [k['id'] for k in key['relationships']['items']['data']]

    for title, values in included.items():
        itemlist.append(item.clone(title=title, action='peliculas', filter=[collection[k] for k in values]))

    itemlist.sort(key=lambda it: it.title)

    return support.thumb(itemlist, genre=True)


def channels(item):
    logger.debug()

    itemlist = [item.clone(title=k, id=v['id'], thumbnail=v['thumb'], action='peliculas') for k, v in item.channels.items() if k !='Tutti']
    itemlist.sort(key=lambda it: it.title)

    return itemlist


def peliculas(item):
    logger.debug()

    itemlist =[]

    if item.text:
        data = session.get('{}/cms/routes/search/result?include=default&contentFilter[query]={}'.format(domain, item.text)).json()['included']
    else:
        data = session.get('{}/cms/collections/{}?include=default'.format(domain, item.id)).json()['included']

    images = {key['id'] : key['attributes']['src'] for key in data if key['type'] == 'image'}

    for key in data:
        if key['type'] == 'show' and 'Free' in str(key.get('relationships',{}).get('contentPackages',{}).get('data',[])) and key['attributes']['episodeCount']:

            if item.filter and key['id'] not in item.filter:
                continue

            thumbId = key['relationships'].get('images',{}).get('data', [{},{},{}])[2].get('id', '')
            fanartId = key['relationships'].get('images',{}).get('data', [{}])[0].get('id', '')
            itemlist.append(
                item.clone(title=typo(key['attributes']['name'],'bold'),
                           plot=key['attributes'].get('description',''),
                           programid=key['attributes']['alternateId'],
                           seasons=key['attributes']['seasonNumbers'],
                           action='seasons',
                           thumbnail=images[thumbId] if thumbId else item.thumbnail,
                           fanart=images[fanartId] if fanartId else item.fanart,
                           contentType='tvshow'))

    itemlist.sort(key=lambda it: it.title)

    if not itemlist:
        from core.item import Item
        itemlist = [Item(title='Nessun Contenuto Free Disponibile', thumbnail=support.thumb('info'))]

    return itemlist


def seasons(item):
    logger.debug()

    itemlist = []
    data = session.get('{}/cms/routes/show/{}?include=default'.format(domain, item.programid)).json()['included']

    for key in data:
        if key['type'] == 'collection' and 'filters' in key['attributes']['component']:
            for option in key['attributes']['component']['filters'][0]['options']:
                itemlist.append(item.clone(title="Stagione {}".format(option['value']),
                                           season=int(option['value']),
                                           seasonparams=option['parameter'],
                                           showparams=key['attributes']['component']['mandatoryParams'],
                                           id=key['id'],
                                           contentType='season',
                                           action='episodios'))
            break

        if key['type'] == 'collection' and 'title' in key['attributes']:
            itemlist.append(
                item.clone(title=typo(key['attributes']['title'],'bold'),
                           plot=key['attributes'].get('description',''), 
                           programid=key['attributes']['alias'],
                           id=key['id'],
                           action='episodios',
                           contentType='season'))

    return itemlist


def episodios(item):
    logger.debug()

    itemlist =[]
    data = session.get('{}/cms/collections/{}?include=default&{}&{}'.format(domain, item.id, item.seasonparams, item.showparams)).json()['included']
    images = {key['id'] : key['attributes']['src'] for key in data if key['type'] == 'image'}

    for key in data:
        if key['type'] == 'video' and 'Free' in str(key.get('relationships',{}).get('contentPackages',{}).get('data',[])):
            if item.season:
                itemlist.append(item.clone(title = "{}x{:02d} - {}".format(item.season, key['attributes']['episodeNumber'], key['attributes']['name']),
                                       plot = key['attributes']['description'],
                                       episode = key['attributes']['episodeNumber'],
                                       contentType = 'episode',
                                       action = 'findvideos',
                                       thumbnail = images[key['relationships']['images']['data'][0]['id']],
                                       id=key['id']))
            else:
                itemlist.append(item.clone(title = key['attributes']['name'],
                                       plot = key['attributes']['longDescription'],
                                       contentType = 'episode',
                                       action = 'findvideos',
                                       thumbnail = images[key['relationships']['images']['data'][0]['id']],
                                       id=key['id']))

    itemlist.sort(key=lambda it: it.episode)

    if not itemlist:
        from core.item import Item
        itemlist = [Item(title='Nessun Episodio Free Disponibile', thumbnail=support.thumb('info'))]

    return itemlist


def findvideos(item):
    logger.debug()

    content = 'video' if item.contentType == 'episode' else 'channel'

    post =  {content + 'Id': item.id,
            'deviceInfo': {
                'adBlocker': 'true',
                'drmSupported': 'true',
                'hwDecodingCapabilities': [],
                'screen':{
                    'width':1920,
                    'height':1080
                },
                'player':{
                    'width':1920,
                    'height':1080
                }
            },
            'wisteriaProperties':{
                'advertiser': {
                    'firstPlay': 0,
                    'fwIsLat': 0
                },
                'device':{
                    'browser':{
                        'name': 'chrome',
                        'version': config.get_setting("chrome_ua_version")
                    },
                    'type': 'desktop'
                },
                'platform': 'desktop',
                'product': 'dplus_emea',
                'sessionId': deviceId,
                'streamProvider': {
                    'suspendBeaconing': 0,
                    'hlsVersion': 6,
                    'pingConfig': 1
                }
            }
        }

    data = session.post('{}/playback/v3/{}PlaybackInfo'.format(domain, content), json=post).json().get('data',{}).get('attributes',{})
    if data.get('streaming', [{}])[0].get('protection', {}).get('drmEnabled',False):
        item.url = data['streaming'][0]['url']
        item.drm = 'com.widevine.alpha'
        item.license ="{}|PreAuthorization={}|R{{SSM}}|".format(data['streaming'][0]['protection']['schemes']['widevine']['licenseUrl'],
	                      data['streaming'][0]['protection']['drmToken'])
    else:
        item.url = data['streaming'][0]['url']
        item.manifest = 'hls'

    return support.server(item, itemlist=[item], Download=False, Videolibrary=False)
