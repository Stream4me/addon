# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# XBMC Library Tools
# ------------------------------------------------------------
# from future import standard_library
# standard_library.install_aliases()
#from builtins import str
import sys, os, threading, time, re, math, xbmc, xbmcgui
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

if PY3:
    import urllib.request as urllib2                                # Es muy lento en PY2.  En PY3 es nativo
else:
    import urllib2                                                  # Usamos el nativo de PY2 que es más rápido

from core import filetools, jsontools, support
from platformcode import config, logger, platformtools
from core import scrapertools
from xml.dom import minidom


# Mappa di alias linguistici per il riconoscimento delle tracce audio/sottotitoli.
# Le chiavi corrispondono ai valori salvati in tvshow_media_prefs.
_LANG_ALIASES = {
    'ita': ['ita', 'italiano', 'italian', 'it'],
    'eng': ['eng', 'english', 'en'],
    'spa': ['spa', 'espanol', 'spanish', 'es'],
    'fra': ['fra', 'francais', 'french', 'fr'],
    'deu': ['deu', 'deutsch', 'german', 'de'],
    'por': ['por', 'portugues', 'portuguese', 'pt'],
    'jpn': ['jpn', 'japanese', 'ja'],
}


def _apply_media_prefs(item):
    """
    Applica le preferenze audio/sottotitoli salvate in tvshow.nfo dopo l'avvio
    della riproduzione. Chiamata da mark_as_watched_subThread().
    """
    try:
        nfo = item.nfo
        if not nfo or not str(nfo).endswith('tvshow.nfo'):
            return
        if not filetools.exists(nfo):
            return

        from core import videolibrarytools
        head_nfo, tvshow_item = videolibrarytools.read_nfo(nfo)
        prefs = getattr(tvshow_item, 'tvshow_media_prefs', None)
        if not prefs:
            return

        audio_lang = prefs.get('audio_lang', '')
        sub_lang   = prefs.get('sub_lang',   '__on__')
        if not audio_lang and not sub_lang:
            return

        # Attende che le tracce siano disponibili (1.5 secondi dopo l'avvio)
        for _ in range(3):
            if not platformtools.is_playing():
                return
            time.sleep(0.5)

        if not platformtools.is_playing():
            return

        player = xbmc.Player()

        # Imposta la traccia audio
        if audio_lang:
            try:
                streams = player.getAvailableAudioStreams()
                aliases = _LANG_ALIASES.get(audio_lang, [audio_lang])
                # Prima passa: cerca tracce non-FORCED
                found = False
                for i, label in enumerate(streams):
                    s = label.lower()
                    if 'forced' in s:
                        continue
                    for alias in aliases:
                        if alias.lower() in s:
                            player.setAudioStream(i)
                            logger.debug("_apply_media_prefs: audio stream %d selezionato: %s" % (i, label))
                            found = True
                            break
                    if found:
                        break
                # Seconda passa: accetta anche FORCED se non trovato nulla
                if not found:
                    for i, label in enumerate(streams):
                        s = label.lower()
                        for alias in aliases:
                            if alias.lower() in s:
                                player.setAudioStream(i)
                                logger.debug("_apply_media_prefs: audio stream (forced) %d selezionato: %s" % (i, label))
                                found = True
                                break
                        if found:
                            break
                if not found:
                    logger.debug("_apply_media_prefs: nessuna traccia audio corrisponde a '%s'" % audio_lang)
            except Exception as e:
                logger.error("_apply_media_prefs: errore impostando audio: %s" % str(e))

        # Imposta i sottotitoli
        if sub_lang:
            try:
                if sub_lang == '__off__':
                    # Forza sottotitoli spenti
                    player.showSubtitles(False)
                    logger.debug("_apply_media_prefs: sottotitoli disabilitati")
                elif sub_lang == '__on__':
                    # Abilita sottotitoli senza cambiare la traccia
                    player.showSubtitles(True)
                    logger.debug("_apply_media_prefs: sottotitoli abilitati (lingua default)")
                else:
                    streams = player.getAvailableSubtitleStreams()
                    aliases = _LANG_ALIASES.get(sub_lang, [sub_lang])
                    # Prima passa: cerca tracce non-FORCED
                    found = False
                    for i, label in enumerate(streams):
                        s = label.lower()
                        if 'forced' in s:
                            continue
                        for alias in aliases:
                            if alias.lower() in s:
                                player.setSubtitleStream(i)
                                player.showSubtitles(True)
                                logger.debug("_apply_media_prefs: sottotitolo stream %d selezionato: %s" % (i, label))
                                found = True
                                break
                        if found:
                            break
                    # Seconda passa: accetta anche FORCED se non trovato nulla
                    if not found:
                        for i, label in enumerate(streams):
                            s = label.lower()
                            for alias in aliases:
                                if alias.lower() in s:
                                    player.setSubtitleStream(i)
                                    player.showSubtitles(True)
                                    logger.debug("_apply_media_prefs: sottotitolo stream (forced) %d selezionato: %s" % (i, label))
                                    found = True
                                    break
                            if found:
                                break
                    if not found:
                        logger.debug("_apply_media_prefs: nessun sottotitolo corrisponde a '%s'" % sub_lang)
            except Exception as e:
                logger.error("_apply_media_prefs: errore impostando sottotitoli: %s" % str(e))

    except Exception as e:
        logger.error("_apply_media_prefs: errore generale: %s" % str(e))


def mark_auto_as_watched(item):
    def mark_as_watched_subThread(item):
        logger.debug()
        actual_time = 0
        total_time = 0

        time_limit = time.time() + 10
        while not platformtools.is_playing() and time.time() < time_limit:
            time.sleep(1)

        _apply_media_prefs(item)

        marked = False
        sync = False
        next_episode = None
        mark_time = 0

        percentage = float(config.get_setting("watched_setting")) / 100
        time_from_end = config.get_setting('next_ep_seconds')

        if item.contentType != 'movie' and 0 < config.get_setting('next_ep') < 3:
            next_dialogs = ['NextDialog.xml', 'NextDialogExtended.xml', 'NextDialogCompact.xml']
            next_ep_type = config.get_setting('next_ep_type')
            ND = next_dialogs[next_ep_type]
            try:
                next_episode = next_ep(item)
            except:
                next_episode = False
            logger.debug(next_episode)

        while not xbmc.Monitor().abortRequested():
            if not platformtools.is_playing(): break
            try: actual_time = xbmc.Player().getTime()
            except: pass
            try: total_time = xbmc.Player().getTotalTime()
            except: pass

            mark_time = total_time * percentage
            difference = total_time - actual_time

            # Mark as Watched
            if mark_time and total_time > actual_time > mark_time and not marked:
                logger.info("Marked as Watched")
                item.playcount = 1
                marked = True
                item.played_time = 0
                platformtools.set_played_time(item)
                if item.options['strm'] : sync = True
                from specials import videolibrary
                videolibrary.mark_content_as_watched2(item)
                if not next_episode:
                    break

            # check for next Episode
            if next_episode and sync and time_from_end >= difference:
                nextdialog = NextDialog(ND, config.get_runtime_path())
                while platformtools.is_playing() and not nextdialog.is_exit():
                    xbmc.sleep(100)
                if nextdialog.continuewatching:
                    next_episode.next_ep = True
                    xbmc.Player().stop()
                nextdialog.close()
                break


        # Silent sync with Trakt
        if sync and config.get_setting("trakt_sync"): sync_trakt_kodi()

        while platformtools.is_playing():
            xbmc.sleep(300)

        if (marked and total_time < 20) or not marked:
            platformtools.set_played_time(item.clone(played_time=actual_time))
            item.disableAutoplay=True
            platformtools.serverWindow(item, itemlist)

        if next_episode and next_episode.next_ep and config.get_setting('next_ep') < 3:
            from platformcode.launcher import run
            xbmc.sleep(1000)
            run(next_episode)

        db.close()

    # If it is configured to mark as seen
    from core import db
    if config.get_setting("mark_as_watched", "videolibrary"):
        itemlist = db['player'].get('itemlist', [])
        db['player']['itemlist'] = []
        db.close()
        threading.Thread(target=mark_as_watched_subThread, args=[item]).start()
        logger.debug('EXIT MONITOR')

def sync_trakt_addon(path_folder):
    """
       Updates the values of episodes seen if
    """
    logger.debug()
    # if the addon exists we do the search
    if xbmc.getCondVisibility('System.HasAddon("script.trakt")'):
        # we import dependencies
        paths = ["special://home/addons/script.module.dateutil/lib/", "special://home/addons/script.module.six/lib/",
                 "special://home/addons/script.module.arrow/lib/", "special://home/addons/script.module.trakt/lib/",
                 "special://home/addons/script.trakt/"]

        for path in paths:
            sys.path.append(xbmc.translatePath(path))

        # the series seen is obtained
        try:
            from resources.lib.traktapi import traktAPI
            traktapi = traktAPI()
        except:
            return

        shows = traktapi.getShowsWatched({})
        shows = list(shows.items())

        # we get the series id to compare
        _id = re.findall(r"\[(.*?)\]", path_folder, flags=re.DOTALL)[0]
        logger.debug("the id is %s" % _id)

        if "tt" in _id:
            type_id = "imdb"
        elif "tvdb_" in _id:
            _id = _id.strip("tvdb_")
            type_id = "tvdb"
        elif "tmdb_" in _id:
            type_id = "tmdb"
            _id = _id.strip("tmdb_")
        else:
            logger.error("There is no _id of the series")
            return

        # we obtain the values ​​of the series
        from core import videolibrarytools
        tvshow_file = filetools.join(path_folder, "tvshow.nfo")
        head_nfo, serie = videolibrarytools.read_nfo(tvshow_file)

        # we look in the trakt series
        for show in shows:
            show_aux = show[1].to_dict()

            try:
                _id_trakt = show_aux['ids'].get(type_id, None)
                # logger.debug("ID ES %s" % _id_trakt)
                if _id_trakt:
                    if _id == _id_trakt:
                        logger.debug("FOUND! %s" % show_aux)

                        # we create the trakt dictionary for the found series with the value that has "seen"
                        dict_trakt_show = {}

                        for idx_season, season in enumerate(show_aux['seasons']):
                            for idx_episode, episode in enumerate(show_aux['seasons'][idx_season]['episodes']):
                                sea_epi = "%sx%s" % (show_aux['seasons'][idx_season]['number'], str(show_aux['seasons'][idx_season]['episodes'][idx_episode]['number']).zfill(2))

                                dict_trakt_show[sea_epi] = show_aux['seasons'][idx_season]['episodes'][idx_episode]['watched']
                        logger.debug("dict_trakt_show %s " % dict_trakt_show)

                        # we get the keys that are episodes
                        regex_epi = re.compile(r'\d+x\d+')
                        keys_episodes = [key for key in serie.library_playcounts if regex_epi.match(key)]
                        # we get the keys that are seasons
                        keys_seasons = [key for key in serie.library_playcounts if 'season ' in key]
                        # we get the numbers of the seasons keys
                        seasons = [key.strip('season ') for key in keys_seasons]

                        # we mark the episodes watched
                        for k in keys_episodes:
                            serie.library_playcounts[k] = dict_trakt_show.get(k, 0)

                        for season in seasons:
                            episodios_temporada = 0
                            episodios_vistos_temporada = 0

                            # we obtain the keys of the episodes of a certain season
                            keys_season_episodes = [key for key in keys_episodes if key.startswith("%sx" % season)]

                            for k in keys_season_episodes:
                                episodios_temporada += 1
                                if serie.library_playcounts[k] > 0:
                                    episodios_vistos_temporada += 1

                            # it is verified that if all the episodes are watched, the season is marked as watched
                            if episodios_temporada == episodios_vistos_temporada:
                                serie.library_playcounts.update({"season %s" % season: 1})

                        temporada = 0
                        temporada_vista = 0

                        for k in keys_seasons:
                            temporada += 1
                            if serie.library_playcounts[k] > 0:
                                temporada_vista += 1

                        # sCheck that if all seasons are viewed, the series is marked as view
                        if temporada == temporada_vista:
                            serie.library_playcounts.update({serie.title: 1})

                        logger.debug("the new values %s " % serie.library_playcounts)
                        filetools.write(tvshow_file, head_nfo + serie.tojson())

                        break
                    else:
                        continue

                else:
                    logger.error("could not get id, trakt has: %s" % show_aux['ids'])

            except:
                import traceback
                logger.error(traceback.format_exc())


def sync_trakt_kodi(silent=True):
    # So that the synchronization is not silent it is worth with silent = False
    if xbmc.getCondVisibility('System.HasAddon("script.trakt")'):
        notificacion = True
        if not config.get_setting("sync_trakt_notification", "videolibrary") and platformtools.is_playing():
            notificacion = False

        xbmc.executebuiltin('RunScript(script.trakt,action=sync,silent=%s)' % silent)
        logger.debug("Synchronization with Trakt started")

        if notificacion:
            platformtools.dialog_notification(config.get_localized_string(20000), config.get_localized_string(60045), sound=False, time=2000)


def mark_content_as_watched_on_kodi(item, value=1):
    """
    mark the content as seen or not seen in the Kodi library
    @type item: item
    @param item: element to mark
    @type value: int
    @param value: > 0 for seen, 0 for not seen
    """
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))
    payload_f = ''

    if item.contentType == "movie":
        movieid = 0
        payload = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies",
                   "params": {"properties": ["title", "playcount", "originaltitle", "file"]},
                   "id": 1}

        data = get_data(payload)
        if 'result' in data and "movies" in data['result']:

            if item.strm_path:              # If Item is from an episode
                filename = filetools.basename(item.strm_path)
                head, tail = filetools.split(filetools.split(item.strm_path)[0])
            else:                           # If Item is from the Series
                filename = filetools.basename(item.path)
                head, tail = filetools.split(filetools.split(item.path)[0])
            path = filetools.join(tail, filename)

            for d in data['result']['movies']:
                if d['file'].replace("/", "\\").endswith(path.replace("/", "\\")):
                    # logger.debug("I mark the movie as a view")
                    movieid = d['movieid']
                    break

        if movieid != 0:
            payload_f = {"jsonrpc": "2.0", "method": "VideoLibrary.SetMovieDetails", "params": {"movieid": movieid, "playcount": value}, "id": 1}

    else:  # item.contentType != 'movie'
        episodeid = 0
        payload = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes",
                   "params": {"properties": ["title", "playcount", "showtitle", "file", "tvshowid"]},
                   "id": 1}

        data = get_data(payload)
        if 'result' in data and "episodes" in data['result']:

            if item.strm_path:              # If Item is from an episode
                filename = filetools.basename(item.strm_path)
                head, tail = filetools.split(filetools.split(item.strm_path)[0])
            else:                           # If Item is from the Series
                filename = filetools.basename(item.path)
                head, tail = filetools.split(filetools.split(item.path)[0])
            path = filetools.join(tail, filename)

            for d in data['result']['episodes']:
                if d['file'].replace("/", "\\").endswith(path.replace("/", "\\")):
                    # logger.debug("I mark the episode as seen")
                    episodeid = d['episodeid']
                    break

        if episodeid != 0:
            payload_f = {"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails", "params": {"episodeid": episodeid, "playcount": value}, "id": 1}

    if payload_f:
        # Mark as seen
        data = get_data(payload_f)
        # logger.debug(str(data))
        if data['result'] != 'OK':
            logger.error("ERROR putting content as viewed")


def mark_season_as_watched_on_kodi(item, value=1):
    """
        mark the entire season as seen or unseen in the Kodi library
        @type item: item
        @param item: element to mark
        @type value: int
        @param value: > 0 for seen, 0 for not seen
        """
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))

    # We can only mark the season as seen in the Kodi database if the database is local, in case of sharing database this functionality will not work
    if config.get_setting("db_mode", "videolibrary"):
        return

    if value == 0:
        value = 'Null'

    request_season = ''
    if item.contentSeason > -1:
        request_season = ' and c12= %s' % item.contentSeason

    tvshows_path = filetools.join(config.get_videolibrary_path(), config.get_setting("folder_tvshows"))
    item_path1 = "%" + item.path.replace("\\\\", "\\").replace(tvshows_path, "")
    if item_path1[:-1] != "\\":
        item_path1 += "\\"
    item_path2 = item_path1.replace("\\", "/")

    sql = 'update files set playCount= %s where idFile in (select idfile from episode_view where (strPath like "%s" or strPath like "%s")%s)' % (value, item_path1, item_path2, request_season)

    execute_sql_kodi(sql)

def set_watched_on_addon(data):
    from specials import videolibrary
    from core import videolibrarytools
    data = jsontools.load(data)
    Type = data.get('item', {}).get('type','')
    ID = data.get('item', {}).get('id','')
    if not Type or not ID:
        return
    playcount = data.get('playcount',0)
    for Type in ['movie', 'episode']:
        sql = 'select strFileName, strPath, uniqueid_value from %s_view where (id%s like "%s")' % (Type, Type.capitalize(), ID)
        n, records = execute_sql_kodi(sql)
        if records:
            for filename, path, uniqueid_value in records:
                if Type in ['movie']:
                    title = filename.replace('.strm', ' [' + uniqueid_value + ']')
                    filename = title +'.nfo'
                else:
                    title = filename.replace('.strm', '')
                    filename = 'tvshow.nfo'

                path = filetools.join(path, filename)
                if filetools.exists(path):
                    head_nfo, item = videolibrarytools.read_nfo(path)
                    if item.library_playcounts:
                        item.library_playcounts.update({title: playcount})
                    else:
                        item.library_playcounts = {title: playcount}
                    filetools.write(path, head_nfo + item.tojson())

                    if item.infoLabels['mediatype'] == "tvshow":
                        for season in item.library_playcounts:
                            if "season" in season:
                                season_num = int(scrapertools.find_single_match(season, r'season (\d+)'))
                                item = videolibrary.check_season_playcount(item, season_num)
                                filetools.write(path, head_nfo + item.tojson())

def mark_content_as_watched_on_addon(path):
    from specials import videolibrary
    from core import videolibrarytools

    """
        mark the entire series or movie as viewed or unseen in the Alpha Video Library based on their status in the Kodi Video Library
        @type str: path
        @param path: content folder to mark
        """
    logger.debug()
    #logger.debug("path: " + path)

    FOLDER_MOVIES = config.get_setting("folder_movies")
    FOLDER_TVSHOWS = config.get_setting("folder_tvshows")
    VIDEOLIBRARY_PATH = config.get_videolibrary_config_path()
    if not VIDEOLIBRARY_PATH:
        return

    # We can only mark the content as a view in the Kodi database if the database is local, in case of sharing database this functionality will not work
    # if config.get_setting("db_mode", "videolibrary"):
    #    return

    path2 = ''
    if "special://" in VIDEOLIBRARY_PATH:
        if FOLDER_TVSHOWS in path:
            path2 = re. sub(r'.*?%s' % FOLDER_TVSHOWS, filetools.join(VIDEOLIBRARY_PATH, FOLDER_TVSHOWS), path).replace("\\", "/")
        if FOLDER_MOVIES in path:
            path2 = re. sub(r'.*?%s' % FOLDER_MOVIES, filetools.join(VIDEOLIBRARY_PATH, FOLDER_MOVIES), path).replace("\\", "/")

    if "\\" in path:
        path = path.replace("/", "\\")
    head_nfo, item = videolibrarytools.read_nfo(path)                   # I read the content .nfo
    old = item.clone()
    if not item:
        logger.error('.NFO not found: ' + path)
        return

    if FOLDER_TVSHOWS in path:                                          # I check if it is CINEMA or SERIES
        contentType = "episode_view"                                    # I mark the Kodi Video BBDD table
        nfo_name = "tvshow.nfo"                                         # I build the name of the .nfo
        path1 = path.replace("\\\\", "\\").replace(nfo_name, '')        # for SQL I just need the folder
        if not path2:
            path2 = path1.replace("\\", "/")                            # Format no Windows
        else:
            path2 = path2.replace(nfo_name, '')

    else:
        contentType = "movie_view"                                      # I mark the Kodi Video BBDD table
        path1 = path.replace("\\\\", "\\")                              # Windows format
        if not path2:
            path2 = path1.replace("\\", "/")                            # Format no Windows
        nfo_name = scrapertools.find_single_match(path2, r'\]\/(.*?)$')  # I build the name of the .nfo
        path1 = path1.replace(nfo_name, '')                             # for SQL I just need the folder
        path2 = path2.replace(nfo_name, '')                             # for SQL I just need the folder
    path2 = filetools.remove_smb_credential(path2)                      # If the file is on an SMB server, we remove the credentials

    # Let's execute the SQL statement
    sql = 'select strFileName, playCount from %s where (strPath like "%s" or strPath like "%s")' % (contentType, path1, path2)
    nun_records = 0
    records = None
    nun_records, records = execute_sql_kodi(sql)                        # SQL execution
    if nun_records == 0:                                                # is there an error?
        logger.error("SQL error: " + sql + ": 0 registros")
        return                                                          # we quit: either it is not cataloged in Kodi, or there is an error in the SQL

    for title, playCount in records:                                    # Now we go through all the records obtained
        if contentType == "episode_view":
            title_plain = title.replace('.strm', '')                    # If it is Serial, we remove the suffix .strm
        else:
            title_plain = scrapertools.find_single_match(item.strm_path, r'.(.*?\s\[.*?\])') # if it's a movie, we remove the title
        if playCount is None or playCount == 0:                         # not yet seen, we set it to 0
            playCount_final = 0
        elif playCount >= 1:
            playCount_final = 1

        elif not PY3 and isinstance(title_plain, (str, unicode)):
            title_plain = title_plain.decode("utf-8").encode("utf-8")   # We do this because if it doesn't generate this: u'title_plain '
        elif PY3 and isinstance(title_plain, bytes):
            title_plain = title_plain.decode('utf-8')
        item.library_playcounts.update({title_plain: playCount_final})  # update the .nfo playCount

    if item.infoLabels['mediatype'] == "tvshow":                        # We update the Season and Series playCounts
        for season in item.library_playcounts:
            if "season" in season:                                      # we look for the tags "season" inside playCounts
                season_num = int(scrapertools.find_single_match(season, r'season (\d+)'))    # we save the season number
                item = videolibrary.check_season_playcount(item, season_num)    # We call the method that updates Temps. and series
    if item.library_playcounts != old.library_playcounts:
        logger.debug('scrivo')
        filetools.write(path, head_nfo + item.tojson())

    #logger.debug(item)


def get_data(payload):
    """
    get the information of the JSON-RPC call with the information passed in payload
    @type payload: dict
    @param payload: data
    :return:
    """
    try:
        import urllib.request as urllib
    except ImportError:
        import urllib
    logger.debug("payload: %s" % payload)
    # Required header for XBMC JSON-RPC calls, otherwise you'll get a 415 HTTP response code - Unsupported media type
    headers = {'content-type': 'application/json'}

    if config.get_setting("db_mode", "videolibrary"):
        try:
            try:
                xbmc_port = config.get_setting("xbmc_puerto", "videolibrary")
            except:
                xbmc_port = 0

            xbmc_json_rpc_url = "http://" + config.get_setting("xbmc_host", "videolibrary") + ":" + str(xbmc_port) + "/jsonrpc"
            req = urllib2.Request(xbmc_json_rpc_url, data=jsontools.dump(payload), headers=headers)
            f = urllib.urlopen(req)
            response = f.read()
            f.close()

            logger.debug("get_data: response %s" % response)
            data = jsontools.load(response)
        except Exception as ex:
            template = "An exception of type %s occured. Arguments:\n%r"
            message = template % (type(ex).__name__, ex.args)
            logger.error("error en xbmc_json_rpc_url: %s" % message)
            data = ["error"]
    else:
        try:
            data = jsontools.load(xbmc.executeJSONRPC(jsontools.dump(payload)))
        except Exception as ex:
            template = "An exception of type %s occured. Arguments:\n%r"
            message = template % (type(ex).__name__, ex.args)
            logger.error("error en xbmc.executeJSONRPC: %s" % message)
            data = ["error"]

    logger.debug("data: %s" % data)

    return data


def update(folder_content=config.get_setting("folder_tvshows"), folder=""):
    """
    Update the library depending on the type of content and the path passed to it.

    @type folder_content: str
    @param folder_content: type of content to update, series or movies
    @type folder: str
    @param folder: name of the folder to scan.
    """
    logger.debug(folder)

    payload = {
        "jsonrpc": "2.0",
        "method": "VideoLibrary.Scan",
        "id": 1
    }

    if folder:
        folder = str(folder)
        videolibrarypath = config.get_videolibrary_config_path()

        if folder.endswith('/') or folder.endswith('\\'):
            folder = folder[:-1]

        update_path = None

        if videolibrarypath.startswith("special:"):
            if videolibrarypath.endswith('/'):
                videolibrarypath = videolibrarypath[:-1]
            update_path = videolibrarypath + "/" + folder_content + "/" + folder + "/"
        else:
            # update_path = filetools.join(videolibrarypath, folder_content, folder) + "/"   # Encoder problems in "folder"
            update_path = filetools.join(videolibrarypath, folder_content, ' ').rstrip()

        if videolibrarypath.startswith("special:") or not scrapertools.find_single_match(update_path, r'(^\w+:\/\/)'):
            payload["params"] = {"directory": update_path}

    while xbmc.getCondVisibility('Library.IsScanningVideo()'):
        xbmc.sleep(500)

    data = get_data(payload)


def search_library_path():
    sql = 'SELECT strPath FROM path WHERE strPath LIKE "special://%/plugin.video.s4me/library/" AND idParentPath ISNULL'
    nun_records, records = execute_sql_kodi(sql)
    if nun_records >= 1:
        logger.debug(records[0][0])
        return records[0][0]
    return None


def search_local_path(item):
    ids = [item.infoLabels['imdb_id'], item.infoLabels['tmdb_id'], item.infoLabels['tvdb_id']]
    for Id in ids:
        nun_ids, ids = execute_sql_kodi('SELECT idShow FROM tvshow_view WHERE uniqueid_value LIKE "%s"' % Id)
        if nun_ids >= 1:
            nun_records, records = execute_sql_kodi('SELECT idPath FROM tvshowlinkpath WHERE idShow LIKE "%s"' % ids[0][0])
            if nun_records >= 1:
                for record in records:
                    num_path, path_records = execute_sql_kodi('SELECT strPath FROM path WHERE idPath LIKE "%s"' % record[0])
                    for path in path_records:
                        if config.get_setting('videolibrarypath') not in path[0]:
                            return path[0]
    return ''


def set_content(content_type, silent=False, custom=False):
    """
    Procedure to auto-configure the kodi video library with the default values
    @type content_type: str ('movie' o 'tvshow')
    @param content_type: content type to configure, series or movies
    """
    logger.debug()
    continuar = True
    msg_text = ""
    videolibrarypath = config.get_setting("videolibrarypath")

    scraper = []
    values = []
    # from core.support import dbg;dbg()
    rpc = '{ "jsonrpc": "2.0", "method": "Addons.GetAddons","params":{"type":"xbmc.metadata.scraper.' + content_type + 's", "properties":["name"]}, "id": "1"}'
    response = jsontools.load(xbmc.executeJSONRPC(rpc))['result']['addons']
    for r in response:
        scraper.append(r['name'])
        values.append(r['addonid'])
    if not custom:
        if content_type == 'movie':
            if PY3:
                seleccion = values.index('metadata.themoviedb.org.python')
            else:
                seleccion = values.index('metadata.themoviedb.org')
        else:
            seleccion = values.index('metadata.tvshows.themoviedb.org.python')
    else:
        seleccion = platformtools.dialog_select(config.get_localized_string(70094 if content_type == 'movie' else 70107), scraper)

    # Configure scraper
    if seleccion != -1:
        xbmc.executebuiltin('Addon.OpenSettings({})'.format(values[seleccion]), True)
    else:
        continuar = False



    idPath = 0
    idParentPath = 0
    if continuar:
        continuar = False

        # We look for the idPath
        sql = 'SELECT MAX(idPath) FROM path'
        nun_records, records = execute_sql_kodi(sql)
        if nun_records == 1:
            idPath = records[0][0] + 1

        sql_videolibrarypath = videolibrarypath
        if sql_videolibrarypath.startswith("special://"):
            sql_videolibrarypath = sql_videolibrarypath.replace('/profile/', '/%/').replace('/home/userdata/', '/%/')
            sep = '/'
        elif scrapertools.find_single_match(sql_videolibrarypath, r'(^\w+:\/\/)'):
            sep = '/'
        else:
            sep = os.sep

        if not sql_videolibrarypath.endswith(sep):
            sql_videolibrarypath += sep

        # We are looking for the idParentPath
        sql = 'SELECT idPath, strPath FROM path where strPath LIKE "%s"' % sql_videolibrarypath
        nun_records, records = execute_sql_kodi(sql)
        if nun_records == 1:
            idParentPath = records[0][0]
            videolibrarypath = records[0][1][:-1]
            continuar = True
        else:
            # There is no videolibrarypath in the DB: we insert it
            sql_videolibrarypath = videolibrarypath
            if not sql_videolibrarypath.endswith(sep):
                sql_videolibrarypath += sep

            sql = 'INSERT INTO path (idPath, strPath,  scanRecursive, useFolderNames, noUpdate, exclude) VALUES ' \
                  '(%s, "%s", 0, 0, 0, 0)' % (idPath, sql_videolibrarypath)
            nun_records, records = execute_sql_kodi(sql)
            if nun_records == 1:
                continuar = True
                idParentPath = idPath
                idPath += 1
            else:
                msg_text = config.get_localized_string(70101)

    if continuar:
        continuar = False

        # We set strContent, strScraper, scanRecursive and strSettings
        if content_type == 'movie':
            strContent = 'movies'
            scanRecursive = 2147483647
            strScraper = values[seleccion]
            path_settings = xbmc.translatePath("special://profile/addon_data/{}/settings.xml".format(strScraper))
            if not os.path.exists(path_settings):
                logger.debug("%s: %s" % (content_type, path_settings + " doesn't exist"))
                return continuar
            settings_data = filetools.read(path_settings)
            strSettings = ' '.join(settings_data.split()).replace("> <", "><")
            strSettings = strSettings.replace("\"","\'")
            strActualizar = "Do you want to set this Scraper in Spanish as the default option for movies?"
            if not videolibrarypath.endswith(sep):
                videolibrarypath += sep
            strPath = videolibrarypath + config.get_setting("folder_movies") + sep
        else:
            strContent = 'tvshows'
            scanRecursive = 0
            strScraper = values[seleccion]
            path_settings = xbmc.translatePath("special://profile/addon_data/{}/settings.xml".format(strScraper))
            if not os.path.exists(path_settings):
                logger.debug("%s: %s" % (content_type, path_settings + " doesn't exist"))
                return continuar
            settings_data = filetools.read(path_settings)
            strSettings = ' '.join(settings_data.split()).replace("> <", "><")
            strSettings = strSettings.replace("\"","\'")
            strActualizar = "Do you want to configure this Scraper in Spanish as a default option for series?"
            if not videolibrarypath.endswith(sep):
                videolibrarypath += sep
            strPath = videolibrarypath + config.get_setting("folder_tvshows") + sep

        logger.debug("%s: %s" % (content_type, strPath))
        # We check if strPath already exists in the DB to avoid duplicates
        sql = 'SELECT idPath FROM path where strPath="%s"' % strPath
        nun_records, records = execute_sql_kodi(sql)
        sql = ""
        if nun_records == 0:
            # Insertamos el scraper
            sql = 'INSERT INTO path (idPath, strPath, strContent, strScraper, scanRecursive, useFolderNames, ' \
                  'strSettings, noUpdate, exclude, idParentPath) VALUES (%s, "%s", "%s", "%s", %s, 0, ' \
                  '"%s", 0, 0, %s)' % (
                      idPath, strPath, strContent, strScraper, scanRecursive, strSettings, idParentPath)
        else:
            if not silent:
                # Preguntar si queremos configurar themoviedb.org como opcion por defecto
                actualizar = platformtools.dialog_yesno(config.get_localized_string(70098), strActualizar)
            else:
                actualizar = True

            if actualizar:
                # Actualizamos el scraper
                idPath = records[0][0]
                sql = 'UPDATE path SET strContent="%s", strScraper="%s", scanRecursive=%s, strSettings="%s" ' \
                      'WHERE idPath=%s' % (strContent, strScraper, scanRecursive, strSettings, idPath)

        if sql:
            nun_records, records = execute_sql_kodi(sql)
            if nun_records == 1:
                continuar = True

        if not continuar:
            msg_text = config.get_localized_string(60055)

    if not continuar:
        heading = config.get_localized_string(70102) % content_type
    elif content_type == 'tvshow' and not xbmc.getCondVisibility(
            'System.HasAddon(metadata.tvshows.themoviedb.org)'):
        heading = config.get_localized_string(70103) % content_type
        msg_text = config.get_localized_string(60058)
    else:
        heading = config.get_localized_string(70103) % content_type
        msg_text = config.get_localized_string(70104)

    logger.debug("%s: %s" % (heading, msg_text))
    return continuar


def update_db(old_path, new_path, old_movies_folder, new_movies_folder, old_tvshows_folder, new_tvshows_folder, progress):
    def path_replace(path, old, new):

        logger.debug()
        logger.debug('path: ' + path + ', old: ' + old + ', new: ' + new)

        if new.startswith("special://") or '://' in new: sep = '/'
        else: sep = os.sep

        path = path.replace(old,new)
        if sep == '/': path = path.replace('\\','/')
        else: path = path.replace('/','\\')

        return path

    logger.debug()

    sql_old_path = old_path
    if sql_old_path.startswith("special://"):
        sql_old_path = sql_old_path.replace('/profile/', '/%/').replace('/home/userdata/', '/%/')
        sep = '/'
    elif '://' in sql_old_path:
        sep = '/'
    else: sep = os.sep
    if not sql_old_path.endswith(sep):
        sql_old_path += sep

    logger.debug('sql_old_path: ' + sql_old_path)
    # search MAIN path in the DB
    sql = 'SELECT idPath, strPath FROM path where strPath LIKE "%s"' % sql_old_path
    logger.debug('sql: ' + sql)
    nun_records, records = execute_sql_kodi(sql)

    # change main path
    if records:
        idPath = records[0][0]
        strPath = path_replace(records[0][1], old_path, new_path)
        sql = 'UPDATE path SET strPath="%s" WHERE idPath=%s' % (strPath, idPath)
        logger.debug('sql: ' + sql)
        nun_records, records = execute_sql_kodi(sql)
    else:
        progress.update(100)
        xbmc.sleep(1000)
        progress.close()
        return

    p = 80
    progress.update(p, config.get_localized_string(20000), config.get_localized_string(80013))

    for OldFolder, NewFolder in [[old_movies_folder, new_movies_folder], [old_tvshows_folder, new_tvshows_folder]]:
        sql_old_folder = sql_old_path + OldFolder
        if not sql_old_folder.endswith(sep): sql_old_folder += sep

        # Search Main Sub Folder
        sql = 'SELECT idPath, strPath FROM path where strPath LIKE "%s"' % sql_old_folder
        logger.debug('sql: ' + sql)
        nun_records, records = execute_sql_kodi(sql)

        # Change Main Sub Folder
        if records:
            for record in records:
                idPath = record[0]
                strPath = path_replace(record[1], filetools.join(old_path, OldFolder), filetools.join(new_path, NewFolder))
                sql = 'UPDATE path SET strPath="%s" WHERE idPath=%s' % (strPath, idPath)
                logger.debug('sql: ' + sql)
                nun_records, records = execute_sql_kodi(sql)

        # Search if Sub Folder exixt in all paths
        sql_old_folder += '%'
        sql = 'SELECT idPath, strPath FROM path where strPath LIKE "%s"' % sql_old_folder
        logger.debug('sql: ' + sql)
        nun_records, records = execute_sql_kodi(sql)

        #Change Sub Folder in all paths
        if records:
            for record in records:
                idPath = record[0]
                strPath = path_replace(record[1], filetools.join(old_path, OldFolder), filetools.join(new_path, NewFolder))
                sql = 'UPDATE path SET strPath="%s" WHERE idPath=%s' % (strPath, idPath)
                logger.debug('sql: ' + sql)
                nun_records, records = execute_sql_kodi(sql)


        if OldFolder == old_movies_folder:
            # if is Movie Folder
            # search and modify in "movie"
            sql = 'SELECT idMovie, c22 FROM movie where c22 LIKE "%s"' % sql_old_folder
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            if records:
                for record in records:
                    idMovie = record[0]
                    strPath = path_replace(record[1], filetools.join(old_path, OldFolder), filetools.join(new_path, NewFolder))
                    sql = 'UPDATE movie SET c22="%s" WHERE idMovie=%s' % (strPath, idMovie)
                    logger.debug('sql: ' + sql)
                    nun_records, records = execute_sql_kodi(sql)
        else:
            # if is TV Show Folder
            # search and modify in "episode"
            sql = 'SELECT idEpisode, c18 FROM episode where c18 LIKE "%s"' % sql_old_folder
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            if records:
                for record in records:
                    idEpisode = record[0]
                    strPath = path_replace(record[1], filetools.join(old_path, OldFolder), filetools.join(new_path, NewFolder))
                    sql = 'UPDATE episode SET c18="%s" WHERE idEpisode=%s' % (strPath, idEpisode)
                    logger.debug('sql: ' + sql)
                    nun_records, records = execute_sql_kodi(sql)
        p += 5
        progress.update(p, config.get_localized_string(20000), config.get_localized_string(80013))

    progress.update(100)
    xbmc.sleep(1000)
    progress.close()
    xbmc.executebuiltin('ReloadSkin()')


def clean(path_list=[]):
    def sql_format(path):
        if path.startswith("special://"):
            path = path.replace('/profile/', '/%/').replace('/home/userdata/', '/%/')
            sep = '/'
        elif '://' in path or path.startswith('/') or path.startswith('%/'):
            sep = '/'
        else: sep = os.sep

        if sep == '/': path = path.replace('\\','/')
        else: path = path.replace('/','\\')

        return path, sep

    logger.debug()

    progress = platformtools.dialog_progress_bg(config.get_localized_string(20000), config.get_localized_string(80025))
    progress.update(0)

    # if the path list is empty, clean the entire video library
    if not path_list:
        logger.debug('the path list is empty, clean the entire video library')
        if not config.get_setting("videolibrary_kodi"):
            sql_path, sep = sql_format(config.get_setting("videolibrarypath"))
            if not sql_path.endswith(sep): sql_path += sep
            sql = 'SELECT idPath FROM path where strPath LIKE "%s"' % sql_path
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            if records:
                idPath = records[0][0]
                sql = 'DELETE from path WHERE idPath=%s' % idPath
                logger.debug('sql: ' + sql)
                nun_records, records = execute_sql_kodi(sql)
                sql = 'DELETE from path WHERE idParentPath=%s' % idPath
                logger.debug('sql: ' + sql)
                nun_records, records = execute_sql_kodi(sql)

        from core import videolibrarytools
        for path, folders, files in filetools.walk(videolibrarytools.MOVIES_PATH):
            for folder in folders:
                path_list.append(filetools.join(config.get_setting("videolibrarypath"), videolibrarytools.FOLDER_MOVIES, folder))

        for path, folders, files in filetools.walk(videolibrarytools.TVSHOWS_PATH):
            for folder in folders:
                tvshow_nfo = filetools.join(path, folder, "tvshow.nfo")
                if filetools.exists(tvshow_nfo):
                    path_list.append(filetools.join(config.get_setting("videolibrarypath"), videolibrarytools.FOLDER_TVSHOWS, folder))

    logger.debug('path_list: ' + str(path_list))
    if path_list: t = float(100) / len(path_list)
    for i, path in enumerate(path_list):
        progress.update(int(math.ceil((i + 1) * t)))

        if not path:
            continue

        sql_path, sep = sql_format(path)
        if filetools.isdir(path) and not sql_path.endswith(sep): sql_path += sep
        logger.debug('path: ' + path)
        logger.debug('sql_path: ' + sql_path)

        if filetools.isdir(path):
            # search movie in the DB
            sql = 'SELECT idMovie FROM movie where c22 LIKE "%s"' % (sql_path + '%')
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            # delete movie
            if records:
                payload = {"jsonrpc": "2.0", "method": "VideoLibrary.RemoveMovie", "id": 1, "params": {"movieid": records[0][0]}}
                data = get_data(payload)
                continue
            # search TV show in the DB
            sql = 'SELECT idShow FROM tvshow_view where strPath LIKE "%s"' % sql_path
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            # delete TV show
            if records:
                payload = {"jsonrpc": "2.0", "method": "VideoLibrary.RemoveTVShow", "id": 1, "params": {"tvshowid": records[0][0]}}
                data = get_data(payload)
        elif config.get_setting("folder_movies") in sql_path:
            # search movie in the DB
            sql = 'SELECT idMovie FROM movie where c22 LIKE "%s"' % sql_path
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            # delete movie
            if records:
                payload = {"jsonrpc": "2.0", "method": "VideoLibrary.RemoveMovie", "id": 1, "params": {"movieid": records[0][0]}}
                data = get_data(payload)
        else:
            # search episode in the DB
            sql = 'SELECT idEpisode FROM episode where c18 LIKE "%s"' % sql_path
            logger.debug('sql: ' + sql)
            nun_records, records = execute_sql_kodi(sql)
            # delete episode
            if records:
                payload = {"jsonrpc": "2.0", "method": "VideoLibrary.RemoveEpisode", "id": 1, "params": {"episodeid": records[0][0]}}
                data = get_data(payload)

    progress.update(100)
    xbmc.sleep(1000)
    progress.close()


def check_db(code):
    path_list = []
    for _id in code:
        sql = 'SELECT strPath FROM tvshow_view where uniqueid_value = "%s"' % _id.replace('tmdb_','').replace('tvdb_','')
        logger.debug('sql: ' + sql)
        nun_records, records = execute_sql_kodi(sql)
        if records:
            path_list += [xbmc.translatePath(r[0]) for r in records]
    return path_list


def execute_sql_kodi(sql):
    """
    Run sql query against kodi database
    @param sql: Valid sql query
    @type sql: str
    @return: Number of records modified or returned by the query
    @rtype nun_records: int
    @return: list with the query result
    @rtype records: list of tuples
    """
    logger.debug()
    file_db = ""
    nun_records = 0
    records = None

    # We look for the archive of the video database according to the version of kodi
    video_db = config.get_platform(True)['video_db']
    if video_db:
        file_db = filetools.join(xbmc.translatePath("special://userdata/Database"), video_db)

    # alternative method to locate the database
    if not file_db or not filetools.exists(file_db):
        file_db = ""
        for f in filetools.listdir(xbmc.translatePath("special://userdata/Database")):
            path_f = filetools.join(xbmc.translatePath("special://userdata/Database"), f)

            if filetools.isfile(path_f) and f.lower().startswith('myvideos') and f.lower().endswith('.db'):
                file_db = path_f
                break

    if file_db:
        logger.debug("DB file: %s" % file_db)
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(file_db)
            cursor = conn.cursor()

            logger.debug("Running sql: %s" % sql)
            cursor.execute(sql)
            conn.commit()

            records = cursor.fetchall()
            if sql.lower().startswith("select"):
                nun_records = len(records)
                if nun_records == 1 and records[0][0] is None:
                    nun_records = 0
                    records = []
            else:
                nun_records = conn.total_changes

            conn.close()
            logger.debug("Query executed. Records: %s" % nun_records)

        except:
            logger.error("Error executing sql query")
            if conn:
                conn.close()

    else:
        logger.debug("Database not found")

    return nun_records, records


def check_sources(new_movies_path='', new_tvshows_path=''):
    def format_path(path):
        if path.startswith("special://") or '://' in path: sep = '/'
        else: sep = os.sep
        if not path.endswith(sep): path += sep
        return path

    logger.debug()

    new_movies_path = format_path(new_movies_path)
    new_tvshows_path = format_path(new_tvshows_path)

    SOURCES_PATH = xbmc.translatePath("special://userdata/sources.xml")
    if filetools.isfile(SOURCES_PATH):
        xmldoc = minidom.parse(SOURCES_PATH)

        video_node = xmldoc.childNodes[0].getElementsByTagName("video")[0]
        paths_node = video_node.getElementsByTagName("path")
        list_path = [p.firstChild.data for p in paths_node]

        return new_movies_path in list_path, new_tvshows_path in list_path
    else:
        xmldoc = minidom.Document()
        source_nodes = xmldoc.createElement("sources")

        for type in ['programs', 'video', 'music', 'picture', 'files']:
            nodo_type = xmldoc.createElement(type)
            element_default = xmldoc.createElement("default")
            element_default.setAttribute("pathversion", "1")
            nodo_type.appendChild(element_default)
            source_nodes.appendChild(nodo_type)
        xmldoc.appendChild(source_nodes)

        return False, False


def update_sources(new='', old=''):
    if new == old: return

    SOURCES_PATH = xbmc.translatePath("special://userdata/sources.xml")
    if filetools.isfile(SOURCES_PATH):
        xmldoc = minidom.parse(SOURCES_PATH)
    else:
        xmldoc = minidom.Document()
        source_nodes = xmldoc.createElement("sources")

        for type in ['programs', 'video', 'music', 'picture', 'files']:
            nodo_type = xmldoc.createElement(type)
            element_default = xmldoc.createElement("default")
            element_default.setAttribute("pathversion", "1")
            nodo_type.appendChild(element_default)
            source_nodes.appendChild(nodo_type)
        xmldoc.appendChild(source_nodes)

    # collect nodes
    # nodes = xmldoc.getElementsByTagName("video")
    video_node = xmldoc.childNodes[0].getElementsByTagName("video")[0]
    paths_node = video_node.getElementsByTagName("path")

    if old:
        # delete old path
        for node in paths_node:
            if node.firstChild.data == old:
                parent = node.parentNode
                remove = parent.parentNode
                remove.removeChild(parent)

        # write changes
        if sys.version_info[0] >= 3: #PY3
            filetools.write(SOURCES_PATH, '\n'.join([x for x in xmldoc.toprettyxml().splitlines() if x.strip()]))
        else:
            filetools.write(SOURCES_PATH, '\n'.join([x for x in xmldoc.toprettyxml().splitlines() if x.strip()]), vfs=False)
        logger.debug("The path %s has been removed from sources.xml" % old)

    if new:
        # create new path
        list_path = [p.firstChild.data for p in paths_node]
        if new in list_path:
            logger.debug("The path %s already exists in sources.xml" % new)
            return
        logger.debug("The path %s does not exist in sources.xml" % new)

        # if the path does not exist we create one
        source_node = xmldoc.createElement("source")

        # <name> Node
        name_node = xmldoc.createElement("name")
        sep = os.sep
        if new.startswith("special://") or scrapertools.find_single_match(new, r'(^\w+:\/\/)'):
            sep = "/"
        name = new
        if new.endswith(sep):
            name = new[:-1]
        name_node.appendChild(xmldoc.createTextNode(name.rsplit(sep)[-1]+ '-' + config.PLUGIN_NAME))
        source_node.appendChild(name_node)

        # <path> Node
        path_node = xmldoc.createElement("path")
        path_node.setAttribute("pathversion", "1")
        path_node.appendChild(xmldoc.createTextNode(new))
        source_node.appendChild(path_node)

        # <allowsharing> Node
        allowsharing_node = xmldoc.createElement("allowsharing")
        allowsharing_node.appendChild(xmldoc.createTextNode('true'))
        source_node.appendChild(allowsharing_node)

        # Añadimos <source>  a <video>
        video_node.appendChild(source_node)

        # write changes
        if sys.version_info[0] >= 3: #PY3
            filetools.write(SOURCES_PATH, '\n'.join([x for x in xmldoc.toprettyxml().splitlines() if x.strip()]))
        else:
            filetools.write(SOURCES_PATH, '\n'.join([x for x in xmldoc.toprettyxml().splitlines() if x.strip()]), vfs=False)
        logger.debug("The path %s has been added to sources.xml" % new)


def ask_set_content(silent=False):
    # from core.support import dbg;dbg()
    logger.debug("videolibrary_kodi %s" % config.get_setting("videolibrary_kodi"))
    def do_config(custom=True):
        if set_content("movie", True, custom) and set_content("tvshow", True, custom):
            platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(70104))
            config.set_setting("videolibrary_kodi", True)
            from specials import videolibrary
            videolibrary.update_videolibrary()
            update()
        else:
            platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(80024))
            config.set_setting("videolibrary_kodi", False)

    # configuration during installation
    if not silent:
        # ask to configure Kodi video library
        if platformtools.dialog_yesno(config.get_localized_string(20000), config.get_localized_string(80015)):
            # ask for custom or default settings
            if not platformtools.dialog_yesno(config.get_localized_string(80026), config.get_localized_string(80016), config.get_localized_string(80017), config.get_localized_string(80018)):
                # input path and folders
                path = platformtools.dialog_browse(3, config.get_localized_string(80019), config.get_setting("videolibrarypath"))
                movies_folder = platformtools.dialog_input(config.get_setting("folder_movies"), config.get_localized_string(80020))
                tvshows_folder = platformtools.dialog_input(config.get_setting("folder_tvshows"), config.get_localized_string(80021))

                if path != "" and movies_folder != "" and tvshows_folder != "":
                    movies_path, tvshows_path = check_sources(filetools.join(path, movies_folder), filetools.join(path, tvshows_folder))
                    # configure later
                    if movies_path or tvshows_path:
                        platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(80029))
                    # set path and folders
                    else:
                        update_sources(path, config.get_setting("videolibrarypath"))
                        config.set_setting("videolibrarypath", path)
                        config.set_setting("folder_movies", movies_folder)
                        config.set_setting("folder_tvshows", tvshows_folder)
                        config.verify_directories_created()
                        do_config(False)
                # default path and folders
                else:
                    platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(80030))
                    do_config(False)
            # default settings
            else:
                platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(80027))
                do_config(False)
        # configure later
        else:
            platformtools.dialog_ok(config.get_localized_string(20000), config.get_localized_string(80022))
    # configuration from the settings menu
    else:
        platformtools.dialog_ok(config.get_localized_string(80026), config.get_localized_string(80023))
        do_config(True)


def next_ep(item):
    from core.item import Item
    logger.debug()
    item.next_ep = False

    # check if next file exist
    current_filename = filetools.basename(item.strm_path).replace('.strm', '')
    base_path = filetools.basename(filetools.dirname(item.strm_path))
    path = filetools.join(config.get_videolibrary_path(), config.get_setting("folder_tvshows"),base_path)
    fileList = []
    for file in filetools.listdir(path):
        if file.endswith('.strm'):
            fileList.append(file.replace('.strm', ''))

    fileList.sort(key=lambda ep: (int(ep.split('x')[0]), int(ep.split('x')[1])))

    nextIndex = fileList.index(current_filename) + 1
    if nextIndex == 0 or nextIndex == len(fileList): next_file = None
    else: next_file = fileList[nextIndex] 
    logger.debug('Next File:' + str(next_file))

    # start next episode window afther x time
    if next_file:
        season = int(next_file.split('x')[0])
        episode = int(next_file.split('x')[1])
        # next_ep = '%sx%s' % (season, episode)
        item = Item(
            action= 'play_from_library',
            channel= 'videolibrary',
            contentEpisodeNumber= episode,
            contentSeason= season,
            contentTitle= next_file,
            contentType= 'episode',
            infoLabels= {'episode': episode, 'mediatype': 'episode', 'season': season, 'title': next_file},
            strm_path= filetools.join(base_path, next_file + '.strm'),
            play_from = item.play_from)

        global INFO
        INFO = filetools.join(path, next_file + '.nfo')
    else:
        item=None

    return item

class NextDialog(xbmcgui.WindowXMLDialog):
    item = None
    cancel = False
    EXIT = False
    continuewatching = True

    def __init__(self, *args, **kwargs):
        self.action_exitkeys_id = [xbmcgui.ACTION_STOP, xbmcgui.ACTION_BACKSPACE, xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK]
        self.progress_control = None

        # set info
        f = filetools.file_open(INFO, 'r')
        full_info = f.read().split('\n')
        full_info = full_info[1:]
        f.close()
        full_info = "".join(full_info)
        info = jsontools.load(full_info)
        info = info["infoLabels"]
        if "fanart" in info: img = info["fanart"]
        elif "thumbnail" in info: img = info["thumbnail"]
        else: img = filetools.join(config.get_runtime_path(), "resources", "noimage.png")
        self.setProperty("next_img", img)
        self.setProperty("title", info["tvshowtitle"])
        ep_title = '{}x{:02d}'.format(info['season'], info["episode"])
        if info.get("title",''):
            ep_title += ' - ' + info["title"]
        self.setProperty("ep_title", ep_title)
        self.show()

    def set_exit(self, EXIT):
        self.EXIT = EXIT

    def set_continue_watching(self, continuewatching):
        self.continuewatching = continuewatching

    def is_exit(self):
        return self.EXIT

    def onFocus(self, controlId):
        pass

    def doAction(self):
        pass

    def closeDialog(self):
        self.close()

    def onClick(self, controlId):
        if controlId == 3012:  # Still watching
            self.set_exit(True)
            self.set_continue_watching(True)
            self.close()
        elif controlId == 3013:  # Cancel
            self.set_exit(True)
            self.set_continue_watching(False)
            self.close()

    def onAction(self, action):
        if action in self.action_exitkeys_id:
            self.set_exit(True)
            self.set_continue_watching(False)
            self.close()
