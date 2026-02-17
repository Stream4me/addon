# -*- coding: utf-8 -*-

from core import httptools, support
from lib import jsunpack
from platformcode import config, logger
import re

def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    global data
    data = httptools.downloadpage(page_url, cookies=False).data
    if '<h1>Page not found</h1>' in data:
        return False, config.get_localized_string(70449) % "VidHide"

    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []
    global data
    packed = support.match(data, patron=r'(eval\(function\(p,a,c,k,e,d\).*?)\s*</script>').match

    if packed:
        data = jsunpack.unpack(packed)
        url = support.match(data, patron=r'["\']hls[24]["\']:["\'](?P<url>[^"\']+)', debug=False).match
        if url:	
            video_urls.append([" [VidHide] ", url])
    
    return video_urls
