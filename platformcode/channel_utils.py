# -*- coding: utf-8 -*-
"""
Utility per gestire i canali S4ME e il sistema di fallback.
"""
from platformcode import config, logger

# Mappa Nomi Settings -> Channel IDs possibili
# Se ci sono più ID per lo stesso nome (cloni), li proviamo tutti o cerchiamo quello attivo
CHANNEL_MAP = {
    'StreamingCommunity': ['streamingcommunity'],
    'AltaDefinizione': ['altadefinizionecommunity', 'altadefinizioneclick', 'altadefinizione01', 'altadefinizione'],
    'CineBlog01': ['cineblog01'],
    'TantiFilm': ['tantifilm'],
    'Filmpertutti': ['filmpertutti'],
    'CasaCinema': ['casacinema'],
    'CinemaLibero': ['cinemalibero'],
    'IlGenioDelloStreaming': ['ilgeniodellostreaming', 'ilgeniodellostreaming_cam'],
    'GuardaSerie': ['guardaserieclick', 'guardaserieicu', 'guardaseriecam'],
    'EuroStreaming': ['eurostreaming'],
    'ItaliaSerie': ['italiaserie'],
    'SerieTVU': ['serietvu']
}


def get_channel_id(label):
    """
    Risolve il nome visualizzato nelle impostazioni nel channel_id reale.
    Ritorna il primo ID che risulta attivo.
    """
    if label == 'Nessuno' or not label:
        return None
        
    possible_ids = CHANNEL_MAP.get(label, [label.lower()])
    
    # Prova a trovare quello attivo
    from core import channeltools
    
    for ch_id in possible_ids:
        try:
            # Verifica se attivo tramite channeltools o active flag nel json
            # Per semplicità assumiamo che se importChannel funziona, è valido.
            # Ma meglio controllare attivo/non attivo
            if is_channel_active(ch_id):
                return ch_id
        except:
            continue
            
    # Se nessuno è attivo, ritorna il primo (magari si attiverà dopo)
    return possible_ids[0]


def is_channel_active(channel_id):
    """Controlla se un canale è marcato come attivo nel suo JSON."""
    import os
    import json
    
    json_path = os.path.join(config.get_runtime_path(), 'channels', channel_id + '.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            return data.get('active', False)
        except:
            pass
    return False


def get_fallback_order(content_type):
    """
    Restituisce la lista ordinata degli ID dei canali da usare.
    Legge direttamente dalle impostazioni di Kodi.
    
    Args:
        content_type: 'movie' o 'tvshow'
    """
    channels = []
    
    if content_type == 'movie':
        keys = ['movie_channel_1', 'movie_channel_2', 'movie_channel_3']
    else:
        keys = ['tv_channel_1', 'tv_channel_2', 'tv_channel_3']
        
    for key in keys:
        label = config.get_setting(key)
        if label and label != 'Nessuno':
            ch_id = get_channel_id(label)
            if ch_id and ch_id not in channels:
                channels.append(ch_id)
                
    return channels


def get_channel_name(channel_id):
    """Restituisce il nome visualizzato (per i log/dialog)."""
    # Cerca nel map inverso
    for name, ids in CHANNEL_MAP.items():
        if channel_id in ids:
            return name
    return channel_id
