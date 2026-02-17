# -*- coding: utf-8 -*-

import datetime
import sys, requests
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

if PY3:
    import urllib.parse as urllib                               # It is very slow in PY2. In PY3 it is native
    from concurrent import futures
else:
    import urllib                                               # We use the native of PY2 which is faster
    from concurrent_py2 import futures

from future.builtins import range
from future.builtins import object

import ast, copy, re, time

from core import filetools, httptools, jsontools, scrapertools
from core.item import InfoLabels
from platformcode import config, logger, platformtools
import threading

info_language = ["de", "en", "es", "fr", "it", "pt"] # from videolibrary.json
def_lang = info_language[config.get_setting("info_language", "videolibrary")]

host = 'https://api.themoviedb.org/3'
api = 'a1ab8b8669da03637a4b98fa39c39228'

""" 
    Set of functions related to infoLabels.
    version 1.0:
    Initial version

    Include:
    - set_infoLabels (source, seekTmdb, search_language): Gets and sets (item.infoLabels) the extra data of one or several series, chapters or movies.
    - set_infoLabels_item (item, seekTmdb, search_language): Gets and sets (item.infoLabels) the extra data of a series, chapter or movie.
    - set_infoLabels_itemlist (item_list, seekTmdb, search_language): Gets and sets (item.infoLabels) the data extras from a list of series, chapters or movies.
    - infoLabels_tostring (item): Returns a str with the list ordered with the item's infoLabels

    Usage:
    - tmdb.set_infoLabels (item, seekTmdb = True)

    Get basic data from a movie:
    Before calling the set_infoLabels method the title to search for must be in item.contentTitle and the year in item.infoLabels ['year'].

    Obtain basic data from a series:
    Before calling the set_infoLabels method the title to search for must be in item.show or in item.contentSerieName.

    Get more data from a movie or series:
    After obtaining the basic data in item.infoLabels ['tmdb'] we will have the code of the series or movie.
    We could also directly set this code, if known, or use the corresponding code of:
    IMDB (in item.infoLabels ['IMDBNumber'] or item.infoLabels ['code'] or item.infoLabels ['imdb_id']), TVDB (only series, in item.infoLabels ['tvdb_id']),
    Freebase (series only, on item.infoLabels ['freebase_mid']), TVRage (series only, on item.infoLabels ['tvrage_id'])

    Get data from a season:
    Before calling the set_infoLabels method the series title must be in item.show or in item.contentSerieName,
    the series TMDB code must be in item.infoLabels ['tmdb'] (it can be set automatically by the basic data query)
    and the season number must be in item.infoLabels ['season'].

    Get data from an episode:
    Before calling the set_infoLabels method the series title must be in item.show or in item.contentSerieName,
    the TMDB code of the series must be in item.infoLabels ['tmdb'] (it can be set automatically using the basic data query),
    the season number must be in item.infoLabels ['season'] and the episode number must be in item.infoLabels ['episode'].
"""
otmdb_global = None
from core import db


def clean_cache():
    db['tmdb_cache'].clear()


# The function name is the name of the decorator and receives the function that decorates.
def cache_response(fn):
    logger.debug()

    # import time
    # start_time = time.time()

    def wrapper(*args, **kwargs):
        def check_expired(saved_date):
            valided = False

            cache_expire = config.get_setting("tmdb_cache_expire", default=0)
            current_date = datetime.datetime.now()
            elapsed = current_date - saved_date

            # 1 day
            if cache_expire == 0:
                if elapsed > datetime.timedelta(days=1):
                    valided = False
                else:
                    valided = True
            # 7 days
            elif cache_expire == 1:
                if elapsed > datetime.timedelta(days=7):
                    valided = False
                else:
                    valided = True

            # 15 days
            elif cache_expire == 2:
                if elapsed > datetime.timedelta(days=15):
                    valided = False
                else:
                    valided = True

            # 1 month - 30 days
            elif cache_expire == 3:
                # we do not take into account February or months with 31 days
                if elapsed > datetime.timedelta(days=30):
                    valided = False
                else:
                    valided = True
            # no expire
            elif cache_expire == 4:
                valided = True

            return valided

        result = {}
        try:

            # cache is not active
            if not config.get_setting("tmdb_cache", default=False) or not kwargs.get('cache', True):
                logger.debug('no cache')
                result = fn(*args)
            else:

                url = args[0].replace('&year=-', '').replace('&primary_release_year=-', '').replace('&first_air_date_year=-', '')
                # if PY3: url = str.encode(url)

                row = db['tmdb_cache'].get(url)

                if row and check_expired(row[1]):
                    result = row[0]

                # si no se ha obtenido información, llamamos a la funcion
                if not result.get('results'):
                    result = fn(*args)
                    db['tmdb_cache'][url] = [result, datetime.datetime.now()]

            # elapsed_time = time.time() - start_time
            # logger.debug("TARDADO %s" % elapsed_time)

        # error getting data
        except Exception as ex:
            message = "An exception of type {} occured. Arguments:\n{}".format(type(ex).__name__, repr(ex.args))
            logger.error("error in:", message)

        return result

    return wrapper


def set_infoLabels(source, seekTmdb=True, search_language=def_lang, forced=False):
    """
    Depending on the data type of source, it obtains and sets (item.infoLabels) the extra data of one or more series, chapters or movies.

    @param source: variable that contains the information to set infoLabels
    @type source: list, item
    @param seekTmdb: if it is True, it searches www.themoviedb.org to obtain the data, otherwise it obtains the data of the Item itself.
    @type seekTmdb: bool
    @param search_language: set the language value in case of search at www.themoviedb.org
    @type search_language: str
    @return: a number or list of numbers with the result of the calls to set_infoLabels_item
    @rtype: int, list
    """

    if not config.get_setting('tmdb_active') and not forced:
        return

    start_time = time.time()
    if type(source) == list:
        ret = set_infoLabels_itemlist(source, seekTmdb, search_language)
        logger.debug("The data of {} links were obtained in {} seconds".format(len(source), time.time() - start_time))
    else:
        ret = set_infoLabels_item(source, seekTmdb, search_language)
        logger.debug("The data were obtained in {} seconds".format(time.time() - start_time))
    return ret


def set_infoLabels_itemlist(itemlist, seekTmdb=False, search_language=def_lang, forced=False):
    """
    Concurrently, it gets the data of the items included in the item_list.

    The API in the past had a limit of 40 requests per IP every 10 '', now there's no limit (https://developers.themoviedb.org/3/getting-started/request-rate-limiting)
    If a limit will be re-added uncomment "tmdb_threads" and related code

    @param item_list: list of Item objects that represent movies, series or chapters. The infoLabels attribute of each Item object will be modified including the extra localized data.
    @type item_list: list
    @param seekTmdb: If it is True, it searches www.themoviedb.org to obtain the data, otherwise it obtains the data of the Item itself if they exist.
    @type seekTmdb: bool
    @param search_language: Language code according to ISO 639-1, in case of search at www.themoviedb.org.
    @type search_language: str

    @return: A list of numbers whose absolute value represents the number of elements included in the infoLabels attribute of each Item. This number will be positive if the data has been obtained from www.themoviedb.org and negative otherwise.
    @rtype: list
    """

    if not config.get_setting('tmdb_active') and not forced:
        return

    r_list = list()

    def sub_thread(_item, _i, _seekTmdb):
        ret = 0
        try:
            ret = set_infoLabels_item(_item, _seekTmdb, search_language)
        except:
            import traceback
            logger.error(traceback.format_exc(1))

        return (_i, _item, ret)
    # from core.support import dbg;dbg()
    # for i, item in enumerate(itemlist):
    #     r_list.append(sub_thread(item, i, seekTmdb))
    with futures.ThreadPoolExecutor() as executor:
        searchList = [executor.submit(sub_thread, item, i, seekTmdb) for i, item in enumerate(itemlist)]
        for res in futures.as_completed(searchList):
            r_list.append(res.result())


    # Sort results list by call order to keep the same order q itemlist
    r_list.sort(key=lambda i: i[0])

    # Rebuild and return list only with results of individual calls
    return [it[2] for it in r_list]


def set_infoLabels_item(item, seekTmdb=True, search_language=def_lang):
    """
    Gets and sets (item.infoLabels) the extra data of a series, chapter or movie.

    @param item: Item object that represents a movie, series or chapter. The infoLabels attribute will be modified including the extra localized data.
    @type item: Item
    @param seekTmdb: If it is True, it searches www.themoviedb.org to obtain the data, otherwise it obtains the data of the Item itself if they exist.
    @type seekTmdb: bool
    @param search_language: Language code according to ISO 639-1, in case of search at www.themoviedb.org.
    @type search_language: str
    @return: A number whose absolute value represents the number of elements included in the item.infoLabels attribute. This number will be positive if the data has been obtained from www.themoviedb.org and negative otherwise.
    @rtype: int
    """
    global otmdb_global

    def read_data(otmdb_aux):
        # item.infoLabels = otmdb_aux.get_infoLabels(item.infoLabels)
        infoLabels = otmdb_aux.get_infoLabels(item.infoLabels)
        if not infoLabels.get('plot'): infoLabels['plot'] = otmdb_aux.get_plot('en')
        item.infoLabels = infoLabels
        if item.infoLabels.get('thumbnail'):
            item.thumbnail = item.infoLabels['thumbnail']
        if item.infoLabels.get('fanart'):
            item.fanart = item.infoLabels['fanart']

    if seekTmdb:
        def search(otmdb_global, search_type):
            if item.infoLabels.get('season'):
                try:
                    seasonNumber = int(item.infoLabels['season'])
                except ValueError:
                    logger.debug("The season number is not valid.")
                    return -1 * len(item.infoLabels)

                if not otmdb_global or (item.infoLabels['tmdb_id'] and str(otmdb_global.result.get("id")) != item.infoLabels['tmdb_id']) \
                        or (otmdb_global.searched_text and otmdb_global.searched_text != item.infoLabels['tvshowtitle']):
                    if item.infoLabels['tmdb_id']:
                        otmdb_global = Tmdb(id_Tmdb=item.infoLabels['tmdb_id'], search_type=search_type,
                                            search_language=search_language)
                    else:
                        otmdb_global = Tmdb(searched_text=scrapertools.unescape(item.infoLabels['tvshowtitle']), search_type=search_type,
                                            search_language=search_language, year=item.infoLabels['year'])

                    read_data(otmdb_global)

                if item.infoLabels['episode']:
                    try:
                        ep = int(item.infoLabels['episode'])
                    except ValueError:
                        logger.debug("The episode number ({}) is not valid".format(repr(item.infoLabels['episode'])))
                        return -1 * len(item.infoLabels)

                    # We have valid season number and episode number...
                    # ... search episode data
                    item.infoLabels['mediatype'] = 'episode'
                    episode = otmdb_global.get_episode(seasonNumber, ep)

                    if episode:
                        # Update data
                        read_data(otmdb_global)
                        item.infoLabels['mediatype'] = 'episode'
                        if episode.get('episode_title'):
                            item.infoLabels['title'] = episode['episode_title']
                        if episode.get('episode_plot'):
                            item.infoLabels['plot'] = episode['episode_plot']
                        if episode.get('episode_image'):
                            item.infoLabels['poster_path'] = episode['episode_image']
                            item.thumbnail = item.infoLabels['poster_path']
                        if episode.get('episode_air_date'):
                            item.infoLabels['aired'] = episode['episode_air_date']
                        if episode.get('episode_vote_average'):
                            item.infoLabels['rating'] = episode['episode_vote_average']
                        if episode.get('episode_vote_count'):
                            item.infoLabels['votes'] = episode['episode_vote_count']
                        if episode.get('episode_id'):
                            item.infoLabels['episode_id'] = episode['episode_id']
                        if episode.get('episode_imdb_id'):
                            item.infoLabels['episode_imdb_id'] = episode['episode_imdb_id']
                        if episode.get('episode_tvdb_id'):
                            item.infoLabels['episode_tvdb_id'] = episode['episode_tvdb_id']
                        if episode.get('episode_posters'):
                            item.infoLabels['posters'] = episode['episode_posters']

                        return len(item.infoLabels)

                else:
                    # We have a valid season number but no episode number...
                    # ... search season data
                    item.infoLabels['mediatype'] = 'season'
                    season = otmdb_global.get_season(seasonNumber)
                    # enseason = otmdb_global.get_season(seasonNumber, language='en')
                    if not isinstance(season, dict):
                        season = ast.literal_eval(season.decode('utf-8'))
                    # if not isinstance(enseason, dict):
                    #     enseason = ast.literal_eval(enseason.decode('utf-8'))

                    if season:
                        # Update data
                        read_data(otmdb_global)
                        seasonTitle = season.get("name", '')
                        seasonPlot = season.get("overview" , '')
                        seasonDate = season.get("air_date", '')
                        seasonPoster = season.get('poster_path', '')
                        seasonPosters = []
                        for image in season['images']['posters']:
                            seasonPosters.append('https://image.tmdb.org/t/p/original' + image['file_path'])

                        item.infoLabels['title'] = seasonTitle
                        item.infoLabels['plot'] = seasonPlot
                        date = seasonDate
                        if date:
                            date.split('-')
                            item.infoLabels['aired'] = date[2] + "/" + date[1] + "/" + date[0]

                        if seasonPoster:
                            item.infoLabels['poster_path'] = 'https://image.tmdb.org/t/p/original' + seasonPoster
                            item.thumbnail = item.infoLabels['poster_path']
                        if seasonPosters:
                            if seasonPoster: seasonPosters.insert(0, seasonPoster)
                            item.infoLabels['posters'] = seasonPosters

                        return len(item.infoLabels)

            # Search...
            else:
                otmdb = copy.copy(otmdb_global)
                # Search by ID...
                if item.infoLabels['tmdb_id']:
                    # ...Search for tmdb_id
                    otmdb = Tmdb(id_Tmdb=item.infoLabels['tmdb_id'], search_type=search_type,
                                 search_language=search_language)

                elif item.infoLabels['imdb_id']:
                    # ...Search by imdb code
                    otmdb = Tmdb(external_id=item.infoLabels['imdb_id'], external_source="imdb_id", search_type=search_type,
                                 search_language=search_language)

                elif search_type == 'tv':  # bsearch with other codes
                    if item.infoLabels['tvdb_id']:
                        # ...Search for tvdb_id
                        otmdb = Tmdb(external_id=item.infoLabels['tvdb_id'], external_source="tvdb_id",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['freebase_mid']:
                        # ...Search for freebase_mid
                        otmdb = Tmdb(external_id=item.infoLabels['freebase_mid'], external_source="freebase_mid",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['freebase_id']:
                        # ...Search by freebase_id
                        otmdb = Tmdb(external_id=item.infoLabels['freebase_id'], external_source="freebase_id",
                                     search_type=search_type, search_language=search_language)
                    elif item.infoLabels['tvrage_id']:
                        # ...Search by tvrage_id
                        otmdb = Tmdb(external_id=item.infoLabels['tvrage_id'], external_source="tvrage_id",
                                     search_type=search_type, search_language=search_language)

                # if otmdb is None:
                if not item.infoLabels['tmdb_id'] and not item.infoLabels['imdb_id'] and not item.infoLabels['tvdb_id']\
                    and not item.infoLabels['freebase_mid'] and not item.infoLabels['freebase_id'] and not item.infoLabels['tvrage_id']:
                    # Could not search by ID ...
                    # do it by title
                    if search_type == 'tv':
                        # Serial search by title and filtering your results if necessary
                        searched_title = scrapertools.unescape(item.infoLabels['tvshowtitle'])
                    else:
                        # Movie search by title ...
                        # if item.infoLabels['year'] or item.infoLabels['filtro']:
                        # ...and year or filter
                        searched_title = scrapertools.unescape(item.infoLabels['title'])
                    # from core.support import dbg;dbg()
                    otmdb = Tmdb(searched_text=searched_title, search_type=search_type, search_language=search_language,
                                    filtro=item.infoLabels.get('filtro', {}), year=item.infoLabels['year'])
                    if otmdb is not None and not otmdb.get_id():
                        otmdb = Tmdb(searched_text=searched_title, search_type=search_type, search_language=search_language,
                                    filtro=item.infoLabels.get('filtro', {}))
                    if otmdb is not None:
                        if otmdb.get_id() and config.get_setting("tmdb_plus_info", default=False):
                            # If the search has been successful and you are not looking for a list of items,
                            # carry out another search to expand the information
                            if search_type == 'multi':
                                search_type = otmdb.result.get('media_type')

                            otmdb = Tmdb(id_Tmdb=otmdb.result.get("id"), search_type=search_type,
                                         search_language=search_language)

                if otmdb is not None and otmdb.get_id():
                    # The search has found a valid result
                    read_data(otmdb)
                    return len(item.infoLabels)

        def unify():
            new_title = scrapertools.title_unify(item.fulltitle)
            if new_title != item.fulltitle:
                item.infoLabels['tvshowtitle'] = scrapertools.title_unify(item.infoLabels['tvshowtitle'])
                item.infoLabels['title'] = scrapertools.title_unify(item.infoLabels['title'])
                # item.fulltitle = new_title
                return True
        # We check what type of content it is...
        # from core.support import dbg;dbg()
        if item.contentType == 'movie':
            search_type = 'movie'
        elif item.contentType == 'undefined':  # don't know
            search_type = 'multi'
        else:
            search_type = 'tv'

        ret = search(otmdb_global, search_type)
        if not ret:  # try with unified title
            backup = [item.fulltitle, item.infoLabels['tvshowtitle'], item.infoLabels['title']]
            if unify():
                ret = search(otmdb_global, search_type)
            if not ret:
                item.fulltitle, item.infoLabels['tvshowtitle'], item.infoLabels['title'] = backup
        return ret
    # Search in tmdb is deactivated or has not given result
    # item.contentType = item.infoLabels['mediatype']
    return -1 * len(item.infoLabels)


def find_and_set_infoLabels(item):
    logger.debug()

    global otmdb_global
    tmdb_result = None

    if item.contentType == "movie":
        search_type = "movie"
        content_type = config.get_localized_string(60247)
        title = item.contentTitle
    else:
        search_type = "tv"
        content_type = config.get_localized_string(60298)
        title = item.contentSerieName

    # If the title includes the (year) we will remove it
    year = scrapertools.find_single_match(title, "^.+?\s*(\(\d{4}\))$")
    if year:
        title = title.replace(year, "").strip()
        item.infoLabels['year'] = year[1:-1]

    if not item.infoLabels.get("tmdb_id") or not item.infoLabels.get("tmdb_id")[0].isdigit():
        if item.infoLabels.get("imdb_id"): otmdb_global = Tmdb(external_id=item.infoLabels.get("imdb_id"), external_source="imdb_id", search_type=search_type)
        else: otmdb_global = Tmdb(searched_text=scrapertools.unescape(title), search_type=search_type, year=item.infoLabels['year'])

    elif not otmdb_global or str(otmdb_global.result.get("id")) != item.infoLabels['tmdb_id']:
        otmdb_global = Tmdb(id_Tmdb=item.infoLabels['tmdb_id'], search_type=search_type, search_language=def_lang)

    results = otmdb_global.get_list_results()
    if len(results) > 1:
        # select tmdb_id at the first position
        if item.infoLabels['selected_tmdb_id']:
            results.insert(0, results.pop([r.get('id') for r in results].index(int(item.infoLabels['selected_tmdb_id']))))
        tmdb_result = platformtools.show_video_info(results, item=item, caption= content_type % title)
    elif len(results) > 0:
        tmdb_result = results[0]

    if isinstance(item.infoLabels, InfoLabels):
        infoLabels = item.infoLabels
    else:
        infoLabels = InfoLabels()

    if tmdb_result:
        infoLabels['tmdb_id'] = tmdb_result['id']
        # all look if it can be removed and get only from get_nfo ()
        infoLabels['url_scraper'] = ["https://www.themoviedb.org/{}/{}".format(search_type, infoLabels['tmdb_id'])]
        if infoLabels['tvdb_id']:
            infoLabels['url_scraper'].append("http://thetvdb.com/index.php?tab=series&id=" +  infoLabels['tvdb_id'])
        item.infoLabels = infoLabels
        set_infoLabels_item(item)

        return True

    else:
        item.infoLabels = infoLabels
        return False


def get_nfo(item, search_groups=False):
    """
    Returns the information necessary for the result to be scraped into the kodi video library, for tmdb it works only by passing it the url.
    @param item: element that contains the data necessary to generate the info
    @type item: Item
    @rtype: str
    @return:
    """

    if search_groups:
        from platformcode.autorenumber import RENUMBER, GROUP
        path = filetools.join(config.get_data_path(), "settings_channels", item.channel + "_data.json")
        if filetools.exists(path): 
            g = jsontools.load(filetools.read(path)).get(RENUMBER,{}).get(item.fulltitle.strip(),{}).get(GROUP,'')
            if g:
                if type(g) == list: g = ', '.join(g)
                return g + '\n'

        groups = get_groups(item)

        if groups:
            Id = select_group(groups, item)
            if Id == 'original':
                info_nfo = ', '.join(item.infoLabels['url_scraper'])
                return info_nfo + '\n'
            elif Id :
                info_nfo = 'https://www.themoviedb.org/tv/{}/episode_group/{}'.format(item.infoLabels['tmdb_id'], Id)
                return info_nfo + '\n'
            else: return

    info_nfo = ', '.join(item.infoLabels['url_scraper'])

    return info_nfo + '\n'

def get_groups(item):
    valid_groups = []

    url = '{}/tv/{}/episode_groups?api_key={}&language={}'.format(host, item.infoLabels['tmdb_id'], api, def_lang)
    groups = requests.get(url).json().get('results',[])

    for g in groups:
        seasons = []
        add = False
        Id = g.get('id','')
        group = get_group(Id)
        for gr in group:
            if gr['episodes']:
                season = gr['episodes'][0]['season_number']
                if season not in seasons:
                    seasons.append(season)
                    add = True
                else:
                    add = False
                    break
        if add: valid_groups.append(g)
    return valid_groups

def select_group(groups, item):
    selected = -1
    url = '{}/tv/{}?api_key={}&language={}'.format(host, item.infoLabels['tmdb_id'], api, def_lang)
    res = requests.get(url).json()
    selections = [['Original',res.get('number_of_seasons',0), res.get('number_of_episodes',0), '', item.thumbnail]]
    ids = ['original']
    for group in groups:
        ID = group.get('id','')
        if ID:
            selections.append([group.get('name',''), group.get('group_count',0), group.get('episode_count',0), group.get('description',''), item.thumbnail])
            ids.append(ID)
    if selections and ids:
        selected = platformtools.dialog_select_group(config.get_localized_string(70831), selections)
    if selected > -1:
        return ids[selected]
    return ''

def get_group(Id):
    # from core.support import dbg;dbg()
    url = '{}/tv/episode_group/{}?api_key={}&language={}'.format(host, Id, api, def_lang)
    group = requests.get(url).json().get('groups',[])
    return group

def completar_codigos(item):
    """
    If necessary, check if the tvdb identifier exists and if it does not exist try to find it
    """
    if item.contentType != "movie" and not item.infoLabels['tvdb_id']:
        # Launch search for imdb_id on tvdb
        from core.tvdb import Tvdb
        ob = Tvdb(imdb_id=item.infoLabels['imdb_id'])
        item.infoLabels['tvdb_id'] = ob.get_id()
    if item.infoLabels['tvdb_id']:
        url_scraper = "http://thetvdb.com/index.php?tab=series&id=" + item.infoLabels['tvdb_id']
        if url_scraper not in item.infoLabels['url_scraper']:
            item.infoLabels['url_scraper'].append(url_scraper)


def discovery(item, dict_=False, cast=False):
    from core.item import Item

    if dict_:
        if item.page:
            if not item.discovery: item.discovery={}
            item.discovery['page'] = item.page
        listado = Tmdb(discover = dict_, cast=cast)

    elif item.search_type == 'discover':
        listado = Tmdb(discover={'url':'discover/' + item.type, 'with_genres':item.list_type, 'language':def_lang, 'page':item.page})

    elif item.search_type == 'list':
        if item.page == '':
            item.page = '1'
        listado = Tmdb(discover={'url': item.list_type, 'language':def_lang, 'page':item.page})

    return listado

def get_dic_genres(search_type):
    lang = def_lang
    # from core.support import dbg;dbg()
    genres = Tmdb(search_type=search_type)

    return genres.dic_genres[lang]


# Auxiliary class
class ResultDictDefault(dict):
    # Python 2.4
    def __getitem__(self, key):
        try:
            return super(ResultDictDefault, self).__getitem__(key)
        except:
            return self.__missing__(key)

    def __missing__(self, key):
        """
        default values in case the requested key does not exist
        """
        if key in ['genre_ids', 'genre', 'genres']:
            return list()

        elif key == 'images_posters':
            posters = dict()
            if 'images' in list(super(ResultDictDefault, self).keys()) and 'posters' in super(ResultDictDefault, self).__getitem__('images'):
                posters = super(ResultDictDefault, self).__getitem__('images')['posters']
                super(ResultDictDefault, self).__setattr__("images_posters", posters)

            return posters

        elif key == "images_backdrops":
            backdrops = dict()
            if 'images' in list(super(ResultDictDefault, self).keys()) and 'backdrops' in super(ResultDictDefault, self).__getitem__('images'):
                backdrops = super(ResultDictDefault, self).__getitem__('images')['backdrops']
                super(ResultDictDefault, self).__setattr__("images_backdrops", backdrops)

            return backdrops

        elif key == "images_profiles":
            profiles = dict()
            if 'images' in list(super(ResultDictDefault, self).keys()) and 'profiles' in super(ResultDictDefault, self).__getitem__('images'):
                profiles = super(ResultDictDefault, self).__getitem__('images')['profiles']
                super(ResultDictDefault, self).__setattr__("images_profiles", profiles)

            return profiles

        else:
            # The rest of the keys return empty strings by default
            return ""

    def __str__(self):
        return self.tostring(separador=',\n')

    def tostring(self, separador=',\n'):
        ls = []
        for i in list(super(ResultDictDefault, self).items()):
            i_str = str(i)[1:-1]
            if isinstance(i[0], str):
                old = i[0] + "',"
                new = i[0] + "':"
            else:
                old = str(i[0]) + ","
                new = str(i[0]) + ":"
            ls.append(i_str.replace(old, new, 1))

        return "{%s}" % separador.join(ls)


# ---------------------------------------------------------------------------------------------------------------
# class Tmdb:
# Scraper for the API based addon from https://www.themoviedb.org/
# version 1.4:
# - Documented limitation of API use (see below).
# - Added get_season () method
# version 1.3:
# - Fixed error when returning None the path_poster and backdrop_path
# - Fixed a bug that caused the list of genres to accumulate from one call to another
# - Added get_genres () method
# - Added optional parameters alternative_language to the get_plot () method
#
#
# Usage:
# Construction methods:
# Tmdb (search_text, type)
# Parameters:
# searched_text: (str) Text or part of the text to search
# type: ("movie" or "tv") Type of result searched for movies or series. Default "movie"
# (optional) language_search: (str) language code according to ISO 639-1
# (optional) include_adult: (bool) Adult content is included in the search or not. Default
# 'False'
# (optional) year: (str) Release year.
# (optional) page: (int) When there are many results for a search these are organized by pages.
# We can load the page we want, although by default it is always the first page.
# Return:
# This call returns a Tmdb object containing the first page of the search result 'search_text'
# on the themoviedb.org website. The more optional parameters are included, the more precise the search will be.
# Also the object is initialized with the first result of the first page of results.
# Tmdb (id_Tmdb, type)
# Parameters:
# id_Tmdb: (str) Identifier code of a certain movie or series at themoviedb.org
# type: ("movie" or "tv") Type of result searched for movies or series. Default "movie"
# (optional) language_search: (str) language code according to ISO 639-1
# Return:
# This call returns a Tmdb object that contains the result of searching for a movie or series with the
# identifier id_Tmd
# on the themoviedb.org website.
# Tmdb (external_id, external_source, type)
# Parameters:
# external_id: (str) Identifier code of a certain movie or series on the web referenced by
# 'external_source'.
# external_source: (For series: "imdb_id", "freebase_mid", "freebase_id", "tvdb_id", "tvrage_id"; For
# movies: "imdb_id")
# type: ("movie" or "tv") Type of result searched for movies or series. Default "movie"
# (optional) language_search: (str) language code according to ISO 639-1
# Return:
# This call returns a Tmdb object that contains the result of searching for a movie or series with the
# identifier 'external_id' of
# the website referenced by 'external_source' on the themoviedb.org website.
#
# Main methods:
# get_id (): Returns a str with the Tmdb identifier of the loaded movie or series or an empty string if there were no
# nothing loaded.
# get_plot (alternate_language): Returns a str with the synopsis of the series or movie loaded.
# get_poster (response_type, size): Get the poster or a list of posters.
# get_backdrop (response_type, size): Get a background image or a list of background images.
# get_season (season): Get a dictionary with season-specific data.
# get_episode (season, episode): Get a dictionary with specific data of the episode.
# get_genres (): Returns a str with the list of genres to which the movie or series belongs.
#
#
# Other methods:
# load_result (result, page): When the search returns several results we can select which result
# concrete and from which page to load the data.
#
# Limitations:
# The use of the API imposes a limit of 20 simultaneous connections (concurrency) or 30 requests in 10 seconds per IP
# Information about the api: http://docs.themoviedb.apiary.io
# -------------------------------------------------------------------------------------------------------------------


class Tmdb(object):
    # Class attribute
    dic_genres = {}
    '''
    dic_genres={"id_idioma1": {"tv": {"id1": "name1",
                                       "id2": "name2"
                                      },
                                "movie": {"id1": "name1",
                                          "id2": "name2"
                                          }
                                }
                }
    '''
    dic_country = {"AD": "Andorra", "AE": "Emiratos Árabes Unidos", "AF": "Afganistán", "AG": "Antigua y Barbuda",
                   "AI": "Anguila", "AL": "Albania", "AM": "Armenia", "AN": "Antillas Neerlandesas", "AO": "Angola",
                   "AQ": "Antártida", "AR": "Argentina", "AS": "Samoa Americana", "AT": "Austria", "AU": "Australia",
                   "AW": "Aruba", "AX": "Islas de Åland", "AZ": "Azerbayán", "BA": "Bosnia y Herzegovina",
                   "BD": "Bangladesh", "BE": "Bélgica", "BF": "Burkina Faso", "BG": "Bulgaria", "BI": "Burundi",
                   "BJ": "Benín", "BL": "San Bartolomé", "BM": "Islas Bermudas", "BN": "Brunéi", "BO": "Bolivia",
                   "BR": "Brasil", "BS": "Bahamas", "BT": "Bhután", "BV": "Isla Bouvet", "BW": "Botsuana",
                   "BY": "Bielorrusia", "BZ": "Belice", "CA": "Canadá", "CC": "Islas Cocos (Keeling)", "CD": "Congo",
                   "CF": "República Centroafricana", "CG": "Congo", "CH": "Suiza", "CI": "Costa de Marfil",
                   "CK": "Islas Cook", "CL": "Chile", "CM": "Camerún", "CN": "China", "CO": "Colombia",
                   "CR": "Costa Rica", "CU": "Cuba", "CV": "Cabo Verde", "CX": "Isla de Navidad", "CY": "Chipre",
                   "CZ": "República Checa", "DE": "Alemania", "DJ": "Yibuti", "DK": "Dinamarca", "DZ": "Algeria",
                   "EC": "Ecuador", "EE": "Estonia", "EG": "Egipto", "EH": "Sahara Occidental", "ER": "Eritrea",
                   "ES": "España", "ET": "Etiopía", "FI": "Finlandia", "FJ": "Fiyi", "FK": "Islas Malvinas",
                   "FM": "Micronesia", "FO": "Islas Feroe", "FR": "Francia", "GA": "Gabón", "GB": "Gran Bretaña",
                   "GD": "Granada", "GE": "Georgia", "GF": "Guayana Francesa", "GG": "Guernsey", "GH": "Ghana",
                   "GI": "Gibraltar", "GL": "Groenlandia", "GM": "Gambia", "GN": "Guinea", "GP": "Guadalupe",
                   "GQ": "Guinea Ecuatorial", "GR": "Grecia", "GS": "Islas Georgias del Sur y Sandwich del Sur",
                   "GT": "Guatemala", "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong kong",
                   "HM": "Islas Heard y McDonald", "HN": "Honduras", "HR": "Croacia", "HT": "Haití", "HU": "Hungría",
                   "ID": "Indonesia", "IE": "Irlanda", "IM": "Isla de Man", "IN": "India",
                   "IO": "Territorio Británico del Océano Índico", "IQ": "Irak", "IR": "Irán", "IS": "Islandia",
                   "IT": "Italia", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordania", "JP": "Japón", "KG": "Kirgizstán",
                   "KH": "Camboya", "KM": "Comoras", "KP": "Corea del Norte", "KR": "Corea del Sur", "KW": "Kuwait",
                   "KY": "Islas Caimán", "KZ": "Kazajistán", "LA": "Laos", "LB": "Líbano", "LC": "Santa Lucía",
                   "LI": "Liechtenstein", "LK": "Sri lanka", "LR": "Liberia", "LS": "Lesoto", "LT": "Lituania",
                   "LU": "Luxemburgo", "LV": "Letonia", "LY": "Libia", "MA": "Marruecos", "MC": "Mónaco",
                   "MD": "Moldavia", "ME": "Montenegro", "MF": "San Martín (Francia)", "MG": "Madagascar",
                   "MH": "Islas Marshall", "MK": "Macedônia", "ML": "Mali", "MM": "Birmania", "MN": "Mongolia",
                   "MO": "Macao", "MP": "Islas Marianas del Norte", "MQ": "Martinica", "MR": "Mauritania",
                   "MS": "Montserrat", "MT": "Malta", "MU": "Mauricio", "MV": "Islas Maldivas", "MW": "Malawi",
                   "MX": "México", "MY": "Malasia", "NA": "Namibia", "NE": "Niger", "NG": "Nigeria", "NI": "Nicaragua",
                   "NL": "Países Bajos", "NO": "Noruega", "NP": "Nepal", "NR": "Nauru", "NU": "Niue",
                   "NZ": "Nueva Zelanda", "OM": "Omán", "PA": "Panamá", "PE": "Perú", "PF": "Polinesia Francesa",
                   "PH": "Filipinas", "PK": "Pakistán", "PL": "Polonia", "PM": "San Pedro y Miquelón",
                   "PN": "Islas Pitcairn", "PR": "Puerto Rico", "PS": "Palestina", "PT": "Portugal", "PW": "Palau",
                   "PY": "Paraguay", "QA": "Qatar", "RE": "Reunión", "RO": "Rumanía", "RS": "Serbia", "RU": "Rusia",
                   "RW": "Ruanda", "SA": "Arabia Saudita", "SB": "Islas Salomón", "SC": "Seychelles", "SD": "Sudán",
                   "SE": "Suecia", "SG": "Singapur", "SH": "Santa Elena", "SI": "Eslovenia",
                   "SJ": "Svalbard y Jan Mayen",
                   "SK": "Eslovaquia", "SL": "Sierra Leona", "SM": "San Marino", "SN": "Senegal", "SO": "Somalia",
                   "SV": "El Salvador", "SY": "Siria", "SZ": "Swazilandia", "TC": "Islas Turcas y Caicos", "TD": "Chad",
                   "TF": "Territorios Australes y Antárticas Franceses", "TG": "Togo", "TH": "Tailandia",
                   "TJ": "Tadjikistán", "TK": "Tokelau", "TL": "Timor Oriental", "TM": "Turkmenistán", "TN": "Tunez",
                   "TO": "Tonga", "TR": "Turquía", "TT": "Trinidad y Tobago", "TV": "Tuvalu", "TW": "Taiwán",
                   "TZ": "Tanzania", "UA": "Ucrania", "UG": "Uganda",
                   "UM": "Islas Ultramarinas Menores de Estados Unidos",
                   "UY": "Uruguay", "UZ": "Uzbekistán", "VA": "Ciudad del Vaticano",
                   "VC": "San Vicente y las Granadinas",
                   "VE": "Venezuela", "VG": "Islas Vírgenes Británicas", "VI": "Islas Vírgenes de los Estados Unidos",
                   "VN": "Vietnam", "VU": "Vanuatu", "WF": "Wallis y Futuna", "WS": "Samoa", "YE": "Yemen",
                   "YT": "Mayotte", "ZA": "Sudáfrica", "ZM": "Zambia", "ZW": "Zimbabue", "BB": "Barbados",
                   "BH": "Bahrein",
                   "DM": "Dominica", "DO": "República Dominicana", "GU": "Guam", "IL": "Israel", "KE": "Kenia",
                   "KI": "Kiribati", "KN": "San Cristóbal y Nieves", "MZ": "Mozambique", "NC": "Nueva Caledonia",
                   "NF": "Isla Norfolk", "PG": "Papúa Nueva Guinea", "SR": "Surinám", "ST": "Santo Tomé y Príncipe",
                   "US": "EEUU"}

    def __init__(self, **kwargs):
        self.page = kwargs.get('page', 1)
        self.index_results = 0
        self.cast = kwargs.get('cast', False)
        self.results = []
        self.result = ResultDictDefault()
        self.total_pages = 0
        self.total_results = 0

        self.season = {}
        self.searched_text = kwargs.get('searched_text', '')

        self.search_id = kwargs.get('id_Tmdb', '')
        self.search_text = re.sub('\[\\\?(B|I|COLOR)\s?[^\]]*\]', '', self.searched_text).strip()
        self.search_type = kwargs.get('search_type', '')
        self.search_language = kwargs.get('search_language', def_lang)
        self.fallback_language = 'en'
        # self.search_include_adult = kwargs.get('include_adult', False)
        self.search_year = kwargs.get('year', '')
        self.search_filter = kwargs.get('filtro', {})
        self.discover = kwargs.get('discover', {})

        # Refill gender dictionary if necessary
        if (self.search_type == 'movie' or self.search_type == "tv") and (self.search_language not in Tmdb.dic_genres or self.search_type not in Tmdb.dic_genres[self.search_language]):
            self.filling_dic_genres(self.search_type, self.search_language)

        if not self.search_type:
            self.search_type = 'movie'

        if self.search_id:
            # Search by tmdb identifier
            self.__by_id()

        elif self.search_text:
            # Search by text
            self.__search(page=self.page)

        elif 'external_source' in kwargs and 'external_id' in kwargs:
            # Search by external identifier according to type.
            # TV Series: imdb_id, freebase_mid, freebase_id, tvdb_id, tvrage_id
            # Movies: imdb_id
            if (self.search_type == 'movie' and kwargs.get('external_source') == "imdb_id") or (self.search_type == 'tv' and kwargs.get('external_source') in ("imdb_id", "freebase_mid", "freebase_id", "tvdb_id", "tvrage_id")):
                self.search_id = kwargs.get('external_id')
                self.__by_id(source=kwargs.get('external_source'))

        elif self.discover:
            self.__discover()

        else:
            logger.debug("Created empty object")

    @staticmethod
    @cache_response
    def get_json(url, cache=True):
        # from core.support import dbg;dbg()
        try:
            result = httptools.downloadpage(url, cookies=False, ignore_response_code=True)

            res_headers = result.headers
            dict_data = result.json
            #logger.debug("result_data es %s" % dict_data)

            if "status_code" in dict_data:
                #logger.debug("\nError de tmdb: %s %s" % (dict_data["status_code"], dict_data["status_message"]))

                if dict_data["status_code"] == 25:
                    while "status_code" in dict_data and dict_data["status_code"] == 25:
                        wait = int(res_headers['retry-after'])
                        #logger.error("Limit reached, we wait to call back on ...%s" % wait)
                        time.sleep(wait)
                        # logger.debug("RE Call #%s" % d)
                        result = httptools.downloadpage(url, cookies=False)

                        res_headers = result.headers
                        # logger.debug("res_headers es %s" % res_headers)
                        dict_data = result.json
                        # logger.debug("result_data es %s" % dict_data)

        # error getting data
        except Exception as ex:
            message = "An exception of type %s occured. Arguments:\n%s" % (type(ex).__name__, repr(ex.args))
            logger.error("error in: %s" % message)
            dict_data = {}

        return dict_data

    @classmethod
    def filling_dic_genres(cls, search_type='movie', language=def_lang):
        # Fill dictionary of genres of the type and language passed as parameters
        if language not in cls.dic_genres:
            cls.dic_genres[language] = {}

        if search_type not in cls.dic_genres[language]:
            cls.dic_genres[language][search_type] = {}
            url = ('{}/genre/{}/list?api_key={}&language={}'.format(host, search_type, api, language))
            try:
                logger.debug("[Tmdb.py] Filling in dictionary of genres")

                result = cls.get_json(url)
                if not isinstance(result, dict):
                    result = ast.literal_eval(result.decode('utf-8'))
                list_genres = result.get("genres", {})

                for i in list_genres:
                    cls.dic_genres[language][search_type][str(i["id"])] = i["name"]
            except:
                logger.error("Error generating dictionaries")
                import traceback
                logger.error(traceback.format_exc())

    def __by_id(self, source='tmdb'):
        # from core.support import dbg;dbg()

        if self.search_id:
            if source == "tmdb":
                url = ('{}/{}/{}?api_key={}&language={}&append_to_response=images,videos,external_ids,credits&include_image_language={},en,null'.format(host, self.search_type, self.search_id, api, self.search_language, self.search_language))
                searching = "id_Tmdb: {}".format(self.search_id)
            else:
                url = ('{}/find/{}?external_source={}&api_key={}&language={}'.format(host, self.search_id, source, api, self.search_language))
                searching = "{}: {}".format(source.capitalize(), self.search_id)

            logger.debug("[Tmdb.py] Searching %s:\n%s" % (searching, url))
            result = self.get_json(url)
            if not isinstance(result, dict):
                result = ast.literal_eval(result.decode('utf-8'))

            if result:
                if source != "tmdb":
                    if self.search_type == "movie":
                        result = result["movie_results"][0]
                    else:
                        if result["tv_results"]:
                            result = result["tv_results"][0]
                        else:
                            result = result['tv_episode_results'][0]

                result = self.get_mpaa(result)

                self.results = [result]
                self.total_results = 1
                self.total_pages = 1
                self.result = ResultDictDefault(result)
                self.result['media_type'] = self.search_type.replace('tv', 'tvshow')

            else:
                # No search results
                msg = "The search of %s gave no results" % searching
                logger.debug(msg)

    def __search(self, index_results=0, page=1):
        self.result = ResultDictDefault()
        results = []
        text_simple = self.search_text.lower()
        text_quote = urllib.quote(text_simple)
        total_results = 0
        total_pages = 0
        searching = ""

        if self.search_text:
            url = ('{}/search/{}?api_key={}&query={}&language={}&include_adult={}&page={}'.format(host, self.search_type, api, text_quote, self.search_language, False, page))

            if self.search_year:
                if self.search_type == 'movie':
                    url += '&primary_release_year=%s' % self.search_year
                else:
                    url += '&first_air_date_year=%s' % self.search_year

            searching = self.search_text.capitalize()
            logger.debug("[Tmdb.py] Searching %s on page %s:\n%s" % (searching, page, url))
            result = self.get_json(url)
            if not isinstance(result, dict):
                result = ast.literal_eval(result.decode('utf-8'))

            total_results = result.get("total_results", 0)
            total_pages = result.get("total_pages", 0)

            if total_results > 0:
                results = [r for r in result["results"] if r.get('first_air_date', r.get('release_date', ''))]

            if self.search_filter and total_results > 1:
                for key, value in list(dict(self.search_filter).items()):
                    for r in results[:]:
                        if not r[key]:
                            r[key] = str(r[key])
                        if key not in r or value not in r[key]:
                            results.remove(r)
                            total_results -= 1

        if results:
            if index_results >= len(results):
                # A higher number of results has been requested than those obtained
                logger.error(
                    "The search for '%s' gave %s results for the page %s \n It is impossible to show the result number %s"
                    % (searching, len(results), page, index_results))
                return 0

            # We sort result based on fuzzy match to detect most similar
            if len(results) > 1:
                from lib.fuzzy_match import algorithims
                if self.search_type == 'multi':
                    if self.search_year:
                        for r in results:
                            if (r.get('release_date', '') and r.get('release_date', '')[:4] == self.search_year) or (r.get('first_air_date', '') and r.get('first_air_date', '')[:4] == self.search_year):
                                results = [r]
                                break
                    if len(results) > 1:
                        results.sort(key=lambda r: algorithims.trigram(text_simple, r.get('name', '') if r.get('media_type') == 'tv' else r.get('title', '')), reverse=True)
                else:
                    results.sort(key=lambda r: algorithims.trigram(text_simple, r.get('name', '') if self.search_type == 'tv' else r.get('title', '')), reverse=True)

            # We return the number of results of this page
            self.results = results
            self.total_results = total_results
            self.total_pages = total_pages
            self.result = ResultDictDefault(self.results[index_results])
            # self.result['mediatype'] = self.result['media_type']

            if not config.get_setting('tmdb_plus_info'):
                self.result = self.get_mpaa(self.result)
            return len(self.results)

        else:
            # No search results
            msg = "The search for '%s' gave no results for page %s" % (searching, page)
            logger.error(msg)
            return 0

    def __discover(self, index_results=0):
        self.result = ResultDictDefault()
        results = []
        total_results = 0
        total_pages = 0

        # Exampleself.discover: {'url': 'discover/movie', 'with_cast': '1'}
        # url: API method to run
        # rest of keys: Search parameters concatenated to the url
        type_search = self.discover.get('url', '')
        if type_search:
            params = []
            for key, value in list(self.discover.items()):
                if key != "url":
                    params.append(key + "=" + str(value))

            url = ('{}/{}?api_key={}&{}'.format(host, type_search, api, "&".join(params)))

            logger.debug("[Tmdb.py] Searching %s:\n%s" % (type_search, url))
            result = self.get_json(url, cache=False)
            if not isinstance(result, dict):
                result = ast.literal_eval(result.decode('utf-8'))

            total_results = result.get("total_results", -1)
            total_pages = result.get("total_pages", 1)

            if total_results > 0 or self.cast:
                if self.cast:
                    results = result['cast']
                    total_results = len(results)
                else:
                    results = result["results"]
                if self.search_filter and results:
                    # TODO documentar esta parte
                    for key, value in list(dict(self.search_filter).items()):
                        for r in results[:]:
                            if key not in r or r[key] != value:
                                results.remove(r)
                                total_results -= 1
            elif total_results == -1:
                results = result

            if index_results >= len(results):
                logger.error(
                    "The search for '%s' did not give %s results" % (type_search, index_results))
                return 0

        # We return the number of results of this page
        if results:
            self.results = results
            self.total_results = total_results
            self.total_pages = total_pages
            if total_results > 0:
                self.result = ResultDictDefault(self.results[index_results])

            else:
                self.result = results
            return len(self.results)
        else:
            # No search results
            logger.error("The search for '%s' gave no results" % type_search)
            return 0

    def load_result(self, index_results=0, page=1):
        # If there are no results, there is only one or if the number of results on this page is less than the index sought to exit
        self.result = ResultDictDefault()
        num_result_page = len(self.results)

        if page > self.total_pages:
            return False

        if page != self.page:
            num_result_page = self.__search(index_results, page)

        if num_result_page == 0 or num_result_page <= index_results:
            return False

        self.page = page
        self.index_results = index_results
        self.result = ResultDictDefault(self.results[index_results])
        return True

    def get_list_results(self, num_result=20):
        # logger.debug("self %s" % str(self))
        res = []

        if num_result <= 0:
            num_result = self.total_results
        num_result = min([num_result, self.total_results])

        cr = 0

        for p in range(1, self.total_pages + 1):
            for r in range(0, len(self.results)):
                try:
                    if self.load_result(r, p):
                        result = self.result.copy()

                        result['thumbnail'] = self.get_poster(size="w300")
                        result['fanart'] = self.get_backdrop()

                        res.append(result)
                        cr += 1

                        if cr >= num_result:
                            return res
                except:
                    continue

        return res

    def get_genres(self, origen=None):
        """
        :param origen: Source dictionary where the infoLabels are obtained, by default self.result
        :type origen: Dict
        :return: Returns the list of genres to which the movie or series belongs.
        :rtype: str
        """
        genre_list = []

        if not origen:
            origen = self.result

        if "genre_ids" in origen:
            # Search list of genres by IDs
            for i in origen.get("genre_ids"):
                try:
                    genre_list.append(Tmdb.dic_genres[self.search_language][self.search_type][str(i)])
                except:
                    pass

        elif "genre" in origen or "genres" in origen:
            # Search genre list (object list {id, name})
            v = origen["genre"]
            v.extend(origen["genres"])
            for i in v:
                genre_list.append(i['name'])

        return ', '.join(genre_list)

    def search_by_id(self, id, source='tmdb', search_type='movie'):
        self.search_id = id
        self.search_type = search_type
        self.__by_id(source=source)

    def get_id(self):
        """
        :return: Returns the Tmdb identifier of the loaded movie or series or an empty string in case nothing was loaded. You can use this method to find out if a search has been successful or not.
        :rtype: str
        """
        return str(self.result.get('id', ""))

    def get_plot(self, language_alternative=''):
        """

        :param language_alternative: Language code, according to ISO 639-1, if there is no synopsis in the language set for the search.
            By default, the original language is used. If None is used as the alternative_language, it will only search in the set language.
        :type language_alternative: str
        :return: Returns the synopsis of a movie or series
        :rtype: str
        """
        ret = ""
        # from core.support import dbg;dbg()

        if 'id' in self.result:
            ret = self.result.get('overview')
            if ret == "" and str(language_alternative).lower() != 'none':
                # Let's launch a search for id and reread the synopsis again
                self.search_id = str(self.result["id"])
                if language_alternative:
                    self.search_language = language_alternative
                else:
                    self.search_language = self.result['original_language']

                url = ('{}/{}/{}?api_key={}&language={}'.format(host, self.search_type, self.search_id, api, self.search_language))

                result = self.get_json(url)
                if not isinstance(result, dict):
                    result = ast.literal_eval(result.decode('utf-8'))

                if 'overview' in result:
                    self.result['overview'] = result['overview']
                    ret = self.result['overview']

        return ret

    def get_poster(self, response_type="str", size="original"):
        """

        @param response_type: Data type returned by this method. Default "str"
        @type response_type: list, str
        @param size: ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280", "original")
            Indicates the width (w) or height (h) of the image to download. Default "original"
        @return: If the response_type is "list" it returns a list with all the urls of the poster images of the specified size.
            If the response_type is "str" ​​it returns the url of the poster image, most valued, of the specified size.
            If the specified size does not exist, the images are returned to the original size.
        @rtype: list, str
        """
        ret = []
        if size not in ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280"):
            size = "original"

        if self.result["poster_path"] is None or self.result["poster_path"] == "":
            poster_path = ""
        else:
            poster_path = 'https://image.tmdb.org/t/p/' + size + self.result["poster_path"]

        if response_type == 'str':
            return poster_path
        elif not self.result["id"]:
            return []

        if len(self.result['images_posters']) == 0:
            # We are going to launch a search by id and reread again
            self.search_id = str(self.result["id"])
            self.__by_id()

        if len(self.result['images_posters']) > 0:
            for i in self.result['images_posters']:
                imagen_path = i['file_path']
                if size != "original":
                    # We cannot order sizes larger than the original
                    if size[1] == 'w' and int(imagen_path['width']) < int(size[1:]):
                        size = "original"
                    elif size[1] == 'h' and int(imagen_path['height']) < int(size[1:]):
                        size = "original"
                ret.append('https://image.tmdb.org/t/p/' + size + imagen_path)
        else:
            ret.append(poster_path)

        return ret

    def get_backdrop(self, response_type="str", size="original"):
        """
        Returns the images of type backdrop
        @param response_type: Data type returned by this method. Default "str"
        @type response_type: list, str
        @param size: ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280", "original")
            Indicates the width (w) or height (h) of the image to download. Default "original"
        @type size: str
        @return: If the response_type is "list" it returns a list with all the urls of the backdrop images of the specified size.
            If the response_type is "str" ​​it returns the url of the backdrop type image, most valued, of the specified size.
            If the specified size does not exist, the images are returned to the original size.
        @rtype: list, str
        """
        ret = []
        if size not in ("w45", "w92", "w154", "w185", "w300", "w342", "w500", "w600", "h632", "w780", "w1280"):
            size = "original"

        if self.result["backdrop_path"] is None or self.result["backdrop_path"] == "":
            backdrop_path = ""
        else:
            backdrop_path = 'get_posterget_poster' + size + self.result["backdrop_path"]

        if response_type == 'str':
            return backdrop_path
        elif self.result["id"] == "":
            return []

        if len(self.result['images_backdrops']) == 0:
            # Let's launch a search by id and reread everything
            self.search_id = str(self.result["id"])
            self.__by_id()

        if len(self.result['images_backdrops']) > 0:
            for i in self.result['images_backdrops']:
                imagen_path = i['file_path']
                if size != "original":
                    # We cannot order sizes larger than the original
                    if size[1] == 'w' and int(imagen_path['width']) < int(size[1:]):
                        size = "original"
                    elif size[1] == 'h' and int(imagen_path['height']) < int(size[1:]):
                        size = "original"
                ret.append('https://image.tmdb.org/t/p/' + size + imagen_path)
        else:
            ret.append(backdrop_path)

        return ret

    def get_season(self, seasonNumber=1, language=''):
        # --------------------------------------------------------------------------------------------------------------------------------------------
        # Parameters:
        # season number: (int) Season number. Default 1.
        # Return: (Dec)
        # Returns a dictionary with data about the season.
        # You can get more information about the returned data at:
        # http://docs.themoviedb.apiary.io/#reference/tv-seasons/tvidseasonseasonnumber/get
        # http://docs.themoviedb.apiary.io/#reference/tv-seasons/tvidseasonseasonnumbercredits/get
        # --------------------------------------------------------------------------------------------------------------------------------------------
        if not self.result["id"] or self.search_type != "tv":
            return {}

        seasonNumber = int(seasonNumber)
        if seasonNumber < 0:
            seasonNumber = 1
        search_language = language if language else self.search_language

        if not self.season.get(seasonNumber, {}) or language:
            # If there is no information about the requested season, check the website

            # http://api.themoviedb.org/3/tv/1407/season/1?api_key=a1ab8b8669da03637a4b98fa39c39228&language=es&
            # append_to_response=credits
            url = "{}/tv/{}/season/{}?api_key={}&language={}&append_to_response=videos,images,credits,external_ids&include_image_language={},en,null".format(host, self.result["id"], seasonNumber, api, search_language, search_language)
            # fallbackUrl = "{}/tv/{}/season/{}?api_key={}&language=en&append_to_response=videos,images,credits&include_image_language={},en,null".format(host, self.result["id"], seasonNumber, api, search_language)
            logger.debug('TMDB URL', url)

            searching = "id_Tmdb: " + str(self.result["id"]) + " season: " + str(seasonNumber) + "\nURL: " + url
            logger.debug("[Tmdb.py] Searching " + searching)
            # from core.support import dbg;dbg()
            try:
                self.season[seasonNumber] = self.get_json(url)
                if not isinstance(self.season[seasonNumber], dict):
                    self.season[seasonNumber] = ast.literal_eval(self.season[seasonNumber].decode('utf-8'))

            except:
                logger.error("Unable to get the season")
                self.season[seasonNumber] = {"status_code": 15, "status_message": "Failed"}
                self.season[seasonNumber] = {"episodes": {}}

            if "status_code" in self.season[seasonNumber]:
                # An error has occurred
                msg = config.get_localized_string(70496) + searching + config.get_localized_string(70497)
                msg += "\nTmdb error: %s %s" % (
                self.season[seasonNumber]["status_code"], self.season[seasonNumber]["status_message"])
                logger.debug(msg)
                self.season[seasonNumber] = {}

        return self.season[seasonNumber]

    def get_collection(self, _id=''):
        ret = {}
        if not _id:
            collection = self.result.get('belongs_to_collection', {})
            if collection:
                _id = collection.get('id')
        if _id:
            translation = {}
            url = '{}/collection/{}?api_key={}&language={}&append_to_response=images&include_image_language={},en,null'.format(host, _id, api, self.search_language, self.search_language)
            tanslationurl = '{}/collection/{}/translations?api_key={}'.format(host, _id, api)
            info = self.get_json(url)
            for t in self.get_json(tanslationurl).get('translations'):
                if t.get('iso_639_1') == self.fallback_language:
                    translation = t.get('data',{})
                    break
            ret['set'] = info.get('name') if info.get('name') else translation.get('name')
            ret['setid'] = _id
            ret['setoverview'] = info.get('overview') if info.get('overview') else translation.get('overview', '')
            posters = ['https://image.tmdb.org/t/p/original' + info.get('poster_path')] if info.get('poster_path') else []
            fanarts = ['https://image.tmdb.org/t/p/original' + info.get('backdrop_path')] if info.get('backdrop_path') else []
            for image in info['images']['posters']:
                posters.append('https://image.tmdb.org/t/p/original' + image['file_path'])
            for image in info['images']['backdrops']:
                fanarts.append('https://image.tmdb.org/t/p/original' + image['file_path'])
            ret['setposters'] = posters
            ret['setfanarts'] = fanarts
        return ret

    def get_episode(self, seasonNumber=1, chapter=1):
        # --------------------------------------------------------------------------------------------------------------------------------------------
        # Parameters:
        # season number (optional): (int) Season number. Default 1.
        # chapter: (int) Chapter number. Default 1.
        # Return: (Dec)
        # Returns a dictionary with the following elements:
        # "season_name", "season_synopsis", "season_poster", "season_num_ episodes" (int),
        # "season_air_date", "episode_vote_count", "episode_vote_average",
        # "episode_title", "episode_synopsis", "episode_image", "episode_air_date",
        # "episode_crew" and "episode_guest_stars",
        # With chapter == -1 the dictionary will only have the elements referring to the season
        # --------------------------------------------------------------------------------------------------------------------------------------------

        if not self.result["id"] or self.search_type != "tv":
            return {}

        try:
            chapter = int(chapter)
            season = int(seasonNumber)
        except ValueError:
            logger.debug("The episode or season number is not valid")
            return {}

        # season = self.get_season(seasonNumber)
        # # enseason = self.get_season(seasonNumber, language='en')
        # # if not isinstance(season, dict):
        # #     season = ast.literal_eval(season.decode('utf-8'))
        # # if not isinstance(enseason, dict):
        # #     enseason = ast.literal_eval(enseason.decode('utf-8'))
        # if not season:
        #     # An error has occurred
        #     return {}

        # if len(season["episodes"]) == 0:
        #     # An error has occurred
        #     logger.error("Episode %d of the season %d not found." % (chapter, seasonNumber))
        #     return {}

        # elif len(season["episodes"]) < chapter and season["episodes"][-1]['episode_number'] >= chapter:
        #     n = None
        #     for i, chapters in enumerate(season["episodes"]):
        #         if chapters['episode_number'] == chapter:
        #             n = i + 1
        #             break
        #     if n != None:
        #         chapter = n
        #     else:
        #         logger.error("Episode %d of the season %d not found." % (chapter, seasonNumber))
        #         return {}

        # elif len(season["episodes"]) < chapter:
        #     logger.error("Episode %d of the season %d not found." % (chapter, seasonNumber))
        #     return {}

        # ret_dic = get_season_dic(season)

        # if chapter == 0:
        #     # If we only look for season data, include the technical team that has intervened in any chapter
        #     dic_aux = dict((i['id'], i) for i in ret_dic["season_crew"])
        #     for e in season["episodes"]:
        #         for crew in e['crew']:
        #             if crew['id'] not in list(dic_aux.keys()):
        #                 dic_aux[crew['id']] = crew
        #     ret_dic["season_crew"] = list(dic_aux.values())


        # Obtain chapter data if applicable
        # from core.support import dbg;dbg()
        ret_dic = {}
        if chapter > 0:
            # episode = season["episodes"][chapter - 1]
            url = "{}/tv/{}/season/{}/episode/{}?api_key={}&language={}&append_to_response=videos,images,credits,external_ids&include_image_language={},en,null".format(host, self.result["id"], seasonNumber, chapter, api, self.search_language, self.search_language)
            episode = self.get_json(url)
            # logger.debug('EPISODE', url)

            episodeTitle = episode.get("name", '')
            episodeId = episode.get('id', '')
            episodePlot = episode.get('overview', '')
            episodeDate = episode.get('air_date', '')
            episodeImage =  episode.get('still_path', '')
            episodeCrew = episode.get('crew', [])
            episodeStars = episode.get('guest_stars', [])
            episodeVoteCount = episode.get('vote_count', 0)
            episodeVoteAverage = episode.get('vote_average', 0)
            externalIds = episode.get('external_ids', {})
            imdb_id = externalIds.get('imdb_id')
            tvdb_id = externalIds.get('tvdb_id')
            posters = []
            for image in episode.get('images',{}).get('stills',{}):
                posters.append('https://image.tmdb.org/t/p/original' + image['file_path'])

            ret_dic["episode_title"] = episodeTitle
            ret_dic["episode_plot"] = episodePlot

            if episodeImage:
                ret_dic["episode_image"] = 'https://image.tmdb.org/t/p/original' + episodeImage
            else:
                ret_dic["episode_image"] = ""
            if episodeDate:
                date = episodeDate.split("-")
                ret_dic["episode_air_date"] = date[2] + "/" + date[1] + "/" + date[0]
            else:
                ret_dic["episode_air_date"] = ""
            if posters:
                ret_dic['episode_posters'] = posters

            ret_dic["episode_crew"] = episodeCrew
            if episodeStars:
                ret_dic["episode_actors"] = [[k['name'], k['character'], 'https://image.tmdb.org/t/p/original/' + k['profile_path'] if k['profile_path'] else '', k['order']] for k in episodeStars]
            ret_dic["episode_vote_count"] = episodeVoteCount
            ret_dic["episode_vote_average"] = episodeVoteAverage
            ret_dic["episode_id"] = episodeId
            ret_dic["episode_imdb_id"] = imdb_id
            ret_dic["episode_tvdb_id"] = tvdb_id


        return ret_dic

    def get_list_episodes(self):
        url = '{}/tv/{}?api_key={}&language={}'.format(host, self.search_id, api, self.search_language)
        results = requests.get(url).json().get('seasons', [])
        seasons = []
        if results and 'Error' not in results:
            for season in results:
                url = '{}/tv/{}/season/{}?api_key={}&language={}'.format(host, self.search_id, season['season_number'], api, self.search_language)
                try: start_from = requests.get(url).json()['episodes'][0]['episode_number']
                except: start_from = 1
                seasons.append({'season_number':season['season_number'], 'episode_count':season['episode_count'], 'start_from':start_from})
        return seasons

    def get_videos(self):
        """
        :return: Returns an ordered list (language / resolution / type) of Dict objects in which each of its elements corresponds to a trailer, teaser or clip from youtube.
        :rtype: list of Dict
        """
        ret = []

        if self.result['id']:
            if self.result['videos']:
                self.result["videos"] = self.result["videos"]['results']
            else:
                self.result["videos"] = []
                # First video search in the search language
                url = "{}/{}/{}/videos?api_key={}&language={}".format(host, self.search_type, self.result['id'], api, self.search_language)

                dict_videos = self.get_json(url)
                if not isinstance(dict_videos, dict):
                    dict_videos = ast.literal_eval(dict_videos.decode('utf-8'))

                if dict_videos['results']:
                    dict_videos['results'] = sorted(dict_videos['results'], key=lambda x: (x['type'], x['size']))
                    self.result["videos"] = dict_videos['results']

            # If the search language is not English, do a second video search in English
            if self.search_language != 'en':
                url = "{}/{}/{}/videos?api_key={}".format(host, self.search_type, self.result['id'], api)

                dict_videos = self.get_json(url)
                if not isinstance(dict_videos, dict):
                    dict_videos = ast.literal_eval(dict_videos.decode('utf-8'))

                if dict_videos['results']:
                    dict_videos['results'] = sorted(dict_videos['results'], key=lambda x: (x['type'], x['size']))
                    self.result["videos"].extend(dict_videos['results'])

            # If the searches have obtained results, return a list of objects
            for i in self.result['videos']:
                if i['site'] == "YouTube":
                    ret.append({'name': i['name'],
                                'url': "plugin://plugin.video.youtube/play/?video_id={}".format(i['key']),
                                'size': str(i['size']),
                                'type': i['type'],
                                'language': i['iso_639_1']})

        return ret

    def get_infoLabels(self, infoLabels=None, origen=None):
        """
        :param infoLabels: Extra information about the movie, series, season or chapter.
        :type infoLabels: Dict
        :param origen: Source dictionary where the infoLabels are obtained, by default self.result
        :type origen: Dict
        :return: Returns the extra information obtained from the current object. If the infoLables parameter was passed, the returned value will be read as a duly updated parameter.
        :rtype: Dict
        """

        if infoLabels:
            ret_infoLabels = InfoLabels(infoLabels)
        else:
            ret_infoLabels = InfoLabels()
        # Start Listings
        l_country = [i.strip() for i in ret_infoLabels['country'].split(',') if ret_infoLabels['country']]
        l_director = [i.strip() for i in ret_infoLabels['director'].split(',') if ret_infoLabels['director']]
        l_director_image = ret_infoLabels.get('director_image', [])
        l_director_id = ret_infoLabels.get('director_id', [])
        l_writer = [i.strip() for i in ret_infoLabels['writer'].split(',') if ret_infoLabels['writer']]
        l_writer_image = ret_infoLabels.get('writer_image', [])
        l_writer_id = ret_infoLabels.get('writer_id', [])
        l_castandrole = ret_infoLabels.get('castandrole', [])

        if not origen:
            origen = self.result

        if 'credits' in list(origen.keys()):
            dic_origen_credits = origen['credits']
            origen['credits_cast'] = dic_origen_credits.get('cast', [])
            origen['credits_crew'] = dic_origen_credits.get('crew', [])
            del origen['credits']

        if 'images' in list(origen.keys()):
            dic_origen_credits = origen['images']
            origen['posters'] = dic_origen_credits.get('posters', [])
            origen['fanarts'] = dic_origen_credits.get('backdrops', [])
            del origen['images']

        items = list(origen.items())

        # Season / episode information
        if ret_infoLabels['season'] and self.season.get(ret_infoLabels['season']):
            # If there is data loaded for the indicated season

            episodio = -1
            if ret_infoLabels['episode']:
                episodio = ret_infoLabels['episode']

            items.extend(list(self.get_episode(ret_infoLabels['season'], episodio).items()))


        for k, v in items:
            if not v:
                continue
            elif isinstance(v, str):
                v = re.sub(r"\n|\r|\t", "", v)
                # fix
                if v == "None":
                    continue

            if k == 'media_type':
                # from core.support import dbg;dbg()
                ret_infoLabels['mediatype'] = v if v in ['tv', 'tvshow'] else 'movie'

            elif k == 'overview':
                if origen:
                    ret_infoLabels['plot'] = v
                else:
                    ret_infoLabels['plot'] = self.get_plot()

            elif k == 'runtime':                                # Duration for movies
                ret_infoLabels['duration'] = int(v) * 60

            elif k == 'episode_run_time':                       # Duration for episodes
                try:
                    for v_alt in v:                             # It comes as a list (?!)
                        ret_infoLabels['duration'] = int(v_alt) * 60
                except:
                    pass

            elif k == 'release_date':
                ret_infoLabels['year'] = int(v[:4])
                ret_infoLabels['premiered'] = v

            elif k == 'first_air_date':
                ret_infoLabels['year'] = int(v[:4])
                ret_infoLabels['aired'] = v
                ret_infoLabels['premiered'] = ret_infoLabels['aired']

            elif k == 'original_title' or k == 'original_name':
                ret_infoLabels['originaltitle'] = v

            elif k == 'vote_average':
                ret_infoLabels['rating'] = float(v)

            elif k == 'vote_count':
                ret_infoLabels['votes'] = v

            elif k in ['poster_path', 'profile_path']:
                ret_infoLabels['thumbnail'] = 'https://image.tmdb.org/t/p/original' + v

            elif k == 'backdrop_path':
                ret_infoLabels['fanart'] = 'https://image.tmdb.org/t/p/original' + v

            elif k == 'id':
                ret_infoLabels['tmdb_id'] = v

            elif k == 'imdb_id':
                ret_infoLabels['imdb_id'] = v

            elif k == 'external_ids':
                if 'tvdb_id' in v:
                    ret_infoLabels['tvdb_id'] = v['tvdb_id']
                if 'imdb_id' in v:
                    ret_infoLabels['imdb_id'] = v['imdb_id']

            elif k in ['genres', "genre_ids", "genre"]:
                ret_infoLabels['genre'] = self.get_genres(origen)

            elif k == 'name' or k == 'title':
                ret_infoLabels['title'] = v

            elif k == 'tagline':
                ret_infoLabels['tagline'] = v

            elif k == 'production_companies':
                ret_infoLabels['studio'] = ", ".join(i['name'] for i in v)

            elif k == 'credits_cast' or k == 'season_cast' or k == 'episode_guest_stars':
                dic_aux = dict((name, [character, thumb, order, id]) for (name, character, thumb, order, id) in l_castandrole)
                l_castandrole.extend([(p['name'], p.get('character', '') or p.get('character_name', ''), 'https://image.tmdb.org/t/p/original' + p.get('profile_path', '') if p.get('profile_path', '') else '', p.get('order'), p.get('id')) \
                                      for p in v if 'name' in p and p['name'] not in list(dic_aux.keys())])

            elif k == 'videos':
                if not isinstance(v, list):
                    v = v.get('results', [])
                for i in v:
                    if i.get("site", "") == "YouTube":
                        ret_infoLabels['trailer'] = "plugin://plugin.video.youtube/play/?video_id=" + v[0]["key"]
                        break

            elif k == 'posters':
                ret_infoLabels['posters'] = ['https://image.tmdb.org/t/p/original' + p["file_path"] for p in v]

            elif k == 'fanarts':
                ret_infoLabels['fanarts'] = ['https://image.tmdb.org/t/p/original' + p["file_path"] for p in v]

            elif k == 'belongs_to_collection':
                c = Tmdb.get_collection(self, v.get('id',''))
                for k, v in c.items():
                    ret_infoLabels[k] = v

            elif k == 'production_countries' or k == 'origin_country':
                # support.dbg()
                if isinstance(v, str):
                    l_country = list(set(l_country + v.split(',')))

                elif isinstance(v, list) and len(v) > 0:
                    if isinstance(v[0], str):
                        l_country = list(set(l_country + v))
                    elif isinstance(v[0], dict):
                        # {'iso_3166_1': 'FR', 'name':'France'}
                        for i in v:
                            if 'name' in i:
                                # pais = Tmdb.dic_country.get(i['iso_3166_1'], i['iso_3166_1'])
                                l_country = list(set(l_country + [i['name']]))

            elif k == 'credits_crew' or k == 'episode_crew' or k == 'season_crew':
                for crew in v:
                    if crew['job'].lower() == 'director':
                        # from core.support import dbg;dbg()
                        l_director = list(set(l_director + [crew['name']]))
                        l_director_image += ['https://image.tmdb.org/t/p/original' + crew['profile_path'] if crew['profile_path'] else '']
                        l_director_id += [crew['id']]

                    elif crew['job'].lower() in ('screenplay', 'writer'):
                        l_writer = list(set(l_writer + [crew['name']]))
                        l_writer_image += ['https://image.tmdb.org/t/p/original' + crew['profile_path'] if crew['profile_path'] else '']
                        l_writer_id += [crew['id']]

            elif k == 'created_by':
                for crew in v:
                    l_writer = list(set(l_writer + [crew['name']]))


            elif isinstance(v, str) or isinstance(v, int) or isinstance(v, float):
                ret_infoLabels[k] = v

            else:
                # logger.debug("Atributos no añadidos: " + k +'= '+ str(v))
                pass

        # Sort the lists and convert them to str if necessary
        if l_castandrole:
            ret_infoLabels['castandrole'] = sorted(l_castandrole, key=lambda tup: tup[0])
        if l_country:
            ret_infoLabels['country'] = ', '.join(sorted(l_country))
        if l_director:
            ret_infoLabels['director'] = ', '.join(l_director)
            ret_infoLabels['director_image'] = l_director_image
            ret_infoLabels['director_id'] = l_director_id
        if l_writer:
            ret_infoLabels['writer'] = ', '.join(l_writer)
            ret_infoLabels['writer_image'] = l_writer_image
            ret_infoLabels['writer_id'] = l_writer_id

        return ret_infoLabels

    def get_mpaa(self, result):
        if result.get('id'):
            Mpaaurl = '{}/{}/{}/{}?api_key={}'.format(host, self.search_type, result['id'], 'release_dates' if self.search_type == 'movie' else 'content_ratings', api)
            Mpaas = self.get_json(Mpaaurl).get('results',[])
            for m in Mpaas:
                if m.get('iso_3166_1','').lower() == 'us':
                    result['mpaa'] = m.get('rating', m.get('release_dates', [{}])[0].get('certification'))
                    break
        return result


def get_season_dic(season):
    ret_dic = dict()
    # logger.debug(jsontools.dump(season))
    # Get data for this season

    seasonTitle = season.get("name", '')
    seasonPlot = season.get("overview" , '')
    seasonId = season.get("id", '')
    seasonEpisodes = len(season.get("episodes",[]))
    seasonDate = season.get("air_date", '')
    seasonPoster = season.get('poster_path', '')
    seasonCredits = season.get('credits', {})
    seasonPosters = season.get('images',{}).get('posters',{})
    seasonFanarts = season.get('images',{}).get('backdrops',{})
    seasonTrailers = season.get('videos',{}).get('results',[])

    ret_dic["season_title"] = seasonTitle
    ret_dic["season_plot"] = seasonPlot
    ret_dic["season_id"] = seasonId
    ret_dic["season_episodes_number"] = seasonEpisodes

    if seasonDate:
        date = seasonDate.split("-")
        ret_dic["season_air_date"] = date[2] + "/" + date[1] + "/" + date[0]
    else:
        ret_dic["season_air_date"] = ''
    if seasonPoster:
        ret_dic["season_poster"] = 'https://image.tmdb.org/t/p/original' + seasonPoster
    else:
        ret_dic["season_poster"] = ''

    if seasonPosters:
        ret_dic['season_posters'] = ['https://image.tmdb.org/t/p/original' + p["file_path"] for p in seasonPosters]
    if seasonFanarts:
        ret_dic['season_fanarts'] = ['https://image.tmdb.org/t/p/original' + p["file_path"] for p in seasonFanarts]
    if seasonTrailers:
        ret_dic['season_trailer'] = []
        for i in seasonTrailers:
            if i.get("site", "") == "YouTube":
                ret_dic['season_trailer'] = "plugin://plugin.video.youtube/play/?video_id=" + seasonTrailers[0]["key"]
                break

    dic_aux = seasonCredits if seasonCredits else {}
    ret_dic["season_cast"] = dic_aux.get('cast', [])
    ret_dic["season_crew"] = dic_aux.get('crew', [])
    return ret_dic

def parse_fallback_info(info, fallbackInfo):
    info_dict = {}
    for key, value in info.items():
        if not value:
            value = fallbackInfo[key]
        info_dict[key] = value
    episodes = info_dict['episodes']

    episodes_list = []
    for i, episode in enumerate(episodes):
        episode_dict = {}
        for key, value in episode.items():
            if not value:
                value = fallbackInfo['episodes'][i][key]
            episode_dict[key] = value
        episodes_list.append(episode_dict)

    info_dict['episodes'] = episodes_list
    return info_dict