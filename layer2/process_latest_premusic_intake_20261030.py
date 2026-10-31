"""Deduplicate and archive the latest premusic intake without touching older holdout files."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREMUSIC = ROOT / "premusic"
USED = ROOT / "premusic_used"
OLD_PLAN = USED / "reorganization_plan_20261029.json"
OUT_DIR = USED / "new_premusic_20261030b"
REPORT = ROOT / "layer2" / "artifacts" / "premusic_intake_20261030b.json"
MANIFEST = USED / "usage_manifest.csv"

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> None:
    old = json.loads(OLD_PLAN.read_text(encoding="utf-8"))
    old_remaining = set(old["remaining_filenames"])
    files = sorted(PREMUSIC.glob("*.mp3"))
    candidates = [p for p in files if p.name not in old_remaining]
    existing_hashes: dict[str, str] = {}
    for p in list(USED.rglob("*.mp3")) + [p for p in files if p.name in old_remaining]:
        existing_hashes.setdefault(sha(p), str(p))
    seen: dict[str, Path] = {}
    deleted = []
    kept = []
    for p in candidates:
        digest = sha(p)
        survivor = existing_hashes.get(digest) or seen.get(digest)
        if survivor is not None:
            p.unlink()
            deleted.append({"name": p.name, "sha256": digest, "survivor": str(survivor)})
        else:
            seen[digest] = p
            kept.append((p, digest))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    moved = []
    for p, digest in kept:
        target = OUT_DIR / p.name
        shutil.move(str(p), str(target))
        moved.append({"name": p.name, "sha256": digest, "path": str(target)})
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for item in moved:
            writer.writerow([str(PREMUSIC / item["name"]), item["path"], item["sha256"], "new_premusic_batch_20261030b"])
    report = {"date": "2026-10-30", "status": "completed", "candidate_files_seen": len(candidates), "exact_duplicates_deleted": deleted, "unique_files_moved": moved, "premusic_remaining": len(list(PREMUSIC.glob('*.mp3'))), "destination": str(OUT_DIR)}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_files_seen": len(candidates), "exact_duplicates_deleted": len(deleted), "unique_files_moved": len(moved), "premusic_remaining": report["premusic_remaining"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
