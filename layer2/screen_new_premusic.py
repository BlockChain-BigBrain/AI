"""Screen newly added premusic files against prior use and existing audio."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from audit_control_collection import bit_error

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "premusic"
USED = ROOT / "premusic_used"
CACHE = ROOT / ".runtime-tests" / "collection-fingerprint-audit"
REPORT = ROOT / "layer2" / "artifacts" / "new_premusic_screen_20261029.json"
sys.path.insert(0, str(ROOT / "layer1"))
import upload_guard_api as gate


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def media_id(name: str) -> str | None:
    match = re.search(r"-(\d+)(?: \(\d+\))?\.[^.]+$", name)
    return match.group(1) if match else None


def main() -> None:
    old_plan = json.loads((USED / "reorganization_plan_20261029.json").read_text(encoding="utf-8"))
    old_names = set(old_plan["remaining_filenames"])
    current = sorted(PRE.glob("*.mp3"))
    current_names = {p.name for p in current}
    if not old_names <= current_names:
        raise RuntimeError("Previously unused premusic files are missing; inspect before screening")
    new = [p for p in current if p.name not in old_names]
    if not new:
        raise RuntimeError("No new premusic files")

    with (ROOT / "layer2/artifacts/pixabay_provenance/file_audit.csv").open(encoding="utf-8-sig", newline="") as stream:
        provenance = list(csv.DictReader(stream))
    with (USED / "usage_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        usage = list(csv.DictReader(stream))
    catalog = []
    for row in provenance:
        folder = row["folder"]
        if folder not in {"original_music", "music"} and not (folder == "premusic" and Path(row["file"]).name in old_names):
            continue
        path = ROOT / folder / Path(row["file"]).name
        if not path.is_file():
            raise RuntimeError(f"Reference missing: {path}")
        catalog.append({"path": path, "group": folder if folder != "premusic" else "old_unused", "sha256": row["sha256"], "media_id": media_id(path.name)})
    for row in usage:
        path = Path(row["new_path"])
        if not path.is_file():
            raise RuntimeError(f"Previously used file missing: {path}")
        catalog.append({"path": path, "group": "previously_used", "sha256": row["sha256"], "media_id": media_id(path.name)})
    for path in new:
        catalog.append({"path": path, "group": "new", "sha256": digest(path), "media_id": media_id(path.name)})

    for number, item in enumerate(catalog, 1):
        if digest(item["path"]) != item["sha256"]:
            raise RuntimeError(f"Reference or new audio changed since its recorded hash: {item['path']}")
        if number % 200 == 0:
            print(f"[hash verification] {number}/{len(catalog)}", flush=True)

    db = gate._load_db()
    original_fp = {}
    for row in db.values():
        path = Path(row.get("file_path", ""))
        if path.parent.resolve() == (ROOT / "original_music").resolve() and row.get("fingerprint_raw"):
            original_fp[path.name] = row["fingerprint_raw"]
    if len(original_fp) != 1000:
        raise RuntimeError(f"Expected 1000 original fingerprints, found {len(original_fp)}")
    for item in catalog:
        path = item["path"]
        if item["group"] == "original_music":
            record = {"fingerprint_raw": original_fp[path.name]}
        else:
            cache = CACHE / f'{item["sha256"]}.json'
            if cache.is_file():
                record = json.loads(cache.read_text(encoding="utf-8"))
            else:
                try:
                    record = gate.extract_raw_fingerprint(path)
                except ValueError as exc:
                    record = {"error": str(exc)}
                CACHE.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(record), encoding="utf-8")
        item["fp"] = np.asarray(record.get("fingerprint_raw", []), dtype=np.uint32)
        item["duration"] = record.get("duration")
        item["error"] = record.get("error")

    postings = defaultdict(list)
    for index, item in enumerate(catalog):
        for frame, value in enumerate(item["fp"]):
            postings[int(value >> 16)].append((index, frame))
    postings = {key: value for key, value in postings.items() if len(value) <= 2000}
    by_sha = defaultdict(list)
    by_media = defaultdict(list)
    for item in catalog:
        by_sha[item["sha256"]].append(item)
        if item["media_id"]:
            by_media[item["media_id"]].append(item)

    rows = []
    for number, query in enumerate((item for item in catalog if item["group"] == "new"), 1):
        fp = query["fp"]
        votes = Counter()
        for qi in range(0, len(fp), 8):
            for index, rj in postings.get(int(fp[qi] >> 16), ()):
                if catalog[index] is not query:
                    votes[(index, (rj - qi) // 3)] += 1
        best = {}
        for (index, bucket), count in votes.most_common(64):
            for offset in range(bucket * 3 - 2, bucket * 3 + 5):
                error, overlap = bit_error(fp, catalog[index]["fp"], offset)
                if index not in best or error < best[index][0]:
                    best[index] = (error, overlap, offset, count)
        matches = []
        for index, (error, overlap, offset, count) in sorted(best.items(), key=lambda pair: pair[1][0]):
            if error < .18 and overlap >= 240:
                ref = catalog[index]
                matches.append({"group": ref["group"], "file": str(ref["path"]), "bit_error": error,
                                "overlap_frames": overlap, "offset_frames": offset, "seed_votes": count})
        same_sha = [{"group": r["group"], "file": str(r["path"])} for r in by_sha[query["sha256"]] if r is not query]
        same_media = [{"group": r["group"], "file": str(r["path"])} for r in by_media[query["media_id"]] if r is not query] if query["media_id"] else []
        rows.append({"file": str(query["path"]), "sha256": query["sha256"], "media_id": query["media_id"],
                     "duration_seconds": query["duration"], "error": query["error"],
                     "same_sha": same_sha, "same_media_id": same_media, "fingerprint_matches": matches})
        print(f"[screen {number}/{len(new)}] {query['path'].name}: exact={len(same_sha)} media={len(same_media)} fingerprint={len(matches)}", flush=True)
    report = {"date": "2026-10-29", "new_files": len(new), "previously_used_files": len(usage),
              "existing_unused_files": len(old_names), "reference_files": len(catalog) - len(new),
              "method": "SHA-256, media ID, and aligned Chromaprint BER < 0.18 with >=240 frames; fingerprint search is bounded",
              "rows": rows}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"new_files": len(new), "same_sha": sum(bool(r["same_sha"]) for r in rows),
                      "same_media_id": sum(bool(r["same_media_id"]) for r in rows),
                      "fingerprint_matches": sum(bool(r["fingerprint_matches"]) for r in rows),
                      "unscorable": sum(bool(r["error"]) for r in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
