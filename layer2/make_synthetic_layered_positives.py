"""Generate held-out positives with a synthesized backing arrangement.

For 10 existing positive source works, keep the original recording audible and
add a generated pad, bass line, and percussion. The code estimates a global key
from chroma and writes a reproducible 4-minute synthetic test mix. This is an
automated robustness test; it is not a human cover or a claim of plagiarism.

Run from the repository root:
    python layer2/make_synthetic_layered_positives.py
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parent.parent
LAYER2 = ROOT / "layer2"
POSITIVE_DIR = LAYER2 / "test_data" / "reperformed_positive"
POSITIVE_MANIFEST = POSITIVE_DIR / "manifest.csv"
OUT_DIR = LAYER2 / "test_data" / "synthetic_layered_positive"
OUT_MANIFEST = OUT_DIR / "manifest.csv"
SAMPLE_RATE = 22_050
DURATION = 240
SEED = 20261001
SOURCE_COUNT = 10
WINDOW_SAMPLES = SAMPLE_RATE * DURATION

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def ffmpeg_path() -> str:
    """Find the FFmpeg executable used by the Layer 2 evaluation pipeline."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        raise SystemExit("FFmpeg or imageio-ffmpeg is required.") from error


def decode_source(ffmpeg: str, path: Path, offset: float) -> np.ndarray:
    """Decode a four-minute mono source excerpt without editing the source."""
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1",
         "-ss", f"{offset:.3f}", "-i", str(path), "-t", str(DURATION), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        check=True, capture_output=True,
    )
    audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    if len(audio) < WINDOW_SAMPLES:
        audio = np.pad(audio, (0, WINDOW_SAMPLES - len(audio)))
    return audio[:WINDOW_SAMPLES]


def estimate_key(audio: np.ndarray) -> tuple[int, str, np.ndarray]:
    """Estimate a rough key from a fast NumPy FFT pitch-class profile."""
    # A representative 30-second sample is enough. This small FFT-based
    # chroma estimate avoids optional audio-analysis packages and JIT startup.
    sample = audio[: SAMPLE_RATE * 30]
    frame_size, hop = 4096, 2048
    if len(sample) < frame_size:
        sample = np.pad(sample, (0, frame_size - len(sample)))
    frames = np.lib.stride_tricks.sliding_window_view(sample, frame_size)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(frame_size), axis=1)) ** 2
    frequencies = np.fft.rfftfreq(frame_size, 1.0 / SAMPLE_RATE)
    valid = (frequencies >= 27.5) & (frequencies <= 5000)
    midi = np.rint(69 + 12 * np.log2(frequencies[valid] / 440.0)).astype(int)
    pitch_classes = midi % 12
    distribution = np.bincount(
        pitch_classes, weights=spectrum[:, valid].mean(axis=0), minlength=12
    ).astype(np.float64)
    candidates: list[tuple[float, int, str]] = []
    for root in range(12):
        candidates.append((float(np.corrcoef(distribution, np.roll(MAJOR_PROFILE, root))[0, 1]), root, "major"))
        candidates.append((float(np.corrcoef(distribution, np.roll(MINOR_PROFILE, root))[0, 1]), root, "minor"))
    _, root, mode = max(candidates, key=lambda item: item[0])
    return root, mode, distribution


def synth_note(frequency: float, length: int, amplitude: float, kind: str) -> np.ndarray:
    """Create a small additive-synth note with a soft attack and release."""
    t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
    phase = 2 * np.pi * frequency * t
    if kind == "pad":
        wave = np.sin(phase) + 0.28 * np.sin(2 * phase + 0.15) + 0.08 * np.sin(3 * phase + 0.3)
        attack, release = int(0.12 * SAMPLE_RATE), int(0.3 * SAMPLE_RATE)
    else:
        wave = np.sin(phase) + 0.16 * np.sin(2 * phase)
        attack, release = int(0.006 * SAMPLE_RATE), int(0.08 * SAMPLE_RATE)
    envelope = np.ones(length, dtype=np.float32)
    if attack:
        envelope[:attack] = np.linspace(0, 1, min(attack, length), dtype=np.float32)
    if release:
        envelope[-release:] *= np.linspace(1, 0, min(release, length), dtype=np.float32)
    if kind == "pad":
        envelope *= 0.86 + 0.14 * np.sin(2 * np.pi * 0.18 * t)
    return amplitude * wave.astype(np.float32) * envelope


def midi_frequency(note: int) -> float:
    """Convert a MIDI note number to frequency in Hz."""
    return 440.0 * 2 ** ((note - 69) / 12)


def synth_backing(root: int, mode: str, seed: int) -> np.ndarray:
    """Render four-chord pad plus simple bass/percussion to accompany the song."""
    rng = np.random.default_rng(seed)
    layer = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
    progression = [0, 7, 9, 5] if mode == "major" else [0, 7, 3, 8]
    third = 4 if mode == "major" else 3
    bar_seconds = 3.2  # 4/4 at a synthetic 75 BPM; deliberately independent of source tempo.
    bar_samples = int(bar_seconds * SAMPLE_RATE)

    # Hold a soft triad for each bar. The dissonance/tempo gap is intentional:
    # it checks whether CLAP still retrieves the underlying source in a remix.
    for bar_start in range(0, WINDOW_SAMPLES, bar_samples):
        chord_index = (bar_start // bar_samples) % len(progression)
        chord_root = (root + progression[chord_index]) % 12
        chord_notes = [48 + chord_root, 48 + (chord_root + third) % 12,
                       48 + (chord_root + 7) % 12, 60 + chord_root]
        note_length = min(bar_samples, WINDOW_SAMPLES - bar_start)
        for note in chord_notes:
            note_wave = synth_note(midi_frequency(note), note_length, 0.032, "pad")
            layer[bar_start:bar_start + note_length] += note_wave

    # Add a low synthesized bass pulse and sparse noise percussion each beat.
    beat_samples = SAMPLE_RATE * 800 // 1000
    for beat_start in range(0, WINDOW_SAMPLES, beat_samples):
        bar_index = beat_start // bar_samples
        chord_root = (root + progression[bar_index % len(progression)]) % 12
        bass_len = min(int(0.28 * SAMPLE_RATE), WINDOW_SAMPLES - beat_start)
        bass = synth_note(midi_frequency(36 + chord_root), bass_len, 0.10, "pluck")
        layer[beat_start:beat_start + bass_len] += bass
        # Quiet synthetic hi-hat-like noise: reproducible for every seed.
        if (beat_start // beat_samples) % 2 == 1:
            noise_len = min(int(0.055 * SAMPLE_RATE), WINDOW_SAMPLES - beat_start)
            noise = rng.normal(0, 0.018, noise_len).astype(np.float32)
            noise *= np.linspace(1, 0, noise_len, dtype=np.float32)
            layer[beat_start:beat_start + noise_len] += noise
    return layer


def load_source_rows() -> list[dict[str, str]]:
    """Select one known positive source row per work, in stable order."""
    if not POSITIVE_MANIFEST.is_file():
        raise SystemExit(f"Missing positive manifest: {POSITIVE_MANIFEST}")
    with POSITIVE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    by_source: dict[str, dict[str, str]] = {}
    for row in rows:
        if Path(row["source_path"]).is_file():
            by_source.setdefault(row["source_track_id"], row)
    return [by_source[key] for key in sorted(by_source)[:SOURCE_COUNT]]


def main() -> None:
    """Create 10 reproducible synthetic instrument-overlay positives."""
    ffmpeg = ffmpeg_path()
    source_rows = load_source_rows()
    if len(source_rows) < SOURCE_COUNT:
        raise SystemExit(f"Need {SOURCE_COUNT} source works; found {len(source_rows)}.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if OUT_MANIFEST.is_file():
        with OUT_MANIFEST.open("r", newline="", encoding="utf-8-sig") as handle:
            existing = list(csv.DictReader(handle))
    existing_sources = {row.get("source_track_id") for row in existing}
    fieldnames = ["query_path", "source_path", "source_track_id", "case_type", "duration_seconds",
                  "estimated_key", "seed", "parameters_json", "label"]
    new_rows: list[dict[str, str]] = []

    for index, row in enumerate(source_rows, start=1):
        source_id = row["source_track_id"]
        output_path = OUT_DIR / f"{source_id}__synth_instrument_layer.wav"
        if source_id in existing_sources and output_path.is_file():
            print(f"[skip] already generated: {output_path.name}")
            continue
        source_path = Path(row["source_path"])
        source_offset = float(row.get("source_offset_seconds", "0") or 0)
        # Use the same source excerpt origin recorded for the positive test.
        print(f"[{index}/{SOURCE_COUNT}] decoding {source_id}", flush=True)
        source = decode_source(ffmpeg, source_path, source_offset)
        root, mode, chroma = estimate_key(source)
        backing = synth_backing(root, mode, SEED + index)
        # Keep the original clearly present while adding a new synthetic mix layer.
        mixed = 0.86 * source + 0.34 * backing
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.98:
            mixed *= 0.98 / peak
        sf.write(output_path, mixed, SAMPLE_RATE, subtype="PCM_16")
        new_rows.append({
            "query_path": str(output_path.resolve()),
            "source_path": str(source_path.resolve()),
            "source_track_id": source_id,
            "case_type": "synth_pad_bass_percussion_overlay",
            "duration_seconds": f"{len(mixed) / SAMPLE_RATE:.3f}",
            "estimated_key": f"{NOTE_NAMES[root]} {mode}",
            "seed": str(SEED + index),
            "parameters_json": json.dumps({
                "original_gain": 0.86, "synthetic_layer_gain": 0.34,
                "synth_instruments": ["pad_chords", "bass_pulse", "hi_hat_noise"],
                "estimated_key": f"{NOTE_NAMES[root]} {mode}",
                "chroma_profile": [round(float(value), 5) for value in chroma],
                "voice_sample": "not included; external voice sample download was rate-limited",
            }, ensure_ascii=False),
            "label": "positive_synthetic_instrument_overlay",
        })
        print(f"[{index}/{SOURCE_COUNT}] {source_id} | {NOTE_NAMES[root]} {mode} | {len(mixed)/SAMPLE_RATE:.0f}s", flush=True)

    if new_rows:
        write_header = not OUT_MANIFEST.is_file() or OUT_MANIFEST.stat().st_size == 0
        with OUT_MANIFEST.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
    print(f"Generated {len(new_rows)} files in {OUT_DIR}")
    print(f"Manifest: {OUT_MANIFEST}")


if __name__ == "__main__":
    main()
