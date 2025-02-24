import json
from core import filetools, downloadtools, httptools, support
from platformcode import config, platformtools, updater
import xbmc, xbmcaddon, sys, platform

host = 'https://github.com'
elementum_url = host + '/elgatito/plugin.video.elementum/releases'
filename = filetools.join(config.get_data_path(),'elementum.zip')
addon_path = xbmc.translatePath('special://home/addons/')
setting_path = xbmc.translatePath('special://profile/addon_data/')
elementum_path = filetools.join(addon_path,'plugin.video.elementum')
elementum_setting = filetools.join(setting_path,'plugin.video.elementum')
elementum_setting_file = filetools.join(elementum_setting,'settings.xml')
s4me_setting_file = filetools.join(addon_path,'plugin.video.s4me', 'resources', 'settings', 'elementum', 'settings.xml')

def setting():
    xbmc.executebuiltin('UpdateLocalAddons')
    xbmc.sleep(1000)
    if filetools.isfile(elementum_setting_file):
        xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.elementum", "enabled": true }}')
        Continue = True
        while Continue:
            try:
                __settings__ = xbmcaddon.Addon(id="plugin.video.elementum")
                __settings__.setSetting('skip_burst_search', 'true')
                __settings__.setSetting('greeting_enabled', 'false')
                __settings__.setSetting('do_not_disturb', 'true')
                Continue = False
            except:
                support.info('RIPROVO')
                xbmc.sleep(100)
    else:
        if not filetools.exists(elementum_path):
            filetools.mkdir(elementum_path)
        filetools.copy(s4me_setting_file, elementum_setting_file)
        xbmc.sleep(1000)
        xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.elementum", "enabled": true }}')

    updater.refreshLang()

    if filetools.exists(filename):
        filetools.remove(filename)

def download(item=None):
    ret = True

    if filetools.exists(elementum_path):
        response = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Addons.GetAddonDetails", "params": {"addonid": "plugin.video.elementum", "properties": ["enabled"]}, "id": 1}')
        result = json.loads(response)
        if 'result' in result and 'addon' in result['result'] and result['result']['addon']['enabled']:
            platformtools.dialog_ok(config.get_localized_string(70784), config.get_localized_string(90006))
            return ret

        if platformtools.dialog_yesno(config.get_localized_string(70784), config.get_localized_string(70783)):
            addon_file = filetools.file_open(filetools.join(elementum_path,'addon.xml')).read()
            required = support.match(addon_file, patron=r'addon="([^"]+)').matches
            for r in required: xbmc.executebuiltin('InstallAddon(' + r + ')', wait=True)
            setting()
            platformtools.dialog_ok('Elementum', config.get_localized_string(70783))
        else:
            ret = False

    else:
        if platformtools.dialog_yesno(config.get_localized_string(70784), config.get_localized_string(70782)):
            pform = get_platform()
            real_elementum_url = elementum_url + '/expanded_assets/' + httptools.downloadpage(elementum_url +'/latest').url.split('/')[-1]
            url = support.match(real_elementum_url, patron=r'<a href="([a-zA-Z0-9/\.-]+{}.zip)'.format(pform)).match
            support.info('OS:', pform)
            support.info('Extract IN:', elementum_path)
            support.info('URL:', url)
            if url:
                dl = downloadtools.downloadfile(host + url, filename)
                if dl == -3:
                    filetools.remove(filename)
                    dl = downloadtools.downloadfile(host + url, filename)
                if dl == None:
                    extract()
                    xbmc.sleep(1000)
                    addon_file = filetools.file_open(filetools.join(elementum_path,'addon.xml')).read()
                    required = support.match(addon_file, patron=r'addon="([^"]+)').matches
                    for r in required: xbmc.executebuiltin('InstallAddon(' + r + ')', wait=True)
                    setting()
                else:
                    ret = False
            else:
                ret = False
        else:
            ret = False
    return ret

def extract():
    import zipfile
    from platformcode.updater import fixZipGetHash
    support.info('Estraggo Elementum in:', elementum_path)
    try:
        with zipfile.ZipFile(filetools.file_open(filename, 'rb', vfs=False)) as zip_ref:
            zip_ref.extractall(xbmc.translatePath(addon_path))

    except Exception as e:
        support.info('Non sono riuscito ad estrarre il file zip')
        support.logger.error(e)
        import traceback
        support.logger.error(traceback.print_exc())

def get_platform():
    build = xbmc.getInfoLabel("System.BuildVersion")
    kodi_version = int(build.split()[0][:2])
    ret = {
        "auto_arch": sys.maxsize > 2 ** 32 and "64-bit" or "32-bit",
        "arch": sys.maxsize > 2 ** 32 and "x64" or "x86",
        "os": "",
        "version": platform.release(),
        "kodi": kodi_version,
        "build": build
    }
    if xbmc.getCondVisibility("system.platform.android"):
        ret["os"] = "android"
        if "arm" in platform.machine() or "aarch" in platform.machine():
            ret["arch"] = "arm"
            if "64" in platform.machine() and ret["auto_arch"] == "64-bit":
                ret["arch"] = "arm64"
    elif xbmc.getCondVisibility("system.platform.linux"):
        ret["os"] = "linux"
        if "aarch" in platform.machine() or "arm64" in platform.machine():
            if xbmc.getCondVisibility("system.platform.linux.raspberrypi"):
                ret["arch"] = "armv7"
            elif ret["auto_arch"] == "32-bit":
                ret["arch"] = "armv7"
            elif ret["auto_arch"] == "64-bit":
                ret["arch"] = "arm64"
            elif platform.architecture()[0].startswith("32"):
                ret["arch"] = "arm"
            else:
                ret["arch"] = "arm64"
        elif "armv7" in platform.machine():
            ret["arch"] = "armv7"
        elif "arm" in platform.machine():
            ret["arch"] = "arm"
    elif xbmc.getCondVisibility("system.platform.xbox"):
        ret["os"] = "windows"
        ret["arch"] = "x64"
    elif xbmc.getCondVisibility("system.platform.windows"):
        ret["os"] = "windows"
        if platform.machine().endswith('64'):
            ret["arch"] = "x64"
    elif xbmc.getCondVisibility("system.platform.osx"):
        ret["os"] = "darwin"
        ret["arch"] = "x64"
    elif xbmc.getCondVisibility("system.platform.ios"):
        ret["os"] = "ios"
        ret["arch"] = "arm"

    return ret['os'] + '_' + ret['arch']
