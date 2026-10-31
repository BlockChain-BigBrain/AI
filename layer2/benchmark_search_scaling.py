"""Measure cached-vector retrieval scaling on the local 1000-track catalog.

This is a CPU exact-search microbenchmark. It excludes audio decoding,
CLAP query encoding, tonal reranking, network, persistence, and any ANN/vector DB.
The target item is kept in every sampled catalog; this is one diagnostic query,
not a recall estimate or an operational SLA.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import statistics
import time
from pathlib import Path

import numpy as np
import torch

import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "layer2" / "artifacts"


def pct(values, q):
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize(values):
    return {
        "p50_ms": pct(values, 50) * 1000,
        "p95_ms": pct(values, 95) * 1000,
        "min_ms": min(values) * 1000,
        "max_ms": max(values) * 1000,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--output", type=Path, default=ART / "search_scaling_benchmark_20261027.json")
    args = parser.parse_args()
    if args.repeats < 10:
        raise ValueError("Use at least 10 repetitions for a useful timing summary")

    catalog_path = ART / "current_reference_catalog.npz"
    with np.load(catalog_path, allow_pickle=False) as saved:
        vectors = saved["vectors"].astype(np.float32)
        ids = saved["ids"].astype(str)
        offsets = saved["offsets"].astype(np.float32)
    track_ids = sorted(set(ids.tolist()))
    if len(track_ids) != 1000:
        raise RuntimeError(f"Expected 1000 catalog tracks, found {len(track_ids)}")

    manifest_path = ROOT / "layer2" / "test_data" / "ai_labeled_positive" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next(
        r for r in manifest["rows"]
        if r.get("dataset") == "positive" and r.get("split") == "test"
        and Path(r["file"]).is_file()
    )
    target_id = str(row["expected_track_id"])
    if target_id not in track_ids:
        raise RuntimeError(f"Query target {target_id!r} is absent from the 1000-track catalog")

    base.FFMPEG_EXE = base.find_ffmpeg()
    if not base.FFMPEG_EXE:
        raise RuntimeError("ffmpeg is required")
    torch.set_num_threads(4)
    device = torch.device("cpu")
    model = agg.ClapAudioModelWithProjection.from_pretrained(
        base.BASE_MODEL, local_files_only=True
    ).to(device).eval()
    processor = agg.ClapProcessor.from_pretrained(base.BASE_MODEL, local_files_only=True)
    query, query_starts = base.embed_file(Path(row["file"]), model, processor, device, False,
                                          all_query_windows=True)
    query_starts = np.asarray(query_starts, dtype=np.float32)
    if query.ndim != 2 or query.shape[0] != len(query_starts):
        raise RuntimeError("Query windows and embeddings are inconsistent")

    rng = random.Random(args.seed)
    other_ids = [t for t in track_ids if t != target_id]
    sizes = sorted(set([34, 100, 250, 500, 1000]))
    rows = []
    for size in sizes:
        chosen = [target_id] + rng.sample(other_ids, size - 1)
        mask = np.isin(ids, chosen)
        ref = vectors[mask]
        ref_ids = ids[mask]
        ref_offsets = offsets[mask]
        mean = ref.mean(axis=0)
        centered = agg.unit_rows(ref - mean)
        groups = [(track, np.flatnonzero(ref_ids == track)) for track in sorted(chosen)]

        def retrieve():
            similarities = agg.unit_rows(query - mean) @ centered.T
            ranked = []
            for track, indices in groups:
                score, _ = agg.non_overlapping_top3(similarities[:, indices], query_starts)
                ranked.append((track, float(score)))
            ranked.sort(key=lambda x: (-x[1], x[0]))
            return ranked

        # Warm BLAS and Python paths before collecting timings.
        for _ in range(3):
            result = retrieve()
        matrix_times = []
        total_times = []
        for _ in range(args.repeats):
            t0 = time.perf_counter()
            similarities = agg.unit_rows(query - mean) @ centered.T
            t1 = time.perf_counter()
            ranked = []
            for track, indices in groups:
                score, _ = agg.non_overlapping_top3(similarities[:, indices], query_starts)
                ranked.append((track, float(score)))
            ranked.sort(key=lambda x: (-x[1], x[0]))
            t2 = time.perf_counter()
            matrix_times.append(t1 - t0)
            total_times.append(t2 - t0)
        target_rank = next((i for i, (track, _) in enumerate(result, 1) if track == target_id), None)
        rows.append({
            "reference_tracks": size,
            "reference_windows": int(mask.sum()),
            "query_windows": int(len(query_starts)),
            "matrix_similarity": summarize(matrix_times),
            "group_aggregation_and_sort_including_similarity": summarize(total_times),
            "diagnostic_target_track": target_id,
            "diagnostic_target_rank": target_rank,
            "diagnostic_target_in_top20": bool(target_rank and target_rank <= 20),
        })

    report = {
        "status": "completed_local_exact_search_microbenchmark",
        "date": "2026-10-27",
        "scope": "CPU exact dense cosine search over cached CLAP reference windows",
        "excluded": ["audio decode", "CLAP query encoding", "tonal reranking", "ANN/vector DB", "network", "API queue", "database writes", "concurrent load"],
        "not_claimed": ["Vector DB latency", "production p95", "independent recall", "generalization from the single diagnostic query"],
        "catalog_tracks": len(track_ids),
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "query": {"kind": row.get("query_kind"), "sha256": row.get("sha256"),
                  "source_track_id": target_id, "windows": int(len(query_starts))},
        "environment": {"platform": platform.platform(), "processor": platform.processor(),
                        "numpy": np.__version__, "torch": torch.__version__, "device": str(device),
                        "torch_threads": torch.get_num_threads(), "repeats": args.repeats, "seed": args.seed},
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["reference_tracks", "reference_windows", "query_windows",
            "matrix_p50_ms", "matrix_p95_ms", "full_retrieval_p50_ms", "full_retrieval_p95_ms",
            "diagnostic_target_rank", "diagnostic_target_in_top20"])
        writer.writeheader()
        for item in rows:
            writer.writerow({"reference_tracks": item["reference_tracks"], "reference_windows": item["reference_windows"],
                "query_windows": item["query_windows"], "matrix_p50_ms": item["matrix_similarity"]["p50_ms"],
                "matrix_p95_ms": item["matrix_similarity"]["p95_ms"],
                "full_retrieval_p50_ms": item["group_aggregation_and_sort_including_similarity"]["p50_ms"],
                "full_retrieval_p95_ms": item["group_aggregation_and_sort_including_similarity"]["p95_ms"],
                "diagnostic_target_rank": item["diagnostic_target_rank"],
                "diagnostic_target_in_top20": item["diagnostic_target_in_top20"]})
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        from matplotlib import font_manager
        font_manager.findfont("Malgun Gothic", fallback_to_default=False)
        plt.rcParams["font.family"] = "Malgun Gothic"
    except Exception:
        pass
    x = [r["reference_tracks"] for r in rows]
    fig, ax = plt.subplots(figsize=(9, 5.8))
    fig.subplots_adjust(left=.09, right=.985, bottom=.20, top=.84)
    for key, label, marker in [
        ("matrix_similarity", "행렬 유사도 계산", "o"),
        ("group_aggregation_and_sort_including_similarity", "곡별 집계·정렬 포함", "s"),
    ]:
        p50 = [r[key]["p50_ms"] for r in rows]
        p95 = [r[key]["p95_ms"] for r in rows]
        ax.plot(x, p50, marker=marker, linewidth=2, label=f"{label} p50")
        ax.plot(x, p95, marker=marker, linewidth=1.5, linestyle="--", label=f"{label} p95")
    ax.set(title="검색 규모별 지연 시간 (로컬 CPU, 캐시 벡터)",
           xlabel="검색 대상 원곡 수", ylabel="지연 시간 (ms)")
    ax.set_xticks(x)
    ax.grid(True, alpha=.25)
    ax.legend(frameon=False, ncol=2, fontsize=9)
    fig.text(.09, .025, "단일 변형 쿼리 5개 창, 30회 반복. 오디오 인코딩·톤 재정렬·Vector DB·네트워크·동시 부하 제외.", fontsize=8)
    png_path = args.output.with_suffix(".png")
    fig.savefig(png_path, dpi=180)
    plt.close(fig)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
