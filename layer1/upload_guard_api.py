"""Chromaprint exact-match upload gate for Layer 1.

Run from the repository root:
    python layer1/upload_guard_api.py --build-index
    python layer1/upload_guard_api.py

The API accepts an audio upload, rejects an exact aligned fingerprint match
with HTTP 409, and stores a clear upload in layer1/accepted_uploads. A passed
upload is added to the fingerprint index so later copies are rejected too.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    FASTAPI_AVAILABLE = True
except ModuleNotFoundError:
    # The index-building CLI only needs Python and fpcalc. API dependencies are
    # required only when starting the HTTP server or serving upload requests.
    FastAPI = None  # type: ignore[assignment,misc]
    UploadFile = Any  # type: ignore[assignment,misc]
    FASTAPI_AVAILABLE = False

    def File(*args: Any, **kwargs: Any) -> None:  # type: ignore[misc]
        return None

    class HTTPException(RuntimeError):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: Any):
            super().__init__(str(detail))
            self.status_code = status_code
            self.detail = detail


# All paths are resolved from this file, so launching the API from another
# working directory does not silently point the index at the wrong folder.
ROOT_DIR = Path(__file__).resolve().parent.parent
LAYER1_DIR = Path(__file__).resolve().parent
ORIGINALS_DIR = ROOT_DIR / "original_music"
MUSIC_DIR = ROOT_DIR / "music"
DB_PATH = LAYER1_DIR / "fingerprints_db.json"
FPCALC_PATH = ROOT_DIR / "fpcalc.exe"
ACCEPTED_UPLOADS_DIR = LAYER1_DIR / "accepted_uploads"

# Bound resource use for public upload requests. Fingerprints shorter than ten
# seconds are too short for this exact-match gate to make a useful decision.
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_FINGERPRINT_SECONDS = 1800
MIN_AUDIO_SECONDS = 10.0
SUPPORTED_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm", ".wma"
}

app = FastAPI(
    title="Track-AI Layer 1 Upload Gate",
    description="Blocks uploads that exactly match a registered Chromaprint sequence.",
    version="1.0.0",
) if FASTAPI_AVAILABLE else None

# Protect the check-save-index sequence from races within this API process.
_upload_lock = threading.Lock()


def _load_db() -> dict[str, dict[str, Any]]:
    """Load the fingerprint JSON database and validate its outer structure."""
    if not DB_PATH.exists():
        return {}
    try:
        with DB_PATH.open("r", encoding="utf-8") as db_file:
            data = json.load(db_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read fingerprint database: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Fingerprint database must be a JSON object.")
    return data


def _save_db(records: dict[str, dict[str, Any]]) -> None:
    """Atomically replace the JSON index so interrupted writes do not corrupt it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as db_file:
        json.dump(records, db_file, ensure_ascii=False, indent=2)
        db_file.write("\n")
        db_file.flush()
        os.fsync(db_file.fileno())
    os.replace(temporary_path, DB_PATH)


def extract_raw_fingerprint(audio_path: Path) -> dict[str, Any]:
    """Run fpcalc and return its unpacked integer fingerprint plus duration."""
    if not FPCALC_PATH.is_file():
        raise FileNotFoundError(f"fpcalc.exe is missing: {FPCALC_PATH}")
    result = subprocess.run(
        [
            str(FPCALC_PATH),
            "-length",
            str(MAX_FINGERPRINT_SECONDS),
            "-raw",
            "-json",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()[-1000:]
        raise ValueError(details or "fpcalc could not decode this audio file.")
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["duration"])
        raw_fingerprint = payload["fingerprint"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("fpcalc returned an invalid fingerprint.") from exc
    if not isinstance(raw_fingerprint, list) or not raw_fingerprint:
        raise ValueError("fpcalc returned an empty fingerprint.")
    if duration < MIN_AUDIO_SECONDS:
        raise ValueError(
            f"Audio must be at least {MIN_AUDIO_SECONDS:g} seconds for duplicate checking."
        )
    return {
        "duration": duration,
        "fingerprint_raw": [int(value) & 0xFFFFFFFF for value in raw_fingerprint],
        "fingerprint_algorithm": "chromaprint-fpcalc-raw-v1",
    }


def _contains_exact_sequence(needle: list[int], haystack: list[int]) -> bool:
    """Return whether all query frames occur contiguously in a reference track."""
    if not needle or len(needle) > len(haystack):
        return False

    # Knuth-Morris-Pratt keeps the scan linear even for long audio fingerprints.
    prefix = [0] * len(needle)
    matched = 0
    for index in range(1, len(needle)):
        while matched and needle[index] != needle[matched]:
            matched = prefix[matched - 1]
        if needle[index] == needle[matched]:
            matched += 1
        prefix[index] = matched

    matched = 0
    for frame in haystack:
        while matched and frame != needle[matched]:
            matched = prefix[matched - 1]
        if frame == needle[matched]:
            matched += 1
            if matched == len(needle):
                return True
    return False


def find_exact_duplicate(
    query_fingerprint: list[int], records: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Find an existing record containing the full uploaded fingerprint."""
    for track_id, record in records.items():
        raw = record.get("fingerprint_raw") if isinstance(record, dict) else None
        if not isinstance(raw, list) or not raw:
            continue
        reference_fingerprint = [int(value) & 0xFFFFFFFF for value in raw]
        if _contains_exact_sequence(query_fingerprint, reference_fingerprint):
            return {
                "track_id": track_id,
                "file_path": record.get("file_path"),
                "duration": record.get("duration"),
            }
    return None


def _index_key(path: Path, base_dir: Path) -> str:
    """Create stable, readable keys relative to the project root."""
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _resolve_legacy_record_path(record: dict[str, Any], key: str) -> Path | None:
    """Find media for older records whose stored Windows path may be stale."""
    stored_path = str(record.get("file_path", ""))
    candidates: list[Path] = []
    if stored_path:
        candidates.append(Path(stored_path))
        windows_basename = PureWindowsPath(stored_path).name
        if windows_basename:
            candidates.extend((ORIGINALS_DIR / windows_basename, MUSIC_DIR / windows_basename))
    key_path = Path(key.replace("/", os.sep))
    candidates.extend((ROOT_DIR / key_path, ORIGINALS_DIR / key_path.name, MUSIC_DIR / key_path.name))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_index() -> tuple[int, list[str]]:
    """Add every original_music track and upgrade resolvable legacy DB rows."""
    records = _load_db()
    indexed_count = 0
    errors: list[str] = []

    # Migrate existing entries to raw fingerprints where their source files exist.
    for key, record in list(records.items()):
        if not isinstance(record, dict):
            errors.append(f"{key}: invalid database record; skipped")
            continue
        raw = record.get("fingerprint_raw")
        if isinstance(raw, list) and raw:
            continue
        source_path = _resolve_legacy_record_path(record, key)
        if source_path is None:
            errors.append(f"{key}: legacy source file not found; old fingerprint retained but not searchable")
            continue
        try:
            fingerprint = extract_raw_fingerprint(source_path)
            record.update(fingerprint)
            record["file_path"] = str(source_path.resolve())
            indexed_count += 1
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(f"{key}: {exc}")

    if not ORIGINALS_DIR.is_dir():
        errors.append(f"Original library folder not found: {ORIGINALS_DIR}")
    else:
        audio_paths = sorted(
            path for path in ORIGINALS_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        for number, audio_path in enumerate(audio_paths, start=1):
            key = _index_key(audio_path, ROOT_DIR)
            try:
                fingerprint = extract_raw_fingerprint(audio_path)
                records[key] = {
                    "file_path": str(audio_path.resolve()),
                    **fingerprint,
                }
                indexed_count += 1
                print(f"[{number}/{len(audio_paths)}] indexed: {audio_path.name}")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                errors.append(f"{audio_path}: {exc}")

    _save_db(records)
    return indexed_count, errors


def _safe_upload_name(filename: str | None) -> str:
    """Strip path components and characters unsafe in a Windows filename."""
    name = (filename or "upload").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "upload")[:180]


def health() -> dict[str, Any]:
    """Expose readiness without leaking full fingerprint contents."""
    try:
        records = _load_db()
        searchable_count = sum(
            isinstance(record, dict)
            and isinstance(record.get("fingerprint_raw"), list)
            and bool(record["fingerprint_raw"])
            for record in records.values()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "ready" if searchable_count else "index_required",
        "searchable_tracks": searchable_count,
        "index_command": "python layer1/upload_guard_api.py --build-index",
    }


async def upload_audio(file: UploadFile = File(...)) -> dict[str, Any]:
    """Reject an exact registered duplicate with 409; store and index a clear upload."""
    original_name = _safe_upload_name(file.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio type. Allowed extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    temp_path: Path | None = None
    stored_path: Path | None = None
    try:
        # Stream to a temporary file instead of keeping large uploads in RAM.
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=extension, prefix="track_ai_upload_", delete=False
        ) as temporary_file:
            temp_path = Path(temporary_file.name)
            total_bytes = 0
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the 250 MB limit.")
                temporary_file.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        try:
            query = extract_raw_fingerprint(temp_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=422, detail="Audio fingerprinting timed out.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with _upload_lock:
            records = _load_db()
            searchable_count = sum(
                isinstance(record, dict)
                and isinstance(record.get("fingerprint_raw"), list)
                and bool(record["fingerprint_raw"])
                for record in records.values()
            )
            if searchable_count == 0:
                raise HTTPException(
                    status_code=503,
                    detail="Fingerprint index is empty. Build it before accepting uploads.",
                )

            duplicate = find_exact_duplicate(query["fingerprint_raw"], records)
            if duplicate:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DUPLICATE_AUDIO",
                        "message": "An exact Chromaprint sequence is already registered.",
                        "matched_track_id": duplicate["track_id"],
                        "matched_file": duplicate["file_path"],
                    },
                )

            ACCEPTED_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            upload_id = uuid.uuid4().hex
            stored_path = ACCEPTED_UPLOADS_DIR / f"{upload_id}_{original_name}"
            os.replace(temp_path, stored_path)
            temp_path = None
            index_key = f"uploaded:{upload_id}/{original_name}"
            records[index_key] = {
                "file_path": str(stored_path.resolve()),
                "upload_id": upload_id,
                "original_filename": original_name,
                **query,
            }
            try:
                _save_db(records)
            except OSError as exc:
                stored_path.unlink(missing_ok=True)
                stored_path = None
                raise HTTPException(status_code=500, detail="Could not save the fingerprint index.") from exc

        return {
            "status": "accepted",
            "upload_id": upload_id,
            "filename": original_name,
            "duration_seconds": round(query["duration"], 2),
            "message": "No exact registered fingerprint match was found; the file was stored and indexed.",
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        await file.close()


# Register routes only when the optional HTTP dependencies are installed. This
# keeps the --build-index command usable in a minimal Python environment.
if app is not None:
    app.get("/health")(health)
    app.post("/api/v1/uploads")(upload_audio)


def main() -> None:
    """Build the fingerprint index or start the local FastAPI server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="Index original_music and upgrade searchable legacy records, then exit.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; default is local-only.")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port; default: 8000.")
    args = parser.parse_args()

    if args.build_index:
        count, errors = build_index()
        print(f"Indexed or upgraded {count} tracks. Searchable records: {sum(bool(r.get('fingerprint_raw')) for r in _load_db().values() if isinstance(r, dict))}.")
        for error in errors:
            print(f"WARNING: {error}")
        return

    if not FASTAPI_AVAILABLE:
        raise SystemExit(
            "FastAPI upload dependencies are missing. Install them with: "
            "python -m pip install -r layer1/requirements-upload-guard.txt"
        )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
