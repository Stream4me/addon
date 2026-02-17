# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# S4Me favorites
# ==============
# - List of links saved as favorites, only in Alpha, not Kodi.
# - Links are organized in (virtual) folders that can be defined by the user.
# - A single file is used to save all folders and links: addonfavorites-default.json
# - addonfavorites-default.json can be copied to other devices since the only local dependency is the thumbnail associated with the links,
# but it is detected by code and adjusts to the current device.
# - You can have different alphabet files and alternate between them, but only one of them is the "active list".
# - Files must be in config.get_data_path () and start with addonfavorites- and end in .json

# Requirements in other modules to run this channel:
# - Add a link to this channel in channelselector.py
# - Modify platformtools.py to control the context menu and add "Save link" in set_context_commands
# ------------------------------------------------------------

# from builtins import str
import sys

from lib import requests
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int
from builtins import object

import os, re
from datetime import datetime

from core.item import Item
from platformcode import config, logger, platformtools
from core import filetools, jsontools, support


def fechahora_actual():
    return datetime.now().strftime('%Y-%m-%d %H:%M')

# List Helpers

PREFIJO_LISTA = 'addonfavorites-'

# Returns the name of the active list (Ex: addonfavorites-default.json)
def get_lista_activa():
    return config.get_setting('lista_activa', default = PREFIJO_LISTA + 'default.json')

# Extract list name from file, removing prefix and suffix (Ex: addonfavorites-Test.json => Test)
def get_name_from_filename(filename):
    return filename.replace(PREFIJO_LISTA, '').replace('.json', '')

# Compose the list file from a name, adding prefix and suffix (Ex: Test => addonfavorites-Test.json)
def get_filename_from_name(name):
    return PREFIJO_LISTA + name + '.json'

# Record the codes of the files that have been shared in a log file
def save_log_lista_shared(msg):
    msg = fechahora_actual() + ': ' + msg + os.linesep
    fullfilename = os.path.join(config.get_data_path(), 'addonfavorites_shared.log')
    with open(fullfilename, 'a') as f: f.write(msg); f.close()

# Clean text to use as file name
def text_clean(txt, disallowed_chars = '[^a-zA-Z0-9\-_()\[\]. ]+', blank_char = ' '):
    import unicodedata
    try:
        txt = unicode(txt, 'utf-8')
    except NameError: # unicode is a default on python 3
        pass
    txt = unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore')
    txt = txt.decode('utf-8').strip()
    if blank_char != ' ': txt = txt.replace(' ', blank_char)
    txt = re.sub(disallowed_chars, '', txt)
    return str(txt)



# Class to load and save in the S4MeFavorites file
class KodfavouritesData(object):

    def __init__(self, filename = None):

        # If no file is specified, the active_list is used (if not, it is created)
        if filename == None:
            filename = get_lista_activa()

        self.user_favorites_file = os.path.join(config.get_data_path(), filename)

        if not os.path.exists(self.user_favorites_file):
            fichero_anterior = os.path.join(config.get_data_path(), 'user_favorites.json')
            if os.path.exists(fichero_anterior): # old format, convert (to delete after some versions)
                jsondata = jsontools.load(filetools.read(fichero_anterior))
                self.user_favorites = jsondata
                self.info_lista = {}
                self.save()
                filetools.remove(fichero_anterior)
            else:
                self.user_favorites = []
        else:
            jsondata = jsontools.load(filetools.read(self.user_favorites_file))
            if not 'user_favorites' in jsondata or not 'info_lista' in jsondata: # incorrect format
                self.user_favorites = []
            else:
                self.user_favorites = jsondata['user_favorites']
                self.info_lista = jsondata['info_lista']


        if len(self.user_favorites) == 0:
            self.info_lista = {}

            # Create some default folders
            self.user_favorites.append({ 'title': config.get_localized_string(30122), 'items': [] })
            self.user_favorites.append({ 'title': config.get_localized_string(30123), 'items': [] })
            self.user_favorites.append({ 'title': config.get_localized_string(70149), 'items': [] })

            self.save()

    def save(self):
        if 'created' not in self.info_lista:
            self.info_lista['created'] = fechahora_actual()
        self.info_lista['updated'] = fechahora_actual()

        jsondata = {}
        jsondata['user_favorites'] = self.user_favorites
        jsondata['info_lista'] = self.info_lista
        if not filetools.write(self.user_favorites_file, jsontools.dump(jsondata)):
            platformtools.dialog_ok('S4Me', config.get_localized_string(70614) + '\n' + os.path.basename(self.user_favorites_file))


# ============================
# Add from context menu
# ============================

def addFavourite(item):
    logger.debug()
    alfav = KodfavouritesData()

    # If you get here through the context menu, you must retrieve the action and channel parameters
    if item.from_action:
        item.__dict__['action'] = item.__dict__.pop('from_action')
    if item.from_channel:
        item.__dict__['channel'] = item.__dict__.pop('from_channel')

    #Clear title
    item.title = re.sub(r'\[COLOR [^\]]*\]', '', item.title.replace('[/COLOR]', '')).strip()
    if item.text_color:
        item.__dict__.pop('text_color')

    # Dialog to choose / create folder
    i_perfil = _selecciona_perfil(alfav, config.get_localized_string(70546))
    if i_perfil == -1: return False

    # Detect that the same link does not already exist in the folder
    campos = ['channel','action','url','extra','list_type'] # if all these fields match the link is considered to already exist
    for enlace in alfav.user_favorites[i_perfil]['items']:
        it = Item().fromurl(enlace)
        repe = True
        for prop in campos:
            if prop in it.__dict__ and prop in item.__dict__ and it.__dict__[prop] != item.__dict__[prop]:
                repe = False
                break
        if repe:
            platformtools.dialog_notification(config.get_localized_string(70615), config.get_localized_string(70616))
            return False

    # If it is a movie / series, fill in tmdb information if tmdb_plus_info is not activated (for season / episode it is not necessary because the "second pass" will have already been done)
    # if (item.contentType == 'movie' or item.contentType == 'tvshow') and not config.get_setting('tmdb_plus_info', default=False):
    #     from core import tmdb
    #     tmdb.set_infoLabels(item, True) # get more data in "second pass" (actors, duration, ...)

    # Add date saved
    item.date_added = fechahora_actual()

    # save
    alfav.user_favorites[i_perfil]['items'].append(item.tourl())
    alfav.save()

    platformtools.dialog_notification(config.get_localized_string(70531), config.get_localized_string(70532) % alfav.user_favorites[i_perfil]['title'])

    return True


# ====================
# NAVIGATION
# ====================

def mainlist(item):
    logger.debug()
    alfav = KodfavouritesData()
    item.category = get_name_from_filename(os.path.basename(alfav.user_favorites_file))

    itemlist = []
    last_i = len(alfav.user_favorites) - 1

    for i_perfil, perfil in enumerate(alfav.user_favorites):
        context = []

        context.append({'title': config.get_localized_string(70533), 'channel': item.channel, 'action': 'editar_perfil_titulo', 'i_perfil': i_perfil})
        context.append({'title': config.get_localized_string(70534), 'channel': item.channel, 'action': 'eliminar_perfil', 'i_perfil': i_perfil})

        if i_perfil > 0:
            context.append({'title': config.get_localized_string(70535), 'channel': item.channel, 'action': 'mover_perfil', 'i_perfil': i_perfil, 'direccion': 'top'})
            context.append({'title': config.get_localized_string(70536), 'channel': item.channel, 'action': 'mover_perfil', 'i_perfil': i_perfil, 'direccion': 'arriba'})
        if i_perfil < last_i:
            context.append({'title': config.get_localized_string(70537), 'channel': item.channel, 'action': 'mover_perfil', 'i_perfil': i_perfil, 'direccion': 'abajo'})
            context.append({'title': config.get_localized_string(70538), 'channel': item.channel, 'action': 'mover_perfil', 'i_perfil': i_perfil, 'direccion': 'bottom'})

        plot = str(len(perfil['items'])) + " " + config.get_localized_string(70723)
        itemlist.append(Item(channel=item.channel, action='mostrar_perfil', title=perfil['title'], plot=plot, i_perfil=i_perfil, context=context, thumbnail=support.thumb('mylink.png')))

    itemlist.append(item.clone(action='crear_perfil', title=config.get_localized_string(70542), folder=False))

    itemlist.append(item.clone(action='mainlist_listas', title=config.get_localized_string(70603)))

    return support.thumb(itemlist)


def mostrar_perfil(item):
    logger.debug()
    alfav = KodfavouritesData()

    itemlist = []

    i_perfil = item.i_perfil
    if not alfav.user_favorites[i_perfil]: return itemlist
    last_i = len(alfav.user_favorites[i_perfil]['items']) - 1

    ruta_runtime = config.get_runtime_path()

    for i_enlace, enlace in enumerate(alfav.user_favorites[i_perfil]['items']):

        it = Item().fromurl(enlace)
        it.from_channel = 'addonfavorites'
        it.context = [ {'title': config.get_localized_string(70617), 'channel': item.channel, 'action': 'acciones_enlace',
                        'i_enlace': i_enlace, 'i_perfil': i_perfil} ]

        it.plot += '[CR][CR]' + config.get_localized_string(70724) + ': ' + it.channel + ' ' + config.get_localized_string(60266) + ': ' + it.action
        if (type(it.extra) is str) and it.extra != '': it.plot += ' Extra: ' + it.extra
        it.plot += '[CR]Url: ' + it.url if isinstance(it.url, str) else '...'
        if it.date_added != '': it.plot += '[CR]' + config.get_localized_string(70469) + ': ' + it.date_added

        if it.server:
            it.thumbnail = it.contentThumbnail
            it.title += ' [{}]'.format(it.serverName)

        # If it is not a url, nor does it have the system path, convert the path since it will have been copied from another device.
        # It would be more optimal if the conversion was done with an import menu, but at the moment it is controlled in run-time.
        # if it.thumbnail and '://' not in it.thumbnail and not it.thumbnail.startswith(ruta_runtime):
        #     ruta, fichero = filetools.split(it.thumbnail)
        #     if ruta == '' and fichero == it.thumbnail: # in linux the split with a windows path does not separate correctly
        #         ruta, fichero = filetools.split(it.thumbnail.replace('\\','/'))
        #     if 'channels' in ruta and 'thumb' in ruta:
        #         it.thumbnail = filetools.join(ruta_runtime, 'resources', 'media', 'channels', 'thumb', fichero)
        #     elif 'themes' in ruta and 'default' in ruta:
        #         it.thumbnail = filetools.join(ruta_runtime, 'resources', 'media', 'themes', 'default', fichero)

        itemlist.append(it)

    return itemlist


# Shared internal routines

# Dialog to select / create a folder. Returns index of folder on user_favorites (-1 if cancel)
def _selecciona_perfil(alfav, titulo=config.get_localized_string(70549), i_actual=-1):
    acciones = [(perfil['title'] if i_p != i_actual else '[I][COLOR pink]%s[/COLOR][/I]' % perfil['title']) for i_p, perfil in enumerate(alfav.user_favorites)]
    acciones.append(config.get_localized_string(70542))

    i_perfil = -1
    while i_perfil == -1: # repeat until a folder is selected or cancel
        ret = platformtools.dialog_select(titulo, acciones)
        if ret == -1: return -1 # order cancel
        if ret < len(alfav.user_favorites):
            i_perfil = ret
        else: # create new folder
            if _crea_perfil(alfav):
                i_perfil = len(alfav.user_favorites) - 1

    return i_perfil


# Dialog to create a folder
def _crea_perfil(alfav):
    titulo = platformtools.dialog_input(default='', heading=config.get_localized_string(70551))
    if titulo is None or titulo == '':
        return False

    alfav.user_favorites.append({'title': titulo, 'items': []})
    alfav.save()

    return True


# Profile and link management

def crear_perfil(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not _crea_perfil(alfav): return False

    platformtools.itemlist_refresh()
    return True


def editar_perfil_titulo(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False

    titulo = platformtools.dialog_input(default=alfav.user_favorites[item.i_perfil]['title'], heading=config.get_localized_string(70533))
    if titulo is None or titulo == '' or titulo == alfav.user_favorites[item.i_perfil]['title']:
        return False

    alfav.user_favorites[item.i_perfil]['title'] = titulo
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def eliminar_perfil(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False

    # Ask for confirmation
    if not platformtools.dialog_yesno(config.get_localized_string(70618), config.get_localized_string(70619)): return False

    del alfav.user_favorites[item.i_perfil]
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def acciones_enlace(item):
    logger.debug()

    acciones = [config.get_localized_string(70620), config.get_localized_string(70621), config.get_localized_string(70622), config.get_localized_string(70623),
                config.get_localized_string(70624), config.get_localized_string(70548), config.get_localized_string(70625),
                config.get_localized_string(70626), config.get_localized_string(70627), config.get_localized_string(70628)]

    ret = platformtools.dialog_select('Action to execute', acciones)
    if ret == -1:
        return False # order cancel
    elif ret == 0:
        return editar_enlace_titulo(item)
    elif ret == 1:
        return editar_enlace_color(item)
    elif ret == 2:
        return editar_enlace_thumbnail(item)
    elif ret == 3:
        return editar_enlace_carpeta(item)
    elif ret == 4:
        return editar_enlace_lista(item)
    elif ret == 5:
        return eliminar_enlace(item)
    elif ret == 6:
        return mover_enlace(item.clone(direccion='top'))
    elif ret == 7:
        return mover_enlace(item.clone(direccion='arriba'))
    elif ret == 8:
        return mover_enlace(item.clone(direccion='abajo'))
    elif ret == 9:
        return mover_enlace(item.clone(direccion='bottom'))


def editar_enlace_titulo(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    it = Item().fromurl(alfav.user_favorites[item.i_perfil]['items'][item.i_enlace])

    titulo = platformtools.dialog_input(default=it.title, heading=config.get_localized_string(70553))
    if titulo is None or titulo == '' or titulo == it.title:
        return False

    it.title = titulo

    alfav.user_favorites[item.i_perfil]['items'][item.i_enlace] = it.tourl()
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def editar_enlace_color(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    it = Item().fromurl(alfav.user_favorites[item.i_perfil]['items'][item.i_enlace])

    colores = ['green','yellow','red','blue','white','orange','lime','aqua','pink','violet','purple','tomato','olive','antiquewhite','gold']
    opciones = ['[COLOR %s]%s[/COLOR]' % (col, col) for col in colores]

    ret = platformtools.dialog_select(config.get_localized_string(70558), opciones)

    if ret == -1: return False # order cancel
    it.text_color = colores[ret]

    alfav.user_favorites[item.i_perfil]['items'][item.i_enlace] = it.tourl()
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def editar_enlace_thumbnail(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    it = Item().fromurl(alfav.user_favorites[item.i_perfil]['items'][item.i_enlace])

    # Starting with Kodi 17, you can use xbmcgui.Dialog (). Select with thumbnails (ListItem & useDetails = True)
    is_kodi17 = (config.get_platform(True)['num_version'] >= 17.0)
    if is_kodi17:
        import xbmcgui

    # Dialog to choose thumbnail (the channel or predefined icons)
    opciones = []
    ids = []
    # try:
    #     from core import channeltools
    #     channel_parameters = channeltools.get_channel_parameters(it.channel)
    #     if channel_parameters['thumbnail'] != '':
    #         nombre = 'Channel %s' % it.channel
    #         if is_kodi17:
    #             it_thumb = xbmcgui.ListItem(nombre)
    #             it_thumb.setArt({ 'thumb': channel_parameters['thumbnail'] })
    #             opciones.append(it_thumb)
    #         else:
    #             opciones.append(nombre)
    #         ids.append(channel_parameters['thumbnail'])
    # except:
    #     pass

    resource_path = 'https://api.github.com/repos/Stream4me/media/git/trees/b36040432b9be120f04e986277fd34f09dcdb4db'
    for f in sorted(requests.get(resource_path).json().get('tree', []), key=lambda p: p.get('path')):
        nombre = f['path'].replace('thumb_', '').replace('.png', '')
        it_thumb = xbmcgui.ListItem(nombre)
        it_thumb.setArt({ 'thumb': support.thumb(nombre)})
        opciones.append(it_thumb)
        ids.append(support.thumb(nombre))

    ret = xbmcgui.Dialog().select(config.get_localized_string(70554), opciones, useDetails=True)

    if ret == -1: return False # order cancel

    it.thumbnail = ids[ret]

    alfav.user_favorites[item.i_perfil]['items'][item.i_enlace] = it.tourl()
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def editar_enlace_carpeta(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    # Dialog to choose / create folder
    i_perfil = _selecciona_perfil(alfav, config.get_localized_string(70555), item.i_perfil)
    if i_perfil == -1 or i_perfil == item.i_perfil: return False

    alfav.user_favorites[i_perfil]['items'].append(alfav.user_favorites[item.i_perfil]['items'][item.i_enlace])
    del alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def editar_enlace_lista(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    # Dialog to choose list
    opciones = []
    itemlist_listas = mainlist_listas(item)
    for it in itemlist_listas:
        if it.lista != '' and '[<---]' not in it.title: # discard item create and active list
            opciones.append(it.lista)

    if len(opciones) == 0:
        platformtools.dialog_ok('S4Me', 'There are no other lists where to move the link.\nYou can create them from the Manage link lists menu')
        return False

    ret = platformtools.dialog_select('Select destination list', opciones)

    if ret == -1:
        return False # order cancel

    alfav_destino = KodfavouritesData(opciones[ret])

    # Dialog to choose / create folder in the destination list
    i_perfil = _selecciona_perfil(alfav_destino, 'Select destination folder', -1)
    if i_perfil == -1: return False

    alfav_destino.user_favorites[i_perfil]['items'].append(alfav.user_favorites[item.i_perfil]['items'][item.i_enlace])
    del alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]
    alfav_destino.save()
    alfav.save()

    platformtools.itemlist_refresh()
    return True


def eliminar_enlace(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    if not alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]: return False

    del alfav.user_favorites[item.i_perfil]['items'][item.i_enlace]
    alfav.save()

    platformtools.itemlist_refresh()
    return True


# Move profiles and links (up, down, top, bottom)
def mover_perfil(item):
    logger.debug()
    alfav = KodfavouritesData()

    alfav.user_favorites = _mover_item(alfav.user_favorites, item.i_perfil, item.direccion)
    alfav.save()

    platformtools.itemlist_refresh()
    return True

def mover_enlace(item):
    logger.debug()
    alfav = KodfavouritesData()

    if not alfav.user_favorites[item.i_perfil]: return False
    alfav.user_favorites[item.i_perfil]['items'] = _mover_item(alfav.user_favorites[item.i_perfil]['items'], item.i_enlace, item.direccion)
    alfav.save()

    platformtools.itemlist_refresh()
    return True


# Move a certain item (numeric) from a list (up, down, top, bottom) and return the modified list
def _mover_item(lista, i_selected, direccion):
    last_i = len(lista) - 1
    if i_selected > last_i or i_selected < 0: return lista # non-existent index in list

    if direccion == 'arriba':
        if i_selected == 0: # It's already on top of everything
            return lista
        lista.insert(i_selected - 1, lista.pop(i_selected))

    elif direccion == 'abajo':
        if i_selected == last_i: # It's already down
            return lista
        lista.insert(i_selected + 1, lista.pop(i_selected))

    elif direccion == 'top':
        if i_selected == 0: # It's already on top of everything
            return lista
        lista.insert(0, lista.pop(i_selected))

    elif direccion == 'bottom':
        if i_selected == last_i: # It's already down
            return lista
        lista.insert(last_i, lista.pop(i_selected))

    return lista


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Manage different alphabetical lists
# ------------------------------------------

def mainlist_listas(item):
    logger.debug()
    itemlist = []
    item.category = 'Listas'

    lista_activa = get_lista_activa()

    import glob

    path = os.path.join(config.get_data_path(), PREFIJO_LISTA+'*.json')
    for fichero in glob.glob(path):
        lista = os.path.basename(fichero)
        nombre = get_name_from_filename(lista)
        titulo = nombre if lista != lista_activa else nombre

        itemlist.append(item.clone(action='acciones_lista', lista=lista, title=titulo, folder=False))

    itemlist.append(item.clone(action='acciones_nueva_lista', title=config.get_localized_string(70642), folder=False))

    return itemlist


def acciones_lista(item):
    logger.debug()

    acciones = [config.get_localized_string(70604), config.get_localized_string(70629),
                config.get_localized_string(70605), config.get_localized_string(70606), config.get_localized_string(70607)]

    ret = platformtools.dialog_select(item.lista, acciones)

    if ret == -1:
        return False # pedido cancel
    elif ret == 0:
        return activar_lista(item)
    elif ret == 1:
        return renombrar_lista(item)
    elif ret == 2:
        return compartir_lista(item)
    elif ret == 3:
        return eliminar_lista(item)
    elif ret == 4:
        return informacion_lista(item)


def activar_lista(item):
    logger.debug()

    fullfilename = os.path.join(config.get_data_path(), item.lista)
    if not os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70630) + '\n' + item.lista)
        return False

    config.set_setting('lista_activa', item.lista)

    from channelselector import get_thumb
    item_inicio = Item(title=config.get_localized_string(70527), channel="addonfavorites", action="mainlist",
                       thumbnail=get_thumb("mylink.png"),
                       category=config.get_localized_string(70527), viewmode="thumbnails")
    platformtools.itemlist_update(item_inicio, replace=True)
    return True


def renombrar_lista(item):
    logger.debug()

    fullfilename_current = os.path.join(config.get_data_path(), item.lista)
    if not os.path.exists(fullfilename_current):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70630) + '\n' + fullfilename_current)
        return False

    nombre = get_name_from_filename(item.lista)
    titulo = platformtools.dialog_input(default=nombre, heading=config.get_localized_string(70612))
    if titulo is None or titulo == '' or titulo == nombre:
        return False
    titulo = text_clean(titulo, blank_char='_')

    filename = get_filename_from_name(titulo)
    fullfilename = os.path.join(config.get_data_path(), filename)

    # Check that the new name does not exist
    if os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70613) + '\n' + fullfilename)
        return False

    # Rename the file
    if not filetools.rename(fullfilename_current, filename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70631) + '\n' + fullfilename)
        return False

    # Update settings if it is the active list
    if item.lista == get_lista_activa():
        config.set_setting('lista_activa', filename)


    platformtools.itemlist_refresh()
    return True


def eliminar_lista(item):
    logger.debug()

    fullfilename = os.path.join(config.get_data_path(), item.lista)
    if not os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70630) + '\n' + item.lista)
        return False

    if item.lista == get_lista_activa():
        platformtools.dialog_ok('S4Me', config.get_localized_string(70632) + '\n' + item.lista)
        return False

    if not platformtools.dialog_yesno(config.get_localized_string(70606), config.get_localized_string(70633) + ' %s ?' % item.lista): return False
    filetools.remove(fullfilename)

    platformtools.itemlist_refresh()
    return True


def informacion_lista(item):
    logger.debug()

    fullfilename = os.path.join(config.get_data_path(), item.lista)
    if not os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70630) + '\n' + item.lista)
        return False

    alfav = KodfavouritesData(item.lista)

    txt = 'Lista: %s' % item.lista
    txt += '[CR]' + config.get_localized_string(70634) + ' ' + alfav.info_lista['created'] + ' ' + config.get_localized_string(70635) + ' ' + alfav.info_lista['updated']

    if 'downloaded_date' in alfav.info_lista:
        txt += '[CR]' + config.get_localized_string(70636) + ' ' + alfav.info_lista['downloaded_date'] + ' ' + alfav.info_lista['downloaded_from'] + ' ' + config.get_localized_string(70637)

    if 'tinyupload_date' in alfav.info_lista:
        txt += '[CR]' + config.get_localized_string(70638) + ' ' + alfav.info_lista['tinyupload_date'] + ' ' + config.get_localized_string(70639) + ' [COLOR blue]' + alfav.info_lista['tinyupload_code'] + '[/COLOR]'

    txt += '[CR]' + config.get_localized_string(70640) + ' ' + str(len(alfav.user_favorites))
    for perfil in alfav.user_favorites:
        txt += '[CR]- %s (%d %s)' % (perfil['title'], len(perfil['items']), config.get_localized_string(70641))

    platformtools.dialog_textviewer(config.get_localized_string(70607), txt)
    return True


def compartir_lista(item):
    logger.debug()

    fullfilename = os.path.join(config.get_data_path(), item.lista)
    if not os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70630) + '\n' + fullfilename)
        return False

    try:
        progreso = platformtools.dialog_progress_bg(config.get_localized_string(70643), config.get_localized_string(70644))

        # Access to the tinyupload home page to obtain necessary data
        from core import httptools, scrapertools
        data = httptools.downloadpage('http://s000.tinyupload.com/index.php').data
        upload_url = scrapertools.find_single_match(data, 'form action="([^"]+)')
        sessionid = scrapertools.find_single_match(upload_url, 'sid=(.+)')

        progreso.update(10, config.get_localized_string(70645) + '\n' + config.get_localized_string(70646))

        # Sending the file to tinyupload using multipart / form-data
        from future import standard_library
        standard_library.install_aliases()
        from lib import MultipartPostHandler
        import urllib.request, urllib.error
        opener = urllib.request.build_opener(MultipartPostHandler.MultipartPostHandler)
        params = { 'MAX_FILE_SIZE' : '52428800', 'file_description' : '', 'sessionid' : sessionid, 'uploaded_file' : open(fullfilename, 'rb') }
        handle = opener.open(upload_url, params)
        data = handle.read()

        progreso.close()

        if not 'File was uploaded successfuly' in data:
            logger.debug(data)
            platformtools.dialog_ok('S4Me', config.get_localized_string(70647))
            return False

        codigo = scrapertools.find_single_match(data, 'href="index\.php\?file_id=([^"]+)')

    except:
        platformtools.dialog_ok('S4Me', config.get_localized_string(70647) + '\n' + item.lista)
        return False

    # Point code in log file and inside the list
    save_log_lista_shared(config.get_localized_string(70648) + ' ' + item.lista + ' ' + codigo + ' ' + config.get_localized_string(70649))

    alfav = KodfavouritesData(item.lista)
    alfav.info_lista['tinyupload_date'] = fechahora_actual()
    alfav.info_lista['tinyupload_code'] = codigo
    alfav.save()

    platformtools.dialog_ok('S4Me', config.get_localized_string(70650) + '\n' + codigo)
    return True



def acciones_nueva_lista(item):
    logger.debug()

    acciones = [config.get_localized_string(70651),
                config.get_localized_string(70652),
                config.get_localized_string(70653),
                config.get_localized_string(70654)]

    ret = platformtools.dialog_select(config.get_localized_string(70608), acciones)

    if ret == -1:
        return False # order cancel

    elif ret == 0:
        return crear_lista(item)

    elif ret == 1:
        codigo = platformtools.dialog_input(default='', heading=config.get_localized_string(70609)) # 05370382084539519168
        if codigo is None or codigo == '':
            return False
        return descargar_lista(item, 'http://s000.tinyupload.com/?file_id=' + codigo)

    elif ret == 2:
        url = platformtools.dialog_input(default='https://', heading=config.get_localized_string(70610))
        if url is None or url == '':
            return False
        return descargar_lista(item, url)

    elif ret == 3:
        txt = config.get_localized_string(70611)
        platformtools.dialog_textviewer(config.get_localized_string(70607), txt)
        return False


def crear_lista(item):
    logger.debug()

    titulo = platformtools.dialog_input(default='', heading=config.get_localized_string(70612))
    if titulo is None or titulo == '':
        return False
    titulo = text_clean(titulo, blank_char='_')

    filename = get_filename_from_name(titulo)
    fullfilename = os.path.join(config.get_data_path(), filename)

    # Check that the file does not already exist
    if os.path.exists(fullfilename):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70613) + '\n' + fullfilename)
        return False

    # Cause it to be saved with empty folders by default
    alfav = KodfavouritesData(filename)

    platformtools.itemlist_refresh()
    return True


def descargar_lista(item, url):
    logger.debug()
    from core import httptools, scrapertools

    if 'tinyupload.com/' in url:
        try:
            from urllib.parse import urlparse
            data = httptools.downloadpage(url).data
            logger.debug(data)
            down_url, url_name = scrapertools.find_single_match(data, ' href="(download\.php[^"]*)"><b>([^<]*)')
            url_json = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(url)) + down_url
        except:
            platformtools.dialog_ok('S4Me', config.get_localized_string(70655) + '\n' + url)
            return False

    elif 'zippyshare.com/' in url:
        from core import servertools
        video_urls, puedes, motivo = servertools.resolve_video_urls_for_playing('zippyshare', url)

        if not puedes:
            platformtools.dialog_ok('S4Me', config.get_localized_string(70655) + '\n' + motivo)
            return False
        url_json = video_urls[0][1] # https://www58.zippyshare.com/d/qPzzQ0UM/25460/addonfavorites-testeanding.json
        url_name = url_json[url_json.rfind('/')+1:]

    elif 'friendpaste.com/' in url:
        url_json = url if url.endswith('/raw') else url + '/raw'
        url_name = 'friendpaste'

    else:
        url_json = url
        url_name = url[url.rfind('/')+1:]


    # Download json
    data = httptools.downloadpage(url_json).data

    # Verify ksonfavourites json format and add download info
    jsondata = jsontools.load(data)
    if 'user_favorites' not in jsondata or 'info_lista' not in jsondata:
        logger.debug(data)
        platformtools.dialog_ok('S4Me', config.get_localized_string(70656))
        return False

    jsondata['info_lista']['downloaded_date'] = fechahora_actual()
    jsondata['info_lista']['downloaded_from'] = url
    data = jsontools.dump(jsondata)

    # Ask for name for downloaded list
    nombre = get_name_from_filename(url_name)
    titulo = platformtools.dialog_input(default=nombre, heading=config.get_localized_string(70657))
    if titulo is None or titulo == '':
        return False
    titulo = text_clean(titulo, blank_char='_')

    filename = get_filename_from_name(titulo)
    fullfilename = os.path.join(config.get_data_path(), filename)

    # If the new name already exists ask for confirmation to overwrite
    if os.path.exists(fullfilename):
        if not platformtools.dialog_yesno('S4Me', config.get_localized_string(70613), config.get_localized_string(70658), filename):
            return False

    if not filetools.write(fullfilename, data):
        platformtools.dialog_ok('S4Me', config.get_localized_string(70659) + '\n' + filename)

    platformtools.dialog_ok('S4Me', config.get_localized_string(70660) + '\n' + filename)
    platformtools.itemlist_refresh()
    return True
