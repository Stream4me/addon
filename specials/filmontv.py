# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale film in tv
# ------------------------------------------------------------

import re
import time
try:
    import urllib.parse as urllib
except ImportError:
    import urllib
from core import httptools, scrapertools, support, tmdb, filetools
from core.item import Item
from platformcode import config, platformtools, logger

host = "https://www.superguidatv.it"
TIMEOUT_TOTAL = 60

TMDB_BLACKLIST = ['Notizie', 'Sport', 'Rubrica', 'Musica']

_films_cache = None
_films_cache_time = 0
CACHE_DURATION = 1800


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
    
    if re.match(r'^\d+$', title) or re.match(r'^\d{4}\s', title):
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
    global _films_cache, _films_cache_time
    now = time.time()
    
    if _films_cache is not None and (now - _films_cache_time) < CACHE_DURATION:
        return _films_cache
    
    films_dict = {}
    
    urls_to_scrape = {
        'Film in TV': f"{host}/film-in-tv/",
        'Sky Intrattenimento': f"{host}/film-in-tv/oggi/sky-intrattenimento/",
        'Sky Cinema': f"{host}/film-in-tv/oggi/sky-cinema/",
        'Sky Doc e Lifestyle': f"{host}/film-in-tv/oggi/sky-doc-e-lifestyle/",
        'Sky Bambini': f"{host}/film-in-tv/oggi/sky-bambini/"
    }
    
    patron = r'<a[^>]*href="/dettaglio-film/[^"]*"[^>]*class="[^"]*sgtv-font-bold[^"]*"[^>]*>([^<]+)</a>.*?'
    patron += r'<img[^>]*src="([^"]+)"[^>]*class="[^"]*sgtv-object-cover[^"]*"[^>]*>.*?'
    patron += r'<p class="[^"]*sgtv-h-1/2[^"]*sgtv-break-words[^"]*sgtv-leading-10[^"]*">[^<]*([0-9]{4})</p>'
    
    for section_name, url in urls_to_scrape.items():
        try:
            data = httptools.downloadpage(url, timeout=TIMEOUT_TOTAL).data.replace('\n', '')
            matches = re.compile(patron, re.DOTALL).findall(data)
            
            for scrapedtitle, scrapedthumb, scrapedyear in matches:
                title_clean = scrapertools.decodeHtmlentities(scrapedtitle).strip().lower()
                
                genre = ""
                title_pos = data.find(scrapedtitle)
                if title_pos > 0:
                    context = data[title_pos:title_pos + 500]
                    genre_match = re.search(r'(?:Genere|Categoria):\s*([^<]+)', context, re.IGNORECASE)
                    if genre_match:
                        genre = genre_match.group(1).strip()
                
                if title_clean not in films_dict or scrapedyear:
                    films_dict[title_clean] = {
                        'year': scrapedyear,
                        'genre': genre,
                        'thumbnail': scrapedthumb.replace("?width=240", "?width=480")
                    }
                    
        except Exception as e:
            logger.error(f"[FILMONTV] Errore caricamento {section_name}: {e}")
    
    _films_cache = films_dict
    _films_cache_time = now
    return films_dict


def _determine_content_type(link_match, channel, scrapedtype, title, films_db):
    if link_match:
        if '/dettaglio-film/' in link_match.group(1):
            return 'movie'
        if '/dettaglio-programma/' in link_match.group(1):
            return 'tvshow'
    
    if 'Film' in scrapedtype:
        return 'movie'
    if re.search(r'\b(19|20)\d{2}\b', title):
        return 'movie'
    if title.lower() in films_db:
        return 'movie'
    
    return 'tvshow'


def now_on_misc(item):
    itemlist = []
    items_for_tmdb = []
    
    films_db = get_films_database()
    data = httptools.downloadpage(item.url).data.replace('\n', '')
    
    logo_pattern = r'<img alt="([^"]+)"[^>]*src="([^"]*)"[^>]*class="[^"]*sgtv-ml-\[10%\][^"]*"[^>]*>'
    logo_matches = list(re.finditer(logo_pattern, data))
    
    for i, logo_match in enumerate(logo_matches):
        scrapedchannel = scrapertools.decodeHtmlentities(logo_match.group(1)).strip()
        logo_url = logo_match.group(2).strip()
        
        start_pos = logo_match.end()
        end_pos = logo_matches[i + 1].start() if i + 1 < len(logo_matches) else len(data)
        segmento = data[start_pos:end_pos]
        
        time_match = re.search(r'<p class="[^"]*sgtv-text-lg[^"]*sgtv-font-bold[^"]*">(\d{2}:\d{2})</p>', segmento)
        title_match = re.search(r'<p class="[^"]*sgtv-max-w-full[^"]*sgtv-truncate[^"]*">([^<]+)</p>', segmento)
        type_match = re.search(r'<p class="[^"]*sgtv-border-l-8[^"]*sgtv-pl-2\.5[^"]*sgtv-text-sm[^"]*">([^<]+)</p>', segmento)
        link_match = re.search(r'href="(/dettaglio-(?:film|programma)/[^"]+)"', segmento)
        
        if not (time_match and title_match):
            continue
            
        scrapedtime = time_match.group(1).strip()
        scrapedtitle = scrapertools.decodeHtmlentities(title_match.group(1)).strip()
        scrapedtype = scrapertools.decodeHtmlentities(type_match.group(1)).strip() if type_match else ""
        full_thumbnail = logo_url

        skip_tmdb = any((
            "qvc" in scrapedchannel.lower() and "replica" in scrapedtitle.lower(),
            "donnatv" in scrapedchannel.lower() and "l'argonauta" in scrapedtitle.lower(),
            "rai 1" in scrapedchannel.lower() and "l'eredità" in scrapedtitle.lower()
        ))

        tipo_base = scrapedtype.split(' (da')[0] if scrapedtype else ""

        if skip_tmdb or tipo_base in TMDB_BLACKLIST:
            itemlist.append(Item(
                channel=item.channel,
                title=f"[B]{scrapedtitle}[/B] - {scrapedchannel} - {scrapedtime}",
                thumbnail=full_thumbnail,
                fanart=full_thumbnail,
                folder=False,
                infoLabels={'title': scrapedtitle, 'plot': f"[COLOR gray][B]Tipo:[/B][/COLOR] {scrapedtype}"}
            ))
        else:
            content_type = _determine_content_type(link_match, scrapedchannel, scrapedtype, scrapedtitle, films_db)
            
            year = ""
            genre = ""
            if content_type == 'movie':
                title_lower = scrapedtitle.lower()
                if title_lower in films_db:
                    year = films_db[title_lower]['year']
                    genre = films_db[title_lower].get('genre', '')
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


def now_on_tv(item):
    itemlist = []
    films_db = get_films_database()
    data = httptools.downloadpage(item.url).data
    
    patron = r'<div class="sgtv-group sgtv-flex sgtv-flex-col[^>]*>.*?'
    patron += r'<img alt="([^"]+)"[^>]*src="([^"]+)"[^>]*>.*?'
    patron += r'<p[^>]*class="[^"]*sgtv-leading-6[^"]*"[^>]*>([^<]+)</p>.*?'
    patron += r'<a[^>]*href="/dettaglio-film/[^"]*"[^>]*class="[^"]*sgtv-font-bold[^"]*"[^>]*>([^<]+)</a>.*?'
    patron += r'(?:<p[^>]*class="[^"]*sgtv-row-span-1[^"]*"[^>]*>Regia: ([^<]*)</p>.*?)?'
    patron += r'(?:<p[^>]*class="[^"]*sgtv-row-span-1[^"]*"[^>]*>([^<]*)</p>.*?)?'
    patron += r'(?:<img[^>]*src="([^"]+)"[^>]*class="[^"]*sgtv-object-cover[^"]*"[^>]*>.*?)?'
    patron += r'<p class="[^"]*sgtv-h-1/2[^"]*sgtv-break-words[^"]*sgtv-leading-10[^"]*">([^<]*)</p>'

    matches = re.compile(patron, re.DOTALL).findall(data)
    
    for match in matches:
        canale = scrapertools.decodeHtmlentities(match[0]).strip()
        orario = match[2].strip()
        titolo = scrapertools.decodeHtmlentities(match[3]).strip()
        genere = scrapertools.decodeHtmlentities(match[5]).strip() if len(match) > 5 and match[5] else ""
        copertina = match[6].strip() if len(match) > 6 and match[6] else ""
        anno_testuale = match[7].strip() if len(match) > 7 and match[7] else ""
        
        if copertina and not copertina.startswith('http'):
            copertina = host + copertina
        
        anno = ""
        if anno_testuale:
            anno_match = re.search(r'(\d{4})', anno_testuale)
            if anno_match:
                anno = anno_match.group(1)
        
        titolo_key = titolo.lower()
        if titolo_key in films_db:
            if films_db[titolo_key]['year']:
                anno = films_db[titolo_key]['year']
            if films_db[titolo_key].get('genre'):
                genere = films_db[titolo_key]['genre']
            if films_db[titolo_key].get('thumbnail'):
                copertina = films_db[titolo_key]['thumbnail']
        
        it = create_search_item(
            title=f"[B]{titolo}[/B] - {canale} - {orario}",
            search_text=titolo,
            content_type='movie',
            thumbnail=copertina,
            year=anno,
            genre=genere
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