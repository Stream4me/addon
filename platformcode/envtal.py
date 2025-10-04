# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Localiza las variables de entorno más habituales (kodi)
# ------------------------------------------------------------

from __future__ import division
from past.utils import old_div
import sys

PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

import xbmc, xbmcaddon, os, subprocess, re, platform

try:
    import ctypes
except:
    pass
import traceback

from core import filetools, scrapertools
from platformcode import logger, config, platformtools


def get_environment():
    """
    Returns the most common OS, Kodi and Alpha environment variables,
    necessary for fault diagnosis
    """

    try:
        import base64
        import ast

        environment = config.get_platform(full_version=True)
        environment['num_version'] = str(environment['num_version'])
        environment['python_version'] = str(platform.python_version())

        environment['os_release'] = str(platform.release())
        if xbmc.getCondVisibility("system.platform.Windows"):
            try:
                if platform._syscmd_ver()[2]:
                    environment['os_release'] = str(platform._syscmd_ver()[2])
            except:
                pass
        environment['prod_model'] = ''
        if xbmc.getCondVisibility("system.platform.Android"):
            environment['os_name'] = 'Android'
            try:
                for label_a in subprocess.check_output('getprop').split('\n'):
                    if 'build.version.release' in label_a:
                        environment['os_release'] = str(scrapertools.find_single_match(label_a, r':\s*\[(.*?)\]$'))
                    if 'product.model' in label_a:
                        environment['prod_model'] = str(scrapertools.find_single_match(label_a, r':\s*\[(.*?)\]$'))
            except:
                try:
                    for label_a in filetools.read(os.environ['ANDROID_ROOT'] + '/build.prop').split():
                        if 'build.version.release' in label_a:
                            environment['os_release'] = str(scrapertools.find_single_match(label_a, '=(.*?)$'))
                        if 'product.model' in label_a:
                            environment['prod_model'] = str(scrapertools.find_single_match(label_a, '=(.*?)$'))
                except:
                    pass

        elif xbmc.getCondVisibility("system.platform.Linux.RaspberryPi"):
            environment['os_name'] = 'RaspberryPi'
        else:
            environment['os_name'] = str(platform.system())

        environment['machine'] = str(platform.machine())
        environment['architecture'] = str(sys.maxsize > 2 ** 32 and "64-bit" or "32-bit")
        environment['language'] = str(xbmc.getInfoLabel('System.Language'))

        environment['cpu_usage'] = str(xbmc.getInfoLabel('System.CpuUsage'))

        environment['mem_total'] = str(xbmc.getInfoLabel('System.Memory(total)')).replace('MB', '').replace('KB', '')
        environment['mem_free'] = str(xbmc.getInfoLabel('System.Memory(free)')).replace('MB', '').replace('KB', '')
        if not environment['mem_total'] or not environment['mem_free']:
            try:
                if environment['os_name'].lower() == 'windows':
                    kernel32 = ctypes.windll.kernel32
                    c_ulong = ctypes.c_ulong
                    c_ulonglong = ctypes.c_ulonglong

                    class MEMORYSTATUS(ctypes.Structure):
                        _fields_ = [
                            ('dwLength', c_ulong),
                            ('dwMemoryLoad', c_ulong),
                            ('dwTotalPhys', c_ulonglong),
                            ('dwAvailPhys', c_ulonglong),
                            ('dwTotalPageFile', c_ulonglong),
                            ('dwAvailPageFile', c_ulonglong),
                            ('dwTotalVirtual', c_ulonglong),
                            ('dwAvailVirtual', c_ulonglong),
                            ('availExtendedVirtual', c_ulonglong)
                        ]

                    memoryStatus = MEMORYSTATUS()
                    memoryStatus.dwLength = ctypes.sizeof(MEMORYSTATUS)
                    kernel32.GlobalMemoryStatus(ctypes.byref(memoryStatus))
                    environment['mem_total'] = str(old_div(int(memoryStatus.dwTotalPhys), (1024 ** 2)))
                    environment['mem_free'] = str(old_div(int(memoryStatus.dwAvailPhys), (1024 ** 2)))

                else:
                    with open('/proc/meminfo') as f:
                        meminfo = f.read()
                    environment['mem_total'] = str(
                        old_div(int(re.search(r'MemTotal:\s+(\d+)', meminfo).groups()[0]), 1024))
                    environment['mem_free'] = str(
                        old_div(int(re.search(r'MemAvailable:\s+(\d+)', meminfo).groups()[0]), 1024))
            except:
                environment['mem_total'] = ''
                environment['mem_free'] = ''

        try:
            environment['kodi_buffer'] = '20'
            environment['kodi_bmode'] = '0'
            environment['kodi_rfactor'] = '4.0'
            if filetools.exists(filetools.join(xbmc.translatePath("special://userdata"), "advancedsettings.xml")):
                advancedsettings = filetools.read(filetools.join(xbmc.translatePath("special://userdata"), "advancedsettings.xml")).split('\n')
                for label_a in advancedsettings:
                    if 'memorysize' in label_a:
                        environment['kodi_buffer'] = str(old_div(int(scrapertools.find_single_match(label_a, r'>(\d+)<\/')), 1024 ** 2))
                    if 'buffermode' in label_a:
                        environment['kodi_bmode'] = str(scrapertools.find_single_match(label_a, r'>(\d+)<\/'))
                    if 'readfactor' in label_a:
                        environment['kodi_rfactor'] = str(scrapertools.find_single_match(label_a, r'>(.*?)<\/'))
        except:
            pass

        environment['userdata_path'] = str(xbmc.translatePath(config.get_data_path()))
        try:
            if environment['os_name'].lower() == 'windows':
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(environment['userdata_path']), None, None, ctypes.pointer(free_bytes))
                environment['userdata_free'] = str(round(float(free_bytes.value) / (1024 ** 3), 3))
            else:
                disk_space = os.statvfs(environment['userdata_path'])
                if not disk_space.f_frsize: disk_space.f_frsize = disk_space.f_frsize.f_bsize
                environment['userdata_free'] = str(round((float(disk_space.f_bavail) / (1024 ** 3)) * float(disk_space.f_frsize), 3))
        except:
            environment['userdata_free'] = '?'

        try:
            environment['videolab_series'] = '?'
            environment['videolab_episodios'] = '?'
            environment['videolab_pelis'] = '?'
            environment['videolab_path'] = str(xbmc.translatePath(config.get_videolibrary_path()))
            if filetools.exists(filetools.join(environment['videolab_path'],  config.get_setting("folder_tvshows"))):
                environment['videolab_series'] = str(len(filetools.listdir(filetools.join(environment['videolab_path'], config.get_setting("folder_tvshows")))))
                counter = 0
                for root, folders, files in filetools.walk(filetools.join(environment['videolab_path'], config.get_setting("folder_tvshows"))):
                    for file in files:
                        if file.endswith('.strm'): counter += 1
                environment['videolab_episodios'] = str(counter)
            if filetools.exists(filetools.join(environment['videolab_path'], config.get_setting("folder_movies"))):
                environment['videolab_pelis'] = str(len(filetools.listdir(filetools.join(environment['videolab_path'], config.get_setting("folder_movies")))))
        except:
            pass
        try:
            video_updates = ['No', 'Inicio', 'Una vez', 'Inicio+Una vez']
            environment['videolab_update'] = str(video_updates[config.get_setting("update", "videolibrary")])
        except:
            environment['videolab_update'] = '?'
        try:
            if environment['os_name'].lower() == 'windows':
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(environment['videolab_path']), None, None, ctypes.pointer(free_bytes))
                environment['videolab_free'] = str(round(float(free_bytes.value) / (1024 ** 3), 3))
            else:
                disk_space = os.statvfs(environment['videolab_path'])
                if not disk_space.f_frsize: disk_space.f_frsize = disk_space.f_frsize.f_bsize
                environment['videolab_free'] = str(round((float(disk_space.f_bavail) / (1024 ** 3)) * float(disk_space.f_frsize), 3))
        except:
            environment['videolab_free'] = '?'

        # environment['torrent_list'] = []
        # environment['torrentcli_option'] = ''
        # environment['torrent_error'] = ''
        # environment['torrentcli_rar'] = config.get_setting("mct_rar_unpack", server="torrent", default=True)
        # environment['torrentcli_backgr'] = config.get_setting("mct_background_download", server="torrent", default=True)
        # environment['torrentcli_lib_path'] = config.get_setting("libtorrent_path", server="torrent", default="")
        # if environment['torrentcli_lib_path']:
        #     lib_path = 'Activo'
        # else:
        #     lib_path = 'Inactivo'
        # environment['torrentcli_unrar'] = config.get_setting("unrar_path", server="torrent", default="")
        # if environment['torrentcli_unrar']:
        #     if xbmc.getCondVisibility("system.platform.Android"):
        #         unrar = 'Android'
        #     else:
        #         unrar, bin = filetools.split(environment['torrentcli_unrar'])
        #         unrar = unrar.replace('\\', '/')
        #         if not unrar.endswith('/'):
        #             unrar = unrar + '/'
        #         unrar = scrapertools.find_single_match(unrar, '\/([^\/]+)\/$').capitalize()
        # else:
        #     unrar = 'Inactivo'
        # torrent_id = config.get_setting("torrent_client", server="torrent", default=0)
        # environment['torrentcli_option'] = str(torrent_id)
        # torrent_options = platformtools.torrent_client_installed()
        # if lib_path == 'Activo':
        #     torrent_options = ['MCT'] + torrent_options
        #     torrent_options = ['BT'] + torrent_options
        # environment['torrent_list'].append({'Torrent_opt': str(torrent_id), 'Libtorrent': lib_path, \
        #                                     'RAR_Auto': str(environment['torrentcli_rar']), \
        #                                     'RAR_backgr': str(environment['torrentcli_backgr']), \
        #                                     'UnRAR': unrar})
        # environment['torrent_error'] = config.get_setting("libtorrent_error", server="torrent", default="")
        # if environment['torrent_error']:
        #     environment['torrent_list'].append({'Libtorrent_error': environment['torrent_error']})

        # for torrent_option in torrent_options:
        #     cliente = dict()
        #     cliente['D_load_Path'] = ''
        #     cliente['Libre'] = '?'
        #     cliente['Plug_in'] = torrent_option.replace('Plugin externo: ', '')
        #     if cliente['Plug_in'] == 'BT':
        #         cliente['D_load_Path'] = str(config.get_setting("bt_download_path", server="torrent", default=''))
        #         if not cliente['D_load_Path']: continue
        #         cliente['Buffer'] = str(config.get_setting("bt_buffer", server="torrent", default=50))
        #     elif cliente['Plug_in'] == 'MCT':
        #         cliente['D_load_Path'] = str(config.get_setting("mct_download_path", server="torrent", default=''))
        #         if not cliente['D_load_Path']: continue
        #         cliente['Buffer'] = str(config.get_setting("mct_buffer", server="torrent", default=50))
        #     elif xbmc.getCondVisibility('System.HasAddon("plugin.video.%s")' % cliente['Plug_in']):
        #         __settings__ = xbmcaddon.Addon(id="plugin.video.%s" % cliente['Plug_in'])
        #         cliente['Plug_in'] = cliente['Plug_in'].capitalize()
        #         if cliente['Plug_in'] == 'Torrenter':
        #             cliente['D_load_Path'] = str(xbmc.translatePath(__settings__.getSetting('storage')))
        #             if not cliente['D_load_Path']:
        #                 cliente['D_load_Path'] = str(filetools.join(xbmc.translatePath("special://home/"), \
        #                                                             "cache", "xbmcup", "plugin.video.torrenter",
        #                                                             "Torrenter"))
        #             cliente['Buffer'] = str(__settings__.getSetting('pre_buffer_bytes'))
        #         else:
        #             cliente['D_load_Path'] = str(xbmc.translatePath(__settings__.getSetting('download_path')))
        #             cliente['Buffer'] = str(__settings__.getSetting('buffer_size'))
        #             if __settings__.getSetting('download_storage') == '1' and __settings__.getSetting('memory_size'):
        #                 cliente['Memoria'] = str(__settings__.getSetting('memory_size'))

        #     if cliente['D_load_Path']:
        #         try:
        #             if environment['os_name'].lower() == 'windows':
        #                 free_bytes = ctypes.c_ulonglong(0)
        #                 ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(cliente['D_load_Path']),
        #                                                            None, None, ctypes.pointer(free_bytes))
        #                 cliente['Libre'] = str(round(float(free_bytes.value) / \
        #                                              (1024 ** 3), 3)).replace('.', ',')
        #             else:
        #                 disk_space = os.statvfs(cliente['D_load_Path'])
        #                 if not disk_space.f_frsize: disk_space.f_frsize = disk_space.f_frsize.f_bsize
        #                 cliente['Libre'] = str(round((float(disk_space.f_bavail) / \
        #                                               (1024 ** 3)) * float(disk_space.f_frsize), 3)).replace('.', ',')
        #         except:
        #             pass
        #     environment['torrent_list'].append(cliente)

        environment['proxy_active'] = ''
        try:
            proxy_channel_bloqued_str = base64.b64decode(config.get_setting('proxy_channel_bloqued')).decode('utf-8')
            proxy_channel_bloqued = dict()
            proxy_channel_bloqued = ast.literal_eval(proxy_channel_bloqued_str)
            for channel_bloqued, proxy_active in list(proxy_channel_bloqued.items()):
                if proxy_active != 'OFF':
                    environment['proxy_active'] += channel_bloqued + ', '
        except:
            pass
        if not environment['proxy_active']: environment['proxy_active'] = 'OFF'
        environment['proxy_active'] = environment['proxy_active'].rstrip(', ')

        for root, folders, files in filetools.walk(xbmc.translatePath("special://logpath/")):
            for file in files:
                if file.lower() in ['kodi.log', 'jarvis.log', 'spmc.log', 'cemc.log', \
                                    'mygica.log', 'wonderbox.log', 'leiapp,log', \
                                    'leianmc.log', 'kodiapp.log', 'anmc.log', \
                                    'latin-anmc.log']:
                    environment['log_path'] = str(filetools.join(root, file))
                    break
            else:
                environment['log_path'] = ''
            break

        if environment['log_path']:
            environment['log_size_bytes'] = str(filetools.getsize(environment['log_path']))
            environment['log_size'] = str(round(float(environment['log_size_bytes']) / \
                                                (1024 * 1024), 3))
        else:
            environment['log_size_bytes'] = ''
            environment['log_size'] = ''

        environment['debug'] = str(config.get_setting('debug'))
        environment['addon_version'] = str(config.get_addon_version())

    except:
        logger.error(traceback.format_exc())
        environment = {}
        environment['log_size'] = ''
        environment['cpu_usage'] = ''
        environment['python_version'] = ''
        environment['log_path'] = ''
        environment['userdata_free'] = ''
        environment['mem_total'] = ''
        environment['machine'] = ''
        environment['platform'] = ''
        environment['videolab_path'] = ''
        environment['num_version'] = ''
        environment['os_name'] = ''
        environment['video_db'] = ''
        environment['userdata_path'] = ''
        environment['log_size_bytes'] = ''
        environment['name_version'] = ''
        environment['language'] = ''
        environment['mem_free'] = ''
        environment['prod_model'] = ''
        environment['proxy_active'] = ''
        environment['architecture'] = ''
        environment['os_release'] = ''
        environment['videolab_free'] = ''
        environment['kodi_buffer'] = ''
        environment['kodi_bmode'] = ''
        environment['kodi_rfactor'] = ''
        environment['videolab_series'] = ''
        environment['videolab_episodios'] = ''
        environment['videolab_pelis'] = ''
        environment['videolab_update'] = ''
        environment['debug'] = ''
        environment['addon_version'] = ''
        environment['torrent_list'] = []
        environment['torrentcli_option'] = ''
        environment['torrentcli_rar'] = ''
        environment['torrentcli_lib_path'] = ''
        environment['torrentcli_unrar'] = ''
        environment['torrent_error'] = ''

    return environment


def list_env(environment={}):
    sep = '-----------------------------------------------------------'
    if not environment:
        environment = get_environment()

    logger.info(sep)
    logger.info('S4Me environment variables: ' + environment['addon_version'] + ' Debug: ' + environment['debug'])
    logger.info(sep)

    logger.info(environment['os_name'] + ' ' + environment['prod_model'] + ' ' +
                environment['os_release'] + ' ' + environment['machine'] + ' ' +
                environment['architecture'] + ' ' + environment['language'])

    logger.info('Kodi ' + environment['num_version'] + ', Vídeo: ' +
                environment['video_db'] + ', Python ' + environment['python_version'])

    if environment['cpu_usage']:
        logger.info('CPU: ' + environment['cpu_usage'])

    if environment['mem_total'] or environment['mem_free']:
        logger.info('Memory: Total: ' + environment['mem_total'] + ' MB | Disp.: ' +
                    environment['mem_free'] + ' MB | Buffers: ' +
                    str(int(environment['kodi_buffer']) * 3) + ' MB | Buffermode: ' +
                    environment['kodi_bmode'] + ' | Readfactor: ' +
                    environment['kodi_rfactor'])

    logger.info('Userdata: ' + environment['userdata_path'] + ' - Free: ' +
                environment['userdata_free'].replace('.', ',') + ' GB')

    logger.info('Videolibrary: Series/Episodes: ' + environment['videolab_series'] + '/' +
                environment['videolab_episodios'] + ' - Pelis: ' +
                environment['videolab_pelis'] + ' - Upd: ' +
                environment['videolab_update'] + ' - Path: ' +
                environment['videolab_path'] + ' - Free: ' +
                environment['videolab_free'].replace('.', ',') + ' GB')

    # if environment['torrent_list']:
    #     for x, cliente in enumerate(environment['torrent_list']):
    #         if x == 0:
    #             cliente_alt = cliente.copy()
    #             del cliente_alt['Torrent_opt']
    #             logger.info('Torrent: Opt: %s, %s' % (str(cliente['Torrent_opt']), \
    #                                                   str(cliente_alt).replace('{', '').replace('}', '') \
    #                                                   .replace("'", '').replace('_', ' ')))
    #         elif x == 1 and environment['torrent_error']:
    #             logger.info('- ' + str(cliente).replace('{', '').replace('}', '') \
    #                         .replace("'", '').replace('_', ' '))
    #         else:
    #             cliente_alt = cliente.copy()
    #             del cliente_alt['Plug_in']
    #             cliente_alt['Libre'] = cliente_alt['Libre'].replace('.', ',') + ' GB'
    #             logger.info('- %s: %s' % (str(cliente['Plug_in']), str(cliente_alt) \
    #                                       .replace('{', '').replace('}', '').replace("'", '') \
    #                                       .replace('\\\\', '\\')))

    # logger.info('Proxy: ' + environment['proxy_active'])

    logger.info('LOG Size: ' + environment['log_size'].replace('.', ',') + ' MB')
    logger.info(sep)

    return environment


def paint_env(item, environment={}):
    from core.item import Item
    from channelselector import get_thumb

    if not environment:
        environment = get_environment()
    environment = list_env(environment)

    itemlist = []

    thumb = get_thumb("setting_0.png")

    cabecera = """\
    It shows the [COLOR yellow] variables [/ COLOR] of the Kodi ecosystem that may be relevant to the problem diagnosis in Alpha:
        - Alpha version with Fix
        - Debug Alfa: True/False
    """
    plataform = """\
    It shows the specific data of the [COLOR yellow] platform [/ COLOR] where Kodi is hosted:
        - Operating system
        - Model (opt)
        - SO version
        - Processor
        - Architecture
        - Kodi language
    """
    kodi = """\
    It shows the specific data of the installation of [COLOR yellow] Kodi [/ COLOR]:
        - Kodi version
        - Video Database
        - Python version
    """
    cpu = """\
    Displays the current consumption data of [COLOR yellow] CPU (s) [/ COLOR]
    """
    memoria = """\
    Displays the usage data of [COLOR yellow] System [/ COLOR] memory:
        - Total memory
        - Available memory
        - en [COLOR yellow]Advancedsettings.xml[/COLOR]
             - Memory buffer
                 configured:
                 for Kodi: 3 x value of
                 <memorysize>
             - Buffermode: cache:
                 * Internet (0, 2)
                 * Also local (1)
                 * No Buffer (3)
             - Readfactor: readfactor *
                 avg bitrate video
    """
    userdata = """\
    It shows the data of the "path" of [COLOR yellow] Userdata [/ COLOR]:
        - Path
        - Available space
    """
    videoteca = """\
    It shows the data of the [COLOR yellow] Video Library [/ COLOR]:
        - Number of Series and Episodes
        - No. of Movies
        - Update type
        - Path
        - Available space
    """
    torrent = """\
    It shows the general data of the status of [COLOR yellow] Torrent [/ COLOR]:
        - ID of the selected customer
        - Automatic decompression of RAR files?
        - Is Libtorrent active?
        - Are RARs decompressed in the background?
        - Is the UnRAR module operational? Which platform?
    """
    torrent_error = """\
    Displays the import error data for [COLOR yellow] Libtorrent [/ COLOR]
    """
    torrent_cliente = """\
    It shows the data of the [COLOR yellow] Torrent Clients [/ COLOR]:
        - Customer name
        - Initial buffer size
        - Download path
        - Memory buffer size
                (opt, si no disco)
        - Available space
    """
    proxy = """\
    Shows the addresses of channels or servers that need [COLOR yellow] Proxy [/ COLOR]
    """
    log = """\
    Displays the current size of the [COLOR yellow] Log [/ COLOR]
    """
    reporte = """\
    Links with the utility that allows the [COLOR yellow] to send the Kodi Log [/ COLOR] through a Pastebin service
    """

    itemlist.append(Item(channel=item.channel, title="S4Me environment variables: %s Debug: %s" % (environment['addon_version'], environment['debug']),
                         action="", plot=cabecera, thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title=environment['os_name'] + ' ' + environment['prod_model'] + ' ' + environment['os_release'] + ' ' + environment['machine'] + ' ' + environment['architecture'] + ' ' + environment['language'],
                         action="", plot=plataform, thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title='Kodi ' + environment['num_version'] + ', Vídeo: ' + environment[ 'video_db'] + ', Python ' + environment['python_version'], action="",
                         plot=kodi, thumbnail=thumb, folder=False))

    if environment['cpu_usage']:
        itemlist.append(Item(channel=item.channel, title='CPU: ' + environment['cpu_usage'], action="", plot=cpu, thumbnail=thumb, folder=False))

    if environment['mem_total'] or environment['mem_free']:
        itemlist.append(Item(channel=item.channel, title='Memory: Total: ' +
                                                         environment['mem_total'] + ' MB / Disp.: ' +
                                                         environment['mem_free'] + ' MB / Buffers: ' +
                                                         str(int(environment['kodi_buffer']) * 3) + ' MB / Buffermode: ' +
                                                         environment['kodi_bmode'] + ' / Readfactor: ' +
                                                         environment['kodi_rfactor'],
                             action="", plot=memoria, thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title='Userdata:' +
                                                     environment['userdata_path'] + ' - Free: ' + environment[ 'userdata_free'].replace('.', ',') +
                                                     ' GB', action="", plot=userdata, thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title='Video store: Series/Epis: ' +
                                                     environment['videolab_series'] + '/' + environment['videolab_episodios'] +
                                                     ' - Movie: ' + environment['videolab_pelis'] + ' - Upd: ' + environment['videolab_update'] + ' - Path: ' +
                                                     environment['videolab_path'] + ' - Free: ' + environment[ 'videolab_free'].replace('.', ',') +
                                                     ' GB', action="", plot=videoteca, thumbnail=thumb, folder=False))

    if environment['torrent_list']:
        for x, cliente in enumerate(environment['torrent_list']):
            if x == 0:
                cliente_alt = cliente.copy()
                del cliente_alt['Torrent_opt']
                itemlist.append(Item(channel=item.channel, title='Torrent: Opt: %s, %s' % (str(cliente['Torrent_opt']), str(cliente_alt).replace('{', '').replace('}', '').replace("'", '').replace('_', ' ')), action="",
                                     plot=torrent, thumbnail=thumb, folder=False))
            elif x == 1 and environment['torrent_error']:
                itemlist.append(Item(channel=item.channel,
                                     title=str(cliente).replace('{', '').replace('}','').replace("'", '').replace('_', ' '), action="", plot=torrent_error,
                                     thumbnail=thumb, folder=False))
            else:
                cliente_alt = cliente.copy()
                del cliente_alt['Plug_in']
                cliente_alt['Libre'] = cliente_alt['Libre'].replace('.', ',') + ' GB'
                itemlist.append(Item(channel=item.channel, title='- %s: %s' % (str(cliente['Plug_in']), str(cliente_alt).replace('{', '').replace('}', '').replace("'", '').replace('\\\\', '\\')), action="",
                                     plot=torrent_cliente, thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title='Proxy: ' + environment['proxy_active'], action="", plot=proxy,
                         thumbnail=thumb, folder=False))

    itemlist.append(Item(channel=item.channel, title='LOG SIZE: ' + environment['log_size'].replace('.', ',') + ' MB', action="",
                         plot=log, thumbnail=thumb,
                         folder=False))

    itemlist.append(Item(title="==> Report a bug",
                         channel="setting", action="report_menu", category='Configuración',
                         unify=False, plot=reporte, thumbnail=get_thumb("error.png")))

    return (itemlist, environment)