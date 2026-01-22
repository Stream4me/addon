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

# list of sites that will not be reached with the manager's DNS

LST_SITE_CHCK_DNS = ['https://cb01official.uno/']

class Kdicc():

    def __init__(self, is_exit = True, check_dns = True, view_msg = True,
                 lst_urls = [], lst_site_check_dns = [], in_addon = False):

        self.ip_addr = xbmc.getIPAddress()
        self.dns = [xbmc.getInfoLabel('Network.DNS1Address'),
                    xbmc.getInfoLabel('Network.DNS2Address')]
        self.check_dns = check_dns
        self.is_exit = is_exit
        self.lst_urls = lst_urls
        self.view_msg = view_msg
        self.lst_site_check_dns = lst_site_check_dns
        self.urls = []
        #logger.info("check #### INIZIO INIT#### ")

    def check_Ip(self):
        """
            check the ip
            if ip_addr = 127.0.0.1 or ip_addr = '' then the device does not is connected to the modem/router

            return: bool
        """
        if self.ip_addr == '127.0.0.1' or self.ip_addr == '':
            return False
        else:
            return True


    def check_Adsl(self):
        """
            check if the device reaches the sites
        """

        urls = LIST_SITE
        r = self.rqst(urls)
        http_errr = 0
        for rslt in r:
            logger.info("check_Adsl rslt: %s" % rslt['code'])
            # Errno -2 could be lack of adsl connection or unreachable site ....
            # even in cases where there is a change of manager.
            if rslt['code'] == '111' or '[Errno -3]' in str(rslt['code']) or 'Errno -2' in str(rslt['code']):
                http_errr +=1

        if len(LIST_SITE) == http_errr:
            return False
        else:
            return True


    def check_Dns(self):
        """
            Control if DNS reaches certain sites
        """
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
        """
            url must start with http(s):'
            return : (esito, sito, url, code, reurl)
        """
        rslt_final = []

        if lst_urls == []:
            lst_urls = self.lst_urls

        for sito in lst_urls:
            rslt = {}
            try:
                r = requests.head(sito, allow_redirects = True) #, timeout=7) # from error after lib insertion of httplib2
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
                # Errno 10061 for s.o. win
                # will the Errno 10xxx and 11xxx be to be compacted in any way?
                # the errors are incorporated in code = '111' since at that moment
                # they are not reached for any reason
                if '[Errno 111]' in str(conn_errr) or 'Errno 10060' in str(conn_errr) \
                     or 'Errno 10061' in str(conn_errr) \
                     or '[Errno 110]' in str(conn_errr) \
                     or 'ConnectTimeoutError' in str(conn_errr) \
                     or 'Errno 11002' in str(conn_errr) or 'ReadTimeout' in str(conn_errr) \
                     or 'Errno 11001' in str(conn_errr) \
                     or 'Errno -2' in str(conn_errr): # this error is also in the code: -2
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
                # both for lack of ADSL and for non-existent sites
                rslt['code'] = -2
            except socket.error as msg:
                # for unreachable sites without correct DNS
                # [Errno 111] Connection refused
                rslt['code'] = 111
            except:
                rslt['code'] = 'Connection error'
        return rslt

    def view_Advise(self, txt = '' ):
        """
            Notice per user testConnected
        """
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
"""
    def called in launcher.py
"""
def test_conn(is_exit, check_dns, view_msg,
              lst_urls, lst_site_check_dns, in_addon):

    ktest = Kdicc(is_exit, check_dns, view_msg, lst_urls, lst_site_check_dns, in_addon)
    # if it does not have the IP, I will communicate it to the user
    if not ktest.check_Ip():
        # I don't let you get into the addon
        # enter language code
        if view_msg == True:
            ktest.view_Advise(config.get_localized_string(70720))
        if ktest.is_exit == True:
            exit()
    # if it has no ADSL connection, I will communicate it to the user
    if not ktest.check_Adsl():
        if view_msg == True:
            ktest.view_Advise(config.get_localized_string(70721))
        if ktest.is_exit == True:
            exit()
    # if it has DNS filtered, I will communicate it to the user
    if check_dns == True:
        if not ktest.check_Dns():
            if view_msg == True:
                ktest.view_Advise(config.get_localized_string(70722))

    logger.info("############ Start Check DNS ############")
    logger.info("## IP: %s" %  (ktest.ip_addr))
    logger.info("## DNS: %s" %  (ktest.dns))
    logger.info("############# End Check DNS #############")
    # if check_dns == True:
    #     if ktest.check_Ip() == True and ktest.check_Adsl() == True and ktest.check_Dns() == True:
    #         return True
    #     else:
    #         return False
    # else:
    #     if ktest.check_Ip() == True and ktest.check_Adsl() == True:
    #         return True
    #     else:
    #         return False

