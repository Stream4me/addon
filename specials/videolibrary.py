# -*- coding: utf-8 -*-

#from builtins import str
import sys
from core import support

PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

import xbmc, os, traceback
from time import time

from core import filetools, scrapertools, videolibrarytools
from core.support import typo, thumb
from core.item import Item
from platformcode import config, logger, platformtools
if PY3:
    from concurrent import futures
else:
    from concurrent_py2 import futures


def mainlist(item):
    logger.debug()

    itemlist = [Item(channel=item.channel, action="list_movies", title=config.get_localized_string(60509),
                     category=config.get_localized_string(70270), thumbnail=thumb("videolibrary_movie")),
                Item(channel=item.channel, action="list_tvshows",title=config.get_localized_string(60600),
                     category=config.get_localized_string(70271), thumbnail=thumb("videolibrary_tvshow"),
                     context=[{"channel":"videolibrary", "action":"update_videolibrary", "title":config.get_localized_string(70269)}]),
                Item(channel='shortcuts', action="SettingOnPosition", title=typo(config.get_localized_string(70287),'bold color std'),
                     category=2, setting=1, thumbnail = thumb("setting_0"),folder=False)]
    return itemlist


def channel_config(item):
    return platformtools.show_channel_settings(channelpath=os.path.join(config.get_runtime_path(), "channels", item.channel), caption=config.get_localized_string(60598))


def list_movies(item, silent=False):
    logger.debug()
    itemlist = []
    movies_path = []
    for root, folders, files in filetools.walk(videolibrarytools.MOVIES_PATH):
        for f in folders:
            movies_path += [filetools.join(root, f, f + ".nfo")]
            local = False
            for f in filetools.listdir(filetools.join(root, f)):
                if f.split('.')[-1] not in ['nfo','json','strm']:
                    local= True
                    break

    # from core.support import dbg;dbg()
    # for movie_path in movies_path:
    #     get_results(movie_path, root, 'movie', local)
    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(get_results, movie_path, root, 'movie', local) for movie_path in movies_path]
        for res in futures.as_completed(itlist):
            item_movie, value = res.result()
            # verify the existence of the channels
            if item_movie.library_urls and len(item_movie.library_urls) > 0:
                itemlist += [item_movie]

    if silent == False: return sorted(itemlist, key=lambda it: it.title.lower())
    else: return


def list_tvshows(item):
    logger.debug()
    itemlist = []
    lista = []

    root = videolibrarytools.TVSHOWS_PATH
    start = time()
    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(get_results, filetools.join(root, folder, "tvshow.nfo"), root, 'tvshow') for folder in filetools.listdir(root)]
        for res in futures.as_completed(itlist):
            item_tvshow, value = res.result()
            # verify the existence of the channels
            if item_tvshow.library_urls and len(item_tvshow.library_urls) > 0:
                itemlist += [item_tvshow]
                lista += [{'title':item_tvshow.contentTitle,'thumbnail':item_tvshow.thumbnail,'fanart':item_tvshow.fanart, 'active': value, 'nfo':item_tvshow.nfo}]
    logger.debug('load list',time() - start)
    if itemlist:
        itemlist = sorted(itemlist, key=lambda it: it.title.lower())

        itemlist += [Item(channel=item.channel, action="update_videolibrary", thumbnail=item.thumbnail,
                          title=typo(config.get_localized_string(70269), 'bold color std'), folder=False),
                     Item(channel=item.channel, action="configure_update_videolibrary", thumbnail=item.thumbnail,
                          title=typo(config.get_localized_string(60599), 'bold color std'), lista=lista, folder=False)]
    return itemlist


def get_results(nfo_path, root, Type, local=False):
    value = 0

    if filetools.exists(nfo_path):
        head_nfo, item = videolibrarytools.read_nfo(nfo_path)
        item.contentType = Type

        # If you have not read the .nfo well, we will proceed to the next
        if not item:
            logger.error('.nfo erroneous in ' + str(nfo_path))
            return Item(), 0

        if len(item.library_urls) > 1: multichannel = True
        else: multichannel = False

        # continue loading the elements of the video library
        if Type == 'movie':
            folder = "folder_movies"
            item.path = filetools.split(nfo_path)[0]
            item.nfo = nfo_path
            sep = '/' if '/' in nfo_path else '\\'
            item.extra = filetools.join(config.get_setting("videolibrarypath"), config.get_setting(folder), item.path.split(sep)[-1])
            strm_path = item.strm_path.replace("\\", "/").rstrip("/")
            if not item.thumbnail: item.thumbnail = item.infoLabels['thumbnail']
            if '/' in item.path: item.strm_path = strm_path
            # If strm has been removed from kodi library, don't show it
            if not filetools.exists(filetools.join(item.path, filetools.basename(strm_path))) and not local: return Item(), 0

            # Contextual menu: Mark as seen / not seen
            visto = item.library_playcounts.get(strm_path.strip('/').split('/')[0], 0)
            item.infoLabels["playcount"] = visto
            if visto > 0:
                seen_text = config.get_localized_string(60016)
                counter = 0
            else:
                seen_text = config.get_localized_string(60017)
                counter = 1

            # Context menu: Delete series / channel
            channels_num = len(item.library_urls)
            if "downloads" in item.library_urls: channels_num -= 1
            if channels_num > 1: delete_text = config.get_localized_string(60018)
            else: delete_text = config.get_localized_string(60019)

            item.context = [{"title": seen_text, "action": "mark_content_as_watched", "channel": "videolibrary",  "playcount": counter},
                            {"title": delete_text, "action": "delete", "channel": "videolibrary", "multichannel": multichannel},
                            {"title": config.get_localized_string(80051), "action": "set_tvshow_media_prefs", "channel": "videolibrary"}]
        else:
            folder = "folder_tvshows"
            try:
                item.title = item.contentTitle
                item.path = filetools.split(nfo_path)[0]
                item.nfo = nfo_path
                sep = '/' if '/' in nfo_path else '\\'
                item.extra = filetools.join(config.get_setting("videolibrarypath"), config.get_setting(folder), item.path.split(sep)[-1])
                # Contextual menu: Mark as seen / not seen
                visto = item.library_playcounts.get(item.contentTitle, 0)
                item.infoLabels["playcount"] = visto
                logger.debug('item\n' + str(item))
                if visto > 0:
                    seen_text = config.get_localized_string(60020)
                    counter = 0
                else:
                    seen_text = config.get_localized_string(60021)
                    counter = 1

            except:
                logger.error('Not find: ' + str(nfo_path))
                logger.error(traceback.format_exc())
                return Item(), 0

            # Context menu: Automatically search for new episodes or not
            if item.active and int(item.active) > 0:
                update_text = config.get_localized_string(60022)
                value = 0
            else:
                update_text = config.get_localized_string(60023)
                value = 1
                item.title += " [B]" + u"\u2022" + "[/B]"

            # Context menu: Delete series / channel
            channels_num = len(item.library_urls)
            if "downloads" in item.library_urls: channels_num -= 1
            if channels_num > 1: delete_text = config.get_localized_string(60024)
            else: delete_text = config.get_localized_string(60025)

            item.context = [{"title": seen_text, "action": "mark_content_as_watched", "channel": "videolibrary", "playcount": counter},
                            {"title": update_text, "action": "mark_tvshow_as_updatable", "channel": "videolibrary", "active": value},
                            {"title": delete_text, "action": "delete", "channel": "videolibrary", "multichannel": multichannel},
                            {"title": config.get_localized_string(70269), "action": "update_tvshow", "channel": "videolibrary"}]
            if item.local_episodes_path == "": item.context.append({"title": config.get_localized_string(80048), "action": "add_local_episodes", "channel": "videolibrary"})
            else: item.context.append({"title": config.get_localized_string(80049), "action": "remove_local_episodes", "channel": "videolibrary"})
            item.context.append({"title": config.get_localized_string(80051), "action": "set_tvshow_media_prefs", "channel": "videolibrary"})
    else: item = Item()
    return item, value


def configure_update_videolibrary(item):
    import xbmcgui
    # Load list of options (active user channels that allow global search)
    lista = []
    ids = []
    preselect = []

    for i, item_tvshow in enumerate(item.lista):
        it = xbmcgui.ListItem(item_tvshow["title"], '')
        it.setArt({'thumb': item_tvshow["thumbnail"], 'fanart': item_tvshow["fanart"]})
        lista.append(it)
        ids.append(Item(nfo=item_tvshow['nfo']))
        if item_tvshow['active']<=0:
            preselect.append(i)

    # Select Dialog
    ret = platformtools.dialog_multiselect(config.get_localized_string(60601), lista, preselect=preselect, useDetails=True)
    if ret is None:
        return False  # order cancel
    selection = [ids[i] for i in ret]

    for tvshow in ids:
        if tvshow not in selection:
            tvshow.active = 0
        elif tvshow in selection:
            tvshow.active = 1
        mark_tvshow_as_updatable(tvshow, silent=True)

    platformtools.itemlist_refresh()

    return True


def get_seasons(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))
    itemlist = []
    dict_temp = {}

    videolibrarytools.check_renumber_options(item)

    raiz, carpetas_series, ficheros = next(filetools.walk(item.path))

    # Menu contextual: Releer tvshow.nfo
    head_nfo, item_nfo = videolibrarytools.read_nfo(item.nfo)

    if config.get_setting("no_pile_on_seasons", "videolibrary") == 2:  # Ever
        return get_episodes(item)

    for f in ficheros:
        if f.endswith('.json'):
            season = f.split('x')[0]
            dict_temp[season] = config.get_localized_string(60027) % season

    if config.get_setting("no_pile_on_seasons", "videolibrary") == 1 and len(
            dict_temp) == 1:  # Only if there is a season
        return get_episodes(item)
    else:
        # We create one item for each season
        for season, title in list(dict_temp.items()):
            new_item = item.clone(action="get_episodes", title=title, contentSeason=season,
                                  filtrar_season=True, channel='videolibrary', contentType='season')

            #Contextual menu: Mark the season as viewed or not
            visto = item_nfo.library_playcounts.get("season %s" % season, 0)
            new_item.infoLabels["playcount"] = visto
            if visto > 0:
                texto = config.get_localized_string(60028)
                value = 0
            else:
                texto = config.get_localized_string(60029)
                value = 1
            new_item.context = [{"title": texto,
                                 "action": "mark_season_as_watched",
                                 "channel": "videolibrary",
                                 "playcount": value}]

            # logger.debug("new_item:\n" + new_item.tostring('\n'))
            itemlist.append(new_item)

        if len(itemlist) > 1:
            itemlist = sorted(itemlist, key=lambda it: int(it.contentSeason))

        if config.get_setting("show_all_seasons", "videolibrary"):
            new_item = item.clone(action="get_episodes", channel='videolibrary', title=config.get_localized_string(60030))
            new_item.infoLabels["playcount"] = 0
            itemlist.insert(0, new_item)

        add_download_items(item, itemlist)
    return itemlist


def get_episodes(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))
    itemlist = []

    # We get the archives of the episodes
    raiz, carpetas_series, ficheros = next(filetools.walk(item.path))

    # Menu contextual: Releer tvshow.nfo
    head_nfo, item_nfo = videolibrarytools.read_nfo(item.nfo)

    # Create an item in the list for each strm found
    for i in ficheros:
        ext = i.split('.')[-1]
        if ext not in ['json','nfo']:
            season_episode = scrapertools.get_season_and_episode(i)
            if not season_episode:
                # The file does not include the season and episode number
                continue
            season, episode = season_episode.split("x")
            # If there is a filter by season, we ignore the chapters of other seasons
            if item.filtrar_season and int(season) != int(item.contentSeason):
                continue
            # Get the data from the season_episode.nfo
            nfo_path = filetools.join(raiz, '%sx%s.nfo' % (season, episode))
            if filetools.isfile(nfo_path):
                head_nfo, epi = videolibrarytools.read_nfo(nfo_path)

                # Set the chapter title if possible
                if epi.contentTitle and epi.contentTitle != epi.fulltitle:
                    title_episodie = epi.contentTitle.strip()
                else:
                    title_episodie = config.get_localized_string(60031) %  (epi.contentSeason, str(epi.contentEpisodeNumber).zfill(2))

                epi.contentTitle = "%sx%s" % (epi.contentSeason, str(epi.contentEpisodeNumber).zfill(2))
                epi.title = "%sx%s - %s" % (epi.contentSeason, str(epi.contentEpisodeNumber).zfill(2), title_episodie)
                epi.contentType = 'episode'

                if item_nfo.library_filter_show:
                    epi.library_filter_show = item_nfo.library_filter_show

                # Contextual menu: Mark episode as seen or not
                visto = item_nfo.library_playcounts.get(season_episode, 0)
                epi.infoLabels["playcount"] = visto
                if visto > 0:
                    texto = config.get_localized_string(60032)
                    value = 0
                else:
                    texto = config.get_localized_string(60033)
                    value = 1
                epi.context = [{"title": texto,
                                "action": "mark_content_as_watched",
                                "channel": "videolibrary",
                                "playcount": value,
                                "nfo": item.nfo}]
                if ext != 'strm':
                    epi.local = True
                itemlist.append(epi)

    itemlist = sorted(itemlist, key=lambda it: (int(it.contentSeason), int(it.contentEpisodeNumber)))
    add_download_items(item, itemlist)
    return itemlist


def findvideos(item):
    from platformcode import platformtools

    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))
    videolibrarytools.check_renumber_options(item)
    itemlist = []
    list_canales = {}
    item_local = None

    # Disable autoplay
    # autoplay.set_status(False)

    if not item.contentTitle or not item.strm_path:
        logger.debug("Unable to search for videos due to lack of parameters")
        return []

    if item.contentEpisodeNumber:
        content_title = str(item.contentSeason) + 'x' + (str(item.contentEpisodeNumber) if item.contentEpisodeNumber > 9 else '0' + str(item.contentEpisodeNumber))
    else:
        content_title = item.contentTitle.strip().lower()

    # Fix in case item.streampath is a full path
    import re
    paths = re.split('\\\|/', item.strm_path)
    strm_path = filetools.join(paths[-2],paths[-1])
    if item.contentType == 'movie':
        strm_path = filetools.join(videolibrarytools.MOVIES_PATH, strm_path)
        path_dir = filetools.dirname(strm_path)
        item.nfo = filetools.join(path_dir, filetools.basename(path_dir) + ".nfo")
    else:
        strm_path = filetools.join(videolibrarytools.TVSHOWS_PATH, strm_path)
        path_dir = filetools.dirname(strm_path)
        item.nfo = filetools.join(path_dir, 'tvshow.nfo')

    for fd in filetools.listdir(path_dir):
        if fd.endswith('.json'):
            contenido, nom_canal = fd[:-6].split('[')
            if (contenido.startswith(content_title) or item.contentType == 'movie') and nom_canal not in list(list_canales.keys()):
                list_canales[nom_canal] = filetools.join(path_dir, fd)

    num_canales = len(list_canales)

    if 'downloads' in list_canales:
        json_path = list_canales['downloads']
        item_json = Item().fromjson(filetools.read(json_path))
        item_json.contentChannel = "local"
        # Support for relative paths in downloads
        if filetools.is_relative(item_json.url):
            item_json.url = filetools.join(videolibrarytools.VIDEOLIBRARY_PATH, item_json.url)

        del list_canales['downloads']

        # Check that the video has not been deleted
        if filetools.exists(item_json.url):
            item_local = item_json.clone(action='play')
            itemlist.append(item_local)
        else:
            num_canales -= 1

    filtro_canal = ''
    if num_canales > 1 and config.get_setting("ask_channel", "videolibrary"):
        opciones = [config.get_localized_string(70089) % k.capitalize() for k in list(list_canales.keys())]
        opciones.insert(0, config.get_localized_string(70083))
        if item_local:
            opciones.append(item_local.title)

        index = platformtools.dialog_select(config.get_localized_string(30163), opciones)
        if index < 0:
            return []

        elif item_local and index == len(opciones) - 1:
            filtro_canal = 'downloads'
            platformtools.play_video(item_local)

        elif index > 0:
            filtro_canal = opciones[index].replace(config.get_localized_string(70078), "").strip()
            itemlist = []

    all_videolibrary = []
    ch_results = []
    list_servers = []

    with futures.ThreadPoolExecutor() as executor:
        for nom_canal, json_path in list(list_canales.items()):
            if filtro_canal and filtro_canal != nom_canal.capitalize():
                continue

            # We import the channel of the selected part
            try:
                if nom_canal == 'community':
                    channel = __import__('specials.%s' % nom_canal, fromlist=["channels.%s" % nom_canal])
                else:
                    channel = __import__('channels.%s' % nom_canal, fromlist=["channels.%s" % nom_canal])
            except ImportError:
                exec("import channels." + nom_canal + " as channel")
            except:
                dead_list = []
                zombie_list = []

                if nom_canal not in dead_list and nom_canal not in zombie_list: confirm = platformtools.dialog_yesno(config.get_localized_string(30131), config.get_localized_string(30132) % nom_canal.upper() + '\n' + config.get_localized_string(30133))
                elif nom_canal in zombie_list: confirm = False
                else: confirm = True

                if confirm:
                    # delete the channel from all movie and tvshow
                    from past.utils import old_div
                    num_enlaces = 0
                    dialog = platformtools.dialog_progress(config.get_localized_string(30131), config.get_localized_string(60005) % nom_canal)
                    if not all_videolibrary:
                        all_videolibrary = list_movies(Item()) + list_tvshows(Item())
                    for n, it in enumerate(all_videolibrary):
                        if nom_canal in it.library_urls:
                            dead_item = Item(multichannel=len(it.library_urls) > 1,
                                             contentType=it.contentType,
                                             dead=nom_canal,
                                             path=filetools.split(it.nfo)[0],
                                             nfo=it.nfo,
                                             library_urls=it.library_urls,
                                             infoLabels={'title': it.contentTitle})
                            num_enlaces += delete(dead_item)
                        dialog.update(old_div(100*n, len(all_videolibrary)))

                    dialog.close()
                    msg_txt = config.get_localized_string(70087) % (num_enlaces, nom_canal)
                    logger.info(msg_txt)
                    platformtools.dialog_notification(config.get_localized_string(30131), msg_txt)
                    platformtools.itemlist_refresh()

                    if nom_canal not in dead_list:
                        dead_list.append(nom_canal)
                    continue
                else:
                    if nom_canal not in zombie_list:
                        zombie_list.append(nom_canal)

                if len(dead_list) > 0:
                    for nom_canal in dead_list:
                        if nom_canal in item.library_urls:
                            del item.library_urls[nom_canal]

            item_json = Item().fromjson(filetools.read(json_path))
            # support.dbg()
            try: from urllib.parse import urlsplit
            except ImportError: from urlparse import urlsplit
            try:
                if urlsplit(item_json.url).netloc.split('.')[0] in channel.host:
                    spurl = urlsplit(item_json.url)
                    item_json.url = channel.host + spurl.path + ('?' + spurl.query if spurl.query else '')
            except: pass

            try:
                # FILTERTOOLS
                # if the channel has a filter, the name it has saved is passed to it so that it filters correctly.
                if "list_language" in item_json:
                    # if it comes from the addon video library
                    if "library_filter_show" in item:
                        item_json.show = item.library_filter_show.get(nom_canal, "")

                # We run find_videos, from the channel or common
                item_json.contentChannel = 'videolibrary'
                item_json.play_from = item.play_from
                item_json.nfo = item.nfo
                item_json.strm_path = item.strm_path
                if hasattr(channel, 'findvideos'):
                    from core import servertools
                    if item_json.videolibray_emergency_urls:
                        del item_json.videolibray_emergency_urls
                    ch_results.append(executor.submit(getattr(channel, 'findvideos'), item_json))
                elif item_json.action == 'play':
                    from platformcode import platformtools
                    # autoplay.set_status(True)
                    item_json.contentChannel = item_json.channel
                    item_json.channel = "videolibrary"
                    platformtools.play_video(item_json)
                    return ''
                else:
                    from core import servertools
                    ch_results.append(executor.submit(servertools.find_video_items, item_json))

            except:
                import traceback
                logger.error("The findvideos function for the channel %s failed" % nom_canal)
                logger.error(traceback.format_exc())

        for ris in futures.as_completed(ch_results):
            try:
                list_servers.extend(ris.result())
            except:
                import traceback
                logger.error("The findvideos function for a channel failed")
                logger.error(traceback.format_exc())


    # Change the title to the servers adding the name of the channel in front and the infoLabels and the images of the item if the server does not have
    for server in list_servers:
        server.contentChannel = server.channel
        server.channel = "videolibrary"
        server.nfo = item.nfo
        server.strm_path = item.strm_path
        server.play_from = item.play_from

        # Kodi 18 Compatibility - Prevents wheel from spinning around in Direct Links
        if server.action == 'play':
            server.folder = False

        # Channel name is added if desired
        if config.get_setting("quit_channel_name", "videolibrary") == 0:
            server.title = "%s: %s" % (server.contentChannel.capitalize(), server.title)

        if not server.thumbnail:
            server.thumbnail = item.thumbnail

        # logger.debug("server:\n%s" % server.tostring('\n'))
        itemlist.append(server)
    # from core.support import dbg;dbg()
    # if autoplay.play_multi_channel(item, itemlist):  # hideserver
    #     return []

    add_download_items(item, itemlist)
    return itemlist


def play(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))

    if not item.contentChannel == "local":
        if item.contentChannel == 'community':
            channel = __import__('specials.%s' % item.contentChannel, fromlist=["channels.%s" % item.contentChannel])
        else:
            channel = __import__('channels.%s' % item.contentChannel, fromlist=["channels.%s" % item.contentChannel])
        if hasattr(channel, "play"):
            itemlist = getattr(channel, "play")(item)

        else:
            itemlist = [item.clone()]
    else:
        itemlist = [item.clone(url=item.url, server="local")]

    if not itemlist:
        return []
    # For direct links in list format
    if isinstance(itemlist[0], list):
        item.video_urls = itemlist
        itemlist = [item]

    # This is necessary in case the channel play deletes the data
    for v in itemlist:
        if isinstance(v, Item):
            v.nfo = item.nfo
            v.strm_path = item.strm_path
            v.infoLabels = item.infoLabels
            if item.contentTitle:
                v.title = item.contentTitle
            else:
                if item.contentType == "episode":
                    v.title = config.get_localized_string(60036) % item.contentEpisodeNumber
            v.thumbnail = item.thumbnail
            v.contentThumbnail = item.thumbnail
            v.contentChannel = item.contentChannel

    return itemlist


def update_videolibrary(item=''):
    logger.debug()

    # Update active series by overwriting
    import service
    service.check_for_update(overwrite=True)

    # Delete movie folders that do not contain strm file
    for raiz, subcarpetas, ficheros in filetools.walk(videolibrarytools.MOVIES_PATH):
        strm = False
        for f in ficheros:
            if f.endswith(".strm"):
                strm = True
                break

        if ficheros and not strm:
            logger.debug("Deleting deleted movie folder: %s" % raiz)
            filetools.rmdirtree(raiz)


def move_videolibrary(current_path, new_path, current_movies_folder, new_movies_folder, current_tvshows_folder, new_tvshows_folder):
    from distutils import dir_util

    logger.debug()

    backup_current_path = current_path
    backup_new_path = new_path

    logger.info('current_path: ' + current_path)
    logger.info('new_path: ' + new_path)
    logger.info('current_movies_folder: ' + current_movies_folder)
    logger.info('new_movies_folder: ' + new_movies_folder)
    logger.info('current_tvshows_folder: ' + current_tvshows_folder)
    logger.info('new_tvshows_folder: ' + new_tvshows_folder)

    notify = False
    progress = platformtools.dialog_progress_bg(config.get_localized_string(20000), config.get_localized_string(80011))
    xbmc.sleep(1000)
    current_path = u'' + xbmc.translatePath(current_path)
    new_path = u'' + xbmc.translatePath(new_path)
    current_movies_path = u'' + filetools.join(current_path, current_movies_folder)
    new_movies_path = u'' + filetools.join(new_path, new_movies_folder)
    current_tvshows_path = u'' + filetools.join(current_path, current_tvshows_folder)
    new_tvshows_path = u'' + filetools.join(new_path, new_tvshows_folder)

    logger.info('current_movies_path: ' + current_movies_path)
    logger.info('new_movies_path: ' + new_movies_path)
    logger.info('current_tvshows_path: ' + current_tvshows_path)
    logger.info('new_tvshows_path: ' + new_tvshows_path)

    from platformcode import xbmc_videolibrary
    movies_path, tvshows_path = xbmc_videolibrary.check_sources(new_movies_path, new_tvshows_path)
    logger.info('check_sources: ' + str(movies_path) + ', ' + str(tvshows_path))
    if movies_path or tvshows_path:
        if not movies_path:
            filetools.rmdir(new_movies_path)
        if not tvshows_path:
            filetools.rmdir(new_tvshows_path)
        config.set_setting("videolibrarypath", backup_current_path)
        config.set_setting("folder_movies", current_movies_folder)
        config.set_setting("folder_tvshows", current_tvshows_folder)
        xbmc_videolibrary.update_sources(backup_current_path, backup_new_path)
        progress.update(100)
        xbmc.sleep(1000)
        progress.close()
        platformtools.dialog_ok(config.get_localized_string(20000), config.get_localized_string(80028))
        return

    config.verify_directories_created()
    progress.update(10, config.get_localized_string(20000), config.get_localized_string(80012))
    if current_movies_path != new_movies_path:
        if filetools.listdir(current_movies_path):
            dir_util.copy_tree(current_movies_path, new_movies_path)
            notify = True
        filetools.rmdirtree(current_movies_path)
    progress.update(40)
    if current_tvshows_path != new_tvshows_path:
        if filetools.listdir(current_tvshows_path):
            dir_util.copy_tree(current_tvshows_path, new_tvshows_path)
            notify = True
        filetools.rmdirtree(current_tvshows_path)
    progress.update(70)
    if current_path != new_path and not filetools.listdir(current_path) and not "plugin.video.s4me\\videolibrary" in current_path:
        filetools.rmdirtree(current_path)

    xbmc_videolibrary.update_sources(backup_new_path, backup_current_path)
    if config.is_xbmc() and config.get_setting("videolibrary_kodi"):
        xbmc_videolibrary.update_db(backup_current_path, backup_new_path, current_movies_folder, new_movies_folder, current_tvshows_folder, new_tvshows_folder, progress)
    else:
        progress.update(100)
        xbmc.sleep(1000)
        progress.close()
    if notify:
        platformtools.dialog_notification(config.get_localized_string(20000), config.get_localized_string(80014), time=5000, sound=False)


def delete_videolibrary(item):
    logger.debug()

    if not platformtools.dialog_yesno(config.get_localized_string(20000), config.get_localized_string(80037)):
        return

    p_dialog = platformtools.dialog_progress_bg(config.get_localized_string(20000), config.get_localized_string(80038))
    p_dialog.update(0)

    if config.is_xbmc() and config.get_setting("videolibrary_kodi"):
        from platformcode import xbmc_videolibrary
        xbmc_videolibrary.clean()
    p_dialog.update(10)
    filetools.rmdirtree(videolibrarytools.MOVIES_PATH)
    p_dialog.update(50)
    filetools.rmdirtree(videolibrarytools.TVSHOWS_PATH)
    p_dialog.update(90)

    config.verify_directories_created()
    p_dialog.update(100)
    xbmc.sleep(1000)
    p_dialog.close()
    platformtools.dialog_notification(config.get_localized_string(20000), config.get_localized_string(80039), time=5000, sound=False)


# context menu methods
def update_tvshow(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))

    heading = config.get_localized_string(60037)
    p_dialog = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
    p_dialog.update(0, heading, item.contentSerieName)

    import service
    if service.update(item.path, p_dialog, 0, 100, item, False) and config.is_xbmc() and config.get_setting("videolibrary_kodi"):
        from platformcode import xbmc_videolibrary
        xbmc_videolibrary.update(folder=filetools.basename(item.path))

    p_dialog.close()

    # check if the TV show is ended or has been canceled and ask the user to remove it from the video library update
    nfo_path = filetools.join(item.path, "tvshow.nfo")
    head_nfo, item_nfo = videolibrarytools.read_nfo(nfo_path)
    if item.active and not item_nfo.active:
        # if not platformtools.dialog_yesno(config.get_localized_string(60037).replace('...',''), config.get_localized_string(70268) % item.contentSerieName):
        item_nfo.active = 1
        filetools.write(nfo_path, head_nfo + item_nfo.tojson())

    platformtools.itemlist_refresh()


def add_local_episodes(item):
    logger.debug()

    done, local_episodes_path = videolibrarytools.config_local_episodes_path(item.path, item, silent=True)
    if done < 0:
        logger.debug("An issue has occurred while configuring local episodes")
    elif local_episodes_path:
        nfo_path = filetools.join(item.path, "tvshow.nfo")
        head_nfo, item_nfo = videolibrarytools.read_nfo(nfo_path)
        item_nfo.local_episodes_path = local_episodes_path
        if not item_nfo.active:
            item_nfo.active = 1
        filetools.write(nfo_path, head_nfo + item_nfo.tojson())

        update_tvshow(item)

        platformtools.itemlist_refresh()


def remove_local_episodes(item):
    logger.debug()

    nfo_path = filetools.join(item.path, "tvshow.nfo")
    head_nfo, item_nfo = videolibrarytools.read_nfo(nfo_path)

    for season_episode in item_nfo.local_episodes_list:
        filetools.remove(filetools.join(item.path, season_episode + '.strm'))

    item_nfo.local_episodes_list = []
    item_nfo.local_episodes_path = ''
    filetools.write(nfo_path, head_nfo + item_nfo.tojson())

    update_tvshow(item)

    platformtools.itemlist_refresh()


def verify_playcount_series(item, path):
    logger.debug()

    """
    This method reviews and repairs the PlayCount of a series that has become out of sync with the actual list of episodes in its folder. Entries for missing episodes, seasons, or series are created with the "not seen" mark. Later it is sent to verify the counters of Seasons and Series
    On return it sends status of True if updated or False if not, usually by mistake. With this status, the caller can update the status of the "verify_playcount" option in "videolibrary.py". The intention of this method is to give a pass that repairs all the errors and then deactivate it. It can be reactivated in the Alpha Video Library menu.

    """
    #logger.debug("item:\n" + item.tostring('\n'))

    # If you have never done verification, we force it
    estado = config.get_setting("verify_playcount", "videolibrary")
    if not estado or estado == False:
        estado = True                                                               # If you have never done verification, we force it
    else:
        estado = False

    if item.contentType == 'movie':                                                 # This is only for Series
        return (item, False)
    if filetools.exists(path):
        nfo_path = filetools.join(path, "tvshow.nfo")
        head_nfo, it = videolibrarytools.read_nfo(nfo_path)                         # We get the .nfo of the Series
        if not hasattr(it, 'library_playcounts') or not it.library_playcounts:      # If the .nfo does not have library_playcounts we will create it for you
            logger.error('** It does not have PlayCount')
            it.library_playcounts = {}

        # We get the archives of the episodes
        raiz, carpetas_series, ficheros = next(filetools.walk(path))
        # Create an item in the list for each strm found
        estado_update = False
        for i in ficheros:
            if i.endswith('.strm'):
                season_episode = scrapertools.get_season_and_episode(i)
                if not season_episode:
                    # The file does not include the season and episode number
                    continue
                season, episode = season_episode.split("x")
                if season_episode not in it.library_playcounts:                     # The episode is not included
                    it.library_playcounts.update({season_episode: 0})               # update the .nfo playCount
                    estado_update = True                                            # We mark that we have updated something

                if 'season %s' % season not in it.library_playcounts:               # Season is not included
                    it.library_playcounts.update({'season %s' % season: 0})         # update the .nfo playCount
                    estado_update = True                                            # We mark that we have updated something

                if it.contentSerieName not in it.library_playcounts:                # Series not included
                    it.library_playcounts.update({item.contentSerieName: 0})        # update the .nfo playCount
                    estado_update = True                                            # We mark that we have updated something

        if estado_update:
            logger.error('** Update status: ' + str(estado) + ' / PlayCount: ' + str(it.library_playcounts))
            estado = estado_update
        # it is verified that if all the episodes of a season are marked, tb the season is marked
        for key, value in it.library_playcounts.items():
            if key.startswith("season"):
                season = scrapertools.find_single_match(key, r'season (\d+)')        # We obtain in no. seasonal
                it = check_season_playcount(it, season)
        # We save the changes to item.nfo
        if filetools.write(nfo_path, head_nfo + it.tojson()):
            return (it, estado)
    return (item, False)


def mark_content_as_watched2(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))
    if filetools.isfile(item.nfo):
        head_nfo, it = videolibrarytools.read_nfo(item.nfo)
        name_file = ""
        if item.contentType == 'movie' or item.contentType == 'tvshow':
            name_file = os.path.splitext(filetools.basename(item.nfo))[0]

            if name_file != 'tvshow' :
                it.library_playcounts.update({name_file: item.playcount})

        if item.contentType == 'episode' or item.contentType == 'tvshow' or item.contentType == 'list' or name_file == 'tvshow':
            name_file = os.path.splitext(filetools.basename(item.strm_path))[0]
            num_season = name_file [0]
            item.__setattr__('contentType', 'episode')
            item.__setattr__('contentSeason', num_season)

        else:
            name_file = item.contentTitle

        if not hasattr(it, 'library_playcounts'):
            it.library_playcounts = {}
        it.library_playcounts.update({name_file: item.playcount})

        # it is verified that if all the episodes of a season are marked, tb the season is marked
        if item.contentType != 'movie':
            it = check_season_playcount(it, item.contentSeason)

        # We save the changes to item.nfo
        if filetools.write(item.nfo, head_nfo + it.tojson()):
            item.infoLabels['playcount'] = item.playcount

            if config.is_xbmc():
                from platformcode import xbmc_videolibrary
                xbmc_videolibrary.mark_content_as_watched_on_kodi(item , item.playcount)


def mark_content_as_watched(item):
    logger.debug()
    #logger.debug("item:\n" + item.tostring('\n'))

    if filetools.exists(item.nfo):
        head_nfo, it = videolibrarytools.read_nfo(item.nfo)

        if item.contentType == 'movie':
            name_file = os.path.splitext(filetools.basename(item.nfo))[0]
        elif item.contentType == 'episode':
            name_file = "%sx%s" % (item.contentSeason, str(item.contentEpisodeNumber).zfill(2))
        else:
            name_file = item.contentTitle

        if not hasattr(it, 'library_playcounts'):
            it.library_playcounts = {}
        it.library_playcounts.update({name_file: item.playcount})

        # it is verified that if all the episodes of a season are marked, tb the season is marked
        if item.contentType != 'movie':
            it = check_season_playcount(it, item.contentSeason)

        # We save the changes to item.nfo
        if filetools.write(item.nfo, head_nfo + it.tojson()):
            item.infoLabels['playcount'] = item.playcount

            if item.contentType == 'tvshow' and item.type != 'episode' :
                # Update entire series
                new_item = item.clone(contentSeason=-1)
                mark_season_as_watched(new_item)

            if config.is_xbmc():
                from platformcode import xbmc_videolibrary
                xbmc_videolibrary.mark_content_as_watched_on_kodi(item, item.playcount)
                if config.get_setting("trakt_sync"):
                    xbmc_videolibrary.sync_trakt_kodi()
            platformtools.itemlist_refresh()


def mark_season_as_watched(item):
    logger.debug()
    # logger.debug("item:\n" + item.tostring('\n'))

    # Get dictionary of marked episodes
    if not item.path: f = item.nfo
    else: f = filetools.join(item.path, 'tvshow.nfo')

    head_nfo, it = videolibrarytools.read_nfo(f)
    if not hasattr(it, 'library_playcounts'):
        it.library_playcounts = {}

    # We get the archives of the episodes
    raiz, carpetas_series, ficheros = next(filetools.walk(item.path))

    # We mark each of the episodes found this season
    episodios_marcados = 0
    for i in ficheros:
        if i.endswith(".strm"):
            season_episode = scrapertools.get_season_and_episode(i)
            if not season_episode:
                # The file does not include the season and episode number
                continue
            season, episode = season_episode.split("x")

            if int(item.contentSeason) == -1 or int(season) == int(item.contentSeason):
                name_file = os.path.splitext(filetools.basename(i))[0]
                it.library_playcounts[name_file] = item.playcount
                episodios_marcados += 1

    if episodios_marcados:
        if int(item.contentSeason) == -1:
            # We add all seasons to the dictionary item.library_playcounts
            for k in list(it.library_playcounts.keys()):
                if k.startswith("season"):
                    it.library_playcounts[k] = item.playcount
        else:
            # Add season to dictionary item.library_playcounts
            it.library_playcounts["season %s" % item.contentSeason] = item.playcount

            # it is verified that if all the seasons are seen, the series is marked as view
            it = check_tvshow_playcount(it, item.contentSeason)

        # We save the changes to tvshow.nfo
        filetools.write(f, head_nfo + it.tojson())
        item.infoLabels['playcount'] = item.playcount

        if config.is_xbmc():
            # We update the Kodi database
            from platformcode import xbmc_videolibrary
            xbmc_videolibrary.mark_season_as_watched_on_kodi(item, item.playcount)
            if config.get_setting("trakt_sync"):
                xbmc_videolibrary.sync_trakt_kodi()

    platformtools.itemlist_refresh()


def mark_tvshow_as_updatable(item, silent=False):
    logger.debug()
    head_nfo, it = videolibrarytools.read_nfo(item.nfo)
    it.active = item.active
    filetools.write(item.nfo, head_nfo + it.tojson())

    if not silent:
        platformtools.itemlist_refresh()


def set_tvshow_media_prefs(item):
    """
    Apre un dialogo per impostare la lingua audio preferita e la preferenza
    dei sottotitoli per una serie TV. Le scelte vengono salvate nel tvshow.nfo
    e applicate automaticamente ad ogni episodio durante la riproduzione.
    """
    logger.debug()

    nfo_path = item.nfo
    if not nfo_path:
        nfo_path = filetools.join(item.path, "tvshow.nfo")

    head_nfo, tvshow_item = videolibrarytools.read_nfo(nfo_path)
    if not tvshow_item:
        platformtools.dialog_notification(
            config.get_localized_string(60010), config.get_localized_string(80058),
            time=4000, sound=False)
        return

    title = tvshow_item.contentSerieName or tvshow_item.contentTitle or ""
    prefs = getattr(tvshow_item, 'tvshow_media_prefs', None) or {}

    # --- Passo 1: Lingua audio ---
    no_pref = config.get_localized_string(80052)
    audio_labels = [
        no_pref,
        "Italian", "English", "Spanish",
        "French", "German", "Portuguese", "Japanese",
    ]
    audio_keys = ["", "ita", "eng", "spa", "fra", "deu", "por", "jpn"]

    current_audio = prefs.get('audio_lang', '')
    preselect_audio = audio_keys.index(current_audio) if current_audio in audio_keys else 0

    audio_title = config.get_localized_string(80055) % title if title else config.get_localized_string(80055) % "?"
    audio_idx = platformtools.dialog_select(
        audio_title,
        audio_labels,
        preselect=preselect_audio
    )
    if audio_idx < 0:
        return  # Utente ha premuto Annulla

    # --- Passo 2: Preferenza sottotitoli ---
    # __on__  = sempre abilitati senza forzare una lingua
    # __off__ = sempre disabilitati
    # ""      = nessuna preferenza (Kodi decide)
    sub_labels = [
        no_pref,
        config.get_localized_string(80053),
        config.get_localized_string(80054),
        "Italian", "English", "Spanish",
        "French", "German", "Portuguese",
    ]
    sub_keys = ["", "__off__", "__on__", "ita", "eng", "spa", "fra", "deu", "por"]

    current_sub = prefs.get('sub_lang', '__on__')
    preselect_sub = sub_keys.index(current_sub) if current_sub in sub_keys else 2  # default: __on__

    sub_title = config.get_localized_string(80056) % title if title else config.get_localized_string(80056) % "?"
    sub_idx = platformtools.dialog_select(
        sub_title,
        sub_labels,
        preselect=preselect_sub
    )
    if sub_idx < 0:
        return  # Utente ha premuto Annulla

    # --- Salvataggio nel tvshow.nfo ---
    tvshow_item.tvshow_media_prefs = {
        'audio_lang': audio_keys[audio_idx],
        'sub_lang':   sub_keys[sub_idx],
    }
    filetools.write(nfo_path, head_nfo + tvshow_item.tojson())

    platformtools.dialog_notification(
        config.get_localized_string(80057),
        u"%s: %s | %s: %s" % (
            "Audio", audio_labels[audio_idx],
            "Subs",  sub_labels[sub_idx]
        ),
        time=4000, sound=False
    )
    platformtools.itemlist_refresh()


def delete(item):
    def delete_all(_item):
        for file in filetools.listdir(_item.path):
            if file.endswith(".strm") or file.endswith(".nfo") or file.endswith(".json")or file.endswith(".torrent"):
                filetools.remove(filetools.join(_item.path, file))

        if _item.contentType == 'movie':
            heading = config.get_localized_string(70084)
        else:
            heading = config.get_localized_string(70085)

        if config.is_xbmc() and config.get_setting("videolibrary_kodi"):
            from platformcode import xbmc_videolibrary
            if _item.local_episodes_path:
                platformtools.dialog_ok(heading, config.get_localized_string(80047) % _item.infoLabels['title'])
            path_list = [_item.extra]
            xbmc_videolibrary.clean(path_list)

        raiz, carpeta_serie, ficheros = next(filetools.walk(_item.path))
        if ficheros == []:
            filetools.rmdir(_item.path)
        elif platformtools.dialog_yesno(heading, config.get_localized_string(70081) % filetools.basename(_item.path)):
            filetools.rmdirtree(_item.path)

        logger.info("All links removed")
        xbmc.sleep(1000)
        platformtools.itemlist_refresh()

    # logger.debug(item.tostring('\n'))

    if item.contentType == 'movie':
        heading = config.get_localized_string(70084)
    else:
        heading = config.get_localized_string(70085)
    if item.multichannel:
        # Get channel list
        channels = []
        opciones = []
        for k in list(item.library_urls.keys()):
            if k != "downloads":
                opciones.append(config.get_localized_string(70086) % k.capitalize())
                channels.append(k)
        if item.dead == '':
            opciones.insert(0, heading)

            index = platformtools.dialog_select(config.get_localized_string(30163), opciones)

            if index == 0:
                # Selected Delete movie / series
                delete_all(item)
                return

            elif index > 0:
                # Selected Delete channel X
                canal = opciones[index].replace(config.get_localized_string(70079), "").lower()
                channels.remove(canal)
            else:
                return
        else:
            canal = item.dead

        num_enlaces = 0
        path_list = []
        for fd in filetools.listdir(item.path):
            if fd.endswith(canal + '].json') or scrapertools.find_single_match(fd, r'%s]_\d+.torrent' % canal):
                if filetools.remove(filetools.join(item.path, fd)):
                    num_enlaces += 1
                    # Remove strm and nfo if no other channel
                    episode = fd.replace(' [' + canal + '].json', '')
                    found_ch = False
                    for ch in channels:
                        if filetools.exists(filetools.join(item.path, episode + ' [' + ch + '].json')):
                            found_ch = True
                            break
                    if found_ch == False:
                        filetools.remove(filetools.join(item.path, episode + '.nfo'))
                        strm_path = filetools.join(item.path, episode + '.strm')
                        # if it is a local episode, do not delete the strm
                        if 'plugin://plugin.video.s4me/?' in filetools.read(strm_path):
                            filetools.remove(strm_path)
                            path_list.append(filetools.join(item.extra, episode + '.strm'))

        if config.is_xbmc() and config.get_setting("videolibrary_kodi") and path_list:
            from platformcode import xbmc_videolibrary
            xbmc_videolibrary.clean(path_list)

        if num_enlaces > 0:
            # Update .nfo
            head_nfo, item_nfo = videolibrarytools.read_nfo(item.nfo)
            del item_nfo.library_urls[canal]
            if item_nfo.emergency_urls and item_nfo.emergency_urls.get(canal, False):
                del item_nfo.emergency_urls[canal]
            filetools.write(item.nfo, head_nfo + item_nfo.tojson())
            platformtools.itemlist_refresh()
        return num_enlaces
    else:
        if platformtools.dialog_yesno(heading, config.get_localized_string(70088) % item.infoLabels['title']):
            delete_all(item)
            return 1
        else:
            return 0


def check_season_playcount(item, season):
    logger.debug()

    if season:
        episodios_temporada = 0
        episodios_vistos_temporada = 0
        for key, value in item.library_playcounts.items():
            if key.startswith("%sx" % season):
                episodios_temporada += 1
                if value > 0:
                    episodios_vistos_temporada += 1

        if episodios_temporada == episodios_vistos_temporada:
            # it is verified that if all the seasons are seen, the series is marked as view
            item.library_playcounts.update({"season %s" % season: 1})
        else:
            # it is verified that if all the seasons are seen, the series is marked as view
            item.library_playcounts.update({"season %s" % season: 0})

    return check_tvshow_playcount(item, season)


def check_tvshow_playcount(item, season):
    logger.debug()
    if season:
        temporadas_serie = 0
        temporadas_vistas_serie = 0
        for key, value in item.library_playcounts.items():
            if key.startswith("season" ):
                temporadas_serie += 1
                if value > 0:
                    temporadas_vistas_serie += 1

        if temporadas_serie == temporadas_vistas_serie:
            item.library_playcounts.update({item.title: 1})
        else:
            item.library_playcounts.update({item.title: 0})

    else:
        playcount = item.library_playcounts.get(item.title, 0)
        item.library_playcounts.update({item.title: playcount})

    return item


def add_download_items(item, itemlist):
    if config.get_setting('downloadenabled'):
        localOnly = True
        for i in itemlist:
            if i.contentChannel != 'local':
                localOnly = False
                break
        if not item.fromLibrary and not localOnly:
            downloadItem = Item(channel='downloads',
                                from_channel=item.channel,
                                title=typo(config.get_localized_string(60355), "color std bold"),
                                fulltitle=item.fulltitle,
                                show=item.fulltitle,
                                contentType=item.contentType,
                                contentSerieName=item.contentSerieName,
                                url=item.url,
                                action='save_download',
                                from_action="findvideos",
                                contentTitle=item.contentTitle,
                                path=item.path,
                                thumbnail=thumb('downloads'),
                                parent=item.tourl())
            if item.action == 'findvideos':
                if item.contentType != 'movie':
                    downloadItem.title = '{} {}'.format(typo(config.get_localized_string(60356), "color std bold"), item.title)
                else:  # film
                    downloadItem.title = typo(config.get_localized_string(60354), "color std bold")
                downloadItem.downloadItemlist = [i.tourl() for i in itemlist]
                itemlist.append(downloadItem)
            else:
                if item.contentSeason:  # season
                    downloadItem.title = typo(config.get_localized_string(60357), "color std bold")
                    itemlist.append(downloadItem)
                else:  # tvshow + not seen
                    itemlist.append(downloadItem)
                    itemlist.append(downloadItem.clone(title=typo(config.get_localized_string(60003), "color std bold"), unseen=True))