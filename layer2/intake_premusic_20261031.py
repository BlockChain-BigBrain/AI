"""Audit a new premusic intake and archive unique files after exact-hash checks."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "premusic"
USED = ROOT / "premusic_used"
ARCHIVE = USED / "new_premusic_20261031"
REPORT = ROOT / "layer2" / "artifacts" / "premusic_intake_20261031.json"
PLAN = USED / "reorganization_plan_20261029.json"
MANIFEST = USED / "usage_manifest.csv"
EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    old = set(json.loads(PLAN.read_text(encoding="utf-8"))["remaining_filenames"])
    files = sorted(p for p in PRE.iterdir() if p.is_file() and p.suffix.lower() in EXT)
    if len(old) != 41 or not old.issubset({p.name for p in files}):
        raise RuntimeError("The 41 historical premusic files changed; stop before moving anything")
    candidates = [p for p in files if p.name not in old]
    known = [p for folder in (ROOT / "original_music", ROOT / "music") for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in EXT]
    known += [p for p in USED.rglob("*") if p.is_file() and p.suffix.lower() in EXT]
    known += [p for p in files if p.name in old]
    keepers: dict[str, Path] = {}
    for p in known:
        keepers.setdefault(digest(p), p)
    unique, duplicates = [], []
    for p in candidates:
        h = digest(p)
        survivor = keepers.get(h)
        if survivor:
            duplicates.append({"name": p.name, "sha256": h, "survivor": str(survivor)})
        else:
            if (ARCHIVE / p.name).exists():
                raise RuntimeError(f"Archive destination already exists: {p.name}")
            unique.append({"name": p.name, "sha256": h})
            keepers[h] = p
    report = {"date": "2026-10-31", "status": "planned", "candidates_seen": len(candidates),
              "exact_duplicates": duplicates, "unique_new": unique,
              "historical_unprocessed_count": len(old), "archive": str(ARCHIVE)}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.apply:
        if not candidates:
            raise RuntimeError("No new candidates to process")
        # Verify every source and keeper again before the first destructive operation.
        for row in duplicates:
            if digest(PRE / row["name"]) != row["sha256"] or digest(Path(row["survivor"])) != row["sha256"]:
                raise RuntimeError(f"Duplicate evidence changed: {row['name']}")
        for row in unique:
            if digest(PRE / row["name"]) != row["sha256"]:
                raise RuntimeError(f"Unique audio changed: {row['name']}")
        ARCHIVE.mkdir(parents=True, exist_ok=False)
        for row in unique:
            shutil.move(str(PRE / row["name"]), str(ARCHIVE / row["name"]))
        with MANIFEST.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            for row in unique:
                writer.writerow([str(PRE / row["name"]), str(ARCHIVE / row["name"]), row["sha256"], "new_premusic_batch_20261031"])
        # Every removed copy has a byte-identical retained survivor.
        for row in duplicates:
            survivor = Path(row["survivor"])
            if not survivor.is_file() and survivor.parent == PRE:
                survivor = ARCHIVE / survivor.name
            if digest(survivor) != row["sha256"]:
                raise RuntimeError(f"Retained copy changed: {row['name']}")
            row["survivor"] = str(survivor)
            (PRE / row["name"]).unlink()
        report["status"] = "completed"
        report["remaining_premusic"] = len([p for p in PRE.iterdir() if p.is_file() and p.suffix.lower() in EXT])
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates_seen": len(candidates),
                      "exact_duplicates": len(duplicates), "unique_new": len(unique)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
