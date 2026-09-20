# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# core/hlsdl.py — download HLS (m3u8) -> file locale
#
# ffmpeg (se presente) : remux .mp4 con -c copy (via preferita)
# fallback Python      : segmenti IN PARALLELO -> .ts
#                        AES-128 SUPPORTATO: pycryptodome con discovery
#                        multi-livello (Cryptodome / Crypto / addon Kodi
#                        / lib dell'addon) o cryptography
#
# RESUME [RESUME]: sidecar <file>.hlsdl con i segmenti completati.
#   Crash/riavvio -> al rilancio salta i segmenti gia' scritti e
#   APPENDE. Sidecar atomico ogni 10 segmenti. Rimosso al completamento.
#
# MEMORIA [MEM-FIX]: finestra scorrevole — solo ~workers*3 segmenti
#   in volo; i buffer vengono liberati appena scritti.
#
# PATIENT: retry con backoff ~40s per segmento.
#
# COSMETIC: popup con "[xx%]" nell'heading.
#
# AES-FIX [AES]: su Windows Kodi il pacchetto e' sotto il namespace
#   'Cryptodome' (non 'Crypto'): discovery in ordine Cryptodome ->
#   Crypto -> addon Kodi (script.module.pycryptodome / lib dell'addon)
#   -> cryptography. Ogni tentativo e' loggato: nel kodi.log si vede
#   SEMPRE quale backend e' stato trovato (o perche' no).
# ------------------------------------------------------------

import os, re, time, subprocess, traceback
from platformcode import logger

FFMPEG = 'ffmpeg'      # percorso completo se un giorno lo installi
WORKERS = 6            # connessioni parallele (6 = safe per il CDN)


def _notify(msg):
    try:
        import xbmcgui
        xbmcgui.Dialog().notification('HLS download', msg,
                                      xbmcgui.NOTIFICATION_INFO, 5000)
    except Exception:
        pass

_AES_BACKEND = None


class _ProgressWithPct(object):
    """DialogProgressBG che mostra 'Titolo [xx%]' nell'heading,
    aggiornato a ogni update(pct)."""

    def __init__(self):
        try:
            import xbmcgui
            self._d = xbmcgui.DialogProgressBG()
            self._heading = 'HLS download'
        except Exception:
            self._d = None

    def create(self, title=None, msg=''):
        if self._d is None:
            return
        try:
            if title:
                self._heading = str(title)
            self._d.create('HLS download', self._heading)
        except Exception:
            pass

    def update(self, pct, msg=''):
        if self._d is None:
            return
        try:
            p = max(0, min(100, int(pct)))
            self._d.update(p, '%s [%d%%]' % (self._heading, p),
                           msg if msg else '')
        except Exception:
            pass

    def close(self):
        if self._d is None:
            return
        try:
            self._d.close()
        except Exception:
            pass


def _progress():
    try:
        return _ProgressWithPct()
    except Exception:
        class _N:
            def create(self, *a, **k): pass
            def update(self, *a, **k): pass
            def close(self, *a, **k): pass
        return _N()


def _abs(base, u):
    """Risolve URL relativi (segmenti/key/map) contro l'URL della playlist."""
    u = u.strip()
    if u.startswith('http'):
        return u
    if u.startswith('/'):
        return re.match(r'(https?://[^/]+)', base).group(1) + u
    return base.rsplit('/', 1)[0] + '/' + u


# ---------------------------------------------------------- AES-128 ----

# [AES-FIX] addon che possono fornire pycryptodome (oltre al namespace
# gia' presente nel Python di Kodi). Includiamo anche la nostra lib/:
_AES_ADDON_CANDIDATES = (
    'script.module.pycryptodome',
    'plugin.video.s4me',        # la nostra lib/ se il fork la bundla
)


def _safe_addon_path(addon_id):
    """Ritorna il path dell'addon se esiste, altrimenti None."""
    try:
        import xbmcaddon
        return xbmcaddon.Addon(addon_id).getAddonInfo('path')
    except Exception:
        return None


def _find_package_dir(base, package_name):
    """Cerca ricorsivamente `package_name` sotto `base` (max 3 livelli).
    Ritorna il path della directory che CONTIENE il package, o None."""
    target = os.path.join(base, package_name)
    if os.path.isdir(target):
        return base
    try:
        for root, dirs, _files in os.walk(base):
            depth = root[len(base):].count(os.sep)
            if depth > 3:
                dirs[:] = []
                continue
            if package_name in dirs:
                return root
    except Exception:
        pass
    return None


def _try_import_pycryptodome():
    """[AES-FIX] Ordine di tentativi:
       1) 'Cryptodome' (fork ufficiale, E' quello che Kodi spedisce su
          Windows/Android in system/Python/Lib/site-packages)
       2) 'Crypto'     (namespace classico)
       3) come addon Kodi: 'Cryptodome' o 'Crypto' nel path dell'addon
          (script.module.pycryptodome, o la lib del nostro addon)
    Ritorna il modulo AES oppure None."""
    # 1) Cryptodome
    try:
        from Cryptodome.Cipher import AES as _AES
        logger.info('hlsdl: pycryptodome trovato come Cryptodome')
        return _AES
    except Exception:
        pass

    # 2) Crypto
    try:
        from Crypto.Cipher import AES as _AES
        logger.info('hlsdl: pycryptodome trovato come Crypto')
        return _AES
    except Exception:
        pass

    # 3) come addon Kodi
    import sys
    for addon_id in _AES_ADDON_CANDIDATES:
        base = _safe_addon_path(addon_id)
        if not base:
            logger.info('hlsdl: addon %s non presente' % addon_id)
            continue
        logger.info('hlsdl: addon %s trovato in %s' % (addon_id, base))

        for pkg_name in ('Cryptodome', 'Crypto'):
            # rimuovi eventuali import falliti precedenti
            for m in list(sys.modules):
                if m == pkg_name or m.startswith(pkg_name + '.'):
                    del sys.modules[m]
            pkg_parent = _find_package_dir(base, pkg_name)
            if not pkg_parent:
                continue
            logger.info('hlsdl: "%s" trovato in %s' % (pkg_name, pkg_parent))
            if pkg_parent not in sys.path:
                sys.path.insert(0, pkg_parent)
            try:
                if pkg_name == 'Cryptodome':
                    from Cryptodome.Cipher import AES as _AES
                else:
                    from Crypto.Cipher import AES as _AES
                return _AES
            except Exception as e:
                logger.error('hlsdl: import %s.Cipher fallito: %s'
                             % (pkg_name, e))

    return None


def _try_import_cryptography():
    try:
        from cryptography.hazmat.primitives.ciphers import (Cipher as _C,
                                                            algorithms as _al,
                                                            modes as _mo)
        return (_C, _al, _mo)
    except Exception:
        return None


def _aes_backend():
    """[AES-FIX] Trova un backend AES con discovery multi-livello.
    Ritorna (nome, obj) oppure (None, None). Cachato in _AES_BACKEND."""
    global _AES_BACKEND
    if _AES_BACKEND is not None:
        return _AES_BACKEND

    aes = _try_import_pycryptodome()
    if aes is not None:
        _AES_BACKEND = ('pc', aes)
        logger.info('hlsdl: AES backend = pycryptodome')
        return _AES_BACKEND

    cg = _try_import_cryptography()
    if cg is not None:
        _AES_BACKEND = ('cg', cg)
        logger.info('hlsdl: AES backend = cryptography')
        return _AES_BACKEND

    logger.error('hlsdl: nessun backend AES disponibile (Cryptodome/Crypto/'
                 'cryptography). Su Windows: verifica che esista '
                 'system/Python/Lib/site-packages/Cryptodome, oppure '
                 'installa script.module.pycryptodome, oppure ffmpeg.')
    _notify('playlist cifrata: nessun backend AES')
    _AES_BACKEND = (None, None)
    return _AES_BACKEND


def _aes_decrypt(key, iv, data):
    """AES-128-CBC decrypt + strip PKCS7 (i segmentatori HLS usano PKCS7)."""
    name, obj = _aes_backend()
    if name == 'pc':
        out = obj.new(key, obj.MODE_CBC, iv).decrypt(data)
    elif name == 'cg':
        C, al, mo = obj
        d = C(al.AES(key), mo.CBC(iv)).decryptor()
        out = d.update(data) + d.finalize()
    else:
        raise RuntimeError('nessun backend AES disponibile')
    n = out[-1] if out else 0
    if 1 <= n <= 16 and out.endswith(bytes([n]) * n):
        out = out[:-n]
    return out


def _parse_ext_x_key(line):
    d = {'method': 'NONE', 'uri': None, 'iv': None}
    m = re.search(r'METHOD=([^,\s]+)', line)
    if m:
        d['method'] = m.group(1)
    m = re.search(r'URI="([^"]+)"', line)
    if m:
        d['uri'] = m.group(1)
    m = re.search(r'IV=0[xX]([0-9a-fA-F]+)', line)
    if m:
        d['iv'] = bytes.fromhex(m.group(1).zfill(32))[:16]   # pad a sx -> 16 byte
    return d


# ------------------------------------------------------------ ffmpeg ----

def download_hls_ffmpeg(m3u8_url, dest, headers=None, ua=None):
    """Remux senza ricodifica. Se ffmpeg non c'e', ritorna None -> fallback."""
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
        logger.info('hlsdl: ffmpeg non installato -> fallback Python')
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
    """Fallback senza ffmpeg: segmenti IN PARALLELO, scritti IN ORDINE.
    AES-128 supportato (discovery multi-livello).
    [RESUME] sidecar <dest>.hlsdl: al rilancio salta i segmenti gia'
    scritti e APPENDE — niente ripartenza da 0 dopo crash/riavvio.
    [MEM-FIX] finestra scorrevole: solo ~workers*3 segmenti in volo.
    [PATIENT] retry con backoff ~40s per segmento."""
    import requests
    from collections import deque
    from requests.adapters import HTTPAdapter
    from concurrent.futures import ThreadPoolExecutor

    sidecar = dest_ts + '.hlsdl'

    # --- [RESUME] segmenti gia' scritti? ---
    resume_from = 0
    if os.path.isfile(sidecar) and os.path.isfile(dest_ts):
        try:
            resume_from = int(open(sidecar).read().strip() or 0)
        except Exception:
            resume_from = 0
    if resume_from < 0:
        resume_from = 0

    s = requests.Session()
    s.headers.update({'User-Agent': ua or 'Mozilla/5.0'})
    for k, v in (headers or []):
        s.headers[k] = v
    adapter = HTTPAdapter(pool_connections=workers + 2, pool_maxsize=workers + 2)
    s.mount('http://', adapter)
    s.mount('https://', adapter)

    def get(u, binary=False, tries=6):
        """[PATIENT] retry con backoff: 1+2+4+8+16+20s ≈ 40s di tolleranza
        per segmento — assorbe blip VPN e pause del CDN senza abortire."""
        last = None
        for attempt in range(tries):
            if attempt:
                time.sleep(min(20, 2 ** (attempt - 1)))
            try:
                r = s.get(u, timeout=30)
                r.raise_for_status()
                return r.content if binary else r.text
            except Exception as e:
                last = e
        raise last

    data = get(m3u8_url)
    if '#EXT-X-STREAM-INF' in data:                # master -> variante max
        pairs = re.findall(r'#EXT-X-STREAM-INF[^\n]*BANDWIDTH=(\d+)[^\n]*\n([^\n#][^\n]*)', data)
        if not pairs:
            logger.error('hlsdl: master senza varianti leggibili')
            return None
        best = max(pairs, key=lambda p: int(p[0]))[1].strip()
        data = get(_abs(m3u8_url, best))

    # --- parsing playlist: segmenti + chiavi correnti + sequence ---
    segs = []          # (url, key_dict|None, media_sequence)
    seq = 0
    cur_key = None
    for line in data.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                seq = int(line.split(':', 1)[1])
            except Exception:
                seq = 0
        elif line.startswith('#EXT-X-KEY:'):
            k = _parse_ext_x_key(line)
            if k['method'] in ('NONE', ''):
                cur_key = None
            elif k['method'] == 'AES-128' and k['uri']:
                cur_key = k
            else:
                logger.error('hlsdl: metodo chiave non supportato: %s (serve ffmpeg)'
                             % k['method'])
                _notify('cifratura non supportata: installa ffmpeg')
                return None
        elif line and not line.startswith('#'):
            segs.append((_abs(m3u8_url, line), cur_key, seq))
            seq += 1

    if not segs:
        logger.error('hlsdl: nessun segmento nella playlist')
        return None

    # --- [RESUME] sanity: il sidecar non puo' superare la playlist ---
    if resume_from >= len(segs):
        logger.info('hlsdl: sidecar (%d) >= playlist (%d): reset'
                    % (resume_from, len(segs)))
        resume_from = 0

    # --- chiavi AES: scaricate una volta per URI (solo per i segmenti da fare) ---
    keys = {}
    encrypted = any(k is not None for _, k, _ in segs[resume_from:])
    if encrypted:
        name, _o = _aes_backend()
        if name is None:
            logger.error('hlsdl: playlist cifrata ma nessun backend AES '
                         '(vedi log discovery qui sopra).')
            return None
        logger.info('hlsdl: playlist cifrata AES-128, backend: %s' % name)
        for _, k, _sq in segs[resume_from:]:
            if k and k['uri'] not in keys:
                kb = get(_abs(m3u8_url, k['uri']), binary=True)
                if len(kb) != 16:
                    logger.error('hlsdl: chiave AES di %d byte (attesi 16)' % len(kb))
                    return None
                keys[k['uri']] = kb

    m = re.search(r'#EXT-X-MAP:URI="?([^",\s]+)"?', data)   # fMP4: init segment
    init_uri = _abs(m3u8_url, m.group(1)) if m else None

    def fetch_one(args):
        u, k, sq = args
        b = get(u, binary=True)
        if k is None:
            return b
        iv = k['iv'] or sq.to_bytes(16, 'big')   # IV assente -> media sequence
        return _aes_decrypt(keys[k['uri']], iv, b)

    todo = segs[resume_from:]
    INFLIGHT = max(4, workers * 3)
    logger.info('hlsdl: %d segmenti (%s), %d worker, finestra %d, resume da %d'
                % (len(segs), 'cifrati' if encrypted else 'in chiaro',
                   workers, INFLIGHT, resume_from))

    # [COSMETIC] titolo del film nell'heading (senza estensione)
    prog = _progress()
    prog.create(os.path.basename(dest_ts).rsplit('.', 1)[0], '')

    ok = 0                      # segmenti scritti IN QUESTA sessione
    t0 = time.time()
    bytes_done = 0
    next_ms = 0.1 if resume_from == 0 else (float(resume_from + 1) / len(segs))
    ex = ThreadPoolExecutor(max_workers=workers)
    window = deque()
    seg_iter = iter(todo)

    def _submit_more(n):
        added = 0
        while added < n:
            try:
                a = next(seg_iter)
            except StopIteration:
                return
            window.append(ex.submit(fetch_one, a))
            added += 1

    def _save_sidecar():
        try:
            tmp = sidecar + '.tmp'
            with open(tmp, 'w') as _sf:
                _sf.write(str(resume_from + ok))
            os.replace(tmp, sidecar)
        except Exception:
            pass

    try:
        mode = 'ab' if resume_from else 'wb'    # append se riprendiamo
        with open(dest_ts, mode) as f:
            if resume_from == 0 and init_uri:
                f.write(get(init_uri, binary=True))
            _submit_more(INFLIGHT)
            while window:
                fut = window.popleft()
                content = fut.result()
                f.write(content)
                ok += 1
                bytes_done += len(content)
                del content                     # [MEM-FIX] libera subito
                _submit_more(1)                 # tieni la finestra piena
                if ok % 10 == 0:
                    _save_sidecar()
                pct = (resume_from + ok) / float(len(segs))
                prog.update(int(pct * 100))     # [COSMETIC] -> "[xx%]" nell'heading
                if pct >= next_ms:
                    dt = time.time() - t0
                    if dt > 0:
                        logger.info('hlsdl: %d%% (%.1f MB/s medi)' %
                                    (int(pct * 100), bytes_done / dt / 1e6))
                    next_ms += 0.1
    except Exception:
        logger.error('hlsdl segmento %d/%d: %s'
                     % (resume_from + ok + 1, len(segs),
                        traceback.format_exc()[-300:]))
    finally:
        ex.shutdown(wait=True)
        _save_sidecar()
        prog.close()

    if resume_from + ok == len(segs):
        # completo: il sidecar non serve piu'
        try:
            os.remove(sidecar)
        except Exception:
            pass
        logger.info('hlsdl: %d/%d segmenti -> %s' % (len(segs), len(segs), dest_ts))
        return dest_ts
    logger.info('hlsdl: %d/%d segmenti (resume da %d) -> %s'
                % (resume_from + ok, len(segs), resume_from, dest_ts))
    if resume_from + ok:
        logger.info('hlsdl: download parziale (riprendibile)')
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
