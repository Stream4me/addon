# -*- coding: utf-8 -*-
# servers/vixsrc.py
import re
import json
from urllib.parse import urlparse, parse_qs, urlencode, urljoin

from core import httptools, support
from platformcode import logger

_BASE = 'https://vixsrc.to'

_TOKEN_RE   = re.compile(r'''["']token["']\s*:\s*["'](\w+)["']''')
_URL_RE     = re.compile(r'''["']url["']\s*:\s*["']([^"']+)["']''')
_EXPIRES_RE = re.compile(r'''["']expires["']\s*:\s*["'](\d+)["']''')
_IFRAME_RE  = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']')
_FHD_RE     = re.compile(r'"canPlayFHD"\s*:\s*true|canPlayFHD\s*=\s*true')
_INERTIA_RE = re.compile(r'data-page="({.+?})"', re.DOTALL)
_M3U8_RE    = re.compile(r'(/playlist/[^/?#]+?)(?:\.m3u8)?(?=[?#]|$)')


def _get_headers(referer=_BASE + '/'):
    return {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Referer':         referer,
        'Origin':          _BASE,
        'Accept':          'text/html,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection':      'keep-alive',
    }


def _download(url, headers):
    resp = httptools.downloadpage(url, headers=headers)
    dati = resp.data
    if isinstance(dati, bytes):
        return resp.code, dati.decode('utf-8', errors='replace')
    return resp.code, (dati or '')


def _decode_url(raw):
    r"""Decodifica sequenze \uXXXX nell'URL grezzo estratto dalla pagina."""
    try:
        return json.loads('"' + raw.replace('"', '\\"') + '"')
    except Exception:
        return raw.replace('\\/', '/').replace('\\u0026', '&')


def _get_inertia_version(html):
    m = _INERTIA_RE.search(html)
    if not m:
        return None
    try:
        payload = json.loads(m.group(1).replace('&quot;', '"'))
        return payload.get('version')
    except Exception as e:
        logger.debug("vixsrc: errore parse Inertia - %s" % e)
        return None


def _build_hls_url(raw_url, token, wp_data, page_url):
    url_pulita = _decode_url(raw_url)
    url_pulita = _M3U8_RE.sub(r'\1.m3u8', url_pulita)

    if '?' in url_pulita:
        base, qs = url_pulita.split('?', 1)
        params = {k: v[0] for k, v in parse_qs(qs).items()}
    else:
        base   = url_pulita
        params = {}

    params['token'] = token

    m = _EXPIRES_RE.search(wp_data)
    if m:
        params['expires'] = m.group(1)

    if _FHD_RE.search(wp_data):
        params['h'] = '1'

    params.setdefault('lang', 'it')

    for k, v in parse_qs(urlparse(page_url).query).items():
        params.setdefault(k, v[0])

    url_finale = base + '?' + urlencode(params)
    return url_finale.replace('&amp;', '&')


def test_video_exists(page_url):
    logger.info("vixsrc test_video_exists: %s" % page_url)
    if not page_url or 'vixsrc.to' not in page_url:
        return False, "URL non valido"
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    logger.info("vixsrc get_video_url: %s" % page_url)

    headers = _get_headers()

    api_url          = page_url.replace('/tv/', '/api/tv/').replace('/movie/', '/api/movie/')
    url_da_scaricare = page_url

    if api_url != page_url:
        logger.debug("vixsrc: tentativo API -> %s" % api_url)
        codice, dati_api = _download(api_url, headers)
        if codice == 200 and dati_api:
            try:
                risposta = json.loads(dati_api)
                if 'src' in risposta:
                    url_da_scaricare = urljoin(_BASE, risposta['src'])
                    logger.info("vixsrc: API src -> %s" % url_da_scaricare)
            except Exception as e:
                logger.debug("vixsrc: API parse error - %s" % e)

    _, wp_data = _download(url_da_scaricare, headers)

    token = None
    m = _TOKEN_RE.search(wp_data)
    if m:
        token = m.group(1)

    if not token:
        logger.debug("vixsrc: token non trovato, cerco iframe...")
        html_corrente = wp_data
        url_corrente  = url_da_scaricare

        for livello in range(3):
            m_iframe = _IFRAME_RE.search(html_corrente)
            if not m_iframe:
                logger.debug("vixsrc: nessun iframe al livello %d" % livello)
                break

            iframe_url = urljoin(url_corrente, m_iframe.group(1))
            logger.info("vixsrc: iframe livello %d -> %s" % (livello + 1, iframe_url))

            hdrs     = _get_headers(referer=url_corrente)
            versione = _get_inertia_version(html_corrente)
            if versione:
                hdrs['X-Inertia']         = 'true'
                hdrs['X-Inertia-Version'] = versione
                logger.debug("vixsrc: Inertia version %s" % versione)

            _, html_iframe = _download(iframe_url, hdrs)

            m = _TOKEN_RE.search(html_iframe)
            if m:
                token   = m.group(1)
                wp_data = html_iframe
                logger.info("vixsrc: token trovato al livello %d" % (livello + 1))
                break

            html_corrente = html_iframe
            url_corrente  = iframe_url

    if not token:
        logger.error("vixsrc: token non trovato dopo tutti i tentativi")
        return [['embed [VixSrc]', page_url]]

    m = _URL_RE.search(wp_data)
    if not m:
        logger.error("vixsrc: URL playlist non trovato")
        return [['embed [VixSrc]', page_url]]

    hls_url = _build_hls_url(m.group(1), token, wp_data, page_url)
    logger.info("vixsrc: HLS finale -> %s" % hls_url)

    return [['hls [VixSrc]', hls_url]]