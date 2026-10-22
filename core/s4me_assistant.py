# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# S4Me Assistant - Modulo Python per addon Kodi
# Gestisce il bypass Cloudflare tramite app Android S4Me Assistant
# Supporta modalita LOCALE (stesso dispositivo) e REMOTA (dispositivi diversi)
# ----------------------------------------------------------------------------

import os
import re
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
NO_CHALLENGE_MARKER = "# S4Me: nessuna challenge"
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


def _parse_address():
    """Legge l'impostazione 'IP:porta'. La porta e facoltativa (predefinita 8787)."""
    value = str(config.get_setting("s4me_remote_ip", default="127.0.0.1:%d" % DEFAULT_PORT) or "").strip()
    for prefix in ("http://", "https://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/")[0]
    host, port = value, DEFAULT_PORT
    if ":" in value:
        host, _, p = value.rpartition(":")
        try:
            port = int(p)
        except ValueError:
            host, port = value, DEFAULT_PORT
    return host.strip(), port


def get_remote_ip():
    """Restituisce l'IP del server S4Me Assistant."""
    return _parse_address()[0]


def get_remote_port():
    """Restituisce la porta del server."""
    return _parse_address()[1]


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

# Durata massima di sicurezza dei cookie CF in secondi (24 ore).
# I cookie si riusano finche Cloudflare non risponde con una challenge: in quel caso
# handle_protection_retry li invalida e li rifa. Se il cookie riporta una scadenza, vale quella.
CF_COOKIE_MAX_AGE = 86400


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
                    if line == NO_CHALLENGE_MARKER:
                        # FlareSolverr ha caricato la pagina senza challenge: non c'e cf_clearance da attendere
                        return True
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7 and parts[5] == "cf_clearance":
                        try:
                            expires = int(parts[4])
                        except ValueError:
                            expires = 0
                        if expires and expires < time.time():
                            logger.info("S4Me: cf_clearance di %s scaduto" % check_domain)
                            _invalidate_domain_cookies(check_domain)
                            break
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


def has_resolved_cookies(domain):
    """True se per il dominio (o il suo fallback) esiste un file cookie salvato da app o FlareSolverr."""
    try:
        for d in {domain, get_effective_domain(domain)}:
            if os.path.isfile(get_cookie_filename(d)):
                return True
    except Exception:
        pass
    return False


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
        # nel log non si scrivono i valori dei cookie (sono legati all'IP e non vanno condivisi)
        masked = []
        for _l in raw.split("\n"):
            _p = _l.split("\t")
            if len(_p) >= 7 and not _l.startswith("#"):
                _p[6] = "<%d caratteri>" % len(_p[6])
                _l = "\t".join(_p)
            masked.append(_l)
        logger.info("S4Me: contenuto=%s" % "\n".join(masked)[:500])
        
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
            
            logger.info("S4Me: cookie: name=%s domain=%s valore=%d caratteri" % (c_name, c_domain, len(c_value)))
            
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
    "Ci siamo quasi",
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

# ============================================================================
# RISOLUZIONE CHALLENGE: S4Me Assistant (app sul telefono), FlareSolverr o entrambi
# ============================================================================

CF_NAME = "cf_clearance"

# Una sola challenge alla volta sull'app (la WebView e una sola)
_app_lock = threading.Lock()
_flare_lock = threading.Lock()
_flare_manager = None
_flare_manager_url = None
_flare_notified = False
_flare_request_lock = threading.Lock()
_flare_challenge_notified = False


def get_cf_method():
    """Metodo scelto nelle impostazioni: 'app', 'flaresolverr' oppure 'auto'."""
    value = config.get_setting("s4me_cf_method", default="S4Me Assistant")
    if value in ("FlareSolverr", 1, "1"):
        return "flaresolverr"
    if value in ("Automatico", 2, "2"):
        return "auto"
    return "app"


def get_flaresolverr_url():
    """Indirizzo del server FlareSolverr, sempre terminato con /v1."""
    url = config.get_setting("s4me_flaresolverr_url", default="http://127.0.0.1:8191/v1")
    url = str(url or "").strip() or "http://127.0.0.1:8191/v1"
    if not url.endswith("/v1"):
        url = url.rstrip("/") + "/v1"
    return url


def _b64q(text):
    """Base64 con caratteri sicuri per la query string."""
    import base64
    try:
        from urllib.parse import quote
    except ImportError:
        from urllib import quote
    return quote(base64.b64encode(text.encode("utf-8")).decode("ascii"), safe="")


def _http_get(url, timeout):
    try:
        from urllib.request import urlopen, Request
    except ImportError:
        from urllib2 import urlopen, Request
    data = urlopen(Request(url, headers={"Connection": "close"}), timeout=timeout).read()
    return data.decode("utf-8", "replace")


def _bare(domain):
    return domain[4:] if domain.startswith("www.") else domain


def _final_domain(requested, final_url):
    """Dominio effettivo dopo i redirect (es. 1337x.to -> altro dominio), altrimenti quello richiesto."""
    try:
        host = urlparse.urlparse(final_url).netloc.split(":")[0]
    except Exception:
        return requested
    if not host or _bare(host) == _bare(requested):
        return requested
    return host


def _cookies_to_netscape(domain, cookies):
    """
    Converte una lista di cookie (dict con name, value e, se noti, domain, path, secure, expires)
    nel formato Netscape che il resto del modulo sa gia leggere.
    """
    now = int(time.time())
    lines = [NETSCAPE_HEADER.rstrip("\n")]
    for c in cookies:
        name = c.get("name")
        if not name:
            continue
        c_domain = c.get("domain") or ("." + _bare(domain))
        flag = "TRUE" if c_domain.startswith(".") else "FALSE"
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure", True) else "FALSE"
        try:
            expires = int(float(c.get("expires", 0)))
        except (TypeError, ValueError):
            expires = 0
        if expires <= now:
            expires = now + 86400
        lines.append("\t".join([c_domain, flag, path, secure, str(expires), str(name), str(c.get("value", ""))]))
    return "\n".join(lines) + "\n"


# Istante (secondi) in cui sono stati salvati gli ultimi cookie di ogni dominio
_resolved_at = {}


def _cookies_saved_at(domain):
    """Quando sono stati salvati i cookie del dominio (o del suo fallback). 0 se non ci sono."""
    best = 0
    for d in {domain, get_effective_domain(domain)}:
        if d in _resolved_at:
            best = max(best, _resolved_at[d])
            continue
        try:
            best = max(best, os.path.getmtime(get_cookie_filename(d)))
        except Exception:
            pass
    return best


def _apply_resolution(domain, resolved_domain, cookies_txt, user_agent):
    """Salva cookie e user agent e li carica nel jar, anche per il dominio originale se e cambiato."""
    now = time.time()
    _resolved_at[resolved_domain] = now
    _resolved_at[domain] = now
    _save_cookies_txt(resolved_domain, cookies_txt)
    if user_agent:
        _save_user_agent(resolved_domain, user_agent)
    load_domain_cookies(resolved_domain, force=True)
    if resolved_domain != domain:
        _set_fallback(domain, resolved_domain)
        _save_cookies_txt(domain, cookies_txt)
        if user_agent:
            _save_user_agent(domain, user_agent)
        load_domain_cookies(domain, force=True)
    return True


# ---------------------------------------------------------------- provider 1: app

def _resolve_with_app(domain):
    """Apre la pagina nella WebView dell'app (telefono o stesso dispositivo) e raccoglie i cookie."""
    import json
    with _app_lock:
        if not _ensure_server_running():
            logger.error("S4Me: app non raggiungibile, impossibile risolvere %s" % domain)
            return False
        target = "https://%s" % domain
        query = "url=%s&time=%d&returnWhenCookieNameFound=%s" % (
            _b64q(target), DEFAULT_RESOLVE_TIMEOUT, _b64q(target + "|" + CF_NAME))
        url = get_base_url() + "/getSourceByPageFinished?" + query
        for attempt in range(1, MAX_RESOLVE_RETRIES + 1):
            try:
                logger.info("S4Me: app, risoluzione %s (tentativo %d/%d)" % (domain, attempt, MAX_RESOLVE_RETRIES))
                data = json.loads(_http_get(url, HTTP_READ_TIMEOUT))
            except Exception as e:
                logger.error("S4Me: app, errore per %s: %s" % (domain, e))
                if attempt == MAX_RESOLVE_RETRIES:
                    _notify_app_not_running()
                else:
                    time.sleep(2)
                continue
            if data.get("error"):
                logger.error("S4Me: app, errore: %s" % data["error"])
                return False
            cookies = [c for c in data.get("cookies", []) if c.get("name")]
            if not any(c["name"] == CF_NAME for c in cookies):
                logger.error("S4Me: app, challenge non risolta per %s (titolo: %s)" % (domain, data.get("title", "")))
                return False
            resolved = _final_domain(domain, data.get("url", ""))
            logger.info("S4Me: app, %s risolto" % resolved)
            return _apply_resolution(domain, resolved, _cookies_to_netscape(resolved, cookies),
                                     data.get("userAgent", ""))
        return False


# ---------------------------------------------------------------- provider 2: FlareSolverr

def _get_flaresolverr(reset=False):
    """Manager FlareSolverr condiviso: la sessione viene creata una volta e riusata."""
    global _flare_manager, _flare_manager_url
    url = get_flaresolverr_url()
    with _flare_lock:
        if reset or _flare_manager is None or _flare_manager_url != url:
            from core.flaresolverr import FlareSolverrManager
            # Ogni sessione di FlareSolverr e un'istanza di Chromium: si eliminano quelle rimaste
            # aperte da risoluzioni precedenti (anche di altri processi Kodi) prima di crearne una nuova
            try:
                FlareSolverrManager(flaresolverr_url=url, session_id="cleanup").clear_flaresolverr_sessions()
            except Exception:
                pass
            manager = FlareSolverrManager(flaresolverr_url=url)
            if not manager.flaresolverr_session:
                _flare_manager = None
                return None
            _flare_manager = manager
            _flare_manager_url = url
        return _flare_manager


def _notify_flaresolverr_unreachable():
    global _flare_notified
    if _flare_notified:
        return
    _flare_notified = True
    try:
        import xbmcgui
        xbmcgui.Dialog().notification(
            "FlareSolverr",
            "Server non raggiungibile (%s)" % get_flaresolverr_url(),
            xbmcgui.NOTIFICATION_WARNING, 8000)
    except Exception:
        pass


def _notify_flaresolverr_challenge():
    """Avvisa (una volta) che FlareSolverr non supera la challenge e suggerisce la lingua del browser."""
    global _flare_challenge_notified
    if _flare_challenge_notified:
        return
    _flare_challenge_notified = True
    try:
        import xbmcgui
        xbmcgui.Dialog().notification(
            "FlareSolverr",
            "Challenge non superata. Avvia FlareSolverr con LANG=en-US, disattiva VPN o DNS alternativi, oppure usa l'app S4Me Assistant",
            xbmcgui.NOTIFICATION_WARNING, 10000)
    except Exception:
        pass


def _flare_cookies_for(domain):
    """Cookie gia salvati per il dominio, nel formato richiesto da FlareSolverr (nome, valore, dominio, percorso)."""
    out = []
    try:
        cookie_file = get_cookie_filename(domain)
        if not os.path.isfile(cookie_file):
            return out
        with open(cookie_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    out.append({"name": parts[5], "value": parts[6],
                                "domain": parts[0].lstrip("."), "path": parts[2] or "/"})
    except Exception:
        return []
    return out


# attese (secondi) tra una richiesta e la successiva mentre FlareSolverr finisce la challenge
FLARE_POLL_WAITS = (1, 1, 1.5, 1.5, 2, 2, 2, 2, 2, 2)


def _close_flaresolverr_session():
    """Chiude la sessione (e quindi Chromium) dopo la risoluzione, per non occupare RAM."""
    global _flare_manager
    with _flare_lock:
        manager = _flare_manager
        _flare_manager = None
    if manager is not None:
        try:
            manager.clear_flaresolverr_sessions()
        except Exception:
            pass


def _resolve_with_flaresolverr(domain):
    try:
        return _resolve_with_flaresolverr_inner(domain)
    finally:
        _close_flaresolverr_session()


def _resolve_with_flaresolverr_inner(domain):
    """Chiede a FlareSolverr di superare la challenge e raccoglie cookie e user agent."""
    global _flare_notified
    target = "https://%s" % domain
    t_start = time.time()
    logger.info("S4Me: FlareSolverr, avvio risoluzione di %s" % domain)
    for attempt in (1, 2):
        # una sola richiesta alla volta: la sessione FlareSolverr e condivisa tra i thread
        with _flare_request_lock:
            manager = _get_flaresolverr(reset=(attempt == 2))
            if not manager:
                continue
            try:
                logger.info("S4Me: FlareSolverr, risoluzione %s (tentativo %d/2, %.1f s dall'avvio)"
                            % (domain, attempt, time.time() - t_start))
                t_req = time.time()
                saved = _flare_cookies_for(domain) if attempt == 1 else []
                try:
                    resp = manager.request(target, tries=1, cookies=saved or None)
                except Exception:
                    if not saved:
                        raise
                    # cookie rifiutati (es. dominio non valido): si riprova senza
                    logger.info("S4Me: FlareSolverr, cookie salvati rifiutati, riprovo senza")
                    resp = manager.request(target, tries=1)
                data = resp.json() if resp else {}
                # Con Windows in italiano Cloudflare titola la challenge "Ci siamo quasi..." e FlareSolverr,
                # che cerca il titolo inglese, la scambia per una pagina normale e risponde subito.
                # Si ripete la richiesta nella stessa sessione dando tempo al browser di finire.
                for poll, wait in enumerate(FLARE_POLL_WAITS, 1):
                    sol = data.get("solution") or {}
                    if data.get("status") != "ok" or sol.get("status") != 200:
                        break
                    if any(c.get("name") == CF_NAME for c in (sol.get("cookies") or [])):
                        break
                    if not is_protection_detected(sol.get("response") or ""):
                        break
                    logger.info("S4Me: FlareSolverr, %s ancora in challenge, attendo %.1f s e ripeto (%d/%d)"
                                % (domain, wait, poll, len(FLARE_POLL_WAITS)))
                    time.sleep(wait)
                    resp = manager.request(target, tries=1)
                    data = resp.json() if resp else {}
            except Exception as e:
                logger.error("S4Me: FlareSolverr, errore per %s: %s" % (domain, e))
                if time.time() - t_req > 50:
                    # FlareSolverr ha provato per tutto il tempo massimo senza superare la challenge:
                    # una nuova sessione non cambia nulla, si evita di aspettare un altro minuto
                    logger.error("S4Me: FlareSolverr, challenge di %s non risolta entro il tempo massimo" % domain)
                    _notify_flaresolverr_challenge()
                    return False
                continue
        solution = data.get("solution") or {}
        status = solution.get("status")
        if data.get("status") != "ok" or status != 200:
            logger.error("S4Me: FlareSolverr, risposta non valida per %s: stato=%s http=%s messaggio=%s"
                         % (domain, data.get("status"), status, data.get("message", "")))
            if time.time() - t_req > 50:
                # FlareSolverr ha usato tutto il tempo massimo senza risolvere: un'altra sessione non serve
                _notify_flaresolverr_challenge()
                return False
            continue
        page = solution.get("response") or ""
        cookies = [c for c in (solution.get("cookies") or []) if c.get("name")]
        has_clearance = any(c["name"] == CF_NAME for c in cookies)
        if not has_clearance and is_protection_detected(page):
            # Nessun cf_clearance e la pagina sembra una challenge o un blocco: FlareSolverr non l'ha riconosciuta
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            logger.error("S4Me: FlareSolverr, %s senza %s e con pagina di challenge o blocco. Titolo: %s | Inizio pagina: %s"
                         % (domain, CF_NAME, (m.group(1).strip() if m else "-"),
                            re.sub(r"\s+", " ", page[:300])))
            # Dopo tutte le attese la challenge non si e risolta: un'altra sessione non cambia nulla,
            # si smette subito invece di ripetere tutto
            _notify_flaresolverr_challenge()
            return False
        if not solution.get("userAgent"):
            logger.error("S4Me: FlareSolverr, nessun userAgent per %s" % domain)
        _flare_notified = False
        resolved = _final_domain(domain, solution.get("url", ""))
        cookies_txt = _cookies_to_netscape(resolved, cookies)
        if not any(c["name"] == CF_NAME for c in cookies):
            # Challenge non scattata per il browser di FlareSolverr: la pagina e valida, si salvano
            # comunque cookie e user agent e si segna il dominio come risolto
            logger.info("S4Me: FlareSolverr, %s senza challenge (cookie ricevuti: %s), salvo user agent e cookie"
                        % (domain, ",".join(c["name"] for c in cookies)))
            cookies_txt = cookies_txt.replace(NETSCAPE_HEADER.rstrip("\n"),
                                              NETSCAPE_HEADER.rstrip("\n") + "\n" + NO_CHALLENGE_MARKER, 1)
        else:
            logger.info("S4Me: FlareSolverr, %s risolto in %.1f s" % (resolved, time.time() - t_start))
        return _apply_resolution(domain, resolved, cookies_txt, solution.get("userAgent", ""))
    _notify_flaresolverr_unreachable()
    return False


# ---------------------------------------------------------------- dispatcher

def resolve_domain(domain):
    """
    Risolve la challenge di un dominio con il metodo scelto nelle impostazioni.
    Con 'Automatico' prova prima l'app (se raggiungibile) e poi FlareSolverr.
    Ritorna True se cookie e user agent sono stati salvati e caricati.
    """
    method = get_cf_method()
    if method == "flaresolverr":
        order = [_resolve_with_flaresolverr]
    elif method == "auto":
        if is_local() and not _is_android():
            # App su questo stesso dispositivo ma non siamo su Android: l'app non puo esserci,
            # si evita il ping che su Windows impiega circa 2 secondi a fallire
            alive = False
        else:
            alive, _ = _raw_test_connection()
        if alive or (_is_android() and is_local()):
            order = [_resolve_with_app, _resolve_with_flaresolverr]
        else:
            order = [_resolve_with_flaresolverr]
    else:
        order = [_resolve_with_app]
    for provider in order:
        try:
            if provider(domain):
                return True
        except Exception:
            import traceback
            logger.error(traceback.format_exc())
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

def ensure_domain_ready(domain, stale_before=0):
    """
    Assicura che un dominio abbia cookie validi prima di procedere.
    stale_before: istante in cui e partita la richiesta che e stata bloccata. I cookie salvati
    prima di quell'istante non funzionano piu e vengono rifatti; quelli salvati dopo li ha
    appena creati un altro thread e si riusano senza rilanciare la challenge.
    """
    if not is_enabled():
        return True

    # Controlla anche il dominio fallback
    effective = get_effective_domain(domain)
    
    lock = _get_domain_lock(domain)
    lock.acquire()
    try:
        # Cookie piu vecchi della richiesta bloccata: non funzionano piu, si rifa la challenge
        if stale_before and (cookies_valid(domain) or (effective != domain and cookies_valid(effective))):
            if _cookies_saved_at(domain) < stale_before:
                logger.info("S4Me: cookie di %s piu vecchi della richiesta bloccata, forzo nuova risoluzione" % domain)
                _invalidate_domain_cookies(domain)
                if effective != domain:
                    _invalidate_domain_cookies(effective)
            else:
                logger.info("S4Me: cookie di %s appena creati da un altro thread, li riuso" % domain)

        # Primo check: cookie gia validi per il dominio o il suo fallback?
        if cookies_valid(domain):
            logger.debug("S4Me: cookie gia validi per %s" % domain)
            return True
        if effective != domain and cookies_valid(effective):
            logger.debug("S4Me: cookie validi per fallback %s (originale: %s)" % (effective, domain))
            # Carica i cookie del fallback
            load_domain_cookies(effective, force=True)
            return True

        # Tenta la risoluzione (app, FlareSolverr o entrambi, secondo le impostazioni)
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
            "App non raggiungibile! Verifica che sia stata avviata sul dispositivo (%s)" % (base_url or "IP non configurato"),
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

    # Codici di protezione, oppure 200 con pagina di challenge (succede con la challenge localizzata)
    if response_code not in [200, 403, 429, 503]:
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

    # Se i cookie esistono ma CF risponde ancora 403, sono invalidi lato CF: ensure_domain_ready li
    # invalida solo se piu vecchi della richiesta bloccata (altrimenti li ha appena creati un altro thread)
    t0 = opt.get('_s4me_t0') or time.time()

    # Tenta la risoluzione
    logger.info("S4Me: protezione rilevata per %s, tentativo risoluzione al volo" % domain)
    success = ensure_domain_ready(domain, stale_before=t0)

    if success:
        # Segna il retry per evitare loop
        opt['_s4me_retry'] = True
        return True

    return False


# ============================================================================
# TEST CONNESSIONE
# ============================================================================

def _raw_test_connection():
    """Test connessione all'app (GET /ping), senza avvio automatico."""
    import json
    base_url = get_base_url()
    if not base_url:
        return False, "URL non configurato"
    try:
        data = json.loads(_http_get(base_url + "/ping", HTTP_CONNECT_TIMEOUT))
        return True, "Connesso! App %s, WebView %s" % (
            data.get("assistantVersion", "?"), data.get("wvbVersion", "?"))
    except Exception as e:
        return False, str(e)


def _test_flaresolverr():
    """Test connessione a FlareSolverr (GET sulla pagina principale)."""
    import json
    url = get_flaresolverr_url()
    root = url[:-3] if url.endswith("/v1") else url
    try:
        data = json.loads(_http_get(root, HTTP_CONNECT_TIMEOUT))
        return True, "FlareSolverr %s attivo" % data.get("version", "")
    except Exception as e:
        return False, "FlareSolverr: %s" % e


def test_connection():
    """
    Testa la connessione secondo il metodo scelto. NON avvia l'app.
    Con 'Automatico' basta che uno dei due risponda.
    Returns:
        tuple (success: bool, message: str)
    """
    method = get_cf_method()
    results = []
    if method in ("app", "auto"):
        ok, msg = _raw_test_connection()
        results.append((ok, ("App: " + msg) if method == "auto" else msg))
    if method in ("flaresolverr", "auto"):
        results.append(_test_flaresolverr())
    success = any(ok for ok, _ in results)
    return success, " | ".join(msg for _, msg in results)


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


# ============================================================================
# DOWNLOAD E INSTALLAZIONE DELL'APK
# ============================================================================

DEFAULT_APK_URL = "https://github.com/aandroide/Assistant/releases/latest/download/S4MeAssistant.apk"
DEFAULT_APK_DIR = "/storage/emulated/0/Download/kodi_apk/"


def _apk_download_dir():
    """Cartella dove salvare l'APK: Download di Android, oppure Download dell'utente su PC."""
    if _is_android():
        folder = DEFAULT_APK_DIR
    else:
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(folder):
            folder = os.path.join(config.get_data_path(), "apk")
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            folder = os.path.join(config.get_data_path(), "apk")
            try:
                os.makedirs(folder)
            except Exception:
                pass
    return folder


def download_apk():
    """Scarica l'APK dall'indirizzo impostato (o usa un percorso locale) e prova ad avviare l'installazione."""
    from platformcode import platformtools
    try:
        from urllib.request import urlopen, Request
    except ImportError:
        from urllib2 import urlopen, Request

    src = str(config.get_setting("s4me_apk_url", default=DEFAULT_APK_URL) or "").strip()
    if not src:
        platformtools.dialog_ok("S4Me Assistant", "Imposta prima l'indirizzo del file APK.")
        return False

    if src.startswith("/"):
        path = src
    else:
        apk_dir = _apk_download_dir()
        path = os.path.join(apk_dir, os.path.basename(urlparse.urlparse(src).path) or "S4MeAssistant.apk")
        progress = platformtools.dialog_progress("S4Me Assistant", "Download in corso")
        try:
            resp = urlopen(Request(src, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            total = int(resp.info().get("Content-Length") or 0)
            done = 0
            with open(path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        progress.update(int(done * 100 / total))
                    if progress.iscanceled():
                        raise Exception("annullato")
        except Exception as e:
            progress.close()
            platformtools.dialog_ok("S4Me Assistant", "Download fallito:\n%s" % e)
            return False
        progress.close()

    if not os.path.isfile(path):
        platformtools.dialog_ok("S4Me Assistant", "File non trovato:\n%s" % path)
        return False
    if _is_android():
        import xbmc
        xbmc.executebuiltin('StartAndroidActivity("","android.intent.action.VIEW",'
                            '"application/vnd.android.package-archive","file://%s")' % path)
    if _is_android():
        platformtools.dialog_ok("S4Me Assistant",
                                "APK salvato in:\n%s\nSe l'installazione non parte, aprilo dal gestore file." % path)
    else:
        platformtools.dialog_ok("S4Me Assistant",
                                "Questo non e un dispositivo Android: l'APK e stato solo scaricato in:\n%s\n"
                                "Copialo sul telefono oppure usa il QR code." % path)
    return True


def show_apk_qr():
    """Mostra a schermo il QR code con l'indirizzo di download dell'APK."""
    from platformcode import platformtools
    import xbmc
    src = str(config.get_setting("s4me_apk_url", default=DEFAULT_APK_URL) or "").strip()
    if not src or src.startswith("/"):
        platformtools.dialog_ok("S4Me Assistant", "Imposta prima l'indirizzo web del file APK.")
        return False
    try:
        from lib import segno
        folder = os.path.join(config.get_data_path(), "apk")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        qr_path = os.path.join(folder, "qr_apk.png")
        segno.make(src, error="m").save(qr_path, scale=10, border=4)
    except Exception as e:
        logger.error("S4Me: QR code non creato: %s" % e)
        platformtools.dialog_ok("S4Me Assistant", "QR code non creato:\n%s" % e)
        return False
    xbmc.executebuiltin('Dialog.Close(addonsettings)')
    try:
        import xbmcgui

        def _solid_png(path, rgb):
            """Crea un PNG 8x8 di un solo colore (serve per sfondo e pulsante)."""
            import zlib, struct
            row = b"\x00" + bytes(bytearray(rgb)) * 8
            raw = row * 8

            def chunk(tag, data):
                c = struct.pack(">I", len(data)) + tag + data
                return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
            png = (b"\x89PNG\r\n\x1a\n"
                   + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                   + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
            with open(path, "wb") as f:
                f.write(png)

        black = os.path.join(folder, "bg_nero.png")
        gray = os.path.join(folder, "btn_grigio.png")
        blue = os.path.join(folder, "btn_blu.png")
        _solid_png(black, (0, 0, 0))
        _solid_png(gray, (70, 70, 70))
        _solid_png(blue, (30, 110, 200))

        class _QRWindow(xbmcgui.WindowDialog):
            def __init__(self):
                xbmcgui.WindowDialog.__init__(self)
                size = 300
                x = (1280 - size) // 2
                y = 110
                self.addControl(xbmcgui.ControlImage(0, 0, 1280, 720, black))
                self.addControl(xbmcgui.ControlImage(x, y, size, size, qr_path, aspectRatio=2))
                self.addControl(xbmcgui.ControlLabel(140, y + size + 20, 1000, 40,
                                                     "Inquadra il QR code con il telefono per scaricare l'APK",
                                                     alignment=2))
                self.btn = xbmcgui.ControlButton((1280 - 220) // 2, y + size + 80, 220, 50, "Esci",
                                                 focusTexture=blue, noFocusTexture=gray, alignment=2 | 4)
                self.addControl(self.btn)
                self.setFocus(self.btn)

            def onControl(self, control):
                # si confronta l'id: l'oggetto passato da Kodi non e lo stesso di self.btn
                try:
                    if control.getId() == self.btn.getId():
                        self.close()
                except Exception:
                    self.close()

            def onClick(self, controlId):
                if controlId == self.btn.getId():
                    self.close()

            def onAction(self, action):
                aid = action.getId()
                # indietro, menu precedente, stop: chiudono la finestra
                if aid in (9, 10, 13, 92):
                    self.close()
                # clic del mouse o Invio sul pulsante Esci
                elif aid in (7, 100):
                    try:
                        if self.getFocusId() == self.btn.getId():
                            self.close()
                    except Exception:
                        pass

        win = _QRWindow()
        win.doModal()
        del win
    except Exception as e:
        logger.error("S4Me: finestra QR non disponibile (%s), uso la visualizzazione immagine" % e)
        xbmc.executebuiltin('ShowPicture(%s)' % qr_path)
    return True
