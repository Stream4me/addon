# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per JustWatch TV
# ------------------------------------------------------------

import sys
import json
import base64
import difflib
import re
import requests

from core import support, httptools, tmdb
from core.item import Item, InfoLabels
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
    edges { node {
      ... on Movie {
        __typename
        id
        content(country: $country, language: $language) {
          title originalReleaseYear posterUrl shortDescription
        }
      }
      ... on Show {
        __typename
        id
        content(country: $country, language: $language) {
          title originalReleaseYear posterUrl shortDescription
        }
      }
    } }
  }
}
"""

Q_EPISODES = """
query Episodi($country: Country!, $language: Language!) {
  node(id: "__ID__") {
    ... on Show {
      episodes(limit: 1000, sortDirection: ASC, releasedInCountry: $country) {
        id
        content(country: $country, language: $language) {
          title seasonNumber episodeNumber shortDescription runtime
        }
        offers(country: $country, platform: WEB, filter: {packages: ["jwt"], monetizationTypes: [FREE], bestOnly: true}) {
          id
        }
      }
    }
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
    offer {
      streamUrlExternalPlayer
    }
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
    film = ['',
            ('Popolari', ['', 'peliculas', 'POPULAR', 'movie']),
            ('Di tendenza', ['', 'peliculas', 'TRENDING', 'movie']),
            ('Casuale', ['', 'peliculas', 'RANDOM', 'movie']),
            ('Ordine alfabetico', ['', 'peliculas', 'ALPHABETICAL', 'movie']),
            ('Anno di uscita', ['', 'peliculas', 'RELEASE_YEAR', 'movie']),
            ('Popolarità TMDB', ['', 'peliculas', 'TMDB_POPULARITY', 'movie']),
            ('Punteggio IMDb', ['', 'peliculas', 'IMDB_SCORE', 'movie'])]
    tvshow = ['',
              ('Popolari', ['', 'peliculas', 'POPULAR', 'tvshow']),
              ('Di tendenza', ['', 'peliculas', 'TRENDING', 'tvshow']),
              ('Casuale', ['', 'peliculas', 'RANDOM', 'tvshow']),
              ('Ordine alfabetico', ['', 'peliculas', 'ALPHABETICAL', 'tvshow']),
              ('Anno di uscita', ['', 'peliculas', 'RELEASE_YEAR', 'tvshow']),
              ('Popolarità TMDB', ['', 'peliculas', 'TMDB_POPULARITY', 'tvshow']),
              ('Punteggio IMDb', ['', 'peliculas', 'IMDB_SCORE', 'tvshow'])]
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


def simile(a, b):
    na = re.sub(r'[^a-z0-9]', '', (a or '').lower())
    nb = re.sub(r'[^a-z0-9]', '', (b or '').lower())
    if not na or not nb:
        return 0
    if na in nb or nb in na:
        return 1
    return difflib.SequenceMatcher(None, na, nb).ratio()


def verificaTmdb(itemlist):
    for it in itemlist:
        info = it.infoLabels
        if not info.get('tmdb_id') or not it.jw_title:
            continue
        trovati = [info.get('originaltitle'), info.get('title')]
        if max([simile(it.jw_title, t) for t in trovati]) >= 0.9:
            continue
        logger.debug('TMDB scartato per', it.jw_title, trovati)
        pulite = {'year': it.jw_year} if it.jw_year else {}
        if it.contentType == 'movie':
            pulite['title'] = it.jw_title
        else:
            pulite['tvshowtitle'] = it.jw_title
        if it.jw_plot:
            pulite['plot'] = it.jw_plot
        it.__dict__['infoLabels'] = InfoLabels(pulite)
        it.thumbnail = it.jw_thumb
        it.fanart = ''


def peliculas(item):
    logger.debug()
    itemlist = []

    valid_sorts = ('POPULAR', 'TRENDING', 'ALPHABETICAL', 'RANDOM',
                   'RELEASE_YEAR', 'TMDB_POPULARITY', 'IMDB_SCORE')
    sort = item.args if item.args in valid_sorts else 'POPULAR'

    if item.search_text:
        types = '[MOVIE, SHOW]'
    elif item.contentType == 'tvshow':
        types = '[SHOW]'
    else:
        types = '[MOVIE]'
    flt = 'objectTypes: ' + types + ', packages: ["jwt"], monetizationTypes: [FREE]'
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
        if node.get('__typename') == 'Show':
            itemlist.append(Item(channel=item.channel,
                                 action='episodios',
                                 contentType='tvshow',
                                 title=c['title'],
                                 fulltitle=c['title'],
                                 show=c['title'],
                                 contentSerieName=c['title'],
                                 infoLabels={'tvshowtitle': c['title'], 'year': str(year)} if year else {'tvshowtitle': c['title']},
                                 thumbnail=poster(c.get('posterUrl')),
                                 jw_id=node['id'],
                                 jw_title=c['title'],
                                 jw_year=str(year) if year else '',
                                 jw_plot=c.get('shortDescription') or '',
                                 jw_thumb=poster(c.get('posterUrl')),
                                 args=item.args,
                                 url=''))
        else:
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
                                 jw_title=c['title'],
                                 jw_year=str(year) if year else '',
                                 jw_plot=c.get('shortDescription') or '',
                                 jw_thumb=poster(c.get('posterUrl')),
                                 args=item.args,
                                 url=''))

    try:
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        verificaTmdb(itemlist)
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


def episodios(item):
    logger.debug()
    itemlist = []

    res = gql(Q_EPISODES.replace('__ID__', item.jw_id), {'country': 'IT', 'language': 'it'})
    if res.get('errors'):
        logger.error('JustWatch errori', res['errors'])
    node = (res.get('data') or {}).get('node') or {}

    show_title = item.jw_title or item.contentSerieName or item.fulltitle
    show_year = item.jw_year or item.infoLabels.get('year', '')

    for ep in node.get('episodes') or []:
        if not ep.get('offers'):
            continue
        c = ep.get('content') or {}
        season = c.get('seasonNumber')
        number = c.get('episodeNumber')
        if season is None or number is None:
            continue
        name = c.get('title') or ''
        label = '{}x{:02d}'.format(season, number)
        itemlist.append(Item(channel=item.channel,
                             action='findvideos',
                             contentType='episode',
                             title=support.typo(label + (' - ' + name if name else ''), 'bold'),
                             fulltitle=show_title,
                             show=show_title,
                             contentSerieName=show_title,
                             contentSeason=season,
                             contentEpisodeNumber=number,
                             infoLabels={'season': season, 'episode': number,
                                         'tvshowtitle': show_title,
                                         'year': show_year},
                             thumbnail=item.thumbnail,
                             jw_id=ep['id'],
                             url=''))

    if itemlist and config.get_setting('episode_info'):
        try:
            tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        except:
            logger.error('TMDB non disponibile')

    support.videolibrary(itemlist, item)
    return itemlist


def offerId(jw_id, quality='hd'):
    raw = 'of|{}:IT:jwt:free:{}'.format(jw_id, quality)
    return base64.b64encode(raw.encode('utf-8')).decode('utf-8')


def findvideos(item):
    logger.debug()

    res = gql(Q_PLAY, {'input': {'offerId': offerId(item.jw_id), 'drmType': 'widevine', 'deviceOs': 'android'}})
    info = (res.get('data') or {}).get('getPlayInformation') or {}
    streams = info.get('streams') or []
    offer = info.get('offer') or {}

    if not streams and offer.get('streamUrlExternalPlayer'):
        url = offer['streamUrlExternalPlayer']
        logger.info('JustWatch HLS (no DRM): {}'.format(url))
        it = item.clone(server='directo',
                        url=url,
                        manifest='hls',
                        drm='',
                        license='',
                        referer=host + '/',
                        no_return=True)
        return support.server(item, itemlist=[it], Download=False, Videolibrary=False)

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