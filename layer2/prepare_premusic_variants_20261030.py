"""Create 30 basic pitch/key-tempo variants and 30 instrument-layer variants."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SEL = ROOT / ".runtime-tests" / "new-premusic-20261030" / "selection.json"
OUT = ROOT / ".runtime-tests" / "new-premusic-20261030" / "variants"
REPORT = ROOT / "layer2" / "artifacts" / "premusic_variants_20261030.json"
SR = 22050
DURATION = 90
N = SR * DURATION


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def decode(path: Path, exe: str) -> np.ndarray:
    result = subprocess.run([exe, "-v", "error", "-nostdin", "-stream_loop", "-1", "-i", str(path),
                             "-t", str(DURATION), "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"],
                            check=True, capture_output=True)
    x = np.frombuffer(result.stdout, dtype="<f4").astype(np.float32)
    if len(x) < N:
        x = np.pad(x, (0, N - len(x)))
    return x[:N]


def estimate_root(x: np.ndarray) -> int:
    frame = x[: SR * 30]
    spec = np.abs(np.fft.rfft(frame[: min(len(frame), SR * 30)] * np.hanning(min(len(frame), SR * 30))))
    freq = np.fft.rfftfreq(len(frame[: min(len(frame), SR * 30)]), 1 / SR)
    valid = (freq >= 55) & (freq <= 1760)
    midi = np.rint(69 + 12 * np.log2(freq[valid] / 440)).astype(int) % 12
    bins = np.bincount(midi, weights=spec[valid], minlength=12)
    return int(np.argmax(bins))


def note(midi: int, length: int, amp: float) -> np.ndarray:
    t = np.arange(length, dtype=np.float32) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    y = np.sin(2 * np.pi * f * t) + .25 * np.sin(4 * np.pi * f * t)
    env = np.ones(length, dtype=np.float32)
    attack = min(length, int(.04 * SR)); release = min(length, int(.18 * SR))
    env[:attack] = np.linspace(0, 1, attack, dtype=np.float32)
    env[-release:] *= np.linspace(1, 0, release, dtype=np.float32)
    return amp * y.astype(np.float32) * env


def layer(x: np.ndarray, root: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y = np.zeros_like(x)
    bar = int(2.8 * SR)
    progression = (0, 7, 9, 5)
    for start in range(0, N, bar):
        chord = (root + progression[(start // bar) % 4]) % 12
        length = min(bar, N - start)
        for midi in (48 + chord, 52 + chord, 55 + chord):
            y[start:start + length] += note(midi, length, .025)
    beat = int(.7 * SR)
    for start in range(0, N, beat):
        length = min(int(.12 * SR), N - start)
        y[start:start + length] += note(36 + root, length, .07)
        if (start // beat) % 2:
            noise = rng.normal(0, .012, length).astype(np.float32)
            y[start:start + length] += noise * np.linspace(1, 0, length, dtype=np.float32)
    mixed = .84 * x + .38 * y
    peak = float(np.max(np.abs(mixed)))
    return mixed * (.98 / peak if peak > .98 else 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=SEL)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    sources = selection["selected"]
    if len(sources) != 30:
        raise RuntimeError("Expected 30 variant sources")
    exe = ffmpeg(); args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, item in enumerate(sources):
        source = Path(item["path"])
        root = estimate_root(decode(source, exe))
        basic = args.out / f"{i:02d}__basic_pitch_key_tempo.wav"
        layered = args.out / f"{i:02d}__instrument_layer.wav"
        # +2 semitones, small tempo change, then restore a comparable duration.
        ratio = 2 ** (2 / 12)
        subprocess.run([exe, "-v", "error", "-nostdin", "-y", "-i", str(source), "-t", str(DURATION),
                        "-af", f"aresample=48000,asetrate=48000*{ratio:.8f},aresample=48000,atempo={1/ratio:.8f},atempo=0.96",
                        "-ar", str(SR), "-ac", "1", str(basic)], check=True, capture_output=True)
        sf.write(layered, layer(decode(source, exe), root, 20261030 + i), SR, subtype="PCM_16")
        rows.extend([
            {"source": str(source), "source_sha256": item["sha256"], "variant": "basic_pitch_key_tempo",
             "path": str(basic), "root_pitch_class": root, "parameters": {"semitones": 2, "tempo_scale": .96}},
            {"source": str(source), "source_sha256": item["sha256"], "variant": "instrument_layer",
             "path": str(layered), "root_pitch_class": root, "parameters": {"pad": True, "bass": True, "percussion": True}},
        ])
        print(f"[variants {i + 1}/30] {source.name}", flush=True)
    args.report.write_text(json.dumps({"date": "2026-10-30", "source_count": 30, "variant_count": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source_count": 30, "variant_count": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
