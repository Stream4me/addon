# s-*- coding: utf-8 -*-
import xbmc, xbmcaddon, sys, re
from core import httptools, scrapertools, filetools, support
from platformcode import config, logger, platformtools

name = 'plugin.video.youtube'

def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    return True, ""

def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    import xbmc
    from xbmcaddon import Addon
    logger.debug("(page_url='%s')" % page_url)
    video_urls = []

    inputstream = platformtools.install_inputstream()

    try:
        __settings__ = Addon(name)
        if inputstream:
            __settings__.setSetting('kodion.video.quality.mpd', 'true')
        else:
            __settings__.setSetting('kodion.video.quality.mpd', 'false')
    except:
        path = xbmc.translatePath('special://home/addons/' + name)
        if filetools.exists(path):
            if platformtools.dialog_yesno(config.get_localized_string(70784), config.get_localized_string(70818)):
                xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "' + name + '", "enabled": true }}')
            else:
                return [['','']]
        else:
            xbmc.executebuiltin('InstallAddon(' + name + ')', wait=True)
            try:
                Addon(name)
            except:
                return [['','']]

    my_addon = xbmcaddon.Addon('plugin.video.youtube')
    addon_dir = xbmc.translatePath(my_addon.getAddonInfo('path'))
    sys.path.append(filetools.join(addon_dir, 'resources', 'lib'))

    dependencies = support.match(filetools.read(filetools.join(addon_dir, 'addon.xml')), patron=r'addon="([^"]+)').matches
    for dep in dependencies:
        sys.path.append(filetools.join(config.get_runtime_path(), '..', dep, 'lib'))
        sys.path.append(filetools.join(config.get_runtime_path(), '..', dep, 'resources', 'modules'))

    from youtube_resolver import resolve
    try:
        for stream in resolve(page_url):
            if scrapertools.find_single_match(stream['title'], r'(\d+p)'):
                video_urls.append([re.sub(r'(\[[^\]]+\])', '', stream['title']), stream['url']])
        video_urls.sort(key=lambda it: int(it[0].split("p", 1)[0]))
    except:
        pass

    return video_urls