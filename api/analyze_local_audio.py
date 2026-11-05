"""Run the frozen Track-AI engine against one local audio file.

This command is read-only: it does not add the query audio to the reference
corpus and it does not create a registration or blockchain transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze one audio file with Track-AI v5")
    parser.add_argument("audio", type=Path, help="MP3, WAV, WebM, FLAC, M4A, AAC, OGG, or WMA file")
    args = parser.parse_args()
    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        parser.error(f"audio file not found: {audio}")
    if audio.suffix.lower() not in {".mp3", ".wav", ".webm", ".flac", ".m4a", ".aac", ".ogg", ".wma"}:
        parser.error("unsupported audio extension")

    from engine import Engine

    result = Engine().verify(audio, sha256_file(audio))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
