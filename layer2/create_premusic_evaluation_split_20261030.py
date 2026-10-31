"""Create a deterministic, leakage-aware split for the 2026-10-30 premusic batch.

The 30 songs used to make transformed diagnostics are kept in a separate
variant-diagnostic partition. The remaining songs are split into calibration
and final-evaluation partitions by SHA-256, so the split is reproducible and
does not change production thresholds.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / ".runtime-tests" / "new-premusic-20261030" / "all_selection.json"
VARIANTS = ROOT / "layer2" / "artifacts" / "premusic_variants_20261030.json"
OUT = ROOT / "layer2" / "artifacts" / "premusic_evaluation_split_20261030.json"


def bucket(sha256: str) -> int:
    return int(hashlib.sha256(("premusic-split-v1:" + sha256).encode()).hexdigest()[:8], 16)


def main() -> None:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    variants = json.loads(VARIANTS.read_text(encoding="utf-8"))
    variant_hashes = {
        item["source_sha256"]
        for item in variants.get("rows", [])
        if item.get("source_sha256")
    }

    diagnostic = []
    eligible = []
    for item in selection["selected"]:
        row = {
            "name": item["name"],
            "sha256": item["sha256"],
            "archived_path": f"premusic_used/new_premusic_20261030/{item['name']}",
        }
        if item["sha256"] in variant_hashes:
            row["partition"] = "variant_diagnostic"
            diagnostic.append(row)
        else:
            eligible.append(row)

    # 60% calibration / 40% final evaluation, deterministic and independent
    # of the order in which files were downloaded or archived.
    eligible.sort(key=lambda row: (bucket(row["sha256"]), row["sha256"]))
    calibration_count = round(len(eligible) * 0.60)
    calibration = eligible[:calibration_count]
    evaluation = eligible[calibration_count:]
    for row in calibration:
        row["partition"] = "threshold_calibration"
    for row in evaluation:
        row["partition"] = "final_evaluation"

    result = {
        "date": "2026-10-30",
        "policy": {
            "production_thresholds_changed": False,
            "variant_sources_excluded_from_final_evaluation": True,
            "split_method": "sha256 deterministic hash; 60% calibration / 40% final evaluation",
            "final_evaluation_must_remain_unseen_until_lock": True,
        },
        "counts": {
            "total_unique_new": len(selection["selected"]),
            "variant_diagnostic": len(diagnostic),
            "threshold_calibration": len(calibration),
            "final_evaluation": len(evaluation),
        },
        "variant_diagnostic": diagnostic,
        "threshold_calibration": calibration,
        "final_evaluation": evaluation,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", **result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
