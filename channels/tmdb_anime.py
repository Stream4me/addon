# -*- coding: utf-8 -*-
# Anime per il canale TMDb: trova l'episodio (o il film) nei siti anime partendo dall'id TMDB, senza confrontare i titoli.
#
# Come funziona:
#  1. una tabella (https://github.com/aandroide/Anime-ids, aggiornata ogni giorno) dice a quali schede AniList e
#     MyAnimeList corrisponde una stagione TMDB, e da quale episodio parte ogni scheda (scarto);
#  2. si cerca il titolo su AnimeUnity e tra i risultati si prende la scheda con lo stesso id AniList o MyAnimeList
#     (se esistono, sia quella doppiata in italiano sia quella sottotitolata);
#  3. dall'elenco episodi della scheda si prende l'episodio giusto e si chiedono i server al canale animeunity.
# Il canale chiede prima la versione doppiata in italiano; solo se non c'e (o non ha l'episodio) chiede la sottotitolata.
#
# Il canale TMDb chiama server(item) solo se i player diretti (VixSrc, vidxgo) non hanno il titolo.

import json
import re
import time
from urllib.parse import urlencode

from core import filetools, httptools, tmdb
from platformcode import config, logger, platformtools

TABELLA_URL = 'https://raw.githubusercontent.com/aandroide/Anime-ids/master/anime_ids.json'
TABELLA_FILE = 'tmdb_anime_ids.json'
TABELLA_DURATA = 3 * 24 * 3600    # secondi prima di riscaricare la tabella
RICERCHE_MAX = 3                  # titoli diversi da provare nella ricerca del sito
TIPI_SERIE = ('TV', 'ONA')               # schede che contengono gli episodi normali di una serie
TIPI_FUORI_STAGIONE = ('OVA', 'MOVIE')   # schede che la tabella lega a una stagione ma non sono episodi della serie

_MEMORIA = {}


# Tabella

def _percorso():
    return filetools.join(config.get_data_path(), TABELLA_FILE)


def _tabella():
    # la tabella in memoria; dal file se e recente, altrimenti riscaricata. Se lo scaricamento non riesce si usa
    # quella vecchia: meglio una tabella di qualche giorno fa che nessuna.
    if 'tabella' in _MEMORIA:
        return _MEMORIA['tabella']
    vecchia = {}
    try:
        if filetools.isfile(_percorso()):
            vecchia = json.loads(filetools.read(_percorso()) or '{}')
    except Exception:
        vecchia = {}
    valida = isinstance(vecchia, dict) and isinstance(vecchia.get('tv'), dict)
    if valida and time.time() - (vecchia.get('scaricata') or 0) < TABELLA_DURATA:
        _MEMORIA['tabella'] = vecchia
        return vecchia
    try:
        nuova = json.loads(httptools.downloadpage(TABELLA_URL).data)
        if isinstance(nuova.get('tv'), dict) and len(nuova['tv']) > 1000:
            nuova['scaricata'] = time.time()
            filetools.write(_percorso(), json.dumps(nuova, separators=(',', ':')))
            _MEMORIA['tabella'] = nuova
            logger.info('tmdb anime: tabella scaricata, %d serie' % len(nuova['tv']))
            return nuova
    except Exception:
        logger.error('tmdb anime: tabella non scaricata')
    _MEMORIA['tabella'] = vecchia if valida else {}
    return _MEMORIA['tabella']


def scheda(tmdb_id, stagione=None, episodio=None):
    # dall'id TMDB alla scheda del sito: restituisce (id AniList, id MyAnimeList, episodio nella scheda) oppure None.
    # Per i film episodio e None.
    tabella = _tabella()
    if not tabella or not tmdb_id:
        return None
    if not (stagione and episodio):
        voci = (tabella.get('film') or {}).get(str(tmdb_id)) or []
        return (voci[0][0], voci[0][1], None) if voci else None
    voci = [v for v in (tabella.get('tv') or {}).get(str(tmdb_id)) or []
            if v[0] == stagione and v[4] not in TIPI_FUORI_STAGIONE]
    # una stagione TMDB puo essere divisa in piu schede: vale quella con lo scarto piu alto sotto l'episodio cercato
    adatte = [v for v in voci if (v[3] or 0) < episodio]
    if adatte:
        scelta = max(adatte, key=lambda v: v[3] or 0)
        return scelta[1], scelta[2], episodio - (scelta[3] or 0)
    # serie lunghe (Detective Conan, One Piece, Naruto...): TMDB le divide in stagioni, AniList e i siti hanno una scheda
    # sola con gli episodi numerati di fila. Nella tabella quella scheda non ha stagione: si usa il numero assoluto.
    intere = [v for v in (tabella.get('tv') or {}).get(str(tmdb_id)) or [] if v[0] is None and v[4] in TIPI_SERIE]
    if len(intere) == 1:
        assoluto = _numero_assoluto(tmdb_id, stagione, episodio)
        if assoluto:
            return intere[0][1], intere[0][2], assoluto
    return None


def _numero_assoluto(tmdb_id, stagione, episodio):
    # numero dell'episodio contando di fila le stagioni TMDB precedenti (senza la stagione 0 degli speciali).
    # La posizione nella stagione si legge dall'elenco degli episodi: cosi funziona sia se TMDB riparte da 1 a ogni
    # stagione, sia se continua la numerazione. Due richieste a TMDB, tenute in cache da core/tmdb.
    try:
        base = '%s/tv/%s' % (tmdb.host, tmdb_id)
        serie = tmdb.Tmdb.get_json('%s?api_key=%s' % (base, tmdb.api)) or {}
        precedenti = sum(s.get('episode_count') or 0 for s in serie.get('seasons') or []
                         if 0 < (s.get('season_number') or 0) < stagione)
        dati = tmdb.Tmdb.get_json('%s/season/%s?api_key=%s' % (base, stagione, tmdb.api)) or {}
        numeri = [e.get('episode_number') for e in dati.get('episodes') or []]
        posizione = numeri.index(episodio) + 1 if episodio in numeri else episodio
        for e in dati.get('episodes') or []:
            if e.get('episode_number') == episodio:
                logger.info('tmdb anime: TMDB %dx%d si intitola "%s", andato in onda il %s' % (
                    stagione, episodio, e.get('name'), e.get('air_date')))
        logger.info('tmdb anime: scheda unica, %dx%02d e l\'episodio %d contando di fila' % (stagione, episodio, precedenti + posizione))
        return precedenti + posizione
    except Exception:
        logger.error('tmdb anime: numero assoluto non calcolato')
        return None


def e_anime(tmdb_id, serie=True):
    tabella = _tabella()
    return str(tmdb_id) in ((tabella.get('tv') if serie else tabella.get('film')) or {})


# AnimeUnity

def _titoli(item, tipo, tmdb_id):
    # titoli con cui cercare nel sito: quello mostrato, poi quello inglese di TMDB, poi senza sottotitolo
    nomi = [item.contentSerieName or item.contentTitle or item.fulltitle or '']
    try:
        dati = tmdb.Tmdb.get_json('%s/%s/%s?api_key=%s&language=en-US' % (tmdb.host, tipo, tmdb_id, tmdb.api)) or {}
        nomi += [dati.get('name') or dati.get('title') or '', dati.get('original_name') or dati.get('original_title') or '']
    except Exception:
        logger.error('tmdb anime: titolo inglese non letto')
    nomi += [n.split(':')[0] for n in list(nomi) if ':' in n]
    puliti = []
    for n in nomi:
        n = (n or '').strip()
        latino = all(ord(c) < 0x250 or not c.isalpha() for c in n)
        if n and latino and n.lower() not in [p.lower() for p in puliti]:
            puliti.append(n)
    return puliti[:RICERCHE_MAX]


def _versioni(record):
    # AnimeUnity (sito nuovo): una scheda sola con le lingue disponibili in 'variants'
    codici = [v.get('language') for v in record.get('variants') or [] if v.get('language')]
    versioni = []
    if 'ita' in codici:
        versioni.append('ITA')
    if any(c != 'ita' for c in codici) or not codici:
        versioni.append('Sub-ITA')
    return versioni


def _cerca(canale, testo):
    url = '%s/api/archive?%s' % (canale.host, urlencode([('query', testo)]))
    risposta = httptools.downloadpage(url, headers=canale.headers)
    return json.loads(risposta.data).get('data') or []


def _schede_sito(canale, titoli, anilist, mal):
    # le schede di AnimeUnity con lo stesso id (di solito una sottotitolata e, se esiste, una doppiata)
    for testo in titoli:
        try:
            trovate = [r for r in _cerca(canale, testo)
                       if (anilist and r.get('anilist_id') == anilist) or (mal and r.get('mal_id') == mal)]
        except Exception:
            logger.error('tmdb anime: ricerca "%s" non riuscita' % testo)
            continue
        logger.info('tmdb anime: ricerca "%s", %d schede con lo stesso id' % (testo, len(trovate)))
        if trovate:
            return trovate
    return []


def _api(canale, percorso, parametri=None):
    url = canale.host + percorso + (('?' + urlencode(parametri)) if parametri else '')
    try:
        return json.loads(httptools.downloadpage(url, headers=canale.headers).data) or {}
    except Exception:
        logger.error('tmdb anime: richiesta %s non riuscita' % url)
        return {}


def _tutti_episodi(canale, anime_id):
    # l'API da 120 puntate per volta; il nome del parametro di partenza si riconosce da solo
    percorso = '/api/anime/%s/episodes' % anime_id
    prima = _api(canale, percorso)
    episodi = list(prima.get('episodes') or [])
    totale = prima.get('total') or len(episodi)
    if totale <= len(episodi) or not episodi:
        return episodi
    primo_id = episodi[0].get('id')
    nome_ok = None
    while len(episodi) < totale:
        altri = []
        for nome in ([nome_ok] if nome_ok else ['start', 'start_range', 'offset', 'from']):
            altri = _api(canale, percorso, [(nome, len(episodi) + 1)]).get('episodes') or []
            if altri and altri[0].get('id') != primo_id:
                nome_ok = nome
                break
            altri = []
        if not altri:
            break
        episodi += altri
    return episodi


def _video(episodio, versione):
    # il video della puntata nella versione voluta: 'ITA' oppure 'Sub-ITA' (qualsiasi lingua diversa da ita)
    for v in episodio.get('videos') or []:
        if v.get('scws_id') and not v.get('is_hidden') and (v.get('language') == 'ita') == (versione == 'ITA'):
            return v
    return None


def _id_episodio(canale, record, numero):
    # episodio del sito (con i video ita/jpn): l'API da 120 puntate per volta, quindi per i numeri bassi
    # basta la prima richiesta, per gli altri si scaricano tutte.
    # Nel log restano numero e video dell'episodio scelto, per controllare l'abbinamento.
    if numero <= 120:
        elenco = _api(canale, '/api/anime/%s/episodes' % record['id']).get('episodes') or []
    else:
        elenco = _tutti_episodi(canale, record['id'])
    for e in elenco:
        if str(e.get('number')) == str(numero):
            logger.info('tmdb anime: animeunity scheda %s, episodio %s id %s video %s' % (
                record.get('slug'), e.get('number'), e.get('id'),
                ', '.join('%s=%s' % (v.get('language'), v.get('id')) for v in e.get('videos') or [])))
            return e
    return None


def _canale(nome):
    try:
        canale = platformtools.channelImport(nome)
    except Exception:
        canale = None
    if not canale or not hasattr(canale, 'findvideos'):
        logger.info('tmdb anime: canale %s non disponibile' % nome)
        return None
    return canale


def _marca(elenco, lingua, nome):
    # solo i server veri, con lingua e nome del sito da mostrare nella finestra dei server di S4Me
    buoni = []
    for s in elenco or []:
        if not s.server:
            continue
        s.extraInfo = lingua
        s.ch_name = s.ch_name or nome
        s.serverName = s.serverName or re.sub(r'\[[^\]]*\]', '', s.title or '').strip() or nome
        buoni.append(s)
    return buoni


def _da_animeunity(item, anilist, mal, numero, titoli, serie, lingua=None):
    # lingua: 'ITA' solo la versione doppiata, 'Sub-ITA' solo quella sottotitolata, None tutte e due
    canale = _canale('animeunity')
    if not canale:
        return []
    chiave = ('schede', anilist, mal)
    if chiave not in _MEMORIA:  # la ricerca nel sito si fa una volta sola, anche se poi si chiede l'altra lingua
        _MEMORIA[chiave] = _schede_sito(canale, titoli, anilist, mal)
    risultato = []
    for record in _MEMORIA[chiave]:
        try:
            base = '%s/anime/%s-%s' % (canale.host, record.get('id'), record.get('slug'))
            episodio_sito = _id_episodio(canale, record, numero) if serie else None
            if serie and not episodio_sito:
                logger.info('tmdb anime: animeunity, la scheda %s non ha l\'episodio %d' % (record.get('slug'), numero))
                continue
            for versione in _versioni(record):
                if lingua and versione != lingua:
                    continue
                # la puntata (o la prima, per i film) nella versione voluta
                scelto = episodio_sito or (_tutti_episodi(canale, record['id']) or [{}])[0]
                video = _video(scelto, versione)
                if not video:
                    logger.info('tmdb anime: animeunity, %s senza la versione %s' % (
                        ('episodio %d' % numero) if serie else 'film', versione))
                    continue
                url = '%s/%s' % (base, video.get('id'))
                voce = item.clone(channel='animeunity', action='findvideos', url=url, global_search=True,
                                  contentLanguage=versione, scws_id=video.get('scws_id'))
                nome_sito = 'AnimeUnity' + (' ep. %s' % episodio_sito.get('number') if serie else '')
                risultato += _marca(canale.findvideos(voce), versione, nome_sito)
        except Exception:
            import traceback
            logger.error('tmdb anime: animeunity, scheda %s non letta\n%s' % (record.get('slug'), traceback.format_exc()))
    return risultato


def server(item, lingua=None):
    # i server di AnimeUnity per l'episodio o il film dell'item TMDb; lista vuota se non e un anime o non si trova.
    # lingua: 'ITA' o 'Sub-ITA' per avere solo quella versione (il canale chiede prima ITA, poi Sub-ITA)
    inizio = time.time()
    tmdb_id = item.tmdb or item.infoLabels.get('tmdb_id') or item.infoLabels.get('tmdb_id_show')
    serie = bool(item.season and item.episode)
    stagione = int(item.season) if serie else None
    episodio = int(item.episode) if serie else None
    trovata = scheda(tmdb_id, stagione, episodio)
    if not trovata:
        if e_anime(tmdb_id, serie):
            logger.info('tmdb anime: id TMDB %s e nella tabella ma senza una scheda per %s' % (
                tmdb_id, ('%sx%s' % (stagione, episodio)) if serie else 'il film'))
        return []
    anilist, mal, numero = trovata
    logger.info('tmdb anime: id TMDB %s%s corrisponde a AniList %s, MyAnimeList %s%s' % (
        tmdb_id, (' %dx%02d' % (stagione, episodio)) if serie else '', anilist, mal,
        (', episodio %d della scheda' % numero) if serie else ''))
    titoli = _titoli(item, 'tv' if serie else 'movie', tmdb_id)
    # prima il doppiato in italiano, poi il sottotitolato
    risultato = sorted(_da_animeunity(item, anilist, mal, numero, titoli, serie, lingua),
                       key=lambda s: 0 if s.extraInfo == 'ITA' else 1)
    logger.info('tmdb anime: %s%d server (%s) in %.1f secondi' % (
        ('richiesto %s, ' % lingua) if lingua else '', len(risultato),
        ', '.join(s.extraInfo for s in risultato) or 'nessuno', time.time() - inizio))
    return risultato
