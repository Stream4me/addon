# -*- coding: utf-8 -*-
import sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True

from six.moves import urllib

import ast
import xbmc

from core import httptools, support, filetools
from platformcode import logger, config

vttsupport = False if int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0]) < 20 else True

DEFAULT_SCWS_URL = 'https://vixcloud.cc'


def _get_embed_url(page_url):
    """Estrae l'URL embed dal data-page (AnimeUnity) o restituisce None."""
    import json, html, re
    try:
        data = httptools.downloadpage(page_url).data or ''
        match = re.search(r'data-page="([^"]+)"', data)
        if not match:
            logger.info('StreamingCommunityWS: data-page non trovato in {} (len={})'.format(page_url, len(data)))
            return None
        page_json = json.loads(html.unescape(match.group(1)))
    except Exception as e:
        logger.info('StreamingCommunityWS: errore lettura {}: {}'.format(page_url, e))
        return None

    props = page_json.get('props') or {}
    scws_url = (props.get('scws_url') or DEFAULT_SCWS_URL).rstrip('/')

    embed_url = props.get('embedUrl')
    if embed_url:
        if embed_url.startswith('//'):
            embed_url = 'https:' + embed_url
        elif embed_url.startswith('/'):
            embed_url = scws_url + embed_url
        return embed_url

    video = props.get('video') or {}
    scws_id = video.get('scws_id')
    if scws_id:
        return '{}/embed/{}?canPlayFHD=1&skin=animeunity2'.format(scws_url, scws_id)

    logger.info('StreamingCommunityWS: embedUrl/video.scws_id assenti, props keys: {}'.format(list(props.keys())))
    return None


def test_video_exists(page_url):
    global iframeParams
    global urlParams

    server_url = _get_embed_url(page_url)

    if not server_url:
        server_url = support.scrapertools.decodeHtmlentities(
            support.match(page_url, patron=['<iframe [^>]+src="([^"]+)', 'embed_url="([^"]+)']).match)

    if not server_url:
        logger.info('StreamingCommunityWS: embed non trovato per {}'.format(page_url))
        return 'StreamingCommunity', 'Prossimamente'

    embed_headers = {'Referer': page_url}
    iframeParams = support.match(
        server_url, headers=embed_headers,
        patron=r'''window\.masterPlaylist\s+=\s+{[^{]+({[^}]+}),\s+url:\s+'([^']+).*?canPlayFHD\s=\s(true|false)''',
        debug=False).match

    if not iframeParams or len(iframeParams) < 2:
        logger.info('StreamingCommunityWS: masterPlaylist non trovata in {}'.format(server_url))
        return 'StreamingCommunity', 'Prossimamente'

    urlParams = urllib.parse.parse_qs(urllib.parse.urlsplit(server_url).query)
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = list()

    params, url, canPlayFHD = iframeParams
    split_url = urllib.parse.urlsplit(url)
    url_params = urllib.parse.parse_qsl(split_url.query)
    logger.debug(url_params)
    masterPlaylistParams = ast.literal_eval(params)
    if canPlayFHD == 'true':
        masterPlaylistParams['h'] = 1
    if 'b' in urlParams:
        masterPlaylistParams['b'] = 1

    masterPlaylistParams.update(url_params)
    url = '{}://{}{}?{}'.format(
        split_url.scheme, split_url.netloc, split_url.path,
        urllib.parse.urlencode(masterPlaylistParams))

    video_urls = [['hls [{}]'.format('FullHD' if canPlayFHD == 'true' else 'HD'), url]]

    return video_urls