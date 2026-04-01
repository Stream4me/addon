# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
# httptools
# Based on code from https://github.com/alfa-addon/
# --------------------------------------------------------------------------------

try:
    import urllib.request as urllib
    import urllib.parse as urlparse
    import http.cookiejar as cookielib
except ImportError:
    import urllib, urlparse, cookielib

import os, time, json
from threading import Lock
from core.jsontools import to_utf8
from platformcode import config, logger
from core import scrapertools

# to surpress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Get the addon version
__version = config.get_addon_version()

cookies_lock = Lock()

cj = cookielib.MozillaCookieJar()
cookies_file = os.path.join(config.get_data_path(), "cookies.dat")

# Headers by default, if nothing is specified
default_headers = dict()
default_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%s.0.0.0 Safari/537.36" % config.get_setting("chrome_ua_version").split(".")[0]
default_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
default_headers["Accept-Language"] = "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3"
default_headers["Accept-Charset"] = "UTF-8"
default_headers["Accept-Encoding"] = "gzip"

# NOTA: Proxy workers disabilitati - si usa S4Me Assistant per il bypass CF
# cf_proxy_list = [{'url': 'quiet-base-584a.ifewfijdqwji.workers.dev', 'token': 'c48912u84u0238u82'},
#                  {'url': 'jfhofuhueshfuh.fmegvvon.workers.dev', 'token': 'h8fes78f4378hj9ufj'},
#                  {'url': 'u88929j98eijdjskfkls.lcbtcnob.workers.dev', 'token': 'nfdvsjnsd73ns82'}]

# direct IP access for some hosts
directIP = {
    'akki.monster': '31.220.1.77',
    'akvi.club': '31.220.1.77',
    'akvi.icu': '31.220.1.77',
    'akvideo.stream': '31.220.1.77',
    'vcrypt.net': '31.220.1.77',
    'vcrypt.pw': '31.220.1.77',
    # 'vidtome.host': '94.75.219.1',
    'nored.icu': '31.220.1.77',
    'wstream.icu': '31.220.1.77',
    'wstream.video': '31.220.1.77',
    'krask.xyz': '31.220.1.77',
}

# Maximum wait time for downloadpage, if nothing is specified
HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT = config.get_setting('httptools_timeout', default=5)
if HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT == 0: HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT = None

# Random use of User-Agents, if nad is not specified
HTTPTOOLS_DEFAULT_RANDOM_HEADERS = False


def get_user_agent():
    # Returns the global user agent to be used when necessary for the url.
    return default_headers["User-Agent"]

def get_url_headers(url, forced=False):
    domain = urlparse.urlparse(url)[1]
    sub_dom = scrapertools.find_single_match(domain, r'\.(.*?\.\w+)')
    if sub_dom and not 'google' in url:
        domain = sub_dom
    domain_cookies = cj._cookies.get("." + domain, {}).get("/", {})

    if "|" in url or not "cf_clearance" in domain_cookies:
        if not forced:
            return url

    headers = dict()
    headers["User-Agent"] = default_headers["User-Agent"]
    headers["Cookie"] = "; ".join(["%s=%s" % (c.name, c.value) for c in domain_cookies.values()])

    return url + "|" + "&".join(["%s=%s" % (h, urllib.quote(headers[h])) for h in headers])

def set_cookies(dict_cookie, clear=True, alfa_s=False):
    """
    View a specific cookie in cookies.dat
    @param dict_cookie: dictionary where the cookie parameters are obtained
        The dict must contain:
        name: cookie name
        value: its value / content
        domain: domain to which the cookie points
        optional:
        expires: life time in seconds, if not used add 1 day (86400s)
    @type dict_cookie: dict

    @param clear: True = delete cookies from the domain, before adding the new one (necessary for cloudproxy, cp)
                  False = disabled by default, just update the cookie
    @type clear: bool
    """

    # The cookie will be given a default day of life
    expires_plus = dict_cookie.get('expires', 86400)
    ts = int(time.time())
    expires = ts + expires_plus

    name = dict_cookie.get('name', '')
    value = dict_cookie.get('value', '')
    domain = dict_cookie.get('domain', '')

    # We delete existing cookies in that domain (cp)
    if clear:
        try:
            cj.clear(domain)
        except:
            pass

    ck = cookielib.Cookie(version=0, name=name, value=value, port=None,
                    port_specified=False, domain=domain,
                    domain_specified=False, domain_initial_dot=False,
                    path='/', path_specified=True, secure=False,
                    expires=expires, discard=True, comment=None, comment_url=None,
                    rest={'HttpOnly': None}, rfc2109=False)

    cj.set_cookie(ck)
    save_cookies()

def load_cookies(alfa_s=False):
    cookies_lock.acquire()
    if os.path.isfile(cookies_file):
        if not alfa_s: logger.info("Reading cookies file")
        try:
            cj.load(cookies_file, ignore_discard=True)
        except:
            if not alfa_s: logger.info("The cookie file exists but is illegible, it is deleted")
            os.remove(cookies_file)
    cookies_lock.release()

load_cookies()

def save_cookies(alfa_s=False):
    cookies_lock.acquire()
    if not alfa_s: logger.debug("Saving cookies...")
    cj.save(cookies_file, ignore_discard=True)
    cookies_lock.release()


def random_useragent():
    """
    Based on code from https://github.com/theriley106/RandomHeaders
    Python Method that generates fake user agents with a locally saved DB (.csv file).
    This is useful for webscraping, and testing programs that identify devices based on the user agent.
    """

    import random

    UserAgentPath = os.path.join(config.get_runtime_path(), 'tools', 'UserAgent.csv')
    if os.path.exists(UserAgentPath):
        UserAgentIem = random.choice(list(open(UserAgentPath))).strip()
        if UserAgentIem:
            return UserAgentIem

    return default_headers["User-Agent"]


def show_infobox(info_dict):
    logger.debug()
    from textwrap import wrap

    box_items_kodi = {'r_up_corner': u'\u250c',
                      'l_up_corner': u'\u2510',
                      'center': u'\u2502',
                      'r_center': u'\u251c',
                      'l_center': u'\u2524',
                      'fill': u'\u2500',
                      'r_dn_corner': u'\u2514',
                      'l_dn_corner': u'\u2518',
                      }

    box_items = {'r_up_corner': '+',
                 'l_up_corner': '+',
                 'center': '|',
                 'r_center': '+',
                 'l_center': '+',
                 'fill': '-',
                 'r_dn_corner': '+',
                 'l_dn_corner': '+',
                 }



    width = 100
    version = '%s: %s' % (config.get_localized_string(20000), __version)
    if config.is_xbmc():
        box = box_items_kodi
    else:
        box = box_items

    logger.debug('%s%s%s' % (box['r_up_corner'], box['fill'] * width, box['l_up_corner']))
    logger.debug('%s%s%s' % (box['center'], version.center(width), box['center']))
    logger.debug('%s%s%s' % (box['r_center'], box['fill'] * width, box['l_center']))

    count = 0
    for key, value in info_dict:
        count += 1
        text = '%s: %s' % (key, value)

        if len(text) > (width - 2):
            text = wrap(text, width)
        else:
            text = text.ljust(width, ' ')
        if isinstance(text, list):
            for line in text:
                if len(line) < width:
                    line = line.ljust(width, ' ')
                logger.debug('%s%s%s' % (box['center'], line, box['center']))
        else:
            logger.debug('%s%s%s' % (box['center'], text, box['center']))
        if count < len(info_dict):
            logger.debug('%s%s%s' % (box['r_center'], box['fill'] * width, box['l_center']))
        else:
            logger.debug('%s%s%s' % (box['r_dn_corner'], box['fill'] * width, box['l_dn_corner']))
    return



def downloadpage(url, **opt):
    # logger.info()
    """
       Open a url and return the data obtained

        @param url: url to open.
        @type url: str
        @param post: If it contains any value, it is sent by POST.
        @type post: str
        @param headers: Headers for the request, if it contains nothing the default headers will be used.
        @type headers: dict, list
        @param timeout: Timeout for the request.
        @type timeout: int
        @param follow_redirects: Indicates if redirects are to be followed.
        @type follow_redirects: bool
        @param cookies: Indicates whether cookies are to be used.
        @type cookies: bool
        @param replace_headers: If True, headers passed by the "headers" parameter will completely replace the default headers.
                                If False, the headers passed by the "headers" parameter will modify the headers by default.
        @type replace_headers: bool
        @param add_referer: Indicates whether to add the "Referer" header using the domain of the url as a value.
        @type add_referer: bool
        @param only_headers: If True, only headers will be downloaded, omitting the content of the url.
        @type only_headers: bool
        @param random_headers: If True, use the method of selecting random headers.
        @type random_headers: bool
        @param ignore_response_code: If True, ignore the method for WebErrorException for error like 404 error in veseriesonline, but it is a functional data
        @type ignore_response_code: bool
        @return: Result of the petition
        @rtype: HTTPResponse
        @param use_requests: Use requests.session()
        @type: bool

                Parameter Type Description
                -------------------------------------------------- -------------------------------------------------- ------------
                HTTPResponse.success: bool True: Request successful | False: Error when making the request
                HTTPResponse.code: int Server response code or error code if an error occurs
                HTTPResponse.error: str Description of the error in case of an error
                HTTPResponse.headers: dict Dictionary with server response headers
                HTTPResponse.data: str Response obtained from server
                HTTPResponse.json: dict Response obtained from the server in json format
                HTTPResponse.time: float Time taken to make the request

        """
    url = scrapertools.unescape(url)
    parse = urlparse.urlparse(url)
    domain = parse.netloc

    # S4Me: se il dominio ha un fallback (es. 1337x.to -> x1337x.cc),
    # riscrive l'URL al dominio effettivo
    try:
        from core import s4me_assistant
        if s4me_assistant.is_enabled():
            effective = s4me_assistant.get_effective_domain(domain)
            if effective != domain:
                url = url.replace(domain, effective, 1)
                parse = urlparse.urlparse(url)
                domain = parse.netloc
                logger.info("S4Me: URL riscritto: %s -> %s" % (domain, effective))
    except Exception as e:
        logger.error("S4Me: errore rewrite URL: %s" % str(e))

    if opt.get('cloudscraper'):
        from lib import cloudscraper
        session = cloudscraper.create_scraper()
    else:
        from lib import requests
        session = requests.session()

        if not opt.get('use_requests', False):
            from core import resolverdns
            session.mount('https://', resolverdns.CipherSuiteAdapter(domain=domain, override_dns=config.get_setting('resolver_dns')))

    req_headers = default_headers.copy()

    # Headers passed as parameters
    if opt.get('headers', None) is not None:
        opt['headers'] = dict(opt['headers'])
        if not opt.get('replace_headers', False):
            req_headers.update(opt['headers'])
        else:
            req_headers = opt['headers']

    if domain in directIP.keys() and not opt.get('disable_directIP', False):
        req_headers['Host'] = domain
        url = urlparse.urlunparse(parse._replace(netloc=directIP.get(domain)))

    if opt.get('random_headers', False) or HTTPTOOLS_DEFAULT_RANDOM_HEADERS:
        req_headers['User-Agent'] = random_useragent()

    # S4Me Assistant: pre-carica cookie CF e User-Agent per questo dominio
    # Funziona sia in locale che in remoto (l'app ora risolve con l'UA di Kodi)
    if not opt.get('_s4me_ua_checked'):
        try:
            from core import s4me_assistant
            if s4me_assistant.is_enabled():
                s4me_assistant.load_domain_cookies(domain)
                opt['_s4me_ua_checked'] = True
                # In remoto, l'UA globale e gia quello di Kodi (non serve cambiarlo)
                # In locale, load_domain_cookies aggiorna default_headers con l'UA della WebView
                req_headers['User-Agent'] = default_headers['User-Agent']
        except ImportError:
            pass
        except Exception:
            pass

    url = urllib.quote(url, safe="%/:=&?~#+!$,;'@()*[]")

    opt['url_save'] = url
    opt['post_save'] = opt.get('post', None)

    response = {}
    info_dict = []
    payload = dict()
    files = {}
    file_name = ''

    session.verify = opt.get('verify', True)

    if opt.get('cookies', True):
        session.cookies = cj
    session.headers.update(req_headers)

    proxy_data = {'dict': {}}

    inicio = time.time()

    if opt.get('timeout', None) is None and HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT is not None:
        opt['timeout'] = HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT
    if opt['timeout'] == 0: opt['timeout'] = None

    if len(url) > 0:
        try:
            if opt.get('post', None) is not None or opt.get('file', None) is not None:
                if opt.get('post', None) is not None:
                    # Convert string post in dict
                    try:
                        json.loads(opt['post'])
                        payload = opt['post']
                    except:
                        if not isinstance(opt['post'], dict):
                            post = urlparse.parse_qs(opt['post'], keep_blank_values=1)
                            payload = dict()

                            for key, value in post.items():
                                try:
                                    payload[key] = value[0]
                                except:
                                    payload[key] = ''
                        else:
                            payload = opt['post']

                # Verify 'file' and 'file_name' options to upload a buffer or file
                if opt.get('file', None) is not None:
                    if os.path.isfile(opt['file']):
                        if opt.get('file_name', None) is None:
                            path_file, opt['file_name'] = os.path.split(opt['file'])
                        files = {'file': (opt['file_name'], open(opt['file'], 'rb'))}
                        file_name = opt['file']
                    else:
                        files = {'file': (opt.get('file_name', 'Default'), opt['file'])}
                        file_name = opt.get('file_name', 'Default') + ', Buffer de memoria'

                info_dict = fill_fields_pre(url, opt, proxy_data, file_name)
                if opt.get('only_headers', False):
                    # Makes the request with HEAD method
                    req = session.head(url, allow_redirects=opt.get('follow_redirects', True),
                                       timeout=opt['timeout'])
                else:
                    # Makes the request with POST method
                    req = session.post(url, data=payload, allow_redirects=False,
                                       files=files, timeout=opt['timeout'])
                    # Make sure it follows redirects
                    i = 10
                    while opt.get('follow_redirects', True) and i > 0 and req.status_code == 301:
                        req = session.post(req.headers['Location'], data=payload, allow_redirects=False,
                                           files=files, timeout=opt['timeout'])
                        i -= 1

            elif opt.get('only_headers', False):
                info_dict = fill_fields_pre(url, opt, proxy_data, file_name)
                # Makes the request with HEAD method
                req = session.head(url, allow_redirects=opt.get('follow_redirects', True),
                                   timeout=opt['timeout'])
            else:
                info_dict = fill_fields_pre(url, opt, proxy_data, file_name)
                # Makes the request with GET method
                req = session.get(url, allow_redirects=opt.get('follow_redirects', True),
                                  timeout=opt['timeout'])
        except Exception as e:
            from lib import requests
            req = requests.Response()
            if not opt.get('ignore_response_code', False) and not proxy_data.get('stat', ''):
                # --- S4Me: se errore di connessione, potrebbe servire risolvere CF prima ---
                if not opt.get('_s4me_retry'):
                    try:
                        from core import s4me_assistant
                        if s4me_assistant.is_enabled():
                            error_str = str(e).lower()
                            if 'name' in error_str or 'resolve' in error_str or 'connection' in error_str:
                                logger.info("S4Me: errore connessione per %s, tento risoluzione CF" % domain)
                                if s4me_assistant.ensure_domain_ready(domain):
                                    s4me_assistant.load_domain_cookies(domain, force=True)
                                    s4me_ua = s4me_assistant.get_domain_user_agent(domain)
                                    if s4me_ua:
                                        if 'headers' not in opt:
                                            opt['headers'] = {}
                                        opt['headers']['User-Agent'] = s4me_ua
                                    opt['_s4me_retry'] = True
                                    return downloadpage(opt['url_save'], **opt)
                    except Exception:
                        pass
                # --- Fine S4Me ---
                response['data'] = ''
                response['success'] = False
                info_dict.append(('Success', 'False'))
                import traceback
                response['code'] = traceback.format_exc()
                info_dict.append(('Response code', str(e)))
                info_dict.append(('Finished in', time.time() - inicio))
                if not opt.get('alfa_s', False):
                    show_infobox(info_dict)
                return type('HTTPResponse', (), response)
            else:
                req.status_code = str(e)

    else:
        response['data'] = ''
        response['success'] = False
        response['code'] = ''
        return type('HTTPResponse', (), response)

    response_code = req.status_code
    response['url'] = req.url

    response['data'] = req.content if req.content else ''

    if type(response['data']) != str:
        try:
            response['data'] = response['data'].decode('utf-8')
        except:
            response['data'] = response['data'].decode('ISO-8859-1')

    if req.headers.get('Server', '').startswith('cloudflare') and response_code in [429, 503, 403]\
            and not opt.get('CF', False) and not opt.get('post', None):
        # NOTA: Proxy workers disabilitati - non piu funzionanti
        # Per riabilitare, decommentare il blocco sotto e la cf_proxy_list in alto
        # if 'Px-Host' in req_headers:  # first try with proxy
        #     logger.debug("CF retry with google translate for domain: %s" % domain)
        #     from lib import proxytranslate
        #     gResp = proxytranslate.process_request_proxy(opt.get('real-url', url))
        #     if gResp:
        #         req = gResp['result']
        #         response_code = req.status_code
        #         response['url'] = gResp['url']
        #         response['data'] = gResp['data']
        # else:
        #     logger.debug("CF retry with proxy for domain: %s" % domain)
        #     from random import choice
        #     cf_proxy = choice(cf_proxy_list)
        #     if not opt.get('headers'):
        #         opt['headers'] = {}
        #     opt['headers']['Px-Host'] = domain
        #     opt['headers']['Px-Token'] = cf_proxy['token']
        #     opt['real-url'] = url
        #     ret = downloadpage(urlparse.urlunparse((parse.scheme, cf_proxy['url'], parse.path, parse.params, parse.query, parse.fragment)), **opt)
        #     ret.url = url
        #     return ret
        logger.info("CloudFlare rilevato per %s - proxy workers disabilitati, in attesa di S4Me Assistant" % domain)

    # --- S4Me Assistant: retry dopo protezione CF ---
    if response_code in [403, 429, 503] and not opt.get('_s4me_retry') and not opt.get('CF'):
        try:
            from core import s4me_assistant
            if s4me_assistant.is_enabled():
                if s4me_assistant.handle_protection_retry(url, response_code, response['data'], opt):
                    logger.info("S4Me: retry per %s dopo risoluzione CF" % domain)
                    s4me_assistant.load_domain_cookies(domain, force=True)
                    s4me_ua = s4me_assistant.get_domain_user_agent(domain)
                    if s4me_ua:
                        if 'headers' not in opt:
                            opt['headers'] = {}
                        opt['headers']['User-Agent'] = s4me_ua
                    opt['_s4me_retry'] = True
                    return downloadpage(opt['url_save'], **opt)
        except ImportError:
            pass
        except Exception as e:
            logger.error("S4Me retry error: %s" % str(e))
    # --- Fine S4Me Assistant ---

    if not response['data']:
        response['data'] = ''

    try:
        response['json'] = to_utf8(req.json())
    except:
        response['json'] = dict()

    response['code'] = response_code
    response['headers'] = req.headers
    response['cookies'] = req.cookies

    info_dict, response = fill_fields_post(info_dict, req, response, req_headers, inicio)

    if opt.get('cookies', True):
        save_cookies(alfa_s=opt.get('alfa_s', False))

    if not 'api.themoviedb' in url and not opt.get('alfa_s', False):
        show_infobox(info_dict)
    if not config.get_setting("debug"): logger.info('Page URL:',url)
    return type('HTTPResponse', (), response)

def fill_fields_pre(url, opt, proxy_data, file_name):
    info_dict = []

    try:
        info_dict.append(('Timeout', opt['timeout']))
        info_dict.append(('URL', url))
        info_dict.append(('Domain', urlparse.urlparse(url)[1]))
        if opt.get('post', None):
            info_dict.append(('Petition', 'POST' + proxy_data.get('stat', '')))
        else:
            info_dict.append(('Petition', 'GET' + proxy_data.get('stat', '')))
        info_dict.append(('Download Page', not opt.get('only_headers', False)))
        if file_name: info_dict.append(('Upload File', file_name))
        info_dict.append(('Use cookies', opt.get('cookies', True)))
        info_dict.append(('Cookie file', cookies_file))
    except:
        import traceback
        logger.error(traceback.format_exc(1))

    return info_dict


def fill_fields_post(info_dict, req, response, req_headers, inicio):
    try:
        info_dict.append(('Cookies', req.cookies))
        info_dict.append(('Data Encoding', req.encoding))
        info_dict.append(('Response code', response['code']))

        if response['code'] == 200:
            info_dict.append(('Success', 'True'))
            response['success'] = True
        else:
            info_dict.append(('Success', 'False'))
            response['success'] = False

        info_dict.append(('Response data length', len(response['data'])))

        info_dict.append(('Request Headers', ''))
        for header in req_headers:
            info_dict.append(('- %s' % header, req_headers[header]))

        info_dict.append(('Response Headers', ''))
        for header in response['headers']:
            info_dict.append(('- %s' % header, response['headers'][header]))
        info_dict.append(('Finished in', time.time() - inicio))
    except:
        import traceback
        logger.error(traceback.format_exc(1))

    return info_dict, response
