# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# core/hlsdl.py — download HLS (m3u8) -> file locale
#
# ffmpeg (se presente) : remux .mp4 con -c copy (gestisce AES-128)
# fallback Python      : segmenti IN PARALLELO -> .ts (niente AES-128)
#
# Su questo OSMC ffmpeg NON e' installato di proposito: si usa sempre
# il fallback Python (il .ts si legge benissimo in Kodi).
#
# Chiamato da specials/downloads.py::download_hls()
# ------------------------------------------------------------

import os, re, time, subprocess, traceback
from platformcode import logger

FFMPEG = 'ffmpeg'      # percorso completo se un giorno lo installi
WORKERS = 6            # connessioni parallele nel fallback Python


def _notify(msg):
    try:
        import xbmcgui
        xbmcgui.Dialog().notification('HLS download', msg,
                                      xbmcgui.NOTIFICATION_INFO, 5000)
    except Exception:
        pass


def _progress():
    try:
        import xbmcgui
        return xbmcgui.DialogProgressBG()
    except Exception:
        class _N:                              # stub se xbmcgui non c'e'
            def create(self, *a, **k): pass
            def update(self, *a, **k): pass
            def close(self, *a, **k): pass
        return _N()


def _abs(base, u):
    """Risolve URL relativi dei segmenti contro l'URL della playlist."""
    u = u.strip()
    if u.startswith('http'):
        return u
    if u.startswith('/'):
        return re.match(r'(https?://[^/]+)', base).group(1) + u
    return base.rsplit('/', 1)[0] + '/' + u


# ------------------------------------------------------------ ffmpeg ----

def download_hls_ffmpeg(m3u8_url, dest, headers=None, ua=None):
    """Remux senza ricodifica. Su questo sistema ffmpeg non c'e' di
    proposito: la funzione resta per chi volesse installarlo."""
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    if ua:
        cmd += ['-user_agent', ua]
    for k, v in (headers or []):
        cmd += ['-headers', '%s: %s\r\n' % (k, v)]     # CRLF obbligatorio
    cmd += ['-reconnect', '1', '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5']
    cmd += ['-i', m3u8_url, '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart', dest]
    logger.info('hlsdl: ' + ' '.join(cmd))
    try:
        d = os.path.dirname(dest)
        if d:
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    out = b''
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = p.communicate()
    except FileNotFoundError:
        logger.info('hlsdl: ffmpeg non installato -> fallback Python')  # [FIX] info, non errore
        return None
    except Exception:
        logger.error('hlsdl ffmpeg: ' + traceback.format_exc()[-300:])
        return None
    if p.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0:
        logger.info('hlsdl ffmpeg ok: %s (%d byte)' % (dest, os.path.getsize(dest)))
        return dest
    logger.error('hlsdl ffmpeg fallito (%s): %s'
                 % (p.returncode, (out or b'')[-400:]))
    try:
        if os.path.isfile(dest):
            os.remove(dest)
    except Exception:
        pass
    return None


# ------------------------------------------------------------ python ----

def download_hls_python(m3u8_url, dest_ts, headers=None, ua=None, workers=WORKERS):
    """Fallback senza ffmpeg: segmenti IN PARALLELO (ThreadPoolExecutor),
    scritti IN ORDINE (map() preserva l'ordine -> .ts coerente).
    Sessione con keep-alive: una connessione per worker -> il DNS del
    proxy si risolve poche volte, non per segmento.
    Limiti: niente AES-128 (playlist cifrate), niente resume."""
    import requests
    from requests.adapters import HTTPAdapter
    from concurrent.futures import ThreadPoolExecutor

    s = requests.Session()
    s.headers.update({'User-Agent': ua or 'Mozilla/5.0'})
    for k, v in (headers or []):
        s.headers[k] = v
    adapter = HTTPAdapter(pool_connections=workers + 2, pool_maxsize=workers + 2)
    s.mount('http://', adapter)
    s.mount('https://', adapter)

    def get(u, binary=False, tries=3):
        last = None
        for _ in range(tries):
            try:
                r = s.get(u, timeout=30)
                r.raise_for_status()
                return r.content if binary else r.text
            except Exception as e:
                last = e
                time.sleep(1)
        raise last

    data = get(m3u8_url)
    if '#EXT-X-STREAM-INF' in data:                # master -> variante max
        pairs = re.findall(r'#EXT-X-STREAM-INF[^\n]*BANDWIDTH=(\d+)[^\n]*\n([^\n#][^\n]*)', data)
        if not pairs:
            logger.error('hlsdl: master senza varianti leggibili')
            return None
        best = max(pairs, key=lambda p: int(p[0]))[1].strip()
        data = get(_abs(m3u8_url, best))

    if re.search(r'#EXT-X-KEY:METHOD=(?!NONE)', data):
        logger.error('hlsdl: playlist cifrata (AES-128): serve ffmpeg')
        _notify('playlist cifrata: installa ffmpeg')
        return None

    m = re.search(r'#EXT-X-MAP:URI="?([^",\s]+)"?', data)   # fMP4: init segment
    init_uri = _abs(m3u8_url, m.group(1)) if m else None

    segs = [_abs(m3u8_url, l.strip()) for l in data.splitlines()
            if l.strip() and not l.startswith('#')]
    if not segs:
        logger.error('hlsdl: nessun segmento nella playlist')
        return None

    logger.info('hlsdl: %d segmenti, %d worker paralleli' % (len(segs), workers))
    prog = _progress()
    prog.create('HLS download', os.path.basename(dest_ts))
    ok = 0
    try:
        with open(dest_ts, 'wb') as f:
            if init_uri:
                f.write(get(init_uri, binary=True))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for content in ex.map(lambda u: get(u, binary=True), segs):
                    f.write(content)
                    ok += 1
                    prog.update(int(100.0 * ok / len(segs)))
    except Exception:
        logger.error('hlsdl segmento %d/%d: %s'
                     % (ok + 1, len(segs), traceback.format_exc()[-300:]))
    finally:
        prog.close()
    logger.info('hlsdl: %d/%d segmenti -> %s' % (ok, len(segs), dest_ts))
    if ok == len(segs):
        return dest_ts
    if ok:
        logger.info('hlsdl: download parziale (file lasciato, stato=errore)')
    return None


def download(m3u8_url, dest_base, headers=None, ua=None):
    """Entry point: ffmpeg (.mp4) se c'e', altrimenti Python parallelo (.ts)."""
    if not m3u8_url:
        return None
    r = download_hls_ffmpeg(m3u8_url, dest_base + '.mp4', headers, ua)
    if r:
        _notify('Download completato')
        return r
    r = download_hls_python(m3u8_url, dest_base + '.ts', headers, ua)
    if r:
        _notify('Download completato')
    return r
