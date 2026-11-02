"""Train a small hard-negative pair verifier using automatic provenance labels."""
from __future__ import annotations
import json, random
from pathlib import Path
import numpy as np
from independent_features import pairwise_vector

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "api/runtime/locked_full_v2/results.jsonl",
         ROOT / "api/runtime/locked_shard_a/results.jsonl",
         ROOT / "api/runtime/locked_shard_b/results.jsonl"]

def features(candidate):
    return pairwise_vector(candidate)

def sigmoid(x):
    x = np.clip(x, -30, 30)
    return 1 / (1 + np.exp(-x))

def fit(x, y):
    mean, std = x.mean(0), np.maximum(x.std(0), 1e-6)
    z = (x - mean) / std
    w = np.zeros(z.shape[1]); b = 0.0
    positive_weight = max(1.0, float((y == 0).sum()) / max(1, (y == 1).sum()))
    weights = np.where(y == 1, positive_weight, 1.0)
    for step in range(6000):
        p = sigmoid(z @ w + b)
        error = (p - y) * weights / weights.sum()
        rate = 0.08 / (1 + step / 2000)
        w -= rate * (z.T @ error + 0.002 * w)
        b -= rate * error.sum()
    return mean, std, w, b

def auc(positive, negative):
    return sum((a > b) + .5 * (a == b) for a in positive for b in negative) / (len(positive) * len(negative))

def main():
    rows = []
    for path in FILES:
        rows += [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    groups = sorted({r["groupId"] for r in rows})
    random.Random(20261101).shuffle(groups)
    split = {g: "tune" if i < round(.6 * len(groups)) else "test" for i, g in enumerate(groups)}
    train_pairs = []
    for row in rows:
        if split[row["groupId"]] != "tune": continue
        for candidate in row["top3"]:
            label = int(row["dataset"] == "positive" and candidate["trackId"] == row["expectedTrackId"])
            train_pairs.append((features(candidate), label))
    x = np.stack([p[0] for p in train_pairs]); y = np.asarray([p[1] for p in train_pairs])
    mean, std, w, b = fit(x, y)
    def probability(candidate): return float(sigmoid(((features(candidate) - mean) / std) @ w + b))
    test = [r for r in rows if split[r["groupId"]] == "test"]
    pair_positive, pair_negative = [], []
    for row in test:
        for c in row["top3"]:
            score = probability(c)
            if row["dataset"] == "positive" and c["trackId"] == row["expectedTrackId"]: pair_positive.append(score)
            else: pair_negative.append(score)
    tune_rows = [r for r in rows if split[r["groupId"]] == "tune"]
    tune_positive = [max(probability(c) for c in r["top3"]) for r in tune_rows if r["dataset"] == "positive"]
    tune_safe = [max(probability(c) for c in r["top3"]) for r in tune_rows if r["dataset"] == "safe_music"]
    thresholds = sorted(set(tune_positive + tune_safe))
    recall_threshold = max(t for t in thresholds if sum(s >= t for s in tune_positive) / len(tune_positive) >= .90)
    precision_threshold = min(t for t in thresholds if sum(s >= t for s in tune_safe) / len(tune_safe) <= .05)
    def query_metrics(part, threshold):
        positive = [r for r in part if r["dataset"] == "positive"]
        safe = [r for r in part if r["dataset"] == "safe_music"]
        return {
            "positiveRecall": sum(max(probability(c) for c in r["top3"]) >= threshold for r in positive) / len(positive),
            "safeFalsePositiveRate": sum(max(probability(c) for c in r["top3"]) >= threshold for r in safe) / len(safe),
            "sourceTop1": sum(max(r["top3"], key=probability)["trackId"] == r["expectedTrackId"] for r in positive) / len(positive),
            "sourceTop3Ceiling": sum(r["expectedTrackId"] in [c["trackId"] for c in r["top3"]] for r in positive) / len(positive),
        }
    output = {"method": "weighted logistic hard-negative pair verifier",
              "features": ["clap", "pitch", "rhythm", "chroma", "pitch*rhythm", "rhythm*chroma", "min_acoustic", "ordered_fraction", "pitch_shift_consistency", "tempo_consistency", "longest_chain_fraction", "matched_segment_fraction"],
              "pairTestAuc": auc(pair_positive, pair_negative),
              "recallOperatingPoint": {"threshold": recall_threshold,
                  "tune": query_metrics(tune_rows, recall_threshold), "test": query_metrics(test, recall_threshold)},
              "precisionOperatingPoint": {"threshold": precision_threshold,
                  "tune": query_metrics(tune_rows, precision_threshold), "test": query_metrics(test, precision_threshold)},
              "standardizationMean": mean.tolist(), "standardizationStd": std.tolist(),
              "weights": w.tolist(), "bias": b}
    (ROOT / "api/runtime/pairwise_verifier_evaluation.json").write_text(json.dumps(output, indent=2), "utf-8")
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__": main()
