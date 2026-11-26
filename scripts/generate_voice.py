"""Genera la voz pregenerada de Din con ElevenLabs (una sola vez por voz).

    .venv\\Scripts\\python.exe scripts\\generate_voice.py               # genera lo que falte
    .venv\\Scripts\\python.exe scripts\\generate_voice.py --force       # regenera todo
    .venv\\Scripts\\python.exe scripts\\generate_voice.py --only n35,pesos   # regenera algunos

Lee ELEVENLABS_API_KEY del .env. Escribe app/static/voice/<voz>/<clave>.mp3 y manifest.json.
Las claves y sus textos están en app/voice.py (CLIPS). Haz commit de la carpeta generada.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.voice import CLIPS, VOICE_DIR  # noqa: E402

DEFAULT_VOICE = "ewn5JTa3lNPY8QVuZJi6"
MODEL = "eleven_multilingual_v2"   # mejor calidad que flash; se paga una sola vez
SETTINGS = {"stability": 0.6, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}

# Windows reserva estos nombres ("con.mp3" no es un archivo para Windows ni para git): se les antepone "_"
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def file_name(key: str) -> str:
    return f"_{key}.mp3" if key.lower() in RESERVED else f"{key}.mp3"


def generate(client: httpx.Client, key: str, voice: str, clip: dict) -> bytes:
    body = {"text": clip["text"], "model_id": MODEL, "voice_settings": SETTINGS}
    if clip.get("prev"):
        body["previous_text"] = clip["prev"]
    if clip.get("next"):
        body["next_text"] = clip["next"]
    for attempt in range(5):
        r = client.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                        params={"output_format": "mp3_44100_128"}, json=body)
        if r.status_code == 429 or r.status_code >= 500:
            wait = 2 ** attempt
            print(f"   {key}: ElevenLabs respondió {r.status_code}, reintento en {wait} s")
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
        return r.content
    raise RuntimeError("ElevenLabs no respondió después de 5 intentos")


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera los audios de la voz pregenerada")
    ap.add_argument("--voice", default=os.getenv("VOICE_ID") or DEFAULT_VOICE, help=f"voz de ElevenLabs (por defecto {DEFAULT_VOICE})")
    ap.add_argument("--force", action="store_true", help="regenera aunque ya existan")
    ap.add_argument("--only", default="", help="claves separadas por coma (ej. n35,pesos)")
    args = ap.parse_args()

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("Falta ELEVENLABS_API_KEY en el .env")
        return 1
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    unknown = only - set(CLIPS)
    if unknown:
        print("Claves que no existen:", ", ".join(sorted(unknown)))
        return 1

    out = VOICE_DIR / args.voice
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    clips = manifest.get("clips", {})

    def stale(k: str) -> bool:  # falta, se borró el archivo o cambió el texto en app/voice.py
        return k not in clips or not (out / file_name(k)).exists() or clips[k].get("text") != CLIPS[k]["text"]

    if only:
        todo = [k for k in CLIPS if k in only]
    else:
        todo = [k for k in CLIPS if args.force or stale(k)]
    chars = sum(len(CLIPS[k]["text"]) for k in todo)
    print(f"Voz {args.voice} · modelo {MODEL}")
    print(f"{len(todo)} de {len(CLIPS)} audios por generar (~{chars} caracteres de ElevenLabs)")

    failed = []
    with httpx.Client(timeout=60, headers={"xi-api-key": api_key}) as client:
        for i, key in enumerate(todo, 1):
            clip = CLIPS[key]
            try:
                audio = generate(client, key, args.voice, clip)
            except Exception as e:
                print(f"✕ {key}: {e}")
                failed.append(key)
                if "401" in str(e) or "voice_not_found" in str(e):
                    break  # llave o voz incorrecta: no tiene caso seguir
                continue
            (out / file_name(key)).write_bytes(audio)
            clips[key] = {"file": file_name(key), "text": clip["text"], "hash": hashlib.sha1(audio).hexdigest()[:10]}
            print(f"✓ {i}/{len(todo)} {key}: {clip['text']}")
            # el manifiesto se guarda en cada paso: si se corta, al volver a correr sigue donde se quedó
            manifest = {"voice": args.voice, "model": MODEL, "settings": SETTINGS,
                        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "clips": clips}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    missing = sorted(set(CLIPS) - set(clips))
    print()
    if failed or missing:
        print(f"Faltan {len(missing)} audios: {', '.join(missing[:20])}{' …' if len(missing) > 20 else ''}")
        print("Vuelve a correr el script para generar solo los que faltan.")
        return 1
    size = sum(f.stat().st_size for f in out.glob("*.mp3")) / 1024
    where = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"Listo: {len(clips)} audios en {where} ({size:,.0f} KB). Haz commit de esa carpeta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
