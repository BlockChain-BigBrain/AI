"""Import manually downloaded Pixabay audio after checking existing tracks.

Pixabay does not provide an official music-download API for mass collection.
This tool only processes files that the user has already downloaded into
``pixabay_inbox``. It skips exact file duplicates and Chromaprint-identical
audio, then (only with ``--apply``) moves up to the requested number of unique
tracks into ``original_music``. Duplicate and unreadable files are left in the
inbox for review.

Examples (run from the project root):
    python layer2/import_pixabay_batch.py                 # preview 905 additions
    python layer2/import_pixabay_batch.py --needed 705     # preview to reach 1,000 total
    python layer2/import_pixabay_batch.py --needed 905 --apply
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


# Resolve all paths from this script so the command works from any directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INBOX = PROJECT_DIR / "pixabay_inbox"
ORIGINALS_DIR = PROJECT_DIR / "original_music"
REPORT_PATH = PROJECT_DIR / "layer2" / "artifacts" / "pixabay_import_report.csv"
LOG_PATH = PROJECT_DIR / "layer2" / "artifacts" / "pixabay_source_log.csv"
FPCALC = PROJECT_DIR / "fpcalc.exe"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm", ".aac", ".wma"}


@dataclass
class Fingerprint:
    """Audio identity data used to compare files beyond their filenames."""

    path: Path
    sha256: str
    duration: float
    frames: list[int]


def audio_files(folder: Path) -> list[Path]:
    """Return supported audio files recursively in stable order."""
    if not folder.is_dir():
        return []
    return sorted(
        (path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS),
        key=lambda path: str(path).casefold(),
    )


def balanced_audio_files(folder: Path) -> list[Path]:
    """Interleave creator-name groups so a capped import is not alphabetically biased."""
    grouped: dict[str, deque[Path]] = defaultdict(deque)
    for path in audio_files(folder):
        # Pixabay filenames commonly start with the contributor slug.
        creator = path.stem.split("-", 1)[0].casefold()
        grouped[creator].append(path)
    ordered: list[Path] = []
    while grouped:
        for creator in sorted(list(grouped)):
            ordered.append(grouped[creator].popleft())
            if not grouped[creator]:
                del grouped[creator]
    return ordered


def sha256_file(path: Path) -> str:
    """Hash file bytes so exact copies can be skipped quickly."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint_file(path: Path) -> Fingerprint:
    """Read a full-track Chromaprint sequence using the bundled fpcalc."""
    result = subprocess.run(
        [str(FPCALC), "-raw", "-json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip()[-1000:] or "fpcalc could not decode the audio")
    payload = json.loads(result.stdout)
    frames = payload.get("fingerprint")
    if not isinstance(frames, list) or not frames:
        raise ValueError("fpcalc returned an empty fingerprint")
    duration = float(payload["duration"])
    if duration < 10:
        raise ValueError("audio is shorter than 10 seconds; duplicate comparison is unreliable")
    return Fingerprint(path, sha256_file(path), duration, [int(frame) & 0xFFFFFFFF for frame in frames])


def contains_sequence(needle: list[int], haystack: list[int]) -> bool:
    """Check if one complete fingerprint occurs contiguously in another."""
    if not needle or len(needle) > len(haystack):
        return False
    # KMP prefix table makes matching linear, even for long full-track fingerprints.
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


def duplicate_of(candidate: Fingerprint, references: list[Fingerprint]) -> Fingerprint | None:
    """Find exact-byte or full-fingerprint matches in the reference tracks."""
    for reference in references:
        if candidate.sha256 == reference.sha256:
            return reference
        # Require the full shorter track fingerprint to match inside the longer
        # one. This catches common re-encodes and a track contained in a longer file.
        shorter, longer = (candidate, reference) if len(candidate.frames) <= len(reference.frames) else (reference, candidate)
        if abs(candidate.duration - reference.duration) <= 1.0 or shorter is candidate:
            if contains_sequence(shorter.frames, longer.frames):
                return reference
    return None


def unique_destination(source: Path, target_dir: Path) -> Path:
    """Avoid overwriting an existing file when names collide."""
    target = target_dir / source.name
    if not target.exists():
        return target
    stem, suffix = source.stem, source.suffix
    index = 2
    while (target_dir / f"{stem} ({index}){suffix}").exists():
        index += 1
    return target_dir / f"{stem} ({index}){suffix}"


def main() -> None:
    """Compare a manually downloaded batch and optionally import unique files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX, help="folder containing manually downloaded audio")
    parser.add_argument("--needed", type=int, default=905, help="maximum additional unique tracks to import")
    parser.add_argument("--apply", action="store_true", help="move unique files into original_music; default is preview only")
    args = parser.parse_args()
    inbox = args.inbox.resolve()
    originals_dir = ORIGINALS_DIR.resolve()
    if args.needed < 1:
        raise SystemExit("--needed must be a positive number")
    if inbox == originals_dir or originals_dir in inbox.parents:
        raise SystemExit("Inbox must not be original_music or a folder inside it")
    if not originals_dir.is_dir():
        raise SystemExit(f"Reference folder does not exist: {originals_dir}")
    if not FPCALC.is_file():
        raise SystemExit(f"fpcalc.exe is missing: {FPCALC}")

    candidates = balanced_audio_files(inbox)
    if not candidates:
        inbox.mkdir(parents=True, exist_ok=True)
        print(f"No audio files found. Put manually downloaded files here: {inbox}")
        print("No download was started. Re-run this command after adding a batch.")
        return

    # Build the reference fingerprints once, then add accepted candidates to the
    # same list so duplicates within the incoming batch are also caught.
    references: list[Fingerprint] = []
    errors: list[dict[str, str]] = []
    for path in audio_files(originals_dir):
        try:
            references.append(fingerprint_file(path))
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            errors.append({"file": str(path), "status": "REFERENCE_ERROR", "matched_file": "", "details": str(exc)})
    if not references:
        raise SystemExit("Could not fingerprint any reference tracks; refusing to import files.")

    # Treat --needed as a cumulative Pixabay-import target across repeated
    # batches, so running the importer again does not restart the count.
    already_imported = 0
    if LOG_PATH.is_file():
        try:
            with LOG_PATH.open("r", newline="", encoding="utf-8-sig") as log:
                already_imported = sum(1 for row in csv.DictReader(log) if row.get("file"))
        except (OSError, csv.Error):
            raise SystemExit(f"Cannot read source log safely: {LOG_PATH}")
    remaining_target = max(0, args.needed - already_imported)

    rows: list[dict[str, str]] = []
    accepted = 0
    originals_dir.mkdir(parents=True, exist_ok=True)
    for path in candidates:
        try:
            candidate = fingerprint_file(path)
            match = duplicate_of(candidate, references)
            if match:
                rows.append({"file": str(path), "status": "DUPLICATE_SKIPPED", "matched_file": str(match.path), "details": "Exact SHA-256 or complete Chromaprint sequence match"})
                continue
            if accepted >= remaining_target:
                rows.append({"file": str(path), "status": "UNPROCESSED_LIMIT", "matched_file": "", "details": f"Cumulative unique import target reached ({args.needed})"})
                continue
            if args.apply:
                destination = unique_destination(path, originals_dir)
                shutil.move(str(path), str(destination))
                candidate.path = destination
                status = "IMPORTED_UNIQUE"
                print(f"[imported] {destination.name}")
            else:
                destination = path
                status = "UNIQUE_PREVIEW"
                print(f"[unique candidate] {path.name}")
            rows.append({"file": str(path), "status": status, "matched_file": "", "details": str(destination) if args.apply else "No file moved; re-run with --apply to import"})
            references.append(candidate)
            accepted += 1
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            rows.append({"file": str(path), "status": "ERROR_SKIPPED", "matched_file": "", "details": str(exc)})

    rows = errors + rows
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", newline="", encoding="utf-8-sig") as report:
        writer = csv.DictWriter(report, fieldnames=["file", "status", "matched_file", "details"])
        writer.writeheader()
        writer.writerows(rows)

    # Preserve licensing/source evidence. The user can fill URL and author fields
    # as files arrive; the importer never fabricates provenance.
    source_exists = LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8-sig") as log:
        writer = csv.DictWriter(log, fieldnames=["file", "sha256", "source_url", "contributor", "license_url"])
        if not source_exists:
            writer.writeheader()
        for row in rows:
            if row["status"] == "IMPORTED_UNIQUE":
                moved = Path(row["details"])
                try:
                    file_hash = sha256_file(moved)
                except OSError:
                    file_hash = ""
                writer.writerow({"file": str(moved), "sha256": file_hash, "source_url": "", "contributor": "", "license_url": ""})

    unique_count = sum(row["status"] == "UNIQUE_PREVIEW" for row in rows) if not args.apply else sum(row["status"] == "IMPORTED_UNIQUE" for row in rows)
    duplicate_count = sum(row["status"] == "DUPLICATE_SKIPPED" for row in rows)
    print(f"\nMode: {'APPLY' if args.apply else 'PREVIEW'}")
    print(f"Existing fingerprinted tracks: {len(references) - unique_count}")
    print(f"Unique files {'imported' if args.apply else 'ready'} this batch: {unique_count}; cumulative target: {already_imported + unique_count}/{args.needed}")
    if remaining_target == 0:
        print(f"Cumulative import target of {args.needed} has already been reached.")
    print(f"Duplicates skipped: {duplicate_count}; report: {REPORT_PATH}")
    if not args.apply:
        print("Preview only: no files were moved. Add --apply to import these unique files.")


if __name__ == "__main__":
    main()
