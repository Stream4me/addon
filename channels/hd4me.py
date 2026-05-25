# -*- coding: utf-8 -*-
from core import httptools, support
import json, html, re

host = support.config.get_channel_url()
CACHE_BASE = 'https://hd4me.net/wp-content/themes/mytheme/cache/'
headers = [['Referer', host]]
_nav_cache = {}


def _get_nav():
    if _nav_cache:
        return _nav_cache
    url = CACHE_BASE + 'nav.json'
    resp = httptools.downloadpage(url, headers=headers)
    if not resp.data:
        return {}
    try:
        data_str = resp.data
        if isinstance(data_str, bytes):
            data_str = data_str.decode('utf-8-sig')
        elif isinstance(data_str, str) and data_str.startswith('\ufeff'):
            data_str = data_str[1:]
        data = json.loads(data_str)
        _nav_cache.update(data)
    except Exception as e:
        support.logger.error('hd4me: errore parsing nav.json: %s' % e)
    return _nav_cache


def _version():
    return _get_nav().get('version', '')


def _get_json(path):
    v = _version()
    url = CACHE_BASE + path
    if v:
        url += '?v={}'.format(v)
    resp = httptools.downloadpage(url, headers=headers)
    if not resp.data:
        return None
    try:
        data_str = resp.data
        if isinstance(data_str, bytes):
            data_str = data_str.decode('utf-8-sig')
        elif isinstance(data_str, str) and data_str.startswith('\ufeff'):
            data_str = data_str[1:]
        return json.loads(data_str)
    except Exception as e:
        support.logger.error('hd4me: errore parsing %s: %s' % (path, e))
        return None


def _clean_title(title):
    return html.unescape(title) if title else ''


def _pure_title(full_title):
    full_title = _clean_title(full_title)
    m = re.match(r'^(.+?)\s*\((\d{4})\)', full_title)
    if m:
        return m.group(1).strip(), m.group(2)
    return full_title, ''


def _posts_to_itemlist(item, posts):
    itemlist = []
    for info in posts:
        post_id = info.get('id', '')
        full_title = _clean_title(info.get('title', ''))
        movie = info.get('movie', {})
        title, year = _pure_title(full_title)
        if not year:
            years = movie.get('years', [])
            year = years[0].get('name', '') if years and isinstance(years[0], dict) else ''
        tmdb_id = int(movie.get('tmdb', 0)) if movie.get('tmdb') else ''
        imdb_id = movie.get('imdb', '')
        poster = movie.get('poster', '')
        duration = movie.get('duration', '')
        genres = ', '.join(g.get('name', '') for g in movie.get('genres', []))
        new_item = item.clone(
            action='findvideos',
            title=title,
            fulltitle=full_title,
            contentTitle=title,
            url='posts/{}.json'.format(post_id),
            thumbnail=poster,
            contentType='movie',
            infoLabels={
                'year': int(year) if year else '',
                'genre': genres,
                'code': imdb_id,
                'tmdb': tmdb_id,
                'duration': int(duration) if duration else '',
            }
        )
        itemlist.append(new_item)
    try:
        from concurrent import futures as _futures
        def _fetch_plot(it):
            try:
                d = _get_json(it.url)
                if d:
                    p = d.get('movie', {}).get('plot', '')
                    if p:
                        it.infoLabels['plot'] = p
            except Exception:
                pass
            return it
        with _futures.ThreadPoolExecutor(max_workers=5) as ex:
            itemlist = list(ex.map(_fetch_plot, itemlist))
    except Exception:
        pass
    return itemlist


@support.menu
def mainlist(item):
    film = ['/index',
        ('Genere', ['', 'genre', 'genre']),
    ]
    search = ''
    return locals()


def genre(item):
    nav = _get_nav()
    itemlist = []
    menus = nav.get('menus', {}).get('primary', [])
    for entry in menus:
        title = entry.get('title', '')
        url = entry.get('url', '').rstrip('/')
        children = entry.get('children', [])
        if title in ['Lista Film', 'Wall', 'Bacheca', 'FORUM']:
            continue
        if children:
            for child in children:
                child_title = child.get('title', '')
                child_url = child.get('url', '').rstrip('/')
                if child_url.startswith('https://hd4me.net'):
                    child_url = child_url.replace('https://hd4me.net', '')
                itemlist.append(item.clone(action='peliculas', title=child_title, url=child_url))
        else:
            if url.startswith('https://hd4me.net'):
                url = url.replace('https://hd4me.net', '')
            itemlist.append(item.clone(action='peliculas', title=title, url=url))
    support.thumb(itemlist, genre=True)
    return itemlist


def peliculas(item):
    page = getattr(item, 'page', 1) or 1
    url = item.url
    if url.startswith('http'):
        from urllib.parse import urlparse
        url = urlparse(url).path
    url_path = url.strip('/')

    if url_path.rstrip('/') in ('studio-ghibli', 'pixar'):
        slug = url_path.rstrip('/').split('/')[-1]
        if slug == 'pixar':
            data = _get_json('categoria/pixar/page-{}.json'.format(page))
            if not data:
                return []
            posts = data.get('posts', [])
            pagination = data.get('pagination', {})
            total_pages = pagination.get('total_pages', 1) if isinstance(pagination, dict) else 1
            itemlist = _posts_to_itemlist(item, posts)
            if page < total_pages:
                itemlist.append(item.clone(title='>> Pagina successiva', page=page + 1))
            return itemlist
        data = _get_json('pages/studio-ghibli.json')
        if not data:
            return []
        content = data.get('content', '')
        ghibli_titles = re.findall(r'&#8220;([^&#]+)\s*\(\d{4}\)[^&#]*&#8221;', content)
        if ghibli_titles:
            posts_data = _get_json('posts_data.json')
            if posts_data:
                itemlist = []
                for gtitle in ghibli_titles:
                    gtitle_clean = _clean_title(gtitle).strip().lower()
                    for entry in posts_data:
                        twy = _clean_title(entry.get('twy', '')).lower()
                        if gtitle_clean in twy or twy.startswith(gtitle_clean):
                            pid = entry.get('pid', '')
                            title = _clean_title(entry.get('twy', ''))
                            pure, yr = _pure_title(title)
                            poster_alt = entry.get('pa', '')
                            poster = 'https://image.tmdb.org/t/p/w300/{}.jpg'.format(poster_alt) if poster_alt else ''
                            itemlist.append(item.clone(
                                action='findvideos',
                                title=pure,
                                fulltitle=title,
                                url='posts/{}.json'.format(pid),
                                thumbnail=poster,
                                contentType='movie',
                                infoLabels={'year': int(yr) if yr else ''},
                            ))
                            break
                if itemlist:
                    return itemlist
        m = re.search(r'href="(https://mega\.nz/[^"]+)"', content)
        if m:
            return [item.clone(action='', title='[Apri cartella Mega nel browser]', url=m.group(1))]
        return []

    slug = url_path.split('/')[-1]

    if slug == 'classici-disney':
        data = _get_json('disney.json')
        if not data:
            return []
        return _posts_to_itemlist(item, data.get('items', []))

    path = '{}/page-{}.json'.format(url_path, page)
    data = _get_json(path)
    if not data:
        return []
    posts = data.get('posts', [])
    pagination = data.get('pagination', {})
    total_pages = pagination.get('total_pages', 1) if isinstance(pagination, dict) else 1
    itemlist = _posts_to_itemlist(item, posts)
    if page < total_pages:
        itemlist.append(item.clone(title='>> Pagina successiva', page=page + 1))
    return itemlist


def search(item, text):
    support.info(text)
    try:
        data = _get_json('posts_data.json')
        if not data:
            return []
        text_lower = text.lower()
        itemlist = []
        for entry in data:
            twy = _clean_title(entry.get('twy', ''))
            to = _clean_title(entry.get('to', ''))
            if text_lower in twy.lower() or text_lower in to.lower():
                pid = entry.get('pid', '')
                year = entry.get('y', '')
                rating = entry.get('rt', 0)
                imdb = entry.get('iid', '')
                poster_alt = entry.get('pa', '')
                poster = 'https://image.tmdb.org/t/p/w300/{}.jpg'.format(poster_alt) if poster_alt else ''
                pure, yr = _pure_title(twy or to)
                itemlist.append(item.clone(
                    action='findvideos',
                    title=pure,
                    fulltitle=twy or to,
                    url='posts/{}.json'.format(pid),
                    thumbnail=poster,
                    contentType='movie',
                    infoLabels={
                        'year': int(year) if year else '',
                        'code': 'tt' + imdb if imdb else '',
                        'rating': rating,
                    }
                ))
        return itemlist
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error('search except: %s' % line)
        return []


def findvideos(item):
    data = _get_json(item.url)
    if not data:
        return support.server(item, '')
    movie = data.get('movie', {})
    url = movie.get('test', '')
    if movie.get('poster') and not item.thumbnail:
        item.thumbnail = movie['poster']
    if movie.get('plot'):
        item.plot = movie['plot']
    if movie.get('imdb') and not item.infoLabels.get('code'):
        item.infoLabels['code'] = movie['imdb']
    if movie.get('tmdb') and not item.infoLabels.get('tmdb_id'):
        item.infoLabels['tmdb_id'] = movie['tmdb']
    if data.get('title') and not item.fulltitle:
        item.fulltitle = _clean_title(data['title'])
    return support.server(item, url)
