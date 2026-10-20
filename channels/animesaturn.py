# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per AnimeSaturn
# ------------------------------------------------------------

import base64
import json
import re
from urllib.parse import urlparse, parse_qs, quote

from core import support
from platformcode import logger

host = support.config.get_channel_url()
__channel__ = 'animesaturn'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def get_data(url, extra_headers=None, referer=None):
    h = dict(headers)
    if extra_headers:
        h.update(extra_headers)
    if referer:
        h['Referer'] = referer
    return support.match(url, headers=h, follow_redirects=True).data


def _abs(url):
    if not url:
        return url
    if url.startswith('http'):
        return url
    return host + ('' if url.startswith('/') else '/') + url


def _to_player_path(href):
    return re.sub(r'^(?:https?://[^/]+)?/episode/', '/anime/', href)


def _is_saturn_embed(link):
    if not link:
        return False
    try:
        path = urlparse(link).path
        return bool(re.search(r'/embed/\d+', path))
    except Exception:
        return False


def _decode_embed_payload(payload, key):
    if not payload:
        return ''
    k = key or 'as'
    raw = base64.b64decode(payload)
    out = bytearray(len(raw))
    for i, b in enumerate(raw):
        out[i] = b ^ ord(k[i % len(k)])
    return out.decode('iso-8859-1', errors='replace')


def _read_embed_params(embed_url, referer):
    parsed = urlparse(embed_url)
    m = re.search(r'/embed/(\d+)', parsed.path)
    fallback_id = m.group(1) if m else ''
    qs = parse_qs(parsed.query)
    fallback_token = (qs.get('token') or [''])[0]
    fallback_expires = (qs.get('expires') or [''])[0]

    try:
        html = get_data(embed_url, referer=referer)
        m = re.search(
            r'window\.__E\s*=\s*\{\s*i\s*:\s*(\d+)\s*,\s*k\s*:\s*"([^"]+)"\s*,\s*e\s*:\s*(\d+)',
            html)
        if m:
            return m.group(1), m.group(2), m.group(3)
    except Exception as e:
        logger.error(f"[animesaturn] embed fetch error: {e}")

    if not fallback_id or not fallback_token:
        raise Exception('Saturn embed: parametri non leggibili')
    return fallback_id, fallback_token, fallback_expires


def _resolve_saturn_embed(embed_url):
    embed_url = (embed_url or '').strip()
    if not embed_url:
        raise Exception('Saturn embed: link mancante')
    if not _is_saturn_embed(embed_url):
        raise Exception(f'Saturn embed: link non interno ({embed_url[:80]})')

    embed_id, token, expires = _read_embed_params(embed_url, host + '/')

    parsed = urlparse(embed_url)
    origin = f'{parsed.scheme}://{parsed.netloc}'

    playlist_url = (
        f'{origin}/embed/{quote(embed_id, safe="")}/playlist'
        f'?token={quote(token, safe="")}&expires={quote(expires, safe="")}'
    )

    body = get_data(
        playlist_url,
        extra_headers={
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest',
        },
        referer=embed_url,
    )

    try:
        payload = json.loads(body).get('d', '')
    except Exception:
        payload = ''

    source = _decode_embed_payload(payload, token)
    if not source:
        raise Exception('Saturn embed: sorgente video vuota')
    if source.startswith('youtube/'):
        raise Exception('Saturn embed: sorgente YouTube, non riproducibile')
    return source


def _parse_watch_page_data(html):
    m = re.search(r'x-data="watchPage\((\{.*?\})\)"', html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).replace('&quot;', '"').replace('\\/', '/').replace('\\u0026', '&')
    try:
        return json.loads(raw)
    except Exception:
        return None


@support.menu
def mainlist(item):
    menu = [
        ('Anime',          ['/az-list',                  'peliculas', 'az']),
        ('ITA',            ['/filter?languages=it',      'peliculas', 'filter']),
        ('SUB-ITA',        ['/filter?languages=jp',      'peliculas', 'filter']),
        ('Più Votati',     ['/filter?sort=best_rated',   'peliculas', 'filter']),
        ('In Corso',       ['/ongoing',                  'peliculas', 'ongoing']),
        ('Ultimi Episodi', ['/newest',                   'peliculas', 'updated']),
    ]
    search = ''
    return locals()


def search(item, texto):
    support.info(texto)
    item.url = host + '/filter?key=' + texto
    item.contentType = 'tvshow'
    try:
        return peliculas(item)
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)
        return []


def newest(categoria):
    support.info()
    item = support.Item()
    try:
        if categoria == 'anime':
            item.url = host + '/newest'
            item.args = 'updated'
            return peliculas(item)
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error("%s" % line)
        return []
    return []


@support.scrape
def peliculas(item):
    anime = True
    action = 'check'
    data = item.data if item.data else get_data(item.url)

    patron = r'<a href="(?P<url>/anime/[^"]+)" class="ac group">\s*'
    patron += r'<div class="ac__poster">\s*'
    patron += r'<img src="(?P<thumb>[^"]+)"\s+alt="[^"]*"'
    patron += r'.*?</div>\s*<div class="ac__caption">\s*'
    patron += r'<h3 class="ac__title">(?P<title>[^<]+)</h3>\s*'
    patron += r'<p class="ac__sub">(?P<sub>[^<]+)</p>'

    next_page = support.match(data, patron=r'href="(?P<url>[^"]+)"[^>]*rel="next"').match

    def itemlistHook(itemlist):
        if next_page:
            itemlist.append(item.clone(
                title=support.typo(support.config.get_localized_string(30992), 'color std bold'),
                url=_abs(next_page), action='peliculas', args=item.args,
                thumbnail=support.thumb()))
        return itemlist
    return locals()


@support.scrape
def episodios(item):
    if item.contentType != 'movie':
        anime = True
    data = item.data if item.data else get_data(item.url)
    patron = (r'<a href="(?P<url>/episode/[^"]+)" class="ep-tile"'
              r'[^>]*title="Episodio (?P<episode>\d+)"')
    return locals()


def check(item):
    data = get_data(item.url) if not item.data else item.data
    tipo = support.match(
        data,
        patron=r'<a href="/filter\?types=\d+"[^>]*>.*?'
               r'<span class="font-medium text-brand[^"]*">([^<]+)</span>').match
    neps = support.match(
        data,
        patron=r'<span class="text-ink-dim text-xs uppercase tracking-wider">'
               r'Episodi</span>\s*<span class="font-medium">(\d+)</span>').match
    if tipo in ('Movie', 'Special') or (neps and int(neps) == 1):
        item.contentType = 'movie'
    else:
        item.contentType = 'tvshow'
    item.data = data
    return episodios(item)


def findvideos(item):
    support.info()
    itemlist = []

    player_url = _abs(_to_player_path(item.url))
    html = get_data(player_url)

    data = _parse_watch_page_data(html)
    if not data:
        logger.error('[animesaturn] watchPage data non trovato')
        return itemlist

    servers = data.get('servers') or []
    for s in servers:
        link = s.get('link', '')
        if not _is_saturn_embed(link):
            continue
        name = s.get('name') or 'AnimeSaturn'
        server_id = s.get('slug') or str(s.get('id', ''))
        itemlist.append(item.clone(
            action='play',
            title=name,
            url=link,
            server='directo',
            server_id=server_id))

    if not itemlist:
        initial = data.get('initialVideoUrl', '')
        if _is_saturn_embed(initial):
            itemlist.append(item.clone(
                action='play',
                title='AnimeSaturn',
                url=initial,
                server='directo',
                server_id='serverstock'))

    return itemlist


def play(item):
    support.info()
    if _is_saturn_embed(item.url):
        try:
            item.url = _resolve_saturn_embed(item.url)
        except Exception as e:
            logger.error(f'[animesaturn] resolve error: {e}')
            return []
    return [item]