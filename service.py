# -*- coding: utf-8 -*-
import ast
import datetime
import math
import os
import sys
import threading
import traceback
import xbmc

try:
    from urllib.parse import urlsplit
except ImportError:
    from urlparse import urlsplit
# on kodi 18 its xbmc.translatePath, on 19 xbmcvfs.translatePath
try:
    import xbmcvfs
    xbmc.translatePath = xbmcvfs.translatePath
except:
    pass
from platformcode import config
librerias = xbmc.translatePath(os.path.join(config.get_runtime_path(), 'lib'))
sys.path.insert(0, librerias)
os.environ['TMPDIR'] = config.get_temp_file('')

from core import videolibrarytools, filetools, channeltools, httptools, scrapertools, db
from lib import schedule
from platformcode import logger, platformtools, updater, xbmc_videolibrary
from specials import videolibrary
from servers import torrent

# if this service need to be reloaded because an update changed it
needsReload = False
# list of threads
threads = []


def update(path, p_dialog, i, t, serie, overwrite):
    logger.debug("Updating " + path)
    insertados_total = 0
    nfo_file = xbmc.translatePath(filetools.join(path, 'tvshow.nfo'))

    head_nfo, it = videolibrarytools.read_nfo(nfo_file)
    videolibrarytools.update_renumber_options(it, head_nfo, path)

    if not serie.library_urls: serie = it
    category = serie.category

    # logger.debug("%s: %s" %(serie.contentSerieName,str(list_canales) ))
    for channel, url in serie.library_urls.items():
        serie.channel = channel
        module = __import__('channels.%s' % channel, fromlist=["channels.%s" % channel])
        url = module.host + urlsplit(url).path
        serie.url = url

        try:
            head_nfo, it = videolibrarytools.read_nfo(nfo_file)         # Refresh the .nfo to collect updates
            if it.emergency_urls:
                serie.emergency_urls = it.emergency_urls
            serie.category = category
        except:
            logger.error(traceback.format_exc())

        channel_enabled = channeltools.is_enabled(serie.channel)

        if channel_enabled:

            heading = config.get_localized_string(20000)
            p_dialog.update(int(math.ceil((i + 1) * t)), heading, config.get_localized_string(60389) % (serie.contentSerieName, serie.channel.capitalize()))
            try:
                pathchannels = filetools.join(config.get_runtime_path(), "channels", serie.channel + '.py')
                logger.debug("loading channel: " + pathchannels + " " + serie.channel)

                if serie.library_filter_show:
                    serie.show = serie.library_filter_show.get(serie.channel, serie.contentSerieName)

                obj = __import__('channels.%s' % serie.channel, fromlist=[pathchannels])

                itemlist = obj.episodios(serie)

                try:
                    if int(overwrite) == 3:
                        # Overwrite all files (tvshow.nfo, 1x01.nfo, 1x01 [channel] .json, 1x01.strm, etc ...)
                        insertados, sobreescritos, fallidos, notusedpath = videolibrarytools.save_tvshow(serie, itemlist, override_active = True)
                        #serie= videolibrary.check_season_playcount(serie, serie.contentSeason)
                        #if filetools.write(path + '/tvshow.nfo', head_nfo + it.tojson()):
                        #    serie.infoLabels['playcount'] = serie.playcount
                    else:
                        insertados, sobreescritos, fallidos = videolibrarytools.save_episodes(path, itemlist, serie,
                                                                                              silent=True,
                                                                                              overwrite=overwrite)
                        #it = videolibrary.check_season_playcount(it, it.contentSeason)
                        #if filetools.write(path + '/tvshow.nfo', head_nfo + it.tojson()):
                        #    serie.infoLabels['playcount'] = serie.playcount
                    insertados_total += insertados

                except:
                    logger.error("Error when saving the chapters of the series")
                    logger.error(traceback.format_exc())

            except:
                logger.error("Error in obtaining the episodes of: %s" % serie.show)
                logger.error(traceback.format_exc())

        else:
            logger.debug("Channel %s not active is not updated" % serie.channel)
    # Synchronize the episodes seen from the Kodi video library with that of S4Me
    try:
        if config.is_xbmc():                # If it's Kodi, we do it
            from platformcode import xbmc_videolibrary
            xbmc_videolibrary.mark_content_as_watched_on_addon(filetools.join(path, 'tvshow.nfo'))
    except:
        logger.error(traceback.format_exc())

    return insertados_total > 0


def check_for_update(overwrite=True):
    logger.debug("Update Series...")
    p_dialog = None
    serie_actualizada = False
    update_when_finished = False
    hoy = datetime.date.today()
    estado_verify_playcount_series = False

    try:
        if overwrite or \
            config.get_setting("update", "videolibrary") in [4, 5] or \
            (config.get_setting("update", "videolibrary") not in [0, 4] and hoy.strftime('%Y-%m-%d') != config.get_setting('updatelibrary_last_check', 'videolibrary')):

            config.set_setting("updatelibrary_last_check", hoy.strftime('%Y-%m-%d'), "videolibrary")

            heading = config.get_localized_string(60601)
            p_dialog = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
            p_dialog.update(0, '')
            show_list = []
            # show_ep_num = []

            for path, folders, files in filetools.walk(videolibrarytools.TVSHOWS_PATH):
                if 'tvshow.nfo' in files:
                    show_list.extend([filetools.join(path, f) for f in files if f == "tvshow.nfo"])
                    # show_ep_num.append(len([f for f in files if f.endswith('.nfo') and f != 'tvshow.nfo']))

            if show_list:
                t = float(100) / len(show_list)

            for i, tvshow_file in enumerate(show_list):
                head_nfo, serie = videolibrarytools.read_nfo(tvshow_file)
                # ep_count = show_ep_num[i] + (len(serie.local_episodes_list) if serie.local_episodes_path else 0)
                # if serie.infoLabels['status'].lower() == 'ended' and \
                #         ep_count >= serie.infoLabels['number_of_episodes']:
                #     serie.active = 0
                #     filetools.write(tvshow_file, head_nfo + serie.tojson())
                path = filetools.dirname(tvshow_file)

                logger.debug("serie=" + serie.contentSerieName)

                # Check the status of the series.library_playcounts of the Series in case it is incomplete
                try:
                    estado = False
                    # If we have not done the verification or do not have a playcount, we enter
                    estado = config.get_setting("verify_playcount", "videolibrary")
                    if not estado or estado == False or not serie.library_playcounts:               # If it hasn't happened before, we do it now
                        serie, estado = videolibrary.verify_playcount_series(serie, path)           # Also happens if a PlayCount is missing completely
                except:
                    logger.error(traceback.format_exc())
                else:
                    if estado:                                                                      # If the update was successful ...
                        estado_verify_playcount_series = True                                       # ... is checked to change the Video Library option

                try:
                    interval = int(serie.active)  # Could be the bool type
                except:
                    interval = 1

                if not serie.active:
                    # if the series is not active discard
                    if not overwrite:
                        # Synchronize the episodes seen from the Kodi video library with that of Alpha, even if the series is deactivated
                        try:
                            if config.is_xbmc():                # If it's Kodi, we do it
                                from platformcode import xbmc_videolibrary
                                xbmc_videolibrary.mark_content_as_watched_on_addon(filetools.join(path, 'tvshow.nfo'))
                        except:
                            logger.error(traceback.format_exc())

                    continue

                p_dialog.update(int(math.ceil((i + 1) * t)), heading, serie.contentSerieName)

                # Obtain the update date and the next scheduled for this series
                update_next = serie.update_next
                if update_next:
                    y, m, d = update_next.split('-')
                    update_next = datetime.date(int(y), int(m), int(d))
                else:
                    update_next = hoy

                update_last = serie.update_last
                if update_last:
                    y, m, d = update_last.split('-')
                    update_last = datetime.date(int(y), int(m), int(d))
                else:
                    update_last = hoy

                # if the series is active ...
                if overwrite or config.get_setting("updatetvshows_interval", "videolibrary") == 0:
                    # ... force update regardless of interval
                    serie_actualizada = update(path, p_dialog, i, t, serie, overwrite)
                    if not serie_actualizada:
                        update_next = hoy + datetime.timedelta(days=interval)

                elif interval == 1 and update_next <= hoy:
                    # ...daily update
                    serie_actualizada = update(path, p_dialog, i, t, serie, overwrite)
                    if not serie_actualizada and update_last <= hoy - datetime.timedelta(days=7):
                        # if it hasn't been updated for a week, change the interval to weekly
                        interval = 7
                        update_next = hoy + datetime.timedelta(days=interval)

                elif interval == 7 and update_next <= hoy:
                    # ... weekly update
                    serie_actualizada = update(path, p_dialog, i, t, serie, overwrite)
                    if not serie_actualizada:
                        if update_last <= hoy - datetime.timedelta(days=14):
                            # if it has not been updated for 2 weeks, change the interval to monthly
                            interval = 30

                        update_next += datetime.timedelta(days=interval)

                elif interval == 30 and update_next <= hoy:
                    # ... monthly update
                    serie_actualizada = update(path, p_dialog, i, t, serie, overwrite)
                    if not serie_actualizada:
                        update_next += datetime.timedelta(days=interval)

                if serie_actualizada:
                    update_last = hoy
                    update_next = hoy + datetime.timedelta(days=interval)

                head_nfo, serie = videolibrarytools.read_nfo(tvshow_file)                       # Reread the .nfo, which has been modified
                if interval != int(serie.active) or update_next.strftime('%Y-%m-%d') != serie.update_next or update_last.strftime('%Y-%m-%d') != serie.update_last:
                    serie.update_last = update_last.strftime('%Y-%m-%d')
                    if update_next > hoy:
                        serie.update_next = update_next.strftime('%Y-%m-%d')
                    serie.active = interval
                    serie.channel = "videolibrary"
                    serie.action = "get_seasons"
                    filetools.write(tvshow_file, head_nfo + serie.tojson())

                if serie_actualizada:
                    if config.get_setting("search_new_content", "videolibrary") == 0:
                        # We update the Kodi video library: Find content in the series folder
                        if config.is_xbmc() and config.get_setting("videolibrary_kodi"):
                            from platformcode import xbmc_videolibrary
                            xbmc_videolibrary.update(folder=filetools.basename(path))
                    else:
                        update_when_finished = True

            if estado_verify_playcount_series:                                                  # If any playcount has been changed, ...
                estado = config.set_setting("verify_playcount", True, "videolibrary")           # ... we update the Videolibrary option

            if config.get_setting("search_new_content", "videolibrary") == 1 and update_when_finished:
                # We update the Kodi video library: Find content in all series
                if config.is_xbmc() and config.get_setting("videolibrary_kodi"):
                    from platformcode import xbmc_videolibrary
                    xbmc_videolibrary.update()

            p_dialog.close()

        else:
            logger.debug("Not update the video library, it is disabled")

    except Exception as ex:
        logger.error("An error occurred while updating the series")
        template = "An exception of type %s occured. Arguments:\n%r"
        message = template % (type(ex).__name__, ex.args)
        logger.error(message)

        if p_dialog:
            p_dialog.close()

    from core.item import Item
    item_dummy = Item()
    videolibrary.list_movies(item_dummy, silent=True)

    if config.get_setting('trakt_sync'):
        from core import trakt_tools
        trakt_tools.update_all()


def updaterCheck():
    global needsReload
    # updater check
    updated, needsReload = updater.check(background=True)


def get_ua_list():
    # https://github.com/alfa-addon/addon/blob/master/plugin.video.alfa/platformcode/updater.py#L273
    logger.info()
    url = "https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Windows&num=6&offset=0"

    try:
        current_ver = config.get_setting("chrome_ua_version", default="").split(".")
        data = httptools.downloadpage(url, alfa_s=True, ignore_response_code=True).data

        data = ast.literal_eval(data)
        new_ua_ver = data[0].get('version', '') if data and isinstance(data, list) else ''
        if not new_ua_ver:
            return

        if not current_ver:
            config.set_setting("chrome_ua_version", new_ua_ver)
        else:
            for pos, val in enumerate(new_ua_ver.split('.')):
                if int(val) > int(current_ver[pos]):
                    config.set_setting("chrome_ua_version", new_ua_ver)
                    break
    except:
        logger.error(traceback.format_exc())


def run_threaded(job_func, args):
    job_thread = threading.Thread(target=job_func, args=args)
    job_thread.start()
    threads.append(job_thread)


def join_threads():
    logger.debug(threads)
    for th in threads:
        try:
            th.join()
        except:
            logger.error(traceback.format_exc())


class AddonMonitor(xbmc.Monitor):
    def __init__(self):
        self.settings_pre = config.get_all_settings_addon()

        self.updaterPeriod = None
        self.update_setting = None
        self.update_hour = None
        self.scheduleScreenOnJobs()
        self.scheduleUpdater()
        self.scheduleUA()

        if not needsReload:  # do not run videolibrary update if service needs to be reloaded
            # videolibrary wait
            update_wait = [0, 10000, 20000, 30000, 60000]
            wait = update_wait[int(config.get_setting("update_wait", "videolibrary"))]
            if wait > 0:
                xbmc.sleep(wait)
            if not config.get_setting("update", "videolibrary") == 2:
                run_threaded(check_for_update, (False,))
            self.scheduleVideolibrary()
        super(AddonMonitor, self).__init__()

    def onSettingsChanged(self):
        logger.debug('settings changed')
        settings_post = config.get_all_settings_addon()
        # sometimes kodi randomly return default settings (rare but happens), this if try to workaround this
        if settings_post and settings_post.get('show_once', True):

            from platformcode import xbmc_videolibrary

            if self.settings_pre.get('downloadpath', None) != settings_post.get('downloadpath', None):
                xbmc_videolibrary.update_sources(settings_post.get('downloadpath', None),
                                                 self.settings_pre.get('downloadpath', None))

            # If the path of the video library has been changed, we call to check directories so that it creates it and automatically asks if to configure the video library
            if self.settings_pre.get("videolibrarypath", None) and self.settings_pre.get("videolibrarypath", None) != settings_post.get("videolibrarypath", None) or \
                self.settings_pre.get("folder_movies", None) and self.settings_pre.get("folder_movies", None) != settings_post.get("folder_movies", None) or \
                self.settings_pre.get("folder_tvshows", None) and self.settings_pre.get("folder_tvshows", None) != settings_post.get("folder_tvshows", None):
                videolibrary.move_videolibrary(self.settings_pre.get("videolibrarypath", ''),
                                               settings_post.get("videolibrarypath", ''),
                                               self.settings_pre.get("folder_movies", ''),
                                               settings_post.get("folder_movies", ''),
                                               self.settings_pre.get("folder_tvshows", ''),
                                               settings_post.get("folder_tvshows", ''))

            # if you want to autoconfigure and the video library directory had been created
            if not self.settings_pre.get("videolibrary_kodi", None) and settings_post.get("videolibrary_kodi", None):
                xbmc_videolibrary.ask_set_content(silent=True)
            elif self.settings_pre.get("videolibrary_kodi", None) and not settings_post.get("videolibrary_kodi", None):
                xbmc_videolibrary.clean()

            if self.settings_pre.get('addon_update_timer') != settings_post.get('addon_update_timer'):
                schedule.clear('updater')
                self.scheduleUpdater()

            if self.update_setting != config.get_setting("update", "videolibrary") or self.update_hour != config.get_setting("everyday_delay", "videolibrary") * 4:
                schedule.clear('videolibrary')
                self.scheduleVideolibrary()

            if self.settings_pre.get('elementum_on_seed') != settings_post.get('elementum_on_seed') and settings_post.get('elementum_on_seed'):
                if not platformtools.dialog_yesno(config.get_localized_string(70805), config.get_localized_string(70806)):
                    config.set_setting('elementum_on_seed', False)
            if self.settings_pre.get("shortcut_key", '') != settings_post.get("shortcut_key", ''):
                xbmc.executebuiltin('Action(reloadkeymaps)')
            if self.settings_pre.get('downloadenabled') != settings_post.get('downloadenabled'):
                platformtools.itemlist_refresh()

            # backup settings
            filetools.copy(os.path.join(config.get_data_path(), "settings.xml"),
                           os.path.join(config.get_data_path(), "settings.bak"), True)
            logger.debug({k: self.settings_pre[k] for k in self.settings_pre
                          if k in settings_post and self.settings_pre[k] != settings_post[k]})

            self.settings_pre = config.get_all_settings_addon()

    def onNotification(self, sender, method, data):
        # logger.debug('METHOD', method, sender, data)
        if method == 'Playlist.OnAdd':
            from core import db
            db['OnPlay']['addon'] = True
            db.close()
        elif method == 'Player.OnStop':
            from core import db
            db['OnPlay']['addon'] = False
            db.close()
        elif method == 'VideoLibrary.OnUpdate':
            xbmc_videolibrary.set_watched_on_addon(data)
            logger.debug('AGGIORNO')

    def onScreensaverActivated(self):
        logger.debug('screensaver activated, un-scheduling screen-on jobs')
        schedule.clear('screenOn')

    def onScreensaverDeactivated(self):
        logger.debug('screensaver deactivated, re-scheduling screen-on jobs')
        self.scheduleScreenOnJobs()

    def scheduleUpdater(self):
        if not config.dev_mode():
            updaterCheck()
            self.updaterPeriod = config.get_setting('addon_update_timer')
            schedule.every(self.updaterPeriod).hours.do(updaterCheck).tag('updater')
            logger.debug('scheduled updater every ' + str(self.updaterPeriod) + ' hours')

    def scheduleUA(self):
        get_ua_list()
        schedule.every(1).day.do(get_ua_list)

    def scheduleVideolibrary(self):
        self.update_setting = config.get_setting("update", "videolibrary")
        # 2 = Daily, 3 = When Kodi starts and daily, 5 = Each time you start Kodi and daily
        if self.update_setting in [2, 3, 5]:
            self.update_hour = config.get_setting("everyday_delay", "videolibrary") * 4
            schedule.every().day.at(str(self.update_hour).zfill(2) + ':00').do(run_threaded, check_for_update, (False,)).tag('videolibrary')
            logger.debug('scheduled videolibrary at ' + str(self.update_hour).zfill(2) + ':00')

    def scheduleScreenOnJobs(self):
        schedule.every().second.do(platformtools.viewmodeMonitor).tag('screenOn')
        schedule.every().second.do(torrent.elementum_monitor).tag('screenOn')

    def onDPMSActivated(self):
        logger.debug('DPMS activated, un-scheduling screen-on jobs')
        schedule.clear('screenOn')

    def onDPMSDeactivated(self):
        logger.debug('DPMS deactivated, re-scheduling screen-on jobs')
        self.scheduleScreenOnJobs()


if __name__ == "__main__":
    logger.info('Starting S4Meservice')

    # Test if all the required directories are created
    config.verify_directories_created()

    if config.get_setting('autostart'):
        xbmc.executebuiltin('RunAddon(plugin.video.' + config.PLUGIN_NAME + ')')

    # port old db to new
    old_db_name = filetools.join(config.get_data_path(), "s4me_db.sqlite")
    if filetools.isfile(old_db_name):
        try:
            import sqlite3

            old_db_conn = sqlite3.connect(old_db_name, timeout=15)
            old_db = old_db_conn.cursor()
            old_db.execute('select * from viewed')

            for ris in old_db.fetchall():
                if ris[1]:  # tvshow
                    show = db['viewed'].get(ris[0], {})
                    show[str(ris[1]) + 'x' + str(ris[2])] = ris[3]
                    db['viewed'][ris[0]] = show
                else:  # film
                    db['viewed'][ris[0]] = ris[3]
        except:
            pass
        finally:
            filetools.remove(old_db_name, True, False)

    # replace tvdb to tmdb for series
    if config.get_setting('videolibrary_kodi') and config.get_setting('show_once'):
        nun_records, records = xbmc_videolibrary.execute_sql_kodi('select * from path where strPath like "' +
                                           filetools.join(config.get_setting('videolibrarypath'), config.get_setting('folder_tvshows')) +
                                           '%" and strScraper="metadata.tvdb.com"')
        if nun_records:
            import xbmcaddon
            # change language
            tvdbLang = xbmcaddon.Addon(id="metadata.tvdb.com").getSetting('language')
            newLang = tvdbLang + '-' + tvdbLang.upper()
            xbmcaddon.Addon(id="metadata.tvshows.themoviedb.org").setSetting('language', newLang)
            updater.refreshLang()

            # prepare to replace strSettings
            path_settings = xbmc.translatePath("special://profile/addon_data/metadata.tvshows.themoviedb.org/settings.xml")
            settings_data = filetools.read(path_settings)
            strSettings = ' '.join(settings_data.split()).replace("> <", "><")
            strSettings = strSettings.replace("\"", "\'")

            # update db
            nun_records, records = xbmc_videolibrary.execute_sql_kodi(
                'update path set strScraper="metadata.tvshows.themoviedb.org", strSettings="' + strSettings + '" where strPath like "' +
                filetools.join(config.get_setting('videolibrarypath'), config.get_setting('folder_tvshows')) +
                '%" and strScraper="metadata.tvdb.com"')

            # scan new info
            xbmc.executebuiltin('UpdateLibrary(video)')
            xbmc.executebuiltin('CleanLibrary(video)')
            # while xbmc.getCondVisibility('Library.IsScanningVideo()'):
            #     xbmc.sleep(1000)

    # check if the user has any connection problems
    from platformcode.checkhost import test_conn
    run_threaded(test_conn, (True, not config.get_setting('resolver_dns'), True, [], [], True))

    monitor = AddonMonitor()

    # mark as stopped all downloads (if we are here, probably kodi just started)
    from specials.downloads import stop_all
    try:
        stop_all()
    except:
        logger.error(traceback.format_exc())

    while True:
        try:
            schedule.run_pending()
        except:
            logger.error(traceback.format_exc())

        if needsReload:
            join_threads()
            db.close()
            logger.info('Relaunching service.py')
            xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.s4me", "enabled": false }}')
            xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.s4me", "enabled": true }}')
            logger.debug(threading.enumerate())
            break

        if monitor.waitForAbort(1): # every second
            logger.debug('S4Meservice EXIT')
            # db need to be closed when not used, it will cause freezes
            join_threads()
            logger.debug('Close Threads')
            db.close()
            logger.debug('Close DB')
            break
    logger.debug('S4Meservice STOPPED')