# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per The Pirate Bay
# ------------------------------------------------------------

import json
import urllib.parse
import re

from core import support, httptools, tmdb
from platformcode import logger, config

host = ''


@support.menu
def mainlist(item):
    search = ''
    return locals()


def estrai_titolo(title):
    titolo = title

    m = re.search(
        r'\s*(?:'
        r'S\d{1,2}(?:E\d{1,3})?'
        r'|\d{1,2}x\d{1,3}'
        r'|[Ss]eason\s*\d{1,2}'
        r'|[Ss]tagione\s*\d{1,2}'
        r'|[Ss]\d{1,2}\s*-\s*[Ee]?\d{1,3}'
        r')\b',
        title
    )
    if m:
        titolo = title[:m.start()]
    else:
        m = re.match(r'^(.+?)\s*[\(\[]?(?:19|20)\d{2}[\)\]]?', title)
        if m:
            titolo = m.group(1)

    titolo = titolo.replace('.', ' ')
    titolo = re.sub(r'\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$', '', titolo)
    titolo = re.sub(r'[\s\.\-_\[\]\(\)]+$', '', titolo)

    return titolo.strip()


def categoria_to_contentType(category):
    try:
        cat = int(category)
    except (ValueError, TypeError):
        return 'undefined'

    if cat in (201, 202, 204, 207, 209, 211):
        return 'movie'

    if cat in (205, 208, 212):
        return 'tvshow'

    return 'undefined'


def is_musica(category):
    try:
        cat = int(category)
    except (ValueError, TypeError):
        return False
    return cat in (100, 101, 102, 103, 104, 199)


def next_page(item):
    """Gestisce la pagina successiva senza aprire il campo di ricerca."""
    text = getattr(item, 'search', '') or ''
    if not text:
        logger.error("Nessun testo per pagina successiva")
        return []
    return search(item, text)


def search(item, text):
    if not text:
        if hasattr(item, 'search') and item.search:
            text = item.search
        elif hasattr(item, 'args') and item.args and isinstance(item.args, str):
            text = item.args

    logger.info("text=" + text)
    itemlist = []

    if not text:
        logger.error("Nessun testo di ricerca")
        return itemlist

    item.args = 'search'

    page = item.page if hasattr(item, 'page') and item.page else 0

    if page > 0:
        api_url = "https://apibay.org/q.php?q=%s:%s" % (urllib.parse.quote(text), page)
    else:
        api_url = "https://apibay.org/q.php?q=%s" % urllib.parse.quote(text)

    logger.info("API URL: %s" % api_url)

    data = httptools.downloadpage(api_url).data

    if not data:
        logger.error("Nessun dato ricevuto")
        return itemlist

    try:
        torrents = json.loads(data)
        logger.info("Torrents trovati: %s" % len(torrents))
    except Exception as e:
        logger.error("Errore parsing JSON: %s" % str(e))
        return itemlist

    if not isinstance(torrents, list):
        return itemlist

    for torrent in torrents:
        if torrent.get('id') == '0':
            continue
        if torrent.get('info_hash') == '0000000000000000000000000000000000000000':
            continue
        if not torrent.get('name'):
            continue
        if torrent.get('name', '').strip().lower() == 'no results returned':
            continue

        title = torrent['name']
        info_hash = torrent.get('info_hash', '')
        seeds = int(torrent.get('seeders') or 0)
        leech = int(torrent.get('leechers') or 0)
        size_bytes = int(torrent.get('size') or 0)
        category = torrent.get('category', '')

        magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, urllib.parse.quote(title))
        size = format_size(size_bytes)

        if seeds >= 100:
            seed_color = '[COLOR green]%s[/COLOR]' % seeds
        elif seeds >= 50:
            seed_color = '[COLOR yellow]%s[/COLOR]' % seeds
        elif seeds >= 10:
            seed_color = '[COLOR orange]%s[/COLOR]' % seeds
        else:
            seed_color = '[COLOR red]%s[/COLOR]' % seeds

        title_formatted = "%s [S:%s L:%s] [%s]" % (title, seed_color, leech, size)

        title_clean = estrai_titolo(title)

        if is_musica(category):
            new_item = item.clone(
                title=title_formatted,
                url=magnet,
                action="findvideos",
                server="torrent",
                folder=False,
                info_hash=info_hash,
                seeders=seeds,
                leechers=leech,
                size=size
            )
        else:
            content_type = categoria_to_contentType(category)

            if content_type == 'tvshow':
                info_labels = {'tvshowtitle': title_clean}
            else:
                info_labels = {'title': title_clean}

            new_item = item.clone(
                title=title_formatted,
                url=magnet,
                action="findvideos",
                server="torrent",
                folder=False,
                contentTitle=title_clean,
                contentType=content_type,
                infoLabels=info_labels,
                category=category,
                info_hash=info_hash,
                seeders=seeds,
                leechers=leech,
                size=size
            )

        itemlist.append(new_item)

    if itemlist and config.get_setting('tmdb_active'):
        try:
            items_tmdb = [it for it in itemlist if getattr(it, 'contentTitle', '')]
            if items_tmdb:
                tmdb.set_infoLabels(items_tmdb, seekTmdb=True)
        except Exception as e:
            logger.error("Errore arricchimento TMDB: %s" % str(e))

    itemlist.sort(key=lambda x: int(x.seeders) if hasattr(x, 'seeders') else 0, reverse=True)

    if "user:" in text:
        next_page_num = page + 1
        check_url = "https://apibay.org/q.php?q=%s:%s" % (urllib.parse.quote(text), next_page_num)
        check_data = httptools.downloadpage(check_url).data

        if check_data:
            try:
                check_torrents = json.loads(check_data)
                if len(check_torrents) > 0:
                    next_item = item.clone(
                        title="[COLOR FF65B3DA]Successivo >[/COLOR]",
                        page=next_page_num,
                        action="next_page",
                        folder=True,
                        thumbnail='',
                        search=text
                    )
                    itemlist.append(next_item)
            except:
                pass

    return itemlist


def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"

    size = float(size_bytes)
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    return "%.1f %s" % (size, units[unit_index])


def findvideos(item):
    if hasattr(item, 'info_hash'):
        logger.info("Riproduzione torrent: %s" % item.info_hash)

    return support.server(item, item.url)