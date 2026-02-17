# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Configuracion
# ------------------------------------------------------------

from __future__ import division
#from builtins import str
import sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int
from builtins import range
from past.utils import old_div

from channelselector import get_thumb
from core import filetools, servertools
from core.item import Item
from platformcode import config, logger, platformtools

CHANNELNAME = "setting"


def menu_channels(item):
    logger.debug()
    itemlist = list()

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60545), action="conf_tools", folder=False,
                         extra="channels_onoff", thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60546) + ":", action="", folder=False,
                         text_bold = True, thumbnail=get_thumb("setting_0.png")))

    # Home - Configurable channels
    import channelselector
    from core import channeltools
    channel_list = channelselector.filterchannels("all")
    for channel in channel_list:
        if not channel.channel:
            continue
        channel_parameters = channeltools.get_channel_parameters(channel.channel)
        if channel_parameters["has_settings"]:
            itemlist.append(Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60547) % channel.title,
                                 action="channel_config", config=channel.channel, folder=False,
                                 thumbnail=channel.thumbnail))
    # End - Configurable channels
    itemlist.append(Item(channel=CHANNELNAME, action="", title="", folder=False, thumbnail=get_thumb("setting_0.png")))
    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60548) + ":", action="", folder=False,
                         text_bold=True, thumbnail=get_thumb("channels.png")))
    itemlist.append(Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60549), action="conf_tools",
                         folder=True, extra="lib_check_datajson", thumbnail=get_thumb("channels.png")))
    return itemlist


def channel_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "channels", item.config))


# def setting_torrent(item):
#     logger.debug()

#     LIBTORRENT_PATH = config.get_setting("libtorrent_path", server="torrent", default="")
#     LIBTORRENT_ERROR = config.get_setting("libtorrent_error", server="torrent", default="")
#     default = config.get_setting("torrent_client", server="torrent", default=0)
#     BUFFER = config.get_setting("mct_buffer", server="torrent", default="50")
#     DOWNLOAD_PATH = config.get_setting("mct_download_path", server="torrent", default=config.get_setting("downloadpath"))
#     if not DOWNLOAD_PATH: DOWNLOAD_PATH = filetools.join(config.get_data_path(), 'downloads')
#     BACKGROUND = config.get_setting("mct_background_download", server="torrent", default=True)
#     RAR = config.get_setting("mct_rar_unpack", server="torrent", default=True)
#     DOWNLOAD_LIMIT = config.get_setting("mct_download_limit", server="torrent", default="")
#     BUFFER_BT = config.get_setting("bt_buffer", server="torrent", default="50")
#     DOWNLOAD_PATH_BT = config.get_setting("bt_download_path", server="torrent", default=config.get_setting("downloadpath"))
#     if not DOWNLOAD_PATH_BT: DOWNLOAD_PATH_BT = filetools.join(config.get_data_path(), 'downloads')
#     MAGNET2TORRENT = config.get_setting("magnet2torrent", server="torrent", default=False)

#     torrent_options = [config.get_localized_string(30006), config.get_localized_string(70254), config.get_localized_string(70255)]
#     torrent_options.extend(platformtools.torrent_client_installed())


#     list_controls = [
#         {
#             "id": "libtorrent_path",
#             "type": "text",
#             "label": "Libtorrent path",
#             "default": LIBTORRENT_PATH,
#             "enabled": True,
#             "visible": False
#         },
#         {
#             "id": "libtorrent_error",
#             "type": "text",
#             "label": "libtorrent error",
#             "default": LIBTORRENT_ERROR,
#             "enabled": True,
#             "visible": False
#         },
#         {
#             "id": "list_torrent",
#             "type": "list",
#             "label": config.get_localized_string(70256),
#             "default": default,
#             "enabled": True,
#             "visible": True,
#             "lvalues": torrent_options
#         },
#         {
#             "id": "mct_buffer",
#             "type": "text",
#             "label": "MCT - " + config.get_localized_string(70758),
#             "default": BUFFER,
#             "enabled": True,
#             "visible": "eq(-1,%s)" % torrent_options[2]
#         },
#         {
#             "id": "mct_download_path",
#             "type": "text",
#             "label": "MCT - " + config.get_localized_string(30017),
#             "default": DOWNLOAD_PATH,
#             "enabled": True,
#             "visible": "eq(-2,%s)" % torrent_options[2]
#         },
#         {
#             "id": "bt_buffer",
#             "type": "text",
#             "label": "BT - " + config.get_localized_string(70758),
#             "default": BUFFER_BT,
#             "enabled": True,
#             "visible": "eq(-3,%s)" % torrent_options[1]
#         },
#         {
#             "id": "bt_download_path",
#             "type": "text",
#             "label": "BT - " + config.get_localized_string(30017),
#             "default": DOWNLOAD_PATH_BT,
#             "enabled": True,
#             "visible": "eq(-4,%s)" % torrent_options[1]
#         },
#         {
#             "id": "mct_download_limit",
#             "type": "text",
#             "label": config.get_localized_string(70759),
#             "default": DOWNLOAD_LIMIT,
#             "enabled": True,
#             "visible": "eq(-5,%s) | eq(-5,%s)" % (torrent_options[1], torrent_options[2])
#         },
#         {
#             "id": "mct_rar_unpack",
#             "type": "bool",
#             "label": config.get_localized_string(70760),
#             "default": RAR,
#             "enabled": True,
#             "visible": True
#         },
#         {
#             "id": "mct_background_download",
#             "type": "bool",
#             "label": config.get_localized_string(70761),
#             "default": BACKGROUND,
#             "enabled": True,
#             "visible": True
#         },
#         {
#             "id": "magnet2torrent",
#             "type": "bool",
#             "label": config.get_localized_string(70762),
#             "default": MAGNET2TORRENT,
#             "enabled": True,
#             "visible": True
#         }
#     ]

#     platformtools.show_channel_settings(list_controls=list_controls, callback='save_setting_torrent', item=item,
#                                         caption=config.get_localized_string(70257), custom_button={'visible': False})


# def save_setting_torrent(item, dict_data_saved):
#     if dict_data_saved and "list_torrent" in dict_data_saved:
#         config.set_setting("torrent_client", dict_data_saved["list_torrent"], server="torrent")
#     if dict_data_saved and "mct_buffer" in dict_data_saved:
#         config.set_setting("mct_buffer", dict_data_saved["mct_buffer"], server="torrent")
#     if dict_data_saved and "mct_download_path" in dict_data_saved:
#         config.set_setting("mct_download_path", dict_data_saved["mct_download_path"], server="torrent")
#     if dict_data_saved and "mct_background_download" in dict_data_saved:
#         config.set_setting("mct_background_download", dict_data_saved["mct_background_download"], server="torrent")
#     if dict_data_saved and "mct_rar_unpack" in dict_data_saved:
#         config.set_setting("mct_rar_unpack", dict_data_saved["mct_rar_unpack"], server="torrent")
#     if dict_data_saved and "mct_download_limit" in dict_data_saved:
#         config.set_setting("mct_download_limit", dict_data_saved["mct_download_limit"], server="torrent")
#     if dict_data_saved and "bt_buffer" in dict_data_saved:
#         config.set_setting("bt_buffer", dict_data_saved["bt_buffer"], server="torrent")
#     if dict_data_saved and "bt_download_path" in dict_data_saved:
#         config.set_setting("bt_download_path", dict_data_saved["bt_download_path"], server="torrent")
#     if dict_data_saved and "magnet2torrent" in dict_data_saved:
#         config.set_setting("magnet2torrent", dict_data_saved["magnet2torrent"], server="torrent")

def menu_servers(item):
    logger.debug()
    itemlist = list()

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60550), action="servers_blacklist", folder=False,
                         thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60551),
                         action="servers_favorites", folder=False, thumbnail=get_thumb("setting_0.png")))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60552),
                         action="", folder=False, text_bold = True, thumbnail=get_thumb("setting_0.png")))

    # Home - Configurable servers

    server_list = list(servertools.get_debriders_list().keys())
    for server in server_list:
        server_parameters = servertools.get_server_parameters(server)
        if server_parameters["has_settings"]:
            itemlist.append(
                Item(channel=CHANNELNAME, title = ".    " + config.get_localized_string(60553) % server_parameters["name"],
                     action="server_debrid_config", config=server, folder=False, thumbnail=""))

    itemlist.append(Item(channel=CHANNELNAME, title=config.get_localized_string(60554),
                         action="", folder=False, text_bold = True, thumbnail=get_thumb("setting_0.png")))

    server_list = list(servertools.get_servers_list().keys())

    for server in sorted(server_list):
        server_parameters = servertools.get_server_parameters(server)
        logger.debug(server_parameters)
        if server_parameters["has_settings"] and [x for x in server_parameters["settings"] if x["id"] not in ["black_list", "white_list"]]:
            itemlist.append(
                Item(channel=CHANNELNAME, title=".    " + config.get_localized_string(60553) % server_parameters["name"],
                     action="server_config", config=server, folder=False, thumbnail=""))

    # End - Configurable servers

    return itemlist


def server_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "servers", item.config))

def server_debrid_config(item):
    return platformtools.show_channel_settings(channelpath=filetools.join(config.get_runtime_path(), "servers", "debriders", item.config))


def servers_blacklist(item):
    server_list = servertools.get_servers_list()
    black_list = config.get_setting("black_list", server='servers', default=[])
    blacklisted = []

    list_controls = []
    list_servers = []

    for i, server in enumerate(sorted(server_list.keys())):
        server_parameters = server_list[server]
        defaults = servertools.get_server_parameters(server)

        control = server_parameters["name"]
        # control.setArt({'thumb:': server_parameters['thumb'] if 'thumb' in server_parameters else config.get_online_server_thumb(server)})
        if not config.get_setting("black_list", server=server):
            list_controls.append(control)
            if defaults.get("black_list", False) or server in black_list:
                blacklisted.append(i)
        list_servers.append(server)
    ris = platformtools.dialog_multiselect(config.get_localized_string(60550), list_controls, preselect=blacklisted)
    if ris is not None:
        config.set_setting("black_list", [l for n, l in enumerate(list_servers) if n in ris], server='servers')
    # if ris is not None:
    #     cb_servers_blacklist({list_servers[n]: True if n in ris else False for n, it in enumerate(list_controls)})
    # return platformtools.show_channel_settings(list_controls=list_controls, dict_values=dict_values, caption=config.get_localized_string(60550), callback="cb_servers_blacklist")


# def cb_servers_blacklist(dict_values):
#     blaklisted = [k for k in dict_values.keys()]
    # progreso = platformtools.dialog_progress(config.get_localized_string(60557), config.get_localized_string(60558))
    # n = len(dict_values)
    # i = 1
    # for k, v in list(dict_values.items()):
    #     if v:  # If the server is blacklisted it cannot be in the favorites list
    #         config.set_setting("favorites_servers_list", 0, server=k)
    #         blaklisted.append(k)
    #         progreso.update(old_div((i * 100), n), config.get_localized_string(60559) % k)
    #     i += 1
    # config.set_setting("black_list", blaklisted, server='servers')

    # progreso.close()


def servers_favorites(item):
    server_list = servertools.get_servers_list()
    dict_values = {}

    list_controls = [{'id': 'favorites_servers',
                      'type': 'bool',
                      'label': config.get_localized_string(60577),
                      'default': False,
                      'enabled': True,
                      'visible': True},
                     {'id': 'quality_priority',
                      'type': 'bool',
                      'label': config.get_localized_string(30069),
                      'default': False,
                      'enabled': 'eq(-1,True)',
                      'visible': True}]
    dict_values['favorites_servers'] = config.get_setting('favorites_servers')
    dict_values['quality_priority'] = config.get_setting('quality_priority')
    if dict_values['favorites_servers'] == None:
        dict_values['favorites_servers'] = False

    server_names = [config.get_localized_string(59992)]
    favorites = config.get_setting("favorites_servers_list", server='servers', default=[])
    blacklisted = config.get_setting("black_list", server='servers', default=[])

    for server in sorted(server_list.keys()):
        if server in blacklisted or config.get_setting("black_list", server=server):
            continue

        server_names.append(server_list[server]['name'])
        if server in favorites:
            orden = favorites.index(server) + 1
            dict_values[orden] = len(server_names) - 1

    for x in range(1, 12):
        control = {'id': x,
                   'type': 'list',
                   'label': config.get_localized_string(60597) % x,
                   'lvalues': server_names,
                   'default': 0,
                   'enabled': 'eq(-%s,True)' % str(x + 1),
                   'visible': True}
        list_controls.append(control)

    return platformtools.show_channel_settings(list_controls=list_controls, dict_values=dict_values, item=server_names,
                                               caption=config.get_localized_string(60551), callback="cb_servers_favorites")


def cb_servers_favorites(server_names, dict_values):
    dict_name = {}
    dict_favorites = {}

    for i, v in list(dict_values.items()):
        if i == "favorites_servers":
            config.set_setting("favorites_servers", v)
        elif i == "quality_priority":
            config.set_setting("quality_priority", v)
        elif int(v) > 0:
            dict_name[server_names[v]] = int(i)

    servers_list = list(servertools.get_servers_list().items())
    for server, server_parameters in servers_list:
        if server_parameters['name'] in list(dict_name.keys()):
            dict_favorites[dict_name[server_parameters['name']]] = server

    favorites_servers_list = [dict_favorites[k] for k in sorted(dict_favorites.keys())]

    config.set_setting("favorites_servers_list", favorites_servers_list, server='servers')

    if not favorites_servers_list:  # If there is no server in the list, deactivate it
        config.set_setting("favorites_servers", False)


def settings(item):
    config.open_settings()


def check_quickfixes(item):
    logger.debug()

    if not config.dev_mode():
        from platformcode import updater
        if not updater.check()[0]:
            platformtools.dialog_ok(config.get_localized_string(20000), config.get_localized_string(70667))
    else:
        return False


# def update_quasar(item):
#     logger.debug()

#     from platformcode import custom_code, platformtools
#     stat = False
#     stat = custom_code.update_external_addon("quasar")
#     if stat:
#         platformtools.dialog_notification("Actualización Quasar", "Realizada con éxito")
#     else:
#         platformtools.dialog_notification("Actualización Quasar", "Ha fallado. Consulte el log")


def conf_tools(item):
    logger.debug()

    # Enable or disable channels
    if item.extra == "channels_onoff":
        if config.get_platform(True)['num_version'] >= 17.0: # From Kodi 16 you can use multiselect, and from 17 with preselect
            return channels_onoff(item)

        import channelselector
        from core import channeltools

        channel_list = channelselector.filterchannels("allchannelstatus")

        excluded_channels = ['url',
                             'search',
                             'videolibrary',
                             'setting',
                             'news',
                             # 'help',
                             'downloads']

        list_controls = []
        try:
            list_controls.append({'id': "all_channels",
                                  'type': "list",
                                  'label': config.get_localized_string(60594),
                                  'default': 0,
                                  'enabled': True,
                                  'visible': True,
                                  'lvalues': ['',
                                              config.get_localized_string(60591),
                                              config.get_localized_string(60592),
                                              config.get_localized_string(60593)]})

            for channel in channel_list:
                # If the channel is on the exclusion list, we skip it
                if channel.channel not in excluded_channels:

                    channel_parameters = channeltools.get_channel_parameters(channel.channel)

                    status_control = ""
                    status = config.get_setting("enabled", channel.channel)
                    # if status does not exist, there is NO value in _data.json
                    if status is None:
                        status = channel_parameters["active"]
                        logger.debug("%s | Status (XML): %s" % (channel.channel, status))
                        if not status:
                            status_control = config.get_localized_string(60595)
                    else:
                        logger.debug("%s  | Status: %s" % (channel.channel, status))

                    control = {'id': channel.channel,
                               'type': "bool",
                               'label': channel_parameters["title"] + status_control,
                               'default': status,
                               'enabled': True,
                               'visible': True}
                    list_controls.append(control)

                else:
                    continue

        except:
            import traceback
            logger.error("Error: %s" % traceback.format_exc())
        else:
            return platformtools.show_channel_settings(list_controls=list_controls,
                                                       item=item.clone(channel_list=channel_list),
                                                       caption=config.get_localized_string(60596),
                                                       callback="channel_status",
                                                       custom_button={"visible": False})

    # Checking channel_data.json files
    elif item.extra == "lib_check_datajson":
        itemlist = []
        import channelselector
        from core import channeltools
        channel_list = channelselector.filterchannels("allchannelstatus")

        # Having an exclusion list doesn't make much sense because it checks if channel.json has "settings", but just in case it is left
        excluded_channels = ['url',
                             'setting',
                             'help']

        try:
            import os
            from core import jsontools
            for channel in channel_list:

                list_status = None
                default_settings = None

                # It is checked if the channel is in the exclusion list
                if channel.channel not in excluded_channels:
                    # It is checked that it has "settings", otherwise it skips
                    list_controls, dict_settings = channeltools.get_channel_controls_settings(channel.channel)

                    if not list_controls:
                        itemlist.append(Item(channel=CHANNELNAME,
                                             title=channel.title + config.get_localized_string(60569),
                                             action="", folder=False,
                                             thumbnail=channel.thumbnail))
                        continue
                        # logger.debug(channel.channel + " SALTADO!")

                    # The json file settings of the channel are loaded
                    file_settings = os.path.join(config.get_data_path(), "settings_channels", channel.channel + "_data.json")
                    dict_settings = {}
                    dict_file = {}
                    if filetools.exists(file_settings):
                        # logger.debug(channel.channel + " Has _data.json file")
                        channeljson_exists = True
                        # We get saved settings from ../settings/channel_data.json
                        try:
                            dict_file = jsontools.load(filetools.read(file_settings))
                            if isinstance(dict_file, dict) and 'settings' in dict_file:
                                dict_settings = dict_file['settings']
                        except EnvironmentError:
                            logger.error("ERROR when reading the file: %s" % file_settings)
                    else:
                        # logger.debug(channel.channel + " No _data.json file")
                        channeljson_exists = False

                    if channeljson_exists:
                        try:
                            datajson_size = filetools.getsize(file_settings)
                        except:
                            import traceback
                            logger.error(channel.title + config.get_localized_string(60570) % traceback.format_exc())
                    else:
                        datajson_size = None

                    # If the _data.json is empty or does not exist ...
                    if (len(dict_settings) and datajson_size) == 0 or not channeljson_exists:
                        # We get controls from the file ../channels/channel.json
                        needsfix = True
                        try:
                            # Default settings are loaded
                            list_controls, default_settings = channeltools.get_channel_controls_settings(
                                channel.channel)
                            # logger.debug(channel.title + " | Default: %s" % default_settings)
                        except:
                            import traceback
                            logger.error(channel.title + config.get_localized_string(60570) % traceback.format_exc())
                            # default_settings = {}

                        # If _data.json needs to be repaired or doesn't exist ...
                        if needsfix or not channeljson_exists:
                            if default_settings is not None:
                                # We create the channel_data.json
                                default_settings.update(dict_settings)
                                dict_settings = default_settings
                                dict_file['settings'] = dict_settings
                                # We create the file ../settings/channel_data.json
                                if not filetools.write(file_settings, jsontools.dump(dict_file), silent=True):
                                    logger.error("ERROR saving file: %s" % file_settings)
                                list_status = config.get_localized_string(60560)
                            else:
                                if default_settings is None:
                                    list_status = config.get_localized_string(60571)

                    else:
                        # logger.debug(channel.channel + " - NO correction needed!")
                        needsfix = False

                    # If the channel status has been set it is added to the list
                    if needsfix is not None:
                        if needsfix:
                            if not channeljson_exists:
                                list_status = config.get_localized_string(60588)
                                list_colour = "red"
                            else:
                                list_status = config.get_localized_string(60589)
                                list_colour = "green"
                        else:
                            # If "needsfix" is "false" and "datjson_size" is None, an error will have occurred
                            if datajson_size is None:
                                list_status = config.get_localized_string(60590)
                                list_colour = "red"
                            else:
                                list_status = config.get_localized_string(60589)
                                list_colour = "green"

                    if list_status is not None:
                        itemlist.append(Item(channel=CHANNELNAME,
                                             title=channel.title + list_status,
                                             action="", folder=False,
                                             thumbnail=channel.thumbnail,
                                             text_color=list_colour))
                    else:
                        logger.error("Something is wrong with the channel %s" % channel.channel)

                # If the channel is on the exclusion list, we skip it
                else:
                    continue
        except:
            import traceback
            logger.error("Error: %s" % traceback.format_exc())

        return itemlist


def channels_onoff(item):
    import channelselector, xbmcgui
    from core import channeltools

    # Load list of options
    # ------------------------
    lista = []; ids = []
    channels_list = channelselector.filterchannels('allchannelstatus')
    for channel in channels_list:
        channel_parameters = channeltools.get_channel_parameters(channel.channel)
        lbl = '%s' % channel_parameters['language']
        # ~ lbl += ' %s' % [config.get_localized_category(categ) for categ in channel_parameters['categories']]
        lbl += ' %s' % ', '.join(config.get_localized_category(categ) for categ in channel_parameters['categories'])

        it = xbmcgui.ListItem(channel.title, lbl)
        it.setArt({ 'thumb': channel.thumbnail, 'fanart': channel.fanart })
        lista.append(it)
        ids.append(channel.channel)

    # Dialog to pre-select
    # ----------------------------
    preselecciones = [config.get_localized_string(70517), config.get_localized_string(70518), config.get_localized_string(70519)]
    ret = platformtools.dialog_select(config.get_localized_string(60545), preselecciones)
    if ret == -1: return False # order cancel
    if ret == 2: preselect = []
    elif ret == 1: preselect = list(range(len(ids)))
    else:
        preselect = []
        for i, canal in enumerate(ids):
            channel_status = config.get_setting('enabled', canal)
            if channel_status is None: channel_status = True
            if channel_status:
                preselect.append(i)

    # Dialog to select
    # ------------------------
    ret = platformtools.dialog_multiselect(config.get_localized_string(60545), lista, preselect=preselect, useDetails=True)
    if ret == None: return False # order cancel
    seleccionados = [ids[i] for i in ret]

    # Save changes to activated channels
    # ------------------------------------
    for canal in ids:
        channel_status = config.get_setting('enabled', canal)
        if channel_status is None: channel_status = True

        if channel_status and canal not in seleccionados:
            config.set_setting('enabled', False, canal)
        elif not channel_status and canal in seleccionados:
            config.set_setting('enabled', True, canal)

    return False


def channel_status(item, dict_values):
    try:
        for k in dict_values:

            if k == "all_channels":
                logger.info("All channels | Selected state: %s" % dict_values[k])
                if dict_values[k] != 0:
                    excluded_channels = ['url', 'search',
                                         'videolibrary', 'setting',
                                         'news',
                                         'help',
                                         'downloads']

                    for channel in item.channel_list:
                        if channel.channel not in excluded_channels:
                            from core import channeltools
                            channel_parameters = channeltools.get_channel_parameters(channel.channel)
                            new_status_all = None
                            new_status_all_default = channel_parameters["active"]

                            # Option Activate all
                            if dict_values[k] == 1:
                                new_status_all = True

                            # Option Deactivate all
                            if dict_values[k] == 2:
                                new_status_all = False

                            # Retrieve default status option
                            if dict_values[k] == 3:
                                # If you have "enabled" in the _data.json, it is because the state is not that of the channel.json
                                if config.get_setting("enabled", channel.channel):
                                    new_status_all = new_status_all_default

                                # If the channel does not have "enabled" in the _data.json it is not saved, it goes to the next
                                else:
                                    continue

                            # Channel status is saved
                            if new_status_all is not None:
                                config.set_setting("enabled", new_status_all, channel.channel)
                    break
                else:
                    continue

            else:
                logger.info("Channel: %s | State: %s" % (k, dict_values[k]))
                config.set_setting("enabled", dict_values[k], k)
                logger.info("the value is like %s " % config.get_setting("enabled", k))

        platformtools.itemlist_update(Item(channel=CHANNELNAME, action="mainlist"))

    except:
        import traceback
        logger.error("Error detail: %s" % traceback.format_exc())
        platformtools.dialog_notification(config.get_localized_string(60579), config.get_localized_string(60580))


def restore_tools(item):
    import service
    from core import videolibrarytools
    import os

    seleccion = platformtools.dialog_yesno(config.get_localized_string(60581),
                                           config.get_localized_string(60582) + '\n' +
                                           config.get_localized_string(60583))
    if seleccion == 1:
        # tvshows
        heading = config.get_localized_string(60584)
        p_dialog = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
        p_dialog.update(0, '')

        show_list = []
        for path, folders, files in filetools.walk(videolibrarytools.TVSHOWS_PATH):
            show_list.extend([filetools.join(path, f) for f in files if f == "tvshow.nfo"])

        if show_list:
            t = float(100) / len(show_list)

        for i, tvshow_file in enumerate(show_list):
            head_nfo, serie = videolibrarytools.read_nfo(tvshow_file)
            path = filetools.dirname(tvshow_file)

            #if not serie.active:
                # if the series is not active discard
            #    continue

            # We delete the folder with the series ...
            if tvshow_file.endswith('.strm') or tvshow_file.endswith('.json') or tvshow_file.endswith('.nfo'):
                os.remove(os.path.join(path, tvshow_file))
            # filetools.rmdirtree(path)

            # ... and we add it again
            service.update(path, p_dialog, i, t, serie, 3)
        p_dialog.close()

        # movies
        heading = config.get_localized_string(60586)
        p_dialog2 = platformtools.dialog_progress_bg(config.get_localized_string(20000), heading)
        p_dialog2.update(0, '')

        movies_list = []
        for path, folders, files in filetools.walk(videolibrarytools.MOVIES_PATH):
            movies_list.extend([filetools.join(path, f) for f in files if f.endswith(".json")])

        logger.debug("movies_list %s" % movies_list)

        if movies_list:
            t = float(100) / len(movies_list)

        for i, movie_json in enumerate(movies_list):
            try:
                from core import jsontools
                path = filetools.dirname(movie_json)
                movie = Item().fromjson(filetools.read(movie_json))

                # We delete the folder with the movie ...
                filetools.rmdirtree(path)

                import math
                heading = config.get_localized_string(20000)

                p_dialog2.update(int(math.ceil((i + 1) * t)), heading, config.get_localized_string(60389) % (movie.contentTitle,
                                                                                   movie.channel.capitalize()))
                # ... and we add it again
                videolibrarytools.save_movie(movie)
            except Exception as ex:
                logger.error("Error creating movie again")
                template = "An exception of type %s occured. Arguments:\n%r"
                message = template % (type(ex).__name__, ex.args)
                logger.error(message)

        p_dialog2.close()


def report_menu(item):
    logger.debug('URL: ' + item.url)

    from channelselector import get_thumb

    thumb_debug = get_thumb("update.png")
    thumb_error = get_thumb("error.png")
    thumb_next = get_thumb("next.png")
    itemlist = []
    paso = 1

    # Create a menu of options to allow the user to report an Alpha failure through a "pastebin" server
    # For the report to be complete, the user must have the option DEBUG = ON
    # Free pastbin servers have capacity limitations, so the size of the log is important
    # At the end of the upload operation, the user is passed the log address on the server to report them

    itemlist.append(Item(channel=item.channel, action="", title=config.get_localized_string(707418),
                thumbnail=thumb_next, folder=False))
    # if not config.get_setting('debug'):
    itemlist.append(Item(channel=item.channel, action="activate_debug", extra=True,
                    title=config.get_localized_string(707419) %
                    str(paso), thumbnail=thumb_debug, folder=False))
    paso += 1
    itemlist.append(Item(channel="channelselector", action="getmainlist",
                    title=config.get_localized_string(707420) %
                    str(paso), thumbnail=thumb_debug))
    paso += 1
    itemlist.append(Item(channel=item.channel, action="report_send",
                    title=config.get_localized_string(707421) %
                    str(paso), thumbnail=thumb_error, folder=False))
    paso += 1
    # if config.get_setting('debug'):
    itemlist.append(Item(channel=item.channel, action="activate_debug", extra=False,
                    title=config.get_localized_string(707422) % str(paso),
                    thumbnail=thumb_debug, folder=False))
    paso += 1

    if item.url:
        itemlist.append(Item(channel=item.channel, action="", title="", folder=False))

        itemlist.append(Item(channel=item.channel, action="",
                    title=config.get_localized_string(707423),
                    thumbnail=thumb_next, folder=False))

        if item.one_use:
            action = ''
            url = ''
        else:
            action = 'call_browser'
            url = item.url
        itemlist.append(Item(channel=item.channel, action=action,
                    title="LOG: [COLOR gold]%s[/COLOR]" % item.url, url=url,
                    thumbnail=thumb_next, unify=False, folder=False))
        if item.one_use:
            itemlist.append(Item(channel=item.channel, action="",
                    title=config.get_localized_string(60305),
                    thumbnail=thumb_next, folder=False))
            itemlist.append(Item(channel=item.channel, action="",
                    title=config.get_localized_string(60308),
                    thumbnail=thumb_next, folder=False))
        itemlist.append(Item(channel=item.channel, action="call_browser",
                             title="su Github (raccomandato)", url='https://github.com/stream4me/addon/issues',
                             thumbnail=thumb_next,
                             folder=False))

    return itemlist


def activate_debug(item):
    logger.info(item.extra)
    from platformcode import platformtools

    #Enable / disable DEBUB option in settings.xml

    if isinstance(item.extra, str):
        return report_menu(item)
    if item.extra:
        config.set_setting('debug', True)
        platformtools.dialog_notification(config.get_localized_string(707430), config.get_localized_string(707431))
    else:
        config.set_setting('debug', False)
        platformtools.dialog_notification(config.get_localized_string(707430), config.get_localized_string(707432))


def report_send(item, description='', fatal=False):
    import xbmc
    import random
    import traceback

    if PY3:
        # from future import standard_library
        # standard_library.install_aliases()
        import urllib.parse as urlparse                         # It is very slow in PY2. In PY3 it is native
        import urllib.parse as urllib
    else:
        import urllib                                           # We use the native of PY2 which is faster
        import urlparse

    try:
        requests_status = True
        import requests
    except:
        requests_status = False
        logger.error(traceback.format_exc())

    from core import jsontools, httptools, scrapertools
    from platformcode import envtal

    # This function performs the LOG upload operation. The file size is of great importance because
    # Free pastebin services have limitations, sometimes very low.
    # There is an ervice, File.io, that allows direct upload of "binary files" through the "request" function
    # This dramatically increases the ability to send the log, well above what is needed.
    # Therefore it is necessary to have a list of "pastebin" services that can perform the upload operation,
    # either by available capacity or by availability.
    # In order to use the "pastebin" servers with a common code, a dictionary has been created with the servers
    # and their characteristics. In each entry the peculiarities of each server are collected, both to form
    # the request with POST as for the way to receive the upload code in the response (json, header, regex
    # in data, ...).
    # Starting this method randomizes the list of "pastebin" servers to prevent all users from doing
    # uploads against the same server and may cause overloads.
    # The log file is read and its size is compared with the server capacity (parameter 10 of each entry
    # (starting from 0), expressed in MB, until a qualified one is found. If the upload fails, it continues trying
    # with the following servers that have the required capacity.
    # If no available server is found, the user is asked to try again later, or to upload the log.
    # directly on the forum. If it is a size problem, you are asked to reset Kodi and redo the fault, to
    # that the LOG is smaller.

    pastebin_list = {
        'hastebin': ('1', 'https://hastebin.com/', 'documents', 'random', '', '',
                    'data', 'json', 'key', '', '0.29', '10', True, 'raw/', '', ''),
        'dpaste': ('1', 'http://dpaste.com/', 'api/v2/', 'random', 'content=',
                    '&syntax=text&title=%s&poster=alfa&expiry_days=7',
                    'headers', '', '', 'location', '0.23', '15', True, '', '.txt', ''),
        'ghostbin': ('1', 'https://ghostbin.com/', 'paste/new', 'random', 'lang=text&text=',
                    '&expire=2d&password=&title=%s',
                    'data', 'regex', '<title>(.*?)\s*-\s*Ghostbin<\/title>', '',
                    '0.49', '15', False, 'paste/', '', ''),
        'write.as': ('1', 'https://write.as/', 'api/posts', 'random', 'body=', '&title=%s',
                    'data', 'json', 'data', 'id', '0.018', '15', True, '', '', ''),
        'oneclickpaste': ('1', 'http://oneclickpaste.com/', 'index.php', 'random', 'paste_data=',
                    '&title=%s&format=text&paste_expire_date=1W&visibility=0&pass=&submit=Submit',
                    'data', 'regex', '<a class="btn btn-primary" href="[^"]+\/(\d+\/)">\s*View\s*Paste\s*<\/a>',
                    '', '0.060', '5', True, '', '', ''),
        'bpaste': ('1', 'https://bpaste.net/', '', 'random', 'code=', '&lexer=text&expiry=1week',
                    'data', 'regex', 'View\s*<a\s*href="[^*]+/(.*?)">raw<\/a>', '',
                    '0.79', '15', True, 'raw/', '', ''),
        'dumpz': ('0', 'http://dumpz.org/', 'api/dump', 'random', 'code=', '&lexer=text&comment=%s&password=',
                    'headers', '', '', 'location', '0.99', '15', False, '', '', ''),
        'file.io': ('1', 'https://file.io/', '', 'random', '', 'expires=1w',
                    'requests', 'json', 'key', '', '99.0', '30', False, '', '', ''),
        'uploadfiles': ('0', 'https://up.ufile.io/v1/upload', '', 'random', '', '',
                    'curl', 'json', 'url', '', '99.0', '30', False, None, '', {'Referer': 'https://ufile.io/'})
        # 'anonfiles': ('1', 'https://api.anonfiles.com/upload', 'upload', 'random', '', '',
        #             'requests', 'json', 'data', 'file,url,short', '99.0', '30', False, None, '', '')
                     }
    pastebin_list_last = ['hastebin', 'ghostbin', 'file.io']            # We leave these services the last
    pastebin_one_use = ['file.io']                                      # Single-use servers and deletes
    pastebin_dir = []
    paste_file = {}
    paste_params = ()
    paste_post = ''
    status = False
    msg = config.get_localized_string(707424)

    # DEBUG = ON is verified, if it is not it is rejected and the user is asked to activate it and reproduce the fault
    if not config.get_setting('debug'):
        platformtools.dialog_notification(config.get_localized_string(707425), config.get_localized_string(707426))
        return report_menu(item)

    # From each to the future the user will be allowed to enter a brief description of the fault that will be added to the LOG
    if description == 'OK':
        description = platformtools.dialog_input('', 'Introduzca una breve descripción del fallo')

    # We write in the log some Kodi and Alpha variables that will help us diagnose the failure
    environment = envtal.list_env()
    if not environment['log_path']:
        environment['log_path'] = str(filetools.join(xbmc.translatePath("special://logpath/"), 'kodi.log'))
        environment['log_size_bytes'] = str(filetools.getsize(environment['log_path']))
        environment['log_size'] = str(round(float(environment['log_size_bytes']) / (1024*1024), 3))

    # LOG file is read
    log_path = environment['log_path']
    if filetools.exists(log_path):
        log_size_bytes = int(environment['log_size_bytes'])             # File size in Bytes
        log_size = float(environment['log_size'])                       # File size in MB
        log_data = filetools.read(log_path)                             # File data
        if not log_data:                                                # Some mistake?
            platformtools.dialog_notification(config.get_localized_string(707427), '', 2)
            return report_menu(item)
    else:                                                               # Log no existe or erroneous path?
        platformtools.dialog_notification(config.get_localized_string(707427), '', 2)
        return report_menu(item)

    # If the fault description has been entered, the beginning of the LOG data is inserted
    # log_title = '***** FAULT DESCRIPTION *****'
    # if description:
    #     log_data = '%s\n%s\n\n%s' %(log_title, description, log_data)

    # Server names "patebin" are scrambled
    for label_a, value_a in list(pastebin_list.items()):
        if label_a not in pastebin_list_last:
            pastebin_dir.append(label_a)
    random.shuffle(pastebin_dir)
    pastebin_dir.extend(pastebin_list_last)                             # We leave these services the last

    # pastebin_dir = ['file.io']                                      # For testing a service
    #log_data = 'TEST FOR SERVICE TESTS'

    # The list of "pastebin" servers is scrolled to locate an active one, with capacity and availability
    for paste_name in pastebin_dir:
        if pastebin_list[paste_name][0] != '1':                         # If the server is not active, we pass
            continue
        if pastebin_list[paste_name][6] == 'requests' and not requests_status:  # If "requests" is not active, we pass
            continue

        paste_host = pastebin_list[paste_name][1]                       # Server URL "pastebin"
        paste_sufix = pastebin_list[paste_name][2]                      # API suffix for POST
        paste_title = ''
        if pastebin_list[paste_name][3] == 'random':
            paste_title = "LOG" + str(random.randrange(1, 999999999))   # LOG title
        paste_post1 = pastebin_list[paste_name][4]                      # Initial part of the POST
        paste_post2 = pastebin_list[paste_name][5]                      # Secondary part of POST
        paste_type = pastebin_list[paste_name][6]                       # Type of downloadpage: DATE HEADERS
        paste_resp = pastebin_list[paste_name][7]                       # Response type: JSON or data with REGEX
        paste_resp_key = pastebin_list[paste_name][8]                   # If JSON, label `primary with KEY
        paste_url = pastebin_list[paste_name][9]                        # Primary label for HEADER and sec. for JSON
        paste_file_size = float(pastebin_list[paste_name][10])          # Server capacity in MB
        if paste_file_size > 0:                                         # If it is 0, the capacity is unlimited
            if log_size > paste_file_size:                              # Capacity and size verification
                msg = config.get_localized_string(60334)
                continue
        paste_timeout = int(pastebin_list[paste_name][11])              # Timeout for the server
        paste_random_headers = pastebin_list[paste_name][12]            # Do you use RAMDOM headers to mislead the serv?
        paste_host_return = pastebin_list[paste_name][13]               # Part of url to compose the key for user
        paste_host_return_tail = pastebin_list[paste_name][14]          # Url suffix to compose user key
        paste_headers = {}
        if pastebin_list[paste_name][15]:                               # Headers required by the server
            paste_headers.update(jsontools.load((pastebin_list[paste_name][15])))

        if paste_name in pastebin_one_use:
            item.one_use = True

        try:
            # POST is created with server options "pastebin"
            # This is the "requests" format
            if paste_type in ['requests', 'curl']:
                paste_file = {'file': (paste_title+'.log', log_data)}
                if paste_post1:
                    paste_file.update(paste_post1)
                if paste_post2:
                    if '%s' in paste_post2:
                        paste_params = paste_post2 % (paste_title+'.log', log_size_bytes)
                    else:
                        paste_params = paste_post2

            # This is the download format
            else:
                # log_data = 'Server Test to see its viability (áéíóúñ¿?)'
                if paste_name in ['hastebin']:                              # There are some services that do not need "quote"
                    paste_post = log_data
                else:
                    paste_post = urllib.quote_plus(log_data)                # A "quote" is made from the LOG data
                if paste_post1:
                    paste_post = '%s%s' % (paste_post1, paste_post)
                if paste_post2:
                    if '%s' in paste_post2:
                        paste_post += paste_post2 % paste_title
                    else:
                        paste_post += paste_post2

            # Request is made on downloadpage with HEADERS or DATA, with server parameters
            if paste_type == 'headers':
                data = httptools.downloadpage(paste_host+paste_sufix, post=paste_post,
                            timeout=paste_timeout, random_headers=paste_random_headers,
                            headers=paste_headers).headers
            elif paste_type == 'data':
                data = httptools.downloadpage(paste_host+paste_sufix, post=paste_post,
                            timeout=paste_timeout, random_headers=paste_random_headers,
                            headers=paste_headers).data

            # If the request is in REQUESTS format, it is made here
            elif paste_type == 'requests':
                #data = requests.post(paste_host, params=paste_params, files=paste_file,
                #            timeout=paste_timeout)
                data = httptools.downloadpage(paste_host, params=paste_params, file=log_data,
                            file_name=paste_title+'.log', timeout=paste_timeout,
                            random_headers=paste_random_headers, headers=paste_headers)

            elif paste_type == 'curl':
                paste_sufix = '/create_session'
                data_post = {'file_size': len(log_data)}
                logger.error(data_post)
                data = httptools.downloadpage(paste_host+paste_sufix, params=paste_params,
                            ignore_response_code=True, post=data_post, timeout=paste_timeout, alfa_s=True,
                            random_headers=paste_random_headers, headers=paste_headers).data
                data = jsontools.load(data)
                if not data.get("fuid", ""):
                    logger.error("fuid: %s" % str(data))
                    raise
                fuid = data["fuid"]

                paste_sufix = '/chunk'
                log_data_chunks = log_data
                i = 0
                chunk_len = 1024
                while len(log_data_chunks) > 0:
                    i += 1
                    chunk = log_data_chunks[:chunk_len]
                    log_data_chunks = log_data_chunks[chunk_len:]
                    data_post = {'fuid': fuid, 'chunk_index': i}
                    data = httptools.downloadpage(paste_host+paste_sufix, params=paste_params, file=chunk, alfa_s=True,
                                ignore_response_code=True, post=data_post, timeout=paste_timeout, CF_test=False,
                                random_headers=paste_random_headers, headers=paste_headers).data
                    if not 'successful' in data:
                        logger.error("successful: %s" % str(data))
                        raise

                data = {}
                paste_sufix = '/finalise'
                data_post = {'fuid': fuid, 'total_chunks': i, 'file_name': paste_title+'.log', 'file_type': 'doc'}
                resp = httptools.downloadpage(paste_host+paste_sufix, params=paste_params,
                            ignore_response_code=True, post=data_post, timeout=paste_timeout,
                            random_headers=paste_random_headers, headers=paste_headers)
                if not resp.data:
                    logger.error("resp.content: %s" % str(resp.data))
                    raise
                data['data'] = resp.data
                data = type('HTTPResponse', (), data)

        except:
            msg = 'Try later'
            logger.error('Failed to save report. ' + msg)
            logger.error(traceback.format_exc())
            continue

        # The server response is analyzed and the upload key is located to form the url to pass to the user
        if data:
            paste_host_resp = paste_host
            if paste_host_return == None:                               # If you return the full url, it is not composed
                paste_host_resp = ''
                paste_host_return = ''

            # Responses to REQUESTS requests
            if paste_type in ['requests', 'curl']:                                # Response of request type "requests"?
                if paste_resp == 'json':                                                # Answer in JSON format?
                    if paste_resp_key in data.data:
                        key = jsontools.load(data.data)[paste_resp_key]
                        if paste_url and key:                                   # hay etiquetas adicionales?
                            try:
                                for key_part in paste_url.split(','):
                                    key = key[key_part]                         # por cada etiqueta adicional
                            except:
                                key = ''
                        if key:
                            item.url = "%s%s%s" % (paste_host_resp+paste_host_return, key,
                                                   paste_host_return_tail)
                    if not key:
                        logger.error('ERROR in data return format. data.data=' + str(data.data))
                        continue

            # Responses to DOWNLOADPAGE requests
            elif paste_resp == 'json':                                  # Answer in JSON format?
                if paste_resp_key in data:
                    if not paste_url:
                        key = jsontools.load(data)[paste_resp_key]      # with a label
                    else:
                        key = jsontools.load(data)[paste_resp_key][paste_url]   # con two nested tags
                    item.url = "%s%s%s" % (paste_host_resp+paste_host_return, key,
                                    paste_host_return_tail)
                else:
                    logger.error('ERROR in data return format. data=' + str(data))
                    continue
            elif paste_resp == 'regex':                                 # Answer in DATA, to search with a REGEX?
                key = scrapertools.find_single_match(data, paste_resp_key)
                if key:
                    item.url = "%s%s%s" % (paste_host_resp+paste_host_return, key,
                                    paste_host_return_tail)
                else:
                    logger.error('ERROR in data return format. data=' + str(data))
                    continue
            elif paste_type == 'headers':                               # Answer in HEADERS, to search in "location"?
                if paste_url in data:
                    item.url = data[paste_url]                          # Key return label
                    item.url =  urlparse.urljoin(paste_host_resp + paste_host_return,
                                    item.url + paste_host_return_tail)
                else:
                    logger.error('ERROR in data return format. response.headers=' + str(data))
                    continue
            else:
                logger.error('ERROR in data return format. paste_type=' + str(paste_type) + ' / DATA: ' + data)
                continue

            status = True                                               # Upload operation completed successfully
            logger.info('Report created: ' + str(item.url))    # The URL of the user report is saved
            # if fatal:                                                   # For future use, for logger.crash
            #     platformtools.dialog_ok('S4MeCREATED ERROR report', 'Report it in the forum by adding FATAL ERROR and this URL: ', '[COLOR gold]%s[/COLOR]' % item.url, pastebin_one_use_msg)
            # else:                                                       # Report URL passed to user
            #     platformtools.dialog_ok('S4MeCrash Report CREATED', 'Report it on the forum by adding a bug description and this URL: ', '[COLOR gold]%s[/COLOR]' % item.url, pastebin_one_use_msg)

            break                                                       # Operation finished, we don't keep looking

    if not status and not fatal:                                        # Operation failed ...
        platformtools.dialog_notification(config.get_localized_string(707428), msg)   #... cause is reported
        logger.error(config.get_localized_string(707428) + msg)

    # Control is returned with updated item.url, so the report URL will appear in the menu
    item.action = 'report_menu'
    platformtools.itemlist_update(item, True)
    # return report_menu(item)


def call_browser(item):
    import webbrowser
    if not webbrowser.open(item.url):
        import xbmc
        if xbmc.getCondVisibility('system.platform.linux') and xbmc.getCondVisibility(
                'system.platform.android'):  # android
            xbmc.executebuiltin('StartAndroidActivity("", "android.intent.action.VIEW", "", "%s")' % (item.url))
        else:
            try:
                import urllib.request as urllib
            except ImportError:
                import urllib
            short = urllib.urlopen(
                'https://u.nu/api.php?action=shorturl&format=simple&url=' + item.url).read()
            platformtools.dialog_ok(config.get_localized_string(20000),
                                    config.get_localized_string(70740) % short)
