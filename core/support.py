# -*- coding: utf-8 -*-
# -----------------------------------------------------------
# support functions that are needed by many channels, to no repeat the same code
import base64, inspect, os, re, sys

PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int
if PY3:
    from concurrent import futures
    from urllib.request import Request, urlopen
    import urllib.parse as urlparse
    from urllib.parse import urlencode
else:
    from concurrent_py2 import futures
    import urlparse
    from urllib2 import Request, urlopen
    from urllib import urlencode

from time import time
from core import filetools, httptools, scrapertools, servertools, tmdb, channeltools
from core.item import Item
from lib import unshortenit
from platformcode import config
from platformcode.logger import info
from platformcode import logger

channels_order = {'Rai 1': 1,
                  'Rai 2': 2,
                  'Rai 3': 3,
                  'Rete 4': 4,
                  'Canale 5': 5,
                  'Italia 1': 6,
                  'La7': 7,
                  'TV8': 8,
                  'NOVE': 9,
                  '20': 20,
                  'Rai 4': 21,
                  'Iris': 22,
                  'Rai 5': 23,
                  'Rai Movie': 24,
                  'Rai Premium': 25,
                  'Cielo': 26,
                  'Paramount': 27,
                  'La7d': 29,
                  'La 5': 30,
                  'Real Time': 31,
                  'Food Network': 33,
                  'Cine34': 34,
                  'Focus': 35,
                  'Warner Tv': 37,
                  'Giallo': 38,
                  'Top Crime': 39,
                  'Boing': 40,
                  'K2': 41,
                  'Rai Gulp': 42,
                  'Rai Yoyo': 43,
                  'Frisbee': 44,
                  'Cartoonito': 46,
                  'Super': 46,
                  'Rai News 24': 48,
                  'Spike': 49,
                  'Sky TG24': 50,
                  'TGCom': 51,
                  'DMAX': 52,
                  'Rai Storia': 54,
                  'Mediaset Extra': 55,
                  'Home and Garden TV': 56,
                  'Rai Sport piu HD': 57,
                  'Rai Sport': 58,
                  'Motor Trend': 59,
                  'Italia 2': 66,
                  'VH1': 67,
                  'Rai Scuola': 146,
                  'Radio 105': 157,
                  'R101tv': 167,
                  'RMC': 256,
                  'Virgin Radio': 257,
                  'Rai Radio 2': 999,
                  }


def hdpass_get_servers(item):
    def get_hosts(url, quality):
        ret = []
        page = httptools.downloadpage(url, CF=False).data
        mir = scrapertools.find_single_match(page, patron_mir)

        for mir_url, srv in scrapertools.find_multiple_matches(mir, patron_option):
            mir_url = scrapertools.decodeHtmlentities(mir_url)
            logger.debug(mir_url)
            it = hdpass_get_url(item.clone(action='play', quality=quality, url=mir_url))[0]
            # it = item.clone(action="play", quality=quality, title=srv, server=srv, url= mir_url)
            # if not servertools.get_server_parameters(srv.lower()): it = hdpass_get_url(it)[0]   # do not exists or it's empty
            ret.append(it)
        return ret
    # Carica la pagina
    itemlist = []
    if 'hdpass' in item.url or 'hdplayer' in item.url: url = item.url
    else:
        data = httptools.downloadpage(item.url, CF=False).data.replace('\n', '')
        patron = r'<iframe(?: id="[^"]+")? width="[^"]+" height="[^"]+" src="([^"]+)"[^>]+><\/iframe>'
        url = scrapertools.find_single_match(data, patron)
        url = url.replace("&download=1", "")
        if 'hdpass' not in url and 'hdplayer' not in url: return itemlist
    if not url.startswith('http'): url = 'https:' + url
    item.referer = url

    data = httptools.downloadpage(url, CF=False).data
    patron_res = '<div class="buttons-bar resolutions-bar">(.*?)<div class="buttons-bar'
    patron_mir = '<div class="buttons-bar hosts-bar">(.*?)(?:<div id="main-player|<script)'
    patron_option = r'<a href="([^"]+?)"[^>]+>([^<]+?)</a'

    res = scrapertools.find_single_match(data, patron_res)

    # non threaded for webpdb
    # for res_url, res_video in scrapertools.find_multiple_matches(res, patron_option):
    #     res_url = scrapertools.decodeHtmlentities(res_url)
    #     itemlist.extend(get_hosts(res_url, res_video))
    #
    with futures.ThreadPoolExecutor() as executor:
        thL = []
        for res_url, res_video in scrapertools.find_multiple_matches(res, patron_option):
            res_url = scrapertools.decodeHtmlentities(res_url)
            thL.append(executor.submit(get_hosts, res_url, res_video))
        for res in futures.as_completed(thL):
            if res.result():
                itemlist.extend(res.result())

    return server(item, itemlist=itemlist)


def hdpass_get_url(item):
    data = httptools.downloadpage(item.url, CF=False).data
    src = scrapertools.find_single_match(data, r'<iframe allowfullscreen custom-src="([^"]+)')
    if src: item.url = base64.b64decode(src)
    else: item.url = scrapertools.find_single_match(data, r'<iframe allowfullscreen src="([^"]+)')
    item.url, c = unshortenit.unshorten_only(item.url)
    return [item]


def color(text, color):
    return "[COLOR " + color + "]" + text + "[/COLOR]"


def search(channel, item, texto):
    info(item.url + " search " + texto)
    item.url = channel.host + "/?s=" + texto
    try:
        return channel.peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            logger.error("%s" % line)
    return []


def dbg():
    if config.dev_mode():
        try:
            import web_pdb
            if not web_pdb.WebPdb.active_instance:
                import webbrowser
                webbrowser.open('http://127.0.0.1:5555')
            web_pdb.set_trace()
        except:
            pass


def regexDbg(item, patron, headers, data=''):
    if config.dev_mode():
        import json, webbrowser
        url = 'https://regex101.com'

        if not data:
            html = httptools.downloadpage(item.url, headers=headers, ignore_response_code=True).data.replace("'", '"')
            html = html.replace('\n', ' ')
            html = html.replace('\t', ' ')
        else:
            html = data
        headers = {'content-type': 'application/json'}
        data = {
            'regex': patron if PY3 else patron.decode('utf-8'),
            'flags': 'gm',
            'testString': html if PY3 else html.decode('utf-8'),
            'delimiter': '"""',
            'flavor': 'python'
        }
        data = json.dumps(data).encode() if PY3 else json.dumps(data, encoding='latin1')
        r = Request(url + '/api/regex', data, headers=headers)
        r = urlopen(r).read()
        permaLink = json.loads(r)['permalinkFragment']
        webbrowser.open(url + "/r/" + permaLink)


def scrapeLang(scraped, lang, longtitle):
    ##    Aggiunto/modificato per gestire i siti che hanno i video
    ##    in ita e subita delle serie tv nella stessa pagina
    # altrimenti dopo un sub-ita mette tutti quelli a seguire in sub-ita
    # e credo sia utile per filtertools
    language = ''

    if scraped.get('lang'):
        if 'ita' in scraped['lang'].lower(): language = 'ITA'
        if 'sub' in scraped['lang'].lower(): language = 'Sub-' + language

    if not language: language = lang
    if language: longtitle += typo(language, '_ [] color std')
    return language, longtitle


def cleantitle(title):
    cleantitle = ''
    if title:
        if type(title) != str: title.decode('UTF-8')
        title = scrapertools.unescape(title)
        title = scrapertools.decodeHtmlentities(title)
        cleantitle = title.replace('"', "'").replace('×', 'x').replace('–', '-').strip().strip('-').strip()
    return cleantitle

def format_longtitle(title, season = None, episode = None, quality = None, lang = None):
    if season and episode:
        longtitle = season + 'x' + episode.zfill(2) + ' ' + title
    else:
        longtitle = title
    longtitle = typo(longtitle, 'bold')
    longtitle += typo(lang, '_ [] color std') if lang else ''
    longtitle += typo(quality, '_ [] color std') if quality else ''

    return longtitle

def unifyEp(ep):
    # ep = re.sub(r'\s-\s|-|&#8211;|&#215;|×', 'x', scraped['episode'])
    ep = ep.replace('-', 'x')
    ep = ep.replace('&#8211;', 'x')
    ep = ep.replace('&#215;', 'x')
    ep = ep.replace('×', 'x')
    return ep


def scrapeBlock(item, args, block, patron, headers, action, pagination, debug, typeContentDict, typeActionDict, blacklist, search, pag, function, lang, sceneTitle, group, flags):
    itemlist = []
    if debug:
        regexDbg(item, patron, headers, block)
    matches = scrapertools.find_multiple_matches_groups(block, patron, flags)
    logger.debug('MATCHES =', matches)

    known_keys = ['url', 'title', 'title2', 'season', 'episode', 'episode2', 'thumb', 'quality', 'year', 'plot', 'duration', 'genere', 'rating', 'type', 'lang', 'other', 'size', 'seed']
    # Legenda known_keys per i groups nei patron
    # known_keys = ['url', 'title', 'title2', 'season', 'episode', 'thumb', 'quality',
    #                'year', 'plot', 'duration', 'genere', 'rating', 'type', 'lang']
    # url = link relativo o assoluto alla pagina titolo film/serie
    # title = titolo Film/Serie/Anime/Altro
    # title2 = titolo dell'episodio Serie/Anime/Altro
    # season = stagione in formato numerico
    # episode = numero episodio, in formato numerico.
    # thumb = linkrealtivo o assoluto alla locandina Film/Serie/Anime/Altro
    # quality = qualità indicata del video
    # year = anno in formato numerico (4 cifre)
    # duration = durata del Film/Serie/Anime/Altro
    # genere = genere del Film/Serie/Anime/Altro. Es: avventura, commedia
    # rating = punteggio/voto in formato numerico
    # type = tipo del video. Es. movie per film o tvshow per le serie. Di solito sono discrimanti usati dal sito
    # lang = lingua del video. Es: ITA, Sub-ITA, Sub, SUB ITA.
    # AVVERTENZE: Se il titolo è trovato nella ricerca TMDB/TVDB/Altro allora le locandine e altre info non saranno quelle recuperate nel sito.!!!!

    stagione = '' # per quei siti che hanno la stagione nel blocco ma non nelle puntate
    contents = []

    for i, match in enumerate(matches):
        if pagination and (pag - 1) * pagination > i and not search: continue  # pagination
        if pagination and i >= pag * pagination and not search: break          # pagination
        # listGroups = match.keys()
        # match = match.values()

        # if len(listGroups) > len(match):  # to fix a bug
        #     match = list(match)
        #     match.extend([''] * (len(listGroups) - len(match)))

        scraped = {}
        for kk in known_keys:
            val = match[kk] if kk in match else ''
            # val = match[listGroups.index(kk)] if kk in listGroups else ''
            if val and (kk == "url" or kk == 'thumb') and 'http' not in val:
                domain = ''
                if val.startswith('//'):
                    domain = scrapertools.find_single_match(item.url, 'https?:')
                elif val.startswith('/'):
                    domain = scrapertools.find_single_match(item.url, 'https?://[a-z0-9.-]+')
                val = domain + val
            scraped[kk] = val.strip() if type(val) == str else val

        # episode = re.sub(r'\s-\s|-|x|&#8211|&#215;', 'x', scraped['episode']) if scraped['episode'] else ''

        title = cleantitle(scraped.get('title', ''))
        if group and scraped.get('title', '') in contents and not item.grouped:  # same title and grouping enabled
            continue
        if item.grouped and scraped.get('title',
                                        '') != item.fulltitle:  # inside a group different tvshow should not be included
            continue
        contents.append(title)
        title2 = cleantitle(scraped.get('title2', '')) if not group or item.grouped else ''
        quality = scraped.get('quality', '')
        if not quality: quality = item.quality
        # Type = scraped['type'] if scraped['type'] else ''
        plot = cleantitle(scraped.get("plot", ''))

        # if title is set, probably this is a list of episodes or video sources
        # necessaria l'aggiunta di == scraped["title"] altrimenti non prende i gruppi dopo le categorie
        if item.infoLabels["title"] == scraped["title"]:
            infolabels = item.infoLabels
        else:
            if function == 'episodios':
                infolabels = item.infoLabels
            else:
                infolabels = {}
            if scraped['year']:
                infolabels['year'] = scraped['year']
            if scraped["plot"]:
                infolabels['plot'] = plot
            if scraped['duration']:
                dur = scrapertools.find_multiple_matches(scraped['duration'],
                                                             r'([0-9])\s*?(?:[hH]|:|\.|,|\\|\/|\||\s)\s*?([0-9]+)')
                for h, m in dur:
                    scraped['duration'] = int(h) * 60 + int(m)
                if not dur:
                    scraped['duration'] = scrapertools.find_single_match(scraped['duration'], r'(\d+)')
                try:
                    infolabels['duration'] = int(scraped['duration']) * 60
                except:
                    scraped['duration'] = ''
            if scraped['genere']:
                genres = scrapertools.find_multiple_matches(scraped['genere'], '[A-Za-z]+')
                infolabels['genere'] = ", ".join(genres)
            if scraped["rating"]:
                infolabels['rating'] = scrapertools.decodeHtmlentities(scraped["rating"])

        episode = ''

        if not group or item.grouped:
            if scraped['season'] and scraped['episode']:
                stagione = scraped['season']
                ep = unifyEp(scraped['episode'])
                if 'x' in ep:
                    episode = ep.split('x')[0].strip()
                    second_episode = ep.split('x')[1].strip()
                else:
                    episode = ep
                    second_episode = ''
                infolabels['season'] = int(scraped['season'])
                infolabels['episode'] = int(episode)
                episode = str(int(scraped['season'])) +'x'+ str(int(episode)).zfill(2) + ('x' + str(int(second_episode)).zfill(2) if second_episode else '')
            elif item.season:
                infolabels['season'] = int(item.season)
                infolabels['episode'] = int(scrapertools.find_single_match(scraped['episode'], r'(\d+)'))
                episode = item.season +'x'+ scraped['episode'].zfill(2)
            elif item.contentType == 'tvshow' and (scraped['episode'] == '' and scraped['season'] == '' and stagione == ''):
                item.news = 'season_completed'
                episode = ''
            else:
                episode = unifyEp(scraped['episode']) if scraped['episode'] else ''
                try:
                    if 'x' in episode:
                        ep = episode.split('x')
                        episode = str(int(ep[0])).zfill(1) + 'x' + str(int(ep[1])).zfill(2)
                        infolabels['season'] = int(ep[0])
                        infolabels['episode'] = int(ep[1])
                    else:
                        infolabels['episode'] = int(episode)
                    second_episode = scrapertools.find_single_match(episode, r'x\d+x-\d+)')
                    if second_episode: episode = re.sub(r'(\d+x\d+)x\d+',r'\1-', episode) + second_episode.zfill(2)
                except:
                    logger.debug('invalid episode: ' + episode)
                    pass

        if scraped['episode2']:
            episode += '-' + scrapertools.find_single_match(scraped['episode2'], r'(\d+)')

        # make formatted Title [longtitle]
        s = ' - '
        # title = episode + (s if episode and title else '') + title
        longtitle = episode + (s if episode and (title or title2) else '') + title + (s if title and title2 else '') + title2

        if sceneTitle:
            from lib.guessit import guessit
            try:
                parsedTitle = guessit(title)
                title = longtitle = parsedTitle.get('title', '')
                logger.debug('TITOLO',title)
                if parsedTitle.get('source'):
                    quality = parsedTitle.get('source')
                    if type(quality) == list:
                        quality = ','.join(quality)
                    else:
                        quality = str(quality) + ' '
                if parsedTitle.get('screen_size'):
                    quality += str(parsedTitle.get('screen_size', ''))
                quality = quality.strip()
                if not scraped['year']:
                    if type(parsedTitle.get('year', '')) == list:
                        infolabels['year'] =parsedTitle.get('year', '')[0]
                    else:
                        infolabels['year'] = parsedTitle.get('year', '')
                if parsedTitle.get('episode') and parsedTitle.get('season'):
                    longtitle = title + s

                    if type(parsedTitle.get('season')) == list:
                        longtitle += str(parsedTitle.get('season')[0]) + '-' + str(parsedTitle.get('season')[-1])
                        infolabels['season'] = parsedTitle.get('season')[0]
                    else:
                        longtitle += str(parsedTitle.get('season'))
                        infolabels['season'] = parsedTitle.get('season')

                    if type(parsedTitle.get('episode')) == list:
                        longtitle += 'x' + str(parsedTitle.get('episode')[0]).zfill(2) + '-' + str(parsedTitle.get('episode')[-1]).zfill(2)
                        infolabels['episode'] = parsedTitle.get('episode')[0]
                    else:
                        longtitle += 'x' + str(parsedTitle.get('episode')).zfill(2)
                        infolabels['episode'] = parsedTitle.get('episode')

                elif parsedTitle.get('season') and type(parsedTitle.get('season')) == list:
                    longtitle += s + config.get_localized_string(30140) + " " +str(parsedTitle.get('season')[0]) + '-' + str(parsedTitle.get('season')[-1])
                elif parsedTitle.get('season'):
                    longtitle += s + config.get_localized_string(60027) % str(parsedTitle.get('season'))
                    infolabels['season'] = parsedTitle.get('season')
                if parsedTitle.get('episode_title'):
                    longtitle += s + parsedTitle.get('episode_title')
                    infolabels['episodeName'] = parsedTitle.get('episode_title')
                if parsedTitle.get('language'):
                    langs = parsedTitle.get('language')
                    if isinstance(langs, list):
                        lang = 'MULTI'
                    else:
                        lang = vars(langs).get('alpha3').upper()
                    if not (lang.startswith('MUL') or lang.startswith('ITA')):
                        subs = parsedTitle.get('subtitle_language')
                        if isinstance(subs, list):
                            lang = 'Multi-Sub'
                        else:
                            lang = vars(subs).get('alpha3').upper()

            except:
                import traceback
                logger.error(traceback.format_exc())

        longtitle = typo(longtitle, 'bold')
        lang1, longtitle = scrapeLang(scraped, lang, longtitle)
        longtitle += typo(quality, '_ [] color std') if quality else ''
        longtitle += typo(scraped['size'], '_ [] color std') if scraped['size'] else ''
        longtitle += typo(scraped['seed'] + ' SEEDS', '_ [] color std') if scraped['seed'] else ''

        AC = CT = ''
        if typeContentDict:
            for name, variants in typeContentDict.items():
                if str(scraped['type']).lower() in variants:
                    CT = name
                    break
                else: CT = item.contentType
        if typeActionDict:
            for name, variants in typeActionDict.items():
                if str(scraped['type']).lower() in variants:
                    AC = name
                    break
                else: AC = action

        if (not scraped['title'] or scraped["title"] not in blacklist) and (search.lower() in longtitle.lower()):
            contentType = 'episode' if function == 'episodios' else CT if CT else item.contentType
            it = Item(
                channel=item.channel,
                action=AC if AC else action,
                contentType=contentType,
                title=longtitle,
                fulltitle=item.fulltitle if function == 'episodios' else title,
                show=item.show if function == 'episodios' else title,
                quality=quality,
                url=scraped["url"] if scraped["url"] else item.url,
                infoLabels=infolabels,
                thumbnail=item.prevthumb if item.prevthumb else item.thumbnail if not scraped["thumb"] else scraped["thumb"],
                args=item.args,
                contentSerieName= title if contentType not in ['movie'] and function not in ['episodios', 'seasons'] or contentType in ['undefined'] else item.contentSerieName,
                contentTitle= title if contentType in ['movie', 'undefined'] and function == 'peliculas' else item.contentTitle,
                contentLanguage = lang1,
                contentSeason= infolabels.get('season', ''),
                contentEpisodeNumber=infolabels.get('episode', ''),
                news= item.news if item.news else '',
                other = scraped['other'] if scraped['other'] else '',
                q=group,
                disable_videolibrary = not args.get('addVideolibrary', True)
            )
            if scraped['episode'] and group and not item.grouped:  # some adjustment for grouping feature
                it.action = function

            # for lg in list(set(listGroups).difference(known_keys)):
            #     it.__setattr__(lg, match[listGroups.index(lg)])
            for lg in list(set(match.keys()).difference(known_keys)):
                it.__setattr__(lg, match[lg])

            if 'itemHook' in args:
                try:
                    it = args['itemHook'](it)
                except:
                    raise logger.ChannelScraperException
            itemlist.append(it)

    return itemlist, matches


def html_uniform(data):
    """
        replace all ' with " and eliminate newline, so we don't need to worry about
    """
    return re.sub(r"\s+|&nbsp;", " " , re.sub("='([^']+)'", '="\\1"', data))


def scrape(func):
    """https://github.com/stream4me/addon/wiki/decoratori#scrape"""

    def wrapper(*args):
        itemlist = []

        args = func(*args)
        function = func.__name__ if not 'actLike' in args else args['actLike']
        # info('STACK= ',inspect.stack()[1][3])
        item = args['item']

        action = args.get('action', 'episodios' if item.contentType == 'tvshow' and function != 'episodios' else 'findvideos')
        anime = args.get('anime', '')
        addVideolibrary = args.get('addVideolibrary', True)
        search = args.get('search', '')
        blacklist = args.get('blacklist', [])
        data = args.get('data', '')
        patron = args.get('patron', args.get('patronMenu', ''))
        if 'headers' in args:
            headers = args['headers']
        elif 'headers' in func.__globals__:
            headers = func.__globals__['headers']
        else:
            headers = ''
        patronNext = args.get('patronNext', '')
        flags = args.get('flags', re.IGNORECASE)
        patronBlock = args.get('patronBlock', '')
        flagsBlock = args.get('flagsBlock', re.IGNORECASE)
        typeActionDict = args.get('typeActionDict', {})
        typeContentDict = args.get('typeContentDict', {})
        debug = args.get('debug', False)
        debugBlock = args.get('debugBlock', False)
        disabletmdb = args.get('disabletmdb', False)
        if 'pagination' in args and inspect.currentframe().f_back.f_code.co_name not in ['add_tvshow', 'get_episodes', 'update', 'find_episodes']: pagination = args['pagination'] if args['pagination'] else 20
        else: pagination = ''
        lang = args.get('deflang', '')
        sceneTitle = args.get('sceneTitle')
        group = args.get('group', False)
        downloadEnabled = args.get('downloadEnabled', True)
        pag = item.page if item.page else 1  # pagination
        matches = []
        nextPageUrl = args.get('nextPageUrl', '')

        for n in range(2):
            logger.debug('PATRON= ', patron)
            if not data:
                page = httptools.downloadpage(item.url, headers=headers, ignore_response_code=True)
                data = page.data
            data = html_uniform(data)
            scrapingTime = time()
            if patronBlock:
                if debugBlock:
                    regexDbg(item, patronBlock, headers, data)
                blocks = scrapertools.find_multiple_matches_groups(data, patronBlock, flagsBlock)
                for bl in blocks:
                    # info(len(blocks),bl)
                    if 'season' in bl and bl['season']:
                        item.season = bl['season']
                    blockItemlist, blockMatches = scrapeBlock(item, args, bl['block'], patron, headers, action, pagination, debug,
                                                typeContentDict, typeActionDict, blacklist, search, pag, function, lang, sceneTitle, group, flags)
                    for it in blockItemlist:
                        if 'lang' in bl:
                            it.contentLanguage, it.title = scrapeLang(bl, it.contentLanguage, it.title)
                        if 'quality' in bl and bl['quality']:
                            it.quality = bl['quality'].strip()
                            it.title = it.title + typo(bl['quality'].strip(), '_ [] color std')
                    itemlist.extend(blockItemlist)
                    matches.extend(blockMatches)
            elif patron:
                itemlist, matches = scrapeBlock(item, args, data, patron, headers, action, pagination, debug, typeContentDict,
                                       typeActionDict, blacklist, search, pag, function, lang, sceneTitle, group, flags)

            if 'itemlistHook' in args:
                try:
                    itemlist = args['itemlistHook'](itemlist)
                except:
                    raise logger.ChannelScraperException

            # if url may be changed and channel has findhost to update
            if 'findhost' in func.__globals__ and not itemlist and n == 0:
                info('running findhost ' + func.__module__)
                ch = func.__module__.split('.')[-1]
                try:
                    host = config.get_channel_url(func.__globals__['findhost'], ch, True)

                    parse = list(urlparse.urlparse(item.url))
                    parse[1] = scrapertools.get_domain_from_url(host)
                    item.url = urlparse.urlunparse(parse)
                except:
                    raise logger.ChannelScraperException
                data = None
                itemlist = []
                matches = []
            else:
                break

        if not data:
            from platformcode.logger import WebErrorException
            raise WebErrorException(urlparse.urlparse(item.url)[1], item.channel)

        if group and item.grouped or args.get('groupExplode'):
            import copy
            nextArgs = copy.copy(args)
            @scrape
            def newFunc():
                return nextArgs
            nextArgs['item'] = nextPage(itemlist, item, data, patronNext, function, nextPageUrl)
            nextArgs['group'] = False
            if nextArgs['item']:
                nextArgs['groupExplode'] = True
                itemlist.pop()  # remove next page just added
                itemlist.extend(newFunc())
            else:
                nextArgs['groupExplode'] = False
                nextArgs['item'] = item
                itemlist = newFunc()
            itemlist = [i for i in itemlist if i.action not in ['add_pelicula_to_library', 'add_serie_to_library']]
        logger.debug(item.channel + ' scraping time ' + ':', time()-scrapingTime)

        if anime and inspect.currentframe().f_back.f_code.co_name not in ['find_episodes']:
            from platformcode import autorenumber
            if function == 'episodios': autorenumber.start(itemlist, item)
            else: autorenumber.start(itemlist)

        if itemlist and action != 'play' and 'patronMenu' not in args and 'patronGenreMenu' not in args \
            and not stackCheck(['add_tvshow', 'get_newest']) and not disabletmdb and (function not in ['episodios', 'mainlist']
            or (function in ['episodios', 'seasons'] and config.get_setting('episode_info') and itemlist[0].season)):
            # dbg()
            tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)

        if not group and not args.get('groupExplode') and ((pagination and len(matches) <= pag * pagination) or not pagination):  # next page with pagination
            if (patronNext or nextPageUrl) and inspect.currentframe().f_back.f_code.co_name not in ['newest'] and len(inspect.stack(0)) > 2 and inspect.stack(0)[2][3] not in ['get_channel_results']:
                nextPage(itemlist, item, data, patronNext, function, nextPageUrl)

        # for it in itemlist:
        #     if it.contentEpisodeNumber and it.contentSeason:
        #         it.title = '[B]{:d}x{:02d} - {}[/B]'.format(it.contentSeason, it.contentEpisodeNumber, it.infoLabels['title'] if it.infoLabels['title'] else it.fulltitle)
        #         if it.contentLanguage:
        #             it.title += typo(it.contentLanguage, '_ [] color std')
        #         if it.quality:
        #             it.title += typo(it.quality, '_ [] color std')

        # next page for pagination
        if pagination and len(matches) > pag * pagination and not search:
            if inspect.currentframe().f_back.f_code.co_name not in ['newest','get_newest']:
                itemlist.append(
                    Item(channel=item.channel,
                         action = item.action,
                         contentType=item.contentType,
                         title=typo(config.get_localized_string(30992), 'color std bold'),
                         fulltitle= item.fulltitle,
                         show= item.show,
                         url=item.url,
                         args=item.args,
                         page=pag + 1,
                         thumbnail=thumb(),
                         prevthumb=item.prevthumb if item.prevthumb else item.thumbnail))

        if inspect.currentframe().f_back.f_code.co_name not in ['find_episodes']:
            if addVideolibrary and (item.infoLabels["title"] or item.fulltitle):
                # item.fulltitle = item.infoLabels["title"]
                videolibrary(itemlist, item, function=function)
            if downloadEnabled and function == 'episodios' or function == 'findvideos':
                download(itemlist, item, function=function)

        if 'patronMenu' in args and itemlist:
            itemlist = thumb(itemlist, genre=True)

        if 'fullItemlistHook' in args:
            try:
                itemlist = args['fullItemlistHook'](itemlist)
            except:
                raise logger.ChannelScraperException

        # itemlist = filterLang(item, itemlist)   # causa problemi a newest

        check_trakt(itemlist)
        return itemlist

    return wrapper


def dooplay_get_links(item, host, paramList=[]):
    # get links from websites using dooplay theme and dooplay_player
    # return a list of dict containing these values: url, title and server
    if not paramList:
        data = httptools.downloadpage(item.url).data.replace("'", '"')
        patron = r'<li id="player-option-[0-9]".*?data-type="([^"]+)" data-post="([^"]+)" data-nume="([^"]+)".*?<span class="title".*?>([^<>]+)</span>(?:<span class="server">([^<>]+))?'
        matches = scrapertools.find_multiple_matches(data, patron)
    else:
        matches = paramList
    ret = []

    for type, post, nume, title, server in matches:
        postData = urlencode({
            "action": "doo_player_ajax",
            "post": post, 
            "nume": nume,
            "type": type
        })
        dataAdmin = httptools.downloadpage(host + '/wp-admin/admin-ajax.php', post=postData,headers={'Referer': item.url}).data
        link = scrapertools.find_single_match(dataAdmin, r"<iframe.*src='([^']+)'")
        if not link: link = scrapertools.find_single_match(dataAdmin, r'"embed_url":"([^"]+)"').replace('\\','')
        ret.append({
            'url': link,
            'title': title,
            'server': server
        })

    return ret


@scrape
def dooplay_get_episodes(item):
    item.contentType = 'tvshow'
    patron = '<li class="mark-[0-9]+">.*?<img.*?(?:data-lazy-)?src="(?P<thumb>[^"]+).*?(?P<episode>[0-9]+ - [0-9]+).*?<a href="(?P<url>[^"]+)">(?P<title>[^<>]+).*?(?P<year>[0-9]{4})'
    actLike = 'episodios'

    return locals()


@scrape
def dooplay_peliculas(item, mixed=False, blacklist=""):
    actLike = 'peliculas'
    # debug = True
    if item.args == 'searchPage':
        return dooplay_search_vars(item, blacklist)
    else:
        if item.contentType == 'movie':
            action = 'findvideos'
            patron = '<article id="post-[0-9]+" class="item movies">.*?<img src="(?!data)(?P<thumb>[^"]+)".*?(?:<span class="quality">(?P<quality>[^<>]+).*?)?<a href="(?P<url>[^"]+)">(?P<title>[^<>]+)</a></h3>.*?(?:<span>[^<>]*(?P<year>[0-9]{4})</span>|</article>)'
        else:
            action = 'episodios'
            patron = '<article id="post-[0-9]+" class="item (?P<type>' + ('\w+' if mixed else 'tvshows') + ')">.*?<img src="(?!data)(?P<thumb>[^"]+)".*?(?:<span class="quality">(?P<quality>[^<>]+))?.*?<a href="(?P<url>[^"]+)">(?P<title>[^<>]+)</a></h3>.*?(?:<span>(?P<year>[0-9]{4})</span>|</article>).*?(?:<div class="texto">(?P<plot>[^<>]+)|</article>).*?(?:genres">(?P<genre>.*?)</div>|</article>)'
        patronNext = '<div class="pagination">.*?class="current".*?<a href="([^"]+)".*?<div class="resppages">'
        addVideolibrary = False

        if mixed:
            typeActionDict={'findvideos': ['movies'], 'episodios': ['tvshows']}
            typeContentDict={'film': ['movies'], 'serie': ['tvshows']}

        return locals()


@scrape
def dooplay_search(item, blacklist=""):
    return dooplay_search_vars(item, blacklist)


def dooplay_search_vars(item, blacklist):
    actLike = 'peliculas'
    if item.contentType == 'undefined':  # ricerca globale
        type = '(?P<type>movies|tvshows)'
        typeActionDict = {'findvideos': ['movies'], 'episodios': ['tvshows']}
        typeContentDict = {'movie': ['movies'], 'tvshow': ['tvshows']}
    elif item.contentType == 'movie':
        type = 'movies'
        action = 'findvideos'
    else:
        type = 'tvshows'
        action = 'episodios'
    patron = '<div class="result-item">.*?<img src="(?P<thumb>[^"]+)".*?<span class="' + type + '">(?P<quality>[^<>]+).*?<a href="(?P<url>[^"]+)">(?P<title>[^<>]+)</a>.*?<span class="year">(?P<year>[0-9]{4}).*?<div class="contenido"><p>(?P<plot>[^<>]+)'
    patronNext = '<a class="arrow_pag" href="([^"]+)"><i id="nextpagination"'

    return locals()


def dooplay_menu(item, type):
    patronMenu = '<a href="(?P<url>[^"#]+)"(?: title="[^"]+")?>(?P<title>[a-zA-Z0-9]+)'
    patronBlock = '<nav class="' + item.args + '">(?P<block>.*?)</nav>'
    action = 'peliculas'

    return locals()


def menuItem(itemlist, filename, title='', action='', url='', contentType='undefined', args=[], style=True, folder=True):
    # Function to simplify menu creation

    # Call typo function
    if style:
        title = typo(title)

    if contentType == 'movie': extra = 'movie'
    else: extra = 'tvshow'

    itemlist.append(Item(
        channel = filename,
        title = title,
        action = action,
        url = url,
        extra = extra,
        args = args,
        contentType = contentType,
        globalsearch = not style,
        folder = folder
    ))


def menu(func):
    """https://github.com/stream4me/addon/wiki/decoratori#menu"""

    def wrapper(*args):
        args = func(*args)

        item = args['item']
        logger.debug(item.channel + ' menu start')
        host = func.__globals__['host']
        menuHost = args.get('host','')
        if menuHost: host = menuHost
        filename = func.__module__.split('.')[1]
        single_search = False
        # listUrls = ['film', 'filmSub', 'tvshow', 'tvshowSub', 'anime', 'animeSub', 'search', 'top', 'topSub']
        listUrls = ['top', 'film', 'tvshow', 'anime', 'search', 'host']
        listUrls_extra = []
        dictUrl = {}

        global_search = item.global_search

        # Main options
        itemlist = []

        for name in listUrls:
            dictUrl[name] = args.get(name, None)
            logger.debug(dictUrl[name])
            if name == 'film': title = 'Film'
            if name == 'tvshow': title = 'Serie TV'
            if name == 'anime': title = 'Anime'

            if name == 'search' and dictUrl[name] is not None:
                single_search = True

            # Make TOP MENU
            elif name == 'top' and dictUrl[name] is not None:
                if not global_search:
                    for sub, var in dictUrl['top']:
                        menuItem(itemlist, filename,
                                 title = sub + '{italic bold}',
                                 url = host + var[0] if len(var) > 0 else '',
                                 action = var[1] if len(var) > 1 else 'peliculas',
                                 args=var[2] if len(var) > 2 else '',
                                 contentType= var[3] if len(var) > 3 else 'movie',
                                 folder = var[4] if len(var) > 4 else True)

            # Make MAIN MENU
            elif dictUrl[name] is not None:
                if len(dictUrl[name]) == 0:
                    url = ''
                else:
                    url = dictUrl[name][0] if type(dictUrl[name][0]) is not tuple and len(dictUrl[name][0]) > 0 else ''

                if not global_search:
                    menuItem(itemlist, filename,
                             title + '{bullet bold}', 'peliculas',
                             host + url,
                             contentType='movie' if name == 'film' else 'tvshow')
                    if len(dictUrl[name]) > 0:
                        if type(dictUrl[name][0]) is not tuple and type(dictUrl[name]) is not str: dictUrl[name].pop(0)
                    if dictUrl[name] is not None and type(dictUrl[name]) is not str:
                        for sub, var in dictUrl[name]:
                            menuItem(itemlist, filename,
                                 title = sub + '{submenu}  {' + title + '}',
                                 url = host + var[0] if len(var) > 0 else '',
                                 action = var[1] if len(var) > 1 else 'peliculas',
                                 args=var[2] if len(var) > 2 else '',
                                 contentType= var[3] if len(var) > 3 else 'movie' if name == 'film' else 'tvshow',
                                 folder = var[4] if len(var) > 4 else True)
                # add search menu for category
                if 'search' not in args: menuItem(itemlist, filename, config.get_localized_string(70741) % title + '… {submenu bold}', 'search', host + url, contentType='movie' if name == 'film' else 'tvshow', style=not global_search)

        # Make EXTRA MENU (on bottom)
        for name, var in args.items():
            if name not in listUrls and name != 'item':
               listUrls_extra.append(name)
        for name in listUrls_extra:
            dictUrl[name] = args.get(name, None)
            for sub, var in dictUrl[name]:
                menuItem(itemlist, filename,
                             title = sub + ' ',
                             url = host + var[0] if len(var) > 0 else '',
                             action = var[1] if len(var) > 1 else 'peliculas',
                             args=var[2] if len(var) > 2 else '',
                             contentType= var[3] if len(var) > 3 else 'movie',
                             folder = var[4] if len(var) > 4 else True)

        if single_search:
            menuItem(itemlist, filename, config.get_localized_string(70741) % '… {bold}', 'search', host + dictUrl['search'], style=not global_search)

        if not global_search:
            # autoplay.init(item.channel, list_servers, list_quality)
            # autoplay.show_option(item.channel, itemlist)
            channel_config(item, itemlist)

            # Apply auto Thumbnails at the menus
            thumb(itemlist)
        logger.debug(item.channel + ' menu end')
        return itemlist

    return wrapper


def typo(string, typography=''):

    std_color = '0xFF65B3DA' #'0xFF0081C2'

    try: string = str(string)
    except: string = str(string.encode('utf8'))

    if config.get_localized_string(30992) in string:
        string = string + ' >'

    if int(config.get_setting('view_mode_channel').split(',')[-1]) in [0, 50, 55]:
       VLT = True
    else:
        VLT = False


    if not typography and '{' in string:
        typography = string.split('{')[1].strip(' }').lower()
        string = string.replace('{' + typography + '}','').strip()
    else:
        string = string
        typography.lower()

    if 'capitalize' in typography:
        string = string.capitalize()
        typography = typography.replace('capitalize', '')
    if 'uppercase' in typography:
        string = string.upper()
        typography = typography.replace('uppercase', '')
    if 'lowercase' in typography:
        string = string.lower()
        typography = typography.replace('lowercase', '')
    if '[]' in typography:
        string = '[' + string + ']'
        typography = typography.replace('[]', '')
    if '()' in typography:
        string = '(' + string + ')'
        typography = typography.replace('()', '')
    if 'submenu' in typography:
        if VLT: string = "•• " + string
        else: string = string
        typography = typography.replace('submenu', '')
    if 'color std' in typography:
        string = '[COLOR ' + std_color + ']' + string + '[/COLOR]'
        typography = typography.replace('color std', '')
    elif 'color' in typography:
        color = scrapertools.find_single_match(typography, 'color ([a-zA-Z0-9]+)')
        string = '[COLOR ' + color + ']' + string + '[/COLOR]'
        typography = typography.replace('color ' + color, '')
    if 'bold' in typography:
        string = '[B]' + string + '[/B]'
        typography = typography.replace('bold', '')
    if 'italic' in typography:
        string = '[I]' + string + '[/I]'
        typography = typography.replace('italic', '')
    if '_' in typography:
        string = ' ' + string
        typography = typography.replace('_', '')
    if '--' in typography:
        string = ' - ' + string
        typography = typography.replace('--', '')
    if 'bullet' in typography:
        if VLT: string = '[B]' + "•" + '[/B] ' + string
        else: string = string
        typography = typography.replace('bullet', '')
    typography = typography.strip()
    if typography: string = string + '{' + typography + '}'
    return string


def match(item_url_string, **args):
    '''
    match is a function that combines httptools and scraper tools:

    supports all httptools and the following arggs:
        @param item_url_string: if it's a titem download the page item.url, if it's a URL download the page, if it's a string pass it to scrapertools
        @type  item_url_string: item or str
        @param string: force item_url_string to be a string
        @type  string: bool
        @param patronBlock: find first element in patron
        @type  patronBlock: str
        @param patronBloks: find multiple matches
        @type  patronBloks: str or list
        @param debugBlock: regex101.com for debug
        @type  debugBlock: bool
        @param patron: find multiple matches on block, blocks or data
        @type  patron: str or list
        @param debug: regex101.com for debug
        @type  debug: bool

    Return a item with the following key:
        data: data of the webpage
        block: first block
        blocks: all the blocks
        match: first match
        matches: all the matches
    '''

    matches = []
    blocks = []
    url = None
    # arguments allowed for scrape
    patron = args.get('patron', None)
    patronBlock = args.get('patronBlock', None)
    patronBlocks = args.get('patronBlocks', None)
    debug = args.get('debug', False)
    debugBlock = args.get('debugBlock', False)
    string = args.get('string', False)

    # remove scrape arguments
    args = dict([(key, val) for key, val in args.items() if key not in ['patron', 'patronBlock', 'patronBlocks', 'debug', 'debugBlock', 'string']])

    # check type of item_url_string
    if string:
        data = item_url_string
    elif isinstance(item_url_string, Item):
        # if item_url_string is an item use item.url as url
        url = item_url_string.url
    else:
        if item_url_string.startswith('http'): url = item_url_string
        else : data = item_url_string
    # else:
    #     # if item_url_string is an item use item.url as url
    #     url = item_url_string.url

    # if there is a url, download the page
    if url:
        if args.get('ignore_response_code', None) is None:
            args['ignore_response_code'] = True
        data = httptools.downloadpage(url, **args).data

    # format page data
    data = html_uniform(data)

    # collect blocks of a page
    if patronBlock:
        blocks = [scrapertools.find_single_match(data, patronBlock)]
    elif patronBlocks:
        if type(patronBlocks) == str: 
            patronBlocks = [patronBlocks]
        for p in patronBlocks:
            blocks += scrapertools.find_multiple_matches(data, p)
    else:
        blocks = [data]

    # match
    if patron:
        if type(patron) == str:  patron = [patron]
        for b in blocks:
            for p in patron:
                matches += scrapertools.find_multiple_matches(b, p)

    # debug mode
    if config.dev_mode():
        if debugBlock:
            match_dbg(data, patronBlock)
        if debug:
            for block in blocks:
                for p in patron:
                    match_dbg(block, p)

    # create a item
    item = Item(data=data,
                blocks=blocks,
                block=blocks[0] if len(blocks) > 0 else '',
                matches=matches,
                match=matches[0] if len(matches) > 0 else '')

    return item


def match_dbg(data, patron):
    import json, webbrowser
    url = 'https://regex101.com'
    headers = {'content-type': 'application/json'}
    data = {
        'regex': patron,
        'flags': 'gm',
        'testString': data,
        'delimiter': '"""',
        'flavor': 'python'
    }
    js = json.dumps(data).encode() if PY3 else json.dumps(data, encoding='latin1')
    r = Request(url + '/api/regex', js, headers=headers)
    r = urlopen(r).read()
    permaLink = json.loads(r)['permalinkFragment']
    webbrowser.open(url + "/r/" + permaLink)


def download(itemlist, item, typography='', function_level=1, function=''):
    if config.get_setting('downloadenabled'):

        if not typography: typography = 'color std bold'

        if item.contentType == 'movie':
            from_action = 'findvideos'
            title = typo(config.get_localized_string(60354), typography)
        elif item.contentType == 'episode':
            from_action = 'findvideos'
            title = typo(config.get_localized_string(60356), typography) + ' - ' + item.title
        elif item.contentType in 'tvshow':
            if item.channel == 'community' and config.get_setting('show_seasons', item.channel):
                from_action = 'season'
            else:
                from_action = 'episodios'
            title = typo(config.get_localized_string(60355), typography)
        elif item.contentType in 'season':
            from_action = 'get_seasons'
        else:  # content type does not support download
            return itemlist

        # function = function if function else inspect.stack()[function_level][3]

        contentSerieName=item.contentSerieName if item.contentSerieName else ''
        contentTitle=item.contentTitle if item.contentTitle else ''
        downloadItemlist = [i.tourl() for i in itemlist]

        if itemlist and item.contentChannel != 'videolibrary':
            show = True
            # do not show if we are on findvideos and there are no valid servers
            if from_action == 'findvideos':
                for i in itemlist:
                    if i.action == 'play':
                        break
                else:
                    show = False
            if show and item.contentType != 'season':
                itemlist.append(
                    Item(channel='downloads',
                         from_channel=item.channel,
                         title=title,
                         fulltitle=item.fulltitle,
                         show=item.fulltitle,
                         contentType=item.contentType,
                         contentSerieName=contentSerieName,
                         url=item.url,
                         action='save_download',
                         from_action=from_action,
                         contentTitle=contentTitle,
                         path=item.path,
                         thumbnail=thumb('downloads'),
                         downloadItemlist=downloadItemlist
                    ))
            if from_action == 'episodios':
                itemlist.append(
                    Item(channel='downloads',
                         from_channel=item.channel,
                         title=typo(config.get_localized_string(60357),typography),
                         fulltitle=item.fulltitle,
                         show=item.fulltitle,
                         contentType=item.contentType,
                         contentSerieName=contentSerieName,
                         url=item.url,
                         action='save_download',
                         from_action=from_action,
                         contentTitle=contentTitle,
                         download='season',
                         thumbnail=thumb('downloads'),
                         downloadItemlist=downloadItemlist
                ))

        return itemlist


def videolibrary(itemlist, item, typography='', function_level=1, function=''):
    # Simply add this function to add video library support
    # Function_level is useful if the function is called by another function.
    # If the call is direct, leave it blank
    logger.debug()

    if item.contentType == 'movie':
        action = 'add_pelicula_to_library'
        extra = 'findvideos'
        contentType = 'movie'
    else:
        action = 'add_serie_to_library'
        extra = 'episodios'
        contentType = 'tvshow'

    function = function if function else inspect.stack(0)[function_level][3]
    # go up until find findvideos/episodios
    while function not in ['findvideos', 'episodios']:
        function_level += 1
        try:
            function = inspect.stack(0)[function_level][3]
        except:
            break

    if not typography: typography = 'color std bold'

    title = typo(config.get_localized_string(30161), typography)
    contentSerieName=item.contentSerieName if item.contentSerieName else item.fulltitle if item.contentType != 'movie' else ''
    contentTitle=item.contentTitle if item.contentTitle else item.fulltitle if item.contentType == 'movie' else ''

    if (function == 'findvideos' and contentType == 'movie') \
        or (function == 'episodios' and contentType != 'movie'):
        if config.get_videolibrary_support() and len(itemlist) > 0:
            itemlist.append(
                item.clone(channel=item.channel,
                     title=title,
                     fulltitle=item.fulltitle,
                     show=item.fulltitle,
                     contentType=contentType,
                     contentTitle=contentTitle,
                     contentSerieName=contentSerieName,
                     url=item.url,
                     action=action,
                     from_action=item.action,
                     extra=extra,
                     path=item.path,
                     thumbnail=thumb('add_to_videolibrary')
                    ))

    return itemlist


def nextPage(itemlist, item, data='', patron='', function_or_level=1, next_page='', resub=[]):
    # Function_level is useful if the function is called by another function.
    # If the call is direct, leave it blank
    logger.debug()
    action = inspect.stack(0)[function_or_level][3] if type(function_or_level) == int else function_or_level

    if not data and not patron and not next_page:
        itemlist.append(
            item.clone(action = action,
                       title=typo(config.get_localized_string(30992), 'color std bold'),
                       nextPage=True,
                       thumbnail=thumb()))
        return itemlist[-1]

    if next_page == '':
        next_page = scrapertools.find_single_match(data, patron)

    if next_page != "":
        if resub: next_page = re.sub(resub[0], resub[1], next_page)
        if 'http' not in next_page:
            if '/' in next_page:
                next_page = scrapertools.find_single_match(item.url, 'https?://[a-z0-9.-]+') + (next_page if next_page.startswith('/') else '/' + next_page)
            else:
                next_page = '/'.join(item.url.split('/')[:-1]) + '/' + next_page
        next_page = next_page.replace('&amp;', '&')
        logger.debug('NEXT= ', next_page)
        itemlist.append(
            item.clone(action = action,
                       title=typo(config.get_localized_string(30992), 'color std bold'),
                       url=next_page,
                       nextPage=True,
                       thumbnail=thumb()))
        return itemlist[-1]


def pagination(itemlist, item, page, perpage, function_level=1):
    if len(itemlist) >= page * perpage:
        itemlist.append(
            Item(channel=item.channel,
                 action=inspect.stack(0)[function_level][3],
                 contentType=item.contentType,
                 title=typo(config.get_localized_string(30992), 'color std bold'),
                 url=item.url,
                 args=item.args,
                 page=page + 1,
                 thumbnail=thumb()))
    return itemlist


def server(item, data='', itemlist=[], headers='', CheckLinks=True, Download=True, patronTag=None, Videolibrary=True, Sorted=True, referer=True):
    logger.debug()

    if not data and not itemlist:
        data = httptools.downloadpage(item.url, headers=headers, ignore_response_code=True).data
    if data:
        itemList = servertools.find_video_items(data=str(data))
        itemlist = itemlist + itemList
    verifiedItemlist = []

    def getItem(n, videoitem):
        # if not videoitem.server:
        #     s = servertools.get_server_from_url(videoitem.url)
        #     videoitem.server = s[2] if s else 'directo'
        #     videoitem.title = s[0] if s else config.get_localized_string(30137)
        if not videoitem.video_urls:
            srv_param = servertools.get_server_parameters(videoitem.server.lower())
            if not srv_param:  # do not exists or it's empty
                findS = servertools.get_server_from_url(videoitem.url)
                info(findS)
                if not findS:
                    if item.channel == 'community':
                        findS= (config.get_localized_string(30137), videoitem.url, 'directo')
                    else:
                        videoitem.url = unshortenit.unshorten_only(videoitem.url)[0]
                        findS = servertools.get_server_from_url(videoitem.url)
                        if not findS:
                            info(videoitem, 'Non supportato')
                            if logger.testMode:
                                raise Exception('Server missing: ' + videoitem.url)
                            return
                videoitem.server = findS[2]
                videoitem.title = findS[0]
                videoitem.url = findS[1]
                srv_param = servertools.get_server_parameters(videoitem.server.lower())
            else:
                videoitem.server = videoitem.server.lower()

        if videoitem.video_urls or srv_param.get('active', False):
            vi = item.clone(server=videoitem.server,
                            extraInfo=videoitem.extraInfo,
                            serverName=videoitem.serverName,
                            subtitle=videoitem.subtitle,
                            url=videoitem.url,
                            videoUrls= videoitem.videoUrlsn,
                            drm=videoitem.drm,
                            license=videoitem.license,
                            ch_name=channeltools.get_channel_parameters(item.channel)['title'],
                            action = "play")

            if videoitem.title: vi.serverName = videoitem.title
            if videoitem.quality: vi.quality = videoitem.quality
            if referer == False: vi.referer = False
            elif referer and not vi.referer: vi.referer = item.url
            vi.contentFanart = item.infoLabels['fanart']
            vi.contentThumb = item.infoLabels['fanart']
            if videoitem.forcethumb:
                vi.thumbnail = videoitem.thumbnail
                vi.forcethumb = True
            videoitem = vi
            videoitem.position = n
            return videoitem

    # non threaded for webpdb
    # dbg()
    # thL = [getItem(videoitem) for videoitem in itemlist if videoitem.url or videoitem.video_urls]
    # for it in thL:
    #     if it and not config.get_setting("black_list", server=it.server.lower()):
    #         verifiedItemlist.append(it)

    with futures.ThreadPoolExecutor() as executor:
        thL = [executor.submit(getItem, n, videoitem) for n,videoitem in enumerate(itemlist) if videoitem.url or videoitem.video_urls]
        for it in futures.as_completed(thL):
            if it.result() and not config.get_setting("black_list", server=it.result().server.lower()):
                verifiedItemlist.append(it.result())

    if not Sorted:
        verifiedItemlist.sort(key=lambda it: it.position)
    # if Sorted:
    #     try:
    #         verifiedItemlist.sort(key=lambda it: int(re.sub(r'\D','',it.quality)))
    #     except:
    #         verifiedItemlist.sort(key=lambda it: it.quality, reverse=True)
    if patronTag:
        addQualityTag(item, verifiedItemlist, data, patronTag)

    # Check Links
    if not item.global_search and config.get_setting('checklinks') and CheckLinks: # and not config.get_setting('autoplay'):
        checklinks_number = config.get_setting('checklinks_number')
        verifiedItemlist = servertools.check_list_links(verifiedItemlist, checklinks_number)

    if Sorted:
        verifiedItemlist = servertools.sort_servers(verifiedItemlist)

    if Videolibrary and item.contentChannel != 'videolibrary':
        videolibrary(verifiedItemlist, item)
    if Download:
        download(verifiedItemlist, item, function_level=3)
    # if item.contentChannel == 'videolibrary' or not config.get_setting('autoplay'):
    return verifiedItemlist


def filterLang(item, itemlist):
    # import channeltools
    list_language = channeltools.get_lang(item.channel)
    if len(list_language) > 1:
        from core import filtertools
        itemlist = filtertools.get_links(itemlist, item, list_language)
    return itemlist


def channel_config(item, itemlist):
    itemlist.append(
        Item(channel='setting',
             action="channel_config",
             title=typo(config.get_localized_string(60587), 'color std bold'),
             config=item.channel,
             folder=False,
             thumbnail=thumb('setting_0'))
    )


def extract_wrapped(decorated):
    from types import FunctionType
    closure = (c.cell_contents for c in decorated.__closure__)
    return next((c for c in closure if isinstance(c, FunctionType)), None)


def addQualityTag(item, itemlist, data, patron):
    if itemlist:
        defQualVideo = {
            "CAM": "metodo di ripresa che indica video di bassa qualità",
            "TS": "questo metodo di ripresa effettua la ripresa su un tre piedi. Qualità sufficiente.",
            "TC": "abbreviazione di TeleCine. Il metodo di ripresa del film è basato su una macchina capace di riversare le Super-8, o 35mm. La qualità è superiore a quella offerta da CAM e TS.",
            "R5": "la qualità video di un R5 è pari a quella di un dvd, può contenere anche sottotitoli. Se è presente la dicitura LINE.ITALIAN è in italiano, altrimenti sarà disponibile in una lingua asiatica o russa.",
            "R6": "video proveniente dall’Asia.",
            "FS": "video a schermo pieno, cioè FullScreen, quindi con un rapporto di 4:3.",
            "WS": "video WideScreen, cioè rapporto 16:9.",
            "VHSSCR": "video estratto da una videocassetta VHS.",
            "DVDRIP": "la fonte video proviene da un DVD, la qualità è buona.",
            "DVDSCR": "la fonte video proviene da un DVD. Tali filmati, di solito, appartengono a copie promozionali.",
            "HDTVRIP": "video copiato e registrato da televisori in HD e che, per questo, restituiscono una qualità eccellente.",
            "PD": "video registrato da Tv satellitare, qualità accettabile.",
            "TV": "video registrato da Tv satellitare, qualità accettabile.",
            "SAT": "video registrato da Tv satellitare, qualità accettabile.",
            "DVBRIP": "video registrato da Tv satellitare, qualità accettabile.",
            "TVRIP": "ripping simile al SAT RIP, solo che, in questo caso, la qualità del vide può variare a seconda dei casi.",
            "VHSRIP": "video registrato da videocassetta. Qualità variabile.",
            "BRRIP": "indica che il video è stato preso da una fonte BluRay. Nella maggior parte dei casi, avremo un video ad alta definizione.",
            "BDRIP": "indica che il video è stato preso da una fonte BluRay. Nella maggior parte dei casi, avremo un video ad alta definizione.",
            "DTTRIP": "video registrato da un canale digitale terreste. Qualità sufficiente.",
            "HQ": "video in alta qualità.",
            "WEBRIP": "in questo caso, i film sono estratti da portali relativi a canali televisivi o di video sharing come YouTube. La qualità varia dall’SD al 1080p.",
            "WEB-DL": "si tratta di un 720p o 1080p reperiti dalla versione americana di iTunes americano. La qualità è paragonabile a quella di un BluRayRip e permette di fruire di episodi televisivi, senza il fastidioso bollo distintivo della rete che trasmette.",
            "WEBDL": "si tratta di un 720p o 1080p reperiti dalla versione americana di iTunes americano. La qualità è paragonabile a quella di un BluRayRip e permette di fruire di episodi televisivi, senza il fastidioso bollo distintivo della rete che trasmette.",
            "DLMux": "si tratta di un 720p o 1080p reperiti dalla versione americana di iTunes americano. La qualità è paragonabile a quella di un BluRayRip e permette di fruire di episodi televisivi, senza il fastidioso bollo distintivo della rete che trasmette.",
            "DVD5": "il film è in formato DVD Single Layer, nel quale vengono mantenute tutte le caratteristiche del DVD originale: tra queste il menu multilingue, i sottotitoli e i contenuti speciali, se presenti. Il video è codificato nel formato DVD originale MPEG-2.",
            "DVD9": "ha le stesse caratteristiche del DVD5, ma le dimensioni del file sono di un DVD Dual Layer (8,5 GB).",
            "HDTS": "viene utilizzata una videocamera professionale ad alta definizione posizionata in modo fisso. La qualità audio video è buona.",
            "DVDMUX": "indica una buona qualità video, l’audio è stato aggiunto da una sorgente diversa per una migliore qualità.",
        }

        defQualAudio = {
            "MD": "l’audio è stato registrato via microfono, quindi la qualità è scarsa.",
            "DTS": "audio ricavato dai dischi DTS2, quindi la qualità audio è elevata.",
            "LD": "l’audio è stato registrato tramite jack collegato alla macchina da presa, pertanto di discreta qualità.",
            "DD": "audio ricavato dai dischi DTS cinema. L’audio è di buona qualità, ma potreste riscontrare il fatto che non potrebbe essere più riproducibile.",
            "AC3": "audio in Dolby Digital può variare da 2.0 a 5.1 canali in alta qualità.",
            "MP3": "codec per compressione audio utilizzato MP3.",
            "RESYNC": "il film è stato lavorato e re sincronizzato con una traccia audio. A volte potresti riscontrare una mancata sincronizzazione tra audio e video.",
        }
        qualityStr = scrapertools.find_single_match(data, patron).strip().upper()
        # if PY3: qualityStr = qualityStr.encode('ascii', 'ignore')
        if not PY3: qualityStr = qualityStr.decode('unicode_escape').encode('ascii', 'ignore')

        if qualityStr:
            try:
                video, audio, descr = None, None, ''
                for tag in defQualVideo:
                    if tag in qualityStr:
                        video = tag
                        break
                for tag in defQualAudio:
                    if tag in qualityStr:
                        audio = tag
                        break
                if video:
                    descr += typo(video + ': ', 'color std') + defQualVideo.get(video, '') + '\n'
                if audio:
                    descr += typo(audio + ': ', 'color std') + defQualAudio.get(audio, '') + '\n'
            except:
                descr = ''
            itemlist.insert(0,Item(channel=item.channel,
                                   action="",
                                   title=typo(qualityStr, 'bold'),
                                   fulltitle=qualityStr,
                                   plot=descr,
                                   folder=False,
                                   thumbnail=thumb('info')))
        else:
            info('nessun tag qualità trovato')

def get_jwplayer_mediaurl(data, srvName, onlyHttp=False, dataIsBlock=False, hls=False):
    from core import jsontools
    video_urls = []
    block = scrapertools.find_single_match(data, r'sources"?\s*:\s*(.*?}?])') if not dataIsBlock else data
    if block:
        json = jsontools.load(block)
        if json:
            sources = []
            for s in json:
                if isinstance(s, str):
                    sources.append((s, ''))
                else:
                    if 'file' in s.keys():
                        src = s['file']
                    else:
                        src = s['src']
                    sources.append((src, s.get('label')))
        else:
            if 'file:' in block:
                sources = scrapertools.find_multiple_matches(block, r'file:\s*"([^"]+)"(?:,label:\s*"([^"]+)")?')
            elif 'src:' in block:
                sources = scrapertools.find_multiple_matches(block, r'src:\s*"([^"]+)",\s*type:\s*"[^"]+"(?:,[^,]+,\s*label:\s*"([^"]+)")?')
            else:
                sources =[(block.replace('"',''), '')]
        for url, quality in sources:
            quality = 'auto' if not quality else quality
            if url.split('.')[-1] != 'mpd':
                _type = url.split('?')[0].split('.')[-1]
                if _type == 'm3u8' and hls:
                    _type = 'hls'
                video_urls.append([_type + ' [' + quality + '] [' + srvName + ']', url.replace(' ', '%20') if not onlyHttp else url.replace('https://', 'http://')])

        video_urls.sort(key=lambda x: x[0].split()[1])
    return video_urls


def thumb(item_itemlist_string=None, genre=False, live=False):
    from channelselector import get_thumb

    if live:
        def liveThumb(item):
            thumb = 'https://raw.githubusercontent.com/Stream4me/media/master/live/{}.png'.format(item.fulltitle.lower().replace(' ','_'))
            if filetools.exists(thumb):
                item.thumbnail = thumb
        if type(item_itemlist_string) == list:
            with futures.ThreadPoolExecutor() as executor: [executor.submit(liveThumb, it) for it in item_itemlist_string]
        else:
            item_itemlist_string.thumbnail = liveThumb(item_itemlist_string)
        return item_itemlist_string

    icon_dict = {'movie':['film', 'movie', 'saghe'],
                 'tvshow':['serie','tv','episodi','episodio','fiction', 'show', 'talent', 'reality'],
                 'documentary':['documentari','documentario', 'documentary', 'documentaristico'],
                 'teenager':['ragazzi','teenager', 'giovani', 'teen'],
                 'learning':['learning', 'school', 'scuola'],
                 'all':['tutti', 'all'],
                 'news':['novità', "novita'", 'aggiornamenti', 'nuovi', 'nuove', 'new', 'newest', 'news', 'ultimi', 'notizie'],
                 'now_playing':['cinema', 'in sala'],
                 'anime':['anime'],
                 'genres':['genere', 'generi', 'categorie', 'categoria', 'category'],
                 'animation': ['animazione', 'cartoni', 'cartoon', 'animation'],
                 'action':['azione', 'marziali', 'action', 'martial'],
                 'adventure': ['avventura', 'adventure'],
                 'biographical':['biografico', 'biographical', 'biografia'],
                 'comedy':['comico', 'commedia', 'demenziale', 'comedy', 'brillante', 'demential', 'parody'],
                 'adult':['erotico', 'hentai', 'harem', 'ecchi', 'adult'],
                 'drama':['drammatico', 'drama', 'dramma'],
                 'syfy':['fantascienza', 'science fiction', 'syfy', 'sci-fi'],
                 'fantasy':['fantasy', 'magia', 'magic', 'fantastico'],
                 'crime':['gangster','poliziesco', 'crime', 'crimine', 'police'],
                 'grotesque':['grottesco', 'grotesque'],
                 'war':['guerra', 'war', 'military'],
                 'children':['bambini', 'kids'],
                 'horror':['horror', 'orrore'],
                 'music':['musical', 'musica', 'music', 'musicale'],
                 'mistery':['mistero', 'giallo', 'mystery'],
                 'noir':['noir'],
                 'popular':['popolari','popolare', 'più visti', 'raccomandati', 'raccomandazioni' 'recommendations'],
                 'thriller':['thriller'],
                 'top_rated' : ['fortunato', 'votati', 'primo', 'lucky', 'top'],
                 'on_the_air' : ['corso', 'onda', 'diretta', 'dirette'],
                 'western':['western'],
                 'vos':['sub','sub-ita'],
                 'romance':['romantico', 'romantici', 'sentimentale', 'romance', 'soap'],
                 'family':['famiglia','famiglie', 'family'],
                 'historical':['storico', 'history', 'storia', 'historical'],
                 'az':['lettera','lista','alfabetico','a-z', 'alphabetical'],
                 'year':['anno', 'anni', 'year'],
                 'update':['replay', 'update'],
                 'videolibrary':['teche', 'archivio'],
                 'info':['info','information','informazioni'],
                 'star':['star', 'personaggi', 'interpreti', 'stars', 'characters', 'performers', 'staff', 'actors', 'attori'],
                 'winter':['inverno', 'winter'],
                 'spring':['primavera', 'spring'],
                 'summer':['estate', 'summer'],
                 'autumn':['autunno', 'autumn'],
                 'autoplay':[config.get_localized_string(60071)]
                }

    suffix_dict = {'_hd':['hd','altadefinizione','alta definizione'],
                   '_4k':['4K'],
                   '_az':['lettera','lista','alfabetico','a-z', 'alphabetical'],
                   '_year':['anno', 'anni', 'year'],
                   '_genre':['genere', 'generi', 'categorie', 'categoria']}

    search = ['cerca', 'search']

    search_suffix ={'_movie':['film', 'movie'],
                    '_tvshow':['serie','tv', 'fiction']}

    def autoselect_thumb(item, genre):
        searched = re.split(r'\:|\.|\{|\}|\[|\]|\(|\)|/| ', item.title.lower())
        # logger.debug('SPLIT',searched)
        if genre == False:
            for thumb, titles in icon_dict.items():
                if any(word in searched for word in search):
                    thumb = 'search'
                    for suffix, titles in search_suffix.items():
                        if any(word in searched for word in titles ):
                            thumb = thumb + suffix
                    item.thumbnail = get_thumb(thumb + '.png')
                elif any(word in searched for word in titles ):
                    if thumb == 'movie' or thumb == 'tvshow':
                        for suffix, titles in suffix_dict.items():
                            if any(word in searched for word in titles ):
                                thumb = thumb + suffix
                        item.thumbnail = get_thumb(thumb + '.png')
                    else: item.thumbnail = get_thumb(thumb + '.png')
                else:
                    thumb = item.thumbnail

        else:
            for thumb, titles in icon_dict.items():
                if any(word in searched for word in titles ):
                    item.thumbnail = get_thumb(thumb + '.png')
                else:
                    thumb = item.thumbnail

        item.title = re.sub(r'\s*\{[^\}]+\}','',item.title)
        return item

    if item_itemlist_string:
        if type(item_itemlist_string) == list:
            for item in item_itemlist_string:
                autoselect_thumb(item, genre)
            return item_itemlist_string

        elif type(item_itemlist_string) == str:
            filename, file_extension = os.path.splitext(item_itemlist_string)
            if not file_extension: item_itemlist_string += '.png'
            return get_thumb(item_itemlist_string)
        else:
            return autoselect_thumb(item_itemlist_string, genre)

    else:
        return get_thumb('next.png')


def vttToSrt(data):
    # Code adapted by VTT_TO_SRT.PY (c) Jansen A. Simanullang
    ret = ''

    data = re.sub(r'(\d\d:\d\d:\d\d).(\d\d\d) --> (\d\d:\d\d:\d\d).(\d\d\d)(?:[ \-\w]+:[\w\%\d:]+)*\n', r'\1,\2 --> \3,\4\n', data)
    data = re.sub(r'(\d\d:\d\d).(\d\d\d) --> (\d\d:\d\d).(\d\d\d)(?:[ \-\w]+:[\w\%\d:]+)*\n', r'00:\1,\2 --> 00:\3,\4\n', data)
    data = re.sub(r'(\d\d).(\d\d\d) --> (\d\d).(\d\d\d)(?:[ \-\w]+:[\w\%\d:]+)*\n', r'00:00:\1,\2 --> 00:00:\3,\4\n', data)
    data = re.sub(r'WEBVTT\n', '', data)
    data = re.sub(r'Kind:[ \-\w]+\n', '', data)
    data = re.sub(r'Language:[ \-\w]+\n', '', data)
    data = re.sub(r'<c[.\w\d]*>', '', data)
    data = re.sub(r'</c>', '', data)
    data = re.sub(r'<\d\d:\d\d:\d\d.\d\d\d>', '', data)
    data = re.sub(r'::[\-\w]+\([\-.\w\d]+\)[ ]*{[.,:;\(\) \-\w\d]+\n }\n', '', data)
    data = re.sub(r'Style:\n##\n', '', data)

    lines = data.split(os.linesep)

    for n, line in enumerate(lines):
        if re.match(r"((\d\d:){2}\d\d),(\d{3}) --> ((\d\d:){2}\d\d),(\d{3})", line):
            ret += str(n + 1) + os.linesep + line + os.linesep
        else:
            ret += line + os.linesep

    return ret

def check_trakt(itemlist):
    if config.get_setting('trakt_sync'):
        from core import trakt_tools
        trakt_tools.trakt_check(itemlist)
    return itemlist


def stackCheck(values):
    logger.debug()
    frame = inspect.currentframe()
    while frame:
        if frame.f_code.co_name in values:
            return True
        frame = frame.f_back
    return False


def callAds(url, host):
    try:
        import requests
        from threading import Thread
        headers = {{'User-Agent': httptools.random_useragent(),
                    'Origin': host,
                    'Referer': host}}
        requests.get(url, headers=headers)
        Thread(target=requests.get, args=(url, headers)).start()
    except:
        pass
