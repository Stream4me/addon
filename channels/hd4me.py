# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per HD4ME - API JSON (SPA) + framework S4Me
# ------------------------------------------------------------

import json, html, re
from core import httptools, support

host = support.config.get_channel_url()
CACHE_BASE = 'https://hd4me.net/wp-content/themes/mytheme/cache/'
headers = [['Referer', host]]
_nav_cache = {}


def _get_nav():
    if _nav_cache:
        return _nav_cache
    resp = httptools.downloadpage(CACHE_BASE + 'nav.json', headers=headers)
    if not resp.data:
        return {}
    try:
        data_str = resp.data
        if isinstance(data_str, bytes):
            data_str = data_str.decode('utf-8-sig')
        elif isinstance(data_str, str) and data_str.startswith('\ufeff'):
            data_str = data_str[1:]
        _nav_cache.update(json.loads(data_str))
    except Exception as e:
        support.logger.error('hd4me: nav.json error: %s' % e)
    return _nav_cache


def _version():
    return _get_nav().get('version', '')


def _get_json(path):
    v = _version()
    url = (CACHE_BASE + path) + ('?v=%s' % v if v else '')
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
        support.logger.error('hd4me: JSON error %s: %s' % (path, e))
        return None


def _clean(t):
    return html.unescape(t) if t else ''


def _pure_title(full_title):
    full_title = _clean(full_title)
    m = re.match(r'^(.+?)\s*\((\d{4})\)', full_title)
    if m:
        return m.group(1).strip(), m.group(2)
    return full_title, ''


def _posts_to_itemlist(item, posts):
    """Converte lista post JSON in itemlist S4Me."""
    itemlist = []
    for info in posts:
        post_id = info.get('id', '')
        full_title = _clean(info.get('title', ''))
        movie = info.get('movie', {})
        title, year = _pure_title(full_title)
        if not year:
            years = movie.get('years', [])
            year = years[0].get('name', '') if years and isinstance(years[0], dict) else ''
        tmdb_raw = movie.get('tmdb', '')
        imdb_raw = movie.get('imdb', '')
        tmdb_id = int(tmdb_raw) if tmdb_raw and str(tmdb_raw).isdigit() else ''
        imdb_id = ('tt' + imdb_raw) if imdb_raw and not str(imdb_raw).startswith('tt') else imdb_raw
        poster = movie.get('poster', '')
        duration = movie.get('duration', '')
        genres = ', '.join(g.get('name', '') for g in movie.get('genres', []))
        new_item = item.clone(
            action='findvideos',
            title=title,
            fulltitle=full_title,
            contentTitle=title,
            url='posts/%s.json' % post_id,
            thumbnail=poster,
            contentType='movie',
            infoLabels={
                'year': int(year) if year else '',
                'genre': genres,
                'imdb_id': imdb_id,
                'tmdb_id': str(tmdb_id) if tmdb_id else '',
                'duration': int(duration) if duration else '',
            }
        )
        itemlist.append(new_item)
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


@support.scrape
def peliculas(item):
    page = getattr(item, 'page', 1) or 1
    url = item.url
    if url.startswith('http'):
        from urllib.parse import urlparse as _up
        url = _up(url).path
    url_path = url.strip('/')

    # Recupera il JSON corretto in base alla sezione
    slug = url_path.split('/')[-1]

    if slug == 'classici-disney':
        data = _get_json('disney.json')
        posts = data.get('items', []) if data else []
        total_pages = 1
    elif slug == 'pixar':
        data = _get_json('categoria/pixar/page-%d.json' % page)
        posts = data.get('posts', []) if data else []
        _pag_data = data.get('pagination', {}) if data else {}
        total_pages = _pag_data.get('total_pages', 1) if isinstance(_pag_data, dict) else 1
    elif slug == 'studio-ghibli':
        # Cerca nei posts_data i film Ghibli
        data = _get_json('pages/studio-ghibli.json')
        posts = []
        if data:
            content = data.get('content', '')
            ghibli_titles = re.findall(r'&#8220;([^&#]+)\s*\(\d{4}\)[^&#]*&#8221;', content)
            if ghibli_titles:
                posts_data = _get_json('posts_data.json') or []
                for gtitle in ghibli_titles:
                    gtitle_clean = _clean(gtitle).strip().lower()
                    for entry in posts_data:
                        twy = _clean(entry.get('twy', '')).lower()
                        if gtitle_clean in twy or twy.startswith(gtitle_clean):
                            pa = entry.get('pa', '')
                            posts.append({
                                'id': entry.get('pid', ''),
                                'title': _clean(entry.get('twy', '')),
                                'movie': {
                                    'poster': 'https://image.tmdb.org/t/p/w300/%s.jpg' % pa if pa else '',
                                    'imdb': entry.get('iid', ''),
                                }
                            })
                            break
        total_pages = 1
    else:
        data = _get_json('%s/page-%d.json' % (url_path, page))
        posts = data.get('posts', []) if data else []
        _pag_data = data.get('pagination', {}) if data else {}
        total_pages = _pag_data.get('total_pages', 1) if isinstance(_pag_data, dict) else 1

    # Costruisce itemlist dal JSON — usiamo itemlistHook per passarla al framework
    _built = _posts_to_itemlist(item, posts)

    # Aggiunge TMDB metadata
    try:
        from core import tmdb
        tmdb.set_infoLabels_itemlist(_built, seekTmdb=True)
    except Exception:
        pass

    # Paginazione manuale aggiunta all'itemlist
    if page < total_pages:
        _built.append(item.clone(
            title=support.typo(support.config.get_localized_string(30992), 'color std bold'),
            page=page + 1,
            thumbnail=support.thumb()
        ))

    def itemlistHook(lst):
        return _built

    # patron vuoto: nessun parsing HTML, tutto via itemlistHook
    patron = ''
    data = ' '
    pagination = 0
    action = 'findvideos'
    disabletmdb = True  # già fatto sopra
    return locals()


def search(item, text):
    support.info(text)
    try:
        data = _get_json('posts_data.json')
        if not data:
            return []
        text_lower = text.lower()
        itemlist = []
        for entry in data:
            twy = _clean(entry.get('twy', ''))
            to = _clean(entry.get('to', ''))
            if text_lower in twy.lower() or text_lower in to.lower():
                pid = entry.get('pid', '')
                year = entry.get('y', '')
                imdb = entry.get('iid', '')
                tmdb = str(entry.get('tid', '')) if entry.get('tid') else ''
                pa = entry.get('pa', '')
                poster = 'https://image.tmdb.org/t/p/w300/%s.jpg' % pa if pa else ''
                pure, yr = _pure_title(twy or to)
                itemlist.append(item.clone(
                    action='findvideos',
                    title=pure,
                    fulltitle=twy or to,
                    contentTitle=pure,
                    url='posts/%s.json' % pid,
                    thumbnail=poster,
                    contentType='movie',
                    infoLabels={
                        'year': int(year) if year else '',
                        'imdb_id': ('tt' + imdb) if imdb else '',
                        'tmdb_id': tmdb,
                    }
                ))
        try:
            from core import tmdb
            tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
        except Exception:
            pass
        return itemlist
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error('search except: %s' % line)
        return []


def findvideos(item):
    url = item.url
    # Normalizza URL assoluti salvati dalla videoteca
    if 'hd4me.net' in url and 'posts/' in url:
        m = re.search(r'posts/\d+\.json', url)
        if m:
            url = m.group(0)
    data = _get_json(url)
    if not data:
        return support.server(item, '')
    movie = data.get('movie', {})
    mega_url = movie.get('test', '')
    if movie.get('poster') and not item.thumbnail:
        item.thumbnail = movie['poster']
    if movie.get('plot'):
        item.plot = movie['plot']
    if movie.get('imdb') and not item.infoLabels.get('imdb_id'):
        imdb = movie['imdb']
        item.infoLabels['imdb_id'] = ('tt' + imdb) if not imdb.startswith('tt') else imdb
    if movie.get('tmdb') and not item.infoLabels.get('tmdb_id'):
        item.infoLabels['tmdb_id'] = str(movie['tmdb'])
    if data.get('title') and not item.fulltitle:
        item.fulltitle = _clean(data['title'])
    if not item.contentTitle and item.fulltitle:
        item.contentTitle = _pure_title(item.fulltitle)[0]
    support.logger.error('hd4me findvideos: url=%s imdb=%s tmdb=%s title=[%s]' % (
        item.url, item.infoLabels.get('imdb_id', ''), item.infoLabels.get('tmdb_id', ''), item.contentTitle))
    return support.server(item, mega_url)
