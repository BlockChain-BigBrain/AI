"""Identify the newly added premusic batch and remove only byte-identical duplicates."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "premusic"
USED = ROOT / "premusic_used"
ART = ROOT / "layer2" / "artifacts"
OLD_PLAN = USED / "reorganization_plan_20261029.json"
REPORT = ART / "new_premusic_batch_20261030.json"
SELECTED = ROOT / ".runtime-tests" / "new-premusic-20261030" / "selection.json"
ALL_SELECTED = ROOT / ".runtime-tests" / "new-premusic-20261030" / "all_selection.json"
AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    old = json.loads(OLD_PLAN.read_text(encoding="utf-8"))
    old_unused = set(old["remaining_filenames"])
    current = sorted(p for p in PRE.iterdir() if p.is_file() and p.suffix.lower() in AUDIO)
    new = [p for p in current if p.name not in old_unused]
    if len(old_unused) != 41 or len(new) not in (179, 181):
        raise RuntimeError(f"Expected 41 old unused and 179/181 new files; got {len(old_unused)} and {len(new)}")
    already_deleted = len(new) == 179

    # Existing catalog and used archives are protected keepers. A new file is
    # deleted only when an identical byte copy already exists there or an
    # earlier new file is retained.
    existing = []
    for folder in ("original_music", "music"):
        existing.extend(p for p in (ROOT / folder).iterdir() if p.is_file() and p.suffix.lower() in AUDIO)
    existing.extend(p for p in USED.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO)
    by_sha = defaultdict(list)
    for path in existing:
        by_sha[sha(path)].append(path)
    kept = []
    deleted = []
    if already_deleted:
        # The prior run completed the destructive part before its final
        # partition assertion. Recover the two visible duplicate pairs in the
        # audit from the surviving suffixed copies.
        for path in new:
            if not path.name.endswith(" (1).mp3"):
                continue
            base = path.with_name(path.name.replace(" (1).mp3", ".mp3"))
            if base.is_file():
                continue
            digest = sha(path)
            deleted.append({"path": str(base), "sha256": digest, "retained_copy": str(path),
                            "reason": "exact_sha_match_new_batch", "already_deleted": True})
        if len(deleted) != 2:
            raise RuntimeError("Expected two already-applied duplicate deletions")
    for path in new:
        if already_deleted and any(item["path"] == str(path) for item in deleted):
            continue
        digest = sha(path)
        if by_sha[digest]:
            deleted.append({"path": str(path), "sha256": digest, "retained_copy": str(by_sha[digest][0]), "reason": "exact_sha_match_existing"})
            continue
        if any(item["sha256"] == digest for item in kept):
            prior = next(item for item in kept if item["sha256"] == digest)
            deleted.append({"path": str(path), "sha256": digest, "retained_copy": prior["path"], "reason": "exact_sha_match_new_batch"})
            continue
        kept.append({"path": str(path), "name": path.name, "sha256": digest})

    for item in deleted:
        path = Path(item["path"])
        retained = Path(item["retained_copy"])
        if not retained.is_file() or sha(retained) != item["sha256"]:
            raise RuntimeError(f"Identical retained copy missing: {retained}")
        if not item.get("already_deleted") and sha(path) != item["sha256"]:
            raise RuntimeError(f"Candidate changed: {path}")
        if path.is_file():
            path.unlink()

    # Select 30 stable sources for the two requested synthetic variant families.
    kept.sort(key=lambda item: hashlib.sha256(("premusic-variants-20261030" + item["sha256"]).encode()).hexdigest())
    selected = kept[:30]
    if len(kept) != 179 or len(selected) != 30:
        raise RuntimeError(f"Expected 179 unique new files and 30 variant sources; got {len(kept)}")
    SELECTED.parent.mkdir(parents=True, exist_ok=True)
    selection = {"date": "2026-10-30", "new_files_seen": 181, "exact_duplicates_deleted": len(deleted),
                 "unique_new_files": len(kept), "variant_source_count": len(selected),
                 "selected": selected, "selection_seed": "premusic-variants-20261030"}
    SELECTED.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    ALL_SELECTED.write_text(json.dumps({**selection, "selected": kept}, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT.write_text(json.dumps({**selection, "deleted": deleted}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"new_files_seen": 181, "exact_duplicates_deleted": len(deleted),
                      "unique_new_files": len(kept), "variant_source_count": len(selected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
