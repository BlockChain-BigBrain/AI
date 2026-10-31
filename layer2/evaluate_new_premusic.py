"""Evaluate newly added, recording-screened premusic songs with the fixed AI policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from scipy.stats import beta

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"
OUT = ROOT / ".runtime-tests" / "new-premusic-20261029"
SCREEN = ART / "new_premusic_screen_20261029.json"
ARCHIVE = ROOT / "premusic_used" / "new_premusic_20261029"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def resolve_audio(path: str, expected_sha: str) -> Path:
    original = Path(path)
    for candidate in (original, ARCHIVE / original.name):
        if candidate.is_file() and digest(candidate) == expected_sha:
            return candidate
    raise RuntimeError(f"Audio missing or changed: {original.name}")


def selection() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    screen = json.loads(SCREEN.read_text(encoding="utf-8"))
    chosen = []
    for row in screen["rows"]:
        if row["same_sha"] or row["same_media_id"] or row["fingerprint_matches"] or row["error"]:
            continue
        resolve_audio(row["file"], row["sha256"])
        if not row["duration_seconds"] or float(row["duration_seconds"]) < 90:
            continue
        chosen.append({key: row[key] for key in ("file", "sha256", "media_id", "duration_seconds")})
    frozen = {"date": "2026-10-29", "purpose": "new_premusic_normal_candidate_diagnostic",
              "screen_sha256": digest(SCREEN), "policy_sha256": digest(ART / "ai_precision_policy.json"),
              "selected_count": len(chosen), "selected": chosen,
              "selection_rule": "No exact SHA, media ID, or bounded fingerprint match; duration >=90 seconds",
              "scope": "ai_labeled", "pure_ai_origin_independently_verified": False}
    path = OUT / "frozen_selection.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != frozen:
            raise RuntimeError("Frozen selection changed")
    else:
        path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    return frozen


def query_plan(frozen: dict, ffmpeg: str) -> dict:
    path = OUT / "query_plan.json"
    if path.exists():
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan["selection_sha256"] != digest(OUT / "frozen_selection.json"):
            raise RuntimeError("Selection changed since query generation")
        return plan
    queries = []
    (OUT / "queries").mkdir(exist_ok=True)
    for index, row in enumerate(frozen["selected"]):
        source = resolve_audio(row["file"], row["sha256"])
        queries.append({"work_id": row["sha256"], "name": source.name,
                        "kind": "full", "file": str(source), "sha256": row["sha256"]})
        duration = float(row["duration_seconds"])
        offsets = (0.0, (duration - 30) / 2, duration - 30)
        for kind, offset in zip(("start30", "middle30", "end30"), offsets):
            target = OUT / "queries" / f"{index:03d}_{kind}.wav"
            subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{offset:.4f}",
                            "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(target)],
                           check=True, capture_output=True)
            queries.append({"work_id": row["sha256"], "name": source.name,
                            "kind": kind, "file": str(target), "sha256": digest(target),
                            "offset_seconds": offset})
        print(f"[prepare] {index + 1}/{len(frozen['selected'])}", flush=True)
    plan = {"selection_sha256": digest(OUT / "frozen_selection.json"),
            "policy_sha256": frozen["policy_sha256"], "query_count": len(queries), "queries": queries,
            "crops": "Start, middle, and end 30-second excerpts; not an exhaustive scan"}
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def summarize(frozen: dict, plan: dict, results: dict) -> dict:
    by_work = defaultdict(dict)
    for (work_id, kind), row in results.items():
        by_work[work_id][kind] = row
    groups = {}
    for group, kinds in (("full", ("full",)), ("three_30s_work_union", ("start30", "middle30", "end30"))):
        complete = []
        for work in frozen["selected"]:
            rows = [by_work[work["sha256"]].get(kind) for kind in kinds]
            if all(row is not None and row["state"] == "completed" for row in rows):
                complete.append((Path(work["file"]).name, rows))
        warnings = [name for name, rows in complete if any(row["result"]["decision"] in {"WARN", "HOLD", "BLOCK"} for row in rows)]
        holds = [name for name, rows in complete if any(row["result"]["decision"] in {"HOLD", "BLOCK"} for row in rows)]
        n = len(complete)
        groups[group] = {"complete_works": n, "warning_works": len(warnings), "hold_or_block_works": len(holds),
                         "warning_rate": len(warnings) / n if n else None,
                         "warning_one_sided_95_upper": float(beta.ppf(.95, len(warnings) + 1, n - len(warnings))) if n and len(warnings) < n else (1.0 if n else None),
                         "warning_names": warnings, "hold_or_block_names": holds}
    return {"date": "2026-10-29", "status": "completed" if len(results) == plan["query_count"] and all(r["state"] == "completed" for r in results.values()) else "incomplete",
            "purpose": frozen["purpose"], "selected_works": len(frozen["selected"]),
            "query_count": plan["query_count"], "queries_recorded": len(results),
            "failed_queries": sum(r["state"] == "failed" for r in results.values()),
            "full": groups["full"], "three_30s_work_union": groups["three_30s_work_union"],
            "pure_ai_origin_independently_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-queries", type=int, default=0)
    args = parser.parse_args()
    frozen = selection()
    sys.path.insert(0, str(ROOT / "api"))
    from engine import Engine
    import evaluate_retrieval_baseline as base
    ffmpeg = base.find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is unavailable")
    plan = query_plan(frozen, ffmpeg)
    engine = Engine(scope="ai_labeled")
    if len(engine.groups) != 34 or engine.evaluation_scope != "ai_labeled":
        raise RuntimeError("AI evaluation scope changed")
    checkpoint = OUT / "results.jsonl"
    results = {}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["work_id"], row["kind"])
            if key in results:
                raise RuntimeError("Duplicate checkpoint row")
            results[key] = row
    added = 0
    with checkpoint.open("a", encoding="utf-8") as stream:
        for index, query in enumerate(plan["queries"], 1):
            key = (query["work_id"], query["kind"])
            if key in results:
                continue
            audio = resolve_audio(query["file"], query["sha256"]) if query["kind"] == "full" else Path(query["file"])
            if not audio.is_file() or digest(audio) != query["sha256"]:
                raise RuntimeError(f"Query audio missing or changed: {audio}")
            if digest(ART / "ai_precision_policy.json") != frozen["policy_sha256"]:
                raise RuntimeError("Evaluation policy changed")
            try:
                row = {**query, "state": "completed", "result": engine.verify(audio, query["sha256"])}
            except Exception as exc:
                row = {**query, "state": "failed", "error_type": type(exc).__name__, "error": str(exc)[:400]}
            results[key] = row
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            added += 1
            print(f"[evaluate {index}/{plan['query_count']}] {query['name']} {query['kind']} {row['state']}", flush=True)
            (OUT / "summary.json").write_text(json.dumps(summarize(frozen, plan, results), ensure_ascii=False, indent=2), encoding="utf-8")
            if args.max_new_queries and added >= args.max_new_queries:
                break
    summary = summarize(frozen, plan, results)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("status", "selected_works", "queries_recorded", "failed_queries", "full", "three_30s_work_union")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
