# -*- coding: utf-8 -*-

from core import httptools, support
from lib import jsunpack
from platformcode import config, logger

def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    global data
    data = httptools.downloadpage(page_url, cookies=False).data
    if 'file was deleted' in data:
        return False, config.get_localized_string(70449) % "VidHide"

    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []
    global data
    packed = support.match(data, patron=r'(eval\(function\(p,a,c,k,e,d\).*?)\s*</script>').match

    if packed:
        data = jsunpack.unpack(packed)
        links = support.match(data, patron=r'["\']hls(?P<num>\d+)["\']:\s*["\'](?P<url>[^"\']+)')
        if links.matches:
            hls_dict = {f"hls{num}": url for num, url in links.matches}
            media_url = hls_dict.get("hls4") or hls_dict.get("hls3") or hls_dict.get("hls2")
            if media_url:
                video_urls.append([" [VidHide] ", media_url])
                return video_urls
        
        source = support.match(data, patron=r'sources:\s*\[{file:\s*["\']([^"\']+)').match
        if source:
            media_url = source.group(1)
            video_urls.append([" [VidHide] ", media_url])
            return video_urls