"""Evaluate a pre-frozen 50-work premusic candidate set without refitting policy.

The sample is a recording-identity-screened Pixabay negative diagnostic. None
of its 50 files has verified pure-AI creation provenance, so results must not
be reported as the independent AI-only false-positive rate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from scipy.stats import beta

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"
OUTPUT = ROOT / ".runtime-tests" / "premusic-holdout-20261029"


def resolve_audio(path: str, expected_sha256: str) -> Path:
    """Keep frozen historical paths immutable while honoring later relocation."""
    original = Path(path)
    if original.is_file() and digest(original) == expected_sha256:
        return original
    relocation = ROOT / "premusic_used" / "reorganization_plan_20261029.json"
    if relocation.is_file():
        plan = json.loads(relocation.read_text(encoding="utf-8"))
        matches = [m for m in plan["moves"] if m["original_path"] == path and m["sha256"] == expected_sha256]
        if len(matches) == 1:
            moved = Path(matches[0]["new_path"])
            if moved.is_file() and digest(moved) == expected_sha256:
                return moved
    raise RuntimeError(f"Frozen audio missing or changed: {original.name}")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def upper95(events: int, count: int):
    return float(beta.ppf(.95, events + 1, count - events)) if count and events < count else (1.0 if count else None)


def read_frozen():
    frozen = json.loads((OUTPUT / "frozen_selection.json").read_text(encoding="utf-8"))
    if frozen["status"] != "frozen_before_scores" or frozen["selected_count"] != 50:
        raise RuntimeError("Selection must be frozen at 50 works before evaluation")
    if not frozen["not_ai_only_validation"]:
        raise RuntimeError("This sample lacks pure-AI creation provenance")
    checks = [
        (ART / "ai_precision_policy.json", frozen["policy_sha256"]),
        (ROOT / "layer1" / "fingerprints_db.json", frozen["fingerprint_db_sha256"]),
        (ART / "control_collection_near_duplicate_audit.json", frozen["reference_audit_sha256"]),
        (ART / "pixabay_provenance" / "file_audit.csv", frozen["provenance_audit_sha256"]),
    ]
    for path, expected in checks:
        if digest(path) != expected:
            raise RuntimeError(f"Frozen input changed: {path.name}")
    for row in frozen["selected"]:
        resolve_audio(row["file"], row["sha256"])
    return frozen


def make_plan(frozen, ffmpeg: str):
    query_dir = OUTPUT / "queries"
    query_dir.mkdir(parents=True, exist_ok=True)
    plan_path = OUTPUT / "frozen_query_plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan["selection_sha256"] != digest(OUTPUT / "frozen_selection.json"):
            raise RuntimeError("Frozen selection changed since query plan creation")
        if len(plan["queries"]) != 200:
            raise RuntimeError("Expected 50 complete works and 150 crops")
        for item in plan["queries"]:
            resolve_audio(item["file"], item["sha256"])
        return plan
    queries = []
    for index, work in enumerate(frozen["selected"]):
        source = resolve_audio(work["file"], work["sha256"])
        duration = float(work["duration_seconds"])
        queries.append({"work_id": work["sha256"], "name": work["name"], "kind": "full",
            "file": str(source), "sha256": work["sha256"], "offset_seconds": 0.0})
        offsets = (0.0, max(0.0, (duration - 30) / 2), max(0.0, duration - 30))
        for kind, offset in zip(("start30", "middle30", "end30"), offsets):
            target = query_dir / f"{index:03d}__{kind}.wav"
            subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{offset:.4f}",
                "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(target)],
                check=True, capture_output=True)
            queries.append({"work_id": work["sha256"], "name": work["name"], "kind": kind,
                "file": str(target), "sha256": digest(target), "offset_seconds": offset})
        if (index + 1) % 10 == 0:
            print(f"[prepare crops] {index+1}/50 works", flush=True)
    plan = {"selection_sha256": digest(OUTPUT / "frozen_selection.json"), "policy_sha256": frozen["policy_sha256"],
            "scope": "ai_labeled", "works": 50, "queries": queries,
            "aggregation": "A work warns if any of its three selected 30-second crops warns; full song evaluated separately.",
            "note": "Three 30-second crops are not an exhaustive scan of every 30-second interval."}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def summarize(frozen, plan, results):
    by_work = defaultdict(dict)
    for item in results:
        by_work[item["work_id"]][item["kind"]] = item
    target = {"normal_warn": .10, "normal_hold": .02}
    summary = {"status": "completed" if len(results) == len(plan["queries"]) and all(r["state"] == "completed" for r in results) else "incomplete",
        "purpose": "premusic_normal_candidate_diagnostic", "sample_works": 50,
        "sample_selection_sha256": plan["selection_sha256"], "policy_sha256": frozen["policy_sha256"],
        "active_scope": "ai_labeled", "reference_tracks": 34,
        "pure_ai_creation_independently_verified": False,
        "query_count_expected": 200, "queries_recorded": len(results),
        "queries_failed": sum(r["state"] != "completed" for r in results),
        "decisions": dict(Counter(r["result"]["decision"] for r in results if r["state"] == "completed")),
        "limits": ["Pixabay source records do not establish pure-AI creation for these 50 works.",
            "Prior-used and bounded fingerprint-near recordings were excluded; absence of a match is not proof of independent rights or composition.",
            "The three 30-second excerpts per work are sampled positions, not an exhaustive sliding-window upload test.",
            "This negative-only sample cannot estimate positive recall.",
            "One-sided binomial bounds assume independent, representative works."]}
    for group, kinds in (("full", ("full",)), ("three_30s_work_union", ("start30", "middle30", "end30"))):
        complete = []
        failed_names = []
        for work in frozen["selected"]:
            records = [by_work[work["sha256"]].get(kind) for kind in kinds]
            if any(r is None or r["state"] != "completed" for r in records):
                failed_names.append(work["name"])
                continue
            complete.append((work["name"], records))
        warnings = [name for name, rs in complete if any(r["result"]["decision"] in ("WARN", "HOLD", "BLOCK") for r in rs)]
        holds = [name for name, rs in complete if any(r["result"]["decision"] in ("HOLD", "BLOCK") for r in rs)]
        n = len(complete)
        summary[group] = {"complete_works": n, "failed_or_unfinished_works": len(failed_names),
            "warning_works": len(warnings), "hold_or_block_works": len(holds),
            "warn_rate": len(warnings) / n if n else None, "hold_rate": len(holds) / n if n else None,
            "warn_one_sided_95_upper": upper95(len(warnings), n),
            "hold_one_sided_95_upper": upper95(len(holds), n),
            "warn_point_target_met": bool(n == 50 and len(warnings) / n <= target["normal_warn"]),
            "warn_upper_bound_target_met": bool(n == 50 and upper95(len(warnings), n) <= target["normal_warn"]),
            "hold_point_target_met": bool(n == 50 and len(holds) / n <= target["normal_hold"]),
            "hold_upper_bound_target_met": bool(n == 50 and upper95(len(holds), n) <= target["normal_hold"]),
            "warning_names": warnings, "hold_or_block_names": holds, "failed_or_unfinished_names": failed_names}
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-queries", type=int, default=0,
                        help="For controlled resumable execution; 0 means process the whole frozen plan.")
    args = parser.parse_args()
    frozen = read_frozen()
    sys.path.insert(0, str(ROOT / "api"))
    from engine import Engine
    import evaluate_retrieval_baseline as base
    base.FFMPEG_EXE = base.find_ffmpeg()
    if not base.FFMPEG_EXE:
        raise RuntimeError("ffmpeg is unavailable")
    plan = make_plan(frozen, base.FFMPEG_EXE)
    engine = Engine(scope="ai_labeled")
    if len(engine.groups) != 34 or engine.evaluation_scope != "ai_labeled":
        raise RuntimeError("Active model scope differs from the frozen 34-reference study")
    checkpoint = OUTPUT / "results.jsonl"
    existing = {}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            key = (record["work_id"], record["kind"])
            if key in existing:
                raise RuntimeError("Duplicate checkpoint result")
            existing[key] = record
    new = 0
    started = time.perf_counter()
    with checkpoint.open("a", encoding="utf-8") as stream:
        for number, query in enumerate(plan["queries"], 1):
            key = (query["work_id"], query["kind"])
            if key in existing:
                continue
            current_audio = resolve_audio(query["file"], query["sha256"])
            if digest(ART / "ai_precision_policy.json") != frozen["policy_sha256"]:
                raise RuntimeError("Policy changed during evaluation")
            try:
                result = engine.verify(current_audio, query["sha256"])
                record = {**query, "state": "completed", "result": result}
            except Exception as exc:
                record = {**query, "state": "failed", "error_type": type(exc).__name__, "error": str(exc)[:400]}
            existing[key] = record
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            new += 1
            elapsed = time.perf_counter() - started
            print(f"[premusic validation {number}/200] {query['kind']} {record['state']} "
                  f"new={new} avg_seconds={elapsed/new:.2f}", flush=True)
            summary = summarize(frozen, plan, list(existing.values()))
            (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.max_new_queries and new >= args.max_new_queries:
                break
    summary = summarize(frozen, plan, list(existing.values()))
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "query_count_expected", "queries_recorded", "queries_failed", "full", "three_30s_work_union")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
