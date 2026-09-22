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
    """
    Estrae il titolo pulito dal nome del torrent per TMDB.
    Gestisce film, serie TV e stagioni complete.
    """
    titolo = title

    # 1. Serie TV: pattern S01E03 / S01 / 1x05 / Season 2 / Stagione 2
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
        # 2. Film: prendi tutto prima dell'anno
        m = re.match(r'^(.+?)\s*[\(\[]?(?:19|20)\d{2}[\)\]]?', title)
        if m:
            titolo = m.group(1)

    # 3. Sostituisci punti con spazi
    titolo = titolo.replace('.', ' ')

    # 4. Rimuovi anno finale residuo
    titolo = re.sub(r'\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$', '', titolo)

    # 5. Rimuovi separatori finali orfani
    titolo = re.sub(r'[\s\.\-_\[\]\(\)]+$', '', titolo)

    return titolo.strip()


def search(item, text):
    logger.info("text=" + text)
    itemlist = []

    # ⭐ Replica ilcorsaronero: segna che è una ricerca
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
        if not torrent.get('name'):
            continue

        title = torrent['name']
        info_hash = torrent.get('info_hash', '')
        seeds = int(torrent.get('seeders') or 0)
        leech = int(torrent.get('leechers') or 0)
        size_bytes = int(torrent.get('size') or 0)

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

        # Titolo pulito per TMDB
        title_clean = estrai_titolo(title)

        new_item = item.clone(
            title=title_formatted,
            url=magnet,
            action="findvideos",
            server="torrent",
            folder=False,
            contentTitle=title_clean,    # <-- SOLO titolo pulito
            # NIENTE contentType → S4Me usa 'undefined' di default
            # NIENTE infoLabels → li crea S4Me
            # NIENTE year → non forzato
            info_hash=info_hash,
            seeders=seeds,
            leechers=leech,
            size=size
        )

        itemlist.append(new_item)

    # --- Arricchimento TMDB (come fa @support.scrape automaticamente) ---
    if itemlist and config.get_setting('tmdb_active'):
        try:
            tmdb.set_infoLabels(itemlist, seekTmdb=True)
        except Exception as e:
            logger.error("Errore arricchimento TMDB: %s" % str(e))

    itemlist.sort(key=lambda x: int(x.seeders) if hasattr(x, 'seeders') else 0, reverse=True)

    # --- Paginazione SOLO se la query contiene "user:" ---
    if "user:" in text:
        next_page = page + 1
        check_url = "https://apibay.org/q.php?q=%s:%s" % (urllib.parse.quote(text), next_page)
        check_data = httptools.downloadpage(check_url).data

        if check_data:
            try:
                check_torrents = json.loads(check_data)
                if len(check_torrents) > 0:
                    next_item = item.clone(
                        title="[COLOR FF65B3DA]Successivo >[/COLOR]",
                        page=next_page,
                        action="search",
                        folder=False,
                        thumbnail=''
                    )
                    next_item.text = text
                    itemlist.append(next_item)
                    logger.info("Aggiunta pagina successiva: %s" % next_page)
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