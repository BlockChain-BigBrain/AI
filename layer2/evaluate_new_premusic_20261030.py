"""Evaluate the 179 unique new premusic works with frozen thresholds.

The 30-second positions are recorded separately so warning location can be
measured without changing the production policy.
"""
from __future__ import annotations

import hashlib
import json
import argparse
import sys
from collections import defaultdict
from pathlib import Path

from scipy.stats import beta

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"
OUT = ROOT / ".runtime-tests" / "new-premusic-20261030"
SEL = OUT / "all_selection.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_plan(frozen, ffmpeg):
    plan_path = OUT / "query_plan_all.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan["selection_sha256"] != digest(SEL):
            raise RuntimeError("Selection changed after query planning")
        return plan
    import subprocess
    queries = []
    qdir = OUT / "queries"
    qdir.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(frozen["selected"], 1):
        source = Path(item["path"])
        queries.append({"work_id": item["sha256"], "name": source.name, "kind": "full",
                        "file": str(source), "sha256": item["sha256"]})
        # Use fixed start/middle/end 30s positions for location analysis.
        for kind, offset in zip(("start30", "middle30", "end30"), (0.0, 30.0, 60.0)):
            target = qdir / f"{i:03d}_{kind}.wav"
            subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{offset:.3f}", "-i", str(source),
                            "-t", "30", "-ac", "1", "-ar", "22050", str(target)], check=True, capture_output=True)
            queries.append({"work_id": item["sha256"], "name": source.name, "kind": kind,
                            "file": str(target), "sha256": digest(target), "offset_seconds": offset})
        if i % 25 == 0:
            print(f"[prepare {i}/{len(frozen['selected'])}]", flush=True)
    plan = {"selection_sha256": digest(SEL), "policy_sha256": frozen["policy_sha256"],
            "query_count": len(queries), "queries": queries}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def summarize(plan, results):
    by_work = defaultdict(dict)
    for key, row in results.items():
        by_work[key[0]][key[1]] = row
    names = {key[0]: next(row["name"] for row in results.values() if row["work_id"] == key[0]) for key in results}
    complete = [work for work in by_work if by_work[work].get("full", {}).get("state") == "completed"]
    warning = lambda row: row["result"]["decision"] in {"WARN", "HOLD", "BLOCK"}
    positions = {kind: {"complete": 0, "warnings": 0, "warning_names": []} for kind in ("start30", "middle30", "end30")}
    for work in complete:
        for kind in positions:
            row = by_work[work].get(kind)
            if row and row["state"] == "completed":
                positions[kind]["complete"] += 1
                if warning(row):
                    positions[kind]["warnings"] += 1
                    positions[kind]["warning_names"].append(names[work])
    full_warnings = [names[work] for work in complete if warning(by_work[work]["full"])]
    union = [names[work] for work in complete if any(kind in by_work[work] and warning(by_work[work][kind]) for kind in positions)]
    def upper(events, count):
        return float(beta.ppf(.95, events + 1, count - events)) if count and events < count else (1.0 if count else None)
    return {"date": "2026-10-30", "status": "completed" if len(results) == plan["query_count"] else "incomplete",
            "query_count": plan["query_count"], "queries_recorded": len(results),
            "failed_queries": sum(row["state"] == "failed" for row in results.values()),
            "full": {"complete": len(complete), "warnings": len(full_warnings), "warning_rate": len(full_warnings) / len(complete) if complete else None,
                     "one_sided_95_upper": upper(len(full_warnings), len(complete)), "warning_names": full_warnings},
            "positions": positions, "three_30s_union": {"complete": len(complete), "warnings": len(union),
                "warning_rate": len(union) / len(complete) if complete else None,
                "one_sided_95_upper": upper(len(union), len(complete)), "warning_names": union}}


def main():
    global OUT, SEL
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--selection", type=Path, default=SEL)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.shard < 0 or args.shard >= args.shards:
        raise ValueError("Invalid shard")
    OUT, SEL = args.out, args.selection
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(SEL.read_text(encoding="utf-8"))
    frozen.setdefault("policy_sha256", digest(ART / "ai_precision_policy.json"))
    sys.path.insert(0, str(ROOT / "api"))
    from engine import Engine
    import evaluate_retrieval_baseline as base
    ffmpeg = base.find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg unavailable")
    plan = build_plan(frozen, ffmpeg)
    engine = Engine(scope="ai_labeled")
    checkpoint = OUT / f"results_all_{args.shard}_of_{args.shards}.jsonl"
    results = {}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            row = json.loads(line); key = (row["work_id"], row["kind"])
            if key in results: raise RuntimeError("Duplicate result")
            results[key] = row
    shard_queries = [query for i, query in enumerate(plan["queries"]) if i % args.shards == args.shard]
    with checkpoint.open("a", encoding="utf-8") as stream:
        for i, query in enumerate(shard_queries, 1):
            key = (query["work_id"], query["kind"])
            if key in results: continue
            path = Path(query["file"])
            if not path.is_file() or digest(path) != query["sha256"]:
                raise RuntimeError(f"Audio changed: {path}")
            try:
                row = {**query, "state": "completed", "result": engine.verify(path, query["sha256"])}
            except Exception as exc:
                row = {**query, "state": "failed", "error_type": type(exc).__name__, "error": str(exc)[:400]}
            results[key] = row; stream.write(json.dumps(row, ensure_ascii=False) + "\n"); stream.flush()
            if i % 10 == 0: print(f"[shard {args.shard}/{args.shards} evaluate {i}/{len(shard_queries)}]", flush=True)
            (OUT / f"summary_all_{args.shard}_of_{args.shards}.json").write_text(json.dumps(summarize(plan, results), ensure_ascii=False, indent=2), encoding="utf-8")
    summary = summarize(plan, results)
    (OUT / f"summary_all_{args.shard}_of_{args.shards}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
