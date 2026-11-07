# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per AnimeUnity
# ------------------------------------------------------------

import cloudscraper, json, copy, inspect, html, re, unicodedata
from core import jsontools, support, httptools, scrapertools, tmdb
from platformcode import autorenumber, logger

host = support.config.get_channel_url()
response = httptools.downloadpage(host + '/archivio')
csrf_token = support.match(response.data, patron='name="csrf-token" content="([^"]+)"').match
headers = {'content-type': 'application/json;charset=UTF-8',
           'x-csrf-token': csrf_token,
           'Cookie' : '; '.join([x.name + '=' + x.value for x in response.cookies])}


@support.menu
def mainlist(item):
    top =  [('Ultimi Episodi', ['', 'news'])]

    menu = [('Anime {bullet bold}',['', 'menu', {}, 'tvshow']),
            ('Film {submenu}',['', 'menu', {'type': 'Movie'}]),
            ('TV {submenu}',['', 'menu', {'type': 'TV'}, 'tvshow']),
            ('OVA {submenu} {tv}',['', 'menu', {'type': 'OVA'}, 'tvshow']),
            ('ONA {submenu} {tv}',['', 'menu', {'type': 'ONA'}, 'tvshow']),
            ('Special {submenu} {tv}',['', 'menu', {'type': 'Special'}, 'tvshow'])]
    search =''
    return locals()

def menu(item):
    item.action = 'peliculas'
    ITA = copy.copy(item.args)
    ITA['title'] = '(ita)'
    InCorso = copy.copy(item.args)
    InCorso['status'] = 'In Corso'
    Terminato = copy.copy(item.args)
    Terminato['status'] = 'Terminato'
    itemlist = [item.clone(title=support.typo('Tutti','bold')),
                item.clone(title=support.typo('ITA','bold'), args=ITA),
                item.clone(title=support.typo('Genere','bold'), action='genres'),
                item.clone(title=support.typo('Anno','bold'), action='years')]
    if item.contentType == 'tvshow':
        itemlist += [item.clone(title=support.typo('In Corso','bold'), args=InCorso),
                     item.clone(title=support.typo('Terminato','bold'), args=Terminato)]
    itemlist +=[item.clone(title=support.typo('Cerca...','bold'), action='search', thumbnail=support.thumb('search'))]
    return itemlist


def genres(item):
    support.info()
    itemlist = []

    genres = json.loads(support.match(response.data, patron='genres="([^"]+)').match.replace('&quot;','"'))

    for genre in genres:
        item.args['genres'] = [genre]
        itemlist.append(item.clone(title=support.typo(genre['name'],'bold'), action='peliculas'))
    return support.thumb(itemlist)

def years(item):
    support.info()
    itemlist = []

    from datetime import datetime
    next_year = datetime.today().year + 1
    oldest_year = int(support.match(response.data, patron='anime_oldest_date="([^"]+)').match)

    for year in list(reversed(range(oldest_year, next_year + 1))):
        item.args['year']=year
        itemlist.append(item.clone(title=support.typo(year,'bold'), action='peliculas'))
    return itemlist


def search(item, text):
    support.info('search', item)
    if not item.args:
        item.args = {'title':text}
    else:
        item.args['title'] = text
    item.search = text

    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            support.info('search log:', line)
        return []


def newest(categoria):
    support.info(categoria)
    itemlist = []
    item = support.Item()
    item.url = host

    try:
        itemlist = news(item)
        if itemlist[-1].action == 'news':
            itemlist.pop()
    except:
        import sys
        for line in sys.exc_info():
            support.info(line)
        return []

    return itemlist


def clean_title(raw_title):
    if not raw_title:
        return ''
    t = html.unescape(raw_title)
    t = unicodedata.normalize('NFKC', t)
    t = re.sub(r'\s*\((?:ita|sub-ita)\)', '', t, flags=re.IGNORECASE)
    t = t.replace('"', '').replace("'", "'")
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def clean_html_entities(text):
    if not text:
        return ''
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = html.unescape(text)
    return text


def news(item):
    support.info()
    item.contentType = 'episode'
    itemlist = []

    fullJs = json.loads(support.match(httptools.downloadpage(item.url).data, headers=headers, patron=r'items-json="([^"]+)"').match.replace('&quot;','"'))
    js = fullJs['data']

    for it in js:
        anime_data = it.get('anime', {})
        if anime_data.get('title') or anime_data.get('title_eng'):
            raw_title = html.unescape(anime_data.get('title') or '')
            raw_title_eng = html.unescape(anime_data.get('title_eng') or '')
            
            lang_match = re.search(r'\((sub-ita|ita)\)', raw_title, re.IGNORECASE)
            if not lang_match:
                lang_match = re.search(r'\((sub-ita|ita)\)', raw_title_eng, re.IGNORECASE)
            
            is_ita = False
            if lang_match:
                is_ita = (lang_match.group(1).upper() == 'ITA')
            else:
                is_ita = (anime_data.get('dub') == 1)

            base_title = raw_title_eng if raw_title_eng else raw_title
            title_name = clean_title(base_title)

            pattern = r'[sS](?P<season>\d+)[eE](?P<episode>\d+)'
            match = scrapertools.find_single_match(it['file_name'], pattern)
            full_episode = ''
            
            if match:
                season, episode = match
                full_episode = ' - S' + season + ' E' + episode
            else:
                pattern = r'[._\s]Ep[._\s]*(?P<episode>\d+)'
                episode = scrapertools.find_single_match(it['file_name'], pattern)
                if episode:
                    full_episode = ' - E' + episode                             

            if is_ita:
                final_title = support.typo(title_name, 'bold') + support.typo('ITA', '_ [] color std')
            else:
                final_title = support.typo(title_name, 'bold') + support.typo('Sub-ITA', '_ [] color std')

            clean_plot = clean_html_entities(anime_data.get('plot', ''))

            itemlist.append(
                item.clone(title = final_title + full_episode,
                           fulltitle = title_name,
                           thumbnail = anime_data['imageurl'],
                           forcethumb = True,
                           scws_id = it.get('scws_id', ''),
                           url = '{}/anime/{}-{}'.format(item.url, anime_data['id'], anime_data['slug']),
                           plot = clean_plot,
                           action = 'findvideos')
            )
            
    if 'next_page_url' in fullJs:
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),thumbnail=support.thumb(), url=fullJs['next_page_url']))
    return itemlist


def peliculas(item):
    support.info()
    itemlist = []

    page = item.page if item.page else 0
    item.args['offset'] = page * 30

    order = support.config.get_setting('order', item.channel)
    if order:
        order_list = [ "Standard", "Lista A-Z", "Lista Z-A", "Popolarità", "Valutazione" ]
        item.args['order'] = order_list[order]

    payload = json.dumps(item.args)
    records = httptools.downloadpage(host + '/archivio/get-animes', headers=headers, post=payload).json['records']
 
    for it in records:
        raw_title = html.unescape(it.get('title') or '')
        raw_title_eng = html.unescape(it.get('title_eng') or '')
        
        is_ita = bool(re.search(r'\(ita\)', raw_title, re.IGNORECASE) or 
                      re.search(r'\(ita\)', raw_title_eng, re.IGNORECASE) or
                      it.get('dub') == 1)
        
        base_title = raw_title_eng if raw_title_eng else raw_title
        title_clean = clean_title(base_title)

        if is_ita:
            itm_title = support.typo(title_clean, 'bold') + support.typo('ITA', '_ [] color std')
        else:
            itm_title = support.typo(title_clean, 'bold') + support.typo('Sub-ITA', '_ [] color std')
        
        itm = item.clone(title=itm_title)
        itm.contentLanguage = 'ITA' if is_ita else 'Sub-ITA'
        itm.type = it['type']
        itm.thumbnail = it['imageurl']
        itm.plot = clean_html_entities(it.get('plot', ''))
        itm.url = '{}/anime/{}-{}'.format(item.url, it.get('id'), it.get('slug'))

        if it.get('episodes_count') == 1 and it.get('type', '').lower() == 'movie':
            itm.contentType = 'movie'
            itm.fulltitle = itm.show = itm.contentTitle = title_clean
            itm.contentSerieName = ''
            itm.action = 'findvideos'
        else:
            itm.api_ep_url = '{}/info_api/{}/'.format(item.url, it.get('id'))
            itm.contentType = 'tvshow'
            itm.contentTitle = ''
            itm.fulltitle = itm.show = itm.contentSerieName = title_clean
            itm.action = 'episodios'

        itemlist.append(itm)

    if itemlist and item.search:
        tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True, forced=True)
        for itm in itemlist:
            logger.info('AnimeUnity TMDB: {} | {} | tmdb_id={}'.format(
                itm.contentType, itm.fulltitle, itm.infoLabels.get('tmdb_id')))

    autorenumber.start(itemlist)
    if len(itemlist) >= 30:
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'), thumbnail=support.thumb(), page=page + 1))

    return itemlist


def episodios(item):
    support.info()
    itemlist = []
    title = 'Parte' if item.type.lower() == 'movie' else 'Episodio'
    start = 1
    limit = 120

    if not getattr(item, 'api_ep_url', None):
        m = re.search(r'/anime/(\d+)', item.url or '')
        if not m:
            logger.info('AnimeUnity: impossibile ricavare api_ep_url da url={}'.format(item.url))
            return []
        item.api_ep_url = '{}/info_api/{}/'.format(host, m.group(1))
        logger.info('AnimeUnity: api_ep_url ricostruito -> {}'.format(item.api_ep_url))
 
    while True:
        url_api = '{}1?start_range={}&end_range={}'.format(item.api_ep_url, start, start + (limit - 1))
        data = httptools.downloadpage(url_api, headers=headers).data

        try:
            full = json.loads(data)
        except (ValueError, TypeError):
            logger.info('AnimeUnity: risposta non valida da {} (len={})'.format(url_api, len(data or '')))
            break
        count = full.get('episodes_count', 0)
        episodes = full.get('episodes', [])
        
        for it in episodes:
            file_name = it.get('file_name', '')
            match = re.search(r'[sS](\d+)[eE](\d+)', file_name)
            if match:
                season_num = int(match.group(1))
                episode_num = int(match.group(2))
            else:
                season_num = 1
                episode_num = int(it['number']) if it['number'].isdigit() else 0

            itemlist.append(
                item.clone(title=support.typo('{} {}'.format(title, it['number']), 'bold'),
                       episode=episode_num,
                       season=season_num,
                       fulltitle=item.title,
                       show=item.title,
                       contentTitle='',
                       contentSerieName=item.contentSerieName,
                       thumbnail=item.thumbnail,
                       plot=item.plot,
                       action='findvideos',
                       contentType='episode',
                       url = '{}/{}'.format(item.url, it['id'])
                      )
            )
        if count > start:
            start = start + limit
        else:
            break

    if inspect.stack(0)[1][3] not in ['find_episodes']:
        autorenumber.start(itemlist, item)
    support.videolibrary(itemlist, item)

    return itemlist


def findvideos(item):
    from core import channeltools
    itemlist = [item.clone(title=channeltools.get_channel_parameters(item.channel)['title'],
                           url=item.url, server='streamingcommunityws')]
    return support.server(item, itemlist=itemlist, referer=False)