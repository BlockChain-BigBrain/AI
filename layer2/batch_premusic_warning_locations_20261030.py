"""Batch 30-second location diagnostic using the frozen production policy inputs.

CLAP windows are embedded in batches. Candidate ranking and tonal confirmation
use the same reference catalog and thresholds; the supplemental CQT route is
reported separately and production thresholds are untouched.
"""
from __future__ import annotations

import hashlib
import json
import sys
import subprocess
import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime-tests" / "new-premusic-20261030"
PLAN = OUT / "query_plan_all.json"
REPORT = ROOT / "layer2" / "artifacts" / "premusic_warning_locations_20261030.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024): h.update(chunk)
    return h.hexdigest()


def main():
    global OUT, PLAN, REPORT
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--selection', type=Path, default=None)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args()
    OUT, PLAN, REPORT = args.out, args.plan, args.report
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    queries = [q for q in plan["queries"] if q["kind"] != "full"]
    selection_path = args.selection or (OUT / "all_selection.json")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    sources = {item["sha256"]: Path(item["path"]) for item in selection["selected"]}
    sys.path.insert(0, str(ROOT / "api"))
    from engine import Engine
    import evaluate_retrieval_baseline as base
    import evaluate_top3_aggregation as aggregation
    import selective_retrieval as selective
    import tonal_alignment as tonal
    engine = Engine(scope="ai_labeled")
    base.FFMPEG_EXE = base.find_ffmpeg()
    if not base.FFMPEG_EXE: raise RuntimeError("ffmpeg unavailable")

    # Decode all five 10-second windows per 30-second query, then embed in
    # larger batches so model overhead is paid once per batch rather than once
    # per file.
    windows = []
    metadata = []
    for i, query in enumerate(queries, 1):
        path = Path(query["file"])
        if not path.is_file() or path.stat().st_size < 1000:
            source = sources[query["work_id"]]
            offset = {"start30": 0, "middle30": 30, "end30": 60}[query["kind"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([base.FFMPEG_EXE, "-v", "error", "-nostdin", "-y", "-ss", str(offset), "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(path)], check=True, capture_output=True)
            if path.stat().st_size < 1000 and offset:
                subprocess.run([base.FFMPEG_EXE, "-v", "error", "-nostdin", "-y", "-ss", "0", "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(path)], check=True, capture_output=True)
            query["sha256"] = sha(path)
        if not path.is_file() or sha(path) != query["sha256"]:
            source = sources[query["work_id"]]
            offset = {"start30": 0, "middle30": 30, "end30": 60}[query["kind"]]
            subprocess.run([base.FFMPEG_EXE, "-v", "error", "-nostdin", "-y", "-ss", str(offset), "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(path)], check=True, capture_output=True)
            if path.stat().st_size < 1000 and offset:
                subprocess.run([base.FFMPEG_EXE, "-v", "error", "-nostdin", "-y", "-ss", "0", "-i", str(source), "-t", "30", "-ac", "1", "-ar", "22050", str(path)], check=True, capture_output=True)
            query["sha256"] = sha(path)
        if not path.is_file() or path.stat().st_size < 1000: raise RuntimeError(f"Could not regenerate query: {path}")
        cache = OUT / "window_cache" / f"{query['sha256']}.v3.npz"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            with np.load(cache, allow_pickle=False) as saved:
                audio, offsets = saved["audio"], saved["offsets"].tolist()
        else:
            audio, offsets = base.extract_windows(path, False, query_window_count=3, all_query_windows=False)
            np.savez_compressed(cache, audio=audio, offsets=np.asarray(offsets, dtype=np.float32))
        start = len(windows); windows.extend(audio.tolist())
        metadata.append({"query": query, "start": start, "end": len(windows), "offsets": offsets})
        if i % 50 == 0: print(f"[decode {i}/{len(queries)}]", flush=True)

    vectors = []
    batch_size = 64
    for start in range(0, len(windows), batch_size):
        batch_cache = OUT / "embedding_cache" / f"{start:06d}.npy"
        batch_cache.parent.mkdir(parents=True, exist_ok=True)
        if batch_cache.exists():
            vectors.append(np.load(batch_cache, allow_pickle=False))
        else:
            inputs = engine.processor(audio=windows[start:start + batch_size], sampling_rate=base.SAMPLE_RATE,
                                       return_tensors="pt", padding=True).to(engine.device)
            with torch.inference_mode():
                batch_vectors = torch.nn.functional.normalize(engine.model(**inputs).audio_embeds, dim=-1).cpu().numpy()
            np.save(batch_cache, batch_vectors)
            vectors.append(batch_vectors)
        if start // batch_size % 20 == 0: print(f"[embed {min(start + batch_size, len(windows))}/{len(windows)}]", flush=True)
    vectors = np.concatenate(vectors).astype(np.float32)
    results = []
    ref_tonal = {}
    for i, item in enumerate(metadata, 1):
        query = item["query"]; q = vectors[item["start"]:item["end"]]; offsets = item["offsets"]
        similarities = q @ engine.centered.T
        candidates = []
        for track_id, indices in engine.groups:
            indices = indices[np.argsort(engine.offsets[indices], kind="stable")]
            score, selected = aggregation.non_overlapping_top3(similarities[:, indices], offsets)
            candidates.append({"trackId": track_id, "score": score, "selected": selected, "indices": indices})
        candidates.sort(key=lambda row: row["score"], reverse=True)
        # Apply the same tonal confirmation and selective rank penalty to the
        # top-20 candidates. The supplemental precision route is kept out of
        # this location batch and evaluated as a separate diagnostic.
        q_tonal = tonal.features(Path(query["file"]), base.FFMPEG_EXE, None)[0]
        confirmed = []
        for rank, candidate in enumerate(candidates[:3], 1):
            track = candidate["trackId"]
            if track not in ref_tonal:
                ref_tonal[track] = tonal.features(engine.reference_paths[track], base.FFMPEG_EXE, ROOT / ".runtime-tests" / "location-tonal-cache")[0]
            evidence = tonal.compare(q_tonal, ref_tonal[track])
            evidence = selective.apply(evidence, rank) if engine.candidate_score_rule else evidence
            confirmed.append({"trackId": track, "score": evidence["tonalScore"], "retrievalScore": candidate["score"],
                              "queryStartSec": evidence["queryStartSec"], "queryEndSec": evidence["queryEndSec"]})
        confirmed.sort(key=lambda row: row["score"], reverse=True)
        score = confirmed[0]["score"] if confirmed else 0.0
        decision = "HOLD" if score >= engine.thresholds["hold"] else "WARN" if score >= engine.thresholds["warn"] else "PASS"
        results.append({"work_id": query["work_id"], "name": query["name"], "kind": query["kind"],
                        "decision": decision, "score": score, "best_track": confirmed[0]["trackId"] if confirmed else None,
                        "match_start_seconds": confirmed[0]["queryStartSec"] if confirmed else None,
                        "match_end_seconds": confirmed[0]["queryEndSec"] if confirmed else None,
                        "supplemental_cqt_route": "not_applied_in_batch_location_pass"})
        if i % 25 == 0: print(f"[score {i}/{len(metadata)}]", flush=True)

    by_work = defaultdict(dict)
    for row in results: by_work[row["work_id"]][row["kind"]] = row
    positions = {}
    for kind in ("start30", "middle30", "end30"):
        rows = [r for r in results if r["kind"] == kind]
        warns = [r for r in rows if r["decision"] in {"WARN", "HOLD", "BLOCK"}]
        positions[kind] = {"works": len(rows), "warnings": len(warns), "holds": sum(r["decision"] in {"HOLD", "BLOCK"} for r in rows),
                           "warning_rate": len(warns) / len(rows) if rows else None,
                           "warning_names": [r["name"] for r in warns]}
    union = []
    for work, rows in by_work.items():
        if any(row["decision"] in {"WARN", "HOLD", "BLOCK"} for row in rows.values()): union.append(next(iter(rows.values()))["name"])
    REPORT.write_text(json.dumps({"date": "2026-10-30", "query_count": len(results),
        "works": len(by_work), "positions": positions, "three_30s_union": {"works": len(by_work), "warnings": len(union), "warning_rate": len(union) / len(by_work), "warning_names": union},
        "thresholds": engine.thresholds, "method": "batched CLAP windows + top-20 tonal confirmation; supplemental CQT route separate", "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"works": len(by_work), "query_count": len(results), "positions": positions, "union_warnings": len(union)}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
