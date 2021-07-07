# -*- coding: utf-8 -*-
from core import httptools, scrapertools, config, support
import base64
from lib import js2py
import math
import re

files = None

def test_video_exists(page_url):

  global htmldata
  htmldata = httptools.downloadpage(page_url).data

  if htmldata:
        return True, ""
  else:
        return False, config.get_localized_string(70449) % "Streamon"


# def get_video_url(page_url, premium=False, user="", password="", video_password=""):

#     tabbler = httptools.downloadpage('https://streamon.to/assets/js/tabber.js').data.replace('eval','')
#     decoded_tabler = js2py.eval_js(tabbler)
#     decoder = scrapertools.find_single_match(decoded_tabler, r'var res = ([a-z]{12})\.replace\("([^"]+)[^\.]+\.replace\("([^"]+)')

#     first_decoder_js = scrapertools.find_single_match(htmldata, '<script\s+?type=[\'|"].*?[\'|"]>\s?(var.*?)<\/script>').replace('eval', '')

#     first_decoder_fn = js2py.eval_js(first_decoder_js)

#     variable_value = scrapertools.find_single_match(first_decoder_fn, 'var {}="([^"]+)"'.format(decoder[0]))

#     res = variable_value.replace(decoder[1], "")
#     res2 = res.replace(decoder[2], "")
#     media_url = base64.b64decode( res2 ).decode('ascii')

#     video_urls = []

#     video_urls.append([scrapertools.get_filename_from_url(media_url)[-4:] + " [Streamon]", media_url])

#     return video_urls


def get_video_url(page_url, premium=False, user="", password="", video_password=""):

    support.dbg()

    tabbler = httptools.downloadpage('https://streamon.to/assets/js/tabber.js').data
    params_tabber = scrapertools.find_single_match(tabbler, r'\}\((.*)\)\)$')


    params_tabber_decoder = params_tabber.split(',')
    decoded_tabler = eval_fn(
      params_tabber_decoder[0].replace('"', ''),
      int(params_tabber_decoder[1]),
      params_tabber_decoder[2].replace('"', ''),
      int(params_tabber_decoder[3]),
      int(params_tabber_decoder[4]),
      int(params_tabber_decoder[5])
    )

    decoder = scrapertools.find_single_match(decoded_tabler, r'var res = ([a-z]{12})\.replace\("([^"]+)[^\.]+\.replace\("([^"]+)')

    params_from_page = scrapertools.find_single_match(htmldata, '<script\s+?type=[\'|"].*?[\'|"]>\s?var.*?\}\((.*?)\)\)<\/script>')

    params_from_page_decoder = params_from_page.split(',')

    first_decoder_fn = eval_fn(
      params_from_page_decoder[0].replace('"', ''),
      int(params_from_page_decoder[1]),
      params_from_page_decoder[2].replace('"', ''),
      int(params_from_page_decoder[3]),
      int(params_from_page_decoder[4]),
      int(params_from_page_decoder[5])
    )

    variable_value = scrapertools.find_single_match(first_decoder_fn, 'var {}="([^"]+)"'.format(decoder[0]))

    res = variable_value.replace(decoder[1], "")
    res2 = res.replace(decoder[2], "")
    media_url = base64.b64decode( res2 ).decode('ascii')

    video_urls = []

    video_urls.append([scrapertools.get_filename_from_url(media_url)[-4:] + " [Streamon]", media_url])

    return video_urls




def loop_reduce(lst, h, e):
  acc = 0
  for index, val in enumerate(lst):
    indexOf = h.find(val)
    if indexOf > -1:
      pow = int(math.pow(e, index))
      acc = acc + indexOf * pow

  return acc





def _0xe36c(d, e, f):
  g = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/'

  h = g[0 : e];
  i = g[0 : f];

  #j = functools.reduce( reduce_array(e), list(d)[::-1] )
  j = loop_reduce(list(d)[::-1], h, e)
  k = ''
  while j > 0:
    j = int(j)
    k = i[j % f] + k
    j = (j - (j % f)) / f

  return k or ''



def eval_fn(h, u, n, t, e, r):
  r = "";
  i = -1
  while i < len(h)  -  1:
    i = i + 1
    s = ''
    while h[i] != n[e]:
      s += h[i]
      i = i + 1
    for j in range(0, len(n)):
      reg = re.compile(n[j])
      s = re.sub(reg, str(j), s)

    res = _0xe36c(s, e, 10)
    r += chr( int( res ) - t )

  return r