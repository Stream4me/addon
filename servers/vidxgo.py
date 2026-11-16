# -*- coding: utf-8 -*-

import base64, json, re, threading, time, traceback, uuid
import urllib.parse

from core import httptools
from platformcode import logger


HOST = 'https://v.vidxgo.co'

UA_CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')

PLAY_HEADERS = {
    'User-Agent':      UA_CHROME,
    'Referer':         HOST + '/',
    'Origin':          'https://v.vidxgo.co',
    'Sec-Fetch-Dest':  'empty',
    'Sec-Fetch-Mode':  'cors',
    'Sec-Fetch-Site':  'cross-site',
}

REFRESH_GRACE = 60
RELAY_CONNECT_TIMEOUT = 10
RELAY_READ_TIMEOUT = 30
HB_INTERVALLO = 50
ATTESA_AVVIO = 30
POLL = 2

_PROXY = {'server': None, 'port': 0, 'base': '', 'imdb': '', 'fresh_query': '',
          'dur': 0, 't0': 0.0, 'last_hb': 0.0, 'expire_ms': 0,
          'hb_type': 'movie', 'last_req': 0.0, 'embed_url': ''}
_HB = {'sid': ''}
_REFRESH_LOCK = threading.Lock()
_SESSION = [None]


def _sessione():
    if _SESSION[0] is None:
        import requests
        s = requests.Session()
        s.headers.update(PLAY_HEADERS)
        s.headers['Accept-Encoding'] = 'identity'
        _SESSION[0] = s
    return _SESSION[0]


def _scadenza_vicina():
    exp = _PROXY.get('expire_ms') or 0
    if not exp or not _PROXY.get('embed_url'):
        return False
    if time.time() - _PROXY['t0'] < REFRESH_GRACE:
        return False
    rimasto = (exp / 1000.0 if exp > 10**12 else exp) - time.time()
    return rimasto <= 45


def _refresh_token():
    if not _PROXY.get('embed_url') or not _REFRESH_LOCK.acquire(blocking=False):
        return False
    try:
        url_e, exp_e, _ = extract_embed(_PROXY['embed_url'])
        q = urllib.parse.urlparse(url_e).query if url_e else ''
        if not q:
            return False
        _PROXY['fresh_query'] = q
        if exp_e:
            _PROXY['expire_ms'] = exp_e
        logger.info('vidxgo token rinnovato')
        return True
    except Exception:
        logger.error('vidxgo rinnovo token fallito: ' + traceback.format_exc()[-300:])
        return False
    finally:
        _REFRESH_LOCK.release()


def _send_heartbeat(pos):
    payload = {"sid": _HB['sid'], "v": 2, "imdb": _PROXY['imdb'],
               "type": _PROXY['hb_type'], "pos": int(pos),
               "dur": int(_PROXY.get('dur') or 0),
               "playing": 1, "ref": HOST + "/", "dm": "PC Linux"}
    try:
        httptools.downloadpage(HOST + '/hb', post=json.dumps(payload),
                               headers={'Referer': HOST + '/', 'Origin': HOST,
                                        'Content-Type': 'application/json', 'Accept': '*/*'},
                               timeout=RELAY_CONNECT_TIMEOUT + 1, alfa_s=True)
    except Exception:
        logger.error('vidxgo heartbeat fallito: ' + traceback.format_exc()[-200:])


def _custode(srv):
    """Un solo thread: heartbeat, rinnovo token e chiusura del proxy a fine riproduzione."""
    player = monitor = None
    try:
        import xbmc
        player, monitor = xbmc.Player(), xbmc.Monitor()
    except Exception:
        pass
    visto_play = False
    fermo = 0
    while _PROXY['server'] is srv:
        if monitor is not None:
            if monitor.waitForAbort(POLL):
                break
        else:
            time.sleep(POLL)
        try:
            in_play = bool(player.isPlaying()) if player is not None else False
        except Exception:
            in_play = False
        if in_play:
            visto_play = True
            fermo = 0
            _PROXY['last_req'] = time.time()
            now = time.time()
            if now - _PROXY['last_hb'] >= HB_INTERVALLO:
                _PROXY['last_hb'] = now
                _send_heartbeat(now - _PROXY['t0'])
            if _scadenza_vicina():
                _refresh_token()
        elif visto_play:
            fermo += 1
            if fermo >= 2:
                break
        elif time.time() - _PROXY['last_req'] > ATTESA_AVVIO:
            break
    _chiudi(srv)
    logger.info('vidxgo proxy chiuso')


def _chiudi(srv):
    srv._stopping = True
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:
        pass
    if _PROXY['server'] is srv:
        _PROXY['server'] = None
        _PROXY['port'] = 0


_HOOK = {'fatto': False}


def _installa_aggancio():
    """Dopo lo stop il proxy locale non serve piu: lo si chiude prima di riaprire la finestra dei
    server, e si rallenta il ciclo del 'segna come visto' che altrimenti gira senza pause e
    blocca Kodi. Non si toccano i file di S4Me."""
    if _HOOK['fatto']:
        return
    try:
        from platformcode import platformtools
        originale_finestra = platformtools.serverWindow
        originale_in_riproduzione = platformtools.is_playing

        def serverWindow(item, *a, **k):
            if getattr(item, 'server', '') == 'vidxgo':
                _stop_proxy()
            return originale_finestra(item, *a, **k)

        def is_playing():
            if 'mark_as_watched' in threading.current_thread().name:
                time.sleep(0.5)
            return originale_in_riproduzione()

        platformtools.serverWindow = serverWindow
        platformtools.is_playing = is_playing
        _HOOK['fatto'] = True
    except Exception:
        logger.error('vidxgo: aggancio non attivato: ' + traceback.format_exc()[-200:])


def _stop_proxy():
    if _PROXY['server'] is not None:
        _chiudi(_PROXY['server'])


def _riscrivi_m3u8(text, req_path, query):
    base_dir = req_path.rsplit('/', 1)[0] + '/'
    totale = 0.0

    def locale(u):
        if u.startswith('//'):
            u = 'https:' + u
        if u.startswith('http://') or u.startswith('https://'):
            p = urllib.parse.urlparse(u)
            u = p.path + (('?' + p.query) if p.query else '')
        elif not u.startswith('/'):
            u = urllib.parse.urljoin(base_dir, u)
        if query and '?' not in u:
            u += '?' + query
        return u

    out = []
    for riga in text.splitlines():
        s = riga.strip()
        if not s:
            continue
        if s.startswith('#'):
            if s.startswith('#EXTINF:'):
                try:
                    totale += float(s.split(':')[1].split(',')[0])
                except Exception:
                    pass
            s = re.sub(r'(URI=")([^"]+)(")', lambda m: m.group(1) + locale(m.group(2)) + m.group(3), s)
        else:
            s = locale(s)
        out.append(s)
    if totale:
        _PROXY['dur'] = totale
    return '\n'.join(out) + '\n'


def _start_proxy():
    _stop_proxy()
    import http.server, socketserver

    class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        timeout = 20

        def _scarica(self, url, headers):
            rt = (RELAY_CONNECT_TIMEOUT, RELAY_READ_TIMEOUT)
            r = _sessione().get(url, headers=headers, timeout=rt, stream=True)
            if r.status_code in (403, 429) and _PROXY.get('embed_url') and \
                    time.time() - _PROXY['t0'] > REFRESH_GRACE:
                r.close()
                if _refresh_token():
                    url = _PROXY['base'] + self.path.partition('?')[0] + '?' + _PROXY['fresh_query']
                    r = _sessione().get(url, headers=headers, timeout=rt, stream=True)
            return r

        def _relay(self, con_corpo):
            _PROXY['last_req'] = time.time()
            path = self.path.partition('?')[0]
            url = _PROXY['base'] + path
            if _PROXY['fresh_query']:
                url += '?' + _PROXY['fresh_query']
            h = {'Range': self.headers['Range']} if self.headers.get('Range') else {}
            try:
                r = self._scarica(url, h)
            except Exception as e:
                logger.error('vidxgo relay: %s' % str(e)[:150])
                self.send_error(502)
                return
            try:
                ct = r.headers.get('Content-Type') or ''
                if 'mpegurl' in ct.lower() or path.lower().endswith('.m3u8'):
                    corpo = _riscrivi_m3u8(r.content.decode('utf-8', 'replace'), path,
                                           _PROXY['fresh_query']).encode('utf-8')
                    self.send_response(r.status_code)
                    self.send_header('Content-Type', ct or 'application/vnd.apple.mpegurl')
                    self.send_header('Content-Length', str(len(corpo)))
                    self.end_headers()
                    if con_corpo:
                        self.wfile.write(corpo)
                    return
                self.send_response(r.status_code)
                if ct:
                    self.send_header('Content-Type', ct)
                if r.headers.get('Content-Length'):
                    self.send_header('Content-Length', r.headers['Content-Length'])
                else:
                    self.send_header('Connection', 'close')
                    self.close_connection = True
                if 'Content-Range' in r.headers:
                    self.send_header('Content-Range', r.headers['Content-Range'])
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                if con_corpo:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            self.wfile.write(chunk)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass
            finally:
                r.close()

        def do_GET(self):
            self._relay(True)

        def do_HEAD(self):
            self._relay(False)

        def log_message(self, *a):
            pass

    try:
        srv = _Srv(('127.0.0.1', 0), _Handler)
    except Exception:
        logger.error('vidxgo: impossibile aprire il proxy locale')
        return 0
    _PROXY['port'] = srv.server_address[1]
    _PROXY['server'] = srv
    _PROXY['last_req'] = time.time()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=_custode, args=(srv,), daemon=True).start()
    logger.info('vidxgo proxy su 127.0.0.1:%d' % _PROXY['port'])
    return _PROXY['port']


_XOR_BLOCK_RE = re.compile(r"var\s+\w+\s*=\s*'([^']*)'\s*,\s*d\s*=\s*atob\(\s*'([^']*)'", re.S)
_SCRIPT_RE = re.compile(r'<script[^>]*>(.*?)</script>', re.S | re.I)
_K_RE = re.compile(r"var\s+k\s*=\s*['\"]([^'\"]+)['\"]")
_ATOB_RE = re.compile(r"atob\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _xor_decode(key, b64):
    try:
        decoded = base64.b64decode(b64)
    except Exception:
        return None
    kb = key.encode('utf-8')
    if not kb:
        return None
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(decoded)).decode('utf-8', 'ignore')


def _decode_xor_blocks(page):
    out = []
    seen = set()

    def add(text):
        if text is not None and text not in seen:
            seen.add(text)
            out.append(text)

    for sm in _SCRIPT_RE.finditer(page):
        body = sm.group(1)
        if '(function' not in body:
            continue
        mk = _K_RE.search(body)
        md = _ATOB_RE.search(body)
        if mk and md:
            add(_xor_decode(mk.group(1), md.group(1)))
    for m in _XOR_BLOCK_RE.finditer(page):
        add(_xor_decode(m.group(1), m.group(2)))
    return out


def _leggi_pagina(url, referer, timeout=10):
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
        'Referer': referer,
        'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin', 'Upgrade-Insecure-Requests': '1',
    }
    if urllib.parse.urlparse(referer).netloc != urllib.parse.urlparse(url).netloc:
        headers['Sec-Fetch-Site'] = 'cross-site'
    return httptools.downloadpage(url, headers=headers, timeout=timeout, alfa_s=True)


def extract_embed(embed_url, referer=None, timeout=10):
    """Legge la pagina del player. Restituisce (url m3u8, scadenza, codice http)."""
    resp = _leggi_pagina(embed_url, referer or HOST + '/', timeout)
    codice = resp.code
    if codice != 200:
        logger.error('vidxgo: pagina del player %s (cf-mitigated=%s)'
                     % (str(codice)[:60], (resp.headers or {}).get('cf-mitigated')))
        return None, 0, codice
    for blob in _decode_xor_blocks(resp.data or ''):
        sm = re.search(r'currentSrc\s*=\s*["\'](https?:[^"\']+?\.m3u8[^"\']*)["\']',
                       blob, re.S | re.I)
        if not sm:
            sm = re.search(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', blob)
        if sm:
            me = re.search(r'let\s+currentExpire\s*=\s*(\d+)', blob)
            return sm.group(1).replace('\\', ''), (int(me.group(1)) if me else 0), codice
    logger.error('vidxgo: m3u8 non trovato nella pagina del player')
    return None, 0, codice


def get_embed_page(page_url, referer=None):
    try:
        resp = _leggi_pagina(page_url, referer or (HOST + '/'), 10)
        if resp.code == 200:
            return resp.data or ''
        logger.error('vidxgo get_embed_page: risposta %s' % str(resp.code)[:60])
    except Exception:
        logger.error('vidxgo get_embed_page: ' + traceback.format_exc())
    return ''


SEASONS_MAX = 20


def episodes_api(token):
    info = {'mode': 'tv', 'episodes': [], 'details': []}
    try:
        hdrs = {'Referer': HOST + '/', 'Accept': 'application/json, text/plain, */*'}
        for sn in range(1, SEASONS_MAX + 1):
            url = '%s/seasons.php?imdb=%s&season=%d' % (HOST, token, sn)
            r = httptools.downloadpage(url, headers=hdrs, timeout=10, alfa_s=True)
            if r.code != 200:
                break
            try:
                data = json.loads(r.data)
            except Exception:
                break
            if data.get('ok') != 1:
                break
            got = 0
            for ep in data.get('episodes') or []:
                try:
                    en = int(ep.get('number'))
                except Exception:
                    continue
                info['episodes'].append((sn, en))
                info['details'].append({'s': sn, 'e': en,
                                        'name': ep.get('name') or '',
                                        'overview': ep.get('overview') or '',
                                        'still': ep.get('still') or ''})
                got += 1
            if not got:
                break
        if not info['episodes']:
            return None
        info['episodes'] = sorted(set(info['episodes']))
        return info
    except Exception:
        logger.error('vidxgo episodes_api: ' + traceback.format_exc())
        return None


MSG_CDN = 'Attualmente non disponibile su Vidxgo.'
_EMBED_CACHE = {}


def _leggi_embed(page_url):
    """Una sola lettura della pagina per test_video_exists e get_video_url."""
    c = _EMBED_CACHE.get(page_url)
    if c and time.time() - c[0] < 60:
        return c[1]
    try:
        esito = extract_embed(page_url, timeout=6)
    except Exception:
        logger.error('vidxgo: lettura del player: ' + traceback.format_exc()[-200:])
        esito = (None, 0, None)
    _EMBED_CACHE[page_url] = (time.time(), esito)
    return esito


def test_video_exists(page_url):
    try:
        if urllib.parse.urlparse(page_url).path.strip('/'):
            url, _, codice = _leggi_embed(page_url)
            if not url:
                if codice in (404, 410):
                    return False, 'Contenuto non disponibile su vidxgo'
                return False, MSG_CDN
    except Exception:
        logger.error('vidxgo test_video_exists: ' + traceback.format_exc()[-150:])
    return True, ''


def get_video_url(page_url, premium=False, user='', password='', video_password=''):
    logger.info('vidxgo.get_video_url: %s' % page_url)
    try:
        _installa_aggancio()
        _stop_proxy()
        parti = urllib.parse.urlparse(page_url).path.strip('/').split('/')
        stream_url, scadenza, _ = _leggi_embed(page_url)
        if not parti[0] or not stream_url:
            logger.error('vidxgo: nessun URL trovato')
            return []
        u = urllib.parse.urlparse(stream_url)
        _PROXY.update(imdb=parti[0], dur=0, embed_url=page_url, expire_ms=scadenza,
                      fresh_query=u.query, base=u.scheme + '://' + u.netloc,
                      hb_type='series' if len(parti) >= 3 and parti[1].isdigit() and parti[2].isdigit() else 'movie',
                      t0=time.time(), last_hb=time.time())
        _HB['sid'] = str(uuid.uuid4())
        port = _start_proxy()
        if not port:
            return []
        return [['vidxgo', 'http://127.0.0.1:%d%s' % (port, u.path)]]
    except Exception:
        logger.error('vidxgo: ' + traceback.format_exc())
        return []
