# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Pluto TV
# ------------------------------------------------------------

import uuid, datetime, six
from platformcode import logger, config
from core.item import Item
from core import jsontools, support, httptools

host = support.config.get_channel_url()
api = 'https://api.pluto.tv'

_SID       = str(uuid.uuid1())
_DEVICE_ID = str(uuid.uuid4())

_jwt_cache = {
    'token'   : None,
    'expires' : None,
    'country' : 'IT',
    'lat'     : '0.0000',
    'lon'     : '0.0000',
}

UUID    = 'sid={}&deviceId={}'.format(_SID, _DEVICE_ID)
vod_url = '{}/v3/vod/categories?includeItems=true&deviceType=web&{}'.format(api, UUID)

APP_VERSION = '9.20.0-89258290264838515e264f5b051b7c1602a58482'

BOOT_URL = (
    'https://boot.pluto.tv/v4/start'
    '?appName=web&appVersion={av}&deviceVersion=146.0.0'
    '&deviceModel=web&deviceMake=chrome&deviceType=web'
    '&clientID={cid}&clientModelNumber=1.0.0&serverSideAds=false'
    '&drmCapabilities=widevine%3AL3&blockingMode='
    '&notificationVersion=1&appLaunchCount=0'
).format(cid=_DEVICE_ID, av=APP_VERSION)

LIVE_STITCH = (
    'https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv'
    '/v2/stitch/hls/channel/{channel_id}/master.m3u8'
    '?sid={sid}&deviceId={did}&jwt={jwt}&masterJWTPassthrough=true'
)

VOD_STITCH = (
    'https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv'
    '/v2/stitch/dash/episode/{{episode_id}}/main.mpd'
    '?advertisingId=&appName=web&appVersion=&app_name=web'
    '&clientDeviceType=0&clientID={did}&clientModelNumber=1.0.0'
    '&country={{country}}&deviceDNT=false&deviceId={did}'
    '&deviceLat={{lat}}&deviceLon={{lon}}'
    '&deviceMake=chrome&deviceModel=web&deviceType=web&deviceVersion=146.0.0'
    '&marketingRegion={{country}}&serverSideAds=false'
    '&sessionID={sid}&sid={sid}&userId='
    '&jwt={{jwt}}&masterJWTPassthrough=true'
    '&includeExtendedEvents=true&eventVOD=false'
).format(sid=_SID, did=_DEVICE_ID)

HEADERS = {
    'Origin'    : 'https://pluto.tv',
    'Referer'   : 'https://pluto.tv/',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/146.0.0.0 Safari/537.36'
    ),
}

LIVE_URL  = '{}/v2/channels.json?{}'.format(api, UUID)
GUIDE_URL = '{}/v2/channels?start={{}}&stop={{}}&{}'.format(api, UUID)


def _get_jwt():
    now = datetime.datetime.utcnow()
    if _jwt_cache['token'] and _jwt_cache['expires'] and now < _jwt_cache['expires']:
        return _jwt_cache['token']

    resp = httptools.downloadpage(BOOT_URL, headers=HEADERS)

    import json as _json_mod
    data = None
    if resp.json and isinstance(resp.json, dict):
        data = resp.json
    elif resp.data:
        try:
            data = _json_mod.loads(resp.data)
        except:
            return ''
    if not data:
        return ''

    token = data.get('sessionToken') or data.get('token') or data.get('jwt') or ''
    if not token:
        return ''

    try:
        import base64, json as _json
        payload_b64  = token.split('.')[1]
        payload_b64 += '=' * (-len(payload_b64) % 4)
        payload      = _json.loads(base64.b64decode(payload_b64).decode('utf-8'))

        exp     = payload.get('exp')
        expires = (datetime.datetime.utcfromtimestamp(exp)
                   if exp else now + datetime.timedelta(hours=23))

        _jwt_cache['country']    = payload.get('country', 'IT')
        _jwt_cache['lat']        = '{:.4f}'.format(payload.get('deviceLat', 0.0))
        _jwt_cache['lon']        = '{:.4f}'.format(payload.get('deviceLon', 0.0))
        _jwt_cache['session_id'] = payload.get('sessionID', _SID)

    except:
        expires = now + datetime.timedelta(hours=23)

    _jwt_cache['token']   = token
    _jwt_cache['expires'] = expires
    return token


def _build_live_url(channel_id):
    jwt = _get_jwt()
    if not jwt:
        return ''
    sid = _jwt_cache.get('session_id', _SID)
    return LIVE_STITCH.format(
        channel_id = channel_id,
        sid        = sid,
        did        = _DEVICE_ID,
        jwt        = jwt,
    )


def _build_vod_url(episode_id):
    jwt = _get_jwt()
    if not jwt:
        return ''
    return VOD_STITCH.format(
        episode_id = episode_id,
        jwt        = jwt,
        country    = _jwt_cache['country'],
        lat        = _jwt_cache['lat'],
        lon        = _jwt_cache['lon'],
    )


@support.menu
def mainlist(item):
    top    = [('Dirette {bold}', ['/it/live-tv/', 'live'])]
    menu   = [('Categorie', ['', 'category'])]
    search = ''
    return locals()


@support.menu
def category(item):
    if not six.PY2:
        menu = [(it['name'], ['/it/on-demand', 'peliculas', it['items']])
                for it in httptools.downloadpage(vod_url).json['categories'][1:]]
        menu.sort(key=lambda item: item[0])
    else:
        menu = sorted([(it['name'], ['/it/on-demand', 'peliculas', it['items']])
                       for it in httptools.downloadpage(vod_url).json['categories'][1:]])
    return locals()


def live(item):
    if not _get_jwt():
        return []

    now   = datetime.datetime.utcnow()
    start = now.strftime('%Y-%m-%dT%H:00:00Z')
    stop  = (now + datetime.timedelta(hours=4)).strftime('%Y-%m-%dT%H:00:00Z')

    guide_resp = httptools.downloadpage(GUIDE_URL.format(start, stop))
    guide_data = guide_resp.json if isinstance(guide_resp.json, list) else []
    guide = {}
    for g in guide_data:
        tl = g.get('timelines', [])
        guide[g.get('number', 0)] = [
            tl[0].get('title', '') if len(tl) > 0 else '',
            tl[1].get('title', '') if len(tl) > 1 else '',
        ]

    channels_resp = httptools.downloadpage(LIVE_URL)
    channels_data = channels_resp.json if isinstance(channels_resp.json, list) else []

    itemlist = []
    for it in channels_data:
        try:
            num        = it.get('number', 0)
            guide_info = guide.get(num, ['', ''])
            thumb      = (it.get('solidLogoPNG') or {}).get('path', '')
            fanart     = (it.get('featuredImage') or {}).get('path', '')
            stream_url = _build_live_url(it.get('_id', ''))

            if not stream_url:
                continue

            itemlist.append(item.clone(
                title        = '[B]{}[/B] | {}'.format(it['name'], guide_info[0]),
                number       = num,
                contentTitle = it['name'],
                action       = 'findvideos',
                thumbnail    = thumb,
                fanart       = fanart,
                plot         = '{}\n\n[B]A seguire:[/B]\n{}'.format(
                                   it.get('summary', ''), guide_info[1]),
                videourl     = stream_url,
                forcethumb   = True,
            ))
        except:
            pass

    itemlist.sort(key=lambda it: it.number)
    return itemlist


def search(item, text):
    logger.debug('Search: {}'.format(text))

    jwt = _get_jwt()
    if not jwt:
        return []

    query = text.replace(" ", "%20")
    url = f"https://service-media-search.clusters.pluto.tv/v1/search?q={query}&limit=100"

    headers = HEADERS.copy()
    headers["Authorization"] = f"Bearer {jwt}"

    resp = httptools.downloadpage(url, headers=headers)
    data = resp.json or {}

    results = data.get("data", [])
    itemlist = []

    for r in results:
        dist = r.get("distributeAs", {})
        if not dist.get("AVOD", False):
            continue

        if r.get("type") == "timeline":
            continue

        rid   = r.get("id")
        rtype = r.get("type")

        if rtype == "movie":
            thumb  = f"https://images.pluto.tv/episodes/{rid}/screenshot16_9.jpg?fill=blur&fit=fill&fm=jpg&w=224&h=124&q=75"
            fanart = f"https://images.pluto.tv/episodes/{rid}/screenshot16_9.jpg?fill=blur&fit=fill&fm=jpg&w=1280&h=720&q=75"
        else:
            thumb  = f"https://images.pluto.tv/series/{rid}/featuredImage.jpg?fill=blur&fit=fill&fm=jpg&w=224&h=124&q=75"
            fanart = f"https://images.pluto.tv/series/{rid}/featuredImage.jpg?fill=blur&fit=fill&fm=jpg&w=1280&h=720&q=75"

        if rtype == "movie":
            itemlist.append(Item(
                channel=item.channel,
                title=r.get("name", ""),
                contentTitle=r.get("name", ""),
                plot="",
                contentType="movie",
                action="findvideos",
                thumbnail=thumb,
                fanart=fanart,
                id=rid,
                videourl="",
            ))
        else:
            itemlist.append(Item(
                channel=item.channel,
                title=r.get("name", ""),
                contentTitle=r.get("name", ""),
                contentSerieName=r.get("name", ""),
                plot="",
                contentType="tvshow",
                action="episodios",
                thumbnail=thumb,
                fanart=fanart,
                id=rid,
                videourl="",
            ))

    return itemlist


def peliculas(item):
    itemlist   = []
    recordlist = []

    for i, it in enumerate(item.args):
        if item.search in it['name'].lower():
            is_series = it['type'] == 'series'
            itm = Item(
                channel          = item.channel,
                url              = item.url,
                title            = it['name'],
                contentTitle     = it['name'],
                contentSerieName = it['name'] if is_series else '',
                plot             = it['description'],
                contentType      = 'tvshow' if is_series else 'movie',
                action           = 'episodios' if is_series else 'findvideos',
                thumbnail        = it['covers'][0]['url'],
                fanart           = it['covers'][2]['url'] if len(it['covers']) > 2 else '',
                id               = it['_id'],
                videourl         = '',
            )
            if i < 20 or item.search:
                itemlist.append(itm)
            else:
                recordlist.append(it)

    support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    if recordlist and not item.search:
        itemlist.append(item.clone(
            title     = support.typo(support.config.get_localized_string(30992), 'color std bold'),
            thumbnail = support.thumb(),
            args      = recordlist,
        ))
    return itemlist


def episodios(item):
    itemlist    = []
    seasons_url = ('{}/v3/vod/series/{}/seasons'
                   '?includeItems=true&deviceType=web&{}'.format(api, item.id, UUID))
    seasons = httptools.downloadpage(seasons_url).json['seasons']

    for season in seasons:
        for episode in season['episodes']:
            itemlist.append(item.clone(
                title                = '{}x{:02d} - {}'.format(
                                           episode['season'], episode['number'], episode['name']),
                contentTitle         = episode['name'],
                contentSeason        = episode['season'],
                contentEpisodeNumber = episode['number'],
                plot                 = episode['description'],
                thumbnail            = episode['covers'][1]['url'],
                id                   = episode['_id'],
                videourl             = '',
                action               = 'findvideos',
            ))

    if config.get_setting('episode_info'):
        support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    support.videolibrary(itemlist, item)
    return itemlist


def findvideos(item):
    item.server = 'directo'

    if item.videourl and 'jwt=' in item.videourl:
        item.manifest      = 'hls'
        item.url           = item.videourl
        item.extra_headers = HEADERS
        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)

    item.manifest = 'mpd'
    item.url      = _build_vod_url(item.id)
    if not item.url:
        return []

    item.extra_headers = HEADERS

    jwt = _get_jwt()
    lic_url = f"https://service-concierge.clusters.pluto.tv/v1/wv/alt?jwt={jwt}"

    item.drm = "com.widevine.alpha"
    item.license = (
        lic_url +
        "|Content-Type=application/octet-stream&Origin=https://pluto.tv&Referer=https://pluto.tv&User-Agent=" +
        HEADERS["User-Agent"] +
        "|R{SSM}|"
    )

    return support.server(item, itemlist=[item], Download=False, Videolibrary=False)
