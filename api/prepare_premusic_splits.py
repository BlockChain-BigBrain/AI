"""Create deterministic train/validation/test splits for unused premusic."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREMUSIC = ROOT / "premusic_used"
SELECTION = ROOT / ".runtime-tests/premusic-20261101-location/selection.json"
DUPLICATES = ROOT / "api/runtime/premusic_duplicate_report.json"
OUT = ROOT / "api/runtime/premusic_remaining_split.json"

def key(name):
    return int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:12], 16)

def main():
    selected = {row["name"] for row in json.loads(SELECTION.read_text("utf-8"))["selected"]}
    duplicate_paths = {path.replace("/", "\\")
                       for path in json.loads(DUPLICATES.read_text("utf-8"))["duplicatePaths"]}
    files = [p for p in PREMUSIC.rglob("*") if p.is_file() and p.name not in selected
             and str(p.relative_to(ROOT)).replace("/", "\\") not in duplicate_paths]
    files.sort(key=lambda p: key(str(p.relative_to(ROOT))))
    n = len(files); train_end = round(n * .60); val_end = round(n * .80)
    rows = []
    for i, path in enumerate(files):
        split = "train" if i < train_end else "validation" if i < val_end else "test"
        rows.append({"path": str(path), "name": path.name, "split": split,
                     "contentKey": hashlib.sha256((path.name + str(path.stat().st_size)).encode()).hexdigest()})
    output = {"method": "deterministic SHA-256 path ordering after exact deduplication",
              "counts": {part: sum(row["split"] == part for row in rows)
                         for part in ("train", "validation", "test")},
              "rows": rows}
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"counts": output["counts"], "excludedSelected": len(selected),
                      "excludedExactDuplicates": len(duplicate_paths)}, ensure_ascii=False))

if __name__ == "__main__": main()
