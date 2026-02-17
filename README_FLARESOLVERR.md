# S4Me - Integrazione FlareSolverr

## Cosa è FlareSolverr?

FlareSolverr è un proxy che permette di bypassare le protezioni Cloudflare. Quando un sito protetto da Cloudflare blocca l'accesso, FlareSolverr risolve automaticamente la challenge e permette all'addon di accedere al contenuto.

## Installazione FlareSolverr

### Windows

1. Scarica FlareSolverr da: https://github.com/FlareSolverr/FlareSolverr/releases
2. Estrai lo ZIP sul desktop (o in una cartella a tua scelta)
3. Esegui `flaresolverr.exe`
4. Lascia la finestra CMD aperta (FlareSolverr deve rimanere in esecuzione)

### Linux/Mac

```bash
# Con Docker (consigliato)
docker run -d \
  --name=flaresolverr \
  -p 8191:8191 \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest

# Oppure con Python
git clone https://github.com/FlareSolverr/FlareSolverr.git
cd FlareSolverr
pip install -r requirements.txt
python src/flaresolverr.py
```

## Configurazione in S4Me

1. Apri Kodi
2. Vai in: **Impostazioni S4Me** → **Servers**
3. Cerca la sezione **"FlareSolverr (Bypass Cloudflare)"**
4. Abilita: **"Abilita FlareSolverr"** = ON
5. Imposta: **"FlareSolverr URL"** = `http://localhost:8191/v1`
   - Se FlareSolverr è su un altro PC, sostituisci `localhost` con l'IP del PC
   - Esempio: `http://192.168.1.100:8191/v1`

## Come Funziona

Quando S4Me rileva un blocco Cloudflare (errore 403, 429 o 503):

1. **Se FlareSolverr è abilitato**: 
   - Appare una notifica "Tentativo bypass Cloudflare in corso..."
   - FlareSolverr risolve la challenge
   - Se ha successo, appare "Cloudflare bypassato con successo!"
   - Il contenuto viene caricato normalmente

2. **Se FlareSolverr è disabilitato o fallisce**:
   - S4Me prova con i proxy tradizionali (meno efficaci)

## Risoluzione Problemi

### "FlareSolverr: Error creating session"
- Verifica che FlareSolverr sia in esecuzione
- Controlla l'URL nelle impostazioni
- Se usi un altro PC, verifica che la porta 8191 sia aperta

### "FlareSolverr: POST request error"
- Verifica la connessione di rete
- Prova a riavviare FlareSolverr
- Controlla che non ci siano firewall che bloccano la porta 8191

### FlareSolverr funziona ma il sito non si carica
- Alcuni siti hanno protezioni aggiuntive
- Prova a ricaricare la pagina
- Verifica che il sito sia effettivamente raggiungibile dal browser

## Note Importanti

- FlareSolverr è **legale** e serve solo a bypassare le protezioni anti-bot
- Mantieni FlareSolverr **sempre in esecuzione** quando usi S4Me
- Su Windows, **non chiudere** la finestra CMD di FlareSolverr
- Su Docker/Linux, FlareSolverr si riavvia automaticamente

## Canali che Beneficiano di FlareSolverr

Questi canali sono spesso protetti da Cloudflare:
- altadefinizione01
- ilgeniodellostreaming
- streamingcommunity
- cineblog01
- 1337x
- Altri siti con protezione Cloudflare

## Crediti

- **FlareSolverr**: https://github.com/FlareSolverr/FlareSolverr
- **Ispirazione**: Addon Cumination
- **Integrazione**: S4Me Team

## Supporto

Per problemi o domande:
- GitHub: https://github.com/stream4me/addon
- Telegram: Gruppo S4Me

---

**Versione**: 1.7.9  
**Data**: Gennaio 2026
