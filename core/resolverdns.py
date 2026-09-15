# -*- coding: utf-8 -*-
import datetime, sys, ssl
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int

if PY3:
    import urllib.parse as urlparse
else:
    import urlparse

from lib.requests_toolbelt.adapters import host_header_ssl
from lib import doh
from platformcode import config, logger
import requests
from core import scrapertools
from core import db
from urllib3.poolmanager import PoolManager
from urllib3.util.ssl_ import create_urllib3_context
from urllib3.util import connection
from requests.adapters import HTTPAdapter

# --- wireformat DoH support (for providers without a JSON API, e.g. LibreDNS) ---
import base64, importlib, os, socket, struct, threading
if PY3:
    import http.client as httplib
else:
    import httplib

_UA = 'Mozilla/5.0 (compatible; Kodi-DoH/1.0)'


def _build_query(domain, qtype=1):
    qname = b''
    for label in domain.rstrip('.').split('.'):
        qname += struct.pack('B', len(label)) + (label.encode('ascii') if PY3 else label)
    qname += b'\x00'
    return (os.urandom(2) + b'\x01\x00' + struct.pack('>HHHH', 1, 0, 0, 0)
            + qname + struct.pack('>HH', qtype, 1))


def _skip_name(msg, off):
    while msg[off]:
        if msg[off] & 0xC0 == 0xC0:  # compression pointer
            return off + 2
        off += 1 + msg[off]
    return off + 1


def _parse_answers(msg):
    ancount = struct.unpack('>H', msg[6:8])[0]
    off = _skip_name(msg, 12) + 4
    ips = []
    for _ in range(ancount):
        off = _skip_name(msg, off)
        rtype, _c, _ttl, rdlen = struct.unpack('>HHIH', msg[off:off + 10])
        off += 10
        rdata = msg[off:off + rdlen]
        off += rdlen
        try:
            if rtype == 1 and rdlen == 4:
                ips.append(socket.inet_ntoa(rdata))
            elif rtype == 28 and rdlen == 16:
                ips.append(socket.inet_ntop(socket.AF_INET6, rdata))
        except Exception:
            pass
    return ips


def wire_query(domain, server, path='/dns-query', timeout=10):
    """RFC 8484 DoH (wireformat). Uses http.client on purpose: a requests
    call here would recurse through the patched create_connection."""
    headers = {'accept': 'application/dns-message', 'user-agent': _UA}
    try:
        pkt = _build_query(domain)
        b64 = base64.urlsafe_b64encode(pkt).rstrip(b'=')
        if PY3:
            b64 = b64.decode('ascii')

        conn = httplib.HTTPSConnection(server, timeout=timeout)
        conn.request('GET', path + '?dns=' + b64, headers=headers)
        resp = conn.getresponse()
        body = resp.read() if resp.status == 200 else b''
        conn.close()

        if resp.status != 200:  # RFC 8484 POST fallback
            conn = httplib.HTTPSConnection(server, timeout=timeout)
            conn.request('POST', path, body=pkt,
                         headers=dict(headers, **{'content-type': 'application/dns-message'}))
            resp = conn.getresponse()
            body = resp.read() if resp.status == 200 else b''
            conn.close()

        if body:
            answers = _parse_answers(body)
            return answers[0] if answers else None
        return None
    except Exception:
        import traceback
        logger.error(traceback.format_exc())
    return None


current_date = datetime.datetime.now()
CIPHERS = "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384"
dns_providers = {'cloudflare': {'mode': 'json', 'host': '1.0.0.1',         'path': '/dns-query'},
                 'google':     {'mode': 'json', 'host': '8.8.4.4',         'path': '/resolve'},
                 'libredns':   {'mode': 'wire', 'host': 'doh.libredns.gr', 'path': '/dns-query'}}


# --- module-level DoH resolution, shared by the adapter and the global override ---

_resolve_busy = threading.local()


def resolve(domain):
    """Resolve via DoH with db cache. Returns ip (bracketed if IPv6) or None."""
    if getattr(_resolve_busy, 'busy', False):  # recursion guard
        return None
    _resolve_busy.busy = True
    try:
        return _resolve(domain)
    finally:
        _resolve_busy.busy = False


def _resolve(domain):
    cache = db['dnscache'].get(domain, {})
    ip = None
    if type(cache) != dict or (cache.get('datetime') and
                               current_date - cache.get('datetime') > datetime.timedelta(hours=1)):
        cache = None

    if not cache:  # not cached
        try:
            cfg_provider = config.get_setting('resolver_dns_provider').lower()
            provider = dns_providers[cfg_provider]
            logger.debug('selected ' + cfg_provider + ' dns provider with address ' + provider['host'] + ' and path ' + provider['path'])

            if provider.get('mode') == 'wire':
                ip = wire_query(domain, provider['host'], provider['path'])
            else:
                ip = doh.query(domain, server = provider['host'], path = provider['path'], fallback=False) # fallback is not necessary here
                if ip is None or not len(ip): # resolver is not available or return no results
                    ip = None
                else:
                    ip = ip[0]

            if ip is not None:
                logger.info('Query DoH: ' + domain + ' = ' + str(ip))
                # IPv6 address
                if ':' in ip:
                    ip = '[' + ip + ']'
                write_to_cache(domain, ip)
            else:
                logger.error('DoH query failed for ' + domain + ', fallback to normal dns')
        except Exception:
            import traceback
            logger.error(traceback.format_exc())
    else:
        ip = cache.get('ip')

    if ip:
        logger.info('Cache DNS: ' + domain + ' = ' + str(ip))
    else:
        logger.error('Failed to resolve hostname ' + domain + ', fallback to normal dns')
    return ip


def write_to_cache(domain, ip):
    db['dnscache'][domain] = {'ip': ip, 'datetime': current_date}


def flush(domain):
    try:
        del db['dnscache'][domain]
    except KeyError:
        pass


# --- global DNS override: routes EVERY urllib3 connection through DoH ---

_patched_conn_modules = []


def _patch_connection_module(mod):
    if mod in _patched_conn_modules:
        return
    if not hasattr(mod, 'original_create_connection'):
        mod.original_create_connection = mod.create_connection

    def override_dns_connection(address, *args, **kwargs):
        """Wrap urllib3's create_connection to resolve the name via DoH"""
        host, port = address
        hostname = resolve(host)
        if not hostname:
            hostname = host  # fallback
            logger.debug("Override dns failed, fallback to normal dns resolver")
        return mod.original_create_connection((hostname, port), *args, **kwargs)

    mod.create_connection = override_dns_connection
    _patched_conn_modules.append(mod)


def install_dns_override():
    """Patch urllib3's create_connection so every https request in this process
    (plain requests, cloudscraper, proxies...) resolves hostnames via DoH.
    Idempotent; honors the resolver_dns setting."""
    if not config.get_setting('resolver_dns'):
        return
    # several vendored copies may exist in the addon; patch all of them
    for modname in ('urllib3.util.connection',
                    'requests.packages.urllib3.util.connection',
                    'lib.urllib3.util.connection',
                    'lib.requests.packages.urllib3.util.connection',
                    'lib.cloudscraper.requests.packages.urllib3.util.connection'):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        _patch_connection_module(mod)


class CipherSuiteAdapter(HTTPAdapter):

    def __init__(self, domain, ssl_options=ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1, override_dns = True, ssl_ciphers = CIPHERS, **kwargs):
        self.ssl_options = ssl_options
        self.ssl_ciphers = ssl_ciphers
        super(CipherSuiteAdapter, self).__init__(**kwargs) 
        if override_dns:
            install_dns_override()

    def flushDns(self, domain, **kwargs):
        flush(domain)

    def getIp(self, domain):
        return resolve(domain)

    def writeToCache(self, domain, ip):
        write_to_cache(domain, ip)

    def init_poolmanager(self, *pool_args, **pool_kwargs):
        ctx = create_urllib3_context(ciphers=self.ssl_ciphers, cert_reqs=ssl.CERT_REQUIRED, options=self.ssl_options)
        self.poolmanager = PoolManager(*pool_args, ssl_context=ctx, **pool_kwargs)

    def send(self, request, flushedDns=False, **kwargs):
        try:
            return super(CipherSuiteAdapter, self).send(request, **kwargs)
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
            logger.info(e)
            try:
                parse = urlparse.urlparse(request.url)
            except:
                raise requests.exceptions.InvalidURL
            if parse.netloc:
                domain = parse.netloc
                logger.info('Request for ' + domain + ' failed')
                if not flushedDns:
                    logger.info('Flushing dns cache for ' + domain)
                    self.flushDns(domain, **kwargs)
                    return self.send(request, flushedDns=True, **kwargs)
        except Exception as e:
            logger.error(e)
            raise e
