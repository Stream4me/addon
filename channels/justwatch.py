# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per JustWatch TV
# ------------------------------------------------------------

import sys
import json
import base64
import requests

from core import support, httptools, tmdb
from core.item import Item
from platformcode import config, logger, platformtools

if sys.version_info[0] >= 3:
    from urllib.parse import urlencode
else:
    from urllib import urlencode

host = support.config.get_channel_url().rstrip('/')
API = 'https://apis.justwatch.com/graphql'
IMAGES = 'https://images.justwatch.com'
PAGE = 40

Q_LIST = """
query Lista($country: Country!, $language: Language!, $first: Int!, $after: String) {
  popularTitles(country: $country, first: $first, after: $after, sortBy: __SORT__, filter: {__FILTER__}) {
    pageInfo { endCursor hasNextPage }
    edges { node { ... on Movie {
      id
      content(country: $country, language: $language) {
        title originalReleaseYear posterUrl shortDescription
      }
    } } }
  }
}
"""

Q_PLAY = """
mutation GetPlayInformation($input: GetPlayInformationInput!) {
  getPlayInformation(input: $input) {
    streams {
      url
      encodingType
      drmType
      manifestUrlDash
      drmConfigs { certificateURL drmType laURL }
    }
    expirationTime
    errorCode
  }
}
"""


def apiHeaders():
    return {'User-Agent': httptools.get_user_agent(),
            'Origin': host,
            'Referer': host + '/',
            'Content-Type': 'application/json'}


def gql(query, variables):
    r = requests.post(API, json={'query': query, 'variables': variables}, headers=apiHeaders(), timeout=20)
    return r.json()


@support.menu
def mainlist(item):
    menu = [('Popolari {bold}', ['', 'peliculas', 'POPULAR', 'movie']),
            ('Di tendenza {bold}', ['', 'peliculas', 'TRENDING', 'movie']),
            ('Ordine alfabetico {bold}', ['', 'peliculas', 'ALPHABETICAL', 'movie'])]
    search = ''
    return locals()


def search(item, text):
    logger.debug(text)
    item.search_text = text
    item.args = 'POPULAR'
    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
        return []


def poster(url):
    if not url:
        return ''
    return IMAGES + url.replace('{profile}', 's332').replace('{format}', 'jpg')


def peliculas(item):
    logger.debug()
    itemlist = []

    sort = item.args if item.args in ('POPULAR', 'TRENDING', 'ALPHABETICAL') else 'POPULAR'
    flt = 'objectTypes: [MOVIE], packages: ["jwt"], monetizationTypes: [FREE]'
    if item.search_text:
        flt += ', searchQuery: ' + json.dumps(item.search_text)

    query = Q_LIST.replace('__SORT__', sort).replace('__FILTER__', flt)
    variables = {'country': 'IT', 'language': 'it', 'first': PAGE}
    if item.after:
        variables['after'] = item.after

    res = gql(query, variables)
    if res.get('errors'):
        logger.error('JustWatch errori', res['errors'])
    pop = (res.get('data') or {}).get('popularTitles') or {}

    for edge in pop.get('edges') or []:
        node = edge.get('node') or {}
        c = node.get('content') or {}
        if not node.get('id') or not c.get('title'):
            continue
        year = c.get('originalReleaseYear')
        itemlist.append(Item(channel=item.channel,
                             action='findvideos',
                             contentType='movie',
                             title=c['title'],
                             fulltitle=c['title'],
                             show=c['title'],
                             contentTitle=c['title'],
                             infoLabels={'year': str(year)} if year else {},
                             thumbnail=poster(c.get('posterUrl')),
                             jw_id=node['id'],
                             args=item.args,
                             url=''))

    try:
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    except:
        logger.error('TMDB non disponibile')

    info = pop.get('pageInfo') or {}
    if info.get('hasNextPage') and info.get('endCursor'):
        label = config.get_localized_string(30992) or 'Pagina successiva'
        itemlist.append(item.clone(title=support.typo(label, 'color kod bold'),
                                   action='peliculas',
                                   after=info['endCursor'],
                                   thumbnail=support.thumb()))
    return itemlist


def offerId(jw_id, quality='hd'):
    raw = 'of|{}:IT:jwt:free:{}'.format(jw_id, quality)
    return base64.b64encode(raw.encode('utf-8')).decode('utf-8')


def findvideos(item):
    logger.debug()

    res = gql(Q_PLAY, {'input': {'offerId': offerId(item.jw_id), 'drmType': 'widevine', 'deviceOs': 'android'}})
    info = (res.get('data') or {}).get('getPlayInformation') or {}
    streams = info.get('streams') or []
    if not streams:
        logger.error('JustWatch', res)
        platformtools.dialog_ok('JustWatch TV', 'Stream non disponibile ({})'.format(info.get('errorCode')))
        return []

    url_dash = ''
    url_hls = ''
    lic = ''
    for s in streams:
        if s.get('manifestUrlDash'):
            url_dash = s['manifestUrlDash']
        u = s.get('url') or ''
        if u:
            if '.mpd' in u or 'DASH' in (s.get('encodingType') or '').upper():
                url_dash = url_dash or u
            else:
                url_hls = url_hls or u
        for d in s.get('drmConfigs') or []:
            if (d.get('drmType') or '').lower().startswith('widevine') and d.get('laURL'):
                lic = d['laURL']

    url = url_dash or url_hls
    manifest = 'mpd' if url_dash else 'hls'
    if not url:
        platformtools.dialog_ok('JustWatch TV', 'Manifest non trovato')
        return []

    if not lic and url_hls:
        try:
            tok = url_hls.split('/manifest/')[1].split('.')[0]
            tok += '=' * (-len(tok) % 4)
            pb = json.loads(base64.urlsafe_b64decode(tok.encode()).decode())['pb']
            lic = 'https://apis.justwatch.com/drm/license?drmType=widevine&playbackId={}'.format(pb)
        except:
            pass
    if not lic:
        platformtools.dialog_ok('JustWatch TV', 'Licenza Widevine non trovata')
        return []

    license_headers = {'Content-Type': 'application/octet-stream',
                       'User-Agent': httptools.get_user_agent(),
                       'Origin': host,
                       'Referer': host + '/'}

    it = item.clone(server='directo',
                    url=url,
                    manifest=manifest,
                    drm='com.widevine.alpha',
                    license=lic + '|' + urlencode(license_headers) + '|R{SSM}|',
                    referer=host + '/',
                    no_return=True)

    return support.server(item, itemlist=[it], Download=False, Videolibrary=False)
