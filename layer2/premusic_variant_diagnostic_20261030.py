"""Evaluate 30 premusic sources after basic and instrument-layer transformations.

This is a separate diagnostic index. It does not change production thresholds.
It compares key-transposed Chroma/CQT sequences and a sustained rhythm/onset
flow independently, then reports whether the source is recovered in Top-K.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import argparse
from pathlib import Path

import numpy as np

from tonal_alignment import compare, features

ROOT = Path(__file__).resolve().parents[1]
SEL = ROOT / ".runtime-tests" / "new-premusic-20261030" / "selection.json"
VARIANTS = ROOT / "layer2" / "artifacts" / "premusic_variants_20261030.json"
OUT = ROOT / "layer2" / "artifacts" / "premusic_variant_diagnostic_20261030.json"
CACHE = ROOT / ".runtime-tests" / "new-premusic-20261030" / "tonal-cache"
SR = 22050


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def rhythm(path: Path, exe: str) -> np.ndarray:
    if path.suffix.lower() == ".wav":
        import soundfile as sf
        x, sr = sf.read(path, dtype="float32", always_2d=False)
        if x.ndim > 1: x = x.mean(axis=1)
    else:
        result = subprocess.run([exe, "-v", "error", "-nostdin", "-i", str(path), "-t", "90", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"], check=True, capture_output=True)
        x = np.frombuffer(result.stdout, dtype="<f4")
        sr = SR
    x = np.asarray(x, dtype=np.float32)
    hop = max(1, int(sr * .1))
    count = len(x) // hop
    if count < 10: return np.zeros(10, dtype=np.float32)
    rms = np.sqrt(np.mean(x[:count * hop].reshape(count, hop) ** 2, axis=1) + 1e-8)
    onset = np.maximum(0, np.diff(rms, prepend=rms[0]))
    onset -= onset.mean(); onset /= max(np.linalg.norm(onset), 1e-8)
    return onset


def rhythm_score(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b)); a, b = a[:n], b[:n]
    if n < 10: return 0.0
    best = -1.0
    for lag in range(-20, 21):
        if lag >= 0: x, y = a[lag:], b[:n-lag]
        else: x, y = a[:n+lag], b[-lag:]
        if len(x) >= 10: best = max(best, float(np.dot(x, y) / max(np.linalg.norm(x) * np.linalg.norm(y), 1e-8)))
    return best


def recall(rows, key, k):
    return sum(row[key + "_rank"] <= k for row in rows) / len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=SEL)
    parser.add_argument("--variants", type=Path, default=VARIANTS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    variants = json.loads(args.variants.read_text(encoding="utf-8"))["rows"]
    sources = [Path(item["path"]) for item in selection["selected"]]
    by_source = {str(path): i for i, path in enumerate(sources)}
    exe = ffmpeg(); CACHE.mkdir(parents=True, exist_ok=True)
    tonal_cache = {}
    rhythm_cache = {}
    def tonal_for(path):
        key = str(path)
        if key not in tonal_cache: tonal_cache[key] = features(path, exe, CACHE)
        return tonal_cache[key]
    def rhythm_for(path):
        key = str(path)
        if key not in rhythm_cache: rhythm_cache[key] = rhythm(path, exe)
        return rhythm_cache[key]
    reference_tonal = [tonal_for(path)[0] for path in sources]
    reference_rhythm = [rhythm_for(path) for path in sources]
    results = []
    for item in variants:
        source_index = by_source[item["source"]]
        query = Path(item["path"])
        q_tonal = tonal_for(query)[0]
        q_rhythm = rhythm_for(query)
        tonal_scores = [compare(q_tonal, ref)["tonalScore"] for ref in reference_tonal]
        rhythm_scores = [rhythm_score(q_rhythm, ref) for ref in reference_rhythm]
        tonal_order = sorted(range(len(sources)), key=lambda i: tonal_scores[i], reverse=True)
        rhythm_order = sorted(range(len(sources)), key=lambda i: rhythm_scores[i], reverse=True)
        result = {"source": item["source"], "variant": item["variant"], "path": item["path"],
                  "source_index": source_index, "tonal_score": tonal_scores[source_index],
                  "rhythm_score": rhythm_scores[source_index],
                  "tonal_rank": tonal_order.index(source_index) + 1,
                  "rhythm_rank": rhythm_order.index(source_index) + 1,
                  "tonal_top5": [str(sources[i]) for i in tonal_order[:5]],
                  "rhythm_top5": [str(sources[i]) for i in rhythm_order[:5]]}
        results.append(result)
        print(f"[diagnostic {len(results)}/{len(variants)}] {query.name} tonal={result['tonal_rank']} rhythm={result['rhythm_rank']}", flush=True)
    summary = {}
    for variant in ("basic_pitch_key_tempo", "instrument_layer"):
        rows = [row for row in results if row["variant"] == variant]
        summary[variant] = {"count": len(rows),
                            "tonal_recall_at_1": recall(rows, "tonal", 1), "tonal_recall_at_3": recall(rows, "tonal", 3), "tonal_recall_at_5": recall(rows, "tonal", 5),
                            "rhythm_recall_at_1": recall(rows, "rhythm", 1), "rhythm_recall_at_3": recall(rows, "rhythm", 3), "rhythm_recall_at_5": recall(rows, "rhythm", 5),
                            "tonal_missed_names": [Path(r["path"]).name for r in rows if r["tonal_rank"] > 5],
                            "rhythm_missed_names": [Path(r["path"]).name for r in rows if r["rhythm_rank"] > 5]}
    args.out.write_text(json.dumps({"date": "2026-10-30", "production_thresholds_changed": False,
                               "method": "all-12-key-transposition Chroma/CQT tonal alignment plus separate onset-rhythm correlation",
                               "summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
