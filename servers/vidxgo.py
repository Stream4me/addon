# -*- coding: utf-8 -*-
# Server vidxgo per S4me

import base64, json, os, re, ssl, tempfile, threading, time, traceback, uuid
import urllib.parse
import cloudscraper

from platformcode import logger

HOST = 'https://v.vidxgo.co'
REF_SITE = 'https://altadefinizionex.live'

UA_CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
UA_FF = 'Mozilla/5.0 (X11; Linux x86_64; rv:155.0) Gecko/20100101 Firefox/155.0'

PLAY_HEADERS = {
    'User-Agent':      UA_CHROME,
    'Referer':         HOST + '/',
    'Origin':          'https://v.vidxgo.co',
    'Sec-Fetch-Dest':  'empty',
    'Sec-Fetch-Mode':  'cors',
    'Sec-Fetch-Site':  'cross-site',
}

WD_POLL = 3
WD_IDLE_PLAYED = 10
WD_IDLE_NEVER = 30

REFRESH_GRACE = 60

CDN_MIN_INTERVAL = 1.0

RELAY_CONNECT_TIMEOUT = 10
RELAY_READ_TIMEOUT = 30

_PROXY = {'server': None, 'port': 0, 'base': '',
          't_url': '', 'imdb': '', 'fresh_query': '', 'dur': 0,
          't0': 0.0, 'last_hb': 0.0, 'last_mint': 0.0, 'expire_ms': 0,
          'hb_type': 'movie',
          'master_path': '',
          'last_req': 0.0, 'played': False,
          'host': ''}
_HB = {'sid': ''}
SEGMENTS_DIRECT = False

_RELAY_SESSIONS = {}
_RELAY_CAND = {}
_RELAY_DIRECT = set()
_LAST_REFRESH = [0.0]
_BG_MAINT = [0.0]
_PLCACHE = {}
_PLCACHE_TTL = 120

_NET_FAIL = [0.0, 0]
_REFRESH_LOCK = threading.Lock()

_HEAL = {'t': 0.0, 'busy': False}
_PATH_MAP = ['', '']


_RATELIMIT_FILE = os.path.join(tempfile.gettempdir(), 'alfa_vidxgo_ratelimit.json')


def _net_down():
    if _NET_FAIL[1] == 0:
        return False
    backoff = min(10 * (2 ** min(_NET_FAIL[1] - 1, 4)), 160)
    return time.time() - _NET_FAIL[0] < backoff


def _is_net_error(e):
    s = str(e)
    tn = type(e).__name__
    if 'Name or service not known' in s or 'Temporary failure' in s:
        return True
    if 'Timeout' in tn:
        return True
    if 'timed out' in s.lower():
        return True
    if 'ConnectionError' in tn or 'gaierror' in tn:
        return True
    return False


def _net_fail():
    _NET_FAIL[0] = time.time()
    _NET_FAIL[1] += 1


def _net_ok():
    _NET_FAIL[1] = 0


def _ratelimit_load():
    try:
        with open(_RATELIMIT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _ratelimit_save(data):
    try:
        with open(_RATELIMIT_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def _ratelimit_mark(host):
    data = _ratelimit_load()
    data[host] = time.time()
    _ratelimit_save(data)


def _ratelimit_wait(host):
    data = _ratelimit_load()
    last = data.get(host, 0)
    delta = time.time() - last
    if delta < CDN_MIN_INTERVAL:
        wait = CDN_MIN_INTERVAL - delta
        logger.info('vidxgo rate-limit backoff: attendo %.1fs (%s)' % (wait, host))
        time.sleep(wait)


_TLS = {'mode': None, 'session': None}
_TLS_CACHE_FILE = os.path.join(tempfile.gettempdir(), 'alfa_vidxgo_tls.json')


def _make_tls_adapter(ciphers=None, ver_range=None, curve=None):
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context
    except Exception:
        return None

    class _A(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            try:
                ctx = create_urllib3_context(ciphers=ciphers) if ciphers else create_urllib3_context()
                if ver_range:
                    ctx.minimum_version, ctx.maximum_version = ver_range
                if curve:
                    ctx.set_ecdh_curve(curve)
                kw['ssl_context'] = ctx
            except Exception:
                pass
            return super().init_poolmanager(*a, **kw)
    return _A()


_TLS_CANDIDATES = [
    ('default',  None, None, None),
    ('sec1',     'DEFAULT@SECLEVEL=1', None, None),
    ('p256',     None, None, 'prime256v1'),
    ('tls12pin', None, (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2), None),
    ('sec0',     'ALL:@SECLEVEL=0',    None, None),
]


def _tls_cache_load():
    try:
        with open(_TLS_CACHE_FILE) as f:
            d = json.load(f)
        ver = (ssl.TLSVersion[d['vmin']], ssl.TLSVersion[d['vmax']]) if d.get('vmin') else None
        return (d['name'], d.get('ciphers'), ver, d.get('curve'))
    except Exception:
        return None


def _tls_cache_save(cand):
    try:
        name, ciphers, ver, curve = cand
        with open(_TLS_CACHE_FILE, 'w') as f:
            json.dump({'name': name, 'ciphers': ciphers,
                       'vmin': ver[0].name if ver else None,
                       'vmax': ver[1].name if ver else None,
                       'curve': curve}, f)
    except Exception:
        pass


def _build_vidxgo_session(cand):
    _, ciphers, ver, curve = cand
    s = cloudscraper.create_scraper()
    ad = _make_tls_adapter(ciphers, ver, curve)
    if ad is not None:
        s.mount('https://', ad)
    return s


def _cf_blocked(r):
    if r.status_code not in (403, 429, 503):
        return False
    if 'cf-mitigated' in r.headers:
        return True
    head = r.text[:3000].lower()
    return ('no-js' in head and 'oldie' in head) or \
           'cloudflare' in head or 'just a moment' in head


def _vidxgo_session():
    if _TLS.get('session') is not None:
        return _TLS['session']
    return _build_vidxgo_session(_TLS['mode'] or _TLS_CANDIDATES[0])


def _vidxgo_resolve(url_candidates, headers):
    saved = _tls_cache_load()
    tried_full = False
    while True:
        if saved:
            order = [saved]
        else:
            if tried_full:
                logger.error('vidxgo resolve: nessuna fingerprint accettata')
                return None, None, None
            order = list(_TLS_CANDIDATES)
            tried_full = True
        was_cached = saved is not None
        saved = None
        for cand in order:
            s = _build_vidxgo_session(cand)
            for u in url_candidates:
                try:
                    r = s.get(u, headers=headers, timeout=10)
                    if r.status_code == 200:
                        _TLS['mode'] = cand
                        _TLS['session'] = s
                        _tls_cache_save(cand)
                        return r, u, s
                    if _cf_blocked(r):
                        if was_cached:
                            logger.info('vidxgo resolve: winner in cache bloccato -> sweep')
                        break
                    if r.status_code in (404, 410):
                        return None, None, None
                except Exception as e:
                    logger.error('vidxgo resolve cand=%s: %s' % (cand[0], str(e)[:150]))


def _relay_cand_for(host):
    name = _RELAY_CAND.get(host)
    if name:
        for c in _TLS_CANDIDATES:
            if c[0] == name:
                return c
    return _TLS['mode'] or _TLS_CANDIDATES[0]


def _relay_session(cand):
    sess = _RELAY_SESSIONS.get(cand[0])
    if sess is None:
        import requests
        from requests.adapters import HTTPAdapter
        try:
            from urllib3.util.retry import Retry
            retry = Retry(total=2, connect=2, read=0, backoff_factor=0.2)
        except Exception:
            retry = 0
        sess = requests.Session()
        sess.headers.update(PLAY_HEADERS)
        sess.headers['Accept-Encoding'] = 'identity'
        _, ciphers, ver, curve = cand
        ad = _make_tls_adapter(ciphers, ver, curve)
        if ad is not None:
            try:
                ad.max_retries = retry
            except Exception:
                pass
            sess.mount('https://', ad)
        else:
            sess.mount('https://', HTTPAdapter(max_retries=retry,
                                               pool_connections=8, pool_maxsize=8))
        sess.mount('http://', HTTPAdapter(max_retries=retry,
                                          pool_connections=8, pool_maxsize=8))
        _RELAY_SESSIONS[cand[0]] = sess
    return sess


def _reset_relay_sessions():
    pass


def _prefetch_playlists():
    try:
        time.sleep(0.1)
        from urllib.parse import urlparse as _up
        base = _PROXY['base']
        sess = _relay_session(_relay_cand_for(_up(base).netloc))
        q = _PROXY.get('fresh_query', '')

        def fetch(path):
            url = base + path + (('?' + q) if q else '')
            try:
                r = sess.get(url, timeout=(RELAY_CONNECT_TIMEOUT, 30))
            except Exception:
                return None
            if r.status_code == 200:
                _PLCACHE[path] = (time.time(), r.text)
                return r.text
            return None

        master_path = _PROXY.get('master_path', '')
        if not master_path.lower().endswith('.m3u8'):
            return
        txt = fetch(master_path)
        if not txt:
            return
        for line in txt.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            p = urllib.parse.urljoin(base + master_path, line)
            media_path = p[len(base):] if p.startswith(base) \
                else urllib.parse.urlparse(p).path
            if media_path and media_path not in _PLCACHE:
                fetch(media_path)
            break
    except Exception:
        logger.error('vidxgo prefetch crashed: ' + traceback.format_exc())


def _refresh_token():
    if time.time() - _LAST_REFRESH[0] < 1.5:
        return True
    if _net_down():
        return False
    if not _REFRESH_LOCK.acquire(blocking=False):
        return True
    try:
        try:
            s = _vidxgo_session()
            r = s.get(_PROXY['t_url'],
                      headers={'User-Agent': UA_FF, 'Referer': HOST + '/',
                               'Accept': 'application/json, text/plain, */*'},
                      timeout=RELAY_CONNECT_TIMEOUT + 1)
            if r.status_code == 200:
                data = r.json()
                new_url = data.get('url') or ''
                if new_url:
                    q = urllib.parse.urlparse(new_url).query
                    if q:
                        _PROXY['fresh_query'] = q
                    exp = data.get('expire')
                    if exp:
                        try:
                            _PROXY['expire_ms'] = int(exp)
                        except Exception:
                            pass
                    _LAST_REFRESH[0] = time.time()
                    _net_ok()
                    logger.info('vidxgo token refreshed')
                    return True
            logger.error('vidxgo token refresh failed: HTTP ' + str(r.status_code))
        except Exception as e:
            if _is_net_error(e):
                _net_fail()
                logger.error('vidxgo token refresh: rete irraggiungibile '
                             '(backoff #%d, %s)' % (_NET_FAIL[1], str(e)[:80]))
            else:
                logger.error('vidxgo token refresh crashed: ' + traceback.format_exc())
        return False
    finally:
        _REFRESH_LOCK.release()


def _maybe_refresh_by_expire():
    exp = _PROXY.get('expire_ms') or 0
    if not exp or not _PROXY.get('t_url'):
        return
    if time.time() - _PROXY.get('t0', time.time()) < REFRESH_GRACE:
        return
    remaining = (exp / 1000.0) - time.time() if exp > 10**12 else (exp - time.time())
    if remaining <= 15:
        _refresh_token()


def _hot_heal(old_host):
    try:
        if not _PROXY.get('t_url'):
            return False
        if _net_down():
            return False
        if time.time() - _HEAL['t'] < 30.0:
            return False
        _HEAL['t'] = time.time()

        hdrs = {'User-Agent': UA_FF, 'Referer': HOST + '/',
                'Accept': 'application/json, text/plain, */*'}
        r, t_url, _s = _vidxgo_resolve([_PROXY['t_url']], hdrs)
        if r is None:
            return False
        data = r.json()
        new_url = data.get('url') or ''
        if not new_url:
            return False
        exp = data.get('expire')
        if exp:
            try:
                _PROXY['expire_ms'] = int(exp)
            except Exception:
                pass
        _PROXY['t_url'] = t_url
        _PROXY['fresh_query'] = urllib.parse.urlparse(new_url).query

        u = urllib.parse.urlparse(new_url)
        new_base = u.scheme + '://' + u.netloc
        if new_base != _PROXY['base']:
            old_dir = _PROXY.get('master_path', '').rsplit('/', 1)[0]
            new_dir = u.path.rsplit('/', 1)[0]
            if old_dir != new_dir:
                _PATH_MAP[0], _PATH_MAP[1] = old_dir, new_dir
            else:
                _PATH_MAP[0] = _PATH_MAP[1] = ''
            logger.info('vidxgo hot-heal: CDN %s -> %s' % (_PROXY['base'], new_base))
            _PROXY['base'] = new_base
            _PROXY['master_path'] = u.path
            _PROXY['host'] = u.netloc
            _PLCACHE.clear()
        else:
            logger.info('vidxgo hot-heal: stesso CDN %s, token rinfrescato' % new_base)
        return True
    except Exception:
        logger.error('vidxgo hot-heal: ' + traceback.format_exc())
        return False


def _maintenance_due():
    exp = _PROXY.get('expire_ms') or 0
    if not exp or not _PROXY.get('t_url'):
        return False
    if time.time() - _PROXY.get('t0', time.time()) < REFRESH_GRACE:
        return False
    remaining = (exp / 1000.0) - time.time() if exp > 10**12 else (exp - time.time())
    return remaining <= 45


def _maintenance_do(pos, need_hb):
    try:
        if need_hb:
            _send_heartbeat(pos)
            _PROXY['last_hb'] = time.time()
        if _maintenance_due():
            _refresh_token()
    except Exception:
        logger.error('vidxgo maintenance: ' + traceback.format_exc())


def _send_heartbeat(pos):
    if _net_down():
        return
    try:
        s = _vidxgo_session()
        payload = {"sid": _HB['sid'], "v": 2, "imdb": _PROXY.get('imdb', ''),
                   "type": _PROXY.get('hb_type', 'movie'), "pos": int(pos),
                   "dur": int(_PROXY.get('dur') or 0),
                   "playing": 1, "ref": REF_SITE + "/", "dm": "PC Linux"}
        s.post(HOST + '/hb', json=payload,
               headers={'User-Agent': UA_FF, 'Referer': HOST + '/',
                        'Origin': HOST, 'Content-Type': 'application/json',
                        'Accept': '*/*'}, timeout=RELAY_CONNECT_TIMEOUT + 1)
        _net_ok()
    except Exception as e:
        if _is_net_error(e):
            _net_fail()
            logger.error('vidxgo hb: rete irraggiungibile (backoff #%d)'
                         % _NET_FAIL[1])
        else:
            logger.error('vidxgo hb failed: ' + traceback.format_exc())


def _proxy_watchdog(srv):
    player = None
    monitor = None
    try:
        import xbmc
        player = xbmc.Player()
        monitor = xbmc.Monitor()
    except Exception:
        pass
    while True:
        if monitor is not None:
            if monitor.waitForAbort(WD_POLL):
                break
        else:
            time.sleep(WD_POLL)
        if _PROXY['server'] is not srv:
            return
        if player is not None and player.isPlaying():
            _PROXY['played'] = True
            _PROXY['last_req'] = time.time()
            continue
        idle = time.time() - _PROXY.get('last_req', 0.0)
        if idle < (WD_IDLE_PLAYED if _PROXY.get('played') else WD_IDLE_NEVER):
            continue
        if player is not None and player.isPlaying():
            continue
        break
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:
        pass
    if _PROXY['server'] is srv:
        _PROXY['server'] = None
        _PROXY['port'] = 0
    _PLCACHE.clear()
    logger.info('vidxgo proxy stopped (idle watchdog)')


def _stop_proxy():
    old = _PROXY['server']
    if old is not None:
        try:
            old.shutdown()
            old.server_close()
        except Exception:
            pass
        _PROXY['server'] = None
        _PROXY['port'] = 0
        _PLCACHE.clear()
        time.sleep(0.05)


def _start_proxy():
    _stop_proxy()
    if _PROXY['server'] is None:
        import http.server, socketserver, threading
        from urllib.parse import urljoin, urlparse

        class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request, client_address):
                import sys, socket
                if sys.exc_info()[0] in (ConnectionResetError, BrokenPipeError,
                                         ConnectionAbortedError,
                                         socket.timeout, TimeoutError):
                    return
                super().handle_error(request, client_address)

        class _Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            timeout = 20

            def _to_proxy(self, u, base_dir, inherit_q):
                if u.startswith('//'):
                    p = urlparse('https:' + u)
                    u = p.path + (('?' + p.query) if p.query else '')
                elif u.startswith('http://') or u.startswith('https://'):
                    p = urlparse(u)
                    u = p.path + (('?' + p.query) if p.query else '')
                elif not u.startswith('/'):
                    u = urljoin(base_dir, u)
                if inherit_q and '?' not in u:
                    u += '?' + inherit_q
                return u

            def _rewrite_m3u8(self, text, req_path, req_q):
                base_dir = req_path.rsplit('/', 1)[0] + '/'
                out, n_seg, total = [], 0, 0.0
                for line in text.splitlines():
                    s = line.strip()
                    if not s:
                        continue
                    if s.startswith('#'):
                        if s.startswith('#EXTINF:'):
                            n_seg += 1
                            try:
                                total += float(s.split(':')[1].split(',')[0])
                            except Exception:
                                pass
                        line = re.sub(r'(URI=")([^"]+)(")',
                                      lambda m: m.group(1) +
                                      self._to_proxy(m.group(2), base_dir, req_q) +
                                      m.group(3), line)
                        out.append(line)
                    else:
                        if SEGMENTS_DIRECT and not s.split('?')[0].lower().endswith('.m3u8'):
                            out.append(s if s.startswith('http')
                                       else urljoin(_PROXY['base'] + base_dir, s))
                        else:
                            out.append(self._to_proxy(s, base_dir, req_q))
                if n_seg and total:
                    _PROXY['dur'] = total
                return '\n'.join(out) + '\n'

            def _relay(self, with_body):
                _PROXY['last_req'] = time.time()
                if not _PROXY['base']:
                    self.send_error(503)
                    return
                h = {}
                if self.headers.get('Range'):
                    h['Range'] = self.headers['Range']

                now = time.time()
                need_hb = (now - _PROXY.get('last_hb', 0) >= 50)
                if need_hb or _maintenance_due():
                    if now - _BG_MAINT[0] > 2.0:
                        _BG_MAINT[0] = now
                        import threading as _th
                        _th.Thread(target=_maintenance_do,
                                   args=(now - _PROXY.get('t0', now), need_hb),
                                   daemon=True).start()

                req_path, _, _ = self.path.partition('?')

                host_up = urllib.parse.urlparse(_PROXY['base']).netloc
                sess = _relay_session(_relay_cand_for(host_up))

                if req_path.lower().endswith('.m3u8'):
                    _ratelimit_wait(host_up)

                req_up = req_path
                if _PATH_MAP[0] and req_path.startswith(_PATH_MAP[0]):
                    req_up = _PATH_MAP[1] + req_path[len(_PATH_MAP[0]):]

                if host_up in _RELAY_DIRECT:
                    durl = _PROXY['base'] + req_up
                    if _PROXY.get('fresh_query'):
                        durl += '?' + _PROXY['fresh_query']
                    self.send_response(302)
                    self.send_header('Location', durl)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return

                ent = _PLCACHE.get(req_path)
                if ent is not None and (time.time() - ent[0]) < _PLCACHE_TTL:
                    try:
                        payload = self._rewrite_m3u8(ent[1], req_path,
                                                     _PROXY.get('fresh_query', '')).encode('utf-8')
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        if with_body:
                            self.wfile.write(payload)
                    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                        pass
                    return

                url = _PROXY['base'] + req_up
                if _PROXY.get('fresh_query'):
                    url += '?' + _PROXY['fresh_query']

                rt = (RELAY_CONNECT_TIMEOUT, RELAY_READ_TIMEOUT)
                try:
                    r = sess.get(url, headers=h, timeout=rt, stream=True)

                    if r.status_code == 403 and _PROXY.get('t_url') and \
                            (time.time() - _PROXY.get('t0', time.time())) > REFRESH_GRACE:
                        try:
                            r.close()
                        except Exception:
                            pass
                        if _refresh_token():
                            url = _PROXY['base'] + req_up + '?' + _PROXY['fresh_query']
                            r = sess.get(url, headers=h, timeout=rt, stream=True)

                    if r.status_code in (403, 429):
                        logger.error('vidxgo upstream %s -> HTTP %s: ruoto fingerprint'
                                     % (host_up, r.status_code))
                        if not _net_down():
                            for cand in _TLS_CANDIDATES:
                                if cand[0] == _relay_cand_for(host_up)[0]:
                                    continue
                                s2 = _relay_session(cand)
                                try:
                                    r2 = s2.get(url, headers=h, timeout=rt, stream=True)
                                    if r2.status_code == 200:
                                        _RELAY_CAND[host_up] = cand[0]
                                        try:
                                            r.close()
                                        except Exception:
                                            pass
                                        r = r2
                                        logger.info('vidxgo relay winner [%s] per %s'
                                                    % (cand[0], host_up))
                                        break
                                    try:
                                        r2.close()
                                    except Exception:
                                        pass
                                except Exception:
                                    pass

                    if r.status_code in (403, 429) and host_up not in _RELAY_DIRECT \
                            and not _HEAL.get('busy') and not _net_down():
                        _HEAL['busy'] = True
                        import threading as _th

                        def _heal_worker(host=host_up):
                            try:
                                _hot_heal(host)
                            finally:
                                _HEAL['busy'] = False
                        _th.Thread(target=_heal_worker, daemon=True).start()
                        try:
                            r.close()
                        except Exception:
                            pass
                        logger.info('vidxgo heal in background (Kodi ritentera)')
                        self.send_error(503)
                        return

                    if r.status_code in (403, 429):
                        cur_host = urllib.parse.urlparse(_PROXY['base']).netloc
                        if cur_host not in _RELAY_DIRECT:
                            _RELAY_DIRECT.add(cur_host)
                            _ratelimit_mark(cur_host)
                            logger.error('vidxgo CDN %s blocca tutte le fingerprint '
                                         '-> DIRECT mode' % cur_host)
                            try:
                                r.close()
                            except Exception:
                                pass
                            _refresh_token()
                            durl = _PROXY['base'] + req_up
                            if _PROXY.get('fresh_query'):
                                durl += '?' + _PROXY['fresh_query']
                            self.send_response(302)
                            self.send_header('Location', durl)
                            self.send_header('Content-Length', '0')
                            self.end_headers()
                            return
                except Exception as e:
                    if _is_net_error(e):
                        _net_fail()
                        logger.error('vidxgo relay: rete irraggiungibile '
                                     '(backoff #%d, %s)' % (_NET_FAIL[1], str(e)[:90]))
                    else:
                        logger.error('vidxgo relay exc: %s' % str(e)[:150])
                    try:
                        self.send_error(502)
                    except Exception:
                        pass
                    return

                ct = r.headers.get('Content-Type') or ''
                is_pl = ('mpegurl' in ct.lower()) or req_path.lower().endswith('.m3u8')
                try:
                    if is_pl and with_body:
                        text = r.content.decode('utf-8', 'replace')
                        if r.status_code == 200:
                            _PLCACHE[req_path] = (time.time(), text)
                        payload = self._rewrite_m3u8(text, req_path,
                                                     _PROXY.get('fresh_query', '')).encode('utf-8')
                        self.send_response(r.status_code)
                        self.send_header('Content-Type', ct or 'application/vnd.apple.mpegurl')
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    else:
                        self.send_response(r.status_code)
                        if ct:
                            self.send_header('Content-Type', ct)
                        cl = r.headers.get('Content-Length')
                        if cl:
                            self.send_header('Content-Length', cl)
                        else:
                            self.send_header('Connection', 'close')
                            self.close_connection = True
                        if 'Content-Range' in r.headers:
                            self.send_header('Content-Range', r.headers['Content-Range'])
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        if with_body:
                            for chunk in r.iter_content(chunk_size=256 * 1024):
                                if chunk:
                                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    pass
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass

            def do_GET(self):
                self._relay(True)

            def do_HEAD(self):
                self._relay(False)

            def log_message(self, *a):
                pass

        try:
            srv = _Srv(('127.0.0.1', 0), _Handler)
        except Exception:
            srv = None
        if srv is None:
            logger.error('vidxgo proxy bind failed')
            return 0
        _PROXY['port'] = srv.server_address[1]
        _PROXY['server'] = srv
        _PROXY['last_req'] = time.time()
        _PROXY['played'] = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        threading.Thread(target=_proxy_watchdog, args=(srv,), daemon=True).start()
        logger.info('vidxgo proxy started on 127.0.0.1:%d' % _PROXY['port'])
    return _PROXY['port']


_XOR_BLOCK_RE = re.compile(r"var\s+\w+\s*=\s*'([^']*)'\s*,\s*d\s*=\s*atob\(\s*'([^']*)'", re.S)


def _decode_xor_blocks(page):
    out = []
    for m in _XOR_BLOCK_RE.finditer(page):
        key, b64 = m.group(1), m.group(2)
        try:
            decoded = base64.b64decode(b64)
        except Exception:
            continue
        kb = key.encode('utf-8')
        if not kb:
            continue
        out.append(bytes(b ^ kb[i % len(kb)]
                         for i, b in enumerate(decoded)).decode('utf-8', 'ignore'))
    return out


def extract_m3u8_from_embed(session, embed_url, referer=None):
    headers = {
        'User-Agent': UA_FF,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
        'Referer': referer or REF_SITE + '/',
        'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin', 'Upgrade-Insecure-Requests': '1',
    }
    resp = session.get(embed_url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception('Embed page returned %s' % resp.status_code)
    blobs = _decode_xor_blocks(resp.text)
    for blob in blobs:
        sm = re.search(r'currentSrc\s*=\s*["\'](https?:[^"\']+?\.m3u8[^"\']*)["\']',
                       blob, re.S | re.I)
        if not sm:
            sm = re.search(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', blob)
        if sm:
            return sm.group(1).replace('\\', '')
    raise Exception('m3u8 non trovato in %d blocchi XOR' % len(blobs))


def get_embed_page(page_url, referer=None):
    headers = {
        'User-Agent': UA_FF,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
        'Referer': referer or (REF_SITE + '/'),
        'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin', 'Upgrade-Insecure-Requests': '1',
    }
    try:
        r, _u, _s = _vidxgo_resolve([page_url], headers)
        if r is not None:
            return r.text
    except Exception:
        logger.error('vidxgo get_embed_page: ' + traceback.format_exc())
    return ''


_D2B_MODE_RE = re.compile(r'<meta\s+name="d2b-mode"\s+content="(\w+)"')
_CURRENT_RE = re.compile(r'current\s*=\s*\{\s*s:\s*(\d+)\s*,\s*e:\s*(\d+)')
_SCACHE_RE = re.compile(r'seasonCache\s*=\s*\{(.+?)\};', re.S)
_EP_N_RE = re.compile(r'"n"\s*:\s*(\d+)')
_SCACHE_KEY_RE = re.compile(r'(?:^|[,{])\s*(\d+)\s*:\s*\[')


def _parse_season_cache(sc_text, default_season):
    pairs = set()
    parts = _SCACHE_KEY_RE.split(sc_text)
    if len(parts) > 1:
        it = iter(parts[1:])
        for key, body in zip(it, it):
            try:
                sn = int(key)
            except Exception:
                continue
            for n in _EP_N_RE.findall(body):
                pairs.add((sn, int(n)))
    else:
        for n in _EP_N_RE.findall(sc_text):
            pairs.add((default_season, int(n)))
    return pairs


_SEASONS_ARR_RE = re.compile(r'seasons\s*:\s*(\[\s*\{[^\]]*\}\s*\])')


def probe(token):
    info = {'mode': '', 'episodes': []}
    try:
        embed = get_embed_page(HOST + '/' + str(token))
        if not embed:
            return info
        m = _D2B_MODE_RE.search(embed)
        info['mode'] = m.group(1) if m else 'movie'
        if info['mode'] != 'tv':
            return info

        def parse_page(page):
            pairs = set()
            for blob in _decode_xor_blocks(page):
                mc = _CURRENT_RE.search(blob)
                ds = int(mc.group(1)) if mc else 1
                ms = _SCACHE_RE.search(blob)
                if ms:
                    pairs |= _parse_season_cache(ms.group(1), ds)
            return pairs

        pairs = parse_page(embed)
        seasons_meta = []
        for blob in _decode_xor_blocks(embed):
            for msm in _SEASONS_ARR_RE.finditer(blob):
                for sn, cnt in re.findall(r'"n"\s*:\s*(\d+)\s*,\s*"count"\s*:\s*(\d+)',
                                          msm.group(1)):
                    seasons_meta.append((int(sn), int(cnt)))

        covered = {s for s, _ in pairs}
        for sn, cnt in sorted(set(seasons_meta)):
            if sn in covered:
                continue
            emb2 = get_embed_page('%s/%s/%d/1' % (HOST, token, sn))
            if not emb2:
                continue
            got = parse_page(emb2)
            pairs |= got

        info['episodes'] = sorted(pairs)
        return info
    except Exception:
        logger.error('vidxgo probe: ' + traceback.format_exc())
        return info


def _tv_default_episode(token):
    try:
        embed = get_embed_page(HOST + '/' + str(token))
        if not embed:
            return None
        m = _D2B_MODE_RE.search(embed)
        if not m or m.group(1) != 'tv':
            return None
        cur = _CURRENT_RE.search(embed)
        cs = int(cur.group(1)) if cur else 1
        ce = int(cur.group(2)) if cur else 1
        sc = _SCACHE_RE.search(embed)
        if not sc:
            return (cs, ce)
        eps = [int(n) for n in _EP_N_RE.findall(sc.group(1))]
        if not eps:
            return (cs, ce)
        return (cs, ce if ce in eps else max(eps))
    except Exception:
        logger.error('vidxgo _tv_default_episode: ' + traceback.format_exc())
        return None


def test_video_exists(page_url):
    return True, ''


def get_video_url(page_url, premium=False, user='', password='', video_password=''):
    logger.info('vidxgo.get_video_url: %s' % page_url)
    try:
        path_parts = urllib.parse.urlparse(page_url).path.strip('/').split('/')
        token = path_parts[0] if path_parts and path_parts[0] else ''
        if not token:
            logger.error('vidxgo: token non trovato')
            return []
        is_episode = len(path_parts) >= 3 and path_parts[1].isdigit() and path_parts[2].isdigit()

        _PROXY['imdb'] = token
        _PROXY['dur'] = 0
        _PROXY['fresh_query'] = ''
        _PROXY['t_url'] = ''
        _PROXY['expire_ms'] = 0
        _PROXY['hb_type'] = 'series' if is_episode else 'movie'

        _HEAL['t'] = 0.0
        _HEAL['busy'] = False
        _PATH_MAP[0] = _PATH_MAP[1] = ''

        if is_episode:
            candidates = [HOST + '/t/' + '/'.join(path_parts[:3]),
                          HOST + '/t/' + '/'.join(path_parts[:3]) + '?se=0']
        else:
            candidates = [HOST + '/t/' + token]

        stream_url = None
        try:
            hdrs = {'User-Agent': UA_FF, 'Referer': page_url,
                    'Accept': 'application/json, text/plain, */*'}
            r, t_url, _s = _vidxgo_resolve(candidates, hdrs)
            if r is not None:
                try:
                    data = r.json()
                    stream_url = data.get('url')
                    exp = data.get('expire')
                    if exp:
                        try:
                            _PROXY['expire_ms'] = int(exp)
                        except Exception:
                            pass
                except Exception:
                    logger.error('vidxgo /t/ non-JSON: ' + r.text[:200])
                    stream_url = None
                else:
                    if stream_url:
                        _PROXY['t_url'] = t_url
                        _PROXY['fresh_query'] = urllib.parse.urlparse(stream_url).query
        except Exception:
            logger.error('vidxgo resolve failed: ' + traceback.format_exc())

        if not stream_url and not is_episode:
            eps = _tv_default_episode(token)
            if eps:
                s0, e0 = eps
                logger.info('vidxgo token nudo = serie, provo /t/%s/%d/%d'
                            % (token, s0, e0))
                _PROXY['hb_type'] = 'series'
                try:
                    hdrs = {'User-Agent': UA_FF, 'Referer': HOST + '/',
                            'Accept': 'application/json, text/plain, */*'}
                    r, t_url, _s = _vidxgo_resolve(
                        [HOST + '/t/%s/%d/%d' % (token, s0, e0)], hdrs)
                    if r is not None:
                        try:
                            data = r.json()
                            stream_url = data.get('url')
                            exp = data.get('expire')
                            if exp:
                                try:
                                    _PROXY['expire_ms'] = int(exp)
                                except Exception:
                                    pass
                        except Exception:
                            logger.error('vidxgo heal non-JSON: ' + r.text[:200])
                            stream_url = None
                        else:
                            if stream_url:
                                _PROXY['t_url'] = t_url
                                _PROXY['fresh_query'] = urllib.parse.urlparse(stream_url).query
                except Exception:
                    logger.error('vidxgo heal retry failed: ' + traceback.format_exc())

        if not stream_url:
            try:
                stream_url = extract_m3u8_from_embed(_vidxgo_session(), page_url,
                                                     referer=REF_SITE + '/')
                _PROXY['t_url'] = ''
            except Exception as e:
                logger.error('vidxgo embed extraction failed: %s' % e)

        if not stream_url:
            logger.error('vidxgo: nessun URL trovato')
            return []

        _reset_relay_sessions()

        u = urllib.parse.urlparse(stream_url)
        _PROXY['base'] = u.scheme + '://' + u.netloc
        _PROXY['master_path'] = u.path
        _PROXY['host'] = u.netloc

        _ratelimit_wait(_PROXY['host'])

        port = _start_proxy()
        if not port:
            return []

        proxy_url = 'http://127.0.0.1:%d%s' % (port, u.path)

        import threading as _th
        _th.Thread(target=_prefetch_playlists, daemon=True).start()

        _HB['sid'] = str(uuid.uuid4())
        now = time.time()
        _PROXY['t0'] = now
        _PROXY['last_hb'] = now
        _PROXY['last_mint'] = now

        return [['vidxgo', proxy_url]]
    except Exception:
        logger.error('vidxgo: ' + traceback.format_exc())
        return []