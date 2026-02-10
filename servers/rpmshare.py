# -*- coding: utf-8 -*-
# -*- Server RPMShare - Decriptazione AES-CBC -*-

from core import httptools, scrapertools, support
from platformcode import logger, config
from six.moves import urllib_parse
import sys, json, re

PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str

# Importa libreria AES
AES_AVAILABLE = False
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    AES_AVAILABLE = True
except:
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import unpad
        AES_AVAILABLE = True
    except:
        pass

# Variabili globali
video_id = None
page_url_global = None
base_url = None

# Chiavi AES statiche
RPMSHARE_KEY = 'kiemtienmua911ca'
RPMSHARE_IV = '1234567890oiuytr'


def test_video_exists(page_url):
    global video_id, page_url_global, base_url
    
    logger.info("page_url: %s" % page_url)
    
    video_id = page_url.split('#')[-1] if '#' in page_url else ''
    if video_id and '&' in video_id:
        video_id = video_id.split('&')[0]
    
    page_url_global = page_url
    parsed = urllib_parse.urlparse(page_url)
    base_url = "%s://%s" % (parsed.scheme, parsed.netloc)
    
    if not video_id or len(video_id) < 2:
        return False, config.get_localized_string(70449) % "RPMShare"
    
    logger.info("video_id: %s" % video_id)
    return True, ""


def aes_cbc_decrypt(encrypted_hex, key, iv):
    if not AES_AVAILABLE:
        raise Exception("AES library not available")
    
    encrypted_hex = encrypted_hex.strip()
    
    if not re.match(r'^[0-9a-fA-F]+$', encrypted_hex):
        raise Exception("Invalid hex format")
    
    if len(encrypted_hex) % 2 != 0:
        raise Exception("Invalid hex length")
    
    encrypted_bytes = bytes.fromhex(encrypted_hex)
    
    key_bytes = key.encode('utf-8') if isinstance(key, str) else key
    iv_bytes = iv.encode('utf-8') if isinstance(iv, str) else iv
    
    if len(key_bytes) not in [16, 24, 32]:
        if len(key_bytes) < 16:
            key_bytes = key_bytes.ljust(16, b'\0')
        elif len(key_bytes) < 24:
            key_bytes = key_bytes[:16]
        elif len(key_bytes) < 32:
            key_bytes = key_bytes[:24]
        else:
            key_bytes = key_bytes[:32]
    
    if len(iv_bytes) != 16:
        iv_bytes = iv_bytes.ljust(16, b'\0') if len(iv_bytes) < 16 else iv_bytes[:16]
    
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
    decrypted = cipher.decrypt(encrypted_bytes)
    
    try:
        decrypted = unpad(decrypted, AES.block_size)
    except:
        padding_length = decrypted[-1]
        if isinstance(padding_length, str):
            padding_length = ord(padding_length)
        if padding_length > 0 and padding_length <= AES.block_size:
            if all(b == padding_length for b in decrypted[-padding_length:]):
                decrypted = decrypted[:-padding_length]
    
    return decrypted.decode('utf-8')


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []
    
    if not AES_AVAILABLE:
        logger.error("AES library not available")
        return video_urls
    
    api_url = "%s/api/v1/video?id=%s&w=1280&h=720&r=" % (base_url, video_id)
    
    try:
        api_response = httptools.downloadpage(
            api_url,
            headers={
                'Referer': page_url_global,
                'Accept': 'application/json',
            },
            alfa_s=True
        )
        
        encrypted_data = api_response.data
        logger.info("encrypted response length: %d" % len(encrypted_data))
        
    except Exception as e:
        logger.error("API call failed: %s" % str(e))
        return video_urls
    
    try:
        decrypted = aes_cbc_decrypt(encrypted_data, RPMSHARE_KEY, RPMSHARE_IV)
        video_data = json.loads(decrypted)
        
        video_url = None
        if 'data' in video_data and 'streams' in video_data['data']:
            streams = video_data['data']['streams']
            if streams and len(streams) > 0:
                video_url = streams[0].get('url')
        elif 'url' in video_data:
            video_url = video_data['url']
        elif 'file' in video_data:
            video_url = video_data['file']
        elif 'source' in video_data:
            video_url = video_data['source']
        
        if video_url:
            logger.info("video url found")
            
            headers = {
                'User-Agent': httptools.get_user_agent(),
                'Referer': page_url_global,
                'Origin': base_url
            }
            
            url_with_headers = video_url + "|" + "&".join([
                "%s=%s" % (k, v) for k, v in headers.items()
            ])
            
            video_urls.append([" [RPMShare]", url_with_headers])
        else:
            logger.error("video url not found in decrypted data")
        
    except Exception as e:
        logger.error("decryption failed: %s" % str(e))
    
    return video_urls


def get_filename(page_url):
    return video_id if video_id else ""
