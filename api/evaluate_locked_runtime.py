"""Run the frozen API engine on the existing source-group test partition.

No thresholds are fitted here. A JSONL checkpoint allows a long run to resume.
The historic safe controls are used as labeled in the original experiment; this
does not substitute for new, independently reviewed normal works.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / ".deps"))
from engine import Engine
from independent_features import FEATURE_VERSION

ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "layer2" / "artifacts" / "top3_aggregation_details.csv"
DEFAULT_OUT = ROOT / "api" / "runtime" / "locked_evaluation"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="Smoke test only; 0 runs all held-out rows")
    parser.add_argument("--start", type=int, default=0, help="Zero-based start for a disjoint shard")
    parser.add_argument("--end", type=int, default=0, help="Exclusive end for a disjoint shard")
    args = parser.parse_args()
    with DETAILS.open(newline="", encoding="utf-8-sig") as stream:
        rows = [row for row in csv.DictReader(stream)
                if row["aggregation"] == "seg_top3_centered" and row["split"] == "test"
                and row["dataset"] in {"positive", "safe_music"}]
    if args.limit:
        rows = rows[:args.limit]
    if args.start or args.end:
        rows = rows[args.start:args.end or None]
    if not rows:
        raise RuntimeError("No frozen held-out rows found")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / "results.jsonl"
    existing = {}
    if checkpoint.exists():
        for line in checkpoint.read_text("utf-8").splitlines():
            entry = json.loads(line)
            existing[entry["querySha256"]] = entry
    engine = Engine()
    frozen = {"scoreVersion": engine.score_version, "thresholds": engine.thresholds,
              "corpusVersion": engine.corpus_version, "detailSha256": sha256(DETAILS),
              "featureVersion": FEATURE_VERSION,
              "engineSha256": sha256(ROOT / "api" / "engine.py"),
              "featureSha256": sha256(ROOT / "api" / "independent_features.py")}
    lock_file = out / "lock.json"
    if lock_file.exists() and json.loads(lock_file.read_text("utf-8")) != frozen:
        raise RuntimeError("Frozen score, thresholds, corpus, or input manifest changed")
    lock_file.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    for index, row in enumerate(rows, 1):
        path = Path(row["file"])
        if not path.is_file():
            raise FileNotFoundError(path)
        file_hash = sha256(path)
        if file_hash in existing:
            continue
        started = time.perf_counter()
        result = engine.verify(path, file_hash)
        if result["scoreVersion"] != frozen["scoreVersion"] or result["thresholds"] != frozen["thresholds"]:
            raise RuntimeError("Runtime policy drifted during locked evaluation")
        entry = {"querySha256": file_hash, "file": str(path), "dataset": row["dataset"],
                 "groupId": row["group_id"], "queryKind": row["query_kind"],
                 "expectedTrackId": row["expected_track_id"], "decision": result["decision"],
                 "score": result["similarityScore"], "top3": result["similarTracks"],
                 "processingSeconds": round(time.perf_counter() - started, 3)}
        with checkpoint.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        existing[file_hash] = entry
        print(f"{index}/{len(rows)} {entry['decision']} {path.name}", flush=True)
    selected = [existing[sha256(Path(row["file"]))] for row in rows]
    positive = [row for row in selected if row["dataset"] == "positive"]
    safe = [row for row in selected if row["dataset"] == "safe_music"]
    summary = {"locked": not bool(args.limit or args.start or args.end), "rows": len(selected), "positive": len(positive),
               "safe": len(safe), "positiveWarnOrHold": sum(row["decision"] in {"WARN", "HOLD"} for row in positive),
               "positiveExpectedInTop3": sum(row["expectedTrackId"] in
                   [candidate["trackId"] for candidate in row["top3"]] for row in positive),
               "safeWarnOrHold": sum(row["decision"] in {"WARN", "HOLD"} for row in safe),
               "safeHold": sum(row["decision"] == "HOLD" for row in safe),
               "featureEvidenceComplete": all(all("featureEvidence" in candidate
                   for candidate in row["top3"]) for row in selected), "frozen": frozen}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
