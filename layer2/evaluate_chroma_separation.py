"""Evaluate chroma similarity on known variants and safe-song CLAP Top-1 pairs.

Run:
    python -u layer2/evaluate_chroma_separation.py

The positives are same-recording transformed excerpts. This script does not
claim to evaluate legal plagiarism or separately performed cover versions.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

import chroma_comparator
import evaluate_retrieval_baseline as retrieval


PROJECT_DIR = Path(__file__).resolve().parent.parent
LAYER2_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = LAYER2_DIR / "artifacts"
POSITIVE_MANIFEST = LAYER2_DIR / "test_data" / "plagiarism_positive" / "manifest.csv"
RETRIEVAL_DETAILS = ARTIFACT_DIR / "retrieval_baseline_details.csv"
ORIGINAL_DIR = PROJECT_DIR / "original_music"
SAFE_DIR = PROJECT_DIR / "music"
CACHE_DIR = ARTIFACT_DIR / "chroma_feature_cache"
RESULTS_CSV = ARTIFACT_DIR / "chroma_evaluation_results.csv"
SUMMARY_JSON = ARTIFACT_DIR / "chroma_evaluation_summary.json"


def load_cases() -> tuple[list[dict[str, str]], dict[str, str]]:
    """양성은 매니페스트, 정상곡의 비교 원곡은 CLAP Top-1 결과에서 읽습니다."""

    cases: list[dict[str, str]] = []
    with POSITIVE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as manifest_file:
        for row in csv.DictReader(manifest_file):
            query = Path(row["query_path"])
            if query.is_file():
                cases.append(
                    {
                        "label": "positive",
                        "query_path": str(query),
                        "candidate_track_id": row["source_track_id"],
                        "expected_track_id": row["source_track_id"],
                        "query_kind": f"synthetic_variant_{row['variant']}",
                    }
                )

    # Use only the CLAP candidate retrieval rows from the baseline CSV.
    safe_candidates: dict[str, str] = {}
    with RETRIEVAL_DETAILS.open("r", newline="", encoding="utf-8-sig") as details_file:
        for row in csv.DictReader(details_file):
            if row["model"] == "clap_only" and row["label"] == "safe":
                safe_candidates[str(Path(row["file"]).resolve())] = row["top_track_id"]

    for safe_path in retrieval.audio_files(SAFE_DIR):
        key = str(safe_path.resolve())
        candidate_id = safe_candidates.get(key)
        if candidate_id:
            cases.append(
                {
                    "label": "safe",
                    "query_path": str(safe_path),
                    "candidate_track_id": candidate_id,
                    "expected_track_id": "",
                    "query_kind": "safe_vs_clap_top1",
                }
            )
    return cases, safe_candidates


def auc_from_scores(positive: list[float], negative: list[float]) -> float | None:
    """ROC AUC를 동점은 반 점으로 세어 직접 계산합니다."""

    if not positive or not negative:
        return None
    wins = sum(
        1.0 if pos > neg else 0.5 if pos == neg else 0.0
        for pos in positive
        for neg in negative
    )
    return wins / (len(positive) * len(negative))


def distribution(values: list[float]) -> dict[str, float | None]:
    """점수 분포의 평균, 표준편차, 중앙값, 사분위 범위를 계산합니다."""

    if not values:
        return {key: None for key in ("mean", "std", "median", "p10", "p90")}
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(array)),
        "std": float(np.std(array, ddof=1)) if len(array) > 1 else 0.0,
        "median": float(np.median(array)),
        "p10": float(np.quantile(array, 0.10)),
        "p90": float(np.quantile(array, 0.90)),
    }


def cohen_d(positive: list[float], negative: list[float]) -> float | None:
    """양성 평균과 정상 평균의 차이를 pooled standard deviation으로 나눕니다."""

    if len(positive) < 2 or len(negative) < 2:
        return None
    pos = np.asarray(positive, dtype=np.float64)
    neg = np.asarray(negative, dtype=np.float64)
    pooled_variance = (
        (len(pos) - 1) * np.var(pos, ddof=1) + (len(neg) - 1) * np.var(neg, ddof=1)
    ) / (len(pos) + len(neg) - 2)
    if pooled_variance <= 0:
        return None
    return float((np.mean(pos) - np.mean(neg)) / math.sqrt(pooled_variance))


def main() -> None:
    """양성/정상 각 쿼리의 원곡 후보와 크로마 유사도를 비교합니다."""

    ffmpeg = retrieval.find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("ffmpeg를 찾을 수 없습니다. PATH 또는 imageio-ffmpeg를 확인하세요.")

    # 파일 stem을 검색 기준 ID로 사용해 후보 ID와 오디오 경로를 연결합니다.
    originals = {
        retrieval.track_id_from_original(path): path
        for path in retrieval.audio_files(ORIGINAL_DIR)
    }
    cases, _ = load_cases()
    if not cases:
        raise SystemExit("양성/정상 평가 사례를 찾을 수 없습니다.")

    results: list[dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        query_path = Path(case["query_path"])
        candidate_id = case["candidate_track_id"]
        candidate_path = originals.get(candidate_id)
        if candidate_path is None:
            print(f"[skip] 기준 원곡을 못 찾음: {candidate_id}", flush=True)
            continue

        try:
            query_chroma, query_duration = chroma_comparator.extract_chroma(
                query_path, ffmpeg, CACHE_DIR
            )
            candidate_chroma, candidate_duration = chroma_comparator.extract_chroma(
                candidate_path, ffmpeg, CACHE_DIR
            )
            comparison = chroma_comparator.compare_chroma(query_chroma, candidate_chroma)
        except Exception as error:
            print(f"[skip] {query_path.name}: {error}", flush=True)
            continue

        result = {
            **case,
            "candidate_path": str(candidate_path),
            "query_duration_seconds": query_duration,
            "candidate_duration_seconds": candidate_duration,
            **comparison,
        }
        results.append(result)
        print(
            f"[{index}/{len(cases)}] {case['label']} {query_path.name}: "
            f"Top-3={comparison['chroma_top3_mean']:.4f}",
            flush=True,
        )

    positive_scores = [
        float(row["chroma_top3_mean"]) for row in results if row["label"] == "positive"
    ]
    negative_scores = [
        float(row["chroma_top3_mean"]) for row in results if row["label"] == "safe"
    ]
    summary = {
        "case_count": len(results),
        "positive_count": len(positive_scores),
        "safe_count": len(negative_scores),
        "score": "mean of up to three non-overlapping 10-second chroma segment matches",
        "positive_distribution": distribution(positive_scores),
        "safe_distribution": distribution(negative_scores),
        "roc_auc": auc_from_scores(positive_scores, negative_scores),
        "cohen_d": cohen_d(positive_scores, negative_scores),
        "interpretation_note": (
            "The positive files are excerpts/transforms of the same source recording. "
            "Safe files are compared only with their CLAP Top-1 candidate. "
            "Chroma reflects pitch-class energy and harmonic patterns; this experiment is not a legal plagiarism verdict. "
            "The current segment comparison is time-aligned and transposition-tolerant but has no DTW tempo alignment."
        ),
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    columns = [
        "label", "query_kind", "query_path", "candidate_track_id", "expected_track_id",
        "candidate_path", "query_duration_seconds", "candidate_duration_seconds",
        "chroma_top3_mean", "chroma_best_segment", "best_query_start_seconds",
        "best_candidate_start_seconds", "query_segment_count", "candidate_segment_count",
        "chroma_selected_matches",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=columns)
        writer.writeheader()
        for row in results:
            writer.writerow({
                **row,
                "chroma_selected_matches": json.dumps(
                    row["chroma_selected_matches"], ensure_ascii=False
                ),
            })
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"상세 결과: {RESULTS_CSV}")
    print(f"요약: {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
