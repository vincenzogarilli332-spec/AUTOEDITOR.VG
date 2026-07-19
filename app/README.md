# Sala Montaggio — app di montaggio video automatico

App con 3 sezioni:
- **Galleria**: carichi le clip grezze, Claude le guarda e le descrive da solo (nessun tag manuale da scrivere).
- **Nuovo Video**: incolli il testo/script diviso in blocchi narrativi (separati da una riga vuota), opzionalmente alleghi il voice-over già registrato. Claude sceglie le clip migliori per ogni blocco seguendo le regole della tua tecnica di montaggio, e ffmpeg costruisce il video finale.
- **Video Creati**: l'archivio dei video generati, guardabili e scaricabili.

---

## 1. Provarla in locale (facoltativo, prima del deploy)

Serve Python 3.11+, ffmpeg installato sul sistema, e una chiave API Anthropic.

```bash
cd backend
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
export APP_PASSWORD="scegli-una-password"
uvicorn main:app --reload
```

Poi apri `http://localhost:8000` nel browser.

---

## 2. Deploy su Railway (consigliato — pochi minuti, pochi €/mese)

1. Crea un account su **railway.app**
2. Crea un nuovo progetto → **Deploy from GitHub repo** (carica prima questa cartella su un repo GitHub, anche privato), oppure usa **Railway CLI** per fare il deploy direttamente da qui senza GitHub:
   ```bash
   npm install -g @railway/cli
   railway login
   railway init
   railway up
   ```
3. Railway rileverà il `Dockerfile` e farà la build automaticamente (include ffmpeg).
4. Vai su **Variables** del progetto e aggiungi:
   - `ANTHROPIC_API_KEY` = la tua chiave (da console.anthropic.com)
   - `APP_PASSWORD` = la password che vuoi usare per accedere
5. **Importante — storage persistente**: vai su **Settings → Volumes**, crea un volume e montalo su `/app/backend/storage`. Senza questo, ogni nuovo deploy cancella le clip e i video caricati.
6. Railway ti da' un URL pubblico (tipo `tuoprogetto.up.railway.app`) — è l'indirizzo da aprire dal telefono o dal computer.

## 2bis. Deploy su Render (alternativa)

Stessa logica: "New → Web Service" → collega il repo → Render legge il `Dockerfile` in automatico → aggiungi le stesse Environment Variables → aggiungi un **Persistent Disk** montato su `/app/backend/storage`.

---

## 3. Limiti attuali / prossimi miglioramenti

- **Sincronizzazione audio-testo**: in questa prima versione il testo di ogni blocco resta a schermo per tutta la durata del blocco, non è ancora sincronizzato parola-per-parola con l'audio (richiederebbe l'integrazione di Whisper per i timestamp — buon prossimo passo, ma appesantisce il server: richiede più RAM/CPU).
- **Selezione manuale**: se in futuro vuoi poter correggere a mano la scelta delle clip fatta da Claude prima di generare il video finale (invece che affidarti al 100% all'automatismo), è un'aggiunta naturale all'interfaccia "Nuovo Video".
- **Miniature reali in Galleria**: al momento le card della galleria non mostrano un vero fotogramma di anteprima (solo la descrizione testuale) — si può aggiungere generando una thumbnail .jpg per clip.
- **Musica di sottofondo**: il mux audio attuale gestisce solo il voice-over; aggiungere un secondo livello (musica a basso volume) è una modifica semplice in `editor.py` (`mux_audio`).

---

## 4. Struttura del progetto

```
app/
  Dockerfile
  .env.example
  backend/
    main.py          -> API FastAPI + serve il frontend
    claude_client.py -> chiamate all'API di Claude (visione + scelta clip)
    clips.py         -> gestione Galleria
    generate.py       -> orchestrazione generazione video
    editor.py          -> montaggio ffmpeg (tagli, zoom, transizioni, testo)
    auth.py            -> password singola
    storage/            -> clip caricate + video generati (da rendere persistente)
  frontend/
    index.html
    style.css
    app.js
```
