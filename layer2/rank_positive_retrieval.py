"""Measure where each of the 90 altered-audio queries ranks its source song.

This is a CLAP-only retrieval check. It uses every source song in
original_music as the reference catalog and does not apply a similarity cutoff.

Run with:
    python -u layer2/rank_positive_retrieval.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch
from transformers import ClapAudioModelWithProjection, ClapProcessor

import evaluate_retrieval_baseline as retrieval


PROJECT_DIR = Path(__file__).resolve().parent.parent
LAYER2_DIR = PROJECT_DIR / "layer2"
ARTIFACT_DIR = LAYER2_DIR / "artifacts"
POSITIVE_MANIFEST = LAYER2_DIR / "test_data" / "plagiarism_positive" / "manifest.csv"
ORIGINAL_DIR = PROJECT_DIR / "original_music"
RANK_CSV = ARTIFACT_DIR / "positive_source_ranks.csv"
SUMMARY_JSON = ARTIFACT_DIR / "positive_source_rank_summary.json"


def read_all_positive_queries() -> list[dict[str, str]]:
    """학습 여부로 제외하지 않고 manifest의 모든 유효한 변형곡을 읽습니다."""

    queries: list[dict[str, str]] = []
    with POSITIVE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as manifest_file:
        for row in csv.DictReader(manifest_file):
            query_path = Path(row["query_path"])
            source_path = Path(row["source_path"])
            if query_path.is_file() and source_path.is_file():
                queries.append(
                    {
                        "query_path": str(query_path),
                        "source_path": str(source_path),
                        "source_track_id": row["source_track_id"],
                    }
                )
    return queries


def main() -> None:
    """CLAP 구간 검색으로 90개 쿼리의 원곡 순위와 Top-K 적중률을 계산합니다."""

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cpu":
        torch.set_num_threads(min(4, torch.get_num_threads()))
    retrieval.FFMPEG_EXE = retrieval.find_ffmpeg()
    if not retrieval.FFMPEG_EXE:
        raise SystemExit("ffmpeg를 찾을 수 없습니다. PATH 또는 imageio-ffmpeg 설치를 확인하세요.")

    # CLAP 오디오 인코더는 고정된 사전학습 모델을 그대로 사용합니다.
    model = ClapAudioModelWithProjection.from_pretrained(
        retrieval.BASE_MODEL, local_files_only=True
    ).to(device)
    model.eval()
    processor = ClapProcessor.from_pretrained(retrieval.BASE_MODEL, local_files_only=True)

    # 학습 때 만든 CLAP 원본 벡터를 재사용하고, 나머지 원곡만 새로 임베딩합니다.
    # 이는 기존 전체 평가와 같은 검색 기준 카탈로그 구성을 유지합니다.
    raw_cache = np.load(ARTIFACT_DIR / "clap_embeddings.npz", allow_pickle=False)
    with (ARTIFACT_DIR / "segment_manifest.csv").open("r", newline="", encoding="utf-8-sig") as manifest_file:
        catalog_rows = list(csv.DictReader(manifest_file))
    catalog_paths = np.asarray([row["segment_path"] for row in catalog_rows])
    if not np.array_equal(raw_cache["paths"].astype(str), catalog_paths.astype(str)):
        raise SystemExit("CLAP embeddings and segment_manifest.csv are out of sync.")
    reference_vectors: list[np.ndarray] = [raw_cache["embeddings"].astype(np.float32)]
    reference_ids: list[str] = [row["track_id"] for row in catalog_rows]
    reference_offsets: list[float] = retrieval.training_window_offsets(raw_cache["paths"]).tolist()
    indexed_ids = set(reference_ids)
    originals = retrieval.audio_files(ORIGINAL_DIR)
    missing_originals = [
        path for path in originals
        if retrieval.track_id_from_original(path) not in indexed_ids
    ]
    for index, source_path in enumerate(missing_originals, start=1):
        track_id = retrieval.track_id_from_original(source_path)
        vectors, offsets = retrieval.embed_file(
            source_path,
            model,
            processor,
            device,
            all_reference_windows=True,
        )
        if len(vectors):
            reference_vectors.append(vectors)
            reference_ids.extend([track_id] * len(vectors))
            reference_offsets.extend(offsets)
        print(f"[reference {index}/{len(missing_originals)}] {source_path.name}", flush=True)

    if not reference_vectors:
        raise SystemExit("검색 기준 원곡에서 임베딩을 만들지 못했습니다.")
    reference_matrix = np.concatenate(reference_vectors, axis=0).astype(np.float32)
    reference_id_array = np.asarray(reference_ids)
    reference_offset_array = np.asarray(reference_offsets, dtype=np.float32)

    # 표절 변형곡 90개 각각에 대해 원곡별 최고 구간 점수로 순위를 냅니다.
    queries = read_all_positive_queries()
    if not queries:
        raise SystemExit("유효한 양성 query가 manifest에서 발견되지 않았습니다.")
    results: list[dict[str, object]] = []
    for index, query in enumerate(queries, start=1):
        query_path = Path(query["query_path"])
        query_vectors, query_offsets = retrieval.embed_file(
            query_path,
            model,
            processor,
            device,
            all_reference_windows=False,
            all_query_windows=True,
        )
        matches = retrieval.scores_by_track(
            query_vectors,
            query_offsets,
            reference_matrix,
            reference_id_array,
            reference_offset_array,
        )
        source_id = query["source_track_id"]
        rank = next(
            (rank for rank, match in enumerate(matches, start=1)
             if match["track_id"] == source_id),
            None,
        )
        source_match = next((match for match in matches if match["track_id"] == source_id), None)
        row: dict[str, object] = {
            "query_file": query["query_path"],
            "source_track_id": source_id,
            "source_rank": rank,
            "source_score": source_match["score"] if source_match else None,
            "top_1_track_id": matches[0]["track_id"],
            "top_1_score": matches[0]["score"],
            "top_5": matches[:5],
            "top_10": matches[:10],
        }
        results.append(row)
        print(
            f"[query {index}/{len(queries)}] {query_path.name}: source rank={rank}",
            flush=True,
        )

    ranks = [int(row["source_rank"]) for row in results if row["source_rank"] is not None]
    summary = {
        "query_count": len(results),
        "ranked_query_count": len(ranks),
        "reference_track_count": len(set(reference_ids)),
        "reference_window_count": len(reference_id_array),
        "top_1_count": sum(rank <= 1 for rank in ranks),
        "top_5_count": sum(rank <= 5 for rank in ranks),
        "top_10_count": sum(rank <= 10 for rank in ranks),
        "top_1_rate": sum(rank <= 1 for rank in ranks) / len(ranks) if ranks else None,
        "top_5_rate": sum(rank <= 5 for rank in ranks) / len(ranks) if ranks else None,
        "top_10_rate": sum(rank <= 10 for rank in ranks) / len(ranks) if ranks else None,
        "median_source_rank": float(np.median(ranks)) if ranks else None,
        "max_source_rank": max(ranks) if ranks else None,
        "scope_note": (
            "All positives are synthetic excerpts/transformations of the same original recording. "
            "This measures same-recording retrieval rank, not independently performed covers or legal plagiarism. "
            "Track score is the maximum cosine similarity across query/reference segment pairs."
        ),
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with RANK_CSV.open("w", newline="", encoding="utf-8-sig") as output_file:
        columns = [
            "query_file", "source_track_id", "source_rank", "source_score",
            "top_1_track_id", "top_1_score", "top_5", "top_10",
        ]
        writer = csv.DictWriter(output_file, fieldnames=columns)
        writer.writeheader()
        for row in results:
            writer.writerow({
                **row,
                "top_5": json.dumps(row["top_5"], ensure_ascii=False),
                "top_10": json.dumps(row["top_10"], ensure_ascii=False),
            })
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"상세 순위: {RANK_CSV}")
    print(f"요약: {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
