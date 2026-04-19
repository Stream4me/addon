# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale film in tv
# ------------------------------------------------------------
import re
import time
import hashlib
import datetime
try:
    import urllib.parse as urllib
except ImportError:
    import urllib
from core import httptools, scrapertools, support, tmdb, filetools
from core.item import Item
from platformcode import config, platformtools, logger

host = "https://www.superguidatv.it"
TIMEOUT_TOTAL = 30

RE_CARD_SPLIT = re.compile(
    r'(?=<div class="sgtv-group sgtv-flex sgtv-flex-col sgtv-rounded-md sgtv-border sgtv-border-neutral-300 sgtv-bg-stone-100 sgtv-shadow-item")'
)
RE_FIRST_PROGRAM_SPLIT = re.compile(r'<hr class="sgtv-ml-2[^"]*"[^>]*>')
RE_CHANNEL = re.compile(r'<img alt="([^"]*)"[^>]*src="([^"]*channels/\d+/logo[^"]*)"')
RE_NOW_TIME = re.compile(r'<p class="sgtv-text-lg sgtv-font-bold">([^<]+)</p>')
RE_NOW_TITLE = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-text-lg[^"]*">([^<]+)</p>')
RE_NOW_TYPE = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-border-l-8[^"]*">([^<]+)</p>')
RE_NOW_BACKDROP = re.compile(r'src="(https://api\.superguidatv\.it/v1/(?:programs|series|movies)/\d+/backdrops/\d+\?[^"]*)"')
RE_FILM_ORARIO = re.compile(r'<p class="sgtv-max-w-full sgtv-truncate sgtv-leading-6">([^<]+)</p>')
RE_FILM_TITLE = re.compile(r'<a href="/dettaglio-film/[^"]+"[^>]*class="[^"]*sgtv-block[^"]*"[^>]*>\s*([^<]+)\s*</a>')
RE_FILM_GENRE = re.compile(r'<p class="sgtv-row-span-1 sgtv-truncate">([^<]+)</p>')
RE_FILM_COVER = re.compile(r'src="(https://api\.superguidatv\.it/v1/movies/\d+/cover\?[^"]*)"')
RE_FILM_ANNO = re.compile(r'<p class="sgtv-h-1/2 sgtv-break-words sgtv-leading-10">([^<]+)</p>')
RE_YEAR = re.compile(r'(\d{4})')
RE_DETAIL_LINK = re.compile(r'<a href="(/dettaglio-film/[^"]+)"')
RE_DETAIL_YEAR = re.compile(r'<p class="sgtv-truncate">(?:[A-Z]{2}(?:,\s*[A-Z]{2})?\s*)?(\d{4})</p>')

_MAX_CACHE_SIZE = 150
_CACHE_DURATION = 21600


def clean_html(html):
    if not html:
        return ""
    html = html.replace("\n", "").replace("\t", "").replace("\r", "")
    html = re.sub(r"\s{2,}", " ", html)
    return html


class FilmCache:
    def __init__(self):
        self._cache = None
        self._expiry = None
        self._hash = None

    def _next_expiry(self):
        now = datetime.datetime.now()
        expiry = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= expiry:
            expiry += datetime.timedelta(days=1)
        return expiry.timestamp()

    def get(self, current_hash=None):
        if self._cache is None or self._expiry is None or time.time() >= self._expiry:
            return None
        if current_hash is not None and current_hash != self._hash:
            return None
        return self._cache

    def set(self, value, current_hash=None):
        self._cache = value
        self._expiry = self._next_expiry()
        self._hash = current_hash


_film_cache = FilmCache()
_persistent_years = {}


def mainlist(item):
    return [
        Item(title=support.typo('Canali live', 'bold'), channel=item.channel, action='live',
             thumbnail=support.thumb('tvshow_on_the_air')),
        Item(channel=item.channel, title=config.get_setting("film1", channel="filmontv"), action="now_on_tv",
             url="%s/film-in-tv/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("film3", channel="filmontv"), action="now_on_tv",
             url="%s/film-in-tv/oggi/sky-intrattenimento/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("film4", channel="filmontv"), action="now_on_tv",
             url="%s/film-in-tv/oggi/sky-cinema/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("film6", channel="filmontv"), action="now_on_tv",
             url="%s/film-in-tv/oggi/sky-doc-e-lifestyle/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("film7", channel="filmontv"), action="now_on_tv",
             url="%s/film-in-tv/oggi/sky-bambini/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now1", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now3", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/sky-intrattenimento/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now4", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/sky-cinema/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now5", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/sky-doc-e-lifestyle/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now6", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/sky-bambini/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title=config.get_setting("now7", channel="filmontv"), action="now_on_misc",
             url="%s/ora-in-onda/rsi/" % host, thumbnail=item.thumbnail),
        Item(channel=item.channel, title="Personalizza Oggi in TV", action="server_config", config="filmontv",
             folder=False, thumbnail=item.thumbnail)
    ]


def server_config(item):
    return platformtools.show_channel_settings(
        channelpath=filetools.join(config.get_runtime_path(), "specials", item.config)
    )


def normalize_title_for_tmdb(title):
    title = scrapertools.decodeHtmlentities(title).strip()
    title = re.sub(r'\s+', ' ', title)
    return title


def get_year_from_detail_page(detail_url):
    global _persistent_years
    now = time.time()
    
    expired = [url for url, data in _persistent_years.items() if now >= data['expiry']]
    for url in expired:
        del _persistent_years[url]
    
    if detail_url in _persistent_years:
        return _persistent_years[detail_url]['year']
    
    try:
        full_url = host + detail_url if detail_url.startswith('/') else detail_url
        data = httptools.downloadpage(full_url).data
        match = RE_DETAIL_YEAR.search(data)
        if not match:
            return ""
        year = match.group(1)
        
        if len(_persistent_years) >= _MAX_CACHE_SIZE:
            sorted_urls = sorted(_persistent_years.keys(), key=lambda k: _persistent_years[k]['expiry'])
            for url in sorted_urls[:_MAX_CACHE_SIZE // 5]:
                del _persistent_years[url]
        
        _persistent_years[detail_url] = {'year': year, 'expiry': now + _CACHE_DURATION}
        return year
    except Exception:
        pass
    return ""


def create_search_item(title, search_text, content_type, thumbnail="", year="", genre="", plot="", event_type=""):
    use_new_search = config.get_setting('new_search')
    clean_text = normalize_title_for_tmdb(search_text).replace("+", " ").strip()

    infoLabels = {'year': year if year else "", 'genre': genre if genre else "", 'title': clean_text, 'plot': plot if plot else ""}
    if content_type == 'tvshow':
        infoLabels['tvshowtitle'] = clean_text

    if use_new_search:
        new_item = Item(channel='globalsearch', action='Search', text=clean_text, title=title, thumbnail=thumbnail,
                        fanart=thumbnail, mode='movie' if content_type == 'movie' else 'tvshow',
                        type='movie' if content_type == 'movie' else 'tvshow', contentType=content_type,
                        infoLabels=infoLabels, folder=False)
        if content_type == 'movie':
            new_item.contentTitle = clean_text
        else:
            new_item.contentSerieName = clean_text
    else:
        quote_fn = urllib.quote_plus
        extra_type = 'movie' if content_type == 'movie' else 'tvshow'
        new_item = Item(channel='search', action="new_search", extra=quote_fn(clean_text) + '{}' + extra_type,
                        title=title, fulltitle=clean_text, mode='all', search_text=clean_text, url="",
                        thumbnail=thumbnail, contentTitle=clean_text, contentYear=year if year else "",
                        contentType=content_type, infoLabels=infoLabels, folder=True)

    new_item.event_type = event_type
    return new_item


def _split_cards(data):
    return [p for p in RE_CARD_SPLIT.split(data) if 'sgtv-shadow-item' in p]


def _split_cards_films(data):
    cards = []
    start_pattern = re.compile(r'<div class="sgtv-group sgtv-flex sgtv-flex-col sgtv-rounded-md[^>]*>')
    pos = 0
    
    while True:
        match = start_pattern.search(data, pos)
        if not match:
            break
        
        start_pos = match.start()
        div_count = 1
        current_pos = match.end()
        
        while div_count > 0 and current_pos < len(data):
            next_open = data.find('<div', current_pos)
            next_close = data.find('</div>', current_pos)
            
            if next_close == -1:
                break
            
            if next_open != -1 and next_open < next_close:
                div_count += 1
                current_pos = next_open + 4
            else:
                div_count -= 1
                current_pos = next_close + 6
        
        if div_count == 0:
            card = data[start_pos:current_pos]
            if 'dettaglio-film' in card and 'sgtv-shadow-item' in card:
                cards.append(card)
        
        pos = current_pos if current_pos > start_pos else start_pos + 1
    
    return cards


def _parse_film_card(card):
    title_match = RE_FILM_TITLE.search(card)
    if not title_match:
        return None

    channel_match = RE_CHANNEL.search(card)
    orario_matches = RE_FILM_ORARIO.findall(card)
    genre_matches = RE_FILM_GENRE.findall(card)
    cover_match = RE_FILM_COVER.search(card)
    anno_match = RE_FILM_ANNO.search(card)

    anno_paese = scrapertools.decodeHtmlentities(anno_match.group(1)).strip() if anno_match else ""
    year_match = RE_YEAR.search(anno_paese)
    channel_logo = channel_match.group(2) if channel_match else ""
    thumbnail = cover_match.group(1).replace("?width=320", "?width=480") if cover_match else channel_logo

    return {
        'title': scrapertools.decodeHtmlentities(title_match.group(1)).strip(),
        'channel': scrapertools.decodeHtmlentities(channel_match.group(1)).strip() if channel_match else "",
        'orario': scrapertools.decodeHtmlentities(orario_matches[0]).strip() if orario_matches else "",
        'genre': scrapertools.decodeHtmlentities(genre_matches[1]).strip() if len(genre_matches) >= 2 else "",
        'thumbnail': thumbnail,
        'year': year_match.group(1) if year_match else ""
    }


def _parse_now_card(card):
    channel_match = RE_CHANNEL.search(card)
    scrapedchannel = scrapertools.decodeHtmlentities(channel_match.group(1)).strip() if channel_match else ""
    channel_logo = channel_match.group(2) if channel_match else ""
    first_block = RE_FIRST_PROGRAM_SPLIT.split(card, maxsplit=1)[0]
    time_match = RE_NOW_TIME.search(first_block)
    title_match = RE_NOW_TITLE.search(first_block)
    type_match = RE_NOW_TYPE.search(first_block)

    if not (time_match and title_match and type_match):
        return None

    backdrop_match = RE_NOW_BACKDROP.search(first_block)

    return {
        'channel': scrapedchannel,
        'time': time_match.group(1).strip(),
        'title': scrapertools.decodeHtmlentities(title_match.group(1)).strip(),
        'type': scrapertools.decodeHtmlentities(type_match.group(1)).strip(),
        'thumbnail': backdrop_match.group(1) if backdrop_match else channel_logo,
        'card': card
    }


def get_films_database():
    first_url = "%s/film-in-tv/" % host

    try:
        first_data = httptools.downloadpage(first_url, timeout=TIMEOUT_TOTAL).data
        first_data = clean_html(first_data)
    except Exception as e:
        logger.error("[FILMONTV] Errore fetch prima pagina: %s" % e)
        return _film_cache.get() or {}

    raw = first_data if isinstance(first_data, bytes) else first_data.encode('utf-8', errors='replace')
    current_hash = hashlib.md5(raw).hexdigest()
    cached = _film_cache.get(current_hash=current_hash)
    if cached is not None:
        return cached

    films_dict = {}
    urls_to_scrape = {
        'Film in TV': (first_url, first_data),
        'Sky Intrattenimento': ("%s/film-in-tv/oggi/sky-intrattenimento/" % host, None),
        'Sky Cinema': ("%s/film-in-tv/oggi/sky-cinema/" % host, None),
        'Sky Doc e Lifestyle': ("%s/film-in-tv/oggi/sky-doc-e-lifestyle/" % host, None),
        'Sky Bambini': ("%s/film-in-tv/oggi/sky-bambini/" % host, None),
    }

    for section_name, (url, preloaded) in urls_to_scrape.items():
        try:
            if preloaded is not None:
                data = preloaded
            else:
                data = httptools.downloadpage(url, timeout=TIMEOUT_TOTAL).data
                data = clean_html(data)
            
            cards = _split_cards(data)
            if not cards:
                continue
            for card in cards:
                try:
                    parsed = _parse_film_card(card)
                    if not parsed:
                        continue
                    films_dict[parsed['title'].lower()] = {
                        'year': parsed['year'],
                        'genre': parsed['genre'],
                        'thumbnail': parsed['thumbnail']
                    }
                except Exception:
                    continue
        except Exception:
            continue

    if not films_dict:
        return _film_cache.get() or {}

    _film_cache.set(films_dict, current_hash=current_hash)
    return films_dict


def now_on_misc(item):
    itemlist = []
    items_for_tmdb = []
    tmdb_blacklist = ['Notizie', 'Sport', 'Rubrica', 'Musica']

    films_db = get_films_database()
    data = httptools.downloadpage(item.url, timeout=TIMEOUT_TOTAL).data
    data = clean_html(data)
    cards = _split_cards(data)

    if not cards:
        return itemlist

    for card in cards:
        try:
            parsed = _parse_now_card(card)
            if not parsed:
                continue

            scrapedchannel = parsed['channel']
            scrapedtime = parsed['time']
            scrapedtitle = parsed['title']
            scrapedtype = parsed['type']
            full_thumbnail = parsed['thumbnail']
            genre = re.sub(r'\s*\(da\s*\d+\'?\)', '', scrapedtype).strip()

            skip_tmdb = (
                any(black in genre for black in tmdb_blacklist) or
                ("rai 1" in scrapedchannel.lower() and "porta a porta" in scrapedtitle.lower()) or
                ("qvc" in scrapedchannel.lower() and "replica" in scrapedtitle.lower()) or
                ("donnatv" in scrapedchannel.lower() and "l'argonauta" in scrapedtitle.lower()) or
                ("rai 1" in scrapedchannel.lower() and "l'eredità" in scrapedtitle.lower()) or
                ("focus" in scrapedchannel.lower() and "dall'alba al tramonto" in scrapedtitle.lower())
            )

            formatted_title = "[B]%s[/B] - %s - %s" % (scrapedtitle, scrapedchannel, scrapedtime)

            if skip_tmdb:
                itemlist.append(Item(channel=item.channel, title=formatted_title, thumbnail=full_thumbnail,
                                     fanart=full_thumbnail, folder=False,
                                     infoLabels={'title': scrapedtitle, 'plot': "[COLOR gray][B]Tipo:[/B][/COLOR] %s" % scrapedtype}))
            else:
                content_type = 'movie' if genre == 'Film' else 'tvshow'
                year = ""
                
                if content_type == 'movie':
                    title_lower = scrapedtitle.lower()
                    if title_lower in films_db:
                        year = films_db[title_lower].get('year', "")
                        if films_db[title_lower].get('genre'):
                            genre = films_db[title_lower]['genre']
                        if films_db[title_lower].get('thumbnail'):
                            full_thumbnail = films_db[title_lower]['thumbnail']
                    else:
                        detail_match = RE_DETAIL_LINK.search(card)
                        if detail_match:
                            year = get_year_from_detail_page(detail_match.group(1))

                search_item = create_search_item(title=formatted_title, search_text=scrapedtitle,
                                                 content_type=content_type, thumbnail=full_thumbnail, year=year,
                                                 genre=genre, event_type=scrapedtype)
                search_item.fanart = full_thumbnail
                itemlist.append(search_item)
                items_for_tmdb.append(search_item)
        except Exception:
            continue

    if items_for_tmdb:
        tmdb.set_infoLabels_itemlist(items_for_tmdb, seekTmdb=True)
        for it in items_for_tmdb:
            if hasattr(it, 'event_type') and it.event_type:
                tipo = "[COLOR gray][B]Tipo:[/B][/COLOR] %s" % it.event_type
                current_plot = it.infoLabels.get('plot', '').strip()
                if not current_plot:
                    it.infoLabels['plot'] = tipo
                elif tipo not in current_plot:
                    it.infoLabels['plot'] = "%s\n\n%s" % (tipo, current_plot)

    return itemlist


def now_on_tv(item):
    itemlist = []
    data = httptools.downloadpage(item.url, timeout=TIMEOUT_TOTAL).data
    data = clean_html(data)
    cards = _split_cards_films(data)

    if not cards:
        return itemlist

    for card in cards:
        try:
            parsed = _parse_film_card(card)
            if not parsed:
                continue
            itemlist.append(create_search_item(
                title="[B]%s[/B] - %s - %s" % (parsed['title'], parsed['channel'], parsed['orario']),
                search_text=parsed['title'], content_type='movie', thumbnail=parsed['thumbnail'],
                year=parsed['year'], genre=parsed['genre']))
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
    import sys
    import channelselector
    if sys.version_info[0] >= 3:
        from concurrent import futures
    else:
        from concurrent_py2 import futures

    itemlist = []
    channels_dict = {}
    channels = channelselector.filterchannels('live')

    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(load_live, ch.channel) for ch in channels]
        for res in futures.as_completed(itlist):
            if res.result():
                channel_name, ch_itemlist = res.result()
                channels_dict[channel_name] = ch_itemlist

    channel_list = ['raiplay', 'mediasetplay', 'la7', 'discoveryplus']
    for ch in channels:
        if ch.channel not in channel_list:
            channel_list.append(ch.channel)
    for ch in channel_list:
        itemlist += channels_dict.get(ch, [])

    itemlist.sort(key=lambda it: support.channels_order.get(it.fulltitle, 1000))
    return itemlist


def load_live(channel_name):
    try:
        channel = __import__('channels.%s' % channel_name, None, None, ['channels.%s' % channel_name])
        itemlist = channel.live(channel.mainlist(Item())[0])
    except Exception:
        itemlist = []
    return channel_name, itemlist