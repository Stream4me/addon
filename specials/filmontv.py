# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale film in tv
# ------------------------------------------------------------
import re
try:
    import urllib.parse as urllib
except ImportError:
    import urllib
from core import httptools, scrapertools, support, tmdb, filetools
from core.item import Item
from platformcode import config, platformtools, logger

host = "https://www.superguidatv.it"
TIMEOUT_TOTAL = 60

RE_BACKDROP = re.compile(r'<img[^>]*class="sgtvonair_backdrop"[^>]*src="([^"]+)"')


def mainlist(item):
    itemlist = [
        Item(title=support.typo('Canali live', 'bold'),
             channel=item.channel,
             action='live',
             thumbnail=support.thumb('tvshow_on_the_air')),
        Item(channel=item.channel,
             title=config.get_setting("film1", channel="filmontv"),
             action="now_on_tv",
             url=f"{host}/film-in-tv/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("film3", channel="filmontv"),
             action="now_on_tv",
             url=f"{host}/film-in-tv/oggi/sky-intrattenimento/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("film4", channel="filmontv"),
             action="now_on_tv",
             url=f"{host}/film-in-tv/oggi/sky-cinema/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("film6", channel="filmontv"),
             action="now_on_tv",
             url=f"{host}/film-in-tv/oggi/sky-doc-e-lifestyle/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("film7", channel="filmontv"),
             action="now_on_tv",
             url=f"{host}/film-in-tv/oggi/sky-bambini/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now1", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now3", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/sky-intrattenimento/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now4", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/sky-cinema/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now5", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/sky-doc-e-lifestyle/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now6", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/sky-bambini/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title=config.get_setting("now7", channel="filmontv"),
             action="now_on_misc",
             url=f"{host}/ora-in-onda/rsi/",
             thumbnail=item.thumbnail),
        Item(channel=item.channel,
             title="Personalizza Oggi in TV",
             action="server_config",
             config="filmontv",
             folder=False,
             thumbnail=item.thumbnail)
    ]
    return itemlist


def server_config(item):
    return platformtools.show_channel_settings(
        channelpath=filetools.join(config.get_runtime_path(), "specials", item.config)
    )


def normalize_title_for_tmdb(title):
    title = scrapertools.decodeHtmlentities(title).strip()
    
    if re.match(r'^\d+$', title):
        return title
    
    if re.match(r'^\d{4}\s', title):
        return title
    
    title = re.sub(r'\bnumero\s+(\d+)\b', r'n.\1', title, flags=re.IGNORECASE)
    title = re.sub(r'\bnumero(\d+)\b', r'n.\1', title, flags=re.IGNORECASE)
    title = re.sub(r'\bn°\s*(\d+)\b', r'n.\1', title, flags=re.IGNORECASE)
    title = re.sub(r'\bn\s+(\d+)\b', r'n.\1', title, flags=re.IGNORECASE)
    
    if not re.match(r'^[IVXLCDM]+$', title):
        roman_map = {
            r'\bI$': '1', r'\bII$': '2', r'\bIII$': '3', r'\bIV$': '4',
            r'\bV$': '5', r'\bVI$': '6', r'\bVII$': '7', r'\bVIII$': '8',
            r'\bIX$': '9', r'\bX$': '10'
        }
        for roman, arabic in roman_map.items():
            title = re.sub(roman, arabic, title)
    
    title = re.sub(r'\s*-\s*', ' - ', title)
    title = re.sub(r'\s*:\s*', ': ', title)
    
    title = title.replace("'", "'").replace("`", "'")
    title = title.replace(""", '"').replace(""", '"')
    
    title = re.sub(r'\s+', ' ', title)
    
    title = title.replace('&', 'e')
    
    return title.strip()


def create_search_item(title, search_text, content_type, thumbnail="", year="", genre="", plot="", event_type=""):
    use_new_search = config.get_setting('new_search')
    
    normalized_text = normalize_title_for_tmdb(search_text)
    clean_text = normalized_text.replace("+", " ").strip()
    
    full_plot = plot if plot else ""

    infoLabels = {
        'year': year if year else "",
        'genre': genre if genre else "",
        'title': clean_text,
        'plot': full_plot
    }

    if content_type == 'tvshow':
        infoLabels['tvshowtitle'] = clean_text

    if use_new_search:
        new_item = Item(
            channel='globalsearch',
            action='Search',
            text=clean_text,
            title=title,
            thumbnail=thumbnail,
            fanart=thumbnail,
            mode='movie' if content_type == 'movie' else 'tvshow',
            type='movie' if content_type == 'movie' else 'tvshow',
            contentType=content_type,
            infoLabels=infoLabels,
            folder=False
        )
        if content_type == 'movie':
            new_item.contentTitle = clean_text
        elif content_type == 'tvshow':
            new_item.contentSerieName = clean_text
    else:
        try:
            quote_fn = urllib.quote_plus
        except:
            from urllib.parse import quote_plus as quote_fn

        extra_type = 'movie' if content_type == 'movie' else 'tvshow'
        new_item = Item(
            channel='search',
            action="new_search",
            extra=quote_fn(clean_text) + '{}' + extra_type,
            title=title,
            fulltitle=clean_text,
            mode='all',
            search_text=clean_text,
            url="",
            thumbnail=thumbnail,
            contentTitle=clean_text,
            contentYear=year if year else "",
            contentType=content_type,
            infoLabels=infoLabels,
            folder=True
        )

    new_item.event_type = event_type
    return new_item


def get_films_database():
    films_dict = {}
    
    urls_to_scrape = {
        'Film in TV': f"{host}/film-in-tv/",
        'Sky Intrattenimento': f"{host}/film-in-tv/oggi/sky-intrattenimento/",
        'Sky Cinema': f"{host}/film-in-tv/oggi/sky-cinema/",
        'Sky Doc e Lifestyle': f"{host}/film-in-tv/oggi/sky-doc-e-lifestyle/",
        'Sky Bambini': f"{host}/film-in-tv/oggi/sky-bambini/"
    }
    
    patron = r'<div class="sgtvfullfilmview_divCell[^>]*>.*?'
    patron += r'sgtvfullfilmview_spanTitleMovie">([^<]*)</span>.*?'
    patron += r'sgtvfullfilmview_spanDirectorGenresMovie">[^<]*</span>.*?'
    patron += r'sgtvfullfilmview_spanDirectorGenresMovie">([^<]*)</span>.*?'
    patron += r'sgtvfullfilmview_cover[^>]*data-src="([^"]*)"[^>]*>.*?'
    patron += r'sgtvfullfilmview_divMovieYear">[^<]*([0-9]{4})'
    
    for section_name, url in urls_to_scrape.items():
        try:
            data = httptools.downloadpage(url, timeout=TIMEOUT_TOTAL).data.replace('\n', '')
            matches = re.compile(patron, re.DOTALL).findall(data)
            
            for scrapedtitle, scrapedgenre, scrapedthumb, scrapedyear in matches:
                title_clean = scrapertools.decodeHtmlentities(scrapedtitle).strip().lower()
                
                films_dict[title_clean] = {
                    'year': scrapedyear,
                    'genre': scrapertools.decodeHtmlentities(scrapedgenre).strip(),
                    'thumbnail': scrapedthumb.replace("?width=240", "?width=480")
                }
                
        except Exception as e:
            logger.error(f"[FILMONTV] Errore caricamento {section_name}: {e}")
    
    return films_dict


def now_on_misc(item):
    itemlist = []
    items_for_tmdb = []
    tmdb_blacklist = ['Notizie', 'Sport', 'Rubrica', 'Musica']

    films_db = get_films_database()
    
    data = httptools.downloadpage(item.url).data.replace('\n', '')

    patron_cell = r'<div class="sgtvonair_divCell[^>]*>(.*?)</div></div></div>'
    cells = re.compile(patron_cell, re.DOTALL).findall(data)

    for cell in cells:
        channel_match = re.search(r'sgtvonair_logo[^>]*alt="([^"]*)"', cell)
        time_match = re.search(r'sgtvonair_divHours">([^<]+)</div>', cell)
        title_match = re.search(r'sgtvonair_spanTitle[^>]*?>([^<]+)</span>', cell)
        type_match = re.search(r'sgtvonair_spanEventType[^>]*?>([^<]+)</span>', cell)
        
        thumb_match = RE_BACKDROP.search(cell)

        if not (time_match and title_match and type_match):
            continue

        scrapedchannel = scrapertools.decodeHtmlentities(channel_match.group(1) if channel_match else "").strip()
        scrapedtime = time_match.group(1).strip()
        scrapedtitle = scrapertools.decodeHtmlentities(title_match.group(1)).strip()
        scrapedtype = scrapertools.decodeHtmlentities(type_match.group(1)).strip()
        scrapedthumbnail = thumb_match.group(1) if thumb_match else ""
        
        full_thumbnail = scrapedthumbnail if scrapedthumbnail.startswith('http') else host + scrapedthumbnail if scrapedthumbnail else ""

        skip_tmdb = ("qvc" in scrapedchannel.lower() and "replica" in scrapedtitle.lower()) or \
                    ("donnatv" in scrapedchannel.lower() and "l'argonauta" in scrapedtitle.lower()) or \
                    ("rai 1" in scrapedchannel.lower() and "l'eredità" in scrapedtitle.lower())

        if skip_tmdb or scrapedtype in tmdb_blacklist:
            itemlist.append(Item(
                channel=item.channel,
                title=f"[B]{scrapedtitle}[/B] - {scrapedchannel} - {scrapedtime}",
                thumbnail=full_thumbnail,
                fanart=full_thumbnail,
                folder=False,
                infoLabels={'title': scrapedtitle, 'plot': f"[COLOR gray][B]Tipo:[/B][/COLOR] {scrapedtype}"}
            ))
        else:
            content_type = 'movie' if scrapedtype == 'Film' else 'tvshow'
            
            year = ""
            genre = ""
            
            if content_type == 'movie':
                title_lower = scrapedtitle.lower()
                if title_lower in films_db:
                    year = films_db[title_lower]['year']
                    genre = films_db[title_lower]['genre']
                    if films_db[title_lower].get('thumbnail'):
                        full_thumbnail = films_db[title_lower]['thumbnail']
            
            search_item = create_search_item(
                title=f"[B]{scrapedtitle}[/B] - {scrapedchannel} - {scrapedtime}",
                search_text=scrapedtitle,
                content_type=content_type,
                thumbnail=full_thumbnail,
                year=year,
                genre=genre,
                event_type=scrapedtype
            )
            itemlist.append(search_item)
            items_for_tmdb.append(search_item)

    if items_for_tmdb:
        tmdb.set_infoLabels_itemlist(items_for_tmdb, seekTmdb=True)
        for it in items_for_tmdb:
            if hasattr(it, 'event_type') and it.event_type:
                tipo = f"[COLOR gray][B]Tipo:[/B][/COLOR] {it.event_type}"
                current_plot = it.infoLabels.get('plot', '').strip()
                if not current_plot:
                    it.infoLabels['plot'] = tipo
                elif tipo not in current_plot:
                    it.infoLabels['plot'] = f"{tipo}\n\n{current_plot}"

    return itemlist


def now_on_misc_film(item):
    itemlist = []
    data = httptools.downloadpage(item.url).data.replace('\n', '')

    patron = r'<div class="sgtvonair_divCell[^>]*>.*?'
    patron += r'sgtvonair_logo[^>]*alt="([^"]*)"[^>]*>.*?'
    patron += r'sgtvonair_divHours">([^<]*)</div>.*?'
    patron += r'sgtvonair_spanTitle[^>]*>([^<]*)</span>.*?'
    patron += r'sgtvonair_backdrop[^>]*src="([^"]*)"'

    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedchannel, scrapedtime, scrapedtitle, scrapedthumbnail in matches:
        scrapedchannel = scrapertools.decodeHtmlentities(scrapedchannel or "").strip()
        scrapedtitle = scrapertools.decodeHtmlentities(scrapedtitle).strip()
        itemlist.append(create_search_item(
            title=f"[B]{scrapedtitle}[/B] - {scrapedchannel} - {scrapedtime}",
            search_text=scrapedtitle,
            content_type='movie',
            thumbnail=scrapedthumbnail if scrapedthumbnail.startswith('http') else host + scrapedthumbnail
        ))

    tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    return itemlist


def now_on_tv(item):
    itemlist = []
    data = httptools.downloadpage(item.url).data.replace('\n', '')

    patron = r'<div class="sgtvfullfilmview_divCell[^>]*>.*?'
    patron += r'sgtvfullfilmview_logo[^>]*alt="([^"]*)"[^>]*>.*?'
    patron += r'sgtvfullfilmview_spanMovieDuration">([^<]*)</span>.*?'
    patron += r'sgtvfullfilmview_spanTitleMovie">([^<]*)</span>.*?'
    patron += r'sgtvfullfilmview_spanDirectorGenresMovie">[^<]*</span>.*?'
    patron += r'sgtvfullfilmview_spanDirectorGenresMovie">([^<]*)</span>.*?'
    patron += r'sgtvfullfilmview_cover[^>]*data-src="([^"]*)"[^>]*>.*?'
    patron += r'sgtvfullfilmview_divMovieYear">[^<]*([0-9]{4})'

    matches = re.compile(patron, re.DOTALL).findall(data)

    for scrapedchannel, scrapedduration, scrapedtitle, scrapedgender, scrapedthumbnail, scrapedyear in matches:
        scrapedchannel = scrapertools.decodeHtmlentities(scrapedchannel or "").strip()
        scrapedtitle = scrapertools.decodeHtmlentities(scrapedtitle).strip()
        it = create_search_item(
            title=f"[B]{scrapedtitle}[/B] - {scrapedchannel} - {scrapedduration}",
            search_text=scrapedtitle,
            content_type='movie',
            thumbnail=scrapedthumbnail.replace("?width=240", "?width=480"),
            year=scrapedyear,
            genre=scrapedgender
        )
        itemlist.append(it)

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
                channel_name, itlist = res.result()
                channels_dict[channel_name] = itlist
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
        channel = __import__(f'channels.{channel_name}', None, None, [f'channels.{channel_name}'])
        itemlist = channel.live(channel.mainlist(Item())[0])
    except:
        itemlist = []
    return channel_name, itemlist
