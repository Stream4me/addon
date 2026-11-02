# -*- coding: utf-8 -*-
# Server vixsrc_alt per S4me — v10.1 "v10 provato + die-fast con guardia"
# ------------------------------------------------------------

import json, os, re, tempfile, threading, time, traceback
import urllib.parse
import cloudscraper
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from platformcode import logger

HOST = 'https://vixsrc.to'
UA_FF = 'Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0'

RELAY_CONNECT_TIMEOUT = 10
RELAY_READ_TIMEOUT = 30
CDN_MIN_INTERVAL = 1.0
PLCACHE_TTL = 3600               # il testo del master non cambia: 1h
WD_POLL = 2                      # [DIE-FAST] reazione rapida
WD_IDLE_NEVER = 60               # mai suonato: finestra di avvio 60s
HEAL_MIN_INTERVAL = 30.0
HEAL_BUSY_MAX = 120.0

_NET_FAIL = [0.0, 0]
_SESS = [None]
_RELAY_SESS = [None]

_RATELIMIT_FILE = os.path.join(tempfile.gettempdir(), 'alfa_vixsrc_alt_ratelimit.json')

_PROXY = {'server': None, 'port': 0,
          'base': '', 'master_path': '', 'query': '',
          'embed_ref': HOST + '/',
          'cdn_alt': '',
          'kind': 'movie', 'imdb': '', 'se': None,
          'last_req': 0.0, 'played': False}

_PLCACHE = {}
_HEAL = {'t': 0.0, 'busy': 0.0}

# ---------------- rete ----------------

def _is_net_error(e):
    s = str(e); tn = type(e).__name__
    if 'Name or service not known' in s or 'Temporary failure' in s:
        return True
    if 'Timeout' in tn or 'timed out' in s.lower():
        return True
    if 'ConnectionError' in tn or 'gaierror' in tn:
        return True
    return False

def _net_down():
    if _NET_FAIL[1] == 0:
        return False
    return time.time() - _NET_FAIL[0] < min(10 * (2 ** min(_NET_FAIL[1] - 1, 4)), 160)

def _net_fail():
    _NET_FAIL[0] = time.time()
    _NET_FAIL[1] += 1

def _net_ok():
    _NET_FAIL[1] = 0

def _session():
    if _SESS[0] is None:
        _SESS[0] = cloudscraper.create_scraper()
    return _SESS[0]

def _make_adapter():
    class _A(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            try:
                kw['ssl_context'] = create_urllib3_context()
            except Exception:
                pass
            return super().init_poolmanager(*a, **kw)
    return _A()

def _relay_session():
    if _RELAY_SESS[0] is None:
        s = requests.Session()
        s.headers.update({'User-Agent': UA_FF, 'Accept-Encoding': 'identity'})
        try:
            s.mount('https://', _make_adapter())
        except Exception:
            pass
        _RELAY_SESS[0] = s
    return _RELAY_SESS[0]

def _ratelimit_wait(key):
    try:
        data = {}
        try:
            with open(_RATELIMIT_FILE) as f:
                data = json.load(f)
        except Exception:
            pass
        delta = time.time() - data.get(key, 0)
        if delta < CDN_MIN_INTERVAL:
            time.sleep(CDN_MIN_INTERVAL - delta)
        data[key] = time.time()
        with open(_RATELIMIT_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

# ---------------- resolve: API -> embed ----------------

def _api_src(kind, imdb, se):
    if kind == 'tv' and se:
        url = '%s/api/tv/%s/%d/%d?lang=it' % (HOST, imdb, se[0], se[1])
    else:
        url = '%s/api/movie/%s?lang=it' % (HOST, imdb)
    try:
        r = _session().get(url, headers={'User-Agent': UA_FF,
                                         'Accept': 'application/json, text/plain, */*'},
                           timeout=RELAY_CONNECT_TIMEOUT + 2)
        _net_ok()
    except Exception as e:
        if _is_net_error(e):
            _net_fail()
            logger.error('vixsrc_alt api: rete (backoff #%d)' % _NET_FAIL[1])
        else:
            logger.error('vixsrc_alt api exc: ' + str(e)[:120])
        return None
    if r.status_code != 200:
        logger.error('vixsrc_alt api -> HTTP %s (%s)' % (r.status_code, url))
        return None
    try:
        src = r.json().get('src') or ''
    except Exception:
        logger.error('vixsrc_alt api non-JSON: ' + r.text[:150])
        return None
    return src if src.startswith('/embed/') else None

_RE_MASTER = re.compile(r"masterPlaylist\s*=\s*\{.*?url:\s*'([^']+)'", re.S)
_RE_TOKEN  = re.compile(r"'token':\s*'([^']+)'")
_RE_EXPIRE = re.compile(r"'expires':\s*'([^']+)'")
_RE_ASN    = re.compile(r"'asn':\s*'([^']*)'")
_RE_STREAMS = re.compile(r'"name":"([^"]+)","active":(0|1),"url":"(.*?)"')
_RE_THUMB  = re.compile(r"thumbnailsUrl\s*=\s*'([^']+)'")

def _embed_info(src_path):
    try:
        r = _session().get(HOST + src_path,
                           headers={'User-Agent': UA_FF, 'Referer': HOST + '/'},
                           timeout=RELAY_CONNECT_TIMEOUT + 2)
        _net_ok()
    except Exception as e:
        if _is_net_error(e):
            _net_fail()
            logger.error('vixsrc_alt embed: rete (backoff #%d)' % _NET_FAIL[1])
        else:
            logger.error('vixsrc_alt embed exc: ' + str(e)[:120])
        return None
    if r.status_code != 200:
        logger.error('vixsrc_alt embed -> HTTP %s' % r.status_code)
        return None
    page = r.text
    mu, mt, me = _RE_MASTER.search(page), _RE_TOKEN.search(page), _RE_EXPIRE.search(page)
    if not (mu and mt and me):
        logger.error('vixsrc_alt embed: masterPlaylist non trovata')
        return None
    streams = [(n, a, u.replace('\\/', '/').replace('\\u0026', '&'))
               for n, a, u in _RE_STREAMS.findall(page)]
    mth = _RE_THUMB.search(page)
    ma = _RE_ASN.search(page)
    return {'url': mu.group(1), 'tok': mt.group(1), 'exp': me.group(1),
            'asn': (ma.group(1) if ma else ''),
            'active': next((u for _n, a, u in streams if a == '1'), None),
            'thumb': (mth.group(1) if mth else '')}

def _xhr_headers(referer):
    return {'User-Agent': UA_FF, 'Accept': '*/*', 'Referer': referer,
            'Origin': HOST, 'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-origin'}

def _get_text(url, headers, timeout):
    try:
        r = _relay_session().get(url, headers=headers,
                                 timeout=(RELAY_CONNECT_TIMEOUT, timeout))
        _net_ok()
        return r.status_code, r.text or ''
    except Exception as e:
        if _is_net_error(e):
            _net_fail()
            logger.error('vixsrc_alt get: rete (backoff #%d, %s)'
                         % (_NET_FAIL[1], str(e)[:70]))
        else:
            logger.error('vixsrc_alt get exc: ' + str(e)[:100])
        return 0, ''

def _try_cdn(info):
    """[CDN-FALLBACK] host+uuid da thumbnailsUrl -> playlist.m3u8 aperta."""
    th = info.get('thumb') or ''
    m = re.match(r'(https?://[^/]+)(/hls/[^/]+/[^/]+/[^/]+/[^/]+)/thumbnails/', th)
    if not m:
        return None
    cdn_base, cdn_dir = m.group(1), m.group(2)
    url = cdn_base + cdn_dir + '/playlist.m3u8'
    code, text = _get_text(url, _xhr_headers(HOST + '/'), 20)
    if code == 200 and '#EXTM3U' in text:
        logger.info('vixsrc_alt CDN fallback OK: %s' % cdn_base)
        return {'base': cdn_base, 'master_path': cdn_dir + '/playlist.m3u8',
                'query': '', 'text': text}
    logger.error('vixsrc_alt CDN fallback -> %s %s' % (code, url[:90]))
    return None

def _resolve_playlist(kind, imdb, se):
    src = _api_src(kind, imdb, se)
    if not src:
        return None
    info = _embed_info(src)
    if not info:
        return None
    embed_ref = HOST + src

    # --- 1) RICETTA player (un solo uso del token: qui) ---
    base_url = info['active'] or info['url']
    if base_url:
        sep = '&' if '?' in base_url else '?'
        q = ['token=' + info['tok'], 'expires=' + info['exp']]
        if info['asn']:
            q.append('asn=' + info['asn'])
        q += ['h=1', 'lang=it']
        murl = base_url + sep + '&'.join(q)
        u = urllib.parse.urlparse(murl)
        cand = {'base': u.scheme + '://' + u.netloc,
                'master_path': u.path, 'query': u.query}
        _ratelimit_wait(u.netloc + u.path)
        code, text = _get_text(murl, _xhr_headers(embed_ref), 20)
        if code == 200 and '#EXTM3U' in text:
            cand['embed_ref'] = embed_ref
            cand['warm'] = text
            # [CDN-FAILOVER] host CDN di soccorso da thumbnailsUrl
            mth2 = re.match(r'(https?://[^/]+)(/hls/[^/]+/[^/]+/[^/]+/[^/]+)/',
                            info.get('thumb') or '')
            if mth2:
                cand['cdn_alt'] = mth2.group(1)
            logger.info('vixsrc_alt ricetta OK: %s (%d B) [token consumato]'
                        % (cand['master_path'], len(text)))
            return cand
        logger.error('vixsrc_alt ricetta -> %s (%s)' % (code, murl[:100]))

    # --- 2) FALLBACK CDN aperto ---
    cand = _try_cdn(info)
    if cand:
        cand['embed_ref'] = embed_ref
        return cand
    return None

# ---------------- heal ----------------

def _hot_heal():
    try:
        if _net_down():
            return False
        old_base = _PROXY.get('base')
        old_path = _PROXY.get('master_path')
        st = _resolve_playlist(_PROXY.get('kind', 'movie'),
                               _PROXY.get('imdb', ''), _PROXY.get('se'))
        if not st:
            return False
        _PROXY['base'] = st['base']
        _PROXY['master_path'] = st['master_path']
        _PROXY['query'] = st['query']
        _PROXY['embed_ref'] = st.get('embed_ref') or _PROXY['embed_ref']
        _PROXY['cdn_alt'] = st.get('cdn_alt') or _PROXY.get('cdn_alt', '')
        # [TOKEN-USE1] NON cancellare la cache: il warm del resolve e'
        # l'unica copia servibile per il retry di Kodi
        if (st['base'] != old_base) or (st['master_path'] != old_path):
            logger.info('vixsrc_alt heal: base cambiato %s%s -> %s%s'
                        % (old_base, old_path, st['base'], st['master_path']))
        logger.info('vixsrc_alt hot-heal: nuovo master in cache (+warm)')
        return True
    except Exception:
        logger.error('vixsrc_alt hot-heal: ' + traceback.format_exc())
        return False
    finally:
        _HEAL['busy'] = 0.0

def _heal_trigger():
    now = time.time()
    stale = _HEAL['busy'] and (now - _HEAL['busy']) > HEAL_BUSY_MAX
    if _HEAL['busy'] and not stale:
        return
    if now - _HEAL['t'] < HEAL_MIN_INTERVAL and not stale:
        return
    _HEAL['t'] = now
    _HEAL['busy'] = now
    threading.Thread(target=_hot_heal, daemon=True).start()

# ---------------- proxy locale ----------------

def _stop_proxy():
    old = _PROXY['server']
    if old is not None:
        try:
            old.shutdown()
            old.server_close()
        except Exception:
            pass
    # [TOKEN-USE1] NIENTE clear qui: _start_proxy chiama _stop_proxy
    # e cancellerebbe la cache calda appena popolata dal resolve
    _PROXY['server'] = None
    _PROXY['port'] = 0
    time.sleep(0.05)

def _start_proxy():
    _stop_proxy()
    import http.server, socketserver

    class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            import sys, socket
            if sys.exc_info()[0] in (ConnectionResetError, BrokenPipeError,
                                     ConnectionAbortedError, socket.timeout,
                                     TimeoutError):
                return
            super().handle_error(request, client_address)

    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        timeout = 20

        def _send(self, code, with_body):
            """[KEEPALIVE-FIX] OGNI risposta chiude la connessione: la
            Stat post-stop di Kodi (che riusa la connessione keep-alive
            del playback) non resta mai in coda al thread handler."""
            self.close_connection = True
            self.send_response(code)
            self.send_header('Connection', 'close')

        def _to_proxy(self, u, base_dir):
            # [MULTI-HOST] assoluti -> /__h/{host}/{path}?{query}
            if u.startswith('//'):
                u = 'https:' + u
            if u.startswith('http://') or u.startswith('https://'):
                p = urllib.parse.urlparse(u)
                q = ('?' + p.query) if p.query else ''
                return '/__h/%s%s%s' % (p.netloc, p.path, q)
            if not u.startswith('/'):
                u = base_dir + u
            return u

        def _rewrite_m3u8(self, text, req_path):
            base_dir = req_path.rsplit('/', 1)[0] + '/'
            out = []
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith('#'):
                    line = re.sub(r'(URI=")([^"]+)(")',
                                  lambda m: m.group(1) +
                                  self._to_proxy(m.group(2), base_dir) +
                                  m.group(3), line)
                    out.append(line)
                else:
                    out.append(self._to_proxy(s, base_dir))
            out_text = '\n'.join(out) + '\n'
            # [VOD-FIX] vixcloud non chiude il manifest -> Kodi/ffmpeg
            # trattano lo stream come LIVE: repoll continuo, 'stream
            # stalled', finestra live, sync error ActiveAE. I contenuti
            # sono VOD: chiudiamo noi il playlist. (Playlist senza
            # #EXTINF restano intatte.)
            if '#EXT-X-ENDLIST' not in out_text and '#EXTINF' in out_text:
                out_text += '#EXT-X-ENDLIST\n'
            return out_text

        def _serve_cached(self, key, with_body):
            ent = _PLCACHE.get(key)
            if not ent or (time.time() - ent[0]) >= PLCACHE_TTL:
                return False
            try:
                payload = self._rewrite_m3u8(ent[1],
                                             key.split('?')[0]).encode('utf-8')
                self._send(200, with_body)
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if with_body:
                    self.wfile.write(payload)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass
            return True

        def _up_query(self, req_q, is_pl):
            # [TOKEN-USE1] playlist con token PROPRIO (dal master):
            # pass-through intoccato. Solo la richiesta "nuda" di Kodi
            # riceve la ricetta completa dal resolve.
            if not is_pl or 'token=' in req_q:
                return req_q
            add = [k + '=' + v
                   for k, v in urllib.parse.parse_qsl(_PROXY.get('query', ''))
                   if k in ('token', 'expires', 'asn', 'h', 'lang')]
            if req_q and add:
                return req_q + '&' + '&'.join(add)
            return '&'.join(add) if add else req_q

        def _relay(self, with_body):
            _PROXY['last_req'] = time.time()
            req_path, _, req_q = self.path.partition('?')
            low = req_path.lower()
            is_pl = low.endswith('.m3u8') or '/playlist/' in low

            # [STAT-FAST] HEAD su playlist: risposta SEMPRE locale e
            # istantanea (e con Connection: close: vedi _send).
            if not with_body and is_pl:
                ent = _PLCACHE.get(self.path) or _PLCACHE.get(req_path)
                try:
                    size = len(ent[1].encode('utf-8')) if ent else 0
                    self._send(200 if ent else 404, with_body)
                    self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                    self.send_header('Content-Length', str(size))
                    self.end_headers()
                except (ConnectionResetError, BrokenPipeError,
                        ConnectionAbortedError):
                    pass
                logger.info('vixsrc_alt HEAD %s -> %s'
                            % (req_path, 'cache' if ent else '404'))
                return

            if not _PROXY['base']:
                self.send_error(503)
                return

            # [MULTI-HOST] /__h/{host}/{path}?{query} -> host esterno
            up_base = _PROXY['base']
            ext = req_path.startswith('/__h/')
            if ext:
                rest = req_path[len('/__h/'):]
                host, _, path = rest.partition('/')
                up_base = 'https://' + host
                req_path = path if path.startswith('/') else '/' + path
                is_pl = req_path.lower().endswith('.m3u8') \
                        or '/playlist/' in req_path.lower()
                up_q = req_q            # mai merge su host esterni (token propri)
            else:
                up_q = self._up_query(req_q, is_pl) if is_pl else req_q

            # [TOKEN-USE1-v2] playlist richiesta NUDA (query locale senza
            # token, check su req_q NON su up_q): il token del resolve e'
            # gia' consumato -> cache o 503+heal, MAI upstream.
            if is_pl and not ext and 'token=' not in req_q:
                if self._serve_cached(self.path, with_body):
                    logger.info('vixsrc_alt GET %s -> cache' % req_path)
                    return
                _heal_trigger()
                logger.info('vixsrc_alt GET %s -> 503 + heal' % req_path)
                self.send_error(503)
                return

            if is_pl and self._serve_cached(self.path, with_body):
                logger.info('vixsrc_alt GET %s -> cache' % req_path)
                return
            if is_pl:
                _ratelimit_wait(up_base + req_path)   # [PERF-RATE] per-path

            url = up_base + req_path + (('?' + up_q) if up_q else '')
            headers = {'User-Agent': UA_FF,
                       'Referer': _PROXY.get('embed_ref') or HOST + '/',
                       'Accept': '*/*'}
            if is_pl and up_base == _PROXY['base']:
                headers.update({'Origin': HOST,
                                'Sec-Fetch-Dest': 'empty',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'same-origin'})
            rng = self.headers.get('Range')
            if rng:
                headers['Range'] = rng

            # [CDN-FAILOVER] su segmenti esterni (non playlist): un solo
            # retry sull'host CDN alternativo se 5xx o errore rete
            r = None
            try:
                r = _relay_session().get(url, headers=headers, stream=True,
                                         timeout=(RELAY_CONNECT_TIMEOUT,
                                                  RELAY_READ_TIMEOUT))
                _net_ok()
                if ext and not is_pl and r.status_code >= 500:
                    alt = _PROXY.get('cdn_alt') or ''
                    if alt and alt != up_base:
                        url2 = alt + req_path + (('?' + up_q) if up_q else '')
                        try:
                            r2 = _relay_session().get(url2, headers=headers,
                                                      stream=True,
                                                      timeout=(RELAY_CONNECT_TIMEOUT,
                                                               RELAY_READ_TIMEOUT))
                            if r2.status_code == 200:
                                logger.info('vixsrc_alt CDN failover %s -> %s'
                                            % (urllib.parse.urlparse(up_base).netloc,
                                               urllib.parse.urlparse(alt).netloc))
                                try:
                                    r.close()
                                except Exception:
                                    pass
                                r = r2
                            else:
                                try:
                                    r2.close()
                                except Exception:
                                    pass
                        except Exception:
                            pass
            except Exception as e:
                alt = _PROXY.get('cdn_alt') or ''
                if ext and not is_pl and alt and alt != up_base:
                    try:
                        url2 = alt + req_path + (('?' + up_q) if up_q else '')
                        r = _relay_session().get(url2, headers=headers,
                                                 stream=True,
                                                 timeout=(RELAY_CONNECT_TIMEOUT,
                                                          RELAY_READ_TIMEOUT))
                        _net_ok()
                        logger.info('vixsrc_alt CDN failover (exc) -> %s'
                                    % urllib.parse.urlparse(alt).netloc)
                    except Exception:
                        r = None
                if r is None:
                    if _is_net_error(e):
                        _net_fail()
                        logger.error('vixsrc_alt relay: rete (backoff #%d, %s)'
                                     % (_NET_FAIL[1], str(e)[:80]))
                    else:
                        logger.error('vixsrc_alt relay exc: ' + str(e)[:120])
                    try:
                        self.send_error(502)
                    except Exception:
                        pass
                    return

            # [DIAG 10.1] log del codice su non-200/206 (il gap v12)
            if r.status_code not in (200, 206):
                logger.error('vixsrc_alt upstream %s -> HTTP %s'
                             % (req_path[:70], r.status_code))

            if r.status_code in (403, 429):
                logger.info('vixsrc_alt upstream %s -> HTTP %s: heal in background'
                            % (req_path[:60], r.status_code))
                _heal_trigger()
                try:
                    r.close()
                except Exception:
                    pass
                self.send_error(503)
                return

            ct = r.headers.get('Content-Type') or ''
            if is_pl or 'mpegurl' in ct.lower():
                try:
                    text = r.content.decode('utf-8', 'replace')
                except Exception:
                    text = ''
                if r.status_code == 200:
                    _PLCACHE[self.path] = (time.time(), text)
                    payload = self._rewrite_m3u8(text, req_path).encode('utf-8')
                else:
                    payload = text.encode('utf-8', 'replace')
                try:
                    self._send(r.status_code, with_body)
                    self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    if with_body:
                        self.wfile.write(payload)
                except (ConnectionResetError, BrokenPipeError,
                        ConnectionAbortedError):
                    pass
                try:
                    r.close()
                except Exception:
                    pass
                return

            try:
                self._send(r.status_code, with_body)
                if ct:
                    self.send_header('Content-Type', ct)
                cl = r.headers.get('Content-Length')
                if cl:
                    self.send_header('Content-Length', cl)
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
        logger.error('vixsrc_alt proxy bind failed')
        return 0
    _PROXY['port'] = srv.server_address[1]
    _PROXY['server'] = srv
    _PROXY['last_req'] = time.time()
    _PROXY['played'] = False
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=_proxy_watchdog, args=(srv,), daemon=True).start()
    logger.info('vixsrc_alt proxy started on 127.0.0.1:%d' % _PROXY['port'])
    return _PROXY['port']

def _proxy_watchdog(srv):
    """[v10.1] DIE-FAST solo DOPO aver suonato: se il player e' fermo ma
    non ha MAI suonato siamo nella finestra di avvio (Kodi fa Stat prima
    di OpenFile: isPlaying()=False non significa 'finito') -> finestra
    WD_IDLE_NEVER (60s). Una volta suonato, lo stop = shutdown immediato
    (fix del crash/restart all'uscita: niente connessioni zombie)."""
    player = None
    monitor = None
    try:
        import xbmc
        player = xbmc.Player()
        monitor = xbmc.Monitor()
    except Exception:
        pass
    stopped_at = 0.0
    while True:
        if monitor is not None:
            if monitor.waitForAbort(WD_POLL):
                break
        else:
            time.sleep(WD_POLL)
        if _PROXY.get('server') is not srv:
            return
        now = time.time()
        if player is not None and player.isPlaying():
            _PROXY['played'] = True
            _PROXY['last_req'] = now
            stopped_at = 0.0
            continue
        if _PROXY.get('played'):
            # [DIE-FAST] ha suonato e ora fermo: muore subito
            logger.info('vixsrc_alt: player fermo, proxy shutdown')
            break
        # mai suonato: finestra di avvio
        if not stopped_at:
            stopped_at = now
            logger.info('vixsrc_alt: avvio in corso, finestra %ds'
                        % WD_IDLE_NEVER)
        if now - stopped_at < WD_IDLE_NEVER:
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
    logger.info('vixsrc_alt proxy stopped')

# ---------------- entry point ----------------

def test_video_exists(page_url):
    return True, ''

def get_video_url(page_url, premium=False, user='', password='', video_password=''):
    logger.info('vixsrc_alt.get_video_url: %s' % page_url)
    try:
        p = urllib.parse.urlparse(page_url)
        parts = [x for x in p.path.split('/') if x]
        kind = parts[0] if parts else ''
        imdb = parts[1] if len(parts) > 1 else ''
        se = None
        if kind == 'tv' and len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
            se = (int(parts[2]), int(parts[3]))
        if kind not in ('movie', 'tv') or not imdb.startswith('tt'):
            logger.error('vixsrc_alt: URL non riconosciuto: %s' % page_url)
            return []
        if kind == 'movie':
            se = None

        _PROXY['kind'] = kind
        _PROXY['imdb'] = imdb
        _PROXY['se'] = se
        _HEAL['t'] = 0.0
        _HEAL['busy'] = 0.0
        _PLCACHE.clear()            # solo qui: nuovo titolo, nuovo master

        st = _resolve_playlist(kind, imdb, se)
        if not st:
            logger.error('vixsrc_alt: resolve fallito (ricetta+CDN)')
            return []

        _PROXY['base'] = st['base']
        _PROXY['master_path'] = st['master_path']
        _PROXY['query'] = st['query']
        _PROXY['embed_ref'] = st.get('embed_ref') or HOST + '/'
        _PROXY['cdn_alt'] = st.get('cdn_alt') or ''

        # warm DELLA COPPIA giusta, DOPO aver fissato lo stato
        warm = st.pop('warm', None)
        if warm:
            _PLCACHE[st['master_path']] = (time.time(), warm)

        port = _start_proxy()       # NON tocca piu' la cache
        if not port:
            return []
        proxy_url = 'http://127.0.0.1:%d%s' % (port, st['master_path'])
        return [['vixsrc_alt', proxy_url]]
    except Exception:
        logger.error('vixsrc_alt: ' + traceback.format_exc())
        return []
