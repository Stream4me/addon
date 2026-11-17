# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per AnimeUnity
# ------------------------------------------------------------

import json, copy, inspect, html, re, unicodedata
from urllib.parse import quote_plus
from core import support, httptools, scrapertools, tmdb
from platformcode import autorenumber, logger

host = support.config.get_channel_url()

headers = {'Accept': 'application/json',
           'X-Requested-With': 'XMLHttpRequest'}

_genres_cache = []
_years_cache = []


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
                item.clone(title=support.typo('Anno','bold'), action='years'),
                item.clone(title=support.typo('Stagione','bold'), action='seasons'),
                item.clone(title=support.typo('Studio','bold'), action='studios'),
                item.clone(title=support.typo('Stato','bold'), action='statuses'),
                item.clone(title=support.typo('Tipo','bold'), action='types'),
                item.clone(title=support.typo('Lingua','bold'), action='languages')]
    if item.contentType == 'tvshow':
        itemlist += [item.clone(title=support.typo('In Corso','bold'), args=InCorso),
                     item.clone(title=support.typo('Terminato','bold'), args=Terminato)]
    itemlist +=[item.clone(title=support.typo('Cerca...','bold'), action='search', thumbnail=support.thumb('search'))]
    return itemlist


def get_data_page(url):
    data = httptools.downloadpage(url).data or ''
    m = re.search(r'data-page="([^"]+)"', data)
    if not m:
        logger.info('AnimeUnity: data-page non trovato in {}'.format(url))
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except Exception as e:
        logger.info('AnimeUnity: errore parsing data-page: {}'.format(e))
        return None


def api_json(url):
    try:
        return httptools.downloadpage(url, headers=headers).json
    except Exception as e:
        logger.info('AnimeUnity: errore richiesta {}: {}'.format(url, e))
        return None


def get_thumb(anime):
    img = anime.get('images')
    if isinstance(img, dict):
        for k in ('poster', 'cover', 'banner'):
            if img.get(k):
                return img[k]
    return anime.get('imageurl') or ''


def anime_url(anime):
    return '{}/anime/{}-{}'.format(host, anime.get('id'), anime.get('slug'))


def lang_badge(is_ita):
    return support.typo('ITA' if is_ita else 'Sub-ITA', '_ [] color std')


def genre_id(g):
    return g.get('id') if isinstance(g, dict) else g


def load_genres():
    if _genres_cache:
        return _genres_cache

    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}

    for key in ('animeGenres', 'genres', 'allGenres', 'filters'):
        val = props.get(key)
        if key == 'filters' and isinstance(val, dict):
            val = val.get('genres')
        if isinstance(val, list) and val and isinstance(val[0], dict) and 'id' in val[0]:
            _genres_cache.extend({'id': g['id'], 'name': g.get('name', str(g['id']))} for g in val)
            return _genres_cache

    logger.info('AnimeUnity: generi non trovati, props keys: {}'.format(list(props.keys())))
    return _genres_cache


def load_years():
    if _years_cache:
        return _years_cache

    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    years = props.get('animeYears')

    if isinstance(years, list) and years:
        _years_cache.extend(years)
    else:
        logger.info('AnimeUnity: animeYears non trovati')
    return _years_cache


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


def genres(item):
    support.info()
    itemlist = []

    for genre in load_genres():
        args = copy.copy(item.args) if item.args else {}
        args['genres'] = [genre['id']]
        itemlist.append(item.clone(title=support.typo(genre['name'],'bold'), args=args, action='peliculas'))
    return support.thumb(itemlist)

def years(item):
    support.info()
    itemlist = []

    for year in load_years():
        args = copy.copy(item.args) if item.args else {}
        args['year_from'] = year
        args['year_to'] = year
        itemlist.append(item.clone(title=support.typo(year,'bold'), args=args, action='peliculas'))
    return itemlist


def seasons(item):
    support.info()
    itemlist = []
    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    seasons = props.get('animeSeasons') or []
    for s in seasons:
        args = copy.copy(item.args) if item.args else {}
        args['season'] = s
        itemlist.append(item.clone(title=support.typo(s.capitalize(),'bold'), args=args, action='peliculas'))
    return itemlist


def studios(item):
    support.info()
    itemlist = []
    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    studios = props.get('animeStudios') or []
    for s in studios:
        args = copy.copy(item.args) if item.args else {}
        args['studio'] = s['id']
        itemlist.append(item.clone(title=support.typo(s['name'],'bold'), args=args, action='peliculas'))
    return itemlist


def statuses(item):
    support.info()
    itemlist = []
    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    statuses = props.get('animeStatuses') or []
    for s in statuses:
        args = copy.copy(item.args) if item.args else {}
        args['status'] = s
        itemlist.append(item.clone(title=support.typo(s.capitalize(),'bold'), args=args, action='peliculas'))
    return itemlist


def types(item):
    support.info()
    itemlist = []
    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    types = props.get('animeTypes') or []
    for t in types:
        args = copy.copy(item.args) if item.args else {}
        args['type'] = t
        itemlist.append(item.clone(title=support.typo(t.capitalize(),'bold'), args=args, action='peliculas'))
    return itemlist


def languages(item):
    support.info()
    itemlist = []
    page = get_data_page(host + '/archive')
    props = (page or {}).get('props') or {}
    languages = props.get('animeLanguages') or []
    for l in languages:
        args = copy.copy(item.args) if item.args else {}
        args['language'] = l
        itemlist.append(item.clone(title=support.typo(l.upper(),'bold'), args=args, action='peliculas'))
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


_plot_cache = {}


def _plot_di(anime_data):
    aid = anime_data.get('id')
    if aid in _plot_cache:
        return _plot_cache[aid]
    plot = ''
    try:
        titolo = anime_data.get('title') or anime_data.get('title_eng')
        r = api_json('{}/api/archive?query={}'.format(host, quote_plus(titolo)))
        records = (r or {}).get('data', [])
        if isinstance(records, dict):
            records = records.get('data', [])
        for rec in records or []:
            if rec.get('id') == aid:
                plot = clean_html_entities(rec.get('plot') or '')
                break
    except Exception:
        plot = ''
    _plot_cache[aid] = plot
    return plot


def news(item):
    support.info()
    item.contentType = 'episode'
    itemlist = []

    url = item.url if (item.url or '').startswith('http') else host

    if '/api/' in url:
        fullJs = api_json(url)
    else:
        page = get_data_page(url)
        fullJs = ((page or {}).get('props') or {}).get('latestEpisodes')

    if not isinstance(fullJs, dict):
        return itemlist

    js = fullJs.get('data') or []

    for it in js:
        if it.get('is_hidden'):
            continue
        ep = it.get('episode') or {}
        anime_data = ep.get('anime') or it.get('anime') or {}
        if anime_data.get('title') or anime_data.get('title_eng'):
            raw_title = html.unescape(anime_data.get('title') or '')
            raw_title_eng = html.unescape(anime_data.get('title_eng') or '')

            is_ita = it.get('language') == 'ita'

            base_title = raw_title_eng if raw_title_eng else raw_title
            title_name = clean_title(base_title)

            file_name = it.get('file_name') or ep.get('file_name') or ''
            full_episode = ''
            season_num, episode_num = 1, 0

            pattern = r'[sS](?P<season>\d+)[eE](?P<episode>\d+)'
            match = scrapertools.find_single_match(file_name, pattern)
            if match:
                season, episode = match
                full_episode = ' - S' + season + ' E' + episode
                season_num, episode_num = int(season), int(episode)
            else:
                episode = str(ep.get('number') or '')
                if episode:
                    full_episode = ' - E' + episode
                    if episode.isdigit():
                        episode_num = int(episode)

            final_title = support.typo(title_name, 'bold') + lang_badge(is_ita)

            url_anime = anime_url(anime_data)
            clean_plot = clean_html_entities(anime_data.get('plot') or '')
            if not clean_plot:
                clean_plot = _plot_di(anime_data)

            itemlist.append(
                item.clone(title = final_title + full_episode,
                           fulltitle = title_name,
                           thumbnail = get_thumb(anime_data),
                           forcethumb = True,
                           scws_id = it.get('scws_id', ''),
                           url = '{}/{}'.format(url_anime, it.get('id')),
                           plot = clean_plot,
                           contentLanguage = 'ITA' if is_ita else 'Sub-ITA',
                           episode = episode_num,
                           season = season_num,
                           show = title_name,
                           contentSerieName = title_name,
                           action = 'findvideos')
            )

    if fullJs.get('next_page_url'):
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),
                                   thumbnail=support.thumb(), url=fullJs['next_page_url'], action='news'))
    return itemlist


def match_filters(it, args):
    if args.get('type') and (it.get('type') or '').lower() != args['type'].lower():
        return False

    gids = [genre_id(g) for g in (args.get('genres') or [])]
    if gids:
        have = set(g.get('id') for g in (it.get('genres') or []))
        if not set(gids) <= have:
            return False

    y = it.get('year')
    if y is not None:
        if args.get('year_from') and y < args['year_from']:
            return False
        if args.get('year_to') and y > args['year_to']:
            return False
    return True


def peliculas(item):
    support.info()
    itemlist = []

    page = item.page if item.page else 0
    args = copy.copy(item.args) if item.args else {}
    ita_only = args.get('title') == '(ita)' or args.get('language') == 'ita'

    params = []
    if ita_only:
        params.append('language=ita')
    elif args.get('title'):
        q = quote_plus(args['title'])
        params.append('query={}'.format(q))
    if args.get('type'):
        params.append('type={}'.format(args['type'].lower()))
    for i, g in enumerate(args.get('genres') or []):
        params.append('genres[{}]={}'.format(i, genre_id(g)))
    if args.get('year_from'):
        params.append('year_from={}'.format(args['year_from']))
    if args.get('year_to'):
        params.append('year_to={}'.format(args['year_to']))
    if args.get('status'):
        status_map = {'In Corso': 'ongoing', 'Terminato': 'completed'}
        params.append('status={}'.format(status_map.get(args['status'], args['status'])))
    if args.get('season'):
        params.append('season={}'.format(args['season']))
    if args.get('studio'):
        params.append('studio[]={}'.format(args['studio']))
    if args.get('language'):
        params.append('language={}'.format(args['language']))
    params.append('page={}'.format(page + 1))

    r = api_json('{}/api/archive?{}'.format(host, '&'.join(params)))
    if not isinstance(r, dict):
        return itemlist

    records = r.get('data', [])
    if isinstance(records, dict):
        records = records.get('data', [])

    for it in records or []:
        if not match_filters(it, args):
            continue

        raw_title = html.unescape(it.get('title') or '')
        raw_title_eng = html.unescape(it.get('title_eng') or '')
        base_title = raw_title_eng if raw_title_eng else raw_title
        title_clean = clean_title(base_title or it.get('title_ja') or '')

        langs = set(v.get('language') for v in (it.get('variants') or []) if v.get('language'))
        versions = []
        if 'ita' in langs:
            versions.append(True)
        if (langs - {'ita'}) or not langs:
            versions.append(False)
        if ita_only:
            versions = [v for v in versions if v]

        for is_ita in versions:
            itm = item.clone(title=support.typo(title_clean, 'bold') + lang_badge(is_ita))
            itm.contentLanguage = 'ITA' if is_ita else 'Sub-ITA'
            itm.type = it.get('type') or ''
            itm.thumbnail = get_thumb(it)
            itm.plot = clean_html_entities(it.get('plot') or '')
            itm.url = anime_url(it)

            if itm.type.lower() == 'movie':
                itm.contentType = 'movie'
                itm.fulltitle = itm.show = itm.contentTitle = title_clean
                itm.contentSerieName = ''
                itm.action = 'findvideos'
            else:
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
    if r.get('next_page_url'):
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'), thumbnail=support.thumb(), page=page + 1))

    return itemlist


def pick_video(videos, ita):
    if not videos:
        return None
    if not any(v.get('language') for v in videos):
        return videos[0]
    if ita:
        for v in videos:
            if v.get('language') == 'ita':
                return v
        return None
    for v in videos:
        if v.get('language') != 'ita':
            return v
    return None


def get_episodes(item):
    m = re.search(r'(.*?/anime/\d+-[^/?#]+)', item.url or '')
    if not m:
        logger.info('AnimeUnity: URL non valido: {}'.format(item.url))
        return [], None
    base = m.group(1)
    anime_id = re.search(r'/anime/(\d+)', base).group(1)

    page = get_data_page(base)
    if not page:
        return [], base

    props = page.get('props') or {}
    loaded = props.get('loadedEpisodes') or {}
    episodes = list(loaded.get('episodes') or [])
    if not episodes:
        logger.info('AnimeUnity: nessun episodio, props keys: {}'.format(list(props.keys())))

    count = loaded.get('total') or 0
    limit = loaded.get('tab_size') or 120
    start = loaded.get('start') or 1
    offset = start + len(episodes)

    while episodes and offset <= count:
        r = api_json('{}/api/anime/{}/episodes?start={}&end={}'.format(
            host, anime_id, offset, offset + limit - 1))
        eps = (r or {}).get('episodes') or []
        if not eps:
            break
        episodes += eps
        offset += len(eps)

    ita = getattr(item, 'contentLanguage', '') == 'ITA'
    out = []
    for ep in episodes:
        video = pick_video(ep.get('videos') or [], ita)
        if not video:
            continue
        out.append({'number': str(ep.get('number', '0')),
                    'file_name': ep.get('file_name') or video.get('file_name') or '',
                    'id': video.get('id'),
                    'scws_id': video.get('scws_id')})
    return out, base


def episodios(item):
    support.info()
    itemlist = []
    title = 'Parte' if (item.type or '').lower() == 'movie' else 'Episodio'

    episodes, base = get_episodes(item)

    for it in episodes:
        match = re.search(r'[sS](\d+)[eE](\d+)', it['file_name'])
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
                   scws_id=it['scws_id'],
                   url = '{}/{}'.format(base, it['id'])
                  )
        )

    if inspect.stack(0)[1][3] not in ['find_episodes']:
        autorenumber.start(itemlist, item)
    support.videolibrary(itemlist, item)

    return itemlist


def findvideos(item):
    from core import channeltools

    if not getattr(item, 'scws_id', None):
        episodes, base = get_episodes(item)
        if episodes:
            item.scws_id = episodes[0]['scws_id']
            item.url = '{}/{}'.format(base, episodes[0]['id'])

    itemlist = [item.clone(title=channeltools.get_channel_parameters(item.channel)['title'],
                           url=item.url, server='streamingcommunityws')]
    return support.server(item, itemlist=itemlist, referer=False)