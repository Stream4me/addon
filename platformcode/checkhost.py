# -*- coding: utf-8 -*-

import xbmc, xbmcgui
import xbmcaddon
from platformcode import config, logger
import requests
import sys
if sys.version_info[0] >= 3:
    from lib.httplib2 import py3 as httplib2
else:
    from lib.httplib2 import py2 as httplib2
import socket

addon = xbmcaddon.Addon("plugin.video." + config.PLUGIN_NAME)
addonname = addon.getAddonInfo('name')
addonid = addon.getAddonInfo('id')

LIST_SITE = ['https://www.ansa.it/', 'https://www.google.com']
LST_SITE_CHCK_DNS = ['https://cb01official.uno/']


def is_valid_dns(value):
    if not value:
        return False
    if "." in value or ":" in value:
        return True
    return False


def get_dns_labels(max_wait=3):
    dns1 = xbmc.getInfoLabel('Network.DNS1Address')
    dns2 = xbmc.getInfoLabel('Network.DNS2Address')

    for _ in range(max_wait * 5):
        if is_valid_dns(dns1) and is_valid_dns(dns2):
            return [dns1, dns2]
        xbmc.sleep(200)
        dns1 = xbmc.getInfoLabel('Network.DNS1Address')
        dns2 = xbmc.getInfoLabel('Network.DNS2Address')

    return [dns1, dns2]


class Kdicc():

    def __init__(self, is_exit = True, check_dns = True, view_msg = True,
                 lst_urls = [], lst_site_check_dns = [], in_addon = False):

        self.ip_addr = xbmc.getIPAddress()
        self.dns = get_dns_labels()
        self.check_dns = check_dns
        self.is_exit = is_exit
        self.lst_urls = lst_urls
        self.view_msg = view_msg
        self.lst_site_check_dns = lst_site_check_dns
        self.urls = []

    def check_Ip(self):
        if self.ip_addr == '127.0.0.1' or self.ip_addr == '':
            return False
        else:
            return True

    def check_Adsl(self):
        urls = LIST_SITE
        r = self.rqst(urls)
        http_errr = 0
        for rslt in r:
            logger.info("check_Adsl rslt: %s" % rslt['code'])
            if rslt['code'] == '111' or '[Errno -3]' in str(rslt['code']) or 'Errno -2' in str(rslt['code']):
                http_errr +=1

        if len(LIST_SITE) == http_errr:
            return False
        else:
            return True

    def check_Dns(self):
        if self.lst_site_check_dns == []:
            urls = LST_SITE_CHCK_DNS
        else:
            urls = self.lst_site_check_dns

        r = self.rqst(urls)
        logger.info("check_Dns result: %s" % r)
        http_errr = 0
        for rslt in r:
            logger.info("check_Dns rslt: %s" % rslt['code'])
            if rslt['code'] == '111':
                http_errr +=1

        if len(LST_SITE_CHCK_DNS) == http_errr:
            return False
        else:
            return True

    def rqst(self, lst_urls):
        rslt_final = []

        if lst_urls == []:
            lst_urls = self.lst_urls

        for sito in lst_urls:
            rslt = {}
            try:
                r = requests.head(sito, allow_redirects = True)
                if r.url.endswith('/'):
                    r.url = r.url[:-1]
                if str(sito) != str(r.url):
                    is_redirect = True
                else:
                    is_redirect = False

                rslt['code'] = r.status_code
                rslt['url'] = str(sito)
                rslt['rdrcturl'] = str(r.url)
                rslt['isRedirect'] = is_redirect
                rslt['history'] = r.history
                logger.info("Risultato nel try: %s" %  (r,))

            except requests.exceptions.ConnectionError as conn_errr:
                if '[Errno 111]' in str(conn_errr) or 'Errno 10060' in str(conn_errr) \
                     or 'Errno 10061' in str(conn_errr) \
                     or '[Errno 110]' in str(conn_errr) \
                     or 'ConnectTimeoutError' in str(conn_errr) \
                     or 'Errno 11002' in str(conn_errr) or 'ReadTimeout' in str(conn_errr) \
                     or 'Errno 11001' in str(conn_errr) \
                     or 'Errno -2' in str(conn_errr):
                    rslt['code'] = '111'
                    rslt['url'] = str(sito)
                    rslt['http_err'] = 'Connection error'
                else:
                    rslt['code'] = conn_errr
                    rslt['url'] = str(sito)
                    rslt['http_err'] = 'Connection refused'
            rslt_final.append(rslt)

        return rslt_final

    def http_Resp(self):
        rslt = {}
        for sito in self.lst_urls:
            try:
                s = httplib2.Http()
                code, resp = s.request(sito, body=None)
                if code.previous:
                    logger.info("r1 http_Resp: %s %s %s %s" %
                             (code.status, code.reason, code.previous['status'],
                              code.previous['-x-permanent-redirect-url']))
                    rslt['code'] = code.previous['status']
                    rslt['redirect'] = code.previous['-x-permanent-redirect-url']
                    rslt['status'] = code.status
                else:
                    rslt['code'] = code.status
            except httplib2.ServerNotFoundError as msg:
                rslt['code'] = -2
            except socket.error as msg:
                rslt['code'] = 111
            except:
                rslt['code'] = 'Connection error'
        return rslt

    def view_Advise(self, txt = '' ):
        ip = self.check_Ip()
        if ip:
            txt += '\nIP: %s\n' % self.ip_addr
            txt += '\nDNS: %s\n' % (self.dns)
        else:
            txt += '\nIP: %s' % self.ip_addr

        dialog = xbmcgui.Dialog()
        if config.get_setting('checkdns'):
            risposta= dialog.yesno(addonname, txt, nolabel=config.get_localized_string(707403), yeslabel=config.get_localized_string(707404))
            if risposta == False:
                config.set_setting('checkdns', False)
                dialog.textviewer(addonname+' '+config.get_localized_string(707405), config.get_localized_string(707406))
        else:
            txt = config.get_localized_string(707402)
            dialog.notification(addonname, txt, xbmcgui.NOTIFICATION_INFO, 10000)


def test_conn(is_exit, check_dns, view_msg,
              lst_urls, lst_site_check_dns, in_addon):

    ktest = Kdicc(is_exit, check_dns, view_msg, lst_urls, lst_site_check_dns, in_addon)

    if not ktest.check_Ip():
        if view_msg == True:
            ktest.view_Advise(config.get_localized_string(70720))
        if ktest.is_exit == True:
            exit()

    if not ktest.check_Adsl():
        if view_msg == True:
            ktest.view_Advise(config.get_localized_string(70721))
        if ktest.is_exit == True:
            exit()

    if check_dns == True:
        if not ktest.check_Dns():
            if view_msg == True:
                ktest.view_Advise(config.get_localized_string(70722))

    logger.info("############ Start Check DNS ############")
    logger.info("## IP: %s" %  (ktest.ip_addr))
    logger.info("## DNS: %s" %  (ktest.dns))
    logger.info("############# End Check DNS #############")
