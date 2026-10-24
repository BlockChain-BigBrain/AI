"""Tonal sequence confirmation, independent of CLAP's timbre embedding.

Inspired by chroma + local alignment (Essentia CoverSongSimilarity), but this is
our own continuous-cosine implementation, not an equivalent Essentia algorithm.
Recipe v1 is fixed before the new evaluation: 0.5 s bins, pitch centering,
all 12 transpositions and local alignment with 1:1 / 1:2 / 2:1 steps.
"""
from pathlib import Path
import numpy as np
from numba import njit
import chroma_comparator as chroma

VERSION = 'tonal-local-v1'
BIN_SECONDS = 0.5


def features(path: Path, ffmpeg: str, cache_dir: Path | None):
    raw, duration = chroma.extract_chroma(path, ffmpeg, cache_dir)
    width = max(1, round(BIN_SECONDS * chroma.SAMPLE_RATE / chroma.HOP_LENGTH))
    rows = np.stack([raw[:, i:i + width].mean(axis=1) for i in range(0, raw.shape[1], width)])
    # Remove shared broadband energy, then normalize each pitch-class profile.
    rows = rows - rows.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(rows, axis=1, keepdims=True)
    rows = np.divide(rows, np.maximum(norm, 1e-8)).astype(np.float32)
    return rows, duration, width * chroma.HOP_LENGTH / chroma.SAMPLE_RATE


@njit(cache=True)
def _align(a, b):
    n, m = len(a), len(b)
    best, best_i, best_j, best_shift = 0.0, 0, 0, 0
    best_start_i, best_start_j = 0, 0
    for shift in range(12):
        score = np.zeros((n + 1, m + 1), np.float32)
        start_i = np.zeros((n + 1, m + 1), np.int32)
        start_j = np.zeros((n + 1, m + 1), np.int32)
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cosine = 0.0
                for p in range(12):
                    cosine += a[i - 1, p] * b[j - 1, (p + shift) % 12]
                # A shared chord alone is insufficient: reward a sustained sequence.
                reward = (cosine - 0.5) / 0.5
                pi, pj = i - 1, j - 1
                predecessor = score[pi, pj]
                if i >= 2 and score[i - 2, j - 1] - 0.15 > predecessor:
                    pi, pj = i - 2, j - 1
                    predecessor = score[pi, pj] - 0.15
                if j >= 2 and score[i - 1, j - 2] - 0.15 > predecessor:
                    pi, pj = i - 1, j - 2
                    predecessor = score[pi, pj] - 0.15
                value = max(0.0, predecessor + reward)
                score[i, j] = value
                if predecessor > 0:
                    start_i[i, j], start_j[i, j] = start_i[pi, pj], start_j[pi, pj]
                else:
                    start_i[i, j], start_j[i, j] = i - 1, j - 1
                if value > best:
                    best, best_i, best_j, best_shift = value, i, j, shift
                    best_start_i, best_start_j = start_i[i, j], start_j[i, j]
    # Normalize against 10 s minimum so sub-second coincidences stay weak.
    denominator = max(20, min(n, m))
    return min(1.0, best / denominator), best_start_i, best_i, best_start_j, best_j, best_shift


def compare(query, reference, query_step=BIN_SECONDS, reference_step=BIN_SECONDS):
    score, qi, qe, ri, re, shift = _align(query, reference)
    return {'tonalScore': float(score), 'queryStartSec': float(qi * query_step),
            'queryEndSec': float(qe * query_step), 'refStartSec': float(ri * reference_step),
            'refEndSec': float(re * reference_step), 'pitchShift': int(shift)}
