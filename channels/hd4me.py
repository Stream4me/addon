# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per HD4ME
# ------------------------------------------------------------

from core import httptools, support


host = support.config.get_channel_url()
headers = [['Referer', host]]


@support.menu
def mainlist(item):

    film = [('Genere', ['', 'genre'])]

    return locals()


@support.scrape
def peliculas(item):
    if item.args == 'alternative':
        pagination = ''
        patron = r'<a title="(?P<title>[^\(]+)\(\s*(?P<year>\d+)\)\s\D+(?P<quality>\d+p).{3}(?P<lang>[^ ]+).*?[^"]+"\s*href="(?P<url>[^"]+)'
    else:
        if not item.args == 'search': # pagination not works
            if not item.nextpage:
                item.page = 1
            else:
                item.page = item.nextpage

            if not item.parent_url:
                item.parent_url = item.url

            item.nextpage = item.page + 1
            nextPageUrl = "{}/page/{}".format(item.parent_url, item.nextpage)
            resp = httptools.downloadpage(nextPageUrl, only_headers = True)
            if (resp.code > 399): # no more elements
                nextPageUrl = ''

        patron = r'<article[^>]+>[^>]+>[^>]+>.*?href="(?P<url>[^"]+)[^>]+>(?P<title>[^<]+?)(\((?P<year>[0-9]{4})\)*).*?(?P<quality>\d+p).{3}(?P<lang>[^ ]+)'

    return locals()


@support.scrape
def genre(item):
    action = 'peliculas'
    blacklist =['prova ', 'Wall', 'Forum', 'Accedi', 'Lista film']
    patronMenu = r'<li\sid="menu-item.*?href="(?P<url>[^#"]+)">(?P<title>.*?)<'
    def itemHook(item):
        if item.fulltitle in ['Classici Disney', 'Studio Ghibli', 'Pixar']:
            item.args = 'alternative'
        return item

    return locals()


def search(item, text):
    support.info(text)
    item.url = host + '/?s=' + text
    item.args = 'search'
    try:
        return peliculas(item)
    # Cattura la eccezione così non interrompe la ricerca globle se il canale si rompe!
    except:
        import sys
        for line in sys.exc_info():
            support.logger.error("search except: %s" % line)
        return []


def findvideos(item):
    url = support.match(item, patron=r'class="bot1" .*?href="(?P<url>[^"]+)"', debug=False).match
    
    if not url.startswith('http'):
        url = host + url
    
    # Trasforma gli URL /?file/ in link Mega.nz diretti
    # Implementa la stessa logica del JavaScript nel sito
    if '/?file/' in url:
        # Estrae la parte dopo /?file/
        file_part = url.split('/?file/')[-1]
        # Converte ! in # e costruisce l'URL Mega
        url = 'https://mega.nz/file/' + file_part.replace('!', '#')
    elif '/?!' in url:
        # Formato alternativo
        file_part = url.split('/?!')[-1]
        url = 'https://mega.nz/file/' + file_part.replace('!', '#')
    
    return support.server(item, url)
