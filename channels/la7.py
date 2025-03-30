# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per La7
# ------------------------------------------------------------

import sys
from core import support, httptools
from platformcode import logger
from datetime import datetime, timezone, timedelta
import html
import json
import ssl

if sys.version_info[0] >= 3:
    from concurrent import futures
    from urllib.parse import urlencode
    import urllib.request as urllib_request
else:
    from concurrent_py2 import futures
    from urllib import urlencode
    import urllib2 as urllib_request  # urllib2 is used in Python 2

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
    la7dlive_item = item.clone(title=support.typo('La7d', 'bold'), fulltitle='La7d', url= host + '/live-la7d', action='findvideos', forcethumb = True, no_return=True)
    json_data = json.loads(httptools.downloadpage("https://www.la7.it/sites/default/files/la7_app_home_smarttv.json").data)
    if "fascia_dirette" in json_data:
        if 'la7' in json_data["fascia_dirette"]:
            titolo = json_data["fascia_dirette"]["la7"]["titolo"]
            la7live_item.plot = support.typo(titolo, 'bold') + " - " + json_data["fascia_dirette"]["la7"]["descrizione"]
            la7live_item.fanart = json_data["fascia_dirette"]["la7"]["url_locandina"]

        if 'la7d' in json_data["fascia_dirette"]:
            titolo = json_data["fascia_dirette"]["la7d"]["titolo"]
            la7dlive_item.plot = support.typo(titolo, 'bold') + " - " + json_data["fascia_dirette"]["la7d"]["descrizione"]
            la7dlive_item.fanart = json_data["fascia_dirette"]["la7d"]["url_locandina"]
    itemlist = [la7live_item, la7dlive_item]
    return support.thumb(itemlist, live=True)


def replay_channels(item):
    itemlist = [item.clone(title=support.typo('La7', 'bold'), fulltitle='La7', url= host + '/rivedila7/0/la7', action='replay_menu', forcethumb = True),
                item.clone(title=support.typo('La7d', 'bold'), fulltitle='La7d', url= host + '/rivedila7/0/la7d', action='replay_menu', forcethumb = True)]
    itemlist = support.thumb(itemlist, live=True)
    itemlist.append(item.clone(title=support.typo('TG La7', 'bold'), fulltitle='TG La7',
                               plot='Informazione a cura della redazione del TG LA7', url= host + '/tgla7', action='episodios',
                               thumbnail='https://raw.githubusercontent.com/Stream4me/media/refs/heads/master/resources/thumb/tg.png',
                               fanart='https://raw.githubusercontent.com/Stream4me/media/refs/heads/master/resources/thumb/tg.png'))
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
    html_content = httptools.downloadpage(item.url).data

    if 'la7teche' in item.url:
        patron = r'<a href="(?P<url>[^"]+)" title="(?P<title>[^"]+)" class="teche-i-img".*?url\(\'(?P<thumb>[^\']+)'
    else:
        tids = {'/fa-che-io-sia-lultima': '115013', '/100minuti': '115737', '/atelechiavi': '84090', '/ai-il-futuro': '114921', '/amarsi-un-po': '115239', '/amgstories': '112885',
             '/amoristonati': '79999', '/artbox': '104964', '/atlantide': '27381', '/atlantidefiles': '87126', '/barbero-risponde': '118666', '/bellitalia-in-viaggio': '102099',
             '/bellidentrobellifuori': '82353', '/bersaglio-mobile': '45819', '/bull': '115680', '/buongiornomondo': '119675', '/c-era-una-volta': '111648', '/cera-una-volta-il-novecento': '111932',
             '/cambio-cuoco': '75628', '/camera-con-vista': '81722', '/cercasiautodisperatamente': '82794', '/coffee-break': '27592', '/cristina-parodi-live': '27533',
             '/crozza': '25457', '/cuochi-e-fiamme': '33163', '/defining-class-since-1886': '114836', '/diciannovequaranta': '59402', '/dimartedi': '59403', '/dizionario-del-tempo-presente': '101035',
             '/donne-vittime-e-carnefici': '33198', '/donne-storie-che-ispirano': '96013', '/downton-abbey': '106972', '/drink-me-out': '86027', '/eccezionale-veramente': '69716',
             '/eccezionale-veramente-2017': '74976', '/eccezionale-veramente-ma-veramente': '72974', '/omnibus-edicola': '114491', '/effetti-personali': '33311', '/quirinale': '106765',
             '/elezioni': '32577', '/elezioni-amministrative-2021': '104639', '/elezioni-europee-2024': '117571', '/elezioni-politiche-2022': '109941', '/regionali2015': '65426',
             '/elezioni-regionali-2020': '94442', '/elezioni-usa': '95091', '/eqelements': '114288', '/euro-dieci': '117427', '/europost': '119993', '/eventi-live': '116094',
             '/speciali-ezio-mauro': '119401', '/facciaafaccia': '73973', '/famiglie-ditalia': '118714', '/film-e-fiction': '53050', '/food-maniac': '34470', '/webserie': '58781',
             '/fuori-di-gusto': '34408', '/fuorionda': '69092', '/futbol': '72814', '/gazzetta-sports-awards': '74693', '/gigawatt': '118659', '/guerrieri': '52614', '/gustibus': '64469',
             '/hawthorne': '85101', '/honestlygood': '82312', '/i-men%C3%B9-di-benedetta': '36443', '/i-responsabili': '109082', '/il-bello-delle-curve': '76901', '/il-boss-dei-comici': '67694',
             '/il-commissario-cordier': '53311', '/il-gusto-di-sapere': '91393', '/il-mondo-che-verr%C3%A0': '37129', '/il-palio-di-siena': '109478', '/ilpolliceverdesonoio': '68548',
              '/il-processo-di-biscardi': '112450', '/in-altre-parole': '114460', '/ricette-di-cucina': '58727', '/la-cucina-di-sonia': '97070', '/in-cucina-con-vissani': '42222', '/in-onda': '58737',
             '/in-treatment': '57985', '/in-tv': '42300', '/in-viaggio-con-barbero': '114442', '/inarrestabili': '58625', '/inchieste-da-fermo': '113584', '/indovina-cosa-sceglie-la-sposa': '75632',
             '/innovation': '36568', '/inseparabili': '101261', '/intanto': '101263', '/italia-fashion-show': '55904', '/josephineangegardien': '77994', '/kataklo': '90255', '/laria-che-tira': '38052',
             '/lariadestate': '66668', '/lerba-del-vicino': '56552', '/lingrediente-perfetto': '86510', '/lofficina-delle-erbe': '74825', '/lora-della-salute': '75316','/lunionefalaforza': '86454',
             '/la-caduta': '115146', '/le-copertine-di-crozza': '66697', '/la-corsa-al-voto': '109702', '/lafelicitanoneunatruffa': '82920', '/la-gabbia': '52618', '/la-gaia-scienza': '38026',
             '/la-mala-educaxxxion': '56214', '/la-mala-educaxxxion-la7d': '38317', '/la-torre-di-babele': '114981', '/la-torre-di-babele-doc': '118783', '/la7cult': '111885', '/la7-cult': '26075',
             '/la7magazine': '63005', '/la7ricorda': '83508', '/la7racconta': '72941', '/la7speciali': '102882', '/la7venti': '103095', '/le-invasioni-barbariche': '38071',
             '/le-parole-della-salute': '91908', '/libri-in-onda': '111130', '/like': '84156', '/linea-gialla': '38501', '/lingo': '109910', '/little-murders': '81521', '/magazine7': '64468',
             '/mamma-mia-che-settimana': '43996', '/marxisti-tendenza-groucho': '48797', '/meravigliosamente': '78387', '/meteo-della-sera': '93826', '/meteola7': '60540',
             '/mica-pizza-e-fichi': '86104', '/miss-italia': '52620', '/miss-marple': '109479', '/missione-natura': '42849', '/mode-e-modi': '58403', '/mondo-senza-fine': '54093',
             '/motorstorie': '111088', '/nene-e-margherita': '49131', '/niente-ferma-le-donne': '75540', '/non-ditelo-alla-sposa': '54990', '/nonelarena': '78932',
             '/oliver-stone-nuclear-now': '115049', '/omnibus': '43855', '/oroscopo': '53863', '/otto-e-mezzo': '45098', '/our-godfather': '85928', '/padre-brown': '109373', '/piazzapulita': '42851',
             '/pinkisgood': '78693', '/trash-it': '76993', '/propagandalive': '78368', '/quattrodonneeunfunerale': '54398', '/raffaella-carra': '103352', '/recital-di-corrado-guzzanti': '53862',
             '/rigenerazione': '115362', '/figworldcup': '84181', '/roshn-saudi-league': '114296', '/royal-wedding': '81166', '/sconosciuti': '116192', '/se-stasera-sono-qui': '45749',
             '/selfiefood': '79476', '/sempre-meglio-che-restare-a-casa': '112451', '/senti-chi-mangia': '92485', '/sfera': '71860', '/si-parla-di': '83927', '/skroll': '78278',
             '/specialguest': '66670', '/speciali': '55153', '/speciali-mentana': '45796', '/startupeconomy': '91462', '/storie-dellaltro-social': '112291', '/storie-di-grandi-chef': '42921',
             '/storie-di-palazzi': '110336', '/syusy-e-patrizio-news': '118758', '/tacco12enonsolo': '72605', '/taga-doc': '87967', '/tagada': '67838', '/taste-il-gusto-delleccellenza': '116662',
             '/tgla7': '52619', '/the-dr-oz-show': '87313', '/the-show-must-go-off': '42865', '/ti-ci-porto-io': '46132', '/trumpstory': '119618', '/un-dolce-da-maestro': '84410',
             '/una-giornata-particolare': '109868', '/uno-maggio-taranto-liberi-e-pensanti': '91830', '/uozzap': '81522', '/urban-scouters': '109003', '/vado-a-vivere-in-montagna': '85810',
             '/varcondicio': '79932', '/victor-victoria': '42868', '/voicetown': '100017', '/voto-piu-voto-meno': '119921', '/welovecinema': '60262', '/zeta': '46396'}
        program_details = {}
        def fetch_program_data(path, tid):
            url = f"https://www.la7.it/appla7/service_propertysmarttv?s=hbbtv&field_property_tid={tid}"
            try:
                data = json.loads(httptools.downloadpage(url).data)
                if data and isinstance(data, list):  # Ensure data is a non-empty list
                    item = data[0]
                    return path, {
                        "titolo": html.unescape(item.get("titolo", "")),
                        "testo": html.unescape(item.get("testo", "")),
                        "img": item.get("img", "").split('src="')[1].split('"')[0] if 'src="' in item.get("img", "") else "",
                        "img_verticale": item.get("img_verticale", "").split('src="')[1].split('"')[0] if 'src="' in item.get("img_verticale", "") else "",
                    }
            except Exception as e:
                return path, None  # Return None if request or parsing fails

        # Use ThreadPoolExecutor for parallel requests
        with futures.ThreadPoolExecutor() as executor:
            future_to_path = {executor.submit(fetch_program_data, path, tid): path for path, tid in tids.items()}
            
            for future in futures.as_completed(future_to_path):
                path, data = future.result()
                if data:
                    program_details[path] = data
        patron = r'<a href="(?P<url>[^"]+)"[^>]+><div class="[^"]+" data-background-image="(?P<thumb>[^"]+)"'

    match = support.match(html_content, patron=patron)
    matches = match.matches
    # url_splits = item.url.split('?')

    itemlist = []
    for n, key in enumerate(matches):
        if 'la7teche' in item.url:
            programma_url, titolo, thumb = key
            plot = ""
            fanart = ""
        else:
            programma_url, thumb = key
            if programma_url in program_details:
                pinfo = program_details[programma_url]
                titolo = pinfo['titolo'] if pinfo['titolo'] else " ".join(programma_url.replace("/", "").split('-')).title()
                plot = pinfo['testo']
                thumb = pinfo['img'] if pinfo['img'] else thumb
                fanart = pinfo['img_verticale']
            else:
                titolo = " ".join(programma_url.replace("/", "").split('-')).title()
                plot = ""
                fanart = ""

        if not thumb.startswith("https://"):
            thumb = f'{host}/{thumb}'
        programma_url = f'{host}{programma_url}'
        titolo = html.unescape(titolo)

        it = item.clone(title=support.typo(titolo, 'bold'),
                        data='',
                        fulltitle=titolo,
                        show=titolo,
                        plot = plot,
                        thumbnail=thumb,
                        fanart = fanart,
                        url=programma_url,
                        video_url=programma_url,
                        order=n)
        it.action = 'episodios'
        it.contentSerieName = it.fulltitle

        itemlist.append(it)

    return itemlist


def episodios(item):
    if item.url.endswith('/tgla7'):
        html_content = httptools.downloadpage('https://tg.la7.it/ultime-edizioni-del-tgla7').data
    else:
        html_content = httptools.downloadpage(item.url).data

    itemlist = []
    matches = []
    
    if 'la7teche' in item.url:
        patron = r'[^>]+>\s*<a href="(?P<url>[^"]+)">.*?image="(?P<thumb>[^"]+)(?:[^>]+>){4,5}\s*(?P<title>[\d\w][^<]+)(?:(?:[^>]+>){7}\s*(?P<title2>[\d\w][^<]+))?'
        html_content = html_content.split('id="block-system-main"')[1]
    elif 'tgla7' in item.url:
        patron = r'<a href="(?P<url>[^"]+)"[^>]+data-bg="(?P<thumb>[^"]+)".*?</a>.*?<h4 class="news-title">\s*<a [^>]*>(?P<title>[^<]+)</a>.*?<div class="news-descrizione">\s*(?P<plot>[^<]+)\s*<'
    else:
        if len(item.url.split('www.la7.it')[-1].strip('/').split("/")) == 1:
            
            match = support.match(html_content, patron=r'page-taxonomy-term-(\d+)')
            tid = match.matches[0] if match.matches else ""
            if tid:
                data = json.loads(httptools.downloadpage(f"https://www.la7.it/appla7/service_propertysmarttv?s=hbbtv&field_property_tid={tid}").data)
                if data and isinstance(data, list):  # Ensure data is a non-empty list
                    plot = html.unescape(data[0].get("testo", ""))
            else:
                plot = ""

            match = support.match(html_content, patron=r'background-image:url\((\'|")([^\'"]+)(\'|")\);')
            fanart = match.matches[0][1] if match.matches else ""

            match = support.match(html_content, patron=r'<li class="voce_menu">\s*<a href="([^"]+)"[^>]*>\s*([^<]+)\s*</a>\s*</li>')
            result_dict = {text: href for href, text in match.matches}
            for k,v in result_dict.items():
                if(len(v.strip('/').split("/")) > 1):
                    if not v.startswith('/') and not v.startswith('https://www.la7.it'):
                        continue
                    else:
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

            patron = r'<div class="item.*?"> <a href="(?P<url>[^"]+)"><div class="holder-bg">.*?data-background-image="(?P<image>(?:https?:)?//[^"]+)".*?<div class="(?:title|occhiello)[^"]*">\s*(?P<title>[^<]+)\s*</div>'
            match = support.match(html_content.split('<div class="subcontent">')[-1], patron=patron)
            matches.extend(match.matches)
        else:
            html_content = html_content.split('<div class="main-content-node">')[-1].split('<div class="right">')[0]

            # split on hidden pager and check what comes before it
            html_content = html_content.split('<div class="view-content clearfix">')
            if len(html_content) > 1:
                patron = r'<div class="[^"]*">.*?<a href="(?P<url>[^"]+)">.*?data-background-image="(?P<image>(?:https?:)?//[^"]+)"[^>]*>.*?<div class="title[^"]*">\s*(?P<title>[^<]+)\s*</div>'
                match = support.match(html_content[0], patron=patron)
                matches.extend(match.matches)

            # and after it
            html_content = html_content[-1]
            patron = r'<div class="[^"]*">.*?<a href="(?P<url>[^"]+)">.*?data-background-image="(?P<image>(?:https?:)?//[^"]+)"[^>]*>.*?<div class="title[^"]*">\s*(?P<title>[^<]+)\s*</div>'
            match = support.match(html_content, patron=patron)
            matches.extend(match.matches)

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
        programma_url = f'{"https://tg.la7.it" if "tgla7" in item.url else host}{programma_url}'
        thumb = 'https://'+thumb[2:] if thumb.startswith("//") else thumb

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

    original_length = len(itemlist)
    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(itInfo, n, it, item) for n, it in enumerate(matches)]
        for res in futures.as_completed(itlist):
            if res.result():
                itemlist.append(res.result())
    itemlist[original_length:] = sorted(itemlist[original_length:], key=lambda it: it.order)

    match = support.match(html_content, patron=r'<li class="pager-next"><a href="(.*?)">›</a></li>')
    if match.matches:
        next_page_link = match.matches[0]
        itemlist.append(
            item.clone(title=support.typo('Next', 'bold'),
                        url= f'{host}{next_page_link}',
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
        req = urllib_request.Request(preurl, headers=tokenHeader)
        with urllib_request.urlopen(req, context=ssl._create_unverified_context()) as response:
            data = json.load(response)  # Parse JSON response
        preAuthToken = data['preAuthToken']

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
