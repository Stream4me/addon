# Stream4Me and Trakt

## Notice

Stream4Me (S4Me) is a free, open source add-on for Kodi. It uses the Trakt API to show which movies and episodes you have already watched. **Trakt for S4Me uses Trakt but is not endorsed or certified by Trakt.** Trakt and the Trakt logo are trademarks of Trakt.

## What the Trakt integration does

* Signs you in to your own Trakt account with the Trakt device code flow. You enter a code on trakt.tv and authorize the app there. S4Me never sees your Trakt password.
* Reads your watched movies and shows, so the add-on can display a check mark on titles you have already seen.
* Checks the date of your last activity on Trakt, so the check marks stay up to date after you finish a video. Data is downloaded again only when something has changed.
* Does not scrobble. Reporting what you play to Trakt is done by the separate Kodi add-on script.trakt, which has its own Trakt app and its own settings.
* Never modifies, deletes or publishes anything on your Trakt account. It only reads.
* Lets you sign in and sign out at any time from the add-on settings (Videolibrary, Trakt section).

## Privacy policy

* S4Me has no server for Trakt data. The add-on talks directly from your device to api.trakt.tv and auth.trakt.tv, and to no other service for this feature.
* The access token, the refresh token and a copy of your watched list are stored only on your device, in the add-on data folder of Kodi (settings_channels/trakt_data.json).
* Your Trakt data is not sent to the developers of S4Me and is not shared with third parties.
* Signing out from the add-on settings removes the tokens and the stored watched list from your device. You can also delete the file above by hand.
* You can revoke the access of the app at any time from your Trakt account, in Settings, Connected Apps.
* The Trakt integration is optional and is off by default. If you do not enable it, no request is made to Trakt.
* Use of Trakt itself is covered by the Trakt terms of use and privacy policy, available on trakt.tv.

## Source code

The whole integration is open source and can be read in the repository, in the file `core/trakt_tools.py`.

---

# Stream4Me e Trakt

## Avviso

Stream4Me (S4Me) è un addon gratuito e open source per Kodi. Usa le API di Trakt per mostrare quali film ed episodi hai già visto. **Questa applicazione usa Trakt ma non è approvata né certificata da Trakt.** Trakt e il logo Trakt sono marchi di Trakt.

## Cosa fa l'integrazione con Trakt

* Accede al tuo account Trakt con il codice da inserire sul sito: scrivi il codice su trakt.tv e autorizzi l'app da lì. S4Me non vede mai la tua password di Trakt.
* Legge i film e le serie che hai visto, per mostrare la spunta sui titoli già guardati.
* Controlla la data dell'ultima attività sul tuo account, così le spunte restano aggiornate quando finisci un video. I dati vengono scaricati di nuovo solo se qualcosa è cambiato.
* Non invia lo scrobble. Il report di ciò che guardi a Trakt lo fa l'addon separato script.trakt, che ha una sua app Trakt e le sue impostazioni.
* Non modifica, non cancella e non pubblica nulla sul tuo account Trakt. Legge soltanto.
* Puoi accedere e uscire in qualsiasi momento dalle impostazioni dell'addon (Videoteca, sezione Trakt).

## Informativa sulla privacy

* S4Me non ha un server per i dati di Trakt. L'addon comunica direttamente dal tuo dispositivo con api.trakt.tv e auth.trakt.tv, e con nessun altro servizio per questa funzione.
* Il token di accesso, il token di rinnovo e una copia dell'elenco dei visti sono salvati solo sul tuo dispositivo, nella cartella dati dell'addon in Kodi (settings_channels/trakt_data.json).
* I tuoi dati di Trakt non vengono inviati agli sviluppatori di S4Me e non vengono condivisi con terzi.
* Uscendo dalle impostazioni dell'addon si cancellano dal dispositivo i token e l'elenco dei visti salvato. Puoi anche eliminare a mano il file indicato sopra.
* Puoi revocare l'accesso dell'app in qualsiasi momento dal tuo account Trakt, in Impostazioni, App collegate.
* L'integrazione con Trakt è facoltativa ed è disattivata di default. Se non la attivi, non viene fatta nessuna richiesta a Trakt.
* L'uso di Trakt è regolato dai termini di utilizzo e dall'informativa sulla privacy di Trakt, disponibili su trakt.tv.

## Codice sorgente

L'intera integrazione è open source e si può leggere nel repository, nel file `core/trakt_tools.py`.
