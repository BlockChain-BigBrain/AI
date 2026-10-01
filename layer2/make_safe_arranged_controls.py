"""Create transformed normal-music controls for Layer 2 experiments.

This script applies the same kinds of audio changes used by the synthetic
positive generator to distinct files in ``music/``. The outputs are useful
for checking whether the detector mistakes editing or audio effects for a
copied melody. They are marked ``unverified_safe_control`` because the source
tracks still need human review before being treated as definitive negatives.

Run from the project root:
    python layer2/make_safe_arranged_controls.py --songs 10 --seed 20260930
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from make_arranged_positives import (
    CASE_TYPES,
    MIN_QUERY_SECONDS,
    audio_files,
    decode_excerpt,
    duration_seconds,
    find_ffmpeg,
    make_filtered_case,
    make_section_edit,
    save_wav,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
MUSIC_DIR = PROJECT_DIR / "music"
ORIGINAL_DIR = PROJECT_DIR / "original_music"
ARTIFACT_DIR = PROJECT_DIR / "layer2" / "artifacts"
DUPLICATE_REPORT = ARTIFACT_DIR / "music_duplicate_report.csv"
OUTPUT_DIR = PROJECT_DIR / "layer2" / "test_data" / "safe_arranged"
MANIFEST_PATH = OUTPUT_DIR / "manifest.csv"
SOURCE_EXCERPT_SECONDS = 240.0


def verified_nonduplicate_music() -> list[Path]:
    """Use only music files explicitly reported as not exact audio duplicates."""
    if not DUPLICATE_REPORT.is_file():
        raise SystemExit(
            f"Duplicate report is missing: {DUPLICATE_REPORT}. "
            "Run remove_duplicate_music.py first and review its report."
        )

    with DUPLICATE_REPORT.open("r", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    clean_paths = {
        str(Path(row["music_file"]).resolve())
        for row in rows
        if row.get("status") == "NO_EXACT_MATCH" and row.get("music_file")
    }
    files = [path for path in audio_files(MUSIC_DIR) if str(path.resolve()) in clean_paths]

    # Also guard against exact byte duplicates in case the fingerprint report
    # is stale or a file was added after it was generated.
    original_hashes: set[bytes] = set()
    import hashlib

    for path in audio_files(ORIGINAL_DIR):
        digest = hashlib.sha256()
        with path.open("rb") as audio_file:
            for block in iter(lambda: audio_file.read(1024 * 1024), b""):
                digest.update(block)
        original_hashes.add(digest.digest())

    unique: list[Path] = []
    for path in files:
        digest = hashlib.sha256()
        with path.open("rb") as audio_file:
            for block in iter(lambda: audio_file.read(1024 * 1024), b""):
                digest.update(block)
        if digest.digest() not in original_hashes:
            unique.append(path)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--songs", type=int, default=10, help="Number of distinct safe source tracks")
    parser.add_argument("--seed", type=int, default=20260930, help="Reproducible selection and transforms")
    args = parser.parse_args()
    if args.songs < 1:
        raise SystemExit("--songs must be at least 1")

    ffmpeg = find_ffmpeg()
    candidates = verified_nonduplicate_music()
    eligible: list[tuple[Path, float]] = []
    for path in candidates:
        try:
            length = duration_seconds(ffmpeg, path)
        except Exception as error:
            print(f"[skip] Could not read duration: {path.name}: {error}")
            continue
        if length >= MIN_QUERY_SECONDS:
            eligible.append((path, length))
    if len(eligible) < args.songs:
        raise SystemExit(f"Only {len(eligible)} eligible distinct safe tracks; requested {args.songs}.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("r", newline="", encoding="utf-8-sig") as file:
            old_rows = list(csv.DictReader(file))
    else:
        old_rows = []
    existing = {row.get("query_path", "") for row in old_rows}
    chosen = random.Random(args.seed).sample(eligible, args.songs)
    new_rows: list[dict[str, str]] = []

    for index, (source, source_duration) in enumerate(chosen, start=1):
        source_id = source.stem
        rng = random.Random(args.seed * 1000 + index)
        max_offset = max(0.0, source_duration - SOURCE_EXCERPT_SECONDS)
        offset = rng.uniform(0.0, max_offset) if max_offset else 0.0
        samples = decode_excerpt(ffmpeg, source, offset)

        outputs: list[tuple[str, Path, dict[str, object], float]] = []
        section_path = OUTPUT_DIR / f"{source_id}__section_edit__seed{args.seed}.wav"
        section_audio, section_params = make_section_edit(samples.copy(), rng)
        section_duration = save_wav(section_path, section_audio)
        outputs.append(("section_edit", section_path, section_params, section_duration))

        for case_type in CASE_TYPES[1:]:
            output_path = OUTPUT_DIR / f"{source_id}__{case_type}__seed{args.seed}.wav"
            params = make_filtered_case(
                ffmpeg,
                source,
                offset,
                output_path,
                case_type,
                random.Random(args.seed + index * 100 + len(outputs)),
            )
            output_duration = duration_seconds(ffmpeg, output_path)
            outputs.append((case_type, output_path, params, output_duration))

        for case_type, output_path, params, output_duration in outputs:
            resolved_output = str(output_path.resolve())
            if resolved_output in existing:
                raise SystemExit(f"Already recorded in manifest; choose another seed: {output_path.name}")
            if output_duration < MIN_QUERY_SECONDS:
                raise RuntimeError(f"Generated control is shorter than 3 minutes: {output_path}")
            new_rows.append({
                "query_path": resolved_output,
                "origin_path": str(source.resolve()),
                "source_track_id": source_id,
                "case_type": case_type,
                "source_offset_seconds": f"{offset:.3f}",
                "query_duration_seconds": f"{output_duration:.3f}",
                "seed": str(args.seed),
                "parameters_json": json.dumps(params, ensure_ascii=False),
                "label": "unverified_safe_control",
            })
            print(f"[{index}/{args.songs}] {case_type}: {output_path.name} ({output_duration / 60:.1f} min)")

    columns = [
        "query_path", "origin_path", "source_track_id", "case_type",
        "source_offset_seconds", "query_duration_seconds", "seed",
        "parameters_json", "label",
    ]
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(old_rows + new_rows)
    print(f"Generated {len(new_rows)} controls from {len(chosen)} distinct tracks.")
    print(f"Manifest: {MANIFEST_PATH}")
    print("These controls are not confirmed negatives until their melodies are reviewed.")


if __name__ == "__main__":
    main()
