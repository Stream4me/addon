# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Server vidxgo per s4me
#
# Accetta url embed nella forma:
#   https://v.vidxgo.co/<token>            -> film
#   https://v.vidxgo.co/<token>/<s>/<e>    -> episodio
#
# Pipeline:
#   1) resolve via /t/ con rotazione fingerprint TLS (cache su disco);
#      un 404/410 genuino esce IMMEDIATAMENTE (niente sweep: e' la forma
#      URL/token ad essere sbagliata, non la fingerprint)
#   2) token nudo che /t/ rifiuta: HEAL -> legge stagione/episodio corrente
#      dal player della pagina embed e riprova /t/<token>/<s>/<e>
#   3) fallback XOR dalla pagina embed (film; per le serie il player ha
#      currentSrc vuoto, quindi per loro il percorso giusto e' /t/<s>/<e>)
#   4) proxy locale: header-injecting, token refresh 150s, heartbeat 50s
#      piggyback sul traffico reale, cache playlist + prefetch FASTSTART,
#      porta fissa per resume stabile
#   5) WATCHDOG: auto-spegnimento dopo WD_IDLE_PLAYED s di idle post-stop
#      (o WD_IDLE_NEVER s se il play non e' mai partito). Senza di esso il
#      thread serve_forever blocca il teardown dell'interprete -> Kodi
#      "OnClick - updating in progress" -> addon congelato fino al riavvio.
#   6) REUSE-FIX: ogni play ricicla la sessione relay e riparte con un
#      proxy pulito. Le connessioni keep-alive del play precedente possono
#      essere state chiuse dal CDN durante la pausa ("stop, attendo 10s,
#      play successivo"): riutilizzarle = prima richiesta appesa su una
#      connessione mezza-morta -> ffmpeg attende il timeout ->
#      "OpenDemuxStream - Error creating demuxer".
#
# Helper per i canali:
#   probe(token)         -> {'mode': 'tv'|'movie'|'', 'episodes': [(s,e)..]}
#                           (episodi dal seasonCache nel blob player)
#   get_embed_page(url)  -> sorgente pagina embed con sessione TLS-cleared
# ------------------------------------------------------------

import base64, json, os, re, ssl, tempfile, time, traceback, uuid
import urllib.parse
import cloudscraper

from platformcode import logger

HOST = 'https://v.vidxgo.co'
REF_SITE = 'https://altadefinizionex.live'   # ref inviato negli heartbeat

FF_UA = 'Mozilla/5.0 (X11; Linux x86_64; rv:155.0) Gecko/20100101 Firefox/155.0'
PLAY_HEADERS = {
    'User-Agent':      FF_UA,
    'Referer':         HOST + '/',
    'Origin':          'https://v.vidxgo.co',
    'Sec-Fetch-Dest':  'empty',
    'Sec-Fetch-Mode':  'cors',
    'Sec-Fetch-Site':  'cross-site',
}

FIXED_PORT = 52714   # porta fissa -> URL di playback stabile tra sessioni (resume Kodi)

# [WATCHDOG] tunables
WD_POLL = 3           # intervallo di controllo (s): recupero navigazione ~10-13s
WD_IDLE_PLAYED = 10   # idle post-stop prima dello spegnimento (s)
WD_IDLE_NEVER = 30    # pazienza extra se il play non e' mai partito (dialogo aperto)

_PROXY = {'server': None, 'port': 0, 'base': '',
          't_url': '', 'imdb': '', 'fresh_query': '', 'dur': 0,
          't0': 0.0, 'last_hb': 0.0, 'last_mint': 0.0, 'hb_type': 'movie',
          'master_path': '',
          'last_req': 0.0, 'played': False}      # [WATCHDOG]
_HB = {'sid': ''}
_SESSION = None
SEGMENTS_DIRECT = False

# [FASTSTART] cache playlist VOD: req_path -> (timestamp, testo raw upstream)
_PLCACHE = {}
_PLCACHE_TTL = 120


# ============================ TLS-COMPAT LAYER ============================
# v.vidxgo.co e' dietro Cloudflare. L'OpenSSL bundlato con Kodi su Android ha
# una fingerprint TLS (JA3) che CF flagga: handshake OK ma 403. Ruotiamo
# fingerprint (cipher / versione TLS / curva EC) contro l'endpoint /t/ REALE.
# La vincente viene PERSISTUTA su disco: 1 sola richiesta a play.
_TLS = {'mode': None, 'session': None}
_TLS_CACHE_FILE = os.path.join(tempfile.gettempdir(), 'alfa_vidxgo_tls.json')


def _make_tls_adapter(ciphers=None, ver_range=None, curve=None):
    """HTTPAdapter con ssl_context personalizzato; None se il build non lo supporta."""
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
    ('default',  None, None, None),                                        # com'era (vincente su Linux)
    ('sec1',     'DEFAULT@SECLEVEL=1', None, None),                        # riabilita cipher legacy medi
    ('p256',     None, None, 'prime256v1'),                                # curva EC diversa -> JA3 diverso
    ('tls12pin', None, (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2), None),  # TLS1.2 puro
    ('sec0',     'ALL:@SECLEVEL=0',    None, None),                        # tutti i cipher
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
        with open(_TLS_CACHE_FILE) as f:
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
    """True se la risposta e' una pagina blocco/sfida Cloudflare."""
    if r.status_code not in (403, 429, 503):
        return False
    if 'cf-mitigated' in r.headers:
        return True
    head = r.text[:3000].lower()
    return ('no-js' in head and 'oldie' in head) or \
           'cloudflare' in head or 'just a moment' in head


def _vidxgo_session():
    """Sessione vidxgo per hb/refresh/XOR: riusa la vincente in cache."""
    if _TLS.get('session') is not None:
        return _TLS['session']
    return _build_vidxgo_session(_TLS['mode'] or _TLS_CANDIDATES[0])


def _vidxgo_resolve(url_candidates, headers):
    """Cached winner: 1 richiesta. 404/410 genuini -> esito IMMEDIATO (il
    token/la forma URL e' sbagliata: un'altra fingerprint otterrebbe lo
    stesso 404, e lo sweep inseguirebbe una challenge CF inutile).
    Ritorna (response, t_url, session) oppure (None, None, None)."""
    saved = _tls_cache_load()
    tried_full = False

    while True:
        if saved:
            order = [saved]
        else:
            if tried_full:
                logger.error('TLS resolve: nessuna fingerprint accettata da Cloudflare')
                return None, None, None
            order = list(_TLS_CANDIDATES)
            tried_full = True

        was_cached = saved is not None
        saved = None                     # la cache vale per un solo giro

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
                            logger.info('winner in cache ora bloccato -> sweep completo')
                        break            # fingerprint bannata: inutile provare gli altri URL
                    if r.status_code in (404, 410):
                        logger.info('/t/ [%s] %s -> HTTP %s (non CF, esito definitivo: '
                                    'token o forma URL errata)'
                                    % (cand[0], u, r.status_code))
                        return None, None, None        # niente sweep
                    logger.info('/t/ [%s] %s -> HTTP %s (non CF)'
                                % (cand[0], u, r.status_code))
                except Exception as e:
                    logger.error('candidate [%s] %s -> %s' % (cand[0], u, str(e)[:150]))

def _get_session():
    global _SESSION
    if _SESSION is None:
        import requests
        from requests.adapters import HTTPAdapter
        # [REUSE-FIX] retry a livello CONNECT: una connessione keep-alive
        # chiusa dal CDN durante la pausa tra due play non deve mai
        # black-holare la prima richiesta del nuovo playback.
        # read=0: NON ritentare mai un download segmento a meta' stream.
        try:
            from urllib3.util.retry import Retry
            retry = Retry(total=2, connect=2, read=0, backoff_factor=0.2)
        except Exception:
            retry = 0
        _SESSION = requests.Session()
        _SESSION.headers.update(PLAY_HEADERS)
        _SESSION.headers['Accept-Encoding'] = 'identity'
        _, ciphers, ver, curve = _TLS['mode'] or _TLS_CANDIDATES[0]
        ad = _make_tls_adapter(ciphers, ver, curve)
        if ad is not None:
            try:
                ad.max_retries = retry
            except Exception:
                pass
            _SESSION.mount('https://', ad)
        else:
            _SESSION.mount('https://', HTTPAdapter(max_retries=retry,
                                                   pool_connections=8, pool_maxsize=8))
        _SESSION.mount('http://', HTTPAdapter(max_retries=retry,
                                              pool_connections=8, pool_maxsize=8))
    return _SESSION


# ============================ [FASTSTART] PREFETCH PLAYLIST ============================
def _prefetch_playlists():
    """Riscalda la cache playlist SUBITO dopo il resolve: master + prima variante
    media. I fetch identici da ~5s del CDN all'avvio diventano hit locali."""
    try:
        time.sleep(0.1)
        sess = _get_session()
        base = _PROXY['base']
        q = _PROXY.get('fresh_query', '')

        def fetch(path):
            url = base + path + (('?' + q) if q else '')
            try:
                r = sess.get(url, timeout=(10, 30))
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
        # prima variante media playlist (prima riga non-commento del master)
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
        logger.error('prefetch crashed: ' + traceback.format_exc())

def _refresh_token():
    if not _PROXY.get('t_url'):
        return True
    try:
        s = _vidxgo_session()
        r = s.get(_PROXY['t_url'],
                  headers={'User-Agent': FF_UA, 'Referer': HOST + '/',
                           'Accept': 'application/json, text/plain, */*'},
                  timeout=10)
        if r.status_code == 200:
            new_url = r.json()['url']
            q = urllib.parse.urlparse(new_url).query
            if q:
                _PROXY['fresh_query'] = q
                logger.info('token refreshed')
                return True
        logger.error('token refresh failed: HTTP ' + str(r.status_code))
    except Exception:
        logger.error('token refresh crashed: ' + traceback.format_exc())
    return False


def _send_heartbeat(pos):
    try:
        s = _vidxgo_session()
        payload = {"sid": _HB['sid'], "v": 2, "imdb": _PROXY.get('imdb', ''),
                   "type": _PROXY.get('hb_type', 'movie'), "pos": int(pos),
                   "dur": int(_PROXY.get('dur') or 0),
                   "playing": 1, "ref": REF_SITE + "/", "dm": "PC Linux"}
        s.post(HOST + '/hb', json=payload,
               headers={'User-Agent': FF_UA, 'Referer': HOST + '/',
                        'Origin': HOST, 'Content-Type': 'application/json',
                        'Accept': '*/*'}, timeout=10)
    except Exception:
        logger.error('hb failed: ' + traceback.format_exc())


# ============================ [WATCHDOG] AUTO-SHUTDOWN PROXY ============================
def _proxy_watchdog(srv):
    """Spegne il proxy quando non serve piu'. Senza questo, il thread
    serve_forever non termina mai e Kodi non puo' finalizzare l'interprete
    python: 'CPythonInvoker waiting on thread' -> ogni click successivo sulla
    GUI finisce in 'OnClick - updating in progress' -> addon congelato fino
    al riavvio. Con il watchdog: ~WD_IDLE_PLAYED s dopo lo stop il server si
    spegne, il thread esce e la navigazione si sblocca."""
    player = None
    monitor = None
    try:
        import xbmc
        player = xbmc.Player()
        monitor = xbmc.Monitor()
    except Exception:
        pass    # fuori da Kodi (test): solo logica a tempo

    while True:
        if monitor is not None:
            if monitor.waitForAbort(WD_POLL):
                break                       # Kodi si spegne
        else:
            time.sleep(WD_POLL)

        # un nuovo play ha sostituito il server -> questo watchdog non serve piu'
        # [REUSE-FIX] _start_proxy ora spegne SEMPRE il server precedente a
        # ogni play, quindi questo guard fa uscire pulitamente il vecchio
        # watchdog invece di lasciarlo armato sul nuovo playback
        if _PROXY['server'] is not srv:
            return

        if player is not None and player.isPlaying():
            _PROXY['played'] = True
            _PROXY['last_req'] = time.time()
            continue

        idle = time.time() - _PROXY.get('last_req', 0.0)
        # ha riprodotto: spegni subito dopo l'idle; mai partito: piu' pazienza
        if idle < (WD_IDLE_PLAYED if _PROXY.get('played') else WD_IDLE_NEVER):
            continue

        if player is not None and player.isPlaying():   # ricontrollo allo scatto
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

# ============================ PROXY LOCALE ============================
def _stop_proxy():
    """[REUSE-FIX] Spegne il server corrente (se c'e') e svuota lo stato.
    Chiamata a ogni nuovo play: riparte sempre puliti."""
    old = _PROXY['server']
    if old is not None:
        logger.info('proxy restart (nuovo play)')
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
    # [REUSE-FIX] ogni play riparte pulito: spegni SEMPRE il server precedente
    # e svuota la cache playlist. Il vecchio watchdog (se ancora armato) esce
    # per il suo guard 'is not srv' invece di uccidere il nuovo playback
    # ('stop A, attendo 10s, play B' non deve mai fallire).
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
            timeout = 20          # [WATCHDOG] le connessioni keep-alive idle
                                  # non devono tenere i thread appesi per sempre

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
                _PROXY['last_req'] = time.time()          # [WATCHDOG]
                if not _PROXY['base']:
                    self.send_error(503)
                    return
                h = {}
                if self.headers.get('Range'):
                    h['Range'] = self.headers['Range']

                # keepalive piggybacked sul traffico reale
                now = time.time()
                if _PROXY.get('t_url') and now - _PROXY.get('last_mint', 0) >= 150:
                    _PROXY['last_mint'] = now
                    _refresh_token()                      # token fresco PRIMA della scadenza 180s
                if now - _PROXY.get('last_hb', 0) >= 50:
                    _PROXY['last_hb'] = now
                    _send_heartbeat(now - _PROXY.get('t0', now))

                req_path, _, _ = self.path.partition('?')

                # [FASTSTART] cache playlist VOD
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

                url = _PROXY['base'] + req_path
                if _PROXY.get('fresh_query'):
                    url += '?' + _PROXY['fresh_query']

                sess = _get_session()
                try:
                    r = sess.get(url, headers=h, timeout=(10, 60), stream=True)
                    if r.status_code == 403 and _PROXY.get('t_url'):
                        try:
                            r.close()
                        except Exception:
                            pass
                        if _refresh_token():
                            url = _PROXY['base'] + req_path + '?' + _PROXY['fresh_query']
                            r = sess.get(url, headers=h, timeout=(10, 60), stream=True)
                except Exception as e:
                    logger.error('proxy upstream fail %s: %s' % (url[:120], str(e)[:150]))
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

        # porta fissa prima (resume stabile), effimera come fallback
        srv = None
        for p in (FIXED_PORT, 0):
            try:
                srv = _Srv(('127.0.0.1', p), _Handler)
                break
            except Exception:
                continue
        if srv is None:
            logger.error('proxy bind failed on all ports')
            return 0

        _PROXY['port'] = srv.server_address[1]
        _PROXY['server'] = srv
        _PROXY['last_req'] = time.time()      # [WATCHDOG] evita spegnimento immediato
        _PROXY['played'] = False              # [WATCHDOG]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        threading.Thread(target=_proxy_watchdog, args=(srv,), daemon=True).start()
        logger.info('local proxy started on 127.0.0.1:%d' % _PROXY['port'])
    return _PROXY['port']


# ============================ XOR FALLBACK (film; per le serie il player
# ha currentSrc vuoto, quindi il loro percorso e' /t/<token>/<s>/<e>) ============
_XOR_BLOCK_RE = re.compile(r"var\s+\w+\s*=\s*'([^']*)'\s*,\s*d\s*=\s*atob\(\s*'([^']*)'", re.S)


def _decode_xor_blocks(page):
    """Decodifica TUTTI i blocchi offuscati della pagina embed.
    Le pagine ne hanno 3+: il player non e' necessariamente nel primo."""
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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


# ============================ HELPER PER I CANALI ============================
def get_embed_page(page_url, referer=None):
    """Scarica il sorgente della pagina embed vidxgo con la sessione
    TLS-cleared (con sweep se serve). Serve ai canali per leggere
    stagioni/episodi delle serie, assenti dalle pagine del sito."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
        logger.error('get_embed_page: ' + traceback.format_exc())
    return ''

_D2B_MODE_RE = re.compile(r'<meta\s+name="d2b-mode"\s+content="(\w+)"')
_SHOW_SEASONS_RE = re.compile(r'seasons:\s*\[([^\]]*)\]')
_CURRENT_RE = re.compile(r'current\s*=\s*\{\s*s:\s*(\d+)\s*,\s*e:\s*(\d+)')
_SCACHE_RE = re.compile(r'seasonCache\s*=\s*\{(.+?)\};', re.S)
_EP_N_RE = re.compile(r'"n"\s*:\s*(\d+)')
_SCACHE_KEY_RE = re.compile(r'(?:^|[,{])\s*(\d+)\s*:\s*\[')


def _parse_season_cache(sc_text, default_season):
    """Coppie (stagione, episodio) dal JSON seasonCache del blob player.
    Chiavi: numeri literal ('1: [...]') oppure la forma calcolata
    '[current.s]: [...]' -> usa default_season dal blocco player."""
    pairs = set()
    parts = _SCACHE_KEY_RE.split(sc_text)
    if len(parts) > 1:
        it = iter(parts[1:])
        for key, body in zip(it, it):          # alterna chiave / corpo
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
    """{'mode': 'tv'|'movie'|'', 'episodes': [(s,e)..]}.
    Pagina default -> stagione renderizzata (seasonCache). Le ALTRE stagioni
    (da seasons[] nei metadata) vengono lette scaricando /token/<s>/1:
    1 richiesta ciascuna con la sessione TLS cached."""
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
            """[(s,e) della stagione renderizzata in quella pagina]"""
            pairs = set()
            for blob in _decode_xor_blocks(page):
                mc = _CURRENT_RE.search(blob)
                ds = int(mc.group(1)) if mc else 1
                ms = _SCACHE_RE.search(blob)
                if ms:
                    pairs |= _parse_season_cache(ms.group(1), ds)
            return pairs

        pairs = parse_page(embed)
        seasons_meta = []                       # [(n, count), ...]
        for blob in _decode_xor_blocks(embed):
            for msm in _SEASONS_ARR_RE.finditer(blob):
                for sn, cnt in re.findall(r'"n"\s*:\s*(\d+)\s*,\s*"count"\s*:\s*(\d+)',
                                          msm.group(1)):
                    seasons_meta.append((int(sn), int(cnt)))

        # stagioni non renderizzate nella pagina default: una pagina ciascuna
        covered = {s for s, _ in pairs}
        for sn, cnt in sorted(set(seasons_meta)):
            if sn in covered:
                continue
            emb2 = get_embed_page('%s/%s/%d/1' % (HOST, token, sn))
            if not emb2:
                continue
            got = parse_page(emb2)
            if not got:
                logger.info('probe %s: stagione %d (count=%d) senza episodi '
                            'nella sua pagina' % (token, sn, cnt))
            pairs |= got

        info['episodes'] = sorted(pairs)
        logger.info('probe %s: mode=tv, seasons_meta=%s, %d episodi %s'
                    % (token, sorted(set(seasons_meta)), len(pairs), sorted(pairs)))

        # diagnostica: i metadata promettono piu' episodi di quanti trovati
        # -> la stagione e' parzialmente indicizzata su vidxgo (non e' un bug nostro)
        for sn, cnt in sorted(set(seasons_meta)):
            found = len([1 for s, _ in pairs if s == sn])
            if cnt > found:
                logger.info('probe %s: stagione %d: metadata count=%d ma trovati %d '
                            '(episodi mancanti lato vidxgo)' % (token, sn, cnt, found))
        return info
    except Exception:
        logger.error('probe: ' + traceback.format_exc())
        return info

def _tv_default_episode(token):
    """(s, e) dell'episodio corrente dal blob player, se il token e' una
    serie; None per film o errori. Serve a guarire i play con token nudo:
    il player carica current = {s, e} e seasonCache con gli episodi reali."""
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
        # se l'episodio corrente esiste in cache usalo, altrimenti l'ultimo
        return (cs, ce if ce in eps else max(eps))
    except Exception:
        logger.error('_tv_default_episode: ' + traceback.format_exc())
        return None

# ============================ ENTRY POINT S4ME ============================
def test_video_exists(page_url):
    # check sintattico: il resolve reale costa una richiesta, avviene in get_video_url
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
        _PROXY['hb_type'] = 'series' if is_episode else 'movie'

        if is_episode:
            candidates = [HOST + '/t/' + '/'.join(path_parts[:3]),
                          HOST + '/t/' + '/'.join(path_parts[:3]) + '?se=0']
        else:
            candidates = [HOST + '/t/' + token]

        stream_url = None
        try:
            hdrs = {'User-Agent': FF_UA, 'Referer': page_url,
                    'Accept': 'application/json, text/plain, */*'}
            r, t_url, _s = _vidxgo_resolve(candidates, hdrs)
            if r is not None:
                try:
                    stream_url = r.json()['url']
                except Exception:
                    logger.error('/t/ returned non-JSON: ' + r.text[:200])
                    stream_url = None
                else:
                    _PROXY['t_url'] = t_url
                    _PROXY['fresh_query'] = urllib.parse.urlparse(stream_url).query
        except Exception:
            logger.error('resolve failed: ' + traceback.format_exc())

        # --- HEAL: token nudo che /t/ rifiuta -> potrebbe essere una serie;
        #     legge stagione/episodio corrente dal player e riprova /t/<s>/<e>
        #     (1 richiesta embed + 1 retry, fingerprint cached, niente sweep) ---
        if not stream_url and not is_episode:
            eps = _tv_default_episode(token)
            if eps:
                s0, e0 = eps
                logger.info('token nudo = serie, provo /t/%s/%d/%d' % (token, s0, e0))
                _PROXY['hb_type'] = 'series'
                try:
                    hdrs = {'User-Agent': FF_UA, 'Referer': HOST + '/',
                            'Accept': 'application/json, text/plain, */*'}
                    r, t_url, _s = _vidxgo_resolve(
                        [HOST + '/t/%s/%d/%d' % (token, s0, e0)], hdrs)
                    if r is not None:
                        try:
                            stream_url = r.json()['url']
                        except Exception:
                            logger.error('heal non-JSON: ' + r.text[:200])
                            stream_url = None
                        else:
                            _PROXY['t_url'] = t_url
                            _PROXY['fresh_query'] = urllib.parse.urlparse(stream_url).query
                except Exception:
                    logger.error('heal retry failed: ' + traceback.format_exc())

        # fallback XOR (utile per i film; per le serie il player ha
        # currentSrc vuoto quindi qui non trovera' nulla, ed e' ok)
        if not stream_url:
            try:
                stream_url = extract_m3u8_from_embed(_vidxgo_session(), page_url,
                                                     referer=REF_SITE + '/')
                _PROXY['t_url'] = ''
            except Exception as e:
                logger.error('embed extraction failed: %s' % e)

        if not stream_url:
            return []

        # --- [REUSE-FIX] ricicla la sessione relay: le connessioni keep-alive
        #     del play precedente possono essere state chiuse dal CDN durante
        #     la pausa tra i due play; riutilizzarle = prima richiesta appesa
        #     su connessione mezza-morta -> ffmpeg attende il timeout ->
        #     'OpenDemuxStream - Error creating demuxer' ---
        global _SESSION
        try:
            if _SESSION is not None:
                _SESSION.close()
        except Exception:
            pass
        _SESSION = None

        u = urllib.parse.urlparse(stream_url)
        _PROXY['base'] = u.scheme + '://' + u.netloc
        _PROXY['master_path'] = u.path
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

        # s4me: lista di coppie [etichetta_qualita, url]
        return [['vidxgo', proxy_url]]
    except Exception:
        logger.error('vidxgo: ' + traceback.format_exc())
        return []
