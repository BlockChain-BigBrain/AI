"""Freeze 50 unused premusic normal candidates before looking at model scores.

This is a bounded recording-identity screen, not AI-generation certification or
proof that different recordings have different compositions/rights holders.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from audit_control_collection import bit_error

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"
OUTPUT = ROOT / ".runtime-tests" / "premusic-holdout-20261029"
CACHE = ROOT / ".runtime-tests" / "collection-fingerprint-audit"
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}
SEED = "premusic-holdout-20261029-v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def rows_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def previous_audio_names_and_hashes():
    """Use actual evaluated manifests; audit inventories do not count as use."""
    names, hashes, files = set(), set(), []
    for manifest in sorted((ROOT / "layer2" / "test_data").rglob("manifest.json")):
        content = json.loads(manifest.read_text(encoding="utf-8-sig"))
        files.append(str(manifest.relative_to(ROOT)))

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("sha256", "source_sha256") and isinstance(item, str) and len(item) == 64:
                        hashes.add(item.lower())
                    elif key in ("file", "source_file", "source_path", "audio_path") and isinstance(item, str):
                        path = Path(item)
                        if path.parent.name.casefold() == "premusic":
                            names.add(path.name.casefold())
                    elif isinstance(item, (dict, list)):
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(content)
    return names, hashes, files


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    audit = json.loads((ART / "control_collection_near_duplicate_audit.json").read_text(encoding="utf-8"))
    fingerprint_db = ROOT / "layer1" / "fingerprints_db.json"
    if digest(fingerprint_db) != audit["fingerprint_index_sha256"]:
        raise RuntimeError("The reference fingerprint index changed after the original near-duplicate audit")
    provenance = rows_csv(ART / "pixabay_provenance" / "file_audit.csv")
    if len(provenance) != 1500:
        raise RuntimeError("Expected provenance inventory for 1000+300+200 audio files")
    by_folder_name = {(r["folder"], Path(r["file"]).name.casefold()): r for r in provenance}
    if len(by_folder_name) != 1500:
        raise RuntimeError("Duplicate folder/filename in the provenance inventory")

    current = {}
    for folder in ("original_music", "music", "premusic"):
        paths = sorted(p for p in (ROOT / folder).iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)
        expected = {"original_music": 1000, "music": 300, "premusic": 200}[folder]
        if len(paths) != expected:
            raise RuntimeError(f"{folder} has {len(paths)} audio files instead of {expected}")
        for number, path in enumerate(paths, 1):
            row = by_folder_name[(folder, path.name.casefold())]
            actual = digest(path)
            if actual != row["sha256"].lower():
                raise RuntimeError(f"Audio hash changed since provenance audit: {folder}/{path.name}")
            current[(folder, path.name.casefold())] = {"path": path, "sha256": actual, "source": row}
            if number % 100 == 0:
                print(f"[hash check] {folder} {number}/{expected}", flush=True)

    names_used, hashes_used, manifests = previous_audio_names_and_hashes()
    # Current original/music identities are already in the indexed/tuning pool.
    used_hashes = hashes_used | {r["sha256"] for (folder, _), r in current.items() if folder != "premusic"}
    used_media = {r["source"]["media_id_candidate"] for (folder, _), r in current.items()
                  if folder != "premusic" and r["source"]["media_id_candidate"]}
    same_sha = defaultdict(set)
    same_media = defaultdict(set)
    for (folder, name), entry in current.items():
        same_sha[entry["sha256"]].add(f"{folder}/{name}")
        media = entry["source"]["media_id_candidate"]
        if media:
            same_media[media].add(f"{folder}/{name}")

    old_near = defaultdict(list)
    old_suspect = defaultdict(list)
    for pair in audit["near_identical_pairs"]:
        if pair["folder"] == "premusic":
            old_near[Path(pair["file"]).name.casefold()].append(Path(pair["reference"]).name)
    for pair in audit["fingerprint_suspect_pairs"]:
        if pair["folder"] == "premusic" and pair["fingerprint_bit_error"] < .18:
            old_suspect[Path(pair["file"]).name.casefold()].append(Path(pair["reference"]).name)

    # Screen the 200 premusic files against all 300 music and against each other.
    fp_data = []
    for (folder, name), entry in current.items():
        if folder not in ("music", "premusic"):
            continue
        cache = CACHE / f'{entry["sha256"]}.json'
        if not cache.exists():
            raise RuntimeError(f"Fingerprint audit cache absent for {folder}/{name}; rerun audit_control_collection.py")
        record = json.loads(cache.read_text(encoding="utf-8"))
        fp_data.append({"folder": folder, "name": name, "fp": np.asarray(record.get("fingerprint_raw", []), dtype=np.uint32),
                        "duration": float(record.get("duration", 0)), "error": record.get("error", "")})
    postings = defaultdict(list)
    for index, record in enumerate(fp_data):
        for frame, value in enumerate(record["fp"]):
            postings[int(value >> 16)].append((index, frame))
    postings = {key: value for key, value in postings.items() if len(value) <= 2000}
    close = defaultdict(list)
    for number, query in enumerate((r for r in fp_data if r["folder"] == "premusic"), 1):
        fp = query["fp"]
        if not len(fp):
            close[query["name"]].append({"reason": "unscorable_fingerprint"})
            continue
        votes = Counter()
        for qi in range(0, len(fp), 8):
            for index, rj in postings.get(int(fp[qi] >> 16), ()):
                if fp_data[index]["folder"] == "premusic" and fp_data[index]["name"] == query["name"]:
                    continue
                votes[(index, (rj - qi) // 3)] += 1
        best = {}
        for (index, bucket), count in votes.most_common(48):
            for offset in range(bucket * 3 - 2, bucket * 3 + 5):
                error, overlap = bit_error(fp, fp_data[index]["fp"], offset)
                if index not in best or error < best[index][0]:
                    best[index] = (error, overlap, offset, count)
        for index, (error, overlap, offset, count) in best.items():
            if error < .18 and overlap >= 240:
                ref = fp_data[index]
                close[query["name"]].append({"folder": ref["folder"], "file": ref["name"],
                    "bit_error": error, "overlap_frames": overlap, "offset_frames": offset, "seed_votes": count})
                if ref["folder"] == "premusic":
                    close[ref["name"]].append({"folder": "premusic", "file": query["name"],
                        "bit_error": error, "overlap_frames": overlap, "offset_frames": -offset, "seed_votes": count})
        if number % 25 == 0:
            print(f"[music+premusic recording screen] {number}/200", flush=True)

    audit_rows = []
    for (folder, name), entry in sorted(current.items()):
        if folder != "premusic":
            continue
        source = entry["source"]
        media = source["media_id_candidate"]
        reasons = []
        if name in names_used or entry["sha256"] in hashes_used:
            # Manifests also list items excluded before scoring; keep those out
            # conservatively without calling them previously evaluated.
            reasons.append("previous_manifest_reference_including_exclusions")
        if entry["sha256"] in used_hashes:
            reasons.append("exact_sha_match_used_catalog_or_manifest")
        if media and media in used_media:
            reasons.append("same_pixabay_media_id_as_original_or_music")
        if len(same_sha[entry["sha256"]]) > 1:
            reasons.append("duplicate_file_sha_within_collections")
        if media and len(same_media[media]) > 1:
            reasons.append("duplicate_pixabay_media_id_within_collections")
        if old_near[name]:
            reasons.append("near_identical_to_original_music")
        elif old_suspect[name]:
            reasons.append("fingerprint_suspect_to_original_music")
        if close[name]:
            reasons.append("fingerprint_suspect_to_music_or_premusic")
        record = next((r for r in fp_data if r["folder"] == "premusic" and r["name"] == name), None)
        if record is None or record["error"] or record["duration"] < 90:
            reasons.append("audio_unscorable_or_shorter_than_90_seconds")
        audit_rows.append({"file": str(entry["path"]), "name": name, "sha256": entry["sha256"],
            "media_id": media, "source_url": source["source_url"], "source_status": source["status"],
            "pure_ai_creation_verified": source["pure_ai_creation_verified"],
            "duration_seconds": record["duration"] if record else None,
            "reasons": sorted(set(reasons)), "original_near_matches": old_near[name],
            "original_fingerprint_suspects": old_suspect[name], "music_or_premusic_suspects": close[name]})
    eligible = [r for r in audit_rows if not r["reasons"]]
    eligible.sort(key=lambda r: hashlib.sha256((SEED + r["sha256"]).encode()).hexdigest())
    if len(eligible) < 50:
        raise RuntimeError(f"Only {len(eligible)} eligible unused premusic files; cannot freeze 50")
    selected = eligible[:50]
    policy = ART / "ai_precision_policy.json"
    frozen = {"date": "2026-10-29", "status": "frozen_before_scores", "purpose": "premusic_normal_candidate_diagnostic",
        "not_ai_only_validation": True, "selection_seed": SEED, "selection_rule": "SHA-256(seed + file_sha256) ascending among eligible",
        "selected_count": len(selected), "policy_sha256": digest(policy), "policy_file": str(policy),
        "fingerprint_db_sha256": digest(fingerprint_db),
        "reference_audit_sha256": digest(ART / "control_collection_near_duplicate_audit.json"),
        "provenance_audit_sha256": digest(ART / "pixabay_provenance" / "file_audit.csv"),
        "used_manifests": manifests,
        "screen_limits": ["The reference-audit screen is bounded by its fingerprint candidates and excludes substantial edits/tempo shifts.",
            "BER<0.18 and >=240 aligned frames is a conservative exclusion, not a proof of copyright or AI origin.",
            "Pixabay source labels do not certify pure AI generation."],
        "eligible_count": len(eligible), "excluded_count": len(audit_rows) - len(eligible),
        "reason_counts": dict(Counter(reason for row in audit_rows for reason in row["reasons"])),
        "selected": [{key: r[key] for key in ("file", "name", "sha256", "media_id", "source_url", "source_status", "pure_ai_creation_verified", "duration_seconds")} for r in selected]}
    audit_path = OUTPUT / "screen_all_200.json"
    frozen_path = OUTPUT / "frozen_selection.json"
    audit_path.write_text(json.dumps(audit_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if frozen_path.exists():
        if json.loads(frozen_path.read_text(encoding="utf-8")) != frozen:
            raise RuntimeError("An earlier selection was frozen. Keep it unchanged and inspect the audit")
    else:
        frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: frozen[key] for key in ("status", "selected_count", "eligible_count", "excluded_count", "reason_counts", "not_ai_only_validation")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
