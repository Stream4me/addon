# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per La7
# ------------------------------------------------------------

import sys
import requests
from core import support, httptools
from platformcode import logger
from datetime import datetime, timezone, timedelta
import html
import re

if sys.version_info[0] >= 3:
    from concurrent import futures
    from urllib.parse import urlencode
else:
    from concurrent_py2 import futures
    from urllib import urlencode

DRM = 'com.widevine.alpha'
key_widevine = "https://la7.prod.conax.cloud/widevine/license"
host = 'https://www.la7.it'
headers = {
    'host_token': 'pat.la7.it',
    'host_license': 'la7.prod.conax.cloud',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36',
    'accept': '*/*',
    'accept-language': 'en,en-US;q=0.9,it;q=0.8',
    'dnt': '1',
    'te': 'trailers',
    'origin': 'https://www.la7.it',
    'referer': 'https://www.la7.it/',
}

@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live']),
            ('Replay {bold}', ['', 'replay_channels'])]

    menu = [('Programmi TV {bullet bold}', ['/tutti-i-programmi', 'peliculas', '', 'tvshow']),
            ('Teche La7 {bullet bold}', ['/la7teche', 'peliculas', '', 'tvshow'])]

    search = ''
    return locals()

def live(item):
    la7live_item = item.clone(title=support.typo('La7', 'bold'), fulltitle='La7', url= host + '/dirette-tv', action='findvideos', forcethumb = True, no_return=True)
    html_content = requests.get(la7live_item.url).text

    patron = r'"name":\s*"([^"]+)",\s*"description":\s*"([^"]+)",.*?"url":\s*"([^"]+)"'
    titolo, plot, image_url = re.findall(patron, html_content, re.DOTALL)[0]
    la7live_item.plot = support.typo(titolo, 'bold') + " - " + plot
    la7live_item.fanart = image_url
    
    la7dlive_item = item.clone(title=support.typo('La7d', 'bold'), fulltitle='La7d', url= host + '/live-la7d', action='findvideos', forcethumb = True, no_return=True)
    html_content = requests.get(la7dlive_item.url).text

    patron = r'<div class="orario">\s*(.*?)\s*</div>.*?<span class="dsk">\s*(.*?)\s*</span>'
    schedule = {k:v for k,v in re.findall(patron, html_content)}
    italy_tz = timezone(timedelta(hours=1))  # CET (Central European Time, UTC+1)

    current_time_utc = datetime.now(timezone.utc)  # Get current time in UTC
    italian_time = current_time_utc.astimezone(italy_tz).time()  # Convert to Italy time zone

    current_show = next((show for (t1, show), (t2, _) in zip(
        sorted((datetime.strptime(t, "%H:%M").time(), show) for t, show in schedule.items()),
        sorted((datetime.strptime(t, "%H:%M").time(), show) for t, show in schedule.items())[1:] + 
        sorted((datetime.strptime(t, "%H:%M").time(), show) for t, show in schedule.items())[:1]
    ) if t1 <= italian_time < t2), "No show currently playing.")

    la7dlive_item.plot = support.typo(current_show, 'bold')
    patron = r"(?<!//)\bposter:\s*['\"](.*?)['\"]"
    la7dlive_item.fanart = f'{host}{re.findall(patron, html_content)[0]}'


    itemlist = [la7live_item,
                la7dlive_item]
    return support.thumb(itemlist, live=True)


def replay_channels(item):
    itemlist = [item.clone(title=support.typo('La7', 'bold'), fulltitle='La7', url= host + '/rivedila7/0/la7', action='replay_menu', forcethumb = True),
                item.clone(title=support.typo('La7d', 'bold'), fulltitle='La7d', url= host + '/rivedila7/0/la7d', action='replay_menu', forcethumb = True)]
    itemlist = support.thumb(itemlist, live=True)
    itemlist.append(item.clone(title=support.typo('TG La7', 'bold'), fulltitle='TG La7', url= host + '/tgla7', action='episodios', thumbnail='https://tg.la7.it/sites/all/themes/bootstrap/img/logo_mod.svg'))
    return itemlist


@support.scrape
def replay_menu(item):
    action = 'replay'
    patron = r'href="(?P<url>[^"]+)"><div class="giorno-text">\s*(?P<day>[^>]+)</div><[^>]+>\s*(?P<num>[^<]+)</div><[^>]+>\s*(?P<month>[^<]+)<'
    def itemHook(item):
        item.title = support.typo(item.day + ' ' + item.num + ' ' + item.month,'bold')
        return item
    return locals()


@support.scrape
def replay(item):
    action = 'findvideos'
    patron = r'guida-tv"><[^>]+><[^>]+>(?P<hour>[^<]+)<[^>]+><[^>]+><[^>]+>\s*<a href="(?P<url>[^"]+)"><[^>]+><div class="[^"]+" data-background-image="(?P<t>[^"]+)"><[^>]+><[^>]+><[^>]+><[^>]+>\s*(?P<name>[^<]+)<[^>]+><[^>]+><[^>]+>(?P<plot>[^<]+)<'
    def itemHook(item):
        item.title = support.typo(item.hour + ' - ' + item.name,'bold')
        item.contentTitle = item.fulltitle = item.show = item.name
        item.thumbnail = 'http:' + item.t
        item.fanart = item.thumbnail
        item.forcethumb = True
        return item
    return locals()


def search(item, text):
    item.url = host + '/tutti-i-programmi'
    item.search = text
    try:
        return peliculas(item)
    except:
        import sys
        for line in sys.exc_info():
            support.info('search log:', line)
        return []


def peliculas(item):

    html_content = requests.get(item.url).text

    if 'la7teche' in item.url:
        patron = r'<a href="(?P<url>[^"]+)" title="(?P<title>[^"]+)" class="teche-i-img".*?url\(\'(?P<thumb>[^\']+)'
    else:
        patron = r'<a href="(?P<url>[^"]+)"[^>]+><div class="[^"]+" data-background-image="(?P<thumb>[^"]+)"></div><div class="titolo">\s*(?P<title>[^<]+)<'
    
    matches = re.findall(patron, html_content)
    url_splits = item.url.split('?')

    itemlist = []
    for n, key in enumerate(matches):
        if 'la7teche' in item.url:
            programma_url, titolo, thumb = key
        else:
            programma_url, thumb, titolo = key

        if not thumb.startswith("https://"):
            thumb = f'{host}/{thumb}'
        programma_url = f'{host}{programma_url}'
        titolo = html.unescape(titolo)

        it = item.clone(title=support.typo(titolo, 'bold'),
                    data='',
                    fulltitle=titolo,
                    show=titolo,
                    thumbnail= thumb,
                    url=programma_url,
                    video_url=programma_url,
                    order=n)
        it.action = 'episodios'
        it.contentSerieName = it.fulltitle

        itemlist.append(it)

    return itemlist


def episodios(item):
    if item.url.endswith('/tgla7'):
        html_content = requests.get('https://tg.la7.it/ultime-edizioni-del-tgla7').text
    else:
        html_content = requests.get(item.url).text

    itemlist = []
    matches = []
    
    if 'la7teche' in item.url:
        # patron = r'<a href="(?P<url>[^"]+)">\s*<div class="holder-bg">.*?data-background-image="(?P<thumb>[^"]+)(?:[^>]+>){4}\s*(?P<title>[^<]+)(?:(?:[^>]+>){2}\s*(?P<plot>[^<]+))?'
        patron = r'[^>]+>\s*<a href="(?P<url>[^"]+)">.*?image="(?P<thumb>[^"]+)(?:[^>]+>){4,5}\s*(?P<title>[\d\w][^<]+)(?:(?:[^>]+>){7}\s*(?P<title2>[\d\w][^<]+))?'
    elif 'tgla7' in item.url:
        # patron = r'<a href="(?P<url>[^"]+)"[^>]+data-bg="(?P<thumb>[^"]+)"[^>]*>[^>]*>(?P<title>[^<]+)</a>.*?<div class="news-descrizione">\s*(?P<plot>[^<]+)<'
        patron = r'<a href="(?P<url>[^"]+)"[^>]+data-bg="(?P<thumb>[^"]+)".*?</a>.*?<h4 class="news-title">\s*<a [^>]*>(?P<title>[^<]+)</a>.*?<div class="news-descrizione">\s*(?P<plot>[^<]+)\s*<'
    else:
        if len(item.url.split('www.la7.it')[-1].strip('/').split("/")) == 1:

            plot = re.search(r'<div class="testo">.*?</div>', html_content, re.DOTALL)[0]
            if plot:
                text = re.sub(r'<[^>]+>', '\n', plot)   # Replace tags with newline
                plot = re.sub(r'\n+', '\n', text).strip('\n')  # Collapse multiple newlines and remove leading/trailing ones
            else:
                plot = ""

            regex = r'background-image:url\((\'|")([^\'"]+)(\'|")\);'
            match = re.findall(regex, html_content)
            if match:
                fanart = match[0][1]
            else:
                fanart = ""

            patron = r'<li class="voce_menu">\s*<a href="([^"]+)"[^>]*>\s*([^<]+)\s*</a>\s*</li>'
            matches = re.findall(patron, html_content)

            result_dict = {text: href for href, text in matches}
            for k,v in result_dict.items():
                if(len(v.strip('/').split("/")) > 1):
                    v = f'{host}{v}'
                    new_item = item.clone(
                            title=support.typo(k, 'bold'),
                            data='',
                            fulltitle=k,
                            show=k,
                            url=v,
                            plot=plot,
                            fanart=fanart
                        )
                    itemlist.append(new_item)
            return itemlist
        else:
            patron = r'<div class="[^"]*">.*?<a href="(?P<url>[^"]+)">.*?data-background-image="(?P<image>//[^"]+)"[^>]*>.*?<div class="title[^"]*">\s*(?P<title>[^<]+)\s*</div>'
            html_content = html_content.split('<div class="view-content clearfix">')

        if "?page=" not in item.url: # if first page check for la settimana
            matches = re.findall(r'<div class="item">.*?<a href="(?P<url>[^"]+)">.*?data-background-image="(?P<image>//[^"]+)"[^>]*>.*?<div class="title[^"]*">\s*(?P<title>[^<]+)\s*</div>', html_content[0])
        html_content = html_content[-1]

    matches = matches + re.findall(patron, html_content, re.DOTALL)
    print(matches)

    visited = set()
    def itInfo(n, key, item):
        if 'la7teche' in item.url:
            programma_url, thumb, titolo, plot = key
        elif 'tgla7' in item.url:
            programma_url, thumb, titolo, plot = key
        else:
            programma_url, thumb, titolo = key
            plot = ""

        if programma_url in visited: return None

        visited.add(programma_url)
        programma_url = f'{host}{programma_url}'
        thumb = 'https://'+thumb[2:] if thumb.startswith("//") else thumb

        # not worth to make a request just to get the plot
        # plot_page = requests.get(programma_url).text
        # match = re.search(r'<div[^>]*class="[^"]*occhiello[^"]*"[^>]*>(.*?)</div>', plot_page)
        # if match:
        #     plot = match.group(1)
        # else:
        #     plot = ""
        titolo = html.unescape(titolo)
        it = item.clone(title=support.typo(titolo, 'bold'),
                    data='',
                    fulltitle=titolo,
                    show=titolo,
                    thumbnail= thumb,
                    url=programma_url,
                    video_url=programma_url,
                    plot = plot if plot != "" else item.plot,
                    order=n)
        it.action = 'findvideos'

        return it

    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(itInfo, n, it, item) for n, it in enumerate(matches)]
        for res in futures.as_completed(itlist):
            if res.result():
                itemlist.append(res.result())
    itemlist.sort(key=lambda it: it.order)


    pattern = r'<li class="pager-next"><a href="(.*?)">›</a></li>'
    match = re.search(pattern, html_content)
    if match:
        next_page_link = match.group(1)
        itemlist.append(
            item.clone(title=support.typo('Next', 'bold'),
                        url= f'{host}{match.group(1)}',
                        order=len(itemlist),
                        video_url='',
                        thumbnail=''
                )
            )

    return itemlist


def findvideos(item):
    support.info()
    if item.livefilter:
        for it in live(item):
            if it.fulltitle == item.livefilter:
                item = it
                break
    data = support.match(item).data

    url = support.match(data, patron=r'''["]?dash["]?\s*:\s*["']([^"']+)["']''').match

    if url:
        preurl = support.match(data, patron=r'preTokenUrl = "(.+?)"').match
        tokenHeader = {
            'host': headers['host_token'],
            'user-agent': headers['user-agent'],
            'accept': headers['accept'],
            'accept-language': headers['accept-language'],
            'dnt': headers['dnt'],
            'te': headers['te'],
            'origin': headers['origin'],
            'referer': headers['referer'],
        }
        preAuthToken = requests.get(preurl, headers=tokenHeader,verify=False).json()['preAuthToken']
        licenseHeader = {
            'host': headers['host_license'],
            'user-agent': headers['user-agent'],
            'accept': headers['accept'],
            'accept-language': headers['accept-language'],
            'preAuthorization': preAuthToken,
            'origin': headers['origin'],
            'referer': headers['referer'],
        }
        preLic= '&'.join(['%s=%s' % (name, value) for (name, value) in licenseHeader.items()])
        tsatmp=str(int(support.time()))
        license_url= key_widevine + '?d=%s'%tsatmp
        lic_url='%s|%s|R{SSM}|'%(license_url, preLic)
        item.drm = DRM
        item.license = lic_url
    else:
        match = support.match(data, patron=r'''["]?m3u8["]?\s*:\s*["']([^"']+)["']''').match
        if match:
            url = match.replace("http://la7-vh.akamaihd.net/i/", "https://awsvodpkg.iltrovatore.it/local/hls/").replace("csmil/master.m3u8", "urlset/master.m3u8");
    
    if url=="":
        url = support.match(data, patron=r'''["]?mp4["]?\s*:\s*["']([^"']+)["']''').match

    item = item.clone(title='Direct', server='directo', url=url, action='play')
    return support.server(item, itemlist=[item], Download=False, Videolibrary=False)
