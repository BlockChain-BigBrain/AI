"""Evaluate pretrained CLAP as a candidate retriever.

The reference catalog comes from original_music. Positive queries come from
synthetic test manifests and safe queries come from music. Training source
tracks are excluded from positive queries to reduce source-track leakage.
Cached CLAP embeddings are reused; missing reference originals are embedded.

This is retrieval evaluation, not a plagiarism verdict. The displayed score
cutoffs are historical and are not calibrated.
"""

from __future__ import annotations

import csv
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from transformers import ClapAudioModelWithProjection, ClapProcessor


# 프로젝트 내 입력 폴더와 기존 학습 산출물 경로입니다.
PROJECT_DIR = Path(__file__).resolve().parent.parent
LAYER2_DIR = PROJECT_DIR / "layer2"
ARTIFACT_DIR = LAYER2_DIR / "artifacts"
POSITIVE_DIR = LAYER2_DIR / "test_data" / "plagiarism_positive"
POSITIVE_MANIFEST = POSITIVE_DIR / "manifest.csv"
REPERFORMANCE_DIR = LAYER2_DIR / "test_data" / "reperformed_positive"
REPERFORMANCE_MANIFEST = REPERFORMANCE_DIR / "manifest.csv"
SAFE_QUERY_DIR = PROJECT_DIR / "music"
ORIGINAL_DIR = PROJECT_DIR / "original_music"
CACHE_DIR = ARTIFACT_DIR / "evaluation_embedding_cache"
REPORT_JSON = ARTIFACT_DIR / "retrieval_baseline_report.json"
REPORT_CSV = ARTIFACT_DIR / "retrieval_baseline_details.csv"
FALSE_POSITIVE_CSV = ARTIFACT_DIR / "false_positive_diagnostics.csv"

# CLAP 입력과 검색 창은 음악 자르기 설정과 맞춥니다.
BASE_MODEL = "laion/clap-htsat-unfused"
SAMPLE_RATE = 48_000
WINDOW_SECONDS = 10
STRIDE_SECONDS = 5
MIN_CONTINUITY_WINDOWS = 3
DEFAULT_QUERY_WINDOW_COUNT = 5
BATCH_SIZE = 8
WARN_THRESHOLD = 0.70
HOLD_THRESHOLD = 0.85
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm", ".aac"}
FFMPEG_EXE: str | None = None


def audio_files(folder: Path) -> list[Path]:
    """지정 폴더 아래의 지원되는 오디오 파일을 정렬해 찾습니다."""

    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def track_id_from_original(path: Path) -> str:
    """원곡 파일의 이름에서 원곡 ID를 만듭니다."""

    return path.stem


def find_ffmpeg() -> str | None:
    """시스템 PATH 또는 imageio-ffmpeg 패키지에서 ffmpeg를 찾습니다."""

    path_command = shutil.which("ffmpeg")
    if path_command:
        return path_command
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def get_duration_seconds(path: Path) -> float:
    """오디오 전체를 디코딩하지 않고 ffmpeg 메타정보에서 길이를 읽습니다."""

    result = subprocess.run(
        [FFMPEG_EXE, "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise RuntimeError(f"음원 길이를 읽지 못했습니다: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def decode_window(path: Path, start_seconds: float) -> np.ndarray:
    """ffmpeg로 필요한 10초 구간만 디코딩해 모노 float32 배열로 돌려줍니다."""

    result = subprocess.run(
        [
            FFMPEG_EXE, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss",
            f"{start_seconds:.3f}", "-i", str(path), "-t", str(WINDOW_SECONDS),
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    target_length = WINDOW_SECONDS * SAMPLE_RATE
    # np.pad 대신 고정 길이 버퍼에 복사해 디코더 출력 길이 차이를 안전하게 처리합니다.
    fixed_audio = np.zeros(target_length, dtype=np.float32)
    copied_length = min(target_length, len(audio))
    fixed_audio[:copied_length] = audio[:copied_length]
    return fixed_audio


def extract_windows(
    path: Path,
    all_reference_windows: bool,
    query_window_count: int = DEFAULT_QUERY_WINDOW_COUNT,
    all_query_windows: bool = False,
) -> tuple[np.ndarray, list[float]]:
    """음원을 읽어 CLAP용 10초 오디오 창들과 각 창 시작 시각을 만듭니다."""

    # 음원 길이를 먼저 구해 창을 만들 수 있는 파일인지 확인합니다.
    duration = get_duration_seconds(path)
    window_size = WINDOW_SECONDS * SAMPLE_RATE
    if duration < WINDOW_SECONDS:
        return np.empty((0, window_size), dtype=np.float32), []
    last_start = duration - WINDOW_SECONDS
    if all_reference_windows or all_query_windows:
        # 기준 원곡과 전체 검사 쿼리는 5초 간격의 모든 10초 창을 만듭니다.
        starts_seconds = list(np.arange(0.0, last_start + 0.001, STRIDE_SECONDS))
        if not starts_seconds or abs(starts_seconds[-1] - last_start) > 0.001:
            starts_seconds.append(last_start)
    else:
        # 빠른 표본 실행에서는 균등한 위치의 창만 선택할 수 있습니다.
        starts_seconds = sorted(
            set(np.linspace(0.0, last_start, num=query_window_count).tolist())
        )

    # 필요한 구간만 디코딩하므로 긴 원곡 전체를 매번 메모리에 읽지 않습니다.
    windows = np.stack([decode_window(path, start) for start in starts_seconds]).astype(np.float32)
    offsets = [float(start) for start in starts_seconds]
    return windows, offsets


def cache_key(
    path: Path,
    all_reference_windows: bool,
    query_window_count: int = DEFAULT_QUERY_WINDOW_COUNT,
    all_query_windows: bool = False,
) -> Path:
    """파일 경로와 수정 시각을 반영해 임베딩 캐시 파일 경로를 계산합니다."""

    signature = (
        f"{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}|"
        f"{all_reference_windows}|None|{query_window_count}"
    )
    # 이전의 쿼리 5창 캐시를 전체 창 평가에서 재사용하지 않게 구분합니다.
    if all_query_windows and not all_reference_windows:
        signature += "|query_all_windows_stride_5s_v2"
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.npz"


def embed_file(
    path: Path,
    model: ClapAudioModelWithProjection,
    processor: ClapProcessor,
    device: torch.device,
    all_reference_windows: bool,
    query_window_count: int = DEFAULT_QUERY_WINDOW_COUNT,
    all_query_windows: bool = False,
) -> tuple[np.ndarray, list[float]]:
    """파일의 창 임베딩을 계산하고 재실행을 위해 캐시에 저장합니다."""

    # 파일이 바뀌지 않았다면 이전 실행에서 계산한 벡터를 재사용합니다.
    cache_path = cache_key(
        path, all_reference_windows, query_window_count, all_query_windows
    )
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        return cached["vectors"].astype(np.float32), cached["offsets"].tolist()

    windows, offsets = extract_windows(
        path, all_reference_windows, query_window_count, all_query_windows
    )
    if len(windows) == 0:
        return np.empty((0, 512), dtype=np.float32), []

    # 여러 창을 묶어 CLAP에 넣어 한 번씩 처리하는 비용을 줄입니다.
    vector_batches: list[np.ndarray] = []
    for start in range(0, len(windows), BATCH_SIZE):
        # Processor는 리스트 안에 파형 배열이 하나씩 들어 있는 형식을 기대합니다.
        audio_batch = [window for window in windows[start : start + BATCH_SIZE]]
        inputs = processor(
            audio=audio_batch,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
            padding=True,
        ).to(device)
        with torch.inference_mode():
            output = model(**inputs)
        vector_batches.append(F.normalize(output.audio_embeds, dim=-1).cpu().numpy())

    vectors = np.concatenate(vector_batches, axis=0).astype(np.float32)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, vectors=vectors, offsets=np.asarray(offsets, dtype=np.float32))
    return vectors, offsets


def read_positive_queries(
    train_track_ids: set[str],
) -> tuple[list[dict[str, str]], dict[str, dict[str, object]]]:
    """학습에 사용되지 않은 원곡의 양성 변형 쿼리만 고르고 원곡 경로를 모읍니다."""

    queries: list[dict[str, str]] = []
    held_out_sources: dict[str, dict[str, object]] = {}
    with POSITIVE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as manifest_file:
        for row in csv.DictReader(manifest_file):
            source_id = row["source_track_id"]
            # ?? ????? ??? ?? ??? ?? ???? ??? ?? ?????.
            if source_id in train_track_ids:
                continue
            query_path = Path(row["query_path"])
            source_path = Path(row["source_path"])
            if query_path.is_file() and source_path.is_file():
                queries.append(
                    {
                        "path": str(query_path),
                        "label": "positive",
                        "expected_track_id": source_id,
                        "query_kind": "synthetic_same_recording_excerpt",
                    }
                )
                held_out_sources.setdefault(source_id, {"path": source_path})
    return queries, held_out_sources


def read_reperformance_queries(train_track_ids: set[str]) -> list[dict[str, str]]:
    """자동 편집·음향변형 양성 매니페스트에서 누수 없는 쿼리를 읽습니다."""

    queries: list[dict[str, str]] = []
    if not REPERFORMANCE_MANIFEST.is_file():
        return queries
    with REPERFORMANCE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as manifest_file:
        for row in csv.DictReader(manifest_file):
            source_id = row["source_track_id"].strip()
            query_path = Path(row["query_path"])
            if source_id in train_track_ids:
                # 학습에 사용한 원곡에서 만든 변형은 원곡 분리 원칙에 따라 제외합니다.
                continue
            if query_path.is_file() and source_id:
                queries.append(
                    {
                        "path": str(query_path),
                        "label": "positive",
                        "expected_track_id": source_id,
                        "query_kind": "synthetic_arrangement_or_audio_transform",
                    }
                )
    return queries


def scores_by_track(
    query_vectors: np.ndarray,
    query_offsets: list[float],
    reference_vectors: np.ndarray,
    reference_ids: np.ndarray,
    reference_offsets: np.ndarray,
) -> list[dict[str, float | str]]:
    """Return per-track maximum scores and time-aligned continuity scores.

    ``score`` is the maximum cosine similarity across all window pairs.
    ``continuity_score`` is the mean similarity of the best aligned three-window
    sequence advancing by the configured stride in both recordings.
    """

    similarities = query_vectors @ reference_vectors.T
    best_by_track: dict[str, dict[str, float | str]] = {}
    for track_id in np.unique(reference_ids):
        reference_indices = np.flatnonzero(reference_ids == track_id)
        # ?? ??? ???? ?? ?? ????? ?????.
        order = np.argsort(reference_offsets[reference_indices], kind="stable")
        reference_indices = reference_indices[order]
        local = similarities[:, reference_indices]
        query_index, local_reference_index = np.unravel_index(np.argmax(local), local.shape)
        reference_index = reference_indices[local_reference_index]

        # ??/?? ???? ?? ?? 5? ??? ???? ???? ?????.
        # ?? 2? ?? 10? ? ?? ? 15?? ?? ??? ????.
        track_offsets = np.asarray(reference_offsets[reference_indices], dtype=np.float32)
        continuity_score = float("-inf")
        continuity_windows = 0
        continuity_query_start = float(query_offsets[query_index])
        continuity_reference_start = float(track_offsets[local_reference_index])

        # Score every aligned triplet at once. Each triplet covers 20 seconds
        # because 10-second windows begin every 5 seconds.
        if local.shape[0] >= MIN_CONTINUITY_WINDOWS and local.shape[1] >= MIN_CONTINUITY_WINDOWS:
            q_steps = np.diff(np.asarray(query_offsets, dtype=np.float32))
            r_steps = np.diff(track_offsets)
            q_valid = (np.abs(q_steps[:-1] - STRIDE_SECONDS) <= 0.51) & (
                np.abs(q_steps[1:] - STRIDE_SECONDS) <= 0.51
            )
            r_valid = (np.abs(r_steps[:-1] - STRIDE_SECONDS) <= 0.51) & (
                np.abs(r_steps[1:] - STRIDE_SECONDS) <= 0.51
            )
            triplet_scores = (
                local[:-2, :-2] + local[1:-1, 1:-1] + local[2:, 2:]
            ) / 3.0
            valid_triplets = q_valid[:, None] & r_valid[None, :]
            triplet_scores = np.where(valid_triplets, triplet_scores, -np.inf)
            if np.isfinite(triplet_scores).any():
                q0, r0 = np.unravel_index(np.argmax(triplet_scores), triplet_scores.shape)
                continuity_score = float(triplet_scores[q0, r0])
                continuity_windows = MIN_CONTINUITY_WINDOWS
                continuity_query_start = float(query_offsets[q0])
                continuity_reference_start = float(track_offsets[r0])

        # For very short queries, fall back to two neighboring windows, then one.
        if continuity_windows == 0 and local.shape[0] >= 2 and local.shape[1] >= 2:
            q_steps = np.diff(np.asarray(query_offsets, dtype=np.float32))
            r_steps = np.diff(track_offsets)
            pair_scores = (local[:-1, :-1] + local[1:, 1:]) / 2.0
            valid_pairs = (
                (np.abs(q_steps - STRIDE_SECONDS) <= 0.51)[:, None]
                & (np.abs(r_steps - STRIDE_SECONDS) <= 0.51)[None, :]
            )
            pair_scores = np.where(valid_pairs, pair_scores, -np.inf)
            if np.isfinite(pair_scores).any():
                q0, r0 = np.unravel_index(np.argmax(pair_scores), pair_scores.shape)
                continuity_score = float(pair_scores[q0, r0])
                continuity_windows = 2
                continuity_query_start = float(query_offsets[q0])
                continuity_reference_start = float(track_offsets[r0])

        if continuity_windows == 0:
            continuity_score = float(local[query_index, local_reference_index])
            continuity_windows = 1

        best_by_track[str(track_id)] = {
            "track_id": str(track_id),
            "score": float(local[query_index, local_reference_index]),
            "query_start_seconds": float(query_offsets[query_index]),
            "reference_start_seconds": float(reference_offsets[reference_index]),
            "continuity_score": float(continuity_score),
            "continuity_windows": int(continuity_windows),
            "continuous_match_seconds": float(WINDOW_SECONDS + (continuity_windows - 1) * STRIDE_SECONDS),
            "continuity_query_start_seconds": continuity_query_start,
            "continuity_reference_start_seconds": continuity_reference_start,
        }
    # Preserve legacy score order; the continuity rerank is created by the caller.
    return sorted(best_by_track.values(), key=lambda item: float(item["score"]), reverse=True)

def training_window_offsets(paths: np.ndarray) -> np.ndarray:
    """기존 학습 세그먼트 파일명에서 각 창의 시작 초를 읽습니다."""

    offsets: list[float] = []
    for value in paths.astype(str):
        match = re.search(r"_(\d{6})s(?:\.[^.]+)?$", Path(value).name)
        offsets.append(float(match.group(1)) if match else 0.0)
    return np.asarray(offsets, dtype=np.float32)


def metrics_at_threshold(
    results: list[dict[str, object]], threshold: float
) -> dict[str, float | int | None]:
    """양성/정상 쿼리에 대한 혼동행렬과 기본 지표를 계산합니다."""

    tp = sum(row["label"] == "positive" and row["top_score"] >= threshold for row in results)
    fn = sum(row["label"] == "positive" and row["top_score"] < threshold for row in results)
    fp = sum(row["label"] == "safe" and row["top_score"] >= threshold for row in results)
    tn = sum(row["label"] == "safe" and row["top_score"] < threshold for row in results)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {
        "threshold": threshold,
        "true_positive": int(tp),
        "false_negative": int(fn),
        "false_positive": int(fp),
        "true_negative": int(tn),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": 1 - specificity if specificity is not None else None,
        "f1": f1,
    }


def main() -> None:
    """Run the retrieval baseline over the configured positive and safe queries."""

    # CPU 환경에서도 소규모로 먼저 돌릴 수 있도록 테스트 파일 수를 조절합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-positive", type=int, default=0, help="양성 쿼리 상한; 0은 전부")
    parser.add_argument("--max-safe", type=int, default=0, help="정상 쿼리 상한; 0은 전부")
    args = parser.parse_args()
    if args.max_positive < 0 or args.max_safe < 0:
        raise SystemExit("--max-positive와 --max-safe는 0 이상이어야 합니다.")

    # 필수 입력 파일과 폴더를 확인하고, 학습 임베딩 캐시를 읽습니다.
    raw_cache_path = ARTIFACT_DIR / "clap_embeddings.npz"
    catalog_manifest_path = ARTIFACT_DIR / "segment_manifest.csv"
    required = [POSITIVE_MANIFEST, raw_cache_path, catalog_manifest_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("필수 파일이 없습니다:\n" + "\n".join(missing))
    if not SAFE_QUERY_DIR.is_dir() or not ORIGINAL_DIR.is_dir():
        raise SystemExit("music 또는 original_music 폴더가 없습니다.")

    raw_cache = np.load(raw_cache_path, allow_pickle=False)
    with (ARTIFACT_DIR / "segment_manifest.csv").open("r", newline="", encoding="utf-8-sig") as manifest_file:
        catalog_rows = list(csv.DictReader(manifest_file))
    catalog_paths = np.asarray([row["segment_path"] for row in catalog_rows])
    if not np.array_equal(raw_cache["paths"].astype(str), catalog_paths.astype(str)):
        raise SystemExit("CLAP embeddings and segment_manifest.csv are out of sync.")
    catalog_track_ids = np.asarray([row["track_id"] for row in catalog_rows])
    train_track_ids = set(catalog_track_ids.tolist())

    # 학습 때 본 곡을 제외한 양성 테스트 쿼리와 그 원곡 경로를 선택합니다.
    positive_queries, held_out_sources = read_positive_queries(train_track_ids)
    positive_queries.extend(read_reperformance_queries(train_track_ids))
    if args.max_positive:
        # 표본 시험에서는 여러 변형본 대신 서로 다른 원곡을 먼저 하나씩 고릅니다.
        first_by_source: dict[str, dict[str, str]] = {}
        for query in positive_queries:
            first_by_source.setdefault(query["expected_track_id"], query)
        chosen_source_ids = list(first_by_source)[: args.max_positive]
        positive_queries = [first_by_source[source_id] for source_id in chosen_source_ids]
        held_out_sources = {
            source_id: {
                "path": held_out_sources[source_id]["path"],
            }
            for source_id in chosen_source_ids
        }
    negative_queries = [
        {
            "path": str(path),
            "label": "safe",
            "expected_track_id": "",
            "query_kind": "safe_music_excerpt",
        }
        for path in audio_files(SAFE_QUERY_DIR)
    ]
    if args.max_safe:
        negative_queries = negative_queries[: args.max_safe]
    if not positive_queries or not negative_queries:
        raise SystemExit(
            f"평가 파일이 부족합니다: held-out 양성 {len(positive_queries)}개, 정상 {len(negative_queries)}개"
        )

    # 기존 174곡의 저장 벡터를 기준 검색 DB로 사용하고, 누락된 양성 원곡을 추가합니다.
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    global FFMPEG_EXE
    FFMPEG_EXE = find_ffmpeg()
    if not FFMPEG_EXE:
        raise SystemExit("ffmpeg를 찾을 수 없습니다. PATH에 추가하거나 imageio-ffmpeg를 설치하세요.")
    # CPU에서는 과도한 스레드 경합을 피하도록 추론 스레드를 적당히 제한합니다.
    if device.type == "cpu":
        torch.set_num_threads(min(4, torch.get_num_threads()))
    # 네트워크가 막힌 환경에서도 이미 내려받은 체크포인트만 사용합니다.
    clap_model = ClapAudioModelWithProjection.from_pretrained(
        BASE_MODEL, local_files_only=True
    ).to(device)
    clap_model.eval()
    processor = ClapProcessor.from_pretrained(BASE_MODEL, local_files_only=True)

    reference_raw_parts = [raw_cache["embeddings"].astype(np.float32)]
    reference_ids_parts = [catalog_track_ids]
    reference_offsets_parts = [training_window_offsets(raw_cache["paths"])]
    existing_reference_ids = set(catalog_track_ids.tolist())
    for source_id, source_info in held_out_sources.items():
        source_path = source_info["path"]
        # 평가 대상 원곡을 전체 길이, 5초 간격으로 기준 DB에 색인합니다.
        vectors, offsets = embed_file(
            source_path,
            clap_model,
            processor,
            device,
            all_reference_windows=True,
        )
        if len(vectors):
            reference_raw_parts.append(vectors)
            # NumPy의 dtype=str은 폭 1 문자열이 되므로 ID 길이에 맞춰 폭을 지정합니다.
            reference_ids_parts.append(
                np.full(len(vectors), source_id, dtype=f"<U{max(1, len(source_id))}")
            )
            reference_offsets_parts.append(np.asarray(offsets, dtype=np.float32))

    # 학습 벡터와 위의 양성 원곡을 제외한 나머지 원곡 전부를 기준 DB에 추가합니다.
    already_indexed_ids = existing_reference_ids | set(held_out_sources)
    missing_originals = [
        path for path in audio_files(ORIGINAL_DIR)
        if track_id_from_original(path) not in already_indexed_ids
    ]
    for reference_number, source_path in enumerate(missing_originals, start=1):
        source_id = track_id_from_original(source_path)
        vectors, offsets = embed_file(
            source_path, clap_model, processor, device, all_reference_windows=True
        )
        if len(vectors):
            reference_raw_parts.append(vectors)
            reference_ids_parts.append(
                np.full(len(vectors), source_id, dtype=f"<U{max(1, len(source_id))}")
            )
            reference_offsets_parts.append(np.asarray(offsets, dtype=np.float32))
        print(
            f"[reference {reference_number}/{len(missing_originals)}] "
            f"{source_path.name} | windows={len(vectors)}",
            flush=True,
        )

    reference_raw = np.concatenate(reference_raw_parts, axis=0)
    reference_ids = np.concatenate(reference_ids_parts, axis=0)
    reference_offsets = np.concatenate(reference_offsets_parts, axis=0)
    # 양성/정상 각 쿼리를 같은 방식으로 잘라 두 모델의 검색 결과를 비교합니다.
    all_queries = positive_queries + negative_queries
    model_results: dict[str, list[dict[str, object]]] = {"clap_only": []}
    for number, query in enumerate(all_queries, start=1):
        query_path = Path(query["path"])
        raw_vectors, offsets = embed_file(
            query_path,
            clap_model,
            processor,
            device,
            all_reference_windows=False,
            all_query_windows=True,
        )
        if len(raw_vectors) == 0:
            print(f"[skip] 10초 미만: {query_path.name}", flush=True)
            continue

        for model_name, query_vectors, reference_vectors in (
            ("clap_only", raw_vectors, reference_raw),
        ):
            matches = scores_by_track(
                query_vectors, offsets, reference_vectors, reference_ids, reference_offsets
            )
            best = matches[0]
            # ? ?? ??? ??? ??, ?? ? ?, ?? ?? ?? ??? ????.
            # Preserve the CLAP Top-5 candidate pool, then rerank only within it.
            # This keeps the candidate recall at the legacy max-score Top-5 level.
            clap_candidates = matches[:5]
            continuity_matches = sorted(
                clap_candidates,
                key=lambda match: (
                    float(match["continuity_score"]),
                    int(match["continuity_windows"]),
                    float(match["score"]),
                ),
                reverse=True,
            )
            continuity_best = continuity_matches[0]
            expected_track_id = query["expected_track_id"]
            continuity_source_rank = next(
                (index for index, match in enumerate(continuity_matches, start=1)
                 if match["track_id"] == expected_track_id),
                None,
            ) if query["label"] == "positive" else None
            result = {
                "file": str(query_path.resolve()),
                "label": query["label"],
                "query_kind": query["query_kind"],
                "expected_track_id": expected_track_id,
                "top_track_id": best["track_id"],
                "top_score": best["score"],
                "expected_source_rank": next(
                    (index for index, match in enumerate(matches, start=1)
                     if match["track_id"] == expected_track_id),
                    None,
                ) if query["label"] == "positive" else None,
                "source_retrieved_at_rank1": (
                    best["track_id"] == expected_track_id
                    if query["label"] == "positive"
                    else None
                ),
                "continuity_top_track_id": continuity_best["track_id"],
                "continuity_top_score": continuity_best["continuity_score"],
                "continuity_top_windows": continuity_best["continuity_windows"],
                "continuity_top_duration_seconds": continuity_best["continuous_match_seconds"],
                "continuity_expected_source_rank": continuity_source_rank,
                "continuity_source_retrieved_at_rank1": (
                    continuity_best["track_id"] == expected_track_id
                    if query["label"] == "positive"
                    else None
                ),
                "window_count": len(offsets),
                "top_matches": matches[:5],
                "clap_top20_matches": matches[:20],
                "continuity_top_matches": continuity_matches[:5],
            }
            model_results[model_name].append(result)

        print(
            f"[{number}/{len(all_queries)}] {query_path.name} | query windows={len(offsets)}",
            flush=True,
        )

    # 고정 임계값 결과와 원곡 검색 성공률을 함께 요약합니다.
    summary: dict[str, object] = {
        "candidate_ranking_policy": {
            "model": "clap_only",
            "candidate_pool": "top 5 tracks by maximum window-pair cosine score",
            "reranking_score": "mean cosine similarity across best aligned three windows",
            "window_seconds": WINDOW_SECONDS,
            "stride_seconds": STRIDE_SECONDS,
            "minimum_coverage_seconds": WINDOW_SECONDS + 2 * STRIDE_SECONDS,
            "candidate_top_k": 5,
            "calibrated": False,
        },
        "reference_track_count": int(len(np.unique(reference_ids))),
        "reference_window_count": int(len(reference_ids)),
        "training_track_count": len(train_track_ids),
        "held_out_positive_source_count": len(held_out_sources),
        "positive_query_count": sum(row["label"] == "positive" for row in model_results["clap_only"]),
        "reperformed_positive_query_count": sum(
            row["query_kind"] == "reperformed_cover_or_arrangement"
            for row in model_results["clap_only"]
        ),
        "safe_query_count": sum(row["label"] == "safe" for row in model_results["clap_only"]),
        "skipped_query_count": len(all_queries) - len(model_results["clap_only"]),
        "query_window_policy": f"all 10-second windows at {STRIDE_SECONDS}-second stride",
        "thresholds_are_calibrated": False,
        "note": (
            "CLAP cosine scores are similarity values, not plagiarism percentages. "
            "Same-recording synthetic queries are not independently performed covers. "
            "The reference index contains all unique-stem files in original_music, using cached vectors for trained tracks. "
            "Thresholds have not been calibrated."
        ),
        "models": {},
    }
    detail_rows: list[dict[str, object]] = []
    for model_name, results in model_results.items():
        positive_results = [row for row in results if row["label"] == "positive"]
        safe_results = [row for row in results if row["label"] == "safe"]
        continuity_source_ranks = [
            row["continuity_expected_source_rank"]
            for row in positive_results
            if row["continuity_expected_source_rank"] is not None
        ]
        summary["models"][model_name] = {
            "hold_0_85": metrics_at_threshold(results, HOLD_THRESHOLD),
            "warn_0_70_or_higher": metrics_at_threshold(results, WARN_THRESHOLD),
            "positive_source_recall_at_1": (
                float(np.mean([row["source_retrieved_at_rank1"] for row in positive_results]))
                if positive_results else None
            ),
            "positive_median_source_rank": (
                float(np.median([row["expected_source_rank"] for row in positive_results]))
                if positive_results else None
            ),
            "clap_candidate_source_recall_at_5": (
                float(np.mean([
                    row["expected_source_rank"] is not None and row["expected_source_rank"] <= 5
                    for row in positive_results
                ])) if positive_results else None
            ),
            "continuity_reranked_source_recall_at_1": (
                float(np.mean([row["continuity_source_retrieved_at_rank1"] for row in positive_results]))
                if positive_results else None
            ),
            "continuity_candidate_coverage_at_5": (
                float(np.mean([
                    row["continuity_expected_source_rank"] is not None
                    and row["continuity_expected_source_rank"] <= 5
                    for row in positive_results
                ])) if positive_results else None
            ),
            "continuity_reranked_median_rank_within_candidates": (
                float(np.median(continuity_source_ranks)) if continuity_source_ranks else None
            ),
            "positive_score_median": (
                float(np.median([row["top_score"] for row in positive_results])) if positive_results else None
            ),
            "safe_score_median": (
                float(np.median([row["top_score"] for row in safe_results])) if safe_results else None
            ),
        }
        for row in results:
            detail_rows.append({"model": model_name, **row})

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with REPORT_CSV.open("w", newline="", encoding="utf-8-sig") as report_file:
        columns = [
            "model", "file", "label", "query_kind", "expected_track_id", "top_track_id",
            "top_score", "expected_source_rank", "source_retrieved_at_rank1",
            "continuity_top_track_id", "continuity_top_score", "continuity_top_windows",
            "continuity_top_duration_seconds", "continuity_expected_source_rank",
            "continuity_source_retrieved_at_rank1", "window_count", "top_matches",
            "continuity_top_matches", "clap_top20_matches",
        ]
        writer = csv.DictWriter(report_file, fieldnames=columns)
        writer.writeheader()
        for row in detail_rows:
            writer.writerow({
                **row,
                "top_matches": json.dumps(row["top_matches"], ensure_ascii=False),
                "continuity_top_matches": json.dumps(row["continuity_top_matches"], ensure_ascii=False),
                "clap_top20_matches": json.dumps(row["clap_top20_matches"], ensure_ascii=False),
            })

    # HOLD 기준을 넘은 정상곡만 따로 뽑아 매칭된 구간을 사람이 확인할 수 있게 합니다.
    # top_matches의 구간 시각은 10초 창의 시작 시각이며, 최대 5개 원곡 후보를 기록합니다.
    with FALSE_POSITIVE_CSV.open("w", newline="", encoding="utf-8-sig") as diagnostic_file:
        columns = [
            "model", "safe_file", "query_top_score", "hold_threshold",
            "rank", "matched_track_id", "matched_score",
            "query_window_start_seconds", "reference_window_start_seconds",
            "query_window_end_seconds", "reference_window_end_seconds",
        ]
        writer = csv.DictWriter(diagnostic_file, fieldnames=columns)
        writer.writeheader()
        for model_name, results in model_results.items():
            for row in results:
                if row["label"] != "safe" or float(row["top_score"]) < HOLD_THRESHOLD:
                    continue
                for rank, match in enumerate(row["top_matches"], start=1):
                    query_start = float(match["query_start_seconds"])
                    reference_start = float(match["reference_start_seconds"])
                    writer.writerow({
                        "model": model_name,
                        "safe_file": row["file"],
                        "query_top_score": row["top_score"],
                        "hold_threshold": HOLD_THRESHOLD,
                        "rank": rank,
                        "matched_track_id": match["track_id"],
                        "matched_score": match["score"],
                        "query_window_start_seconds": query_start,
                        "reference_window_start_seconds": reference_start,
                        "query_window_end_seconds": query_start + WINDOW_SECONDS,
                        "reference_window_end_seconds": reference_start + WINDOW_SECONDS,
                    })

    candidate_csv = ARTIFACT_DIR / "retrieval_continuity_candidates.csv"
    with candidate_csv.open("w", newline="", encoding="utf-8-sig") as candidate_file:
        columns = [
            "query_file", "label", "expected_track_id", "candidate_rank", "clap_max_rank", "candidate_track_id",
            "max_pair_score", "continuity_score", "continuity_windows", "continuous_match_seconds",
            "query_start_seconds", "reference_start_seconds",
        ]
        writer = csv.DictWriter(candidate_file, fieldnames=columns)
        writer.writeheader()
        for row in model_results["clap_only"]:
            original_ranks = {
                item["track_id"]: rank
                for rank, item in enumerate(row["top_matches"], start=1)
            }
            for rank, candidate in enumerate(row["continuity_top_matches"], start=1):
                writer.writerow({
                    "query_file": row["file"],
                    "label": row["label"],
                    "expected_track_id": row["expected_track_id"],
                    "candidate_rank": rank,
                    "clap_max_rank": original_ranks[candidate["track_id"]],
                    "candidate_track_id": candidate["track_id"],
                    "max_pair_score": candidate["score"],
                    "continuity_score": candidate["continuity_score"],
                    "continuity_windows": candidate["continuity_windows"],
                    "continuous_match_seconds": candidate["continuous_match_seconds"],
                    "query_start_seconds": candidate["continuity_query_start_seconds"],
                    "reference_start_seconds": candidate["continuity_reference_start_seconds"],
                })

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Continuity candidate list: {candidate_csv}")
    print(f"상세 결과: {REPORT_CSV}")
    print(f"요약 결과: {REPORT_JSON}")
    print(f"HOLD 오탐 구간 분석: {FALSE_POSITIVE_CSV}")


if __name__ == "__main__":
    main()
