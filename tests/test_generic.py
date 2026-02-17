# -*- coding: utf-8 -*-
# use export PYTHONPATH=addon source code
# and inside .kodi to run tests locally
# you can pass specific channel name using S4ME_TST_CH environment var

# export PYTHONPATH=/home/user/.kodi/addons/plugin.video.s4me
# export S4ME_TST_CH=channel
# python tests/test_generic.py
import html
import os
import random
import sys
import time
import unittest
import datetime
import xbmc

if 'S4ME_TST_CH' not in os.environ:
    from sakee import addoninfo
    # custom paths
    def add_on_info(*args, **kwargs):
        return addoninfo.AddonData(
            kodi_home_path=os.path.join(os.getcwd(), 'tests', 'home'),
            add_on_id='plugin.video.s4me',
            add_on_path=os.getcwd(),
            kodi_profile_path=os.path.join(os.getcwd(), 'tests', 'home', 'userdata')
        )

    # override
    addoninfo.get_add_on_info_from_calling_script = add_on_info

# functions that on kodi 19 moved to xbmcvfs
try:
    import xbmcvfs
    xbmc.translatePath = xbmcvfs.translatePath
    xbmc.validatePath = xbmcvfs.validatePath
    xbmc.makeLegalFilename = xbmcvfs.makeLegalFilename
except:
    pass

import HtmlTestRunner
import parameterized

from platformcode import config, logger

config.set_setting('tmdb_active', False)

librerias = os.path.join(config.get_runtime_path(), 'lib')
sys.path.insert(0, librerias)
from core.support import typo
from core.item import Item
from core.httptools import downloadpage
from core import servertools, httptools
import channelselector
import re

logger.DEBUG_ENABLED = False
httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT = 10

outDir = os.path.join(os.getcwd(), 'reports')
validUrlRegex = re.compile(
    r'^(?:http|ftp)s?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
    r'localhost|'  # localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)

chBlackList = ['url', 'mediasetplay', 'metalvideo', 'accuradio', 'cinetecadibologna', 'tunein']
srvBlacklist = ['mega', 'hdmario', 'torrent', 'youtube']
chNumRis = {
    'altadefinizione01': {
        'Film': 30
    },
    'altadefinizione01_link': {
        'Film': 16,
        'Serie TV': 16,
    },
    'altadefinizioneclick': {
        'Film': 36,
        'Serie TV': 36,
    },
    'casacinema': {
        'Film': 10,
        'Serie TV': 10,
    },
    'cineblog01': {
        'Film': 12,
        'Serie TV': 13
    },
    'cinemalibero': {
        'Film': 20,
        'Serie TV': 20,
    },
    'cinetecadibologna': {
        'Film': 10
    },
    'eurostreaming': {
        'Serie TV': 18
    },
    'Filmpertutti': {
        'Film': 24,
        'Serie TV': 24,
    },
    'hd4me': {
        'Film': 10
    },
    'ilgeniodellostreaming': {
        'Film': 30,
        'Serie TV': 30
    },
    'italiaserie': {
        'Serie TV': 15
    },
    'casacinemaInfo': {
        'Film': 150
    },
    'netfreex': {
        'Film': 30,
        'Serie TV': 30
    },
    'piratestreaming': {
        'Film': 24,
        'Serie TV': 24
    },
    'polpotv': {
        'Film': 12,
        'Serie TV': 12
    },
    'streamingaltadefinizione': {
        'Film': 30,
        'Serie TV': 30
    },
    'seriehd': {
        'Serie TV': 12
    },
    'serietvonline': {
        'Film': 25,
        'Serie TV': 35
    },
    'tantifilm': {
        'Film': 20,
        'Serie TV': 20
    },
}


def wait():
    pass
    # time.sleep(random.randint(1, 3))


servers = []
channels = []
channel_list = channelselector.filterchannels("all") if 'S4ME_TST_CH' not in os.environ else [Item(channel=os.environ['S4ME_TST_CH'], action="mainlist")]
logger.DEBUG_ENABLED = True
logger.info([c.channel for c in channel_list])
results = []

logger.record = True
for chItem in channel_list:
    ch = chItem.channel
    wait()
    if ch not in chBlackList:
        hasChannelConfig = False
        mainlist = []
        module = None
        error = None
        menuItemlist = {}
        serversFound = {}
        firstContent = None  # to check search
        logMenu = {}

        try:
            module = __import__('channels.%s' % ch, fromlist=["channels.%s" % ch])
            mainlist = module.mainlist(Item())
        except:
            import traceback
            logger.error(traceback.format_exc())
            error = logger.recordedLog
            logger.recordedLog = ''
        for it in mainlist:
            wait()
            try:
                now = datetime.datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print(current_time + 'preparing ' + ch + ' -> ' + it.title)

                if it.action == 'channel_config':
                    hasChannelConfig = True
                    continue

                if it.action == 'search':
                    # no title to search
                    if not firstContent:
                        continue
                    itemlist = module.search(it, firstContent)
                else:
                    itemlist = getattr(module, it.action)(it)

                    # if more search action (ex: movie, tvshow), firstcontent need to be changed in every menu
                    if itemlist and itemlist[0].action in ('findvideos', 'episodios'):
                        for it2 in itemlist:
                            # some sites refuse to search if the search term is too short
                            title = it2.fulltitle if it2.contentType == 'movie' else it2.contentSerieName
                            if len(title) > 5:
                                firstContent = re.match('[ \w]*', title).group(0)
                                break

                    # some sites might have no link inside, but if all results are without servers, there's something wrong
                    for resIt in itemlist:
                        wait()
                        if resIt.action == 'findvideos' or resIt.action == 'episodios':
                            if hasattr(module, resIt.action):
                                serversFound[it.title] = getattr(module, resIt.action)(resIt)
                                if serversFound[it.title] and resIt.action == 'episodios':
                                    wait()
                                    serversFound[it.title] = getattr(module, serversFound[it.title][0].action)(serversFound[it.title][0])
                            else:
                                serversFound[it.title] = [resIt]

                            if serversFound[it.title]:
                                if hasattr(module, 'play'):
                                    tmp = []
                                    for srv in serversFound[it.title]:
                                        itPlay = getattr(module, 'play')(srv)
                                        if itPlay:
                                            tmp.append(itPlay[0])
                                    serversFound[it.title] = tmp
                                for srv in serversFound[it.title]:
                                    if srv.server:
                                        srv.foundOn = ch + ' --> ' + it.title + ' --> ' + resIt.title
                                        servers.append({'name': srv.server.lower(), 'server': srv})
                                break
                menuItemlist[it.title] = itemlist
            except Exception as ex:
                import traceback
                menuItemlist[it.title] = {
                    'traceback': traceback.format_exc(),
                    'exception': ex
                }

            logMenu[it.title] = logger.recordedLog
            logger.recordedLog = ''

        # results.append(
        #     {'ch': ch, 'hasChannelConfig': hasChannelConfig, 'mainlist': [it.title for it in mainlist],
        #      'menuItemlist': {k: [it.tojson() if type(it) == Item else it for it in menuItemlist[k]] for k in menuItemlist.keys()},
        #      'serversFound': {k: [it.tojson() if type(it) == Item else it for it in menuItemlist[k]] for k in menuItemlist.keys()},
        #      'module': str(module), 'logMenu': logMenu, 'error': error})
        channels.append({'ch': ch, 'hasChannelConfig': hasChannelConfig, 'mainlist': mainlist,
                        'menuItemlist': menuItemlist, 'serversFound': serversFound, 'module': module,
                         'logMenu': logMenu, 'error': error})

logger.record = False

from specials import news
dictNewsChannels, any_active = news.get_channels_list()
# if not os.path.isdir(outDir):
#     os.mkdir(outDir)
# json.dump(results, open(os.path.join(outDir, 'result.json'), 'w'))

# only 1 server item for single server
serverNames = []
serversFinal = []
for s in servers:
    if s['name'] not in serverNames and s['name'] not in srvBlacklist:
        serverNames.append(s['name'])
        serversFinal.append(s)


@parameterized.parameterized_class(channels)
class GenericChannelTest(unittest.TestCase):
    def test_mainlist(self):
        self.assertIsNone(self.error, self.error)
        self.assertTrue(self.mainlist, 'channel ' + self.ch + ' has no mainlist')
        self.assertTrue(self.hasChannelConfig, 'channel ' + self.ch + ' has no channel config')

    def test_newest(self):
        for cat in dictNewsChannels:
            for ch in dictNewsChannels[cat]:
                if self.ch == ch[0]:
                    itemlist = self.module.newest(cat)
                    self.assertTrue(itemlist, 'channel ' + self.ch + ' returned no news for category ' + cat)
                    break


def testnameCh(cls, num, params_dict):
    return 'channels.' + params_dict['ch'] + ' -> ' + params_dict['title']


def testnameSrv(cls, num, params_dict):
    return 'servers.' + params_dict['name']


@parameterized.parameterized_class(
    [{'ch': ch['ch'], 'title': title, 'itemlist': itemlist,
      'serversFound': ch['serversFound'][title] if title in ch['serversFound'] else True,
      'module': ch['module'], 'log': ch['logMenu'][title]}
     for ch in channels
     for title, itemlist in ch['menuItemlist'].items()], class_name_func=testnameCh)
class GenericChannelMenuItemTest(unittest.TestCase):
    def test_menu(self):
        print('testing ' + self.ch + ' --> ' + self.title)

        logger.info(self.log)
        # returned an error
        if type(self.itemlist) == dict and self.itemlist['exception']:
            logger.error(self.itemlist['traceback'])
            raise self.itemlist['exception']

        self.assertTrue(self.module.host, 'channel ' + self.ch + ' has not a valid hostname')
        self.assertTrue(self.itemlist, 'channel ' + self.ch + ' -> ' + self.title + ' is empty')
        self.assertTrue(self.serversFound,
                        'channel ' + self.ch + ' -> ' + self.title + ' has no servers on all results')

        if self.ch in chNumRis:  # i know how much results should be
            for content in chNumRis[self.ch]:
                if content in self.title:
                    risNum = len([i for i in self.itemlist if i.title != typo(config.get_localized_string(30992), 'color std bold')])  # not count nextpage
                    if 'Search' not in self.title:
                        self.assertEqual(chNumRis[self.ch][content], risNum,
                                         'channel ' + self.ch + ' -> ' + self.title + ' returned wrong number of results<br>'
                                         + str(risNum) + ' but should be ' + str(chNumRis[self.ch][content]) + '<br>' +
                                         '<br>'.join([html.escape(i.title) for i in self.itemlist if not i.nextPage]))
                    break

        for resIt in self.itemlist:
            logger.info(resIt.title + ' -> ' + resIt.url)
            self.assertLess(len(resIt.fulltitle), 110,
                            'channel ' + self.ch + ' -> ' + self.title + ' might contain wrong titles:<br>' + html.escape(resIt.fulltitle))
            if resIt.url:
                self.assertIsInstance(resIt.url, str,
                                      'channel ' + self.ch + ' -> ' + self.title + ' -> ' + html.escape(resIt.title) + ' contain non-string url')
                self.assertIsNotNone(re.match(validUrlRegex, resIt.url),
                                     'channel ' + self.ch + ' -> ' + self.title + ' -> ' + html.escape(resIt.title) + ' might contain wrong url<br>' + html.escape(resIt.url))
            if 'year' in resIt.infoLabels and resIt.infoLabels['year']:
                msgYear = 'channel ' + self.ch + ' -> ' + self.title + ' might contain wrong infolabels year:<br>' + html.escape(str(resIt.infoLabels['year']))
                self.assert_(type(resIt.infoLabels['year']) is int or resIt.infoLabels['year'].isdigit(), msgYear)
                self.assert_(1900 < int(resIt.infoLabels['year']) < 2100, msgYear)

            if resIt.title == typo(config.get_localized_string(30992), 'color std bold'):  # next page
                nextPageItemlist = getattr(self.module, resIt.action)(resIt)
                self.assertTrue(nextPageItemlist,
                                'channel ' + self.ch + ' -> ' + self.title + ' has nextpage not working')

        print('test passed')


@parameterized.parameterized_class(serversFinal, class_name_func=testnameSrv)
class GenericServerTest(unittest.TestCase):
    def test_get_video_url(self):
        module = __import__('servers.%s' % self.name, fromlist=["servers.%s" % self.name])
        page_url = self.server.url
        # httptools.default_headers['Referer'] = self.server.referer
        print('testing ' + page_url)
        print('Found on ' + self.server.foundOn)
        print()

        self.assert_(hasattr(module, 'test_video_exists'), self.name + ' has no test_video_exists')

        if module.test_video_exists(page_url)[0]:
            urls = module.get_video_url(page_url)
            server_parameters = servertools.get_server_parameters(self.name)
            self.assertTrue(urls or server_parameters.get("premium"),
                            self.name + ' scraper did not return direct urls for ' + page_url)
            print(urls)
            for u in urls:
                spl = u[1].split('|')
                if len(spl) == 2:
                    directUrl, headersUrl = spl
                else:
                    directUrl, headersUrl = spl[0], ''
                headers = {}
                if headersUrl:
                    for name in headersUrl.split('&'):
                        h, v = name.split('=')
                        h = str(h)
                        headers[h] = str(v)
                    print(headers)
                if 'magnet:?' in directUrl:  # check of magnet links not supported
                    continue
                page = downloadpage(directUrl, headers=headers, only_headers=True, use_requests=True, verify=False)
                if not page.success and directUrl.split('.')[-1] == 'm3u8':  # m3u8 is a text file and HEAD may be forbidden
                    page = downloadpage(directUrl, headers=headers, use_requests=True, verify=False)

                self.assertTrue(page.success, self.name + ' scraper returned an invalid link')
                self.assertLess(page.code, 400, self.name + ' scraper returned a ' + str(page.code) + ' link')
                contentType = page.headers['Content-Type'].lower()
                self.assert_(contentType.startswith(
                    'video') or 'mpegurl' in contentType or 'octet-stream' in contentType or 'dash+xml' in contentType,
                             self.name + ' scraper did not return valid url for link ' + page_url + '<br>Direct url: ' + directUrl + '<br>Content-Type: ' + page.headers['Content-Type'])
                print('test passed')


if __name__ == '__main__':
    unittest.main(testRunner=HtmlTestRunner.HTMLTestRunner(report_name='report', add_timestamp=False, combine_reports=True,
                 report_title='S4MeTest Suite', template=os.path.join(config.get_runtime_path(), 'tests', 'template.html')), exit=False)
    import webbrowser
    webbrowser.open(os.path.join(outDir, 'report.html'))
