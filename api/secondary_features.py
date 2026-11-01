"""Lightweight independent audio features for runtime corroboration.

No model fitting happens here. Features are deterministic, bounded, and used
only as corroborating evidence beside CLAP segment scores.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
WINDOW_SECONDS = 10
N_FFT = 2048
HOP = 512


def decode(path: Path, start: float, ffmpeg: str) -> np.ndarray:
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}",
         "-i", str(path), "-t", str(WINDOW_SECONDS), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "pipe:1"],
        check=True, capture_output=True,
    )
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float32)
    target = WINDOW_SECONDS * SAMPLE_RATE
    if len(audio) < target:
        audio = np.pad(audio, (0, target - len(audio)))
    return audio[:target]


def _frames(audio: np.ndarray) -> np.ndarray:
    padded = np.pad(audio, (N_FFT // 2, N_FFT // 2))
    windows = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]
    return windows * np.hanning(N_FFT).astype(np.float32)


def _chroma(spec: np.ndarray) -> np.ndarray:
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SAMPLE_RATE)
    valid = (freqs >= 55.0) & (freqs <= 5000.0)
    midi = np.rint(69 + 12 * np.log2(freqs[valid] / 440.0)).astype(int) % 12
    result = np.stack([spec[:, valid][:, midi == pc].sum(axis=1) for pc in range(12)], axis=1)
    return result / np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-8)


def _pitch(spec: np.ndarray) -> np.ndarray:
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SAMPLE_RATE)
    valid = (freqs >= 55.0) & (freqs <= 1200.0)
    peaks = np.argmax(spec[:, valid], axis=1)
    hz = freqs[valid][peaks]
    energy = spec[:, valid].max(axis=1)
    contour = np.log2(np.maximum(hz, 1e-6))
    contour[energy < np.percentile(energy, 20)] = np.nan
    fill = np.nanmedian(contour) if np.isfinite(contour).any() else 0.0
    return np.nan_to_num(contour, nan=fill)


def _rhythm(spec: np.ndarray) -> np.ndarray:
    energy = np.log1p(spec[:, 1:].mean(axis=1))
    onset = np.maximum(0.0, np.diff(energy, prepend=energy[:1]))
    onset -= onset.mean()
    norm = np.linalg.norm(onset)
    return onset / max(norm, 1e-8)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    length = min(len(a), len(b))
    if length < 2:
        return 0.0
    a, b = a[:length], b[:length]
    a = a - a.mean()
    b = b - b.mean()
    return float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-8))


def compare(query: Path, reference: Path, query_start: float, reference_start: float, ffmpeg: str) -> dict[str, float]:
    q = np.abs(np.fft.rfft(_frames(decode(query, query_start, ffmpeg)), axis=1))
    r = np.abs(np.fft.rfft(_frames(decode(reference, reference_start, ffmpeg)), axis=1))
    q_chroma, r_chroma = _chroma(q), _chroma(r)
    chroma = max(_corr(q_chroma[:, shift].mean(axis=1), r_chroma[:, np.roll(np.arange(12), shift)].mean(axis=1)) for shift in range(12))
    pitch = max(0.0, min(1.0, (_corr(_pitch(q), _pitch(r)) + 1.0) / 2.0))
    rhythm = max(0.0, min(1.0, (_corr(_rhythm(q), _rhythm(r)) + 1.0) / 2.0))
    return {
        "chromaScore": max(0.0, min(1.0, chroma)),
        "pitchScore": pitch,
        "rhythmScore": rhythm,
        "corroborationScore": 0.45 * max(0.0, chroma) + 0.30 * pitch + 0.25 * rhythm,
    }
