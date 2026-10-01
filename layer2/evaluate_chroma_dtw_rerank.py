"""Evaluate OTI + chroma DTW reranking within CLAP Top-5 and Top-20 pools.

Run after evaluate_retrieval_baseline.py has written clap_top20_matches:
    python -u layer2/evaluate_chroma_dtw_rerank.py

This evaluates retrieval and reranking only; it does not set verdict thresholds.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

import chroma_comparator as chroma
import evaluate_retrieval_baseline as retrieval


PROJECT_DIR = Path(__file__).resolve().parent.parent
LAYER2_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = LAYER2_DIR / "artifacts"
RETRIEVAL_CSV = ARTIFACT_DIR / "retrieval_baseline_details.csv"
CACHE_DIR = ARTIFACT_DIR / "chroma_feature_cache"
DETAILS_CSV = ARTIFACT_DIR / "chroma_dtw_rerank_details.csv"
CANDIDATES_CSV = ARTIFACT_DIR / "chroma_dtw_rerank_candidates.csv"
SUMMARY_JSON = ARTIFACT_DIR / "chroma_dtw_rerank_summary.json"
CANDIDATE_KS = (5, 20)


def auc_from_scores(positive: list[float], negative: list[float]) -> float | None:
    """Compute ROC AUC, including half credit for tied scores."""
    if not positive or not negative:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def main() -> None:
    if not RETRIEVAL_CSV.is_file():
        raise SystemExit(f"Retrieval report not found: {RETRIEVAL_CSV}")
    ffmpeg = retrieval.find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("FFmpeg was not found; install imageio-ffmpeg or add FFmpeg to PATH.")

    original_paths = {
        retrieval.track_id_from_original(path): path
        for path in retrieval.audio_files(PROJECT_DIR / "original_music")
    }
    with RETRIEVAL_CSV.open("r", newline="", encoding="utf-8-sig") as source:
        queries = [row for row in csv.DictReader(source) if row["model"] == "clap_only"]
    if not queries or "clap_top20_matches" not in queries[0]:
        raise SystemExit("Rerun evaluate_retrieval_baseline.py to create the CLAP Top-20 list first.")

    # Keep extracted audio features in memory so one song is decoded only once.
    feature_cache: dict[str, np.ndarray] = {}
    comparison_cache: dict[tuple[str, str], dict[str, object]] = {}

    def features(path: Path) -> np.ndarray:
        key = str(path.resolve())
        if key not in feature_cache:
            feature_cache[key], _ = chroma.extract_chroma(path, ffmpeg, CACHE_DIR)
            if len(feature_cache) % 25 == 0:
                print(f"Chroma feature files loaded: {len(feature_cache)}", flush=True)
        return feature_cache[key]

    def compare(query_path: Path, candidate_path: Path) -> dict[str, object]:
        key = (str(query_path.resolve()), str(candidate_path.resolve()))
        if key not in comparison_cache:
            comparison_cache[key] = chroma.compare_chroma_dtw(
                features(query_path), features(candidate_path)
            )
        return comparison_cache[key]

    detail_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    for query_index, query in enumerate(queries, start=1):
        query_path = Path(query["file"])
        if not query_path.is_file():
            print(f"[skip] Missing query: {query_path}", flush=True)
            continue
        try:
            top20 = json.loads(query["clap_top20_matches"])
        except (json.JSONDecodeError, TypeError):
            print(f"[skip] Bad Top-20 JSON: {query_path.name}", flush=True)
            continue

        scored: list[dict[str, object]] = []
        for clap_rank, match in enumerate(top20, start=1):
            candidate_id = str(match["track_id"])
            candidate_path = original_paths.get(candidate_id)
            if candidate_path is None:
                continue
            try:
                scores = compare(query_path, candidate_path)
            except Exception as error:
                print(f"[skip candidate] {candidate_path.name}: {error}", flush=True)
                continue
            scored.append({
                "track_id": candidate_id,
                "candidate_path": str(candidate_path.resolve()),
                "clap_max_rank": clap_rank,
                "clap_max_score": float(match["score"]),
                **scores,
            })

        if not scored:
            continue
        expected_id = query["expected_track_id"]
        label = query["label"]
        case_type = next(
            (kind for kind in ("section_edit", "tempo_pitch_eq", "remix_fx") if kind in query_path.name),
            query["query_kind"],
        )
        for k in CANDIDATE_KS:
            pool = [item for item in scored if int(item["clap_max_rank"]) <= k]
            ranked = sorted(
                pool,
                key=lambda item: (
                    float(item["chroma_dtw_score"]),
                    float(item["coarse_oti_score"]),
                    float(item["clap_max_score"]),
                ),
                reverse=True,
            )
            source_rank = next(
                (rank for rank, item in enumerate(ranked, 1) if item["track_id"] == expected_id),
                None,
            ) if label == "positive" else None
            raw_source_rank = next(
                (rank for rank, item in enumerate(pool, 1) if item["track_id"] == expected_id),
                None,
            ) if label == "positive" else None
            best = ranked[0]
            detail_rows.append({
                "query_file": str(query_path.resolve()),
                "label": label,
                "query_kind": query["query_kind"],
                "case_type": case_type,
                "expected_track_id": expected_id,
                "candidate_k": k,
                "candidate_pool_size": len(pool),
                "expected_source_in_pool": raw_source_rank is not None,
                "source_rank_by_clap_within_pool": raw_source_rank,
                "source_rank_after_chroma_dtw": source_rank,
                "source_reranked_top1": source_rank == 1 if label == "positive" else None,
                "top_candidate_track_id": best["track_id"],
                "top_candidate_dtw_score": best["chroma_dtw_score"],
                "top_candidate_coarse_oti_score": best["coarse_oti_score"],
                "top_candidate_clap_rank": best["clap_max_rank"],
                "top_candidate_match_seconds": best["dtw_match_seconds"],
                "top_candidate_query_start_seconds": best["dtw_query_start_seconds"],
                "top_candidate_reference_start_seconds": best["dtw_candidate_start_seconds"],
            })
            for rerank, item in enumerate(ranked, start=1):
                candidate_rows.append({
                    "query_file": str(query_path.resolve()),
                    "label": label,
                    "expected_track_id": expected_id,
                    "candidate_k": k,
                    "rerank": rerank,
                    "candidate_track_id": item["track_id"],
                    "clap_max_rank": item["clap_max_rank"],
                    "clap_max_score": item["clap_max_score"],
                    "chroma_dtw_score": item["chroma_dtw_score"],
                    "coarse_oti_score": item["coarse_oti_score"],
                    "dtw_match_seconds": item["dtw_match_seconds"],
                    "query_start_seconds": item["dtw_query_start_seconds"],
                    "reference_start_seconds": item["dtw_candidate_start_seconds"],
                    "oti_pitch_class_shifts": json.dumps(item["oti_pitch_class_shifts"]),
                })
        print(f"[{query_index}/{len(queries)}] {query_path.name}: scored {len(scored)} candidates", flush=True)

    summary: dict[str, object] = {
        "method": "10-second chroma windows, OTI shift, local DTW, aligned three-window mean",
        "candidate_pool_sizes": list(CANDIDATE_KS),
        "decision_thresholds_calibrated": False,
        "query_count": len({row["query_file"] for row in detail_rows}),
        "results_by_candidate_k": {},
        "scope_note": (
            "This evaluates retrieval reranking, not a plagiarism verdict. Positive data include synthetic transforms. "
            "DTW cannot recover a source omitted from the CLAP candidate pool."
        ),
    }
    for k in CANDIDATE_KS:
        subset = [row for row in detail_rows if int(row["candidate_k"]) == k]
        positives = [row for row in subset if row["label"] == "positive"]
        negatives = [row for row in subset if row["label"] == "safe"]
        ranks = [int(row["source_rank_after_chroma_dtw"]) for row in positives
                 if row["source_rank_after_chroma_dtw"] is not None]
        source_found = sum(bool(row["expected_source_in_pool"]) for row in positives)
        positive_scores = [float(row["top_candidate_dtw_score"]) for row in positives]
        negative_scores = [float(row["top_candidate_dtw_score"]) for row in negatives]
        breakdown = {}
        for case in sorted({str(row["case_type"]) for row in positives}):
            group = [row for row in positives if row["case_type"] == case]
            group_ranks = [int(row["source_rank_after_chroma_dtw"]) for row in group
                           if row["source_rank_after_chroma_dtw"] is not None]
            breakdown[case] = {
                "query_count": len(group),
                "source_in_candidate_pool": sum(bool(row["expected_source_in_pool"]) for row in group),
                "source_top1_after_dtw": sum(rank == 1 for rank in group_ranks),
                "source_top5_after_dtw": sum(rank <= 5 for rank in group_ranks),
            }
        summary["results_by_candidate_k"][str(k)] = {
            "positive_count": len(positives),
            "safe_count": len(negatives),
            "source_candidate_pool_recall": source_found / len(positives) if positives else None,
            "source_top1_after_dtw_rate": sum(rank == 1 for rank in ranks) / len(positives) if positives else None,
            "source_top5_after_dtw_rate": sum(rank <= 5 for rank in ranks) / len(positives) if positives else None,
            "top1_given_source_in_pool": sum(rank == 1 for rank in ranks) / source_found if source_found else None,
            "median_source_rank_when_present": float(np.median(ranks)) if ranks else None,
            "positive_top_candidate_score_median": float(np.median(positive_scores)) if positive_scores else None,
            "safe_top_candidate_score_median": float(np.median(negative_scores)) if negative_scores else None,
            "top_candidate_score_roc_auc": auc_from_scores(positive_scores, negative_scores),
            "positive_breakdown": breakdown,
        }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in ((DETAILS_CSV, detail_rows), (CANDIDATES_CSV, candidate_rows)):
        with path.open("w", newline="", encoding="utf-8-sig") as output:
            fields = list(data[0]) if data else []
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Summary: {SUMMARY_JSON}")
    print(f"Details: {DETAILS_CSV}")
    print(f"Candidates: {CANDIDATES_CSV}")


if __name__ == "__main__":
    main()
