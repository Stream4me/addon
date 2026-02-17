# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
# FlareSolverr Integration for S4Me
# Based on Cumination implementation
# --------------------------------------------------------------------------------

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2

from platformcode import logger

class FlareSolverrManager:
    """
    Gestisce le richieste attraverso FlareSolverr per bypassare le protezioni Cloudflare
    """
    
    def __init__(self, flaresolverr_url=None, session_id=None):
        """
        Inizializza il manager FlareSolverr
        @param flaresolverr_url: URL del server FlareSolverr (default: http://localhost:8191/v1)
        @param session_id: Session ID esistente da riutilizzare (opzionale)
        """
        import json
        self.json = json
        self.flaresolverr_url = flaresolverr_url or "http://localhost:8191/v1"
        logger.info("FlareSolverr URL: %s" % self.flaresolverr_url)
        
        # RIUTILIZZO: Se session_id fornito, usa quello invece di crearne uno nuovo
        if session_id:
            logger.info("FlareSolverr: Reusing existing session: %s" % session_id)
            self.flaresolverr_session = session_id
        else:
            # Crea nuova sessione solo se non fornita
            logger.info("FlareSolverr: Creating new session")
            session_create_request = {"cmd": "sessions.create"}
            try:
                session_create_response = self._post_request(session_create_request)
                if session_create_response:
                    response_data = self.json.loads(session_create_response)
                    self.flaresolverr_session = response_data.get("session")
                    logger.info("FlareSolverr session created: %s" % self.flaresolverr_session)
                else:
                    logger.error("FlareSolverr: Failed to create session")
                    self.flaresolverr_session = None
            except Exception as e:
                logger.error("FlareSolverr: Error creating session: %s" % str(e))
                self.flaresolverr_session = None
    
    def __del__(self):
        """
        Distrugge la sessione quando l'oggetto viene eliminato
        NOTA: Disabilitato per permettere riutilizzo sessioni.
        FlareSolverr pulisce automaticamente le sessioni vecchie.
        """
        # Sessione non viene distrutta automaticamente per permettere riutilizzo
        # FlareSolverr gestisce automaticamente la pulizia delle sessioni inattive
        pass
    
    def clear_flaresolverr_sessions(self):
        """
        Elimina tutte le sessioni FlareSolverr esistenti
        """
        try:
            session_list_request = {"cmd": "sessions.list"}
            session_list_response = self._post_request(session_list_request)
            
            if session_list_response:
                response_data = self.json.loads(session_list_response)
                sessions = response_data.get("sessions", [])
                
                # Elimina ogni sessione
                if sessions:
                    for session_id in sessions:
                        session_destroy_request = {
                            "cmd": "sessions.destroy",
                            "session": session_id
                        }
                        self._post_request(session_destroy_request)
                    logger.info("FlareSolverr: Cleared %d sessions" % len(sessions))
        except Exception as e:
            logger.error("FlareSolverr: Error clearing sessions: %s" % str(e))
    
    def request(self, url, method="GET", cookies=None, tries=3):
        """
        Effettua una richiesta attraverso FlareSolverr
        @param url: URL da richiedere
        @param method: Metodo HTTP (GET o POST)
        @param cookies: Cookie opzionali da inviare
        @param tries: Numero di tentativi in caso di errore
        @return: Risposta della richiesta
        """
        if not self.flaresolverr_session:
            logger.error("FlareSolverr: No valid session")
            return None
        
        # Timeout fisso 60 secondi (60000 millisecondi)
        # Può essere esteso in futuro passandolo come parametro al metodo request()
        timeout_ms = 60000
        
        flaresolverr_request = {
            "cmd": "request.%s" % method.lower(),
            "url": url,
            "session": self.flaresolverr_session,
            "maxTimeout": timeout_ms
        }
        
        if cookies:
            flaresolverr_request["cookies"] = cookies
        
        flaresolverr_response = None
        last_error = None
        
        for try_count in range(tries):
            try:
                logger.info("FlareSolverr: Attempt %d/%d for %s" % (try_count + 1, tries, url))
                response_text = self._post_request(flaresolverr_request)
                
                if response_text:
                    response_data = self.json.loads(response_text)
                    
                    # FlareSolverr ritorna status come stringa 'ok' nel campo principale
                    # e status HTTP numerico in solution.status
                    solution = response_data.get('solution', {})
                    http_status = solution.get('status', 500) if isinstance(solution.get('status'), int) else 500
                    
                    # Crea un oggetto risposta compatibile
                    flaresolverr_response = type('FlareSolverrResponse', (), {
                        'status_code': http_status,
                        'content': response_text,
                        'json': lambda *args, **kwargs: response_data
                    })()
                    
                    status_code = flaresolverr_response.status_code
                    
                    if status_code >= 500:
                        raise ValueError(
                            "FlareSolverr request failed, got status code %d" % status_code
                        )
                    
                    logger.info("FlareSolverr: Request successful (status: %d)" % status_code)
                    break
            except Exception as error:
                logger.error("FlareSolverr error %d/%d: %s" % (try_count + 1, tries, str(error)))
                last_error = error
        
        if not flaresolverr_response and last_error:
            raise last_error
        
        return flaresolverr_response
    
    def _post_request(self, data):
        """
        Effettua una richiesta POST al server FlareSolverr
        @param data: Dati da inviare
        @return: Risposta come stringa
        """
        try:
            request_data = self.json.dumps(data).encode('utf-8')
            req = urllib2.Request(
                self.flaresolverr_url,
                data=request_data,
                headers={'Content-Type': 'application/json'}
            )
            response = urllib2.urlopen(req, timeout=120)
            return response.read().decode('utf-8')
        except Exception as e:
            logger.error("FlareSolverr: POST request error: %s" % str(e))
            return None
