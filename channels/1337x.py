# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per 1337x
# ------------------------------------------------------------

import inspect
from core import support
from platformcode import logger, config

# host = support.config.get_channel_url()
host = 'https://1337x.to'

@support.menu
def mainlist(item):

    menu = [('Film ITA {bullet bold}',['/movie-lib-sort/all/it/popularity/desc/all/1/', 'peliculas', '', 'movie']),
            ('Film {submenu}',['/movie-library/1/', 'peliculas', 'filter', 'movie']),
            ('Serie TV {bullet bold}',['/series-library/', 'az', '', 'tvshow'])]

    search = ''

    return locals()


def moviefilter(item):
    if logger.testMode:
        return host +'/movie-lib-sort/all/all/score/desc/all/1/'
    from platformcode import platformtools

    item.args = ''
    controls = []
    data = support.match(item).data

    patronBlock = r'<select name="{}"[^>]+>(.+?)</select>'
    patron = r'value="([^"]+)">([^<]+)'

    genres = support.match(data, patronBlock=patronBlock.format('genre'), patron=patron).matches
    years = support.match(data, patronBlock=patronBlock.format('year'), patron=patron).matches
    langs = support.match(data, patronBlock=patronBlock.format('lang'), patron=patron).matches
    sorts = support.match(data, patronBlock=patronBlock.format('sortby'), patron=patron).matches
    orders = support.match(data, patronBlock=patronBlock.format('sort'), patron=patron).matches

    item.genreValues = [x[0] for x in genres]
    item.yearValues = [x[0] for x in years]
    item.langValues = [x[0] for x in langs]
    item.sortValues = [x[0] for x in sorts]
    item.orderValues = [x[0] for x in orders]

    genres = [g[1] for g in genres]
    years = [g[1] for g in years]
    langs = [g[1] for g in langs]
    sorts = [g[1] for g in sorts]
    orders = [g[1] for g in orders]

    controls.append({'id': 'lang', 'label': 'Lingua', 'type': 'list', 'enabled':True, 'visible':True, 'lvalues':langs, 'default': 0})
    controls.append({'id': 'genre', 'label': 'Genere', 'type': 'list', 'enabled':True, 'visible':True, 'lvalues':genres, 'default': 0})
    controls.append({'id': 'year', 'label': 'Anno', 'type': 'list', 'enabled':True, 'visible':True, 'lvalues':years, 'default': 0})
    controls.append({'id': 'sort', 'label': 'Anno', 'type': 'list', 'enabled':True, 'visible':True, 'lvalues':sorts, 'default': 0})
    controls.append({'id': 'order', 'label': 'Anno', 'type': 'list', 'enabled':True, 'visible':True, 'lvalues':orders, 'default': 0})
    return platformtools.show_channel_settings(list_controls=controls, item=item, caption='Filtro', callback='filtered')



def filtered(item, values):
    genre = item.genreValues[values['genre']]
    lang = item.langValues[values['lang']]
    sortby = item.sortValues[values['sort']]
    order = item.orderValues[values['order']]
    year = item.yearValues[values['year']]

    return '{}/movie-lib-sort/{}/{}/{}/{}/{}/1/'.format(host, genre, lang, sortby, order, year)


def az(item):
    import string
    itemlist = [item.clone(title='1-9', url=item.url +'num/1/', action='peliculas', thumbnail=support.thumb('az'))]
    for letter in list(string.ascii_lowercase):
        itemlist.append(item.clone(title=letter.upper(), url=item.url + letter +'/1/', action='peliculas', thumbnail=support.thumb('az')))
    return itemlist


def search(item, text):
    support.info('search', text)
    item.args = 'search'
    if config.get_setting('itaSearch', channel=item.channel, default=False):
        text += ' ita'
    text = text.replace(' ', '+')
    item.url = '{}/search/{}/1/'.format(host, text)
    try:
        return peliculas(item)
    # Cattura la eccezione così non interrompe la ricerca globle se il canale si rompe!
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("search except: ", line)
        return []

@support.scrape
def peliculas(item):
    if item.args == 'filter':
        item.url = moviefilter(item)
    if not item.url:
        data = ' '
    else:
        data = support.match(item).data
    # debug = True
    if item.args == 'search':
        sceneTitle = 'undefined'
        patron = r'<a href="(?P<url>[^"]+)">(?P<title>[^<]+)<(?:[^>]+>){3,7}(?P<seed>[^<]+)<(?:[^>]+>){6}(?P<size>[^<]+)<span'
        patronNext = r'"([^"]+)">&gt;&gt;'
    elif item.contentType == 'movie':
        patron = r'<img[^>]+data-original="(?P<thumb>[^"]+)(?:[^>]+>){15}(?P<title>[^<]+).*?<p>(?P<plot>[^<]+).*?<a href="(?P<url>[^"]+)'
        patronNext = r'"([^"]+)">&gt;&gt;'
    else:
        action = 'seasons'
        patron = r'<img src="(?P<thumb>[^"]+)(?:[^>]+>){4}\s*<a href="(?P<url>[^"]+)[^>]+>(?P<title>[^<]+)'

    if (item.args == 'search' or item.contentType != 'movie') and not support.stackCheck(['get_channel_results']):
        patronNext = None
        def itemlistHook(itemlist):
            lastUrl = support.match(data, patron=r'href="([^"]+)">Last').match
            if lastUrl:
                currentPage = support.match(item.url, string=True, patron=r'/(\d+)/').match
                nextPage = int(currentPage) + 1
                support.nextPage(itemlist, item, next_page=item.url.replace('/{}'.format(currentPage), '/{}'.format(nextPage)), function_or_level='peliculas')
            return itemlist

    return locals()


@support.scrape
def seasons(item):
    item.contentType = 'season'
    action = 'episodios'
    patron = r'<li>\s*<a href="(?P<url>[^"]+)[^>]+>\s*<img alt="[^"]*"\ssrc="(?P<thumb>[^"]+)(?:([^>]+)>){2}\s*(?P<title>\w+ (?P<season>\d+))'
    return locals()

@support.scrape
def episodios(item):
    patron = r'<img src="(?P<thumb>[^"]+)(?:[^>]+>){13}\s*(?P<season>\d+)x(?P<episode>\d+)\s*<span class="seperator">(?:[^>]+>){2}\s*<a href="(?P<url>[^"]+)">(?P<title>[^<]+)'
    def itemlistHook(itemlist):
        itemlist.reverse()
        return itemlist
    return locals()


def findvideos(item):
    itemlist = []
    item.disableAutoplay = True
    if item.args == 'search':
        itemlist.append(item.clone(server='torrent', action='play'))
    else:
        from lib.guessit import guessit

        items = support.match(item.url, patron=r'<a href="([^"]+)">([^<]+)<(?:[^>]+>){3}([^<]+)<(?:[^>]+>){6}([^<]+)<span').matches

        for url, title, seed, size in items:
            parsedTitle = guessit(title)

            title = support.scrapertools.unescape(parsedTitle.get('title', ''))

            lang = ''
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
            if lang:
                title = '{} [{}]'.format(title, lang)

            sizematch = support.match(size, patron='(\d+(?:\.\d+)?)\s* (\w+)').match
            sizenumber = float(sizematch[0])
            if sizematch[1].lower() == 'gb':
                sizenumber = sizenumber * 1024

            itemlist.append(item.clone(title = '{} [{} SEEDS] [{}]'.format(title, seed, size), seed=int(seed), size=sizenumber, url=host + url, server='torrent', action='play'))
        itemlist.sort(key=lambda it: (it.seed, it.size), reverse=True)

    Videolibrary = True if 'movie' in item.args else False
    return support.server(item, itemlist=itemlist, Videolibrary=Videolibrary, Sorted=False)


def play(item):
    from core import servertools
    data = support.match(item.url, patron=r'href="(magnet[^"]+)').match
    return servertools.find_video_items(item, data=data)
