# -*- coding: utf-8 -*-
# Canale TMDb per S4Me.
# Mostra le categorie di TMDB (film e serie) e al click riproduce subito: il video si chiede direttamente ai player
# raggiungibili da un id (VixSrc con l'id TMDB, vidxgo con l'id IMDb), senza cercare il titolo nei siti.
# I riferimenti sono solo id, quindi il canale non dipende dai domini dei siti e i widget non si rompono.
# Gli anime che quei player non hanno si cercano per id AniList o MyAnimeList nel modulo tmdb_anime (facoltativo).
# Tutto il resto lo fa S4Me: autoplay o finestra dei server, e "Cerca negli altri canali" dal menu contestuale.

import sys
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from core import support, tmdb, servertools
from core.item import Item
from platformcode import config, logger, platformtools

# Canali da provare in ordine di priorita. Ogni canale deve avere play(item) che costruisce
# l'indirizzo da item.tmdb / infoLabels['tmdb_id'] (con item.season e item.episode per le serie).
# Facoltativa: disponibile(tmdb_id, tipo, stagione, episodio), per saltare subito chi non ha il titolo.
CANALI = ['vixsrc']

# Player raggiungibili direttamente da un id, senza passare dai siti. Vidxgo usa l'id IMDb senza "tt":
# <host>/<imdb> per i film, <host>/<imdb>/<stagione>/<episodio> per le serie (come fanno i canali che lo usano).
VIDXGO_HOST = 'https://v.vidxgo.co'   # usato solo se servers/vidxgo.py non indica il suo HOST

# il canale non usa nessun sito, solo TMDB
host = ''

IMG = 'https://image.tmdb.org/t/p/'
# False: nelle liste i titoli non hanno la copertina davanti (resta lo sfondo). True la rimette.
COPERTINE = True
ATTESA_SERVER = 10  # secondi per controllare che un server abbia davvero il video
ATTESA_SERVER_ALTRI = 2  # dopo il primo server valido, secondi concessi agli altri

# Menu come quello di TMDb Helper (senza Trakt e senza le voci legate alla libreria di Kodi): la radice ha Film, Serie TV,
# Persone, Cerca e TheMovieDb. Film, Serie TV e Persone mostrano subito le sezioni; TheMovieDb le raggruppa in
# sottosezioni. Voci: (titolo, azione, argomento). L'azione 'lista' apre l'elenco di titoli di quel percorso TMDB.
MENU_FILM = [
    ('Popolare', 'lista', 'movie/popular'),
    ('Più apprezzati', 'lista', 'movie/top_rated'),
    ('In arrivo', 'lista', 'movie/upcoming?region=IT'),
    ('Di tendenza oggi', 'lista', 'trending/movie/day'),
    ('Di tendenza questa settimana', 'lista', 'trending/movie/week'),
    ('Al cinema', 'lista', 'movie/now_playing?region=IT'),
    ('Generi', 'generi', 'movie'),
    ('Provider', 'piattaforme', 'movie'),
    ('Entrate più alte', 'lista', 'discover/movie?sort_by=revenue.desc'),
    ('I più votati', 'lista', 'discover/movie?sort_by=vote_count.desc'),
    ('Studi', 'studi', ''),
    ('Collezioni', 'collezioni', ''),
    ('Parole chiave', 'parole_chiave', ''),
]

MENU_SERIE = [
    ('Popolare', 'lista', 'tv/popular'),
    ('Più apprezzati', 'lista', 'tv/top_rated'),
    ('Di tendenza oggi', 'lista', 'trending/tv/day'),
    ('Di tendenza questa settimana', 'lista', 'trending/tv/week'),
    ('In onda oggi', 'lista', 'tv/airing_today'),
    ('Attualmente in onda', 'lista', 'tv/on_the_air'),
    ('Prossimo in onda nella libreria', 'lista', 'calendario_libreria'),
    ('Library dei prossimi in onda', 'lista', 'in_onda_libreria'),
    ('Generi', 'generi', 'tv'),
    ('Provider', 'piattaforme', 'tv'),
    ('I più votati', 'lista', 'discover/tv?sort_by=vote_count.desc'),
    ('Reti', 'reti', ''),
]

MENU_PERSONE = [
    ('Popolare', 'persone', 'person/popular'),
    ('Di tendenza oggi', 'persone', 'trending/person/day'),
    ('Di tendenza questa settimana', 'persone', 'trending/person/week'),
]

# TheMovieDb: le sezioni con piu voci sono sottosezioni, quelle con una sola voce si aprono direttamente
GRUPPI = [
    ('Popolare', [('Popolare Film', 'lista', 'movie/popular'), ('Popolare Serie TV', 'lista', 'tv/popular'),
                  ('Popolare Persone', 'persone', 'person/popular')]),
    ('Più apprezzati', [('Più apprezzati Film', 'lista', 'movie/top_rated'),
                        ('Più apprezzati Serie TV', 'lista', 'tv/top_rated')]),
    ('In arrivo', [('In arrivo Film', 'lista', 'movie/upcoming?region=IT'),
                   ('Al cinema Film', 'lista', 'movie/now_playing?region=IT'),
                   ('In onda oggi Serie TV', 'lista', 'tv/airing_today'),
                   ('Attualmente in onda Serie TV', 'lista', 'tv/on_the_air')]),
    ('Di tendenza', [('Di tendenza oggi Film', 'lista', 'trending/movie/day'),
                     ('Di tendenza oggi Serie TV', 'lista', 'trending/tv/day'),
                     ('Di tendenza oggi Persone', 'persone', 'trending/person/day'),
                     ('Di tendenza questa settimana Film', 'lista', 'trending/movie/week'),
                     ('Di tendenza questa settimana Serie TV', 'lista', 'trending/tv/week'),
                     ('Di tendenza questa settimana Persone', 'persone', 'trending/person/week')]),
    ('Generi', [('Generi Film', 'generi', 'movie'), ('Generi Serie TV', 'generi', 'tv')]),
    ('Provider', [('Provider Film', 'piattaforme', 'movie'), ('Provider Serie TV', 'piattaforme', 'tv')]),
    ('Entrate più alte', [('Entrate più alte', 'lista', 'discover/movie?sort_by=revenue.desc')]),
    ('I più votati', [('I più votati Film', 'lista', 'discover/movie?sort_by=vote_count.desc'),
                      ('I più votati Serie TV', 'lista', 'discover/tv?sort_by=vote_count.desc')]),
    ('Studi', [('Studi Film', 'studi', ''), ('Reti Serie TV', 'reti', '')]),
    ('Collezioni', [('Collezioni', 'collezioni', '')]),
    ('Parole chiave', [('Parole chiave', 'parole_chiave', '')]),
]


# Icone delle voci di menu: S4Me le sceglie dal titolo (support.thumb con un Item), come fa per i canali con
# @support.menu. Per le poche voci che quel riconoscimento non copre si indica l'icona a mano.
ICONE_A_MANO = {'collezioni': 'movie', 'più apprezzati': 'top_rated', 'di tendenza': 'popular', 'persone': 'star',
                'provider': 'on_the_air', 'entrate': 'top_rated', 'libreria': 'videolibrary', 'cronologia': 'update'}


def _icona(titolo):
    nome = titolo.lower()
    for parte, icona in ICONE_A_MANO.items():
        if parte in nome:
            return support.thumb(icona)
    try:
        trovata = support.thumb(Item(title=titolo)).thumbnail
    except Exception:
        trovata = ''
    # mai l'icona generica senza nome (e quella del pulsante "successivo"): se una lista ha la stessa immagine del
    # suo genitore, S4Me la sostituisce con il segnaposto di film e serie e il pulsante appare come una cartella
    return trovata or support.thumb('all')


def _successivo(item, pagina, tipo=None):
    # il pulsante "Successivo >" costruito come fa support.scrape: un Item nuovo (non una copia della voce genitore),
    # con l'icona del framework e prevthumb. Il tipo non deve restare 'undefined': Kodi disegna quel tipo come
    # cartella (stesso difetto gia risolto negli altri canali), quindi si usa film o serie TV
    tipo = tipo or item.contentType
    if tipo not in ('movie', 'tvshow'):
        tipo = 'movie'
    return Item(channel=item.channel, action=item.action, contentType=tipo,
                title=support.typo(config.get_localized_string(30992), 'color std bold'),
                fulltitle=item.fulltitle, show=item.show, url=item.url, args=item.args, page=pagina,
                thumbnail=support.thumb(), prevthumb=item.prevthumb if item.prevthumb else item.thumbnail)


def _cartella(item, titolo, azione, args=''):
    # collezioni e persone passano da 'peliculas': cosi S4Me le mostra con la stessa vista dei film (locandine
    # grandi, senza la miniatura davanti al titolo)
    if azione == 'collezioni':
        azione, args = 'lista', 'collezioni'
    elif azione == 'persone':
        azione = 'lista'
    return Item(channel=item.channel, title=support.typo(titolo, 'bold'),
                action='peliculas' if azione == 'lista' else azione, args=args, page=1,
                thumbnail=_icona(titolo), folder=True)


def _cerca(item, titolo, contenuto, args=''):
    return Item(channel=item.channel, title=support.typo(titolo, 'bold'), action='search', contentType=contenuto,
                args=args, thumbnail=support.thumb('search'), folder=True)


def mainlist(item):
    logger.debug()
    if item.global_search:
        return [Item(channel=item.channel, title='Cerca', action='search', contentType=c, globalsearch=True, folder=True)
                for c in ('movie', 'tvshow')]
    itemlist = [_cartella(item, 'Film', 'menu_film'), _cartella(item, 'Serie TV', 'menu_serie'),
                _cartella(item, 'Cerca', 'menu_cerca')]
    support.channel_config(item, itemlist)
    return itemlist


def _cerca_cartella(item, titolo, contenuto, args=''):
    # come TMDb Helper: "Cerca" e' una cartella con la ricerca, le ultime ricerche e la voce per cancellarle
    return Item(channel=item.channel, title=support.typo(titolo, 'bold'), action='peliculas', args='cerca_cartella',
                tipo_ricerca=contenuto, args_ricerca=args, thumbnail=support.thumb('search'), folder=True)


def menu_film(item):
    return [_cerca_cartella(item, 'Cerca', 'movie')] + [_cartella(item, *voce) for voce in MENU_FILM]


def menu_serie(item):
    return [_cerca_cartella(item, 'Cerca', 'tvshow')] + [_cartella(item, *voce) for voce in MENU_SERIE]


def menu_persone(item):
    return [_cerca_cartella(item, 'Cerca', 'undefined', 'persone')] + [_cartella(item, *voce) for voce in MENU_PERSONE]


def menu_cerca(item):
    return [_cerca_cartella(item, 'Cerca film', 'movie'), _cerca_cartella(item, 'Cerca serie TV', 'tvshow'),
            _cerca_cartella(item, 'Cerca persone', 'undefined', 'persone')]


def menu_tmdb(item):
    itemlist = [_cerca(item, 'Cerca', 'undefined')]
    for nome, voci in GRUPPI:
        if len(voci) > 1:
            itemlist.append(_cartella(item, nome, 'gruppo', nome))
        else:
            itemlist.append(_cartella(item, *voci[0]))
    return itemlist


def gruppo(item):
    for nome, voci in GRUPPI:
        if nome == item.args:
            return [_cartella(item, *voce) for voce in voci]
    return []


# TMDB

def _date(percorso):
    ora = datetime.now()
    for chiave, giorni in (('{oggi}', 0), ('{fa180}', 180), ('{fa365}', 365), ('{fa1095}', 1095)):
        percorso = percorso.replace(chiave, (ora - timedelta(days=giorni)).strftime('%Y-%m-%d'))
    return percorso


def _tmdb(percorso, pagina=None):
    sep = '&' if '?' in percorso else '?'
    url = '%s/%s%sapi_key=%s&language=%s' % (tmdb.host, percorso, sep, tmdb.api, tmdb.def_lang)
    if pagina:
        url += '&page=%d' % pagina
    return url


def _latino(testo):
    return all(ord(c) < 0x250 or not c.isalpha() for c in testo or '')


def _titoli_latini(dati, percorso, pagina):
    # TMDB senza traduzione italiana restituisce il titolo originale (giapponese, hindi, ecc.): Kodi lo mostra con dei
    # quadratini e la ricerca negli altri canali non trova niente. Per i titoli non latini di una pagina si prova la stessa
    # pagina in inglese e, se manca ancora qualcosa, in qualche altra lingua: una chiamata per lingua, mai una per titolo
    risultati = dati.get('results') or []
    mancanti = set(r.get('id') for r in risultati if not _latino(r.get('title') or r.get('name')))
    trovati = {}
    for lingua in ('en-US', 'es-ES', 'fr-FR', 'de-DE'):
        if not mancanti:
            break
        try:
            url = _tmdb(percorso, pagina).replace('language=%s' % tmdb.def_lang, 'language=%s' % lingua)
            altra = tmdb.Tmdb.get_json(url) or {}
        except Exception:
            logger.error('tmdb: titoli in %s non disponibili' % lingua)
            continue
        for r in altra.get('results') or []:
            nome = r.get('title') or r.get('name')
            if r.get('id') in mancanti and _latino(nome):
                trovati[r.get('id')] = nome
                mancanti.discard(r.get('id'))
    # titoli ancora senza versione latina: si guardano le traduzioni e i titoli alternativi di quel solo titolo
    # (al massimo 10 per pagina, per non fare troppe richieste)
    tipo = 'movie' if 'movie' in percorso.split('?')[0] else 'tv'
    for tmdb_id in list(mancanti)[:10]:
        nome = _titolo_da_traduzioni(tipo, tmdb_id)
        if nome:
            trovati[tmdb_id] = nome
    _trame_inglesi(risultati, percorso, pagina)
    return trovati


def _trame_inglesi(risultati, percorso, pagina):
    # senza traduzione italiana TMDB lascia la trama vuota: si riempie con quella inglese, presa dalla stessa pagina
    # in inglese (una sola chiamata per pagina, mai una per titolo). Se manca anche li resta vuota
    senza = set(r.get('id') for r in risultati if r.get('id') and not r.get('overview'))
    if not senza:
        return
    try:
        url = _tmdb(percorso, pagina).replace('language=%s' % tmdb.def_lang, 'language=en-US')
        altra = tmdb.Tmdb.get_json(url) or {}
    except Exception:
        logger.error('tmdb: trame in inglese non disponibili')
        return
    inglesi = dict((r.get('id'), r.get('overview')) for r in altra.get('results') or [] if r.get('overview'))
    for r in risultati:
        if r.get('id') in senza and inglesi.get(r.get('id')):
            r['overview'] = inglesi[r['id']]


def _titolo_da_traduzioni(tipo, tmdb_id):
    # una sola richiesta per titolo, con traduzioni e titoli alternativi: si prende un titolo in alfabeto latino
    # (inglese e italiano per primi)
    candidati = []
    try:
        dati = tmdb.Tmdb.get_json('%s/%s/%s?api_key=%s&append_to_response=translations,alternative_titles'
                                  % (tmdb.host, tipo, tmdb_id, tmdb.api)) or {}
        for t in (dati.get('translations') or {}).get('translations') or []:
            d = t.get('data') or {}
            nome = d.get('title') or d.get('name')
            if nome and _latino(nome):
                candidati.append((0 if t.get('iso_639_1') == 'en' else 1 if t.get('iso_639_1') == 'it' else 2, nome))
        alt = dati.get('alternative_titles') or {}
        for t in alt.get('titles') or alt.get('results') or []:
            if t.get('title') and _latino(t['title']):
                candidati.append((3, t['title']))
    except Exception:
        logger.error('tmdb: traduzioni di %s non disponibili' % tmdb_id)
        return None
    return sorted(candidati, key=lambda c: c[0])[0][1] if candidati else None


_NOMI_LINGUE = {'ja': 'giapponese', 'ko': 'coreano', 'zh': 'cinese', 'cn': 'cinese', 'th': 'thai', 'hi': 'hindi',
                'ar': 'arabo', 'ru': 'russo', 'fa': 'persiano', 'he': 'ebraico', 'bn': 'bengalese', 'ta': 'tamil',
                'te': 'telugu', 'ml': 'malayalam', 'uk': 'ucraino', 'el': 'greco'}


def _durate(risultati, tipo):
    # la durata non e nelle liste di TMDB: si chiede la scheda di ogni titolo della pagina, in parallelo (come TMDb
    # Helper). Per i film e' runtime, per le serie la durata di una puntata.
    from concurrent import futures

    def una(r):
        try:
            d = tmdb.Tmdb.get_json(_tmdb('%s/%s' % (tipo, r['id']))) or {}
        except Exception:
            return
        minuti = d.get('runtime') if tipo == 'movie' else (
            (d.get('episode_run_time') or [None])[0] or (d.get('last_episode_to_air') or {}).get('runtime'))
        if minuti:
            r['_durata'] = minuti

    elenco = [r for r in risultati if r.get('id')]
    if elenco:
        with futures.ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(una, elenco))
    _senza_durata_a_destra()


def _senza_durata_a_destra():
    # senza un metodo di ordinamento Kodi mostra la durata a destra di ogni riga (maschera %D). La skin la mostra gia
    # in basso accanto alla data, quindi si indica un ordinamento 'non ordinato' con la seconda etichetta vuota
    try:
        import xbmcplugin
        xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED, '%L', ' ')
    except Exception:
        logger.error('tmdb: metodo di ordinamento non impostato')


def _elemento(r, tipo, base, latini=None):
    # un elemento costruito solo con i dati gia presenti nella risposta di TMDB: nessuna chiamata in piu
    tmdb_id = r.get('id')
    nome = r.get('title') or r.get('name')
    visibile = nome
    if not _latino(nome):
        trovato = (latini or {}).get(tmdb_id)
        if trovato:
            nome = visibile = trovato
        else:
            # nessun titolo latino su TMDB: nella lista si mostra la lingua, al posto dei quadratini
            visibile = 'Titolo %s' % _NOMI_LINGUE.get(r.get('original_language'), 'non leggibile')
    if not tmdb_id or not nome:
        return None
    data = r.get('release_date') or r.get('first_air_date') or ''
    anno = data[:4]
    voto = round(r.get('vote_average') or 0, 1)
    titolo = support.typo(visibile, 'bold')
    # niente anno ne voto nel titolo: la skin mostra la data (premiered) in basso e il voto sulla copertina
    info = {'tmdb_id': str(tmdb_id), 'year': anno, 'plot': r.get('overview') or '', 'rating': voto}
    if data:
        info['premiered'] = data
    minuti = r.get('_durata') or r.get('runtime') or (r.get('episode_run_time') or [0])[0]
    if minuti:
        info['duration'] = int(minuti) * 60  # Kodi vuole i secondi
    poster = (IMG + 'w500' + r['poster_path']) if r.get('poster_path') else support.thumb('movie')
    fanart = (IMG + 'original' + r['backdrop_path']) if r.get('backdrop_path') else ''
    comuni = dict(channel=base.channel, title=titolo, fulltitle=nome, show=nome,
                  thumbnail=poster if COPERTINE else '', fanart=fanart,
                  plot=r.get('overview') or '', tmdb=str(tmdb_id),
                  data_uscita=data, tmdb_stat=True,  # tmdb_stat: la videoteca non deve cercare di nuovo il titolo su TMDB
                  titolo_originale=(r.get('original_title') or r.get('original_name') or ''))
    if tipo == 'movie':
        info.update(mediatype='movie', title=nome)
        azione = _azione_click(base.channel)
        menu = [{'title': 'Vai alla collezione', 'action': 'collezione_del_film', 'channel': base.channel}]
        if azione != 'findvideos':
            # con findvideos S4Me aggiunge da solo la voce; con le altre azioni la si aggiunge qui (add_movie salva findvideos)
            menu.append({'title': config.get_localized_string(60353), 'action': 'add_pelicula_to_library'})
        return Item(action=azione, contentType='movie', contentTitle=nome, infoLabels=info, context=menu, **comuni)
    info.update(mediatype='tvshow', tvshowtitle=nome)
    return Item(action='seasons', folder=True, contentType='tvshow', contentSerieName=nome, infoLabels=info,
                context=[{'title': config.get_localized_string(60352), 'action': 'aggiungi_serie'}], **comuni)


def peliculas(item):
    logger.debug()
    # elenchi che S4Me deve mostrare con la vista a locandine dei film: la vista dipende dall'azione 'peliculas'
    smistamento = {'collezioni': collezioni, 'cerca_collezioni': cerca_collezioni,
                   'scheda_collezione': collezione, 'filmografia_persona': filmografia,
                   'cerca_cartella': cerca_cartella, 'cerca_storico': cerca_storico, 'cerca_cancella': cerca_cancella,
                   'calendario_libreria': calendario_libreria, 'in_onda_libreria': in_onda_libreria}
    if item.args in smistamento:
        return smistamento[item.args](item)
    if 'person' in (item.args or '').split('?')[0].split('/'):
        return persone(item)
    percorso = _date(item.args or ('movie/popular' if item.contentType == 'movie' else 'tv/popular'))
    tipo = 'movie' if 'movie' in percorso.split('?')[0] else 'tv'
    pagina = int(item.page or 1)
    itemlist = []
    try:
        dati = tmdb.Tmdb.get_json(_tmdb(percorso, pagina)) or {}
    except Exception:
        logger.error('tmdb: elenco non disponibile')
        return itemlist
    latini = _titoli_latini(dati, percorso, pagina)
    _durate(dati.get('results') or [], tipo)
    for r in dati.get('results') or []:
        el = _elemento(r, tipo, item, latini)
        if el:
            itemlist.append(el)
    if (dati.get('total_pages') or 1) > pagina:
        itemlist.append(_successivo(item, pagina + 1, 'movie' if tipo == 'movie' else 'tvshow'))
    return itemlist


def _voce(item, titolo, percorso):
    return item.clone(title=support.typo(titolo, 'bold'), action='peliculas', args=percorso, page=1,
                      thumbnail=_icona(titolo), folder=True)


def piattaforme(item):
    # come TMDb Helper: i provider sono quelli che TMDB elenca per l'Italia (stesso ordine, stesse icone)
    logger.debug()
    tipo = item.args or 'movie'
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('watch/providers/%s?watch_region=IT' % tipo)) or {}
    except Exception:
        logger.error('tmdb: provider non disponibili')
        dati = {}
    itemlist = []
    for p in sorted(dati.get('results') or [], key=lambda x: x.get('display_priority', 9999)):
        voce = _voce(item, p['provider_name'],
                     'discover/%s?watch_region=IT&with_watch_providers=%s&sort_by=popularity.desc' % (tipo, p['provider_id']))
        if p.get('logo_path'):
            voce.thumbnail = IMG + 'w500' + p['logo_path']
        itemlist.append(voce)
    if not itemlist:
        platformtools.dialog_notification('TMDb', 'Elenco delle piattaforme non disponibile')
    return itemlist


def generi(item):
    logger.debug()
    tipo = item.args or 'movie'
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('genre/%s/list' % tipo))
    except Exception:
        logger.error('tmdb: generi non disponibili')
        return []
    return [_voce(item, g['name'], 'discover/%s?with_genres=%s&sort_by=popularity.desc' % (tipo, g['id']))
            for g in sorted((dati or {}).get('genres', []), key=lambda x: x.get('name', ''))]


# Cronologia delle ricerche: salvata con le impostazioni del canale (stesso meccanismo degli altri canali), una lista per tipo

MAX_STORIA = 20


def _chiave_storia(item):
    return 'persone' if (item.args == 'persone' or item.args_ricerca == 'persone') else (item.contentType or item.tipo_ricerca or 'undefined')


def _leggi_storia(chiave):
    from core import channeltools
    try:
        dati = channeltools.get_channel_setting('cronologia_ricerche', 'tmdb', {}) or {}
        return [x for x in dati.get(chiave, []) if x]
    except Exception:
        return []


def _salva_storia(chiave, testo):
    from core import channeltools
    try:
        dati = channeltools.get_channel_setting('cronologia_ricerche', 'tmdb', {}) or {}
        elenco = [x for x in dati.get(chiave, []) if x.lower() != testo.lower()]
        dati[chiave] = ([testo] + elenco)[:MAX_STORIA]
        channeltools.set_channel_setting('cronologia_ricerche', dati, 'tmdb')
    except Exception:
        logger.error('tmdb: cronologia delle ricerche non salvata')


def cerca_cartella(item):
    contenuto = item.tipo_ricerca or 'undefined'
    args = item.args_ricerca or ''
    nome = {'movie': 'film', 'tvshow': 'serie TV'}.get(contenuto, 'persone' if args == 'persone' else 'titoli')
    itemlist = [_cerca(item, 'Cerca %s' % nome, contenuto, args)]
    storia = _leggi_storia('persone' if args == 'persone' else contenuto)
    for testo in storia:
        itemlist.append(Item(channel=item.channel, title=support.typo(testo, 'bold'), action='peliculas',
                             args='cerca_storico', tipo_ricerca=contenuto, args_ricerca=args, testo=testo,
                             contentType=contenuto, thumbnail=support.thumb('search'), folder=True))
    if storia:
        itemlist.append(Item(channel=item.channel, title=support.typo('Cancella cronologia ricerche', 'bold'),
                             action='peliculas', args='cerca_cancella', tipo_ricerca=contenuto, args_ricerca=args,
                             thumbnail=_icona('cronologia'), folder=False))
    return itemlist


def cerca_storico(item):
    # una ricerca gia fatta, rilanciata dalla cronologia
    ricerca = item.clone(args=item.args_ricerca or '', contentType=item.tipo_ricerca or 'undefined')
    return search(ricerca, item.testo)


def cerca_cancella(item):
    from core import channeltools
    try:
        dati = channeltools.get_channel_setting('cronologia_ricerche', 'tmdb', {}) or {}
        dati.pop('persone' if item.args_ricerca == 'persone' else (item.tipo_ricerca or 'undefined'), None)
        channeltools.set_channel_setting('cronologia_ricerche', dati, 'tmdb')
    except Exception:
        logger.error('tmdb: cronologia delle ricerche non cancellata')
    platformtools.dialog_notification('TMDb', 'Cronologia cancellata', sound=False)
    platformtools.itemlist_refresh()
    return None


# Serie della libreria di Kodi con la prossima puntata in onda (come TMDb Helper: due voci, il calendario per giorno e
# l'elenco ordinato). Le serie si leggono dalla libreria di Kodi, i dati dell'episodio successivo vengono da TMDB.

def _serie_libreria():
    import json
    import xbmc
    try:
        risposta = json.loads(xbmc.executeJSONRPC(json.dumps(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'VideoLibrary.GetTVShows',
             'params': {'properties': ['uniqueid', 'imdbnumber']}})))
    except Exception:
        logger.error('tmdb: libreria di Kodi non letta')
        return []
    ids = []
    for serie in (risposta.get('result') or {}).get('tvshows') or []:
        trovato = (serie.get('uniqueid') or {}).get('tmdb') or ''
        if not str(trovato).isdigit():
            trovato = serie.get('imdbnumber') or ''
        if str(trovato).isdigit() and trovato not in ids:
            ids.append(str(trovato))
    return ids


def _prossime_puntate():
    # [(data, scheda serie TMDB)] per le serie della libreria che hanno una puntata in arrivo
    from concurrent import futures
    ids = _serie_libreria()
    if not ids:
        platformtools.dialog_notification('TMDb', 'Nessuna serie nella libreria di Kodi')
        return []

    def scheda(id_serie):
        try:
            return tmdb.Tmdb.get_json(_tmdb('tv/%s' % id_serie)) or {}
        except Exception:
            return {}

    with futures.ThreadPoolExecutor(max_workers=10) as executor:
        schede = list(executor.map(scheda, ids))
    oggi = datetime.now().strftime('%Y-%m-%d')
    prossime = []
    for r in schede:
        pross = r.get('next_episode_to_air') or {}
        if r.get('id') and r.get('name') and (pross.get('air_date') or '') >= oggi:
            prossime.append((pross['air_date'], r, pross))
    prossime.sort(key=lambda x: x[0])
    if not prossime:
        platformtools.dialog_notification('TMDb', 'Nessuna puntata in arrivo per le serie della libreria')
    return prossime


def _voce_puntata(item, data, r, pross):
    el = _elemento(r, 'tv', item)
    if not el:
        return None
    giorno = '%s/%s' % (data[8:10], data[5:7])
    el.title = support.typo(r['name'], 'bold') + support.typo('%dx%02d %s' % (
        pross.get('season_number') or 0, pross.get('episode_number') or 0, giorno), '_ [] color std')
    return el


def in_onda_libreria(item):
    return [v for v in (_voce_puntata(item, d, r, p) for d, r, p in _prossime_puntate()) if v]


def calendario_libreria(item):
    from datetime import timedelta
    if not item.giorno:
        itemlist = []
        nomi = ('lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom')
        for n in range(14):
            d = datetime.now() + timedelta(days=n)
            etichetta = 'Oggi' if n == 0 else 'Domani' if n == 1 else '%s %s/%s' % (nomi[d.weekday()], d.strftime('%d'), d.strftime('%m'))
            itemlist.append(Item(channel=item.channel, title=support.typo(etichetta, 'bold'), action='peliculas',
                                 args='calendario_libreria', giorno=d.strftime('%Y-%m-%d'), page=1,
                                 thumbnail=support.thumb('update'), folder=True))
        return itemlist
    return [v for v in (_voce_puntata(item, d, r, p) for d, r, p in _prossime_puntate() if d == item.giorno) if v]


def search(item, text):
    logger.debug(text)
    itemlist = []
    if text and not item.globalsearch:
        _salva_storia('persone' if item.args == 'persone' else (item.contentType or 'undefined'), text)
    if item.args == 'persone':
        try:
            dati = tmdb.Tmdb.get_json(_tmdb('search/person?query=%s' % quote(text), 1)) or {}
        except Exception:
            logger.error('tmdb: ricerca persone non riuscita')
            return itemlist
        return _persone_da_risultati(item, dati.get('results') or [])
    try:
        for tipo in ('movie', 'tv'):
            if item.contentType in ('movie', 'tvshow') and ('movie' if item.contentType == 'movie' else 'tv') != tipo:
                continue
            percorso = 'search/%s?query=%s' % (tipo, quote(text))
            dati = tmdb.Tmdb.get_json(_tmdb(percorso, 1)) or {}
            latini = _titoli_latini(dati, percorso, 1)
            _durate(dati.get('results') or [], tipo)
            for r in dati.get('results') or []:
                el = _elemento(r, tipo, item, latini)
                if el:
                    itemlist.append(el)
    except Exception:
        import traceback
        logger.error(traceback.format_exc())
    return itemlist


# Collezioni (le saghe di TMDB). TMDB non ha un elenco di tutte le collezioni: si cercano per nome, oppure si apre
# quella a cui appartiene un film dal menu contestuale. Una chiamata per ricerca e una per collezione.

def _parti_collezione(item, id_collezione):
    itemlist = []
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('collection/%s' % id_collezione)) or {}
    except Exception:
        logger.error('tmdb: collezione non disponibile')
        return itemlist
    _durate(dati.get('parts') or [], 'movie')
    for r in sorted(dati.get('parts') or [], key=lambda x: x.get('release_date') or '9999'):
        el = _elemento(r, 'movie', item)
        if el:
            itemlist.append(el)
    if not itemlist:
        platformtools.dialog_notification('TMDb', 'Collezione vuota')
    return itemlist


# Collezioni, studi, reti e parole chiave: come TMDb Helper usano le esportazioni giornaliere ufficiali di TMDB (id e
# nome), perche ne il sito ne l'API hanno un elenco. Si scaricano una volta e si tengono in un piccolo database
# temporaneo per qualche giorno, ordinate per id. Per le collezioni i nomi in italiano si chiedono a TMDB solo per la
# pagina che si apre: 20 collezioni, in parallelo.
ESPORTAZIONI = {'collezioni': 'collection', 'studi': 'production_company', 'reti': 'tv_network', 'parole': 'keyword'}
URL_ESPORTAZIONE = 'https://files.tmdb.org/p/exports/%s_ids_%s.json.gz'
VALIDITA_ELENCO = 7 * 24 * 3600
PER_PAGINA = 20


def _scarica_esportazione(esportazione):
    import gzip
    import json
    from urllib.request import Request, urlopen
    # il file del giorno esce nelle prime ore: se manca si prova con i giorni precedenti
    for giorni in range(4):
        data = (datetime.utcnow() - timedelta(days=giorni)).strftime('%m_%d_%Y')
        try:
            risposta = urlopen(Request(URL_ESPORTAZIONE % (esportazione, data), headers={'User-Agent': 'Mozilla/5.0'}),
                               timeout=60)
            righe = gzip.decompress(risposta.read()).decode('utf-8').splitlines()
        except Exception:
            logger.error('tmdb: esportazione %s del %s non disponibile' % (esportazione, data))
            continue
        elenco = []
        for riga in righe:
            try:
                d = json.loads(riga)
            except ValueError:
                continue
            if d.get('id') and d.get('name'):
                elenco.append((d['id'], d['name']))
        if elenco:
            return elenco
    return []


def _esportazione(tipo, limite, pagina):
    # restituisce (righe della pagina, c'e una pagina successiva)
    import os
    import sqlite3
    esportazione = ESPORTAZIONI[tipo]
    conn = sqlite3.connect(os.path.join(config.get_temp_file(''), 'tmdb_esportazioni.db'))
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS meta (tipo TEXT PRIMARY KEY, aggiornato REAL)')
        riga = conn.execute('SELECT aggiornato FROM meta WHERE tipo=?', (tipo,)).fetchone()
        if not riga or time.time() - riga[0] > VALIDITA_ELENCO:
            elenco = _scarica_esportazione(esportazione)
            if elenco:
                conn.execute('DROP TABLE IF EXISTS %s' % esportazione)
                conn.execute('CREATE TABLE %s (id INTEGER PRIMARY KEY, name TEXT)' % esportazione)
                conn.executemany('INSERT OR REPLACE INTO %s VALUES (?, ?)' % esportazione, elenco)
                conn.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (tipo, time.time()))
                conn.commit()
        try:
            righe = conn.execute('SELECT id, name FROM %s ORDER BY id LIMIT ? OFFSET ?' % esportazione,
                                 (limite + 1, (pagina - 1) * limite)).fetchall()
        except sqlite3.Error:
            righe = []
    finally:
        conn.close()
    return righe[:limite], len(righe) > limite


def _lista_esportazione(item, tipo, parametro, tipo_tmdb):
    # studi, reti e parole chiave: 250 per pagina, ognuno apre i titoli collegati
    logger.debug()
    pagina = int(item.page or 1)
    righe, altre = _esportazione(tipo, 250, pagina)
    if not righe and pagina == 1:
        platformtools.dialog_notification('TMDb', 'Elenco non disponibile')
    itemlist = [_voce(item, nome, 'discover/%s?%s=%s&sort_by=popularity.desc' % (tipo_tmdb, parametro, id_e))
                for id_e, nome in righe]
    if altre:
        itemlist.append(_successivo(item, pagina + 1))
    return itemlist


def studi(item):
    return _lista_esportazione(item, 'studi', 'with_companies', 'movie')


def reti(item):
    return _lista_esportazione(item, 'reti', 'with_networks', 'tv')


def parole_chiave(item):
    return _lista_esportazione(item, 'parole', 'with_keywords', 'movie')


def _scheda_collezione(id_c):
    try:
        return tmdb.Tmdb.get_json(_tmdb('collection/%s' % id_c)) or {}
    except Exception:
        logger.error('tmdb: collezione %s non disponibile' % id_c)
        return {}


def collezioni(item):
    logger.debug()
    from concurrent import futures
    pagina = int(item.page or 1)
    righe, altre = _esportazione('collezioni', PER_PAGINA, pagina)
    if not righe:
        platformtools.dialog_notification('TMDb', 'Elenco delle collezioni non disponibile')
        return []
    blocco = [id_c for id_c, _ in righe]
    with futures.ThreadPoolExecutor(max_workers=10) as executor:
        schede = list(executor.map(_scheda_collezione, blocco))
    itemlist = []
    if pagina == 1:
        itemlist.append(item.clone(title=support.typo('Cerca per nome', 'bold'), action='peliculas', args='cerca_collezioni',
                                   contentType='movie', thumbnail=support.thumb('search'), folder=True))
    for id_c, r in zip(blocco, schede):
        if not r.get('name') or not r.get('parts'):
            continue
        poster = (IMG + 'w500' + r['poster_path']) if r.get('poster_path') else support.thumb('movie')
        fanart = (IMG + 'original' + r['backdrop_path']) if r.get('backdrop_path') else ''
        itemlist.append(Item(channel=item.channel, action='peliculas', args='scheda_collezione', contentType='movie', title=support.typo(r['name'], 'bold'),
                             collezione=str(id_c), thumbnail=poster if COPERTINE else support.thumb('movie'), fanart=fanart,
                             plot=r.get('overview') or '', folder=True))
    if altre:
        itemlist.append(_successivo(item, pagina + 1))
    return itemlist


def cerca_collezioni(item):
    logger.debug()
    testo = platformtools.dialog_input('', 'Cerca una collezione')
    if not testo:
        return []
    itemlist = []
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('search/collection?query=%s' % quote(testo), 1)) or {}
    except Exception:
        logger.error('tmdb: ricerca collezioni non riuscita')
        return itemlist
    for r in dati.get('results') or []:
        if not r.get('id') or not r.get('name'):
            continue
        poster = (IMG + 'w500' + r['poster_path']) if r.get('poster_path') else support.thumb('movie')
        fanart = (IMG + 'original' + r['backdrop_path']) if r.get('backdrop_path') else ''
        itemlist.append(Item(channel=item.channel, action='peliculas', args='scheda_collezione', contentType='movie', title=support.typo(r['name'], 'bold'),
                             collezione=str(r['id']), thumbnail=poster if COPERTINE else support.thumb('movie'), fanart=fanart,
                             plot=r.get('overview') or '', folder=True))
    if not itemlist:
        platformtools.dialog_notification('TMDb', 'Nessuna collezione trovata')
    return itemlist


def collezione(item):
    logger.debug()
    return _parti_collezione(item, item.collezione)


def collezione_del_film(item):
    # dal menu contestuale di un film: si apre la collezione a cui appartiene, se ne ha una
    logger.debug()
    tmdb_id = item.infoLabels.get('tmdb_id') or item.tmdb
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('movie/%s' % tmdb_id)) or {}
    except Exception:
        logger.error('tmdb: scheda del film non disponibile')
        return []
    raccolta = dati.get('belongs_to_collection') or {}
    if not raccolta.get('id'):
        platformtools.dialog_notification('TMDb', 'Questo film non fa parte di una collezione')
        return []
    return _parti_collezione(item, raccolta['id'])


def _persone_da_risultati(item, risultati):
    itemlist = []
    for r in risultati:
        if not r.get('id') or not r.get('name'):
            continue
        foto = (IMG + 'w500' + r['profile_path']) if r.get('profile_path') else support.thumb('star')
        noti = ', '.join(x.get('title') or x.get('name') or '' for x in (r.get('known_for') or [])[:3])
        itemlist.append(Item(channel=item.channel, action='peliculas', args='filmografia_persona', contentType='movie', title=support.typo(r['name'], 'bold'),
                             persona=str(r['id']), thumbnail=foto if COPERTINE else support.thumb('star'), plot=noti, folder=True))
    return itemlist


def persone(item):
    logger.debug()
    pagina = int(item.page or 1)
    try:
        dati = tmdb.Tmdb.get_json(_tmdb(item.args, pagina)) or {}
    except Exception:
        logger.error('tmdb: elenco persone non disponibile')
        return []
    itemlist = _persone_da_risultati(item, dati.get('results') or [])
    if (dati.get('total_pages') or 1) > pagina:
        itemlist.append(_successivo(item, pagina + 1))
    return itemlist


def filmografia(item):
    # film e serie di una persona, dai piu popolari
    logger.debug()
    try:
        dati = tmdb.Tmdb.get_json(_tmdb('person/%s/combined_credits' % item.persona)) or {}
    except Exception:
        logger.error('tmdb: filmografia non disponibile')
        return []
    itemlist = []
    visti = set()
    for r in sorted(dati.get('cast') or [], key=lambda x: x.get('popularity') or 0, reverse=True):
        tipo = r.get('media_type')
        if tipo not in ('movie', 'tv') or (tipo, r.get('id')) in visti:
            continue
        visti.add((tipo, r.get('id')))
        el = _elemento(r, tipo, item)
        if el:
            itemlist.append(el)
    return itemlist


# Serie: prima le stagioni (azione seasons, riconosciuta da S4Me per la vista delle stagioni, dati gia nella
# scheda della serie), poi gli episodi di una sola stagione. Una chiamata a TMDB per livello, mai una per episodio.

def seasons(item):
    logger.debug()
    itemlist = []
    id_serie = item.infoLabels.get('tmdb_id') or item.tmdb
    nome = item.contentSerieName or item.fulltitle
    try:
        otmdb = tmdb.Tmdb(id_Tmdb=id_serie, search_type='tv')
        elenco = (otmdb.result or {}).get('seasons') or []
    except Exception:
        logger.error('tmdb: scheda serie non disponibile')
        return itemlist
    trama = item.plot or (otmdb.result or {}).get('overview') or ''
    if not trama:  # senza trama in italiano si ripiega sull'inglese, una sola chiamata
        try:
            url = _tmdb('tv/%s' % id_serie).replace('language=%s' % tmdb.def_lang, 'language=en-US')
            trama = (tmdb.Tmdb.get_json(url) or {}).get('overview') or ''
        except Exception:
            trama = ''
    for s in elenco:
        n = s.get('season_number')
        if not n:  # salta gli speciali (stagione 0)
            continue
        img = (IMG + 'w500' + s['poster_path']) if s.get('poster_path') else item.thumbnail
        itemlist.append(item.clone(title=support.typo(s.get('name') or 'Stagione %d' % n, 'bold'),
                                   action='episodios', season=n, contentSeason=n, thumbnail=img,
                                   plot=s.get('overview') or trama, fulltitle=nome, show=nome, folder=True))
    # come gli altri canali: voce "Aggiungi alla videoteca" in fondo, salva tutte le stagioni tramite episodios
    support.videolibrary(itemlist, item.clone(action='episodios', season=''), function='episodios')
    return itemlist


def aggiungi_serie(item):
    # dal menu contestuale della serie: stessa cosa della voce in fondo all'elenco, S4Me chiama episodios senza stagione
    from core import videolibrarytools
    serie = item.clone(action='episodios', season='', contentType='tvshow', from_action='', from_channel='')
    videolibrarytools.add_tvshow(serie)


def episodios(item):
    logger.debug()
    itemlist = []
    id_serie = item.infoLabels.get('tmdb_id') or item.tmdb
    nome = item.contentSerieName or item.fulltitle
    oggi = datetime.now().strftime('%Y-%m-%d')
    # senza stagione (aggiunta alla videoteca, aggiornamento automatico della libreria) servono tutte le stagioni
    # e gli episodi con azione findvideos, perche il canale non guarda piu come si e arrivati li
    libreria = not item.season or support.stackCheck(['add_tvshow'])
    try:
        otmdb = tmdb.Tmdb(id_Tmdb=id_serie, search_type='tv')
        if libreria:
            stagioni = [s['season_number'] for s in (otmdb.result or {}).get('seasons') or [] if s.get('season_number')]
        else:
            stagioni = [int(item.season)]
    except Exception:
        logger.error('tmdb: scheda serie non disponibile')
        return itemlist
    azione = 'findvideos' if libreria else _azione_click(item.channel)
    for n in stagioni:
        try:
            dati = otmdb.get_season(n) or {}
        except Exception:
            logger.error('tmdb: stagione %s non disponibile' % n)
            continue
        for e in dati.get('episodes') or []:
            num = e.get('episode_number')
            if num is None or (e.get('air_date') or '9999') > oggi:
                continue  # episodi non ancora usciti
            titolo = e.get('name') or ''
            # gli episodi ereditano la copertina della stagione (o della serie se la stagione non ce l'ha): niente
            # immagini per ogni episodio. Quelle le prende il tmdb di S4Me quando la serie va in videoteca
            img = item.thumbnail
            itemlist.append(item.clone(title=support.typo('%dx%02d' % (n, num) + (': ' + titolo if titolo else ''), 'bold'),
                                       action=azione, contentType='episode', contentSeason=n,
                                       contentEpisodeNumber=num, season=n, episode=num, thumbnail=img,
                                       tmdb=str(id_serie), fulltitle=nome, show=nome, contentSerieName=nome, context=[],
                                       plot=e.get('overview') or item.plot or ''))
    return itemlist


# Riproduzione: i player diretti per id, controllati prima di passarli a S4Me

def _carica(nome):
    # stesso caricatore usato da S4Me per eseguire le azioni dei canali
    try:
        return platformtools.channelImport(nome)
    except Exception:
        logger.error('tmdb: canale %s non caricabile' % nome)
        return None


def _con_server(risultato):
    # play() di un canale puo restituire un item senza server: S4Me lo tratterebbe come "directo".
    # Il server si ricava dall'indirizzo con gli stessi schemi usati da servers/*.json.
    if risultato and isinstance(risultato[0], Item) and not risultato[0].server and risultato[0].url:
        try:
            trovato = servertools.get_server_from_url(risultato[0].url)
            if trovato:
                risultato[0].server = trovato[2]
                risultato[0].url = trovato[1]
        except Exception:
            logger.error('tmdb: server non riconosciuto per %s' % risultato[0].url)
    return risultato


def _server_esiste(voce):
    # stesso controllo che S4Me fa prima di riprodurre (server.test_video_exists): l'elenco di un canale
    # puo contenere titoli che poi il server non ha, e a quel punto sarebbe troppo tardi per il fallback
    try:
        if not voce.server or not voce.url:
            return True
        modulo = __import__('servers.%s' % voce.server, None, None, ['servers.%s' % voce.server])
        if hasattr(modulo, 'test_video_exists'):
            risposta = modulo.test_video_exists(page_url=voce.url)
            primo = risposta[0] if isinstance(risposta, (tuple, list)) else risposta
            # valido solo con True: alcuni server rispondono con un testo ("Prossimamente") al posto di False
            return primo is True
    except Exception:
        logger.error('tmdb: controllo del server non riuscito per %s' % voce.server)
    return True


def _dai_canali(item, controlla=True):
    # prova i canali di CANALI in ordine di priorita e restituisce la lista da riprodurre, oppure None
    tmdb_id = item.tmdb or item.infoLabels.get('tmdb_id') or item.infoLabels.get('tmdb_id_show')
    serie = bool(item.season and item.episode)
    tipo = 'tv' if serie else 'movie'
    for nome in CANALI:
        canale = _carica(nome)
        if not canale or not hasattr(canale, 'play'):
            continue
        try:
            if hasattr(canale, 'disponibile') and not canale.disponibile(
                    tmdb_id, tipo, item.season if serie else None, item.episode if serie else None):
                logger.debug('tmdb: %s non ha il titolo, provo il prossimo canale' % nome)
                continue
            proposta = item.clone(channel=nome, action='play', url='', tmdb=str(tmdb_id))
            risultato = canale.play(proposta)
            if risultato:
                risultato = _con_server(risultato)
                if controlla and not _server_esiste(risultato[0]):
                    logger.debug('tmdb: %s ha il titolo nell\'elenco ma il server dice di no, provo il prossimo' % nome)
                    continue
                return risultato
        except Exception:
            import traceback
            logger.error('tmdb: errore su %s\n%s' % (nome, traceback.format_exc()))
    return None


_IMDB = {}


def _id_imdb(tmdb_id, tipo):
    # id IMDb (solo le cifre, senza "tt") dall'id TMDB: una richiesta, tenuta in cache da core/tmdb
    chiave = (tipo, str(tmdb_id))
    if chiave not in _IMDB:
        trovato = ''
        try:
            dati = tmdb.Tmdb.get_json('%s/%s/%s/external_ids?api_key=%s' % (tmdb.host, tipo, tmdb_id, tmdb.api)) or {}
            valore = dati.get('imdb_id') or ''
            if valore.startswith('tt') and valore[2:].isdigit():
                trovato = valore[2:]
        except Exception:
            logger.error('tmdb: id IMDb non letto per %s' % tmdb_id)
        _IMDB[chiave] = trovato
    return _IMDB[chiave]


def _da_vidxgo(item, tmdb_id, serie):
    # il link vidxgo costruito dall'id, senza cercare il titolo nei siti che lo usano. Restituisce una lista con un
    # server (non ancora controllato) oppure vuota.
    if not tmdb_id:
        return []
    try:
        if not servertools.is_server_enabled('vidxgo'):
            return []
        imdb = _id_imdb(tmdb_id, 'tv' if serie else 'movie')
        if not imdb:
            logger.info('tmdb: nessun id IMDb per %s, vidxgo saltato' % tmdb_id)
            return []
        host = VIDXGO_HOST
        try:
            modulo = __import__('servers.vidxgo', None, None, ['servers.vidxgo'])
            valore = getattr(modulo, 'HOST', '')
            if isinstance(valore, str) and valore.startswith('http'):
                host = valore
        except Exception:
            pass
        url = '%s/%s' % (host.rstrip('/'), imdb)
        if serie:
            url += '/%s/%s' % (int(item.season), int(item.episode))
        return [item.clone(action='play', server='vidxgo', url=url, serverName='Vidxgo', tmdb_diretto=True)]
    except Exception:
        import traceback
        logger.error('tmdb: vidxgo diretto non riuscito\n%s' % traceback.format_exc())
        return []


def _diretti(item):
    # i player raggiungibili da un id: prima i canali di CANALI (VixSrc, id TMDB), poi vidxgo (id IMDb).
    # Controllati insieme: appena uno e valido, all'altro restano ATTESA_SERVER_ALTRI secondi.
    tmdb_id = item.tmdb or item.infoLabels.get('tmdb_id') or item.infoLabels.get('tmdb_id_show')
    serie = bool(item.season and item.episode)
    candidati = list(_dai_canali(item, controlla=False) or [])[:1] + _da_vidxgo(item, tmdb_id, serie)
    validi = _server_validi(candidati)
    logger.info('tmdb: player diretti per id: %s' % (', '.join(v.server or '?' for v in validi) or 'nessuno'))
    return validi


def _da_anime(item, lingua):
    # modulo facoltativo: se manca, o se il titolo non e un anime, restituisce una lista vuota
    try:
        from channels import tmdb_anime
        return tmdb_anime.server(item, lingua)
    except ImportError:
        return []
    except Exception:
        import traceback
        logger.error('tmdb: ricerca anime non riuscita\n%s' % traceback.format_exc())
        return []


def _attendi(lavori, massimo, breve, utile):
    # aspetta i lavori paralleli per al massimo `massimo` secondi; quando utile(lavoro) dice che e arrivato un risultato
    # buono, agli altri restano solo `breve` secondi. Controlla ogni secondo, quindi la scadenza vale anche se nessun
    # lavoro finisce, e si ferma se Kodi sta chiudendo. Restituisce 'tutti', 'accorciata' oppure 'tempo'.
    from concurrent import futures
    try:
        import xbmc
        monitor = xbmc.Monitor()
    except Exception:
        monitor = None
    in_attesa = set(lavori)
    scadenza = time.time() + massimo
    accorciata = False
    while in_attesa:
        resto = scadenza - time.time()
        if resto <= 0 or (monitor is not None and monitor.abortRequested() is True):
            return 'accorciata' if accorciata else 'tempo'
        finiti, in_attesa = futures.wait(in_attesa, timeout=min(resto, 1), return_when=futures.FIRST_COMPLETED)
        for lavoro in finiti:
            if utile(lavoro) and not accorciata and breve < massimo:
                accorciata = True
                scadenza = min(scadenza, time.time() + breve)
    return 'tutti'


def _senza_doppi(server):
    # canali diversi danno spesso lo stesso indirizzo (stesso player): si tiene il primo e si prova una volta sola
    unici, visti = [], set()
    for voce in server:
        chiave = (voce.server, voce.url)
        if voce.url and chiave in visti:
            continue
        visti.add(chiave)
        unici.append(voce)
    if len(unici) < len(server):
        logger.info('tmdb: tolti %d server doppi (stesso indirizzo da canali diversi)' % (len(server) - len(unici)))
    return unici


def _server_validi(server):
    # un sito puo dire di avere il titolo e poi il server non averlo (o non rispondere): si controllano tutti i server
    # in parallelo con lo stesso test che S4Me fa prima di riprodurre, e si tengono solo quelli che rispondono.
    # Chi non risponde entro ATTESA_SERVER viene scartato.
    from concurrent import futures
    if not server:
        return []
    server = _senza_doppi(server)
    esecutore = futures.ThreadPoolExecutor(max_workers=len(server))
    lavori = [(voce, esecutore.submit(_server_esiste, voce)) for voce in server]

    def utile(lavoro):
        try:
            return bool(lavoro.result())
        except Exception:
            return True

    # appena un server e valido, agli altri restano ATTESA_SERVER_ALTRI secondi: poi si parte con quelli arrivati
    _attendi([l for _, l in lavori], ATTESA_SERVER, ATTESA_SERVER_ALTRI, utile)
    validi = []
    for voce, lavoro in lavori:
        if not lavoro.done():
            logger.info('tmdb: server %s non ha risposto in tempo, scartato' % voce.server)
            continue
        try:
            if lavoro.result():
                validi.append(voce)
            else:
                logger.info('tmdb: server %s non ha il video, scartato' % voce.server)
        except Exception:
            validi.append(voce)
    esecutore.shutdown(wait=False)
    return validi


def _pulisci(titolo):
    import re
    return re.sub(r'\[/?COLOR[^\]]*\]', '', titolo or '')


# UpNext: avviso e passaggio automatico all'episodio successivo

def _episodio_upnext(item, nome, stagione, episodio, dati):
    # descrizione di un episodio nel formato che UpNext si aspetta
    still = (IMG + 'original' + dati['still_path']) if dati.get('still_path') else item.thumbnail
    return {'type': 'episode', 'episodeid': -1, 'tvshowid': -1, 'showtitle': nome,
            'season': stagione, 'episode': episodio,
            'title': dati.get('name') or 'Episodio %d' % episodio, 'plot': dati.get('overview') or '',
            'firstaired': dati.get('air_date') or '', 'runtime': int(dati.get('runtime') or 0) * 60,
            'rating': round(dati.get('vote_average') or 0, 1), 'playcount': 0,
            'art': {'thumb': still, 'tvshow.fanart': item.fanart or '', 'tvshow.poster': item.thumbnail or ''}}


def _prossimo_episodio(otmdb, stagione, episodio):
    # episodio successivo gia uscito: stesso blocco di stagione, altrimenti primo della stagione dopo
    oggi = datetime.now().strftime('%Y-%m-%d')
    corrente = {}
    for e in (otmdb.get_season(stagione) or {}).get('episodes') or []:
        if e.get('episode_number') == episodio:
            corrente = e
        elif e.get('episode_number') == episodio + 1 and (e.get('air_date') or '9999') <= oggi:
            return corrente, stagione, e
    numeri = [s.get('season_number') for s in (otmdb.result or {}).get('seasons') or []]
    if stagione + 1 in numeri:
        for e in (otmdb.get_season(stagione + 1) or {}).get('episodes') or []:
            if e.get('episode_number') == 1 and (e.get('air_date') or '9999') <= oggi:
                return corrente, stagione + 1, e
    return corrente, None, None


def _sta_andando(player, nome, stagione, episodio):
    # il video in riproduzione e proprio questo episodio di questa serie? (stagione, episodio e titolo della serie)
    try:
        tag = player.getVideoInfoTag()
        if int(tag.getSeason()) != int(stagione) or int(tag.getEpisode()) != int(episodio):
            return False
        serie = (tag.getTVShowTitle() or '').lower().strip()
        atteso = _pulisci(nome or '').lower().strip()
        return not serie or not atteso or serie in atteso or atteso in serie
    except Exception:
        return True  # se Kodi non da i dati, meglio mandare il segnale come prima


def _invia_upnext(item):
    # attende che la riproduzione sia partita e manda a UpNext episodio corrente e successivo.
    # Il segnale va dopo l'avvio del video: se arrivasse prima, gli eventi del player lo cancellerebbero.
    import json
    import base64
    import xbmc
    try:
        if not xbmc.getCondVisibility('System.AddonIsEnabled(service.upnext)'):
            return
        id_serie = item.infoLabels.get('tmdb_id') or item.tmdb
        nome = item.contentSerieName or item.fulltitle
        stagione, episodio = int(item.season), int(item.episode)
        otmdb = tmdb.Tmdb(id_Tmdb=id_serie, search_type='tv')
        corrente, ns, prossimo = _prossimo_episodio(otmdb, stagione, episodio)
        if not prossimo:
            logger.info('tmdb: upnext, nessun episodio successivo')
            return
        successivo = item.clone(season=ns, episode=prossimo['episode_number'], contentSeason=ns,
                                contentEpisodeNumber=prossimo['episode_number'], action='findvideos',
                                contentType='episode', url='', no_return=False, da_upnext=True,
                                plot=prossimo.get('overview') or item.plot,
                                title=support.typo('%dx%02d: %s' % (ns, prossimo['episode_number'], prossimo.get('name') or ''), 'bold'))
        dati = {'current_video': _episodio_upnext(item, nome, stagione, episodio, corrente),
                'next_video': _episodio_upnext(item, nome, ns, prossimo['episode_number'], prossimo),
                'play_url': 'plugin://plugin.video.s4me/?' + successivo.tourl()}
        # attesa: video in riproduzione e gia avviato (massimo 3 minuti)
        monitor = xbmc.Monitor()
        player = xbmc.Player()
        # ogni richiesta ha un suo contrassegno: se ne parte un'altra, questa attesa finisce (altrimenti il segnale di una
        # serie arriverebbe mentre si guarda un'altra serie)
        import xbmcgui
        finestra = xbmcgui.Window(10000)
        contrassegno = '%s-%s-%s' % (id_serie, stagione, episodio) + str(time.time())
        finestra.setProperty('tmdb_upnext', contrassegno)
        limite = time.time() + 180
        while not monitor.abortRequested() and time.time() < limite:
            if finestra.getProperty('tmdb_upnext') != contrassegno:
                logger.info('tmdb: upnext, partita un\'altra richiesta, segnale non inviato')
                return
            try:
                if player.isPlayingVideo() and player.getTime() > 3 and _sta_andando(player, nome, stagione, episodio):
                    break
            except Exception:
                pass
            monitor.waitForAbort(1)
        else:
            logger.info('tmdb: upnext, riproduzione non partita, segnale non inviato')
            return
        monitor.waitForAbort(3)
        if finestra.getProperty('tmdb_upnext') != contrassegno or not _sta_andando(player, nome, stagione, episodio):
            logger.info('tmdb: upnext, il video in riproduzione non e piu questo, segnale non inviato')
            return
        monitor.waitForAbort(3)
        codificato = base64.b64encode(json.dumps(dati).encode('utf-8')).decode('ascii')
        xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'JSONRPC.NotifyAll',
                                        'params': {'sender': 'plugin.video.s4me.SIGNAL', 'message': 'upnext_data',
                                                   'data': [codificato]}}))
        logger.info('tmdb: upnext, inviato il segnale per %dx%02d' % (ns, prossimo['episode_number']))
    except Exception:
        import traceback
        logger.error('tmdb: upnext non riuscito\n%s' % traceback.format_exc())


def _avvia_upnext(item):
    import threading
    if item.season and item.episode:
        threading.Thread(target=_invia_upnext, args=[item.clone()]).start()


def _prossimamente(item):
    # titolo non ancora uscito: inutile cercarlo, si avvisa e basta
    data = item.data_uscita
    if not data or data <= datetime.now().strftime('%Y-%m-%d'):
        return False
    try:
        uscita = datetime.strptime(data, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        uscita = data
    nome = item.contentSerieName or item.contentTitle or item.fulltitle
    platformtools.dialog_ok('Prossimamente', '%s\nUscita prevista: %s' % (nome, uscita))
    return True


def _azione_click(canale):
    # con "Riproduci subito" il click apre findvideos. Con le altre due scelte si usa 'avvia': se il canale non
    # restituisce una lista, S4Me non mostra la notifica "Nessun elemento da visualizzare" che findvideos
    # senza server farebbe comparire appena parte la ricerca
    try:
        return 'findvideos' if not int(config.get_setting('al_click', channel=canale) or 0) else 'avvia'
    except (TypeError, ValueError):
        return 'findvideos'


def avvia(item):
    if _al_click(item):
        return None
    import xbmc
    # si vuole riprodurre: stessa richiesta con findvideos, senza chiedere di nuovo cosa fare
    xbmc.executebuiltin('RunPlugin(%s?%s)' % (sys.argv[0], item.clone(action='findvideos', salta_scelta=True).tourl()))
    return None


def _al_click(item):
    # impostazione del canale "Al click sul contenuto": 0 riproduci subito, 1 scelta utente, 2 ricerca negli altri canali.
    # Restituisce True se il click e stato gestito qui (ricerca avviata o scelta annullata), False per riprodurre.
    try:
        scelta = int(config.get_setting('al_click', channel=item.channel) or 0)
    except (TypeError, ValueError):
        scelta = 0
    if scelta == 1:
        voce = platformtools.dialog_select('Cosa vuoi fare?', ['Riproduci subito', 'Cerca negli altri canali'])
        if voce < 0:
            return True
        scelta = 2 if voce == 1 else 0
    if scelta != 2:
        return False
    import xbmc
    nome = item.contentSerieName or item.contentTitle or item.fulltitle
    tipo = 'movie' if item.contentType == 'movie' else 'tvshow'
    anno = item.infoLabels.get('year') or ''
    # si apre direttamente la ricerca, senza la finestra "Canali inclusi nella ricerca" che S4Me mostra
    # con l'azione from_context del menu contestuale
    if config.get_setting('new_search'):
        ricerca = Item(channel='globalsearch', action='Search', text=nome, infoLabels=item.infoLabels, mode='search',
                       type=tipo, contentType=tipo, release_date=anno, folder=False)
        comando = 'RunPlugin'
    else:
        ricerca = Item(channel='search', action='channel_search', text=nome, infoLabels=item.infoLabels, mode=tipo,
                       contentType=tipo, release_date=anno)
        comando = 'Container.Update'
    xbmc.executebuiltin('%s(%s?%s)' % (comando, sys.argv[0], ricerca.tourl()))
    return True


def _ricorda_server(elenco):
    # con un solo server S4Me lo avvia subito e svuota l'elenco dei server: allo stop la finestra dei server
    # resterebbe vuota. Dopo che S4Me ha svuotato l'elenco, e prima che parta il video, lo si rimette.
    import threading

    def rimetti():
        time.sleep(0.5)
        try:
            from core import db
            if not db['player'].get('itemlist'):
                db['player']['itemlist'] = elenco
            db.close()
        except Exception:
            logger.error('tmdb: elenco dei server non ripristinato')

    threading.Thread(target=rimetti).start()


def findvideos(item):
    inizio = time.time()
    if item.da_upnext:
        # richiesta arrivata dalla playlist di UpNext: Kodi si aspetta che il plugin risolva l'indirizzo,
        # altrimenti a fine avvio mostra 'riproduzione fallita'. Si risolve con il video finto (come fa la libreria)
        try:
            platformtools.fakeVideo()
        except Exception:
            logger.error('tmdb: fakeVideo non riuscito')
    if _prossimamente(item):
        return []
    if not item.da_upnext and not item.salta_scelta and _al_click(item):
        return []
    _avvia_upnext(item)
    server = _diretti(item)
    if not server:
        # anime che i player diretti non hanno: scheda trovata per id (modulo tmdb_anime), poi stesso controllo dei server.
        # Prima la versione doppiata in italiano; la sottotitolata solo se quella manca o il suo server non e valido
        server = _server_validi(_da_anime(item, 'ITA')) or _server_validi(_da_anime(item, 'Sub-ITA'))
    for voce in server:
        # nella finestra dei server S4Me mostra serverName e ch_name
        voce.serverName = voce.serverName or (voce.server or '').capitalize()
        voce.ch_name = voce.ch_name or 'TMDb'
    logger.info('tmdb: findvideos terminato in %.1f secondi, %d server' % (time.time() - inizio, len(server)))
    if not server:
        platformtools.dialog_notification('TMDb', 'Non disponibile: prova "Cerca negli altri canali" dal menu contestuale')
    elif len(server) == 1 and not config.get_setting('autoplay') and not item.da_upnext:
        # autoplay spento e un solo server: S4Me lo avvia senza mostrare la finestra, quindi si dice da dove parte
        voce = server[0]
        testo = voce.serverName
        if voce.ch_name and voce.ch_name != 'TMDb':
            testo += ' (%s)' % voce.ch_name
        if voce.extraInfo:
            testo += ' [%s]' % voce.extraInfo
        platformtools.dialog_notification('TMDb', 'Server: %s' % testo, sound=False)
    if not server or item.da_upnext:
        return server
    # come gli altri canali, nell'elenco c'e anche la voce "Aggiungi alla videoteca" (solo per i film)
    completo = support.videolibrary(list(server), item, function='findvideos')
    if len(server) == 1:
        _ricorda_server(completo)
    # un server: S4Me lo avvia subito. Piu server: autoplay di S4Me, oppure la finestra dei server se e spento
    return completo


def play(item):
    # avvio diretto da un player esterno (TMDb Helper): solo i canali di CANALI
    logger.debug()
    if item.tmdb_diretto and item.server and (item.url or '').startswith('http'):
        return [item]  # server costruito da questo canale (vidxgo per id): l'indirizzo e gia pronto
    risultato = _dai_canali(item)
    if risultato:
        return risultato
    platformtools.dialog_notification('TMDb', 'Nessun canale ha questo titolo')
    return []
