"""
openai_client.py

Wrapper minimale per chiamare l'API di OpenAI (GPT-4.1 mini, con capacita'
di visione) via HTTP diretto — stessa struttura di claude_client.py, cosi'
il resto dell'app (clips.py, generate.py) non deve cambiare, cambia solo
quale "cervello" analizza le clip e sceglie il montaggio.

Usato per due cose:
1. Descrivere automaticamente una scena video guardando alcuni fotogrammi
   (sezione "Galleria").
2. Scegliere quali clip usare per ogni blocco narrativo del testo/voice-over
   (sezione "Nuovo Video").
"""

import base64
import json
import os

import httpx

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4.1-mini"


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Manca la variabile d'ambiente OPENAI_API_KEY. "
            "Impostala nelle Environment Variables del servizio (Railway/Render)."
        )
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def describe_clip_from_frames(frame_paths: list[str]) -> dict:
    """Manda 2-3 fotogrammi di una scena a GPT-4.1 mini e chiede un'analisi
    strutturata: descrizione, se ci sono scritte gia' presenti nel video,
    se mostra il prodotto (un nastro/tape blu), su quale parte del corpo,
    e se mostra piu' persone/testimonianze in sequenza. Serve a scegliere
    con precisione quale clip usare in ogni momento del video."""

    content = [
        {
            "type": "text",
            "text": (
                "Guarda questi fotogrammi presi da una clip video verticale "
                "usata per un contenuto di marketing di un prodotto: un nastro "
                "kinesiologico blu (tape) usato per spalla, ginocchio o alluce "
                "valgo. Rispondi SOLO con un JSON valido (nessun testo prima o "
                "dopo), con questa forma esatta:\n"
                '{"description": "descrizione breve (1-2 frasi, max 35 parole): '
                'soggetto, azione/gesto, ambientazione. Se si vede un oggetto '
                'legato a un rimedio contro il dolore diverso dal nastro blu '
                '(es. tutore rigido, crema, cerotto, antinfiammatorio/pillole), '
                'nominalo esplicitamente nella descrizione", '
                '"has_text_overlay": true/false (scritte/didascalie gia\' '
                'sovrimpresse nel video, non conta il logo di un\'app), '
                '"text_position": "top"/"middle"/"bottom"/"none", '
                '"shows_product": true/false (si vede chiaramente il nastro '
                'kinesiologico BLU, il prodotto stesso, applicato o in mano), '
                '"body_part": "spalla"/"ginocchio"/"alluce_valgo_piede"/"altro"/"nessuno" '
                '(su quale parte del corpo e\' applicato il prodotto o si vede '
                'il problema/dolore; "nessuno" se non e\' rilevante), '
                '"shows_multiple_people": true/false (la clip mostra piu\' '
                'persone diverse, o una sequenza di piu\' momenti/testimonianze '
                'diverse in rapida successione, utile per una sezione di '
                'recensioni/prova sociale)}'
            ),
        }
    ]
    for fp in frame_paths:
        with open(fp, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            }
        )

    payload = {
        "model": MODEL,
        "max_tokens": 250,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": content}],
    }

    with httpx.Client(timeout=60) as client:
        r = client.post(OPENAI_API_URL, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()

    raw = data["choices"][0]["message"]["content"].strip()
    parsed = json.loads(raw)
    return {
        "description": parsed.get("description", "").strip(),
        "has_text_overlay": bool(parsed.get("has_text_overlay", False)),
        "text_position": parsed.get("text_position", "none"),
        "shows_product": bool(parsed.get("shows_product", False)),
        "body_part": parsed.get("body_part", "nessuno"),
        "shows_multiple_people": bool(parsed.get("shows_multiple_people", False)),
    }


def detect_product_context(full_script: str) -> str:
    """Legge lo script completo e riconosce di quale variante del prodotto
    (nastro blu per spalla / ginocchio / alluce valgo) si sta parlando,
    cosi' la scelta delle clip puo' restare coerente con quella parte del
    corpo per tutto il video."""
    prompt = (
        "Il prodotto venduto e' sempre un nastro kinesiologico blu (tape), "
        "disponibile in tre varianti: spalla, ginocchio, alluce valgo (piede). "
        "Leggi questo script pubblicitario e rispondi SOLO con una di queste "
        "quattro parole esatte, senza altro testo: spalla / ginocchio / "
        "alluce_valgo_piede / generico (usa 'generico' solo se davvero non si "
        "capisce quale parte del corpo).\n\nSCRIPT:\n" + full_script
    )
    payload = {
        "model": MODEL,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=30) as client:
        r = client.post(OPENAI_API_URL, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"].strip().lower()


def choose_clips_for_blocks(
    blocks: list[str],
    clip_library: list[dict],
    block_targets: list[float],
    product_context: str = "generico",
) -> list[dict]:
    """Dato un elenco di blocchi di testo (ognuno una fase narrativa: problema,
    smentita soluzioni, reveal, benefici...), la libreria di clip disponibili
    (ognuna con id + descrizione) e una durata-obiettivo per ogni blocco
    (calcolata dalla durata reale dell'audio, proporzionalmente al testo),
    chiede al modello di scegliere, per ogni blocco, quali clip usare, con
    quale durata e quale tipo di transizione in entrata, seguendo le regole
    della tecnica di editing.

    Ritorna una lista allineata a 'blocks': per ogni blocco, un dizionario
    { transition_in: "hard"|"strong", segments: [ {clip_id, duration, zoom}, ... ] }.
    """

    rules = (
        f"CONTESTO PRODOTTO: questo script parla della variante '{product_context}' "
        "del nastro kinesiologico blu. Quando scegli clip che mostrano il prodotto o "
        "il problema/parte del corpo, preferisci sempre quelle con body_part coerente "
        f"con '{product_context}' (se disponibili in libreria); evita clip di varianti "
        "diverse (es. non usare clip su una spalla se il prodotto e' per il ginocchio).\n\n"
        "REGOLA FONDAMENTALE SUL REVEAL DEL PRODOTTO:\n"
        "- Individua tu stesso in quale blocco il testo nomina/rivela per la prima volta "
        "il prodotto (di solito e' dopo meta' dei blocchi totali, mai nei primissimi).\n"
        "- In TUTTI i blocchi PRIMA di quel punto: NON scegliere MAI clip con "
        "shows_product=true. Zero eccezioni, anche se sarebbero visivamente adatte.\n"
        "- Dal blocco del reveal in poi: le clip con shows_product=true diventano "
        "preferibili quando il testo parla del prodotto stesso.\n\n"
        "REGOLE SUI PRIMI BLOCCHI (hook, problema, smentita soluzioni passate):\n"
        "- Devono essere i piu' 'narrativi' possibile: persone che agiscono, provano "
        "qualcosa, mostrano il problema (dolore, fatica, disagio) o usano una soluzione "
        "diversa dal nostro prodotto. Mai clip statiche o del nostro prodotto qui.\n"
        "- Se il testo nomina uno strumento/rimedio specifico gia' provato dalla persona "
        "(es. 'tutore rigido', 'crema', 'antinfiammatorio', 'cerotto'), scegli la clip la "
        "cui descrizione nomina ESPLICITAMENTE quello stesso oggetto. Non generalizzare: "
        "se il testo dice 'tutore rigido', non va bene una clip generica di dolore, va "
        "cercata proprio la clip che mostra un tutore rigido.\n\n"
        "REGOLE SUL MATCHING EMOZIONALE/GESTUALE (non solo letterale):\n"
        "- Il testo puo' descrivere una sensazione/risultato senza nominare oggetti "
        "concreti (es. 'torno a camminare tranquillo', 'mi sento di nuovo libero'). In "
        "questi casi scegli la clip il cui gesto/movimento/espressione comunica quella "
        "stessa sensazione (es. una persona che cammina con naturalezza, un sorriso, un "
        "gesto di sollievo), anche se la descrizione della clip non usa le stesse parole "
        "del testo.\n\n"
        "REGOLE SULLA SEZIONE RECENSIONI / PROVA SOCIALE:\n"
        "- Quando il testo parla di quante persone hanno gia' provato il prodotto o cita "
        "recensioni/testimonianze, preferisci le clip con shows_multiple_people=true "
        "(piu' persone o piu' momenti diversi in rapida sequenza) rispetto a una singola "
        "persona.\n\n"
        "REGOLE DI MONTAGGIO GENERALI:\n"
        "- Ogni blocco ha una DURATA-OBIETTIVO indicata: la somma delle durate dei suoi "
        "segmenti deve avvicinarsi a quel numero (tolleranza +/- 15%), ma decidi tu come "
        "distribuirla in base al senso del testo in quel punto:\n"
        "  - Azione lenta, dettaglio importante, momento chiave -> clip piu' lunga (fino "
        "a 2.5-3s).\n"
        "  - Scena lenta/ripetitiva (persona che parla/si muove senza cambiare granche') "
        "-> spezzala con un micro-taglio ritmico (0.7-1.0s), anche riusando la stessa "
        "clip con un offset diverso.\n"
        "  - Momenti di build-up/urgenza -> ritmo piu' veloce, piu' tagli brevi.\n"
        "  - Momenti calmi/esplicativi -> clip singole piu' lunghe.\n"
        "- Zoom leggero (Ken Burns) su circa 1 clip ogni 2-3, non di piu'.\n"
        "- Ogni blocco puo' contenere da 1 a 4 clip in sequenza (taglio secco dentro lo "
        "stesso blocco).\n"
        "- Ragiona sull'INTERA libreria di clip disponibili insieme, per tutti i blocchi "
        "contemporaneamente: non scegliere in modo affrettato blocco per blocco, ma "
        "considera quali clip si adattano meglio a quale blocco viste tutte insieme, "
        "cosi' da non sprecare la clip migliore in un punto secondario.\n"
        "- Evita di ripetere sempre la stessa clip se ci sono alternative valide.\n\n"
        "REGOLE PER LA TRANSIZIONE TRA UN BLOCCO E IL PRECEDENTE (campo transition_in):\n"
        "- 'hard' (taglio secco, DEFAULT): il blocco continua lo stesso filo narrativo "
        "del precedente.\n"
        "- 'strong' (transizione con avvicinamento): SOLO in corrispondenza di una vera "
        "svolta narrativa importante (es. il momento del reveal del prodotto). Usalo con "
        "parsimonia: al massimo 1-2 transizioni 'strong' in tutto il video.\n"
        "- Il primo blocco non ha transizione in entrata, ignora questo campo per il "
        "blocco 0.\n"
    )

    targets_text = "\n".join(
        f"BLOCCO {i}: durata-obiettivo {t:.1f}s" for i, t in enumerate(block_targets)
    )

    library_text = "\n".join(
        f"- id={c['id']}: {c['description']} "
        f"[shows_product={c.get('shows_product', False)}, "
        f"body_part={c.get('body_part', 'nessuno')}, "
        f"shows_multiple_people={c.get('shows_multiple_people', False)}]"
        for c in clip_library
    )
    blocks_text = "\n".join(f"BLOCCO {i}: \"{b}\"" for i, b in enumerate(blocks))

    prompt = (
        f"{rules}\n\nDURATE OBIETTIVO PER BLOCCO:\n{targets_text}\n\n"
        f"LIBRERIA CLIP DISPONIBILI:\n{library_text}\n\n"
        f"TESTO DIVISO IN BLOCCHI NARRATIVI:\n{blocks_text}\n\n"
        "Per ogni blocco, scegli la sequenza di clip da usare e il tipo di transizione in "
        "entrata. Rispondi SOLO con un JSON valido (nessun testo prima o dopo, nessun blocco "
        "markdown), con questa forma esatta:\n"
        '{"blocks": [ {"transition_in": "hard", "segments": [ {"clip_id": "...", '
        '"duration": 1.8, "zoom": false}, ... ] }, ... ] }\n'
        "L'array 'blocks' deve avere esattamente la stessa lunghezza e lo stesso ordine dei "
        "BLOCCO elencati sopra."
    )

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }

    with httpx.Client(timeout=60) as client:
        r = client.post(OPENAI_API_URL, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()

    raw = data["choices"][0]["message"]["content"].strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    parsed = json.loads(raw)
    return parsed["blocks"]
