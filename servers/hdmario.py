# -*- coding: utf-8 -*-
import xbmc

from core import httptools, scrapertools, filetools
from platformcode import logger, config, platformtools
from lib.fakeMail import Gmailnator

baseUrl = 'https://hdmario.live'

def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    global page, data

    page = httptools.downloadpage(page_url)
    data = page.data
    logger.debug(page.url)

    if "the page you are looking for could not be found" in data:
        return False, config.get_localized_string(70449) % "HDmario"
    return True, ""


def login():
    r = httptools.downloadpage(page.url.replace('/unauthorized', '/login'),
                           post={'email': config.get_setting('username', server='hdmario'),
                                 'password': config.get_setting('password', server='hdmario')})
    if not r.success or 'Email o Password non validi' in r.data:
        platformtools.dialog_ok('HDmario', 'Username/password non validi')
        return False

    return True


def registerOrLogin(page_url):
    if config.get_setting('username', server='hdmario') and config.get_setting('password', server='hdmario'):
        if login():
            return True

    action = platformtools.dialog_yesno('HDmario',
                                  'Questo server necessita di un account, ne hai già uno oppure vuoi tentare una registrazione automatica?',
                                  yeslabel='Accedi', nolabel='Tenta registrazione', customlabel='Annulla')
    if action == 1:  # accedi
        from specials import setting
        from core.item import Item
        user_pre = config.get_setting('username', server='hdmario')
        password_pre = config.get_setting('password', server='hdmario')
        setting.server_config(Item(config='hdmario'))
        user_post = config.get_setting('username', server='hdmario')
        password_post = config.get_setting('password', server='hdmario')

        if user_pre != user_post or password_pre != password_post:
            return registerOrLogin(page_url)
        else:
            return []
    elif action == 0:  # tenta registrazione
        import random
        import string
        logger.debug('Registrazione automatica in corso')
        mailbox = Gmailnator()
        randPsw = ''.join(random.choice(string.ascii_letters + string.digits) for i in range(10))
        # captcha = httptools.downloadpage(baseUrl + '/captchaInfo').json
        logger.debug('email: ' + mailbox.address)
        logger.debug('pass: ' + randPsw)
        reg = platformtools.dialog_register(baseUrl + '/register/', email=True, password=True, email_default=mailbox.address, password_default=randPsw)
        if not reg:
            return False
        regPost = httptools.downloadpage(baseUrl + '/register/',
                                                  post={'email': reg['email'], 'email_confirmation': reg['email'],
                                                        'password': reg['password'],
                                                        'password_confirmation': reg['password']})
                                                        # 'captchaUuid': captcha['captchaUuid'],
                                                        # 'captcha': reg['captcha']})
        if '/register' in regPost.url:
            error = scrapertools.htmlclean(scrapertools.find_single_match(regPost.data, 'Impossibile proseguire.*?</div>'))
            error = scrapertools.unescape(scrapertools.re.sub('\n\s+', ' ', error))
            platformtools.dialog_ok('HDmario', error)
            return False
        if reg['email'] == mailbox.address:
            if "L'indirizzo email è già stato utilizzato" in regPost.data:
                # httptools.downloadpage(baseUrl + '/forgotPassword', post={'email': reg['email']})
                platformtools.dialog_ok('HDmario', 'Indirizzo mail già utilizzato')
                return False
            mail = mailbox.waitForMail()
            if mail:
                checkUrl = scrapertools.find_single_match(mail.body, 'href="([^"]+)">Premi qui').replace(r'\/', '/')
                logger.debug('CheckURL: ' + checkUrl)
                httptools.downloadpage(checkUrl)
                config.set_setting('username', mailbox.address, server='hdmario')
                config.set_setting('password', randPsw, server='hdmario')
                platformtools.dialog_ok('HDmario',
                                        'Registrato automaticamente con queste credenziali:\nemail:' + mailbox.address + '\npass: ' + randPsw)
            else:
                platformtools.dialog_ok('HDmario', 'Impossibile registrarsi automaticamente')
                return False
        else:
            platformtools.dialog_ok('HDmario', 'Hai modificato la mail quindi S4Menon sarà in grado di effettuare la verifica in autonomia, apri la casella ' + reg['email']
                                    + ' e clicca sul link. Premi ok quando fatto')
        logger.debug('Registrazione completata')
    else:
        return False

    return True


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    global page, data
    page_url = page_url.replace('?', '')
    logger.debug("url=" + page_url)

    if 'unconfirmed' in page.url:
        id = page_url.split('/')[-1]
        mailbox = Gmailnator()
        postData = {
            'email': mailbox.address,
            'hls_video_id': id
        }
        httptools.downloadpage(page.url, post=postData)
        mail = mailbox.waitForMail()
        logger.debug(mail)
        if mail:
            code = mail.subject.split(' - ')[0]
            page = httptools.downloadpage(page_url + '?code=' + code)
            data = page.data

    if '/unauthorized' in page.url or '/not-active' in page.url:
        httptools.set_cookies({'domain': 'hdmario.live'}, True)  # clear cookies
        if not registerOrLogin(page_url):
            platformtools.play_canceled = True
            return []
        page = httptools.downloadpage(page_url)
        data = page.data

    # logger.debug(data)
    from lib import jsunpack_js2py
    unpacked = jsunpack_js2py.unpack(scrapertools.find_single_match(data, '(eval.*?)</'))
    # p,a,c,k,e,d data -> xhr.setRequestHeader
    secureProof = scrapertools.find_single_match(unpacked, """X-Secure-Proof['"]\s*,\s*['"]([^"']+)""")
    logger.debug('X-Secure-Proof=' + secureProof)

    data = httptools.downloadpage(baseUrl + '/pl/' + page_url.split('/')[-1].replace('?', ''), headers=[['X-Secure-Proof', secureProof]]).data
    filetools.write(xbmc.translatePath('special://temp/hdmario'), data, 'w')

    video_urls = [['.m3u8 [HDmario]', 'special://temp/hdmario']]

    return video_urls
