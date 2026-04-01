# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# S4Me Assistant - Modulo Python per addon Kodi
# Gestisce il bypass Cloudflare tramite app Android S4Me Assistant
# Supporta modalita LOCALE (stesso dispositivo) e REMOTA (dispositivi diversi)
# ----------------------------------------------------------------------------

import os
import sys
import time
import hashlib
import threading

try:
    import urllib.parse as urlparse
    import http.cookiejar as cookielib
except ImportError:
    import urlparse
    import cookielib

from platformcode import config, logger

# ============================================================================
# COSTANTI E PERCORSI CONDIVISI
# ============================================================================

# Percorsi base condivisi (speculari all'app Android)
# Primario: /sdcard/data/com.s4meapp/ (fuori Android/data, leggibile senza permessi)
# Fallback: /sdcard/Download/S4MEAssistant/
# Supporto multi-utente: /storage/emulated/0 per utente principale, /1 per secondario ecc.

def _get_android_user_id():
    """Ottiene l'ID utente Android corrente.
    Android assegna UID = user_id * 100000 + app_id
    Utente principale = 0, secondario = 1, ecc.
    """
    try:
        uid = os.getuid()
        return uid // 100000
    except Exception:
        return 0

_ANDROID_USER_ID = _get_android_user_id()

_SHARED_PATHS = [
    "/sdcard/data/com.s4meapp",
    "/storage/emulated/%d/data/com.s4meapp" % _ANDROID_USER_ID,
    "/sdcard/Download/S4MEAssistant",
    "/storage/emulated/%d/Download/S4MEAssistant" % _ANDROID_USER_ID,
]

def _get_shared_base_path():
    """Trova il path base condiviso con l'app (cerca in ordine di priorita)."""
    for path in _SHARED_PATHS:
        if os.path.isdir(path):
            return path
    return _SHARED_PATHS[0]

SHARED_BASE_PATH = _get_shared_base_path()

# File heartbeat - scritto dall'app ogni 30 secondi
HEARTBEAT_FILE_PATH = os.path.join(SHARED_BASE_PATH, "s4me_running.flag")

# Cartella backup cookie (solo per debug/ispezione)
SHARED_COOKIES_PATH = os.path.join(SHARED_BASE_PATH, "cookies")

# Porta di default del server HTTP nell'app
DEFAULT_PORT = 8787

# Timeout di default per la risoluzione (millisecondi)
DEFAULT_RESOLVE_TIMEOUT = 120000

# Massimo numero di tentativi per risolvere un dominio
MAX_RESOLVE_RETRIES = 3

# Soglia heartbeat: se piu vecchio di N secondi, app considerata non attiva
HEARTBEAT_MAX_AGE = 60

# Timeout connessione HTTP verso l'app (secondi)
HTTP_CONNECT_TIMEOUT = 5

# Timeout lettura risposta dall'app (secondi - alto per dare tempo alla WebView e al cambio DNS)
HTTP_READ_TIMEOUT = 130

# Header Netscape cookie file
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# https://curl.haxx.se/rfc/cookie_spec.html\n# This is a generated file! Do not edit.\n"

# ============================================================================
# LOCK PER DOMINIO (thread-safe)
# ============================================================================

_domain_locks = {}
_domain_locks_lock = threading.Lock()

# Domini per cui i cookie sono gia stati caricati nel jar in questa sessione
_cookies_loaded_domains = set()

# Mappa fallback: dominio originale -> dominio effettivo (es. "1337x.to" -> "x1337x.cc")
_domain_fallback_map = {}


def _get_fallback_map_file():
    """Path del file che salva il mapping fallback su disco."""
    return os.path.join(config.get_data_path(), "cookies", "fallback_map.json")


def _load_fallback_map():
    """Carica il mapping fallback da disco."""
    global _domain_fallback_map
    try:
        path = _get_fallback_map_file()
        if os.path.isfile(path):
            import json
            with open(path, "r") as f:
                _domain_fallback_map = json.load(f)
            logger.debug("S4Me: fallback map caricata: %s" % str(_domain_fallback_map))
    except Exception:
        pass


def _save_fallback_map():
    """Salva il mapping fallback su disco."""
    try:
        path = _get_fallback_map_file()
        cookies_dir = os.path.dirname(path)
        if not os.path.isdir(cookies_dir):
            os.makedirs(cookies_dir)
        import json
        with open(path, "w") as f:
            json.dump(_domain_fallback_map, f)
    except Exception:
        pass


_fallback_map_loaded = False

def get_effective_domain(domain):
    """Restituisce il dominio effettivo (dopo fallback) o il dominio stesso."""
    global _fallback_map_loaded
    if not _fallback_map_loaded:
        _load_fallback_map()
        _fallback_map_loaded = True
        logger.info("S4Me: fallback map caricata da disco: %s" % str(_domain_fallback_map))
    result = _domain_fallback_map.get(domain, domain)
    if result != domain:
        logger.info("S4Me: effective domain: %s -> %s" % (domain, result))
    return result


def _set_fallback(original, effective):
    """Registra un mapping fallback e lo salva su disco."""
    _domain_fallback_map[original] = effective
    _save_fallback_map()


def _get_domain_lock(domain):
    """Restituisce un Lock specifico per il dominio (creato lazy)."""
    with _domain_locks_lock:
        if domain not in _domain_locks:
            _domain_locks[domain] = threading.Lock()
        return _domain_locks[domain]


# ============================================================================
# CONFIGURAZIONE (lettura impostazioni addon)
# ============================================================================

def is_enabled():
    """Controlla se S4Me Assistant e abilitato nelle impostazioni."""
    return config.get_setting("s4me_enabled", default=False)


def get_remote_ip():
    """Restituisce l'IP del server S4Me Assistant."""
    return config.get_setting("s4me_remote_ip", default="127.0.0.1")


def get_remote_port():
    """Restituisce la porta del server."""
    port = config.get_setting("s4me_remote_port", default=DEFAULT_PORT)
    return int(port) if port else DEFAULT_PORT


def is_local():
    """Restituisce True se l'IP configurato e localhost (stesso dispositivo)."""
    ip = get_remote_ip()
    return ip in ("127.0.0.1", "localhost", "")


def get_base_url():
    """Costruisce l'URL base del server S4Me Assistant."""
    ip = get_remote_ip()
    port = get_remote_port()
    if not ip:
        ip = "127.0.0.1"
    return "http://%s:%d" % (ip, port)


# ============================================================================
# GESTIONE NOMI FILE COOKIE
# ============================================================================

def _sanitize_domain(domain):
    """Sanitizza il dominio per usarlo come nome file.
    Sostituisce punti e caratteri problematici con underscore.
    Es: hd4me.net -> hd4me_net
    """
    # Rimuove eventuale punto iniziale
    domain = domain.lstrip(".")
    # Sostituisce caratteri non alfanumerici con underscore
    safe = ""
    for c in domain:
        if c.isalnum() or c == "_":
            safe += c
        else:
            safe += "_"
    return safe


def get_cookie_filename(domain):
    """Restituisce il percorso assoluto del file cookie per un dominio.
    Il file viene salvato nella cartella privata dell'addon:
    config.get_data_path()/cookies/<dominio_sanitizzato>.txt
    """
    cookies_dir = os.path.join(config.get_data_path(), "cookies")
    if not os.path.exists(cookies_dir):
        try:
            os.makedirs(cookies_dir)
        except OSError:
            pass
    filename = _sanitize_domain(domain) + ".txt"
    return os.path.join(cookies_dir, filename)


# ============================================================================
# VERIFICA VALIDITA COOKIE
# ============================================================================

# Durata massima dei cookie CF in secondi (30 minuti)
# Cloudflare imposta cf_clearance con durata tra 15min e 2h, 
# ma 30min e un valore sicuro per la maggior parte dei siti
CF_COOKIE_MAX_AGE = 1800


def cookies_valid(domain):
    """Verifica se esistono cookie validi (non scaduti) per un dominio.
    Controlla anche il dominio fallback se il file per il dominio originale non esiste.
    """
    # Prova prima il dominio richiesto, poi il fallback
    domains_to_check = [domain]
    effective = get_effective_domain(domain)
    if effective != domain:
        domains_to_check.append(effective)
    
    for check_domain in domains_to_check:
        cookie_file = get_cookie_filename(check_domain)
        if not os.path.isfile(cookie_file):
            continue

        try:
            file_age = time.time() - os.path.getmtime(cookie_file)
            if file_age > CF_COOKIE_MAX_AGE:
                try:
                    os.remove(cookie_file)
                except Exception:
                    pass
                _cookies_loaded_domains.discard(check_domain)
                continue
        except Exception:
            continue

        # Verifica che contenga cf_clearance
        try:
            with open(cookie_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7 and parts[5] == "cf_clearance":
                        remaining = CF_COOKIE_MAX_AGE - file_age
                        logger.debug("S4Me: cf_clearance valido per %s (resta ~%.0f min)" 
                                     % (check_domain, remaining / 60))
                        return True
        except Exception:
            continue

    return False


def _invalidate_domain_cookies(domain):
    """Invalida i cookie di un dominio: cancella il file e resetta la cache."""
    cookie_file = get_cookie_filename(domain)
    try:
        if os.path.isfile(cookie_file):
            os.remove(cookie_file)
    except Exception:
        pass
    _cookies_loaded_domains.discard(domain)
    # Rimuovi anche l'UA cached per forzare un refresh
    _domain_user_agents.pop(domain, None)


def _save_cookies_txt(domain, cookies_txt):
    """Salva la stringa cookie Netscape nel file dedicato al dominio."""
    cookie_file = get_cookie_filename(domain)
    try:
        with open(cookie_file, "w") as f:
            f.write(cookies_txt)
        logger.info("S4Me: cookie salvati in %s" % cookie_file)
        return True
    except Exception as e:
        logger.error("S4Me: errore salvataggio cookie per %s: %s" % (domain, str(e)))
        return False


# Cache in memoria degli User-Agent per dominio
_domain_user_agents = {}


def _save_user_agent(domain, user_agent):
    """Salva lo User-Agent della WebView per un dominio.
    Lo salva sia in memoria che su file per persistenza.
    Usa la stessa cartella dei cookie (addon_data/cookies/) per funzionare su tutte le piattaforme.
    """
    _domain_user_agents[domain] = user_agent
    try:
        cookies_dir = os.path.join(config.get_data_path(), "cookies")
        if not os.path.exists(cookies_dir):
            os.makedirs(cookies_dir)
        ua_file = os.path.join(cookies_dir, _sanitize_domain(domain) + ".ua")
        with open(ua_file, "w") as f:
            f.write(user_agent)
    except Exception:
        pass


def get_domain_user_agent(domain):
    """Restituisce lo User-Agent per un dominio CF. Prova anche il fallback."""
    # Cache in memoria
    if domain in _domain_user_agents:
        return _domain_user_agents[domain]
    # File su disco
    try:
        cookies_dir = os.path.join(config.get_data_path(), "cookies")
        ua_file = os.path.join(cookies_dir, _sanitize_domain(domain) + ".ua")
        if os.path.isfile(ua_file):
            with open(ua_file, "r") as f:
                ua = f.read().strip()
            if ua:
                _domain_user_agents[domain] = ua
                return ua
    except Exception:
        pass
    # Prova dominio fallback
    effective = get_effective_domain(domain)
    if effective != domain:
        if effective in _domain_user_agents:
            return _domain_user_agents[effective]
        try:
            cookies_dir = os.path.join(config.get_data_path(), "cookies")
            ua_file = os.path.join(cookies_dir, _sanitize_domain(effective) + ".ua")
            if os.path.isfile(ua_file):
                with open(ua_file, "r") as f:
                    ua = f.read().strip()
                if ua:
                    _domain_user_agents[effective] = ua
                    _domain_user_agents[domain] = ua
                    return ua
        except Exception:
            pass
    return None


def _sanitize_domain(domain):
    """Sanitizza un dominio per usarlo come nome file."""
    return domain.strip('.').replace('.', '_').replace(':', '_')


def load_domain_cookies(domain, force=False):
    """Carica i cookie di un dominio nel jar globale di httptools."""
    from core import httptools

    if not force and domain in _cookies_loaded_domains:
        return True

    cookie_file = get_cookie_filename(domain)
    
    # Se il file non esiste, prova il dominio fallback
    if not os.path.isfile(cookie_file):
        effective = get_effective_domain(domain)
        if effective != domain:
            cookie_file = get_cookie_filename(effective)
            if os.path.isfile(cookie_file):
                logger.info("S4Me: cookie per %s non trovati, uso fallback %s" % (domain, effective))
            else:
                logger.info("S4Me: file cookie non trovato per %s ne %s" % (domain, effective))
                return False
        else:
            logger.info("S4Me: file cookie non trovato per %s" % domain)
            return False

    try:
        # Log contenuto file per debug
        with open(cookie_file, "r") as f:
            raw = f.read()
        logger.info("S4Me: === FILE COOKIE %s ===" % domain)
        logger.info("S4Me: path=%s" % cookie_file)
        logger.info("S4Me: contenuto=%s" % raw[:500])
        
        count = 0
        lines = raw.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                logger.info("S4Me: riga ignorata (parts=%d): %s" % (len(parts), line[:80]))
                continue
            
            c_domain = parts[0]
            c_path = parts[2]
            c_secure = parts[3].upper() == "TRUE"
            try:
                c_expires = int(parts[4])
                if c_expires < time.time():
                    c_expires = int(time.time()) + 86400
            except (ValueError, IndexError):
                c_expires = int(time.time()) + 86400
            c_name = parts[5]
            c_value = parts[6] if len(parts) > 6 else ""
            
            logger.info("S4Me: cookie: name=%s domain=%s value=%s..." % (c_name, c_domain, c_value[:30]))
            
            ck = cookielib.Cookie(
                version=0,
                name=str(c_name),
                value=str(c_value),
                port=None,
                port_specified=False,
                domain=c_domain,
                domain_specified=True,
                domain_initial_dot=c_domain.startswith("."),
                path=c_path,
                path_specified=True,
                secure=c_secure,
                expires=c_expires,
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False
            )
            httptools.cj.set_cookie(ck)
            count += 1

        if count > 0:
            httptools.save_cookies()
            
            # Aggiorna User-Agent GLOBALE
            user_agent = get_domain_user_agent(domain)
            if user_agent:
                httptools.default_headers["User-Agent"] = user_agent
                logger.info("S4Me: UA globale aggiornato: %s" % user_agent[:60])
            
            _cookies_loaded_domains.add(domain)
            logger.info("S4Me: %d cookie di %s caricati OK" % (count, domain))
            
            # Verifica: cerca cf_clearance nel jar
            jar_cookies = httptools.cj._cookies.get(c_domain, {}).get("/", {})
            if "cf_clearance" in jar_cookies:
                logger.info("S4Me: VERIFICA OK - cf_clearance trovato nel jar per %s" % c_domain)
            else:
                logger.info("S4Me: VERIFICA FAIL - cf_clearance NON trovato nel jar per %s" % c_domain)
                # Prova tutte le varianti
                for d in httptools.cj._cookies:
                    if domain.replace(".", "") in d.replace(".", ""):
                        logger.info("S4Me: jar contiene dominio simile: %s -> %s" % (d, list(httptools.cj._cookies[d].get("/", {}).keys())))
        else:
            logger.info("S4Me: NESSUN cookie valido trovato nel file per %s" % domain)
            
        return count > 0
    except Exception as e:
        import traceback
        logger.error("S4Me: errore caricamento cookie per %s: %s" % (domain, traceback.format_exc()))
        return False


# ============================================================================
# VERIFICA HEARTBEAT (solo modalita locale)
# ============================================================================

def is_app_alive():
    """Verifica se l'app S4Me Assistant e attiva controllando il file heartbeat.
    Utile solo in modalita locale per evitare tentativi inutili.
    
    Returns:
        True se l'app sembra attiva, False altrimenti
    """
    if not os.path.isfile(HEARTBEAT_FILE_PATH):
        logger.debug("S4Me: file heartbeat non trovato, app non avviata")
        return False

    try:
        with open(HEARTBEAT_FILE_PATH, "r") as f:
            ts_str = f.read().strip()
            ts = int(ts_str)

        age = time.time() - ts
        if age < HEARTBEAT_MAX_AGE:
            logger.debug("S4Me: heartbeat valido (eta: %.1f sec)" % age)
            return True
        else:
            logger.debug("S4Me: heartbeat vecchio (eta: %.1f sec), app probabilmente non attiva" % age)
            return False
    except Exception as e:
        logger.error("S4Me: errore lettura heartbeat: %s" % str(e))
        return False


# ============================================================================
# RILEVAMENTO PROTEZIONE (analisi risposta HTTP)
# ============================================================================

# Pattern noti nelle pagine di challenge Cloudflare
CF_CHALLENGE_PATTERNS = [
    "cf-browser-verification",
    "cf_chl_opt",
    "challenge-platform",
    "/cdn-cgi/challenge-platform/",
    "jschl_vc",
    "jschl_answer",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "Just a moment...",
    "Checking your browser",
    "Verifica del browser in corso",
    "Attendere prego",
]


def is_protection_detected(response):
    """Analizza la risposta HTTP per capire se e una pagina di challenge CF.
    
    Args:
        response: oggetto response (deve avere .content o .text o essere string-like)
    
    Returns:
        True se la pagina sembra una challenge Cloudflare
    """
    try:
        if hasattr(response, 'text'):
            data = response.text
        elif hasattr(response, 'content'):
            data = response.content
            if isinstance(data, bytes):
                data = data.decode('utf-8', errors='ignore')
        elif isinstance(response, str):
            data = response
        else:
            data = str(response)

        # Controlla solo le prime porzioni della pagina
        check_data = data[:5000].lower() if data else ""
        
        matches = 0
        for pattern in CF_CHALLENGE_PATTERNS:
            if pattern.lower() in check_data:
                matches += 1

        if matches >= 2:
            logger.debug("S4Me: protezione CF rilevata (%d pattern trovati)" % matches)
            return True

        return False
    except Exception as e:
        logger.error("S4Me: errore analisi protezione: %s" % str(e))
        return False


# ============================================================================
# RISOLUZIONE DOMINIO (comunicazione con l'app)
# ============================================================================

def resolve_domain(domain):
    """Contatta l'app S4Me Assistant per risolvere la challenge di un dominio.
    Funzione bloccante che invia POST /resolve e attende la risposta.
    
    Args:
        domain: il dominio da risolvere (es. "hd4me.net")
    
    Returns:
        True se la risoluzione ha avuto successo, False altrimenti
    """
    from lib import requests
    import json

    base_url = get_base_url()
    if not base_url:
        logger.error("S4Me: URL base non configurato")
        return False

    resolve_url = base_url + "/resolve"
    target_url = "https://%s" % domain

    payload = {
        "url": target_url,
        "timeout": DEFAULT_RESOLVE_TIMEOUT
    }

    for attempt in range(1, MAX_RESOLVE_RETRIES + 1):
        try:
            logger.info("S4Me: risoluzione %s (tentativo %d/%d)" 
                        % (domain, attempt, MAX_RESOLVE_RETRIES))

            resp = requests.post(
                resolve_url,
                json=payload,
                timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
            )

            if resp.status_code != 200:
                logger.error("S4Me: risposta HTTP %d dal server" % resp.status_code)
                continue

            data = resp.json()

            if data.get("success"):
                cookies_txt = data.get("cookies_txt", "")
                user_agent = data.get("user_agent", "")
                # L'app puo rispondere con un dominio diverso (fallback .to -> .cc)
                resolved_domain = data.get("domain", domain)
                
                if cookies_txt:
                    # Salva i cookie per il dominio effettivo (puo essere diverso)
                    _save_cookies_txt(resolved_domain, cookies_txt)
                    if user_agent:
                        _save_user_agent(resolved_domain, user_agent)
                    load_domain_cookies(resolved_domain, force=True)
                    
                    # Se il dominio e diverso (fallback), salva il mapping
                    # e carica i cookie anche per il dominio originale
                    if resolved_domain != domain:
                        logger.info("S4Me: fallback %s -> %s" % (domain, resolved_domain))
                        _set_fallback(domain, resolved_domain)
                        # Copia cookies e UA anche per il dominio originale
                        _save_cookies_txt(domain, cookies_txt)
                        if user_agent:
                            _save_user_agent(domain, user_agent)
                        load_domain_cookies(domain, force=True)
                    
                    logger.info("S4Me: dominio %s risolto con successo (UA: %s)" % (resolved_domain, user_agent[:50] if user_agent else "N/D"))
                    return True
                else:
                    logger.error("S4Me: risposta OK ma cookies_txt vuoto per %s" % domain)
            else:
                error = data.get("error", "errore sconosciuto")
                logger.error("S4Me: risoluzione fallita per %s: %s" % (domain, error))

        except requests.exceptions.ConnectTimeout:
            logger.error("S4Me: timeout connessione al server (tentativo %d)" % attempt)
            if attempt == MAX_RESOLVE_RETRIES:
                _notify_app_not_running()
        except requests.exceptions.ReadTimeout:
            logger.error("S4Me: timeout lettura risposta (tentativo %d)" % attempt)
        except requests.exceptions.ConnectionError:
            logger.error("S4Me: impossibile connettersi al server (tentativo %d)" % attempt)
            if attempt == MAX_RESOLVE_RETRIES:
                _notify_app_not_running()
        except Exception as e:
            logger.error("S4Me: errore imprevisto (tentativo %d): %s" % (attempt, str(e)))

        if attempt < MAX_RESOLVE_RETRIES:
            time.sleep(2)  # Pausa tra i tentativi

    logger.error("S4Me: tutti i tentativi esauriti per %s" % domain)
    return False


def is_remote():
    """Verifica se Kodi NON gira sullo stesso dispositivo Android dell'app.
    In modalita remota, i cookie CF non funzionano perche sono legati
    all'IP/fingerprint del telefono. Serve usare /fetch.
    """
    try:
        import xbmc
        return not xbmc.getCondVisibility('System.Platform.Android')
    except:
        return True  # Se non siamo in Kodi, siamo sicuramente remoti


def fetch_page(url, headers=None):
    """Scarica una pagina tramite l'app S4Me (modo proxy/remoto).
    L'app fa la richiesta HTTP con i propri cookie CF e fingerprint TLS.
    
    Args:
        url: URL completo da scaricare
        headers: dict opzionale di header extra
    
    Returns:
        dict con 'data', 'url', 'status_code' se successo, None se fallito
    """
    from lib import requests as lib_requests
    import json

    base_url = get_base_url()
    if not base_url:
        logger.error("S4Me: URL base non configurato per fetch")
        return None

    fetch_url = base_url + "/fetch"
    
    payload = {
        "url": url,
        "timeout": DEFAULT_RESOLVE_TIMEOUT
    }
    if headers:
        payload["headers"] = headers

    try:
        logger.info("S4Me: fetch remoto di %s" % url)
        resp = lib_requests.post(
            fetch_url,
            json=payload,
            timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
        )

        if resp.status_code != 200:
            logger.error("S4Me: fetch HTTP %d" % resp.status_code)
            return None

        data = resp.json()

        if data.get("success"):
            html = data.get("data", "")
            status_code = data.get("status_code", 200)
            final_url = data.get("url", url)
            logger.info("S4Me: fetch OK, status=%d, html=%d chars" % (status_code, len(html)))
            return {
                "data": html,
                "url": final_url,
                "status_code": status_code
            }
        else:
            error = data.get("error", "errore sconosciuto")
            logger.error("S4Me: fetch fallito: %s" % error)
            return None

    except Exception as e:
        logger.error("S4Me: errore fetch: %s" % str(e))
        return None


# ============================================================================
# ENSURE DOMAIN READY (funzione principale per la pre-risoluzione)
# ============================================================================

def ensure_domain_ready(domain):
    """Assicura che un dominio abbia cookie validi prima di procedere."""
    if not is_enabled():
        return True

    # Controlla anche il dominio fallback
    effective = get_effective_domain(domain)
    
    lock = _get_domain_lock(domain)
    lock.acquire()
    try:
        # Primo check: cookie gia validi per il dominio o il suo fallback?
        if cookies_valid(domain):
            logger.debug("S4Me: cookie gia validi per %s" % domain)
            return True
        if effective != domain and cookies_valid(effective):
            logger.debug("S4Me: cookie validi per fallback %s (originale: %s)" % (effective, domain))
            # Carica i cookie del fallback
            load_domain_cookies(effective, force=True)
            return True

        # Verifica se il server e attivo
        if not _ensure_server_running():
            logger.error("S4Me: server non raggiungibile, impossibile risolvere %s" % domain)
            return False

        # Tenta la risoluzione
        result = resolve_domain(domain)
        return result

    finally:
        lock.release()


# Lock e stato per avvio app: solo un thread alla volta tenta di avviare
_server_check_lock = threading.Lock()
_server_confirmed_alive = False
_server_confirmed_time = 0


def _ensure_server_running():
    """Verifica se il server S4Me e attivo. Se non lo e, tenta di avviarlo.
    Thread-safe: solo il primo thread tenta l'avvio, gli altri aspettano il risultato.
    
    Returns:
        True se il server e raggiungibile, False altrimenti
    """
    global _server_confirmed_alive, _server_confirmed_time
    
    # Se confermato attivo negli ultimi 30 secondi, non ricontrollare
    if _server_confirmed_alive and (time.time() - _server_confirmed_time) < 30:
        return True
    
    # Quick check senza lock
    success, _ = _raw_test_connection()
    if success:
        _server_confirmed_alive = True
        _server_confirmed_time = time.time()
        global _app_not_running_notified
        _app_not_running_notified = False
        return True
    
    # Lock: solo un thread tenta l'avvio
    with _server_check_lock:
        # Ricontrolla: un altro thread potrebbe aver avviato nel frattempo
        if _server_confirmed_alive and (time.time() - _server_confirmed_time) < 30:
            return True
        
        success, _ = _raw_test_connection()
        if success:
            _server_confirmed_alive = True
            _server_confirmed_time = time.time()
            return True
        
        logger.info("S4Me: server non attivo su %s" % get_base_url())
        
        # Avvio automatico solo se l'app e sullo stesso dispositivo (IP locale)
        # Se l'IP e remoto (es. telefono -> Fire Stick), non avviare app localmente
        if _is_android() and is_local():
            try:
                import xbmc
                logger.info("S4Me: lancio app S4Me Assistant (locale)...")
                xbmc.executebuiltin('StartAndroidActivity("com.s4me.assistant","","","com.s4me.assistant.MainActivity")')
                
                for wait in range(10):
                    time.sleep(2)
                    success, msg = _raw_test_connection()
                    if success:
                        logger.info("S4Me: server avviato dopo %d secondi" % ((wait + 1) * 2))
                        _server_confirmed_alive = True
                        _server_confirmed_time = time.time()
                        return True
                    logger.debug("S4Me: attendo avvio server... (%d/10)" % (wait + 1))
                
                logger.error("S4Me: timeout avvio app")
                return False
                
            except Exception as e:
                logger.error("S4Me: errore avvio app: %s" % str(e))
                return False
        else:
            logger.error("S4Me: server remoto non raggiungibile (%s). Aprire l'app manualmente." % get_base_url())
            _notify_app_not_running()
            return False


# Flag per evitare notifiche ripetute nella stessa sessione
_app_not_running_notified = False


def _notify_app_not_running():
    """Mostra una notifica visibile in Kodi quando l'app S4Me non e raggiungibile."""
    global _app_not_running_notified
    if _app_not_running_notified:
        return
    _app_not_running_notified = True
    try:
        import xbmcgui
        base_url = get_base_url()
        xbmcgui.Dialog().notification(
            "S4Me Assistant",
            "App non raggiungibile! Avviala sul telefono (%s)" % (base_url or "IP non configurato"),
            xbmcgui.NOTIFICATION_WARNING,
            8000  # 8 secondi
        )
    except Exception:
        pass


def _is_android():
    """Verifica se Kodi e in esecuzione su Android."""
    try:
        import xbmc
        return xbmc.getCondVisibility("system.platform.android")
    except Exception:
        return False


# ============================================================================
# PRE-RISOLUZIONE DOMINI (per ricerca globale)
# ============================================================================

def _extract_domain_from_url(url):
    """Estrae il dominio da un URL."""
    try:
        parsed = urlparse.urlparse(url)
        domain = parsed.netloc
        # Rimuove eventuale porta
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain
    except:
        return ""


def get_channel_domains(channels_list):
    """Estrae i domini unici dai canali coinvolti nella ricerca.
    
    Args:
        channels_list: lista di nomi canali (es. ['hd4me', 'cineblog01'])
    
    Returns:
        set di domini unici
    """
    domains = set()
    for channel_name in channels_list:
        try:
            url = config.get_channel_url(name=channel_name)
            if url:
                domain = _extract_domain_from_url(url)
                if domain:
                    domains.add(domain)
        except Exception:
            # Canale potrebbe usare findhost o non avere URL diretto
            try:
                module = __import__('channels.%s' % channel_name, 
                                     fromlist=["channels.%s" % channel_name])
                host = getattr(module, 'host', '')
                if host:
                    domain = _extract_domain_from_url(host)
                    if domain:
                        domains.add(domain)
            except Exception:
                pass
    return domains


def pre_resolve_domains(channels_list, timeout=120):
    """Pre-risolve i domini CF prima della ricerca globale.
    
    Risolve solo i domini che:
    - Hanno un file cookie CF scaduto (quindi sappiamo che avevano CF)
    - Hanno "cloudflare": true nel JSON del canale
    
    Per tutti gli altri domini, il fallback handle_protection_retry in httptools
    rileva la challenge nella risposta e manda la richiesta all'app al volo.
    
    Args:
        channels_list: lista di nomi canali
        timeout: timeout globale in secondi
    
    Returns:
        dict con {dominio: True/False} per ogni dominio processato
    """
    if not is_enabled():
        return {}

    domains_to_resolve = set()

    for channel_name in channels_list:
        domain = _get_domain_for_channel(channel_name)
        if not domain:
            continue

        # 1. Se ha cookie validi, non serve risolvere
        if cookies_valid(domain):
            continue

        # 2. Se ha cookie scaduti, sappiamo che aveva CF -> pre-risolvi
        if _has_expired_cf_cookie(domain):
            domains_to_resolve.add(domain)

    if not domains_to_resolve:
        logger.debug("S4Me: nessun dominio da pre-risolvere tra i %d canali" % len(channels_list))
        return {}

    logger.info("S4Me: pre-risoluzione di %d domini: %s" 
                % (len(domains_to_resolve), ", ".join(domains_to_resolve)))

    results = {}
    start_time = time.time()

    for domain in domains_to_resolve:
        if time.time() - start_time > timeout:
            logger.error("S4Me: timeout globale pre-risoluzione raggiunto")
            for d in domains_to_resolve:
                if d not in results:
                    results[d] = False
            break

        result = ensure_domain_ready(domain)
        results[domain] = result

        if not result:
            logger.error("S4Me: pre-risoluzione fallita per %s" % domain)

    resolved = sum(1 for v in results.values() if v)
    logger.info("S4Me: pre-risoluzione completata: %d/%d domini pronti" 
                % (resolved, len(results)))
    return results


def _get_domain_for_channel(channel_name):
    """Estrae il dominio di un canale leggendo channels.json o il modulo .py."""
    # 1. Prova channels.json -> direct
    try:
        url = config.get_channel_url(name=channel_name)
        if url:
            return _extract_domain_from_url(url)
    except Exception:
        pass
    
    # 2. Prova importando il modulo e leggendo host
    try:
        module = __import__('channels.%s' % channel_name, 
                             fromlist=["channels.%s" % channel_name])
        host = getattr(module, 'host', '')
        if host:
            return _extract_domain_from_url(host)
    except Exception:
        pass
    
    return None


def _has_expired_cf_cookie(domain):
    """Controlla se esiste un file cookie CF scaduto per questo dominio.
    Se esiste un file ma i cookie sono scaduti, sappiamo che il dominio aveva CF.
    """
    cookie_file = get_cookie_filename(domain)
    if not os.path.isfile(cookie_file):
        return False
    try:
        with open(cookie_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7 and parts[5] == "cf_clearance":
                    return True  # Ha/aveva cf_clearance
    except Exception:
        pass
    return False




# ============================================================================
# RETRY DOPO 403 (fallback per downloadpage)
# ============================================================================

def handle_protection_retry(url, response_code, response_obj, opt):
    """Gestisce il retry automatico dopo un 403/429/503 con protezione CF.
    Da chiamare dentro httptools.downloadpage() dopo aver ottenuto la risposta.
    
    Args:
        url: URL della richiesta originale
        response_code: codice HTTP della risposta
        response_obj: oggetto response (per analisi HTML)
        opt: dizionario opzioni di downloadpage
    
    Returns:
        True se bisogna fare retry, False altrimenti
    """
    if not is_enabled():
        return False

    # Non fare retry se gia tentato
    if opt.get('_s4me_retry'):
        return False

    # Solo su codici di protezione
    if response_code not in [403, 429, 503]:
        return False

    # Analizza la risposta per confermare che e una challenge CF
    if not is_protection_detected(response_obj):
        return False

    # Estrai il dominio
    try:
        parsed = urlparse.urlparse(url)
        domain = parsed.netloc
        if ":" in domain:
            domain = domain.split(":")[0]
    except:
        return False

    # Se i cookie esistono ma CF risponde ancora 403, sono invalidi lato CF
    # Invalida e forza nuova risoluzione
    if cookies_valid(domain):
        logger.info("S4Me: cookie presenti per %s ma CF risponde %d - cookie invalidati, forzo nuova risoluzione" % (domain, response_code))
        _invalidate_domain_cookies(domain)

    # Tenta la risoluzione
    logger.info("S4Me: protezione rilevata per %s, tentativo risoluzione al volo" % domain)
    success = ensure_domain_ready(domain)

    if success:
        # Segna il retry per evitare loop
        opt['_s4me_retry'] = True
        return True

    return False


# ============================================================================
# TEST CONNESSIONE
# ============================================================================

def _raw_test_connection():
    """Test connessione puro - senza avvio automatico del server.
    Usa una session nuova per evitare problemi di pool/keep-alive.
    """
    from lib import requests

    base_url = get_base_url()
    if not base_url:
        return False, "URL non configurato"

    status_url = base_url + "/status"

    try:
        # Session nuova per evitare problemi di connection pooling
        session = requests.Session()
        session.headers.update({"Connection": "close"})
        resp = session.get(
            status_url,
            timeout=(HTTP_CONNECT_TIMEOUT, 10)
        )
        session.close()
        if resp.status_code == 200:
            data = resp.json()
            return True, "Connesso! Attivo da %s" % data.get("uptime", "N/D")
        else:
            return False, "HTTP %d" % resp.status_code
    except Exception as e:
        return False, str(e)


def test_connection():
    """Testa la connessione al server S4Me Assistant.
    NON avvia l'app automaticamente - testa solo se il server risponde.
    
    Returns:
        tuple (success: bool, message: str)
    """
    logger.info("S4Me: test connessione a %s" % get_base_url())
    return _raw_test_connection()


# ============================================================================
# PULIZIA COOKIE SCADUTI
# ============================================================================

def cleanup_expired_cookies():
    """Rimuove i file cookie scaduti dalla cartella dell'addon."""
    cookies_dir = os.path.join(config.get_data_path(), "cookies")
    if not os.path.isdir(cookies_dir):
        return

    now = int(time.time())
    cleaned = 0

    for filename in os.listdir(cookies_dir):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(cookies_dir, filename)
        try:
            all_expired = True
            has_cookies = False
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        has_cookies = True
                        try:
                            exp = int(parts[4])
                            if exp > now:
                                all_expired = False
                                break
                        except ValueError:
                            pass

            if has_cookies and all_expired:
                os.remove(filepath)
                cleaned += 1
                logger.debug("S4Me: rimosso cookie scaduto: %s" % filename)
        except Exception:
            pass

    if cleaned:
        logger.info("S4Me: rimossi %d file cookie scaduti" % cleaned)


def clear_all_cookies():
    """Elimina TUTTI i cookie e gli User-Agent salvati da S4Me Assistant.
    Da usare quando i cookie salvati sono invalidi e causano problemi.
    
    Returns:
        tuple (removed_count, message)
    """
    global _domain_user_agents
    removed = 0
    
    # 1. Cookie nella cartella privata dell'addon
    cookies_dir = os.path.join(config.get_data_path(), "cookies")
    if os.path.isdir(cookies_dir):
        for filename in os.listdir(cookies_dir):
            try:
                filepath = os.path.join(cookies_dir, filename)
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    removed += 1
            except Exception:
                pass

    # 2. Cookie e UA nella cartella condivisa
    if os.path.isdir(SHARED_COOKIES_PATH):
        for filename in os.listdir(SHARED_COOKIES_PATH):
            try:
                filepath = os.path.join(SHARED_COOKIES_PATH, filename)
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    removed += 1
            except Exception:
                pass

    # 3. Cache UA in memoria
    _domain_user_agents.clear()
    
    # 3b. Reset tracking domini caricati
    _cookies_loaded_domains.clear()

    # 4. Rimuovi anche i cookie CF dal jar globale di httptools
    try:
        from core import httptools
        to_remove = []
        for cookie in httptools.cj:
            if cookie.name == "cf_clearance":
                to_remove.append(cookie)
        for cookie in to_remove:
            httptools.cj.clear(cookie.domain, cookie.path, cookie.name)
        if to_remove:
            httptools.save_cookies()
            removed += len(to_remove)
    except Exception:
        pass

    msg = "Eliminati %d cookie/file S4Me" % removed if removed else "Nessun cookie S4Me trovato"
    logger.info("S4Me: %s" % msg)
    return removed, msg


# ============================================================================
# DNS BLOCK DETECTION
# ============================================================================

def _is_dns_blocked(domain):
    """Verifica se un dominio e bloccato dal DNS del provider.
    Confronta risoluzione DNS di sistema con DNS-over-HTTPS.
    
    Returns:
        True se bloccato (sistema fallisce ma DoH funziona)
    """
    import socket
    
    # Step 1: prova DNS di sistema
    system_ip = None
    try:
        result = socket.getaddrinfo(domain, 443, socket.AF_INET)
        if result:
            system_ip = result[0][4][0]
    except Exception:
        pass
    
    # Se il DNS di sistema funziona, non e bloccato
    if system_ip:
        # Verifica che non sia un IP di blocco noto
        blocked_ips = {"0.0.0.0", "127.0.0.1"}
        if system_ip not in blocked_ips:
            return False
    
    # Step 2: prova DoH (Cloudflare)
    doh_ip = _resolve_doh(domain)
    
    if doh_ip and not system_ip:
        # DoH funziona ma sistema no -> bloccato dal provider
        logger.warning("S4Me DNS: %s bloccato dal provider (sistema FAIL, DoH -> %s)" % (domain, doh_ip))
        return True
    
    if doh_ip and system_ip and system_ip != doh_ip:
        # IP diversi: il provider redirige a pagina di blocco
        logger.warning("S4Me DNS: %s possibile blocco (sistema -> %s, DoH -> %s)" % (domain, system_ip, doh_ip))
        return True
    
    return False


def _resolve_doh(domain):
    """Risolve un dominio via DNS-over-HTTPS (Cloudflare/Google).
    Returns: IP string o None
    """
    try:
        from lib import requests as req
    except ImportError:
        import requests as req
    
    providers = [
        "https://1.0.0.1/dns-query?name=%s&type=A" % domain,
        "https://8.8.4.4/resolve?name=%s&type=A" % domain,
    ]
    
    import re
    ip_pattern = re.compile(r'"data"\s*:\s*"(\d+\.\d+\.\d+\.\d+)"')
    
    for url in providers:
        try:
            resp = req.get(url, headers={"Accept": "application/dns-json"}, timeout=5)
            if resp.status_code == 200:
                match = ip_pattern.search(resp.text)
                if match:
                    return match.group(1)
        except Exception:
            pass
    return None


def _notify_dns_blocked(domain):
    """Mostra una notifica in Kodi quando un dominio e bloccato dal DNS del provider."""
    try:
        import xbmcgui
        dialog = xbmcgui.Dialog()
        dialog.notification(
            "S4Me - DNS bloccato",
            "Necessario il cambio dei DNS per %s" % domain,
            xbmcgui.NOTIFICATION_WARNING,
            8000
        )
    except Exception:
        pass
    logger.warning("S4Me: dominio %s bloccato dal DNS del provider. Necessario cambio DNS." % domain)
