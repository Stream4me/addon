import base64
import hashlib
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit, urlencode, quote, unquote, quote_plus

from core import httptools, scrapertools, servertools
from platformcode import config, logger

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def _base(url):
    p = urlsplit(url)
    return '%s://%s' % (p.scheme, p.netloc)


def _radice(url):
    return re.split(r'guarda', url, 1)[0]


def _intestazioni(url, extra=None):
    h = {'User-Agent': UA, 'Referer': _radice(url)}
    if extra:
        h.update(extra)
    return h


def _sha256(s):
    return hashlib.sha256(s.encode('ascii', 'ignore')).hexdigest()


def _rc4(data, key):
    s = list(range(256))
    j = 0
    kb = [ord(c) for c in key]
    for i in range(256):
        j = (j + s[i] + kb[i % len(kb)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for c in bytearray(data):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(c ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _apri_payload(payload, key):
    try:
        b64 = str(payload).replace('-', '+').replace('_', '/')
        raw = base64.b64decode(b64 + '=' * (-len(b64) % 4))
    except Exception:
        return ''
    for k in (key, key + ':lx3'):
        dec = _rc4(raw, k).decode('latin-1')
        if dec[:4] in ('LX2:', 'LX3:'):
            return unquote(dec[4:])
    return ''


def _flag(page, name):
    return scrapertools.find_single_match(page, r'const %s = (true|false)' % name) == 'true'


def _drime(page, page_url):
    h = scrapertools.find_single_match(page, r'const guardaDrimeHash = "([^"]*)"')
    h = re.sub(r'(?i)\.liveac\.', '', h).strip('.').strip()
    if not h:
        return None
    r = httptools.downloadpage(
        page_url.split('#')[0],
        post=urlencode([('action', 'drime_resolve'), ('hash', h)]),
        headers=_intestazioni(page_url, {
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': _base(page_url),
            'Referer': page_url}),
        ignore_response_code=True).data
    try:
        dj = json.loads(r)
    except Exception:
        return None
    if dj and dj.get('stream'):
        return {'streamUrl': dj['stream']}
    return None


def _risolvi(page_url):
    t0 = time.time()
    page = httptools.downloadpage(page_url, headers=_intestazioni(page_url),
                                  ignore_response_code=True).data
    logger.info('loonex: pagina scaricata in %.2f s' % (time.time() - t0))
    if _flag(page, 'isDrime'):
        d = _drime(page, page_url)
        if d:
            return d
    b64ctx = scrapertools.find_single_match(
        page, r'guardaPlaybackContext\s*=\s*JSON\.parse\(atob\("([^"]+)"\)\)')
    if not b64ctx:
        logger.info('loonex: contesto non trovato')
        return None
    cfg = json.loads(base64.b64decode(b64ctx).decode('utf-8'))
    vid_san = scrapertools.find_single_match(page, r'currentVideoIdSanitized\s*=\s*"([^"]*)"')
    vid_raw = scrapertools.find_single_match(
        page, r'currentVideoId\s*=\s*\(function\(\)\s*\{\s*return\s*"([^"]*)"')
    vid = vid_san or vid_raw
    env = '1920x1080:it-IT:UTF-8'
    proof = _sha256('%s:%s:%s:%s' % (cfg['ch'], vid, cfg['ts'], env))
    resp_key = _sha256('%s:resp:%s' % (cfg['ch'], proof))

    if _flag(page, 'isOkru'):
        ptype = 'zk_id'
    elif _flag(page, 'isOkruBypass'):
        ptype = 'zk_bp_id'
    elif _flag(page, 'isRumble'):
        ptype = 'rmb_id'
    elif _flag(page, 'isDrive'):
        ptype = 'driv'
    elif _flag(page, 'isDrime'):
        ptype = 'drim'
    else:
        ptype = 'norm'
    srv = scrapertools.find_single_match(page, r'const activeServer = (\d+)') or '1'
    logger.info('loonex: tipo=%s srv=%s' % (ptype, srv))

    post = urlencode([('action', cfg['act']), ('tok', cfg['tok']), ('poe_ch', cfg['ch']),
                      ('poe_ts', str(cfg['ts'])), ('poe_proof', proof), ('env', env),
                      ('video_id', vid), ('raw_video_id', vid_raw or ''),
                      ('player_type', ptype), ('srv', srv)])
    t1 = time.time()
    r = httptools.downloadpage(
        page_url.split('#')[0], post=post,
        headers=_intestazioni(page_url, {
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            base64.b64decode('WC1Mb29uZXgtUGxheWVyLVNlc3Npb24=').decode(): cfg['nonce'],
            'Origin': _base(page_url),
            'Referer': page_url}),
        ignore_response_code=True).data
    logger.info('loonex: richiesta del flusso in %.2f s' % (time.time() - t1))
    try:
        data = json.loads(r)
    except Exception:
        logger.info('loonex: risposta non valida')
        return None
    if not data or not data.get('ok'):
        logger.info('loonex: risposta negata')
        return None
    if data.get('payload'):
        dec = _apri_payload(data['payload'], resp_key)
        try:
            parsed = json.loads(dec)
        except Exception:
            parsed = None
        if parsed and parsed.get('ok'):
            data = parsed
    return data


def _esterno(page_url):
    page = httptools.downloadpage(page_url, headers=_intestazioni(page_url),
                                  ignore_response_code=True).data
    for frame in re.findall(r'<iframe[^>]*\ssrc="([^"]+)"', page):
        trovato = servertools.get_server_from_url(frame)
        if not trovato:
            continue
        urls, ok, msg = servertools.resolve_video_urls_for_playing(trovato[2], trovato[1])
        if urls:
            return urls
    return []


def _codifica(stream):
    p = urlsplit(stream)
    path = quote(unquote(p.path), safe="/:@!$&'()*+,;=-._~")
    return urlunsplit((p.scheme, p.netloc, path, p.query, ''))


def test_video_exists(page_url):
    # False solo con 404 o 410 veri; in ogni dubbio il video va provato
    page_url = page_url.split('|')[0]
    try:
        risposta = httptools.downloadpage(page_url, headers=_intestazioni(page_url), ignore_response_code=True,
                                          timeout=5)
        if risposta.code in (404, 410):
            return False, config.get_localized_string(70449) % 'Loonex'
    except (IOError, OSError, ValueError) as e:
        logger.info('loonex: test_video_exists %s' % e)
    return True, ''


def get_video_url(page_url, premium=False, user='', password='', video_password=''):
    page_url = page_url.split('|')[0]
    if '/guarda/srv_ext' in page_url:
        return _esterno(page_url)
    stream = ''
    inizio = time.time()
    try:
        data = _risolvi(page_url)
        logger.info('loonex: risoluzione completata in %.2f s' % (time.time() - inizio))
        if data:
            stream = data.get('streamUrl') or ''
            ok = data.get('okruData') or {}
            if not stream or 'start1.mp4' in stream:
                stream = ok.get('hls') or ok.get('prog') or ''
    except Exception:
        import traceback
        logger.info('loonex: errore %s' % traceback.format_exc())
    if not stream or 'start1.mp4' in stream:
        return []
    stream = _codifica(stream)
    if 'rumble.com' in stream:
        return [['hls [Loonex]', stream]]
    base = _base(page_url)
    play = '%s|User-Agent=%s&Referer=%s/&Origin=%s' % (stream, quote_plus(UA), base, base)
    if '.m3u8' in urlsplit(stream).path:
        # HLS: con l'etichetta "hls" S4Me lo passa a inputstream.adaptive (come VixSrc), che gestisce gli spostamenti
        # avanti e indietro. Con "video" lo legge ffmpeg, che sugli HLS firmati si blocca dopo qualche salto
        return [['hls [Loonex]', play]]
    return [['video [Loonex]', play]]
