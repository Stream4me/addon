# -*- coding: utf-8 -*-
import threading

import xbmc, xbmcgui, sys, channelselector, time, os
from core.support import dbg, tmdb
from core.item import Item
from core import channeltools, servertools, scrapertools
from platformcode import platformtools, config, logger
from platformcode.launcher import run
from threading import Thread
from specials.search import save_search

if sys.version_info[0] >= 3:
    PY3 = True
    from concurrent import futures
else:
    PY3 = False
    from concurrent_py2 import futures

info_language = ["de", "en", "es", "fr", "it", "pt"] # from videolibrary.json
def_lang = info_language[config.get_setting("info_language", "videolibrary")]
close_action = False
update_lock = threading.Lock()
moduleDict = {}
searchActions = []
thread = None


def busy(state):
    if state: xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    else: xbmc.executebuiltin('Dialog.Close(busydialognocancel)')


def set_workers():
    workers = config.get_setting('thread_number') if config.get_setting('thread_number') > 0 else None
    return workers


def Search(*args):
    xbmc.executebuiltin('Dialog.Close(all)')
    w = SearchWindow('GlobalSearch.xml', config.get_runtime_path())
    w.start(*args)
    del w

# Actions
LEFT = 1
RIGHT = 2
UP = 3
DOWN = 4
ENTER = 7
EXIT = 10
BACKSPACE = 92
SWIPEUP = 531
CONTEXT = 117
MOUSEMOVE = 107
FULLSCREEN = 18

# Container
SEARCH = 1
EPISODES = 2
SERVERS = 3
NORESULTS = 4
LOADING = 5

# Search
MAINTITLE = 100
CHANNELS = 101
RESULTS = 102

PROGRESS = 500
COUNT = 501
MENU = 502
BACK = 503
CLOSE = 504
QUALITYTAG = 505

# Servers
EPISODESLIST = 200
SERVERLIST = 300

class SearchWindow(xbmcgui.WindowXML):
    global thread
    def start(self, item, thActions=None):
        logger.debug()
        self.exit = False
        self.item = item
        self.type = self.item.mode
        self.channels = []
        self.persons = []
        self.episodes = []
        self.results = {}
        self.focus = SEARCH
        self.page = 1
        self.moduleDict = moduleDict
        self.searchActions = searchActions
        self.thread = None
        self.selected = False
        self.pos = 0
        self.items = []
        self.search_threads = []

        if not thActions:
            self.thActions = Thread(target=self.getActionsThread)
            self.thActions.start()
        else:
            self.thActions = thActions

        self.lastSearch()
        if not self.item.text: return

        self.doModal()

    def lastSearch(self):
        logger.debug()
        if not self.item.text:
            if self.item.contentTitle:
                self.item.text = self.item.contentTitle
            elif self.item.contentSerieName:
                self.item.text = self.item.contentSerieName

            if not self.item.text:
                if config.get_setting('last_search'): last_search = channeltools.get_channel_setting('Last_searched', 'search', '')
                else: last_search = ''
                if not self.item.text: self.item.text = platformtools.dialog_input(default=last_search, heading='')
                if self.item.text:
                    channeltools.set_channel_setting('Last_searched', self.item.text, 'search')
                    if self.item.mode == 'all':
                        save_search(self.item.text)
        else:
            if self.item.context:
                del self.item.context  # needed for preventing same content twice in saved search
            save_search(self.item.__dict__)

    def getActionsThread(self):
        logger.debug()
        self.channelsList = self.get_channels()
        for channel in self.channelsList:
            logger.debug(channel)
            try:
                module = __import__('channels.%s' % channel, fromlist=["channels.%s" % channel])
                mainlist = getattr(module, 'mainlist')(Item(channel=channel, global_search=True))
                action = [elem for elem in mainlist if elem.action == "search" and (
                            self.item.mode in ['all', 'person'] or elem.contentType in [self.item.type, 'undefined'])]
                self.moduleDict[channel] = module
                self.searchActions += action
            except:
                import traceback
                logger.error('error importing/getting search items of ' + channel)
                logger.error(traceback.format_exc())

    def getActions(self):
        # return immediately all actions that are already loadead
        for action in self.searchActions:
            yield action
        # wait and return as getActionsThread load
        lastLen = len(self.searchActions)
        logger.debug('LAST LEN:', lastLen)
        while self.thActions.is_alive() or lastLen < len(self.searchActions):
            while len(self.searchActions) == lastLen:
                if not self.thActions.is_alive():
                    return
                # time.sleep(0.1)
            yield self.searchActions[lastLen - 1]
            lastLen = len(self.searchActions)
            logger.debug(lastLen)

    def select(self):
        logger.debug()
        self.PROGRESS.setVisible(False)
        self.items = []
        if self.item.mode == 'person_':
            tmdb_info = tmdb.discovery(self.item, dict_=self.item.discovery)
            results = tmdb_info.results.get('cast',[])
        else:
            tmdb_info = tmdb.Tmdb(searched_text=self.item.text, search_type=self.item.mode.replace('show', ''))
            results = tmdb_info.results

        for result in results:
            result = tmdb_info.get_infoLabels(result, origen=result)
            if self.item.mode == 'movie':
                title = result['title']
                result['mode'] = 'movie'
            elif self.item.mode == 'tvshow':
                title = result['name']
                result['mode'] = 'tvshow'
            else:
                title = result.get('title', '')
                result['mode'] = result['media_type'].replace('tv', 'tvshow')

            thumbnail = result.get('thumbnail', '')
            noThumb = 'Infoplus/' + result['mode'].replace('show','') + '.png'
            fanart = result.get('fanart', '')
            year = result.get('release_date', '')
            rating = str(result.get('vote_average', ''))

            new_item = Item(channel='globalsearch',
                            action="Search",
                            title=title,
                            thumbnail=thumbnail,
                            fanart=fanart,
                            mode='search',
                            type=result['mode'],
                            contentType=result['mode'],
                            text=title,
                            infoLabels=result)

            if self.item.mode == 'movie':
                new_item.contentTitle = result['title']
            else:
                new_item.contentSerieName = result['name']

            it = xbmcgui.ListItem(title)
            it.setProperties({'thumb': result.get('thumbnail', noThumb), 'fanart': result.get('fanart', ''), 'rating': '    [' + rating + ']' if rating else '',
                              'plot': result.get('overview', ''), 'search': 'search', 'release_date': '', 'item': new_item.tourl(),
                              'year': '   [' + year.split('/')[-1] + ']' if year else '    [' + result.get('first_air_date','').split('-')[0] + ']'})
            self.items.append(it)

        if self.items:
            self.RESULTS.reset()
            self.RESULTS.addItems(self.items)
            self.setFocusId(RESULTS)
        else:
            self.RESULTS.setVisible(False)
            self.NORESULTS.setVisible(True)
            self.setFocusId(CLOSE)

    def actors(self):
        logger.debug()
        self.PROGRESS.setVisible(False)
        items = []

        dict_ = {'url': 'search/person', 'language': def_lang, 'query': self.item.text, 'page':self.page}
        prof = {'Acting': 'Actor', 'Directing': 'Director', 'Production': 'Productor'}
        plot = ''
        self.item.search_type = 'person'
        tmdb_inf = tmdb.discovery(self.item, dict_=dict_)
        results = tmdb_inf.results

        for elem in results:
            name = elem.get('name', '')
            if not name: continue
            rol = elem.get('known_for_department', '')
            rol = prof.get(rol, rol)
            know_for = elem.get('known_for', '')
            cast_id = elem.get('id', '')
            if know_for:
                t_k = know_for[0].get('title', '')
                if t_k: plot = '%s in %s' % (rol, t_k)

            t = elem.get('profile_path', '')
            if t: thumb = 'https://image.tmdb.org/t/p/original' + t
            else : thumb = 'Infoplus/no_photo.png'

            discovery = {'url': 'person/%s/combined_credits' % cast_id, 'page': '1', 'sort_by': 'primary_release_date.desc', 'language': def_lang}
            self.persons.append(discovery)

            new_item = Item(channel='globalsearch',
                            action="Search",
                            title=name,
                            thumbnail=thumb,
                            mode='search')

            it = xbmcgui.ListItem(name)
            it.setProperties({'thumb': thumb, 'plot': plot, 'search': 'persons', 'item': new_item.tourl()})
            items.append(it)
        if len(results) > 19:
            it = xbmcgui.ListItem(config.get_localized_string(70006))
            it.setProperty('thumb', 'Infoplus/next_focus.png')
            it.setProperty('search','next')
            items.append(it)
        if self.page > 1:
            it = xbmcgui.ListItem(config.get_localized_string(70005))
            it.setProperty('thumb', 'Infoplus/previous_focus.png')
            it.setProperty('search','previous')
            items.insert(0, it)

        if items:
            self.RESULTS.reset()
            self.RESULTS.addItems(items)
            self.setFocusId(RESULTS)
        else:
            self.RESULTS.setVisible(False)
            self.NORESULTS.setVisible(True)
            self.setFocusId(CLOSE)

    def get_channels(self):
        logger.debug()
        channels_list = []
        all_channels = channelselector.filterchannels('all')

        for ch in all_channels:
            channel = ch.channel
            ch_param = channeltools.get_channel_parameters(channel)
            if not ch_param.get("active", False):
                continue
            list_cat = ch_param.get("categories", [])

            if not ch_param.get("include_in_global_search", False):
                continue

            if 'anime' in list_cat:
                n = list_cat.index('anime')
                list_cat[n] = 'tvshow'

            if self.item.mode in ['all', 'person'] or self.item.mode in list_cat or self.item.type in list_cat:
                if config.get_setting("include_in_global_search", channel) and ch_param.get("active", False):
                    channels_list.append(channel)

        logger.debug('search in channels:', channels_list)

        return channels_list

    def timer(self):
        while self.searchActions or self.thActions.is_alive():
            if self.exit: return
            try:
                percent = (float(self.count) / len(self.searchActions)) * 100
            except ZeroDivisionError:
                percent = 0
            self.PROGRESS.setPercent(percent)
            self.COUNT.setText('%s/%s [%s"]' % (self.count, len(self.searchActions), int(time.time() - self.time)))
            if percent == 100 and not self.thActions.is_alive():
                self.channels = []
                self.moduleDict = {}
                self.searchActions = []

                # if no results
                total = 0
                for num in self.results.values():
                    total += num
                if not total:
                    self.PROGRESS.setVisible(False)
                    self.NORESULTS.setVisible(True)
                    self.setFocusId(CLOSE)
            time.sleep(1)

    def search(self):
        logger.debug()
        self.count = 0
        self.LOADING.setVisible(True)
        Thread(target=self.timer).start()

        # --- S4Me Assistant: pre-risoluzione domini ---
        try:
            from core import s4me_assistant
            if s4me_assistant.is_enabled():
                # Attendi che la lista canali sia pronta
                self.thActions.join()
                # Estrai i nomi dei canali dalle searchActions caricate
                channel_names = list(set(a.channel for a in self.searchActions))
                if channel_names:
                    logger.info("S4Me: avvio pre-risoluzione per %d canali" % len(channel_names))
                    s4me_assistant.pre_resolve_domains(channel_names)
        except ImportError:
            pass
        except Exception as e:
            logger.error("S4Me pre-resolve error: %s" % str(e))
        # --- Fine S4Me Assistant ---

        try:
            with futures.ThreadPoolExecutor(max_workers=set_workers()) as executor:
                for searchAction in self.getActions():
                    if self.exit: break
                    self.search_threads.append(executor.submit(self.get_channel_results, searchAction))
                for res in futures.as_completed(self.search_threads):
                    if self.exit: break
                    if res.result():
                        channel, valid, results = res.result()
                        self.update(channel, valid, results)

                        # if results:
                        #     name = results[0].channel
                        #     if name not in results: 
                        #         self.channels[name] = []
                        #     self.channels[name].extend(results)

                        # if valid or results:
                        #     self.update()
        except:
            import traceback
            logger.error(traceback.format_exc())
        self.count = len(self.searchActions)

    def get_channel_results(self, searchAction):
        def channel_search(text):
            valid = []
            other = []
            results = self.moduleDict[channel].search(searchAction, text)
            if len(results) == 1:
                if not results[0].action or results[0].nextPage:
                    results = []

            if self.item.mode != 'all':
                for elem in results:
                    if elem.infoLabels.get('tmdb_id') == self.item.infoLabels.get('tmdb_id'):
                        elem.from_channel = channel
                        elem.verified = 1
                        valid.append(elem)
                    else:
                        other.append(elem)
            return results, valid, other

        logger.debug()
        channel = searchAction.channel
        results = []
        valid = []
        other = []

        try:
            results, valid, other = channel_search(self.item.text)
            if self.exit: return

            # if we are on movie search but no valid results is found, and there's a lot of results (more pages), try
            # to add year to search text for better filtering
            if self.item.contentType == 'movie' and not valid and other and other[-1].nextPage \
                    and self.item.infoLabels['year']:
                logger.debug('retring adding year on channel ' + channel)
                dummy, valid, dummy = channel_search(self.item.text + " " + str(self.item.infoLabels['year']))

            if self.exit: return
            # some channels may use original title
            if self.item.mode != 'all' and not valid and self.item.infoLabels.get('originaltitle'):
                original = scrapertools.title_unify(self.item.infoLabels.get('originaltitle'))
                if self.item.text != original:
                    logger.debug('retring with original title on channel ' + channel)
                    dummy, valid, dummy = channel_search(original)
        except:
            import traceback
            logger.error(traceback.format_exc())

        if self.exit: return
        # update_lock.acquire()
        self.count += 1

        return channel, valid, other if other else results
        # update_lock.release()

    def makeItem(self, url):
        item = Item().fromurl(url)
        channelParams = channeltools.get_channel_parameters(item.channel)
        thumb = item.thumbnail if item.thumbnail else 'Infoplus/' + item.contentType.replace('show', '') + '.png'
        logger.info('THUMB', thumb)
        it = xbmcgui.ListItem(item.title)
        year = str(item.year if item.year else item.infoLabels.get('year', ''))
        rating = str(item.infoLabels.get('rating', ''))
        it.setProperties({'thumb': thumb, 'fanart': item.fanart, 'plot': item.plot,
                          'year': '    [' + year + ']' if year else '', 'rating':'    [' + rating + ']' if rating else '',
                          'item': url, 'verified': item.verified, 'channel':channelParams['title'], 'channelthumb': channelParams['thumbnail'] if item.verified else ''})
        if item.server:
            color = scrapertools.find_single_match(item.alive, r'(FF[^\]]+)')
            it.setProperties({'channel': channeltools.get_channel_parameters(item.channel).get('title', ''),
                              'thumb': config.get_online_server_thumb(item.server),
                              'servername': servertools.get_server_parameters(item.server.lower()).get('name', item.server),
                              'color': color if color else 'FF0082C2'})

        return it

    def update(self, channel, valid, results):
        update_lock.acquire()
        self.LOADING.setVisible(False)
        if self.exit:
            return
        logger.debug('Search on channel', channel)
        if self.item.mode != 'all' and 'valid' not in self.results:
            self.results['valid'] = 0
            item = xbmcgui.ListItem('valid')
            item.setProperties({'thumb': 'valid.png',
                                'position': '0',
                                'results': '0'})
            self.channels.append(item)
            pos = self.CHANNELS.getSelectedPosition()
            self.CHANNELS.addItems(self.channels)
            self.CHANNELS.selectItem(pos)
            self.setFocusId(RESULTS)

        if valid and self.CHANNELS.size():
            item = self.CHANNELS.getListItem(0)
            resultsList = item.getProperty('items')
            for result in valid:
                resultsList += result.tourl() + '|'
            item.setProperty('items', resultsList)
            res = len(resultsList.split('|'))
            self.channels[0].setProperty('results', str(res - 1  if res > 0 else 0))

            if self.CHANNELS.getSelectedPosition() == 0:
                items = []
                for result in valid:
                    if result: items.append(self.makeItem(result.tourl()))
                pos = self.RESULTS.getSelectedPosition()
                self.RESULTS.addItems(items)
                if pos < 0:
                    self.setFocusId(RESULTS)
                    pos = 0
                self.RESULTS.selectItem(pos)

        if results:
            resultsList = ''
            channelParams = channeltools.get_channel_parameters(channel)
            name = channelParams['title']
            if name not in self.results:
                item = xbmcgui.ListItem(name)
                item.setProperties({'thumb': channelParams['thumbnail'],
                                    'position': '0',
                                    'results': str(len(results))
                                    })
                for result in results:
                    resultsList += result.tourl() + '|'
                item.setProperty('items', resultsList)
                self.results[name] = len(self.results)
                self.channels.append(item)
            else:
                item = self.CHANNELS.getListItem(self.results[name])
                resultsList = item.getProperty('items')
                for result in results:
                    resultsList += result.tourl() + '|'
                item.setProperty('items',resultsList)
                logger.log(self.channels[int(self.results[name])])
                res = len(resultsList.split('|'))
                self.channels[int(self.results[name])].setProperty('results', str(res - 1 if res > 0 else 0))
            pos = self.CHANNELS.getSelectedPosition()
            self.CHANNELS.reset()
            self.CHANNELS.addItems(self.channels)
            self.CHANNELS.selectItem(pos)

            if len(self.channels) == 1:
                self.setFocusId(CHANNELS)
                channelResults = self.CHANNELS.getListItem(self.results[name]).getProperty('items').split('|')
                items = []
                for result in channelResults:
                    if result: items.append(self.makeItem(result))
                self.RESULTS.reset()
                self.RESULTS.addItems(items)
        update_lock.release()

    def onInit(self):
        self.time = time.time()

        # collect controls
        self.CHANNELS = self.getControl(CHANNELS)
        self.RESULTS = self.getControl(RESULTS)
        self.PROGRESS = self.getControl(PROGRESS)
        self.COUNT = self.getControl(COUNT)
        self.MAINTITLE = self.getControl(MAINTITLE)
        self.MAINTITLE.setText(config.get_localized_string(30993).replace('...', '') % '"%s"' % self.item.text)
        self.SEARCH = self.getControl(SEARCH)
        self.EPISODES = self.getControl(EPISODES)
        self.EPISODESLIST = self.getControl(EPISODESLIST)
        self.SERVERS = self.getControl(SERVERS)
        self.SERVERLIST = self.getControl(SERVERLIST)
        self.NORESULTS = self.getControl(NORESULTS)
        self.NORESULTS.setVisible(False)
        self.LOADING = self.getControl(LOADING)
        self.LOADING.setVisible(False)

        self.Focus(self.focus)

        if self.type:
            self.type = None
            if self.item.mode in ['all', 'search']:
                if self.item.type:
                    self.item.mode = self.item.type
                    self.item.text = scrapertools.title_unify(self.item.text)
                thread = Thread(target=self.search)
                thread.start()
            elif self.item.mode in ['movie', 'tvshow', 'person_']:
                self.select()
            elif self.item.mode in ['person']:
                self.actors()

    def Focus(self, focusid):
        if focusid in [SEARCH]:
            self.focus = CHANNELS
            self.SEARCH.setVisible(True)
            self.EPISODES.setVisible(False)
            self.SERVERS.setVisible(False)
        if focusid in [EPISODES]:
            self.focus = focusid
            self.SEARCH.setVisible(False)
            self.EPISODES.setVisible(True)
            self.SERVERS.setVisible(False)
        if focusid in [SERVERS]:
            self.focus = SERVERLIST
            self.SEARCH.setVisible(False)
            self.EPISODES.setVisible(False)
            self.SERVERS.setVisible(True)

    def onAction(self, action):
        global close_action
        action = action.getId()
        focus = self.getFocusId()

        if action in [CONTEXT] and focus in [RESULTS, EPISODESLIST, SERVERLIST]:
            self.context()

        elif action in [SWIPEUP] and self.CHANNELS.isVisible():
            self.setFocusId(CHANNELS)
            pos = self.CHANNELS.getSelectedPosition()
            self.CHANNELS.selectItem(pos)

        elif action in [LEFT, RIGHT, MOUSEMOVE] and focus in [CHANNELS] and self.CHANNELS.isVisible():
            update_lock.acquire()
            items = []
            name = self.CHANNELS.getSelectedItem().getLabel()
            subpos = int(self.CHANNELS.getSelectedItem().getProperty('position'))
            channelResults = self.CHANNELS.getListItem(self.results[name]).getProperty('items').split('|')
            for result in channelResults:
                if result: items.append(self.makeItem(result))
            self.RESULTS.reset()
            self.RESULTS.addItems(items)
            self.RESULTS.selectItem(subpos)
            update_lock.release()

        elif (action in [DOWN] and focus in [BACK, CLOSE, MENU]) or focus not in [BACK, CLOSE, MENU, SERVERLIST, EPISODESLIST, RESULTS, CHANNELS]:
            if self.SERVERS.isVisible(): self.setFocusId(SERVERLIST)
            elif self.EPISODES.isVisible(): self.setFocusId(EPISODESLIST)
            elif self.RESULTS.isVisible() and self.RESULTS.size() > 0: self.setFocusId(RESULTS)
            elif self.CHANNELS.isVisible(): self.setFocusId(CHANNELS)

        elif focus in [RESULTS]:
            pos = self.RESULTS.getSelectedPosition()
            try:
                self.CHANNELS.getSelectedItem().setProperty('position', str(pos))
            except:
                pass

        elif action == ENTER and focus in [CHANNELS]:
            self.setFocusId(RESULTS)

        if action in [BACKSPACE]:
            self.Back()

        elif action in [EXIT]:
            self.Close()
            close_action = True
            xbmc.sleep(500)

    def onClick(self, control_id):
        global close_action

        if self.RESULTS.getSelectedItem(): search = self.RESULTS.getSelectedItem().getProperty('search')
        else: search = None
        if control_id in [CHANNELS]:
            items = []
            name = self.CHANNELS.getSelectedItem().getLabel()
            subpos = int(self.CHANNELS.getSelectedItem().getProperty('position'))
            channelResults = self.CHANNELS.getListItem(self.results[name]).getProperty('items').split('|')
            for result in channelResults:
                if result: items.append(self.makeItem(result))
            self.RESULTS.reset()
            self.RESULTS.addItems(items)
            self.RESULTS.selectItem(subpos)
            self.CHANNELS.getSelectedItem().setProperty('position', str(subpos))

        elif control_id in [BACK]:
            self.Back()

        elif control_id in [CLOSE]:
            self.Close()
            close_action = True

        elif control_id in [MENU]:
            self.context()

        elif search:
            pos = self.RESULTS.getSelectedPosition()
            if search == 'next':
                self.page += 1
                self.actors()
            elif search == 'previous':
                self.page -= 1
                self.actors()
            elif search == 'persons':
                item = Item().fromurl(self.RESULTS.getSelectedItem().getProperty('item')).clone(mode='person_', discovery=self.persons[pos], text=True, folder=False)
                Search(item, self.thActions)
                if close_action:
                    self.close()
            else:
                item = Item().fromurl(self.RESULTS.getSelectedItem().getProperty('item'))
                if self.item.mode == 'movie': item.contentTitle = self.RESULTS.getSelectedItem().getLabel()
                else: item.contentSerieName = self.RESULTS.getSelectedItem().getLabel()
                item.folder = False

                logger.debug(item)
                Search(item, self.thActions)
                if close_action:
                    self.close()

        elif control_id in [RESULTS, EPISODESLIST]:
            busy(True)
            if control_id in [RESULTS]:
                name = self.CHANNELS.getSelectedItem().getLabel()
                self.pos = self.RESULTS.getSelectedPosition()
                item = Item().fromurl(self.RESULTS.getSelectedItem().getProperty('item'))
            else:
                item_url = self.EPISODESLIST.getSelectedItem().getProperty('item')
                if item_url:
                    item = Item().fromurl(item_url)
                else:  # no results  item
                    busy(False)
                    return

                if item.action != 'episodios':
                    xbmc.executebuiltin("RunPlugin(plugin://plugin.video.s4me/?" + item_url + ")")
                    busy(False)
                    return

            try:
                self.channel = __import__('channels.%s' % item.channel, fromlist=["channels.%s" % item.channel])
                self.itemsResult = getattr(self.channel, item.action)(item)
                if self.itemsResult and self.itemsResult[0].server:
                    from platformcode.launcher import findvideos
                    busy(False)
                    findvideos(self.item, self.itemsResult)
                    return
            except:
                import traceback
                logger.error('error importing/getting search items of ' + item.channel)
                logger.error(traceback.format_exc())
                self.itemsResult = []

            self.episodes = self.itemsResult if self.itemsResult else []
            self.itemsResult = []
            ep = []
            for item in self.episodes:
                it = xbmcgui.ListItem(item.title)
                it.setProperty('item', item.tourl())
                ep.append(it)

            if not ep:
                ep = [xbmcgui.ListItem(config.get_localized_string(60347))]
                ep[0].setProperty('thumb', channelselector.get_thumb('nofolder.png'))

            self.Focus(EPISODES)
            self.EPISODESLIST.reset()
            self.EPISODESLIST.addItems(ep)
            self.setFocusId(EPISODESLIST)

            busy(False)

        elif control_id in [SERVERLIST]:
            server = Item().fromurl(self.getControl(control_id).getSelectedItem().getProperty('item'))
            return self.play(server)

    def Back(self):
        self.getControl(QUALITYTAG).setText('')
        if self.SERVERS.isVisible():
            if self.episodes:
                self.Focus(EPISODES)
                self.setFocusId(EPISODESLIST)
            else:
                self.Focus(SEARCH)
                self.setFocusId(RESULTS)
                self.RESULTS.selectItem(self.pos)
        elif self.EPISODES.isVisible():
            self.episodes = []
            self.Focus(SEARCH)
            self.setFocusId(RESULTS)
            self.RESULTS.selectItem(self.pos)
        else:
            self.Close()

    def Close(self):
        self.exit = True
        if thread and thread.is_alive():
            busy(True)
            for th in self.search_threads:
                th.cancel()
            thread.join()
            busy(False)
        self.close()

    def context(self):
        focus = self.getFocusId()
        if focus == EPISODESLIST:  # context on episode
            item_url = self.EPISODESLIST.getSelectedItem().getProperty('item')
            parent = Item().fromurl(self.RESULTS.getSelectedItem().getProperty('item'))
        elif focus == SERVERLIST:
            item_url = self.SERVERLIST.getSelectedItem().getProperty('item')
            parent = Item().fromurl(self.RESULTS.getSelectedItem().getProperty('item'))
        else:
            item_url = self.RESULTS.getSelectedItem().getProperty('item')
            parent = self.item
        item = Item().fromurl(item_url)
        parent.noMainMenu = True
        commands = platformtools.set_context_commands(item, item_url, parent)
        context = [c[0] for c in commands]
        context_commands = [c[1].replace('Container.Refresh', 'RunPlugin').replace('Container.Update', 'RunPlugin') for c in commands]
        index = xbmcgui.Dialog().contextmenu(context)
        if index > -1: xbmc.executebuiltin(context_commands[index])


    def play(self, server=None):
        platformtools.prevent_busy()
        server.window = True
        server.globalsearch = True
        return run(server)
