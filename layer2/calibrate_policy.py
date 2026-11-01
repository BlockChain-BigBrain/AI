"""Tune aggregation rules on the tune split and report locked metrics.

This script never changes runtime thresholds. It reads the evaluator's detail CSV,
fits only on rows with split=tune, and reports the selected rule on split=test.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from decision_policy import PolicyConfig, classify_segments, evaluate_rates

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "layer2" / "artifacts"
DETAILS = ARTIFACT_DIR / "top3_aggregation_details.csv"
OUTPUT = ARTIFACT_DIR / "policy_calibration_candidate.json"


def load_rows() -> list[dict]:
    with DETAILS.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def segments(row: dict) -> list[float]:
    try:
        matches = json.loads(row.get("top5_matches", "[]"))
    except json.JSONDecodeError:
        matches = []
    if isinstance(matches, list):
        for candidate in matches:
            if candidate.get("track_id") == row.get("top_track_id"):
                value = candidate.get("seg_top3_query_starts")
                if isinstance(value, list):
                    return [float(row.get("top_score", 0.0)) for _ in value]
    return [float(row.get("top_score", 0.0))]


def fit(rows: list[dict]) -> dict:
    tune = [row for row in rows if row.get("split") == "tune"]
    test = [row for row in rows if row.get("split") == "test"]
    candidates = []
    for min_warn in (2, 3):
        for min_hold in (2, 3):
            for corroboration in (1, 2):
                config = PolicyConfig(
                    warn_threshold=0.8566381335,
                    hold_threshold=0.8944060206,
                    min_warn_segments=min_warn,
                    min_hold_segments=min_hold,
                )
                labels = []
                for row in tune:
                    result = classify_segments(
                        segments(row), config=config,
                        corroborating_scores=segments(row),
                    )
                    labels.append((row.get("label"), result))
                normal = [result for label, result in labels if label == "safe"]
                positive = [result for label, result in labels if label == "positive"]
                fpr = sum(result["decision"] in ("WARN", "HOLD") for result in normal) / max(1, len(normal))
                recall = sum(result["decision"] in ("WARN", "HOLD") for result in positive) / max(1, len(positive))
                hold_fpr = sum(result["decision"] == "HOLD" for result in normal) / max(1, len(normal))
                if fpr <= 0.10 and hold_fpr <= 0.02:
                    candidates.append((recall, -fpr, -hold_fpr, min_warn, min_hold, corroboration))
    if not candidates:
        raise RuntimeError("No tune-only policy satisfies WARN<=10% and HOLD<=2%")
    best = max(candidates)
    _, _, _, min_warn, min_hold, corroboration = best
    config = PolicyConfig(
        warn_threshold=0.8566381335,
        hold_threshold=0.8944060206,
        min_warn_segments=min_warn,
        min_hold_segments=min_hold,
    )
    normal = [classify_segments(segments(row), config=config, corroborating_scores=segments(row)) for row in test if row.get("label") == "safe"]
    positive = [classify_segments(segments(row), config=config, corroborating_scores=segments(row)) for row in test if row.get("label") == "positive"]
    metrics = evaluate_rates(
        warn_or_hold_false_positives=sum(item["decision"] in ("WARN", "HOLD") for item in normal),
        hold_false_positives=sum(item["decision"] == "HOLD" for item in normal),
        normal_count=len(normal),
        positive_warn_or_hold_hits=sum(item["decision"] in ("WARN", "HOLD") for item in positive),
        positive_hold_hits=sum(item["decision"] == "HOLD" for item in positive),
        positive_count=len(positive),
    )
    return {
        "status": "candidate_only",
        "fitSplit": "tune",
        "evaluationSplit": "test_locked",
        "policy": {
            "minWarnSegments": min_warn,
            "minHoldSegments": min_hold,
            "corroborationVotes": corroboration,
            "warnThreshold": config.warn_threshold,
            "holdThreshold": config.hold_threshold,
        },
        "lockedMetrics": metrics,
        "runtimeChangeAuthorized": False,
    }


if __name__ == "__main__":
    result = fit(load_rows())
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
