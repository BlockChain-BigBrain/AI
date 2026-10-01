"""Chroma feature extraction and transposition-tolerant segment comparison."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import numpy as np


SAMPLE_RATE = 22_050
HOP_LENGTH = 2_048
WINDOW_SECONDS = 10
STRIDE_SECONDS = 5


def extract_chroma(path: Path, ffmpeg: str, cache_dir: Path) -> tuple[np.ndarray, float]:
    """ffmpeg로 오디오를 디코딩하고 캐시된 12음계 크로마그램을 돌려줍니다."""

    # 경로, 크기, 수정 시각을 캐시 키에 넣어 파일이 바뀌면 다시 분석합니다.
    signature = f"{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}"
    cache_path = cache_dir / (hashlib.sha256(signature.encode("utf-8")).hexdigest() + ".npz")
    if cache_path.is_file():
        saved = np.load(cache_path, allow_pickle=False)
        return saved["chroma"].astype(np.float32), float(saved["duration"])

    # MP3, WebM 등 입력 형식을 ffmpeg가 모노 float 배열로 통일합니다.
    decoded = subprocess.run(
        [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    audio = np.frombuffer(decoded.stdout, dtype="<f4").copy()
    if audio.size == 0:
        raise RuntimeError(f"오디오 데이터를 읽지 못했습니다: {path}")
    duration = len(audio) / SAMPLE_RATE

    # Hann 창을 씌운 짧은 프레임들에 STFT를 적용합니다.
    # librosa 기본 함수와 같은 방식으로 중앙 정렬을 위해 양 끝을 패딩합니다.
    n_fft = 4096
    padded_audio = np.pad(audio, (n_fft // 2, n_fft // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded_audio, n_fft)[::HOP_LENGTH]
    window = np.hanning(n_fft).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window[None, :], axis=1)).astype(np.float32)

    # FFT 주파수를 가장 가까운 음높이에 배정한 뒤 12개 음계 계열로 합칩니다.
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / SAMPLE_RATE)
    valid_bins = (frequencies >= 55.0) & (frequencies <= 5_000.0)
    midi_notes = np.rint(69 + 12 * np.log2(frequencies[valid_bins] / 440.0)).astype(np.int32)
    pitch_classes = midi_notes % 12
    chroma = np.stack(
        [spectrum[:, valid_bins][:, pitch_classes == pitch_class].sum(axis=1)
         for pitch_class in range(12)],
        axis=0,
    )
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    chroma = np.divide(chroma, np.maximum(norms, 1e-8)).astype(np.float32)

    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, chroma=chroma, duration=np.asarray(duration))
    return chroma, duration


def segment_features(chroma: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """크로마그램을 10초 창, 5초 간격으로 나눠 창별 프레임 행렬을 만듭니다."""

    frames_per_window = max(1, round(WINDOW_SECONDS * SAMPLE_RATE / HOP_LENGTH))
    frames_per_stride = max(1, round(STRIDE_SECONDS * SAMPLE_RATE / HOP_LENGTH))
    last_start = max(0, chroma.shape[1] - frames_per_window)
    starts = list(range(0, last_start + 1, frames_per_stride))
    if not starts or starts[-1] != last_start:
        starts.append(last_start)

    windows: list[np.ndarray] = []
    for start in starts:
        window = chroma[:, start : start + frames_per_window]
        if window.shape[1] < frames_per_window:
            window = np.pad(window, ((0, 0), (0, frames_per_window - window.shape[1])))
        windows.append(window)
    offsets = [start * HOP_LENGTH / SAMPLE_RATE for start in starts]
    return np.stack(windows), offsets


def compare_chroma(query_chroma: np.ndarray, candidate_chroma: np.ndarray) -> dict[str, object]:
    """구간별 시간 정렬 크로마 코사인을 비교하고 조옮김을 허용합니다.

    점수는 10초 구간의 프레임별 코사인 유사도를 음계 12개 회전에서
    가장 잘 맞는 방향으로 계산한 값입니다. 시간축 DTW는 아직 적용하지 않습니다.
    """

    query_windows, query_offsets = segment_features(query_chroma)
    candidate_windows, candidate_offsets = segment_features(candidate_chroma)
    scores = np.empty((len(query_windows), len(candidate_windows)), dtype=np.float32)

    # 12개 피치 클래스 순환 이동을 시험해 키가 다른 경우도 허용합니다.
    for query_index, query_window in enumerate(query_windows):
        for candidate_index, candidate_window in enumerate(candidate_windows):
            shift_scores = [
                float(np.mean(np.sum(query_window * np.roll(candidate_window, shift, axis=0), axis=0)))
                for shift in range(12)
            ]
            scores[query_index, candidate_index] = max(shift_scores)

    # 겹치는 창이 같은 구간을 중복 집계하지 않도록 서로 10초 이상 떨어진
    # query/reference 창만 남기는 탐욕적 Top-3 집계를 사용합니다.
    ranked_pairs = sorted(
        (
            (float(scores[q_index, c_index]), q_index, c_index)
            for q_index in range(scores.shape[0])
            for c_index in range(scores.shape[1])
        ),
        reverse=True,
    )
    selected: list[tuple[float, int, int]] = []
    for score, q_index, c_index in ranked_pairs:
        q_start = query_offsets[q_index]
        c_start = candidate_offsets[c_index]
        if all(
            abs(q_start - query_offsets[old_q]) >= WINDOW_SECONDS
            and abs(c_start - candidate_offsets[old_c]) >= WINDOW_SECONDS
            for _, old_q, old_c in selected
        ):
            selected.append((score, q_index, c_index))
            if len(selected) == 3:
                break
    if not selected:
        raise RuntimeError("크로마 창을 비교할 수 없습니다.")

    best_score, best_q, best_c = max(
        (
            (float(scores[q_index, c_index]), q_index, c_index)
            for q_index in range(scores.shape[0])
            for c_index in range(scores.shape[1])
        ),
        key=lambda item: item[0],
    )
    return {
        "chroma_top3_mean": float(np.mean([item[0] for item in selected])),
        "chroma_best_segment": best_score,
        "chroma_selected_matches": [
            {
                "score": score,
                "query_start_seconds": query_offsets[q_index],
                "candidate_start_seconds": candidate_offsets[c_index],
            }
            for score, q_index, c_index in selected
        ],
        "best_query_start_seconds": query_offsets[best_q],
        "best_candidate_start_seconds": candidate_offsets[best_c],
        "query_segment_count": len(query_windows),
        "candidate_segment_count": len(candidate_windows),
    }


# JIT keeps the many short window-level DTW comparisons fast enough for reranking.
from numba import njit


@njit(cache=False)
def _oti_dtw_similarity(query_window: np.ndarray, candidate_window: np.ndarray) -> tuple[float, int]:
    """Estimate a circular pitch-class shift, then DTW-align two chroma windows."""
    query_frames = query_window.shape[1]
    candidate_frames = candidate_window.shape[1]
    query_mean = np.zeros(12, dtype=np.float32)
    candidate_mean = np.zeros(12, dtype=np.float32)
    for pitch in range(12):
        for frame in range(query_frames):
            query_mean[pitch] += query_window[pitch, frame]
        query_mean[pitch] /= max(1, query_frames)
        for frame in range(candidate_frames):
            candidate_mean[pitch] += candidate_window[pitch, frame]
        candidate_mean[pitch] /= max(1, candidate_frames)

    best_shift = 0
    best_histogram_score = -1.0
    for shift in range(12):
        score = 0.0
        for pitch in range(12):
            score += query_mean[pitch] * candidate_mean[(pitch + shift) % 12]
        if score > best_histogram_score:
            best_histogram_score = score
            best_shift = shift

    previous = np.full(candidate_frames + 1, np.inf, dtype=np.float32)
    current = np.full(candidate_frames + 1, np.inf, dtype=np.float32)
    previous[0] = 0.0
    for query_index in range(1, query_frames + 1):
        current[:] = np.inf
        for candidate_index in range(1, candidate_frames + 1):
            cosine = 0.0
            for pitch in range(12):
                cosine += (
                    query_window[pitch, query_index - 1]
                    * candidate_window[(pitch + best_shift) % 12, candidate_index - 1]
                )
            local_cost = 1.0 - min(1.0, max(0.0, cosine))
            predecessor = min(
                previous[candidate_index],
                current[candidate_index - 1],
                previous[candidate_index - 1],
            )
            current[candidate_index] = local_cost + predecessor
        swap = previous
        previous = current
        current = swap

    normalized_cost = previous[candidate_frames] / max(query_frames, candidate_frames)
    similarity = max(0.0, 1.0 - normalized_cost)
    return similarity, best_shift


def chroma_windows(chroma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compress frame chroma to about 1 Hz and produce overlapping 10-second windows."""
    frames_per_bin = max(1, round(SAMPLE_RATE / HOP_LENGTH))
    bins = []
    for start in range(0, chroma.shape[1], frames_per_bin):
        feature = np.mean(chroma[:, start:start + frames_per_bin], axis=1)
        norm = float(np.linalg.norm(feature))
        bins.append(feature / max(norm, 1e-8))
    if not bins:
        raise ValueError("No chroma frames available")
    binned = np.stack(bins).astype(np.float32)
    window_bins = 10
    stride_bins = 5
    last_start = max(0, len(binned) - window_bins)
    starts = list(range(0, last_start + 1, stride_bins))
    if not starts or starts[-1] != last_start:
        starts.append(last_start)
    windows = []
    offsets = []
    seconds_per_bin = frames_per_bin * HOP_LENGTH / SAMPLE_RATE
    for start in starts:
        window = binned[start:start + window_bins]
        if len(window) < window_bins:
            window = np.pad(window, ((0, window_bins - len(window)), (0, 0)))
        windows.append(window.T.copy())
        offsets.append(start * seconds_per_bin)
    return np.stack(windows), np.asarray(offsets, dtype=np.float32)


def compare_chroma_dtw(query_chroma: np.ndarray, candidate_chroma: np.ndarray) -> dict[str, object]:
    """Compare aligned 20-second sequences using OTI and local chroma DTW.

    A coarse transposition-tolerant score finds the best three adjacent pairs of
    10-second windows. DTW then handles local tempo differences inside those
    windows. The returned score is a retrieval reranking feature, not a verdict.
    """
    query_windows, query_offsets = chroma_windows(query_chroma)
    candidate_windows, candidate_offsets = chroma_windows(candidate_chroma)
    query_means = query_windows.mean(axis=2)
    candidate_means = candidate_windows.mean(axis=2)
    coarse = np.zeros((len(query_windows), len(candidate_windows)), dtype=np.float32)
    for shift in range(12):
        shifted = candidate_means[:, np.roll(np.arange(12), shift)]
        coarse = np.maximum(coarse, query_means @ shifted.T)

    best_score = -1.0
    best_indices = (0, 0)
    match_windows = 1
    if coarse.shape[0] >= 3 and coarse.shape[1] >= 3:
        triplet_scores = (coarse[:-2, :-2] + coarse[1:-1, 1:-1] + coarse[2:, 2:]) / 3.0
        query_steps = np.diff(query_offsets)
        candidate_steps = np.diff(candidate_offsets)
        valid_query = (np.abs(query_steps[:-1] - STRIDE_SECONDS) < 0.6) & (
            np.abs(query_steps[1:] - STRIDE_SECONDS) < 0.6
        )
        valid_candidate = (np.abs(candidate_steps[:-1] - STRIDE_SECONDS) < 0.6) & (
            np.abs(candidate_steps[1:] - STRIDE_SECONDS) < 0.6
        )
        valid = valid_query[:, None] & valid_candidate[None, :]
        triplet_scores = np.where(valid, triplet_scores, -np.inf)
        if np.isfinite(triplet_scores).any():
            q0, c0 = np.unravel_index(np.argmax(triplet_scores), triplet_scores.shape)
            best_score = float(triplet_scores[q0, c0])
            best_indices = (int(q0), int(c0))
            match_windows = 3
    if match_windows == 1 and coarse.shape[0] >= 2 and coarse.shape[1] >= 2:
        pair_scores = (coarse[:-1, :-1] + coarse[1:, 1:]) / 2.0
        valid = (
            (np.abs(np.diff(query_offsets) - STRIDE_SECONDS) < 0.6)[:, None]
            & (np.abs(np.diff(candidate_offsets) - STRIDE_SECONDS) < 0.6)[None, :]
        )
        pair_scores = np.where(valid, pair_scores, -np.inf)
        if np.isfinite(pair_scores).any():
            q0, c0 = np.unravel_index(np.argmax(pair_scores), pair_scores.shape)
            best_score = float(pair_scores[q0, c0])
            best_indices = (int(q0), int(c0))
            match_windows = 2
    if match_windows == 1 and best_score < 0:
        q0, c0 = np.unravel_index(np.argmax(coarse), coarse.shape)
        best_score = float(coarse[q0, c0])
        best_indices = (int(q0), int(c0))

    q0, c0 = best_indices
    dtw_scores = []
    shifts = []
    for step in range(match_windows):
        score, shift = _oti_dtw_similarity(
            query_windows[q0 + step], candidate_windows[c0 + step]
        )
        dtw_scores.append(float(score))
        shifts.append(int(shift))
    return {
        "chroma_dtw_score": float(np.mean(dtw_scores)),
        "coarse_oti_score": float(best_score),
        "dtw_window_count": match_windows,
        "dtw_match_seconds": float(WINDOW_SECONDS + (match_windows - 1) * STRIDE_SECONDS),
        "dtw_query_start_seconds": float(query_offsets[q0]),
        "dtw_candidate_start_seconds": float(candidate_offsets[c0]),
        "oti_pitch_class_shifts": shifts,
        "query_window_count": len(query_windows),
        "candidate_window_count": len(candidate_windows),
    }
