# -*- coding: utf-8 -*-

import glob, os

from core.item import Item
from platformcode import config, logger
addon = config.__settings__
downloadenabled = addon.getSetting('downloadenabled')


def getmainlist(view="thumb_"):
    logger.debug()
    itemlist = list()

    try:
        from core.filetools import isdir
        kodpath = os.path.abspath(os.path.join(config.get_data_path(), "../plugin.video.kod"))
        if isdir(kodpath):
            itemlist.append(Item(title="Migrazione KoD -> S4Me", action="migrate"))
    except:
        pass
    # Main Menu Channels
    if addon.getSetting('enable_news_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(30130), channel="news", action="mainlist",
                             thumbnail=get_thumb("news.png", view), category=config.get_localized_string(30119), viewmode="thumbnails",
                             context=[{"title": config.get_localized_string(70285), "channel": "shortcuts", "action": "SettingOnPosition", "category":7, "setting":1}]))

    if addon.getSetting('enable_channels_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(30118), channel="channelselector", action="getchanneltypes",
                             thumbnail=get_thumb("channels.png", view), view=view, category=config.get_localized_string(30119), viewmode="thumbnails"))

    if addon.getSetting('enable_search_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(30103), channel="search", path='special', action="mainlist",
                             thumbnail=get_thumb("search.png", view), category=config.get_localized_string(30119), viewmode="list",
                             context = [{"title": config.get_localized_string(60412), "action": "setting_channel_new", "channel": "search"},
                                       {"title": config.get_localized_string(70286), "channel": "shortcuts", "action": "SettingOnPosition", "category":5 , "setting":1}]))

    if addon.getSetting('enable_onair_menu') == "true":
        itemlist.append(Item(channel="filmontv", action="mainlist", title=config.get_localized_string(50001),
                             thumbnail=get_thumb("on_the_air.png"), viewmode="thumbnails"))

    if addon.getSetting('enable_link_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(70527), channel="addonfavorites", action="mainlist", thumbnail=get_thumb("mylink.png", view),
                             view=view, category=config.get_localized_string(70527), viewmode="thumbnails"))

    if addon.getSetting('enable_fav_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(30102), channel="favorites", action="mainlist",
                            thumbnail=get_thumb("favorites.png", view), category=config.get_localized_string(30102), viewmode="thumbnails"))

    if config.get_videolibrary_support() and addon.getSetting('enable_library_menu') == "true":
        itemlist.append(Item(title=config.get_localized_string(30131), channel="videolibrary", action="mainlist",
                             thumbnail=get_thumb("videolibrary.png", view), category=config.get_localized_string(30119), viewmode="thumbnails",
                             context=[{"title": config.get_localized_string(70287), "channel": "shortcuts", "action": "SettingOnPosition", "category":2, "setting":1},
                                      {"title": config.get_localized_string(60568), "channel": "videolibrary", "action": "update_videolibrary"}]))
    if downloadenabled != "false":
        itemlist.append(Item(title=config.get_localized_string(30101), channel="downloads", action="mainlist", thumbnail=get_thumb("downloads.png", view), viewmode="list",
                             context=[{"title": config.get_localized_string(70288), "channel": "shortcuts", "action": "SettingOnPosition", "category":6}]))

    thumb_setting = "setting_%s.png" % 0  # config.get_setting("plugin_updates_available")


    itemlist.append(Item(title=config.get_localized_string(30100), channel="setting", action="settings",
                         thumbnail=get_thumb(thumb_setting, view), category=config.get_localized_string(30100), viewmode="list", folder=False))
    itemlist.append(Item(title=config.get_localized_string(30104) + " (v" + config.get_addon_version(with_fix=True) + ")", channel="help", action="mainlist",
                         thumbnail=get_thumb("help.png", view), category=config.get_localized_string(30104), viewmode="list"))
    return itemlist



def getchanneltypes(view="thumb_"):
    logger.debug()

    # Category List
    channel_types = ["movie", "tvshow", "anime", "documentary", "vos", "live", "torrent",  "music"] #, "direct"

    # Channel Language
    channel_language = auto_filter()
    logger.debug("channel_language=%s" % channel_language)

    # Build Itemlist
    itemlist = list()
    title = config.get_localized_string(30121)
    itemlist.append(Item(title=title, channel="channelselector", action="filterchannels", view=view,
                         category=title, channel_type="all", thumbnail=get_thumb("all.png", view),
                         viewmode="thumbnails"))

    for channel_type in channel_types:
        title = config.get_localized_category(channel_type)
        itemlist.append(Item(title=title, channel="channelselector", action="filterchannels", category=title,
                             channel_type=channel_type, viewmode="thumbnails",
                             thumbnail=get_thumb("%s.png" % channel_type, view)))

    itemlist.append(Item(title=config.get_localized_string(70685), channel="community", action="mainlist", view=view,
                         category=config.get_localized_string(70685), channel_type="all", thumbnail=get_thumb("community.png", view),
                         viewmode="thumbnails"))
    return itemlist


def filterchannels(category, view="thumb_"):
    from core import channeltools
    logger.debug('Filter Channels ' + category)

    channelslist = []

    # If category = "allchannelstatus" is that we are activating / deactivating channels
    appenddisabledchannels = False
    if category == "allchannelstatus":
        category = "all"
        appenddisabledchannels = True

    channel_path = os.path.join(config.get_runtime_path(), 'channels', '*.json')
    logger.debug("channel_path = %s" % channel_path)

    channel_files = glob.glob(channel_path)
    logger.debug("channel_files found %s" % (len(channel_files)))

    # Channel Language
    channel_language = auto_filter()
    logger.debug("channel_language=%s" % channel_language)

    for channel_path in channel_files:
        logger.debug("channel in for = %s" % channel_path)

        channel = os.path.basename(channel_path).replace(".json", "")

        try:
            channel_parameters = channeltools.get_channel_parameters(channel)

            if channel_parameters["channel"] == 'community':
                continue

            # If it's not a channel we skip it
            if not channel_parameters["channel"]:
                continue
            logger.debug("channel_parameters=%s" % repr(channel_parameters))

            # If you prefer the banner and the channel has it, now change your mind
            if view == "banner_" and "banner" in channel_parameters:
                channel_parameters["thumbnail"] = channel_parameters["banner"]

            # if the channel is deactivated the channel is not shown in the list
            if not channel_parameters["active"]:
                continue

            # The channel is skipped if it is not active and we are not activating / deactivating the channels
            channel_status = config.get_setting("enabled", channel_parameters["channel"])

            if channel_status is None:
                # if channel_status does not exist, there is NO value in _data.json.
                # as we got here (the channel is active in channel.json), True is returned
                channel_status = True

            if not channel_status:
                # if we get the list of channels from "activate / deactivate channels", and the channel is deactivated
                # we show it, if we are listing all the channels from the general list and it is deactivated, it is not shown
                if not appenddisabledchannels:
                    continue

            if channel_language != "all" and "*" not in channel_parameters["language"] \
                 and channel_language not in str(channel_parameters["language"]):
                continue

            # The channel is skipped if it is in a filtered category
            if category != "all" and category not in channel_parameters["categories"]:
                continue

            # If you have configuration we add an item in the context
            context = []
            if channel_parameters["has_settings"]:
                context.append({"title": config.get_localized_string(70525), "channel": "setting", "action": "channel_config",
                                "config": channel_parameters["channel"]})

            channel_info = set_channel_info(channel_parameters)
            # If it has come this far, add it
            channelslist.append(Item(title=channel_parameters["title"], channel=channel_parameters["channel"],
                                     action="mainlist", thumbnail=channel_parameters["thumbnail"],
                                     fanart=channel_parameters["fanart"], plot=channel_info, category=channel_parameters["title"],
                                     language=channel_parameters["language"], viewmode="list", context=context))

        except:
            logger.error("An error occurred while reading the channel data '%s'" % channel)
            import traceback
            logger.error(traceback.format_exc())

    channelslist.sort(key=lambda item: item.title.lower().strip())

    if not config.get_setting("only_channel_icons"):
        if category == "all":
            channel_parameters = channeltools.get_channel_parameters('url')
            # If you prefer the banner and the channel has it, now change your mind
            if view == "banner_" and "banner" in channel_parameters:
                channel_parameters["thumbnail"] = channel_parameters["banner"]

            channelslist.insert(0, Item(title=config.get_localized_string(60088), action="mainlist", channel="url",
                                        thumbnail=channel_parameters["thumbnail"], type="generic", viewmode="list"))
        # Special Category
        if category in ['movie', 'tvshow']:
            titles = [config.get_localized_string(70028), config.get_localized_string(30985), config.get_localized_string(70559), config.get_localized_string(60264), config.get_localized_string(70560)]
            ids = ['popular', 'top_rated', 'now_playing', 'on_the_air']
            for x in range(0,3):
                if x == 2 and category != 'movie':
                    title=titles[x+1]
                    id = ids[x+1]
                else:
                    title=titles[x]
                    id = ids[x]
                channelslist.insert(x,
                    Item(channel='search', action='discover_list', title=title, search_type='list',
                         list_type='%s/%s' % (category.replace('show',''), id), mode=category, thumbnail=get_thumb(id+".png")))

            channelslist.insert(3, Item(channel='search', action='genres_menu', title=config.get_localized_string(30987),
                                        type=category.replace('show',''), mode=category ,thumbnail=get_thumb("genres.png")))

    return channelslist


def get_thumb(thumb_name, view="thumb_"):
    from core import filetools
    if thumb_name.startswith('http'):
        return thumb_name
    elif config.get_setting('enable_custom_theme') and config.get_setting('custom_theme') and filetools.isfile(config.get_setting('custom_theme') + view + thumb_name):
        media_path = config.get_setting('custom_theme')
    else:
        icon_pack_name = config.get_setting('icon_set', default="default")
        media_path = filetools.join("https://raw.githubusercontent.com/Stream4me/media/master/themes", icon_pack_name)
    return filetools.join(media_path, view + thumb_name)


def set_channel_info(parameters):
    logger.debug()

    info = ''
    language = ''
    content = ''
    langs = parameters['language']
    lang_dict = {'ita':'Italiano',
                 'sub-ita':'Sottotitolato in Italiano',
                 '*':'Italiano, Sottotitolato in Italiano'}

    for lang in langs:

        if lang in lang_dict:
            if language != '' and language != '*':
                language = '%s, %s' % (language, lang_dict[lang])
            else:
                language = lang_dict[lang]
        if lang == '*':
            break

    categories = parameters['categories']
    for cat in categories:
        if content != '':
            content = '%s, %s' % (content, config.get_localized_category(cat))
        else:
            content = config.get_localized_category(cat)

    info = '[B]' + config.get_localized_string(70567) + ' [/B]' + content + '\n\n'
    info += '[B]' + config.get_localized_string(70568) + ' [/B] ' + language
    return info


def auto_filter(auto_lang=False):
    list_lang = ['ita', 'vos', 'sub-ita']
    if config.get_setting("channel_language") == 'auto' or auto_lang == True:
        lang = config.get_language()

    else:
        lang = config.get_setting("channel_language", default="all")

    if lang not in list_lang:
        lang = 'all'

    return lang
