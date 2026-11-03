"""Leakage-resistant model selection for nonlinear pairwise verifiers.

Model choice and thresholds use validation only. The grouped test split and
premusic test controls are evaluated once after selection.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_pairwise_verifier import features

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "api" / "runtime"
AI_FILES = [RUNTIME / "locked_full_v2" / "results.jsonl",
            RUNTIME / "locked_shard_a" / "results.jsonl",
            RUNTIME / "locked_shard_b" / "results.jsonl"]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def grouped_split(rows):
    groups = sorted({r["groupId"] for r in rows})
    random.Random(20261102).shuffle(groups)
    n = len(groups)
    a, b = round(.50 * n), round(.75 * n)
    mapping = {g: ("train" if i < a else "validation" if i < b else "test")
               for i, g in enumerate(groups)}
    return mapping


def query_score(model, row):
    x = np.stack([features(c) for c in row["top3"]])
    return float(model.predict_proba(x)[:, 1].max())


def choose_threshold(scores, labels, target_recall=.90):
    positives = scores[labels == 1]
    candidates = sorted(set(scores.tolist()))
    eligible = [t for t in candidates if np.mean(positives >= t) >= target_recall]
    return max(eligible) if eligible else min(candidates)


def choose_hold(scores, labels, max_fpr=.05):
    negatives = scores[labels == 0]
    candidates = sorted(set(scores.tolist()))
    eligible = [t for t in candidates if np.mean(negatives >= t) <= max_fpr]
    return min(eligible) if eligible else max(candidates)


def metrics(scores, labels, threshold):
    p, n = labels == 1, labels == 0
    return {"positiveRecall": float(np.mean(scores[p] >= threshold)),
            "safeFalsePositiveRate": float(np.mean(scores[n] >= threshold)),
            "positiveCount": int(p.sum()), "safeCount": int(n.sum())}


def main():
    ai = sum((read_jsonl(p) for p in AI_FILES), [])
    split = grouped_split(ai)

    x, y = [], []
    for row in ai:
        if split[row["groupId"]] != "train":
            continue
        for c in row["top3"]:
            x.append(features(c))
            y.append(int(row["dataset"] == "positive" and c["trackId"] == row["expectedTrackId"]))

    minimal = read_jsonl(RUNTIME / "premusic_minimal_results.jsonl")
    for row in minimal:
        if row["selectionSplit"] == "train":
            for c in row["top3"]:
                x.append(features(c)); y.append(0)
    mined_path = RUNTIME / "premusic_mined_train.jsonl"
    mined = read_jsonl(mined_path) if mined_path.exists() else []
    for row in mined:
        if row.get("decision") in ("WARN", "HOLD"):
            for c in row["similarTracks"]:
                x.append(features(c)); y.append(0)
    x, y = np.stack(x), np.asarray(y)

    def eval_rows(name):
        rows = []
        for row in ai:
            if split[row["groupId"]] == name:
                rows.append((row, int(row["dataset"] == "positive")))
        for row in minimal:
            if row["selectionSplit"] == name:
                rows.append(({"top3": row["top3"]}, 0))
        return rows

    val_rows, test_rows = eval_rows("validation"), eval_rows("test")
    models = {
        "logistic_l2": make_pipeline(StandardScaler(), LogisticRegression(
            C=.5, class_weight="balanced", max_iter=3000, random_state=20261102)),
        "random_forest": RandomForestClassifier(n_estimators=500, min_samples_leaf=3,
            max_features=.75, class_weight="balanced_subsample", n_jobs=-1, random_state=20261102),
        "extra_trees": ExtraTreesClassifier(n_estimators=500, min_samples_leaf=3,
            max_features=.75, class_weight="balanced", n_jobs=-1, random_state=20261102),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=250,
            learning_rate=.04, max_leaf_nodes=12, min_samples_leaf=10,
            l2_regularization=1.0, class_weight="balanced", random_state=20261102),
    }

    reports = {}
    for name, model in models.items():
        model.fit(x, y)
        vs = np.asarray([query_score(model, r) for r, _ in val_rows])
        vy = np.asarray([label for _, label in val_rows])
        warn, hold = choose_threshold(vs, vy), choose_hold(vs, vy)
        reports[name] = {"warnThreshold": warn, "holdThreshold": hold,
                         "validationWarn": metrics(vs, vy, warn),
                         "validationHold": metrics(vs, vy, hold)}

    # Select on validation only: lowest WARN FPR, then highest HOLD recall.
    chosen = min(reports, key=lambda n: (
        reports[n]["validationWarn"]["safeFalsePositiveRate"],
        -reports[n]["validationHold"]["positiveRecall"]))
    model = models[chosen]
    ts = np.asarray([query_score(model, r) for r, _ in test_rows])
    ty = np.asarray([label for _, label in test_rows])
    reports[chosen]["testWarn"] = metrics(ts, ty, reports[chosen]["warnThreshold"])
    reports[chosen]["testHold"] = metrics(ts, ty, reports[chosen]["holdThreshold"])

    output = {"protocol": "grouped 50/25/25; validation-only model/threshold selection",
              "trainingPairs": int(len(y)), "trainingPositivePairs": int(y.sum()),
              "trainingNegativePairs": int((y == 0).sum()),
              "selectedModel": chosen, "models": reports,
              "premusicPolicy": "train controls fit; validation selects; test evaluated once"}
    (RUNTIME / "nonlinear_verifier_evaluation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    joblib.dump(model, RUNTIME / "nonlinear_verifier.joblib")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
