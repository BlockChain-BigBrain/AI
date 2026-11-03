"""Calibrate current runtime thresholds on automatically labeled AI variants."""
from __future__ import annotations
import json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = [ROOT / "api/runtime/locked_full_v2/results.jsonl",
          ROOT / "api/runtime/locked_shard_a/results.jsonl",
          ROOT / "api/runtime/locked_shard_b/results.jsonl"]

def load():
    rows = []
    for path in INPUTS:
        rows.extend(json.loads(line) for line in path.read_text("utf-8").splitlines())
    return rows

def with_fusion(rows, weight=0.5):
    for row in rows:
        for candidate in row["top3"]:
            f = candidate["featureEvidence"]
            feature = .4 * f["pitchScore"] + .35 * f["chromaScore"] + .25 * f["rhythmScore"]
            candidate["fusionScore"] = (1 - weight) * candidate["score"] + weight * feature
        row["decisionScore"] = max(c["fusionScore"] for c in row["top3"])

def choose(rows, hold_fpr=0.05, warn_recall=0.90):
    safe = [float(r["decisionScore"]) for r in rows if r["dataset"] == "safe_music"]
    positive = [float(r["decisionScore"]) for r in rows if r["dataset"] == "positive"]
    candidates = sorted(set(safe + positive))
    hold_options = [t for t in candidates if sum(s >= t for s in safe) / len(safe) <= hold_fpr]
    warn_options = [t for t in candidates if sum(p >= t for p in positive) / len(positive) >= warn_recall]
    return max(warn_options) if warn_options else None, min(hold_options) if hold_options else None

def metrics(rows, warn, hold):
    p = [r for r in rows if r["dataset"] == "positive"]
    s = [r for r in rows if r["dataset"] == "safe_music"]
    return {
        "positiveWarnOrHoldRate": sum(float(r["decisionScore"]) >= warn for r in p) / len(p),
        "safeWarnOrHoldRate": sum(float(r["decisionScore"]) >= warn for r in s) / len(s),
        "safeHoldRate": sum(float(r["decisionScore"]) >= hold for r in s) / len(s),
        "positiveCount": len(p), "safeCount": len(s),
    }

def main():
    rows = load()
    with_fusion(rows)
    groups = sorted({r["groupId"] for r in rows})
    random.Random(20261101).shuffle(groups)
    cut = round(len(groups) * 0.6)
    split = {g: "tune" if i < cut else "test" for i, g in enumerate(groups)}
    tune = [r for r in rows if split[r["groupId"]] == "tune"]
    test = [r for r in rows if split[r["groupId"]] == "test"]
    warn, hold = choose(tune)
    result = {
        "method": "source-group split over automatically labeled AI variants",
        "seed": 20261101, "groupCount": len(groups), "tuneGroups": cut,
        "testGroups": len(groups) - cut, "warn": warn, "hold": hold,
        "tune": metrics(tune, warn, hold), "test": metrics(test, warn, hold),
        "all": metrics(rows, warn, hold),
        "source": "locked runtime results; no human labels used",
    }
    out = ROOT / "api/runtime/ai_calibrated_policy.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
