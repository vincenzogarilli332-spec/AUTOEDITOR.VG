"""
clips.py

Gestisce la "Galleria": le clip video grezze caricate dall'utente.
Per ogni clip caricata:
1. La salviamo su disco (storage/clips/<id>.mp4)
2. Estraiamo alcuni fotogrammi
3. Mandiamo i fotogrammi a Claude per farceli descrivere
4. Salviamo la descrizione in un piccolo "database" JSON (storage/clips_meta.json)

Questo elenco di descrizioni e' poi quello che il modello usa per scegliere
quale clip abbinare a ogni blocco di testo, nella sezione "Nuovo Video".
"""

import json
import shutil
import uuid
from pathlib import Path

from claude_client import describe_clip_from_frames
from editor import extract_frames, get_duration

STORAGE = Path(__file__).parent / "storage"
CLIPS_DIR = STORAGE / "clips"
META_FILE = STORAGE / "clips_meta.json"

CLIPS_DIR.mkdir(parents=True, exist_ok=True)
if not META_FILE.exists():
    META_FILE.write_text("[]")


def _load_meta() -> list[dict]:
    return json.loads(META_FILE.read_text())


def _save_meta(items: list[dict]):
    META_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False))


def list_clips() -> list[dict]:
    return _load_meta()


def delete_clip(clip_id: str):
    items = _load_meta()
    items = [c for c in items if c["id"] != clip_id]
    _save_meta(items)
    for f in CLIPS_DIR.glob(f"{clip_id}.*"):
        f.unlink(missing_ok=True)


def add_clip(tmp_path: Path, original_filename: str) -> dict:
    """Salva una nuova clip, la analizza con Claude e ne salva i metadati.
    Ritorna il record della clip appena creata."""
    clip_id = uuid.uuid4().hex[:12]
    ext = Path(original_filename).suffix or ".mp4"
    dest = CLIPS_DIR / f"{clip_id}{ext}"
    shutil.copy(tmp_path, dest)

    duration = get_duration(dest)

    frames_dir = STORAGE / "tmp_frames" / clip_id
    frame_paths = extract_frames(dest, frames_dir, count=3)
    description = describe_clip_from_frames([str(p) for p in frame_paths])
    shutil.rmtree(frames_dir, ignore_errors=True)

    record = {
        "id": clip_id,
        "filename": dest.name,
        "original_filename": original_filename,
        "duration": round(duration, 2),
        "description": description,
    }

    items = _load_meta()
    items.append(record)
    _save_meta(items)
    return record
