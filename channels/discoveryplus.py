# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Rai Play
# ------------------------------------------------------------

import requests
from core import support, jsontools
from platformcode import logger, config
typo = support.typo
session = requests.Session()
host = support.config.get_channel_url()

def getToken():
    token = config.get_setting('token', 'discoveryplus', None)
    if not token:
        token = session.get('https://disco-api.discoveryplus.it/token?realm=dplayit').json()['data']['attributes']['token']
        config.set_setting('token', token, 'discoveryplus')
    return token

token = getToken()

api = "https://disco-api.discoveryplus.it"
headers = {'User-Agent': 'Mozilla/50.0 (Windows NT 10.0; WOW64; rv:45.0) Gecko/20100101 Firefox/45.0',
           'Referer': host,
           'Cookie' : 'st=' + token}

def Dict(item):
    global pdict
    pdict = session.get(api + '/cms/routes/{}?decorators=viewingHistory&include=default'.format(item.args), headers=headers).json()['included']


@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live']),
            ('Programmi {bullet bold tv}', ['', 'peliculas', 'programmi']),
            ('Generi {bullet bold tv}', ['', 'genres'])]

    search = ''

    return locals()


def liveDict():
    livedict = {}
    for key in session.get(api + '/cms/routes/home?decorators=viewingHistory&include=default', headers=headers).json()['included']:
        if key['type'] == 'channel' and key.get('attributes',{}).get('hasLiveStream', '') and 'Free' in key.get('attributes',{}).get('packages', []):
            title = key['attributes']['name']
            livedict[title] = {}
            livedict[title]['plot'] = key['attributes']['description']
            livedict[title]['url'] = '{}/canali/{}'.format(host, key['attributes']['alternateId'])
            livedict[title]['id'] = key['id']
    return livedict


def search(item, text):
    itemlist = []
    item.args = 'search'
    item.text = text
    try:
        itemlist = peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)

    return itemlist


def live(item):
    logger.debug()
    itemlist =[]
    for name, values in liveDict().items():
        itemlist.append(item.clone(title=typo(name,'bold'), fulltitle=name, plot=values['plot'], url=values['url'], id=values['id'], action='play', forcethumb=True, no_return=True))
    return support.thumb(itemlist, live=True)


def genres(item):
    item.action = 'peliculas'
    itemlist = [
        item.clone(title='Attualità e inchiesta', args='genere/attualita-e-inchiesta'),
        item.clone(title='Beauty and style', args='genere/beauty-and-style'),
        item.clone(title='Serie TV', args='genere/serie-tv'),
        item.clone(title='Casa', args='genere/casa'),
        item.clone(title='Comedy', args='genere/comedy'),
        item.clone(title='Crime', args='genere/crime'),
        item.clone(title='Documentari', args='genere/documentari'),
        # item.clone(title='Discovery + Originals', args='genere/discoveryplus-original'),
        item.clone(title='Food', args='genere/food'),
        item.clone(title='Medical', args='genere/medical'),
        item.clone(title='Motori', args='genere/motori'),
        item.clone(title='Natura', args='genere/natura'),
        item.clone(title='Paranormal', args='genere/paranormal'),
        item.clone(title='People', args='genere/people'),
        item.clone(title='Real Adventure', args='genere/real-adventure'),
        item.clone(title='Real Life', args='genere/real-life'),
        item.clone(title='Scienza e Spazio', args='genere/scienza-e-spazio'),
        item.clone(title='Sex and love', args='genere/sex-and-love'),
        item.clone(title='Sport', args='genere/sport'),
        item.clone(title='Talent Show', args='genere/talent-show'),
        ]
    return itemlist


def peliculas(item):
    logger.debug()
    itemlist =[]
    if 'search' in item.args:
        pdict = session.get('{}/content/shows?include=genres,images,primaryChannel.images,contentPackages&page[size]=12&query={}'.format(api, item.text), headers=headers).json()['data']
    else:
        pdict = session.get('{}/cms/routes/{}?decorators=viewingHistory&include=default'.format(api, item.args), headers=headers).json()['included']
    images = list(filter(lambda x: x['type'] == 'image', pdict))

    for key in pdict:
        if key['type'] == 'show' and 'Free' in str(key.get('relationships',{}).get('contentPackages',{}).get('data',[])):
            title = key['attributes']['name']
            plot = key['attributes'].get('description','')
            url = '{}/programmi/{}'.format(host, key['attributes']['alternateId'])
            seasons = key['attributes']['seasonNumbers']
            thumbs = [image['attributes']['src'] for image in images if image['id'] == key['relationships']['images']['data'][0]['id']]
            thumb = thumbs[0] if thumbs else item.thumbnail
            fanarts = [image['attributes']['src'] for image in images if len(key['relationships']['images']['data']) > 1 and image['id'] == key['relationships']['images']['data'][1]['id']]
            fanart = fanarts[0] if fanarts else item.fanart
            itemlist.append(
                item.clone(title=typo(title,'bold'),
                            fulltitle=title,
                            plot=plot,
                            url=url,
                            programid=key['attributes']['alternateId'],
                            id=key['id'],
                            seasons=seasons,
                            action='episodios',
                            thumbnail=thumb,
                            fanart=fanart,
                            contentType='tvshow'))

    return itemlist


def episodios(item):
    logger.debug()
    itemlist =[]
    pdict = session.get(api + '/cms/routes/programmi/{}?decorators=viewingHistory&include=default'.format(item.programid), headers=headers).json()['included']

    for key in pdict:
        if key['type'] == 'collection' and key.get('attributes',{}).get('component',{}).get('id', '') == 'tabbed-content':
            mandatory = key['attributes']['component'].get('mandatoryParams','')
            if not mandatory: return [support.Item(title='CONTENUTO PLUS')]
            for option in key['attributes']['component']['filters'][0]['options']:
                url = '{}/cms/collections/{}?decorators=viewingHistory&include=default&{}&{}'.format(api, key['id'], mandatory, option['parameter'])
                seasons = []
                season = {}
                try:
                    season = session.get(url, headers=headers).json()
                    seasons.append(season['included'])
                    pages = season['data'].get('meta',{}).get('itemsTotalPages', 0)
                    if pages:
                        for page in range(2,pages + 1):
                            url = '{}/cms/collections/{}?decorators=viewingHistory&include=default&{}&{}&page[items.number]={}'.format(api, key['id'], mandatory, option['parameter'], page)
                            logger.debug(url)
                            season = session.get(url, headers=headers).json()['included']
                            seasons.append(season)
                except:
                    pass

                for season in seasons:
                    for episode in season:
                        if episode['type'] == 'video' and 'Free' in episode['attributes']['packages']:
                            title = '{}x{:02d} - {}'.format(option['id'], episode['attributes']['episodeNumber'], episode['attributes']['name'])
                            plot = episode['attributes']['description']
                            itemlist.append(
                                item.clone(title=typo(title,'bold'),
                                           fulltitle=title,
                                           plot=plot,
                                           id=episode['id'],
                                           action='play',
                                           contentType='episode',
                                           season=option['id'],
                                           episode=episode['attributes']['episodeNumber'],
                                           forcethumb=True,
                                           no_return=True))

    if itemlist: itemlist.sort(key=lambda it: (int(it.season), int(it.episode)))
    return itemlist


def play(item):
    if item.livefilter:
        item.id = liveDict()[item.livefilter]['id']
        item.fulltitle = item.livefilter
        item.forcethumb = True
        item.no_return = True
        support.thumb(item, live=True)
    if item.contentType == 'episode': data = session.get('{}/playback/v2/videoPlaybackInfo/{}?usePreAuth=true'.format(api, item.id), headers=headers).json().get('data',{}).get('attributes',{})
    else: data = session.get('{}/playback/v2/channelPlaybackInfo/{}?usePreAuth=true'.format(api, item.id), headers=headers).json().get('data',{}).get('attributes',{})
    if data.get('protection', {}).get('drm_enabled',True):
        url = data['streaming']['dash']['url']
        item.drm = 'com.widevine.alpha'
        item.license = data['protection']['schemes']['widevine']['licenseUrl'] + '|PreAuthorization=' + data['protection']['drmToken'] + '|R{SSM}|'
    else:
        url = data['streaming']['hls']['url']
    return support.servertools.find_video_items(item, data=url)