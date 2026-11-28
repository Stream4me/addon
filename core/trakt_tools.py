# -*- coding: utf-8 -*-
# -*- Tools for trakt sync -*-
# -*- Created for Alfa-addon -*-
# -*- By the Alfa Develop Group -*

import os
import sys
import json
import time
import traceback
from threading import Thread, Lock

import xbmc

from core import httptools, jsontools
from core.item import Item
from platformcode import config, logger

if sys.version_info[0] >= 3:
    from concurrent import futures
    from urllib.parse import urlencode
else:
    from concurrent_py2 import futures
    from urllib import urlencode

client_id = "zzm0oXxVRk0RodM-ryxy8ODJJToVNVhiYvaT9Kp0COw"
client_secret = ""

AUTH_URL = "https://auth.trakt.tv"
API_URL = "https://api.trakt.tv"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
SYNC_FILE = "trakt_data.json"

TIMEOUT_AUTH = 15
TIMEOUT_API = 30
LIMIT_MOVIES = 250
LIMIT_SHOWS = 100
MAX_PAGES = 200
CHECK_INTERVAL = 900
RETRY_DELAY = 120
REFRESH_MARGIN = 3600
REFRESH_COOLDOWN = 300
AUTH_COOLDOWN = 300
SEASON_TTL = 21600
OVERLAY_WATCHED = 5

_refresh_lock = Lock()
_sync_lock = Lock()
_last_refresh_fail = 0

_DEVICE_MESSAGES = {
    'pending': 'Autorizzazione non ancora completata',
    'invalid': 'Codice non valido, riavvia la procedura',
    'used': 'Codice gia utilizzato, riavvia la procedura',
    'expired': 'Codice scaduto, riavvia la procedura',
    'denied': 'Autorizzazione rifiutata',
    'slow': 'Troppe richieste, riprova tra qualche secondo',
    'error': 'Errore di comunicazione con Trakt',
}


def _headers(token=None):
    h = {'Content-Type': 'application/json',
         'Accept': 'application/json',
         'trakt-api-key': client_id,
         'trakt-api-version': '2'}
    if token:
        h['Authorization'] = 'Bearer %s' % token
    return h


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _header(headers, name):
    try:
        value = headers.get(name)
        if value is not None:
            return value
        for key in headers:
            if key.lower() == name.lower():
                return headers[key]
    except Exception:
        pass
    return None


def _notify(text, title="Trakt"):
    try:
        from platformcode import platformtools
        platformtools.dialog_notification(title, text)
    except Exception:
        logger.error(traceback.format_exc())


def _request(url, post=None, headers=None, timeout=TIMEOUT_API):
    opt = {'headers': headers or _headers(), 'timeout': timeout,
           'alfa_s': True, 'cookies': False}
    if post is not None:
        opt['post'] = post
    try:
        resp = httptools.downloadpage(url, **opt)
    except Exception:
        logger.error(traceback.format_exc())
        return 0, {}, {}

    code = getattr(resp, 'code', 0)
    if not isinstance(code, int):
        logger.error('Trakt: connessione fallita verso %s: %s' % (url, str(code)[-300:]))
        return 0, {}, {}

    body = getattr(resp, 'data', '')
    data = {}
    if body:
        try:
            data = jsontools.load(body)
        except Exception:
            data = {}
    return code, data, (getattr(resp, 'headers', {}) or {})


def _get_token():
    return config.get_setting("token_trakt", "trakt") or ''


def _save_tokens(data):
    created = _to_int(data.get('created_at')) or int(time.time())
    expires_in = _to_int(data.get('expires_in')) or 7 * 86400
    config.set_setting("token_trakt", data["access_token"], "trakt")
    if data.get('refresh_token'):
        config.set_setting("refresh_token_trakt", data["refresh_token"], "trakt")
    config.set_setting("token_expires_trakt", str(created + expires_in), "trakt")
    config.set_setting("client_id_trakt", client_id, "trakt")
    config.set_setting("auth_fail_trakt", "", "trakt")


def _clear_tokens():
    config.set_setting("token_trakt", "", "trakt")
    config.set_setting("refresh_token_trakt", "", "trakt")
    config.set_setting("token_expires_trakt", "", "trakt")


def reset_if_client_changed():
    try:
        if config.get_setting('token_trakt', 'trakt') and \
                config.get_setting('client_id_trakt', 'trakt') != client_id:
            logger.info('trakt: token di un\'altra app, azzerato')
            _clear_tokens()
    except Exception:
        logger.error(traceback.format_exc())


def refresh_access_token(used_token=None):
    global _last_refresh_fail
    with _refresh_lock:
        current = _get_token()
        if used_token and current and current != used_token:
            return True

        if time.time() - _last_refresh_fail < REFRESH_COOLDOWN:
            return False

        refresh = config.get_setting("refresh_token_trakt", "trakt")
        if not refresh:
            return False

        body = {'refresh_token': refresh, 'client_id': client_id,
                'redirect_uri': REDIRECT_URI, 'grant_type': 'refresh_token'}
        if client_secret:
            body['client_secret'] = client_secret

        code, data, _ = _request(AUTH_URL + "/oauth/token", post=jsontools.dump(body),
                                 timeout=TIMEOUT_AUTH)

        if code == 200 and isinstance(data, dict) and data.get('access_token'):
            _save_tokens(data)
            _last_refresh_fail = 0
            logger.info('Trakt: token rinnovato')
            return True

        _last_refresh_fail = time.time()
        error = data.get('error') if isinstance(data, dict) else ''
        desc = data.get('error_description') if isinstance(data, dict) else ''
        logger.error('Trakt: rinnovo del token fallito (HTTP %s, error=%s, %s)' % (code, error, desc))
        if code == 400 and error == 'invalid_grant':
            _clear_tokens()
            _notify('Sessione Trakt scaduta: riautorizza l\'account dalle impostazioni')
        return False


def get_valid_token():
    token = _get_token()
    if not token:
        return ''
    expires_at = _to_int(config.get_setting("token_expires_trakt", "trakt"))
    if expires_at and time.time() > expires_at - REFRESH_MARGIN:
        refresh_access_token(token)
        token = _get_token()
    return token


def _api_get(path, params=None, retry=True):
    token = get_valid_token()
    if not token:
        return None
    url = API_URL + path
    if params:
        url += '?' + urlencode(params)
    code, data, headers = _request(url, headers=_headers(token))
    if code == 401 and retry:
        if refresh_access_token(token):
            return _api_get(path, params, retry=False)
    return code, data, headers


def _auth_in_cooldown():
    last = _to_int(config.get_setting("auth_fail_trakt", "trakt"))
    return bool(last) and 0 <= time.time() - last < AUTH_COOLDOWN


def _auth_failed():
    config.set_setting("auth_fail_trakt", str(int(time.time())), "trakt")


def auth_trakt():
    # Il launcher chiama questa funzione a ogni lista finche manca il token:
    # dopo un errore si attende prima di riprovare, per non martellare Trakt
    if _auth_in_cooldown():
        return
    item = Item()
    folder = (config.get_platform() == "plex")
    item.folder = folder
    try:
        post = jsontools.dump({'client_id': client_id})
        code, data, _ = _request(AUTH_URL + "/oauth/device/code", post=post, timeout=TIMEOUT_AUTH)
        if code != 200 or not isinstance(data, dict) or 'device_code' not in data:
            logger.error('Trakt: richiesta del codice dispositivo fallita (HTTP %s): %s' % (code, data))
            _auth_failed()
            _notify('Impossibile contattare Trakt, riprova piu tardi')
            return

        item.verify_url = data["verification_url"]
        item.user_code = data["user_code"]
        item.device_code = data["device_code"]
        item.intervalo = data.get("interval", 5)
        item.expires_in = data.get("expires_in", 600)
        if not item.folder:
            token_trakt(item)
        else:
            itemlist = []
            title = config.get_localized_string(60248) % item.verify_url
            itemlist.append(item.clone(title=title, action=""))
            title = config.get_localized_string(60249) % item.user_code
            itemlist.append(item.clone(title=title, action=""))
            title = config.get_localized_string(60250)
            itemlist.append(item.clone(title=title, action="token_trakt"))
            return itemlist
    except Exception:
        logger.error(traceback.format_exc())
        _auth_failed()


def _poll_device_token(device_code):
    post = jsontools.dump({'code': device_code, 'client_id': client_id})
    code, data, _ = _request(AUTH_URL + "/oauth/device/token", post=post, timeout=TIMEOUT_AUTH)
    if code == 200 and isinstance(data, dict) and data.get('access_token'):
        return 'ok', data
    status = {400: 'pending', 404: 'invalid', 409: 'used',
              410: 'expired', 418: 'denied', 429: 'slow'}.get(code, 'error')
    if status == 'error':
        logger.error('Trakt: controllo del device token fallito (HTTP %s)' % code)
    return status, data


def _wait_for_authorization(item):
    from platformcode import platformtools

    monitor = xbmc.Monitor()
    dialog_auth = platformtools.dialog_progress(
        config.get_localized_string(60251),
        config.get_localized_string(60252) % item.verify_url + '\n' +
        config.get_localized_string(60253) % item.user_code + '\n' +
        config.get_localized_string(60254))

    interval = max(_to_int(getattr(item, 'intervalo', 5), 5), 1)
    expires_in = _to_int(getattr(item, 'expires_in', 600), 600) or 600
    deadline = time.time() + expires_in
    errors = 0
    token = ''

    try:
        while time.time() < deadline:
            waited = 0.0
            while waited < interval:
                if dialog_auth.iscanceled() or monitor.waitForAbort(0.5):
                    config.set_setting("trakt_sync", False)
                    return None
                waited += 0.5

            status, data = _poll_device_token(item.device_code)
            if status == 'ok':
                _save_tokens(data)
                token = data["access_token"]
                break
            if status == 'pending':
                errors = 0
                continue
            if status == 'slow':
                interval += 5
                continue
            if status == 'error':
                errors += 1
                if errors >= 5:
                    _notify(_DEVICE_MESSAGES['error'])
                    break
                continue
            _notify(_DEVICE_MESSAGES[status])
            break
        else:
            _notify(_DEVICE_MESSAGES['expired'])
    finally:
        try:
            dialog_auth.close()
        except Exception:
            pass

    return token


def token_trakt(item):
    from platformcode import platformtools

    token = ""
    try:
        if item.extra == "renew":
            return refresh_access_token()

        if item.action == "token_trakt":
            status, data = _poll_device_token(item.device_code)
            if status == 'ok':
                _save_tokens(data)
                token = data["access_token"]
            else:
                _notify(_DEVICE_MESSAGES.get(status, _DEVICE_MESSAGES['error']))
        else:
            token = _wait_for_authorization(item)
            if token is None:
                return
    except Exception:
        logger.error(traceback.format_exc())
        token = ""
        _notify('Errore durante l\'autorizzazione di Trakt')

    if not item.folder:
        if token:
            platformtools.dialog_notification(config.get_localized_string(60255),
                                              config.get_localized_string(60256))
            xbmc.executebuiltin("Container.Refresh")
        return

    itemlist = []
    if token:
        itemlist.append(item.clone(title=config.get_localized_string(60256), action=""))
    else:
        itemlist.append(item.clone(title=config.get_localized_string(60260), action=""))

    return itemlist


def set_trakt_info(item):
    logger.debug()
    import xbmcgui
    from core import scrapertools
    try:
        info = item.infoLabels or {}
        tmdb = info.get('tmdb_id') or info.get('tmdb_id_show')
        title = info.get('title') or info.get('tvshowtitle') or item.contentSerieName or item.fulltitle
        ids = jsontools.dump({'tmdb': tmdb, 'tvdb': info.get('tvdb_id'), 'imdb': info.get('imdb_id', ''),
                              'slug': scrapertools.slugify(title)})
        xbmcgui.Window(10000).setProperty('script.trakt.ids', ids)
        logger.info('Trakt: ids per script.trakt: %s anno=%s tipo=%s' % (ids, info.get('year'), item.contentType))
    except Exception:
        logger.info('Trakt: ids per script.trakt non impostati: %s' % traceback.format_exc())


def _fetch_all(path, params, limit):
    items = []
    seen = set()
    page = 1
    while page <= MAX_PAGES:
        query = dict(params or {})
        query['page'] = page
        query['limit'] = limit
        res = _api_get(path, query)
        if res is None:
            return None
        code, data, headers = res
        if code != 200 or not isinstance(data, list):
            logger.error('Trakt: %s pagina %s non riuscita (HTTP %s)' % (path, page, code))
            return None
        if not data:
            break

        signature = json.dumps(data[0], sort_keys=True)
        if signature in seen:
            logger.info('Trakt: %s pagina %s ripete dati gia ricevuti, mi fermo' % (path, page))
            break
        seen.add(signature)
        items.extend(data)

        page_count = _to_int(_header(headers, 'X-Pagination-Page-Count'))
        if page_count and page >= page_count:
            break
        page += 1
    else:
        logger.error('Trakt: raggiunto il limite di %s pagine per %s' % (MAX_PAGES, path))
        return None
    return items


def _parse_movies(items, id_type):
    id_list = []
    for it in items:
        try:
            value = it['movie']['ids'].get(id_type)
        except (KeyError, TypeError, AttributeError):
            continue
        if value:
            id_list.append(str(value))
    return id_list


def _parse_shows(items, id_map=None, complete=None):
    dict_show = {}
    no_seasons = 0
    for it in items:
        try:
            ids = it['show']['ids']
            tmdb = ids.get('tmdb')
        except (KeyError, TypeError, AttributeError):
            continue
        if not tmdb:
            continue
        seasons = it.get('seasons')
        if seasons is None:
            no_seasons += 1
            continue

        reset_at = it.get('reset_at')
        season_dict = {}
        watched_count = 0
        for season in seasons:
            number = season.get('number')
            if number is None:
                continue
            episodes = []
            for episode in season.get('episodes', []):
                if episode.get('number') is None:
                    continue
                if reset_at and (episode.get('last_watched_at') or '') < reset_at:
                    continue
                episodes.append(str(episode['number']))
            if episodes:
                season_dict[str(number)] = episodes
                if number != 0:
                    watched_count += len(episodes)
        if season_dict:
            dict_show[str(tmdb)] = season_dict
            aired = _to_int((it.get('show') or {}).get('aired_episodes'))
            if complete is not None and aired and watched_count >= aired:
                complete.append(str(tmdb))
            if id_map is not None and ids.get('trakt'):
                id_map[str(tmdb)] = ids['trakt']

    if no_seasons:
        logger.error('Trakt: %s serie senza il campo "seasons": la risposta non contiene '
                     'stagioni ed episodi (verificare extended=progress)' % no_seasons)
    return dict_show


def _fetch_watched(mediatype, id_type='tmdb', id_map=None, complete=None):
    if mediatype == 'movies':
        items = _fetch_all('/sync/watched/movies', {}, LIMIT_MOVIES)
        return None if items is None else _parse_movies(items, id_type)
    if mediatype == 'shows':
        items = _fetch_all('/sync/watched/shows', {'extended': 'progress'}, LIMIT_SHOWS)
        return None if items is None else _parse_shows(items, id_map, complete)
    return None


def _sync_path():
    return os.path.join(config.get_data_path(), 'settings_channels', SYNC_FILE)


def _load_node():
    node = {}
    if os.path.exists(_sync_path()):
        try:
            node = jsontools.get_node_from_file('trakt', "TRAKT") or {}
        except Exception:
            logger.error(traceback.format_exc())
            node = {}
    return node


def _save_node(node):
    jsontools.update_node(node, 'trakt', 'TRAKT')


def _shows_meta_missing(node):
    return 'show_ids' not in node or 'shows_complete' not in node


def get_trakt_watched(id_type, mediatype, update=False):
    logger.debug()

    empty = {} if mediatype == 'shows' else []
    if not _get_token():
        return empty

    if id_type != 'tmdb':
        data = _fetch_watched(mediatype, id_type)
        return empty if data is None else data

    node = _load_node()
    cached = node.get(mediatype)
    if cached is not None and not update:
        return cached

    id_map = {} if mediatype == 'shows' else None
    complete = [] if mediatype == 'shows' else None
    data = _fetch_watched(mediatype, 'tmdb', id_map, complete)
    if data is None:
        return cached if cached is not None else empty

    node[mediatype] = data
    if id_map is not None:
        node['show_ids'] = id_map
        node['shows_complete'] = complete
    _save_node(node)
    return data


def sync_if_changed(kinds=None, force=False, full=False):
    kinds = kinds or ('movies', 'shows')
    if not _get_token():
        return
    if not _sync_lock.acquire(False):
        return
    try:
        node = _load_node()
        meta = node.get('sync_meta') or {}
        now = int(time.time())

        due = [k for k in kinds
               if force or node.get(k) is None
               or (k == 'shows' and _shows_meta_missing(node))
               or now - _to_int((meta.get(k) or {}).get('checked')) >= CHECK_INTERVAL]
        if not due:
            return

        activities = None
        res = _api_get('/sync/last_activities')
        if res and res[0] == 200 and isinstance(res[1], dict):
            activities = res[1]
        else:
            logger.error('Trakt: last_activities non disponibile')

        changed = False
        for kind in due:
            m = meta.get(kind) or {}
            meta[kind] = m
            retry_at = now - CHECK_INTERVAL + RETRY_DELAY

            if activities is None and node.get(kind) is not None:
                m['checked'] = retry_at
                continue

            section = (activities or {}).get('movies' if kind == 'movies' else 'episodes') or {}
            stamp = section.get('watched_at')

            if full or node.get(kind) is None or stamp is None or stamp != m.get('activity') \
                    or (kind == 'shows' and _shows_meta_missing(node)):
                id_map = {} if kind == 'shows' else None
                complete = [] if kind == 'shows' else None
                data = _fetch_watched(kind, 'tmdb', id_map, complete)
                if data is None:
                    m['checked'] = retry_at
                    continue
                node[kind] = data
                changed = True
                if id_map is not None:
                    node['show_ids'] = id_map
                    node['shows_complete'] = complete
                m['activity'] = stamp
            m['checked'] = now

        node['sync_meta'] = meta
        _save_node(node)
        return changed
    except Exception:
        logger.error(traceback.format_exc())
    finally:
        _sync_lock.release()


def _mark(info, watched):
    if watched:
        info['playcount'] = 1
        info['overlay'] = OVERLAY_WATCHED
    elif _to_int(info.get('overlay')) == OVERLAY_WATCHED:
        info.pop('overlay', None)
        info.pop('playcount', None)


def _is_library_item(item):
    action = str(getattr(item, 'action', '') or '').lower()
    return 'library' in action or 'videoteca' in action


def get_completed_shows():
    get_trakt_watched('tmdb', 'shows')
    return set(_load_node().get('shows_complete') or [])


def _is_season(info):
    mediatype = info.get('mediatype')
    if mediatype == 'season':
        return True
    return mediatype == 'tvshow' and info.get('season') not in (None, '')


def _lookup_trakt_id(tmdb_id):
    res = _api_get('/search/tmdb/%s' % tmdb_id, {'type': 'show'})
    if res and res[0] == 200 and isinstance(res[1], list):
        for result in res[1]:
            ids = (result.get('show') or {}).get('ids') or {}
            if str(ids.get('tmdb')) == str(tmdb_id) and ids.get('trakt'):
                return ids['trakt']
    logger.info('Trakt: nessun id Trakt trovato per la serie tmdb %s' % tmdb_id)
    return None


def get_completed_seasons(tmdb_id, imdb_id=''):
    tmdb_id = str(tmdb_id or '')
    if not tmdb_id or not _get_token():
        return set()

    node = _load_node()
    if tmdb_id not in (node.get('shows') or {}):
        return set()

    activity = ((node.get('sync_meta') or {}).get('shows') or {}).get('activity')
    entry = (node.get('season_progress') or {}).get(tmdb_id)
    stale = set(entry.get('complete', [])) if entry else set()
    now = int(time.time())
    if entry and now - _to_int(entry.get('checked')) < SEASON_TTL and entry.get('activity') == activity:
        return stale

    ref = (node.get('show_ids') or {}).get(tmdb_id) or imdb_id
    if not ref:
        ref = _lookup_trakt_id(tmdb_id)
        if not ref:
            return stale
        node.setdefault('show_ids', {})[tmdb_id] = ref

    res = _api_get('/shows/%s/progress/watched' % ref, {'specials': 'true', 'count_specials': 'false'})
    if not res or res[0] != 200 or not isinstance(res[1], dict):
        logger.error('Trakt: progresso della serie %s non disponibile (HTTP %s)' % (ref, res[0] if res else None))
        return stale

    complete = []
    for season in res[1].get('seasons') or []:
        number = season.get('number')
        if number is None:
            continue
        aired, completed = season.get('aired'), season.get('completed')
        if aired is None or completed is None:
            episodes = season.get('episodes') or []
            aired = len(episodes)
            completed = len([e for e in episodes if e.get('completed')])
        if aired and completed >= aired:
            complete.append(str(number))

    node.setdefault('season_progress', {})[tmdb_id] = {'checked': now, 'activity': activity,
                                                       'complete': complete}
    _save_node(node)
    return set(complete)


def trakt_check(itemlist):
    if type(itemlist) != list:
        return

    def sync(item, id_result):
        info = item.infoLabels
        try:
            if _is_library_item(item):
                info.pop('playcount', None)
                info.pop('overlay', None)
                return

            mediatype = info.get('mediatype')
            tmdb_id = str(info.get('tmdb_id') or '')

            if mediatype == 'movie':
                if tmdb_id and tmdb_id in id_result.get('movie', ()):
                    info['playcount'] = 1
            elif _is_season(info):
                done = bool(tmdb_id) and info.get('season') is not None and \
                    str(info['season']) in id_result.get('season', {}).get(tmdb_id, ())
                _mark(info, done)
            elif mediatype == 'tvshow':
                _mark(info, bool(tmdb_id) and tmdb_id in id_result.get('tvshow', ()))
            elif mediatype == 'episode':
                season = info.get('season')
                episode = info.get('episode')
                done = bool(tmdb_id) and season is not None and episode is not None and \
                    tmdb_id in id_result.get('episode', {}) and \
                    str(episode) in id_result['episode'][tmdb_id].get(str(season), [])
                if done:
                    info['playcount'] = 1
                elif _to_int(info.get('overlay')) == OVERLAY_WATCHED:
                    _mark(info, False)
        except Exception:
            logger.debug('Trakt: controllo visto non riuscito: %s' % traceback.format_exc())

    if itemlist and itemlist[0].channel != 'videolibrary' \
            and 'mediatype' in itemlist[0].infoLabels \
            and (itemlist[0].infoLabels['mediatype'] in ['movie', 'episode', 'tvshow']
                 or _is_season(itemlist[0].infoLabels)):

        mediatype = itemlist[0].infoLabels['mediatype']
        kind = 'movies' if mediatype == 'movie' else 'shows'

        sync_if_changed((kind,))

        id_result = {}
        if mediatype == 'movie':
            id_result['movie'] = set(get_trakt_watched('tmdb', 'movies'))
        elif mediatype == 'episode':
            id_result['episode'] = get_trakt_watched('tmdb', 'shows')
        elif not _is_season(itemlist[0].infoLabels):
            id_result['tvshow'] = get_completed_shows()
        else:
            get_trakt_watched('tmdb', 'shows')
            id_result['season'] = {}
            for it in itemlist:
                tid = str(it.infoLabels.get('tmdb_id') or '')
                if tid and tid not in id_result['season']:
                    id_result['season'][tid] = get_completed_seasons(tid, it.infoLabels.get('imdb_id'))

        with futures.ThreadPoolExecutor() as executor:
            [executor.submit(sync, it, id_result) for it in itemlist]

    return itemlist


def get_sync_from_file():
    logger.debug()
    sync_if_changed(force=True)


def update_trakt_data(mediatype, trakt_data):
    logger.debug()

    if os.path.exists(_sync_path()):
        trakt_node = _load_node()
        trakt_node[mediatype] = trakt_data
        _save_node(trakt_node)


def ask_install_script():
    logger.debug()

    from platformcode import platformtools

    respuesta = platformtools.dialog_yesno(config.get_localized_string(20000), config.get_localized_string(70521))
    if respuesta:
        xbmc.executebuiltin("InstallAddon(script.trakt)")
        return
    else:
        config.set_setting('install_trakt', False)
        return


def wait_for_update_trakt():
    logger.debug()
    # Dopo una riproduzione basta il controllo con last_activities: niente scaricamento completo
    t = Thread(target=update_all, kwargs={'full': False})
    t.daemon = True
    t.start()


def _refresh_list():
    # Ridisegna la lista S4Me aperta, cosi' le spunte nuove si vedono senza uscire e rientrare.
    # Ritorna True se ha eseguito il refresh
    try:
        if xbmc.Player().isPlaying():
            return False
        if 'plugin.video.s4me' in xbmc.getInfoLabel('Container.FolderPath'):
            xbmc.executebuiltin('Container.Refresh')
            return True
    except Exception:
        logger.error(traceback.format_exc())
    return False


def _stamps():
    # Segni di modifica salvati con i dati Trakt: cambiano quando qualunque processo aggiorna i visti
    meta = _load_node().get('sync_meta') or {}
    return (str((meta.get('movies') or {}).get('activity')), str((meta.get('shows') or {}).get('activity')))


def update_all(full=True):
    # full=True (avvio del servizio): ricarica sempre i visti da Trakt, cosi una visione
    # tolta dal sito sparisce. full=False (dopo una riproduzione): ricarica solo se Trakt segnala modifiche
    from time import sleep
    logger.debug()
    if full:
        sleep(20)
        while xbmc.Player().isPlaying():
            sleep(20)
        sync_if_changed(force=True, full=True)
        return

    before = _stamps()
    # attende l'avvio e poi la fine della riproduzione, controllando ogni secondo
    for _ in range(60):
        if xbmc.Player().isPlaying():
            break
        sleep(1)
    while xbmc.Player().isPlaying():
        sleep(1)
    # script.trakt invia la visione a Trakt qualche secondo dopo lo stop: si controlla ogni 2 secondi
    # (solo last_activities, leggero) e appena Trakt segnala la novita si ridisegna la lista.
    # I dati possono essere aggiornati anche dal servizio: si confrontano i segni salvati
    sleep(1)
    for _ in range(30):
        sync_if_changed(force=True, full=False)
        if _stamps() != before:
            # subito dopo lo stop la finestra puo essere ancora quella del video: si riprova per qualche secondo
            for _ in range(10):
                if _refresh_list():
                    break
                sleep(1)
            return
        sleep(2)
