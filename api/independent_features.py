"""Independent acoustic evidence for CLAP matched segments.

These scores describe the matched audio only. They do not change the calibrated
CLAP decision until a separate, locked validation establishes thresholds.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
HOP = 512
FFT = 2048
FEATURE_VERSION = "pitch-rhythm-chroma-temporal-v3"


def extract(path: Path, ffmpeg: str, start: float | None = None,
            duration: float | None = None) -> dict[str, np.ndarray]:
    seek = ["-ss", str(max(0.0, start))] if start is not None else []
    length = ["-t", str(duration)] if duration is not None else []
    decoded = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", *seek, "-i", str(path), *length, "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        capture_output=True, check=True,
    )
    audio = np.frombuffer(decoded.stdout, dtype="<f4")
    if audio.size < FFT:
        raise ValueError(f"Audio is too short for feature extraction: {path}")
    frames = np.lib.stride_tricks.sliding_window_view(audio, FFT)[::HOP]
    magnitude = np.abs(np.fft.rfft(frames * np.hanning(FFT), axis=1)).astype(np.float32)
    frequency = np.fft.rfftfreq(FFT, 1 / SAMPLE_RATE)
    band = (frequency >= 80) & (frequency <= 4000)
    band_spec = magnitude[:, band]
    band_freq = frequency[band]

    # Pitch follows the strongest spectral peak per frame. Chroma sums energy
    # from every audible pitch class, so these are distinct measurements.
    peak = band_spec.argmax(axis=1)
    peak_energy = band_spec[np.arange(len(peak)), peak]
    pitch = np.rint(69 + 12 * np.log2(band_freq[peak] / 440)).astype(int) % 12
    pitch_hist = np.zeros((len(peak), 12), dtype=np.float32)
    pitch_hist[np.arange(len(peak)), pitch] = peak_energy

    classes = np.rint(69 + 12 * np.log2(band_freq / 440)).astype(int) % 12
    chroma = np.stack([band_spec[:, classes == i].sum(axis=1) for i in range(12)], axis=1)
    # Positive spectral flux is an onset envelope independent of tonal class.
    normalized = band_spec / np.maximum(band_spec.sum(axis=1, keepdims=True), 1e-8)
    onset = np.maximum(np.diff(normalized, axis=0, prepend=normalized[:1]), 0).sum(axis=1)
    return {"pitch": pitch_hist, "chroma": chroma.astype(np.float32),
            "onset": onset.astype(np.float32)}


def _unit(vector: np.ndarray) -> np.ndarray:
    return vector / max(float(np.linalg.norm(vector)), 1e-8)


def _tonal_score(left: np.ndarray, right: np.ndarray) -> tuple[float, int]:
    a = _unit(left.sum(axis=0))
    b = _unit(right.sum(axis=0))
    scores = [float(a @ np.roll(b, shift)) for shift in range(12)]
    shift = int(np.argmax(scores))
    return scores[shift], shift


def _rhythm_score(left: np.ndarray, right: np.ndarray) -> float:
    # Normalized onset autocorrelation compares periodic structure while
    # allowing a modest tempo change and ignoring absolute loudness.
    def profile(onsets: np.ndarray) -> np.ndarray:
        centered = onsets - onsets.mean()
        if not np.any(centered):
            return np.zeros(80, dtype=np.float32)
        corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
        return _unit(corr[10:90].astype(np.float32))
    a, b = profile(left), profile(right)
    return max(0.0, float(a @ b))


def compare(query: dict[str, np.ndarray], reference: dict[str, np.ndarray],
            matches: list[dict], reference_origin: float = 0.0) -> dict:
    evidence = []
    for match in matches:
        q0 = max(0, round(float(match["queryStartSec"]) * SAMPLE_RATE / HOP))
        r0 = max(0, round((float(match["refStartSec"]) - reference_origin) * SAMPLE_RATE / HOP))
        count = round(10 * SAMPLE_RATE / HOP)
        q1, r1 = min(q0 + count, len(query["onset"])), min(r0 + count, len(reference["onset"]))
        if q1 - q0 < 10 or r1 - r0 < 10:
            continue
        pitch, shift = _tonal_score(query["pitch"][q0:q1], reference["pitch"][r0:r1])
        chroma, _ = _tonal_score(query["chroma"][q0:q1], reference["chroma"][r0:r1])
        rhythm = _rhythm_score(query["onset"][q0:q1], reference["onset"][r0:r1])
        evidence.append({"queryStartSec": match["queryStartSec"],
                         "refStartSec": match["refStartSec"], "pitchScore": pitch,
                         "rhythmScore": rhythm, "chromaScore": chroma,
                         "pitchShift": shift})
    if not evidence:
        raise ValueError("No valid matched segments for acoustic features")
    return {"version": FEATURE_VERSION, "segments": evidence,
            **{key: float(np.mean([row[key] for row in evidence]))
               for key in ("pitchScore", "rhythmScore", "chromaScore")}}


def compare_file(query: dict[str, np.ndarray], reference_path: Path,
                 matches: list[dict], ffmpeg: str) -> dict:
    segments = []
    for match in matches:
        start = float(match["refStartSec"])
        reference = extract(reference_path, ffmpeg, start=start, duration=10.1)
        segments.extend(compare(query, reference, [match], reference_origin=start)["segments"])
    segments.sort(key=lambda row: float(row["queryStartSec"]))
    query_duration = len(query["onset"]) * HOP / SAMPLE_RATE
    query_starts = [float(row["queryStartSec"]) for row in segments]
    ref_starts = [float(row["refStartSec"]) for row in segments]
    ordered = all(b >= a for a, b in zip(ref_starts, ref_starts[1:]))
    order_fraction = (sum(b >= a for a, b in zip(ref_starts, ref_starts[1:])) /
                     max(1, len(ref_starts) - 1))
    shifts = [int(row["pitchShift"]) for row in segments]
    if shifts:
        shift_hist = np.bincount(shifts, minlength=12).astype(np.float32)
        pitch_consistency = float(shift_hist.max() / len(shifts))
    else:
        pitch_consistency = 0.0
    query_deltas = np.diff(query_starts)
    ref_deltas = np.diff(ref_starts)
    valid = (query_deltas > 0) & (ref_deltas > 0)
    ratios = query_deltas[valid] / ref_deltas[valid]
    tempo_ratio = float(np.median(ratios)) if len(ratios) else 1.0
    tempo_consistency = (float(np.exp(-np.std(np.log(np.maximum(ratios, 1e-8)))))
                         if len(ratios) > 1 else 1.0 if len(ratios) == 1 else 0.0)
    # Longest monotonic chain in the matched ten-second windows.
    longest = 1
    chain = 1
    for a, b in zip(ref_starts, ref_starts[1:]):
        chain = chain + 1 if b >= a else 1
        longest = max(longest, chain)
    match_seconds = min(10.0 * len(segments), query_duration)
    return {"version": FEATURE_VERSION, "segments": segments,
            "matchedSegmentCount": len(segments),
            "orderedMatchFraction": float(order_fraction),
            "orderedMatches": bool(ordered),
            "pitchShiftConsistency": pitch_consistency,
            "tempoRatioMedian": tempo_ratio,
            "tempoRatioConsistency": tempo_consistency,
            "longestOrderedChainSeconds": float(min(10 * longest, query_duration)),
            "queryCoverage": float(match_seconds / max(query_duration, 1e-8)),
            "referenceCoverage": float(min(1.0, match_seconds / max(ref_starts[-1] + 10.0, 1e-8))),
            **{key: float(np.mean([row[key] for row in segments]))
               for key in ("pitchScore", "rhythmScore", "chromaScore")}}


def pairwise_vector(candidate: dict) -> np.ndarray:
    """Feature vector shared by offline training and the API verifier."""
    evidence = candidate["featureEvidence"]
    base = np.asarray([candidate["score"], evidence["pitchScore"],
                       evidence["rhythmScore"], evidence["chromaScore"]], dtype=np.float64)
    segments = sorted(evidence.get("segments", []), key=lambda x: x["queryStartSec"])
    refs = [float(x["refStartSec"]) for x in segments]
    queries = [float(x["queryStartSec"]) for x in segments]
    ordered = sum(b >= a for a, b in zip(refs, refs[1:])) / max(1, len(refs) - 1)
    shifts = [int(x.get("pitchShift", 0)) for x in segments]
    shift_consistency = max((shifts.count(s) for s in set(shifts)), default=0) / max(1, len(shifts))
    ratios = [(b-a)/(d-c) for c, d, a, b in zip(queries, queries[1:], refs, refs[1:]) if d > c and b > a]
    tempo_consistency = float(np.exp(-np.std(np.log(np.maximum(ratios, 1e-8))))) if len(ratios) > 1 else 1.0 if ratios else 0.0
    longest = chain = 1
    for a, b in zip(refs, refs[1:]):
        chain = chain + 1 if b >= a else 1
        longest = max(longest, chain)
    return np.concatenate([base, [base[1] * base[2], base[2] * base[3], min(base[1:]),
                                  ordered, shift_consistency, tempo_consistency,
                                  min(1.0, 10 * longest / max(10.0, max(queries, default=0) + 10)),
                                  len(segments) / 3]])
