"""Evaluate whether independent features improve CLAP Top-3 ordering."""
from __future__ import annotations
import json, random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "api/runtime/locked_full_v2/results.jsonl",
         ROOT / "api/runtime/locked_shard_a/results.jsonl",
         ROOT / "api/runtime/locked_shard_b/results.jsonl"]

def rank(row, weight):
    ranked = []
    for candidate in row["top3"]:
        f = candidate["featureEvidence"]
        feature = .4 * f["pitchScore"] + .35 * f["chromaScore"] + .25 * f["rhythmScore"]
        score = (1 - weight) * candidate["score"] + weight * feature
        ranked.append((score, candidate["trackId"]))
    return [track for _, track in sorted(ranked, reverse=True)]

def metrics(rows, weight):
    positive = [r for r in rows if r["dataset"] == "positive"]
    return {
        "top1": sum(rank(r, weight)[0] == r["expectedTrackId"] for r in positive) / len(positive),
        "top3": sum(r["expectedTrackId"] in rank(r, weight) for r in positive) / len(positive),
    }

def auc(positive, negative):
    return sum((a > b) + 0.5 * (a == b) for a in positive for b in negative) / (
        len(positive) * len(negative))

def feature_diagnostics(rows):
    result = {}
    for key in ("clap", "pitch", "rhythm", "chroma"):
        def value(row):
            candidate = row["top3"][0]
            return candidate["score"] if key == "clap" else candidate["featureEvidence"][key + "Score"]
        positive = [value(r) for r in rows if r["dataset"] == "positive"]
        safe = [value(r) for r in rows if r["dataset"] == "safe_music"]
        result[key] = {"auc": auc(positive, safe),
                       "positiveMedian": statistics.median(positive),
                       "safeMedian": statistics.median(safe)}
    return result

def main():
    rows = []
    for path in FILES:
        rows.extend(json.loads(line) for line in path.read_text("utf-8").splitlines())
    groups = sorted({r["groupId"] for r in rows})
    random.Random(20261101).shuffle(groups)
    split = {g: "tune" if i < round(.6 * len(groups)) else "test" for i, g in enumerate(groups)}
    tune = [r for r in rows if split[r["groupId"]] == "tune"]
    test = [r for r in rows if split[r["groupId"]] == "test"]
    results = {str(w): {"tune": metrics(tune, w), "test": metrics(test, w)}
               for w in (0, .1, .2, .3, .4, .5, .6, .7, .8)}
    best = max(results, key=lambda w: (results[w]["tune"]["top3"], results[w]["tune"]["top1"]))
    output = {"feature": ".4 pitch + .35 chroma + .25 rhythm", "diagnostics": feature_diagnostics(rows),
              "weights": results,
              "selectedWeight": float(best), "selectedTest": results[best]["test"]}
    (ROOT / "api/runtime/feature_fusion_evaluation.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
