# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale film in tv
# ------------------------------------------------------------
import re
import time
import hashlib
import datetime
import threading

try:
    import urllib.parse as urllib
except ImportError:
    import urllib

from core import httptools, scrapertools, support, tmdb, filetools
from core.item import Item
from platformcode import config, platformtools, logger

try:
    from concurrent import futures
except ImportError:
    from concurrent_py2 import futures

from specials.globalsearch import set_workers

host = "https://www.superguidatv.it"

RE_CARD_SPLIT   = re.compile(r'(?=<div class="sgtv-group sgtv-flex sgtv-flex-col sgtv-rounded-md sgtv-border sgtv-border-neutral-300 sgtv-bg-stone-100 sgtv-shadow-item")')
RE_HR_SPLIT     = re.compile(r'<hr class="sgtv-ml-2[^"]*"[^>]*>')
RE_CHANNEL      = re.compile(r'<img alt="([^"]*)"[^>]*src="([^"]*channels/\d+/logo[^"]*)"')
RE_NOW_TIME     = re.compile(r'<p class="sgtv-text-lg sgtv-font-bold">([^<]+)</p>')
RE_NOW_TITLE    = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-text-lg[^"]*">([^<]+)</p>')
RE_NOW_TYPE     = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-border-l-8[^"]*">([^<]+)</p>')
RE_FILM_ORARIO  = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-leading-6">([^<]+)</p>')
RE_FILM_TITLE   = re.compile(r'<a href="/dettaglio-film/[^"]+"[^>]*class="[^"]*sgtv-block[^"]*"[^>]*>\s*([^<]+)\s*</a>')
RE_FILM_GENRE   = re.compile(r'<p class="sgtv-row-span-1 sgtv-truncate">([^<]+)</p>')
RE_FILM_ANNO    = re.compile(r'<p class="sgtv-h-1/2 sgtv-break-words sgtv-leading-10">([^<]+)</p>')
RE_YEAR         = re.compile(r'(\d{4})')
RE_DETAIL_LINK  = re.compile(r'<a href="(/dettaglio-film/[^"]+)"')
RE_DETAIL_YEAR  = re.compile(r'<p class="sgtv-truncate">(?:[A-Z]{2}(?:,\s*[A-Z]{2})*)?\s*(\d{4})</p>')
RE_WHITESPACE   = re.compile(r'\s{2,}')
RE_TIPO_DURATA  = re.compile(r'\s*\(da\s*\d+\'?\)')

try:
    _HTML_STRIP = str.maketrans('', '', '\n\t\r')
    def clean_html(html):
        if not html:
            return ""
        return RE_WHITESPACE.sub(" ", html.translate(_HTML_STRIP))
except AttributeError:
    def clean_html(html):
        if not html:
            return ""
        return RE_WHITESPACE.sub(" ", html.replace("\n", "").replace("\t", "").replace("\r", ""))

_MAX_CACHE_SIZE = 150
_CACHE_DURATION = 21600
_TMDB_BLACKLIST = frozenset(['Notizie', 'Sport', 'Rubrica', 'Musica'])
_years_lock     = threading.Lock()
_cache_lock     = threading.Lock()

_MAIN_MENU_ITEMS = [
    ("film1", "Film in TV",                "/film-in-tv/",                         "now_on_tv"),
    ("film3", "Sky Intrattenimento",        "/film-in-tv/oggi/sky-intrattenimento/","now_on_tv"),
    ("film4", "Sky Cinema",                "/film-in-tv/oggi/sky-cinema/",          "now_on_tv"),
    ("film6", "Sky Doc e Lifestyle",        "/film-in-tv/oggi/sky-doc-e-lifestyle/","now_on_tv"),
    ("film7", "Sky Bambini",               "/film-in-tv/oggi/sky-bambini/",         "now_on_tv"),
    ("now1",  "Adesso in onda",            "/ora-in-onda/",                         "now_on_misc"),
    ("now3",  "Sky Intrattenimento (ora)", "/ora-in-onda/sky-intrattenimento/",      "now_on_misc"),
    ("now4",  "Sky Cinema (ora)",          "/ora-in-onda/sky-cinema/",              "now_on_misc"),
    ("now5",  "Sky Doc e Lifestyle (ora)", "/ora-in-onda/sky-doc-e-lifestyle/",     "now_on_misc"),
    ("now6",  "Sky Bambini (ora)",         "/ora-in-onda/sky-bambini/",             "now_on_misc"),
    ("now7",  "RSI (ora)",                 "/ora-in-onda/rsi/",                     "now_on_misc"),
]

_FILM_SECTIONS_DATABASE = [
    ("/film-in-tv/oggi/sky-intrattenimento/", "Sky Intrattenimento"),
    ("/film-in-tv/oggi/sky-cinema/",          "Sky Cinema"),
    ("/film-in-tv/oggi/sky-doc-e-lifestyle/", "Sky Doc e Lifestyle"),
    ("/film-in-tv/oggi/sky-bambini/",         "Sky Bambini"),
]


def _decode(text):
    return scrapertools.decodeHtmlentities(text).strip()


def get_higher_res_logo(logo_url):
    return logo_url.replace("?width=120", "?width=480") if logo_url else ""


class FilmCache:
    def __init__(self):
        self._cache  = None
        self._expiry = None
        self._hash   = None

    def _next_expiry(self):
        now    = datetime.datetime.now()
        expiry = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= expiry:
            expiry += datetime.timedelta(days=1)
        return expiry.timestamp()

    def get(self, current_hash=None):
        with _cache_lock:
            if self._cache is None or self._expiry is None or time.time() >= self._expiry:
                return None
            if current_hash is not None and current_hash != self._hash:
                return None
            return self._cache

    def set(self, value, current_hash=None):
        with _cache_lock:
            self._cache  = value
            self._expiry = self._next_expiry()
            self._hash   = current_hash


_film_cache       = FilmCache()
_persistent_years = {}


def mainlist(item):
    itemlist = [
        Item(title=support.typo('Canali live', 'bold'), channel=item.channel, action='live',
             thumbnail=support.thumb('tvshow_on_the_air')),
    ]
    for key, default, path, action in _MAIN_MENU_ITEMS:
        itemlist.append(Item(
            channel=item.channel,
            title=config.get_setting(key, channel="filmontv") or default,
            action=action,
            url=host + path,
            thumbnail=item.thumbnail
        ))
    itemlist.append(Item(
        channel=item.channel, title="Personalizza Oggi in TV",
        action="server_config", config="filmontv",
        folder=False, thumbnail=item.thumbnail
    ))
    return itemlist


def server_config(item):
    return platformtools.show_channel_settings(
        channelpath=filetools.join(config.get_runtime_path(), "specials", item.config)
    )


def normalize_title_for_tmdb(title):
    return RE_WHITESPACE.sub(' ', scrapertools.decodeHtmlentities(title).strip())


def get_year_from_detail_page(detail_url):
    now = time.time()

    with _years_lock:
        if _persistent_years:
            for url in [u for u, d in list(_persistent_years.items()) if now >= d['expiry']]:
                _persistent_years.pop(url, None)
        if detail_url in _persistent_years:
            return _persistent_years[detail_url]['year']

    try:
        full_url = host + detail_url if detail_url.startswith('/') else detail_url
        data     = httptools.downloadpage(full_url, alfa_s=True).data
        match    = RE_DETAIL_YEAR.search(data)
        if not match:
            return ""
        year = match.group(1)

        with _years_lock:
            if len(_persistent_years) >= _MAX_CACHE_SIZE:
                for url in sorted(_persistent_years, key=lambda k: _persistent_years[k]['expiry'])[:_MAX_CACHE_SIZE // 5]:
                    _persistent_years.pop(url, None)
            _persistent_years[detail_url] = {'year': year, 'expiry': now + _CACHE_DURATION}

        return year
    except Exception:
        return ""


def create_search_item(title, search_text, content_type, thumbnail="", year="", genre="", plot="", event_type=""):
    use_new_search = config.get_setting('new_search')
    clean_text     = normalize_title_for_tmdb(search_text).replace("+", " ").strip()
    is_movie       = content_type == 'movie'
    mode           = 'movie' if is_movie else 'tvshow'

    infoLabels = {'year': year, 'genre': genre, 'title': clean_text, 'plot': plot}
    if not is_movie:
        infoLabels['tvshowtitle'] = clean_text

    if use_new_search:
        new_item = Item(channel='globalsearch', action='Search', text=clean_text, title=title,
                        thumbnail=thumbnail, fanart=thumbnail, mode=mode, type=mode,
                        contentType=content_type, infoLabels=infoLabels, folder=False)
        if is_movie:
            new_item.contentTitle = clean_text
        else:
            new_item.contentSerieName = clean_text
    else:
        new_item = Item(channel='search', action="new_search",
                        extra=urllib.quote_plus(clean_text) + '{}' + mode,
                        title=title, fulltitle=clean_text, mode='all', search_text=clean_text,
                        url="", thumbnail=thumbnail, contentTitle=clean_text, contentYear=year,
                        contentType=content_type, infoLabels=infoLabels, folder=True)

    new_item.event_type = event_type
    return new_item


def _split_cards(data):
    return [p for p in RE_CARD_SPLIT.split(data) if 'sgtv-shadow-item' in p]


def _parse_film_card(card):
    title_match = RE_FILM_TITLE.search(card)
    if not title_match:
        return None

    channel_match  = RE_CHANNEL.search(card)
    orario_matches = RE_FILM_ORARIO.findall(card)
    genre_matches  = RE_FILM_GENRE.findall(card)
    anno_match     = RE_FILM_ANNO.search(card)

    anno_paese   = _decode(anno_match.group(1)) if anno_match else ""
    year_match   = RE_YEAR.search(anno_paese)
    channel_logo = channel_match.group(2) if channel_match else ""

    return {
        'title':     _decode(title_match.group(1)),
        'channel':   _decode(channel_match.group(1)) if channel_match else "",
        'orario':    _decode(orario_matches[0]) if orario_matches else "",
        'genre':     _decode(genre_matches[1] if len(genre_matches) >= 2 else genre_matches[0]) if genre_matches else "",
        'thumbnail': get_higher_res_logo(channel_logo),
        'year':      year_match.group(1) if year_match else ""
    }


def _parse_now_card(card):
    channel_match = RE_CHANNEL.search(card)
    first_block   = RE_HR_SPLIT.split(card, maxsplit=1)[0]
    time_match    = RE_NOW_TIME.search(first_block)
    title_match   = RE_NOW_TITLE.search(first_block)
    type_match    = RE_NOW_TYPE.search(first_block)

    if not (time_match and title_match and type_match):
        return None

    return {
        'channel':   _decode(channel_match.group(1)) if channel_match else "",
        'time':      time_match.group(1).strip(),
        'title':     _decode(title_match.group(1)),
        'type':      _decode(type_match.group(1)),
        'thumbnail': get_higher_res_logo(channel_match.group(2) if channel_match else ""),
        'card':      card
    }


def _parse_cards_into_dict(cards):
    result = {}
    for card in cards:
        try:
            parsed = _parse_film_card(card)
            if parsed:
                result[parsed['title'].lower()] = {
                    'year': parsed['year'], 'genre': parsed['genre'], 'thumbnail': parsed['thumbnail']
                }
        except Exception:
            continue
    return result


def get_films_database():
    first_url = "%s/film-in-tv/" % host

    try:
        first_data = clean_html(httptools.downloadpage(first_url, alfa_s=True).data)
    except Exception as e:
        logger.error("[FILMONTV] Errore fetch prima pagina: %s" % e)
        return _film_cache.get() or {}

    raw          = first_data if isinstance(first_data, bytes) else first_data.encode('utf-8', errors='replace')
    current_hash = hashlib.md5(raw).hexdigest()
    cached       = _film_cache.get(current_hash=current_hash)
    if cached is not None:
        return cached

    films_dict = {}

    with futures.ThreadPoolExecutor(max_workers=set_workers()) as executor:
        future_to_section = {
            executor.submit(httptools.downloadpage, host + path, alfa_s=True): name
            for path, name in _FILM_SECTIONS_DATABASE
        }
        for future in futures.as_completed(future_to_section):
            section_name = future_to_section[future]
            try:
                films_dict.update(_parse_cards_into_dict(_split_cards(clean_html(future.result().data))))
            except Exception as e:
                logger.error("[FILMONTV] Errore sezione %s: %s" % (section_name, e))

    films_dict.update(_parse_cards_into_dict(_split_cards(first_data)))

    if not films_dict:
        return _film_cache.get() or {}

    _film_cache.set(films_dict, current_hash=current_hash)
    return films_dict


def _should_skip_tmdb(title_l, channel_l, genre):
    return (
        any(black in genre for black in _TMDB_BLACKLIST) or
        "porta a porta" in title_l or
        ("qvc" in channel_l and "replica" in title_l) or
        ("donnatv" in channel_l and "l'argonauta" in title_l) or
        ("rai 1" in channel_l and "l'eredità" in title_l) or
        ("focus" in channel_l and "dall'alba al tramonto" in title_l)
    )


def _build_search_item(d, year):
    item = create_search_item(
        title=d['formatted_title'],
        search_text=d['scrapedtitle'],
        content_type=d['content_type'],
        thumbnail=d['full_thumbnail'],
        year=year,
        genre=d['genre'],
        event_type=d['scrapedtype']
    )
    item.fanart = d['full_thumbnail']
    return item


def _apply_tmdb_plot(items_for_tmdb):
    tmdb.set_infoLabels_itemlist(items_for_tmdb, seekTmdb=True)
    for it in items_for_tmdb:
        if not (hasattr(it, 'event_type') and it.event_type):
            continue
        tipo         = "[COLOR gray][B]Tipo:[/B][/COLOR] %s" % it.event_type
        current_plot = it.infoLabels.get('plot', '').strip()
        if not current_plot:
            it.infoLabels['plot'] = tipo
        elif tipo not in current_plot:
            it.infoLabels['plot'] = "%s\n\n%s" % (tipo, current_plot)


def now_on_misc(item):
    itemlist       = []
    items_for_tmdb = []
    missing_years  = []

    films_db = get_films_database()
    cards    = _split_cards(clean_html(httptools.downloadpage(item.url).data))

    if not cards:
        return itemlist

    for card in cards:
        try:
            parsed = _parse_now_card(card)
            if not parsed:
                continue

            channel        = parsed['channel']
            scrapedtime    = parsed['time']
            title          = parsed['title']
            scrapedtype    = parsed['type']
            full_thumbnail = parsed['thumbnail']
            genre          = RE_TIPO_DURATA.sub('', scrapedtype).strip()
            formatted      = "[B]%s[/B] - %s - %s" % (title, channel, scrapedtime)

            title_l   = title.lower()
            channel_l = channel.lower()
            if _should_skip_tmdb(title_l, channel_l, genre):
                itemlist.append(Item(
                    channel=item.channel, title=formatted,
                    thumbnail=full_thumbnail, fanart=full_thumbnail, folder=False,
                    infoLabels={'title': title, 'plot': "[COLOR gray][B]Tipo:[/B][/COLOR] %s" % scrapedtype}
                ))
                continue

            content_type = 'movie' if genre == 'Film' else 'tvshow'
            year         = ""

            if content_type == 'movie':
                db_entry = films_db.get(title_l)
                if db_entry:
                    year           = db_entry.get('year', "")
                    genre          = db_entry.get('genre') or genre
                    full_thumbnail = db_entry.get('thumbnail') or full_thumbnail
                else:
                    detail_match = RE_DETAIL_LINK.search(card)
                    if detail_match:
                        idx = len(itemlist)
                        itemlist.append(None)
                        missing_years.append({
                            'detail_url': detail_match.group(1),
                            'idx': idx,
                            'data': {
                                'scrapedtitle':    title,
                                'scrapedtype':     scrapedtype,
                                'full_thumbnail':  full_thumbnail,
                                'genre':           genre,
                                'content_type':    content_type,
                                'formatted_title': formatted
                            }
                        })
                        continue

            search_item = _build_search_item(
                {'scrapedtitle': title, 'scrapedtype': scrapedtype, 'full_thumbnail': full_thumbnail,
                 'genre': genre, 'content_type': content_type, 'formatted_title': formatted},
                year
            )
            itemlist.append(search_item)
            items_for_tmdb.append(search_item)

        except Exception:
            continue

    if missing_years:
        with futures.ThreadPoolExecutor(max_workers=set_workers()) as executor:
            future_to_missing = {
                executor.submit(get_year_from_detail_page, m['detail_url']): m
                for m in missing_years
            }
            for future in futures.as_completed(future_to_missing):
                m = future_to_missing[future]
                try:
                    year = future.result()
                except Exception:
                    year = ""
                search_item = _build_search_item(m['data'], year)
                itemlist[m['idx']] = search_item
                items_for_tmdb.append(search_item)

        itemlist = [it for it in itemlist if it is not None]

    if items_for_tmdb:
        _apply_tmdb_plot(items_for_tmdb)

    return itemlist


def now_on_tv(item):
    itemlist = []
    cards    = _split_cards(clean_html(httptools.downloadpage(item.url).data))

    for card in cards:
        try:
            parsed = _parse_film_card(card)
            if not parsed:
                continue
            itemlist.append(create_search_item(
                title="[B]%s[/B] - %s - %s" % (parsed['title'], parsed['channel'], parsed['orario']),
                search_text=parsed['title'],
                content_type='movie',
                thumbnail=parsed['thumbnail'],
                year=parsed['year'],
                genre=parsed['genre']
            ))
        except Exception:
            continue

    if itemlist:
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    return itemlist


def Search(item):
    from specials import globalsearch
    return globalsearch.Search(item)


def new_search(item):
    from specials import search as search_module
    return search_module.new_search(item)


def live(item):
    import channelselector

    channels      = channelselector.filterchannels('live')
    channels_dict = {}

    with futures.ThreadPoolExecutor(max_workers=set_workers()) as executor:
        for future in futures.as_completed({executor.submit(load_live, ch.channel): ch for ch in channels}):
            result = future.result()
            if result:
                channels_dict[result[0]] = result[1]

    channel_list = ['raiplay', 'mediasetplay', 'la7', 'discoveryplus']
    for ch in channels:
        if ch.channel not in channel_list:
            channel_list.append(ch.channel)

    itemlist = []
    for ch in channel_list:
        itemlist += channels_dict.get(ch, [])

    itemlist.sort(key=lambda it: support.channels_order.get(it.fulltitle, 1000))
    return itemlist


def load_live(channel_name):
    try:
        channel  = __import__('channels.%s' % channel_name, None, None, ['channels.%s' % channel_name])
        itemlist = channel.live(channel.mainlist(Item())[0])
    except Exception:
        itemlist = []
    return channel_name, itemlist