"""Compare six CLAP Top-3 candidate aggregation variants and calibrate thresholds.

This is a retrieval/risk-score experiment, not an automated legal plagiarism
verdict. Positive and safe source works are kept entirely in either the tune
split or the held-out test split. Synthetic safe_arranged controls are reported
separately because their negative label has not been independently verified.

Run from the repository root with the same Python environment used for CLAP:
    python layer2/evaluate_top3_aggregation.py
"""

from __future__ import annotations

import csv
import json
import math
import random
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import ClapAudioModelWithProjection, ClapProcessor

import evaluate_retrieval_baseline as baseline


ARTIFACT_DIR = baseline.ARTIFACT_DIR
OUTPUT_JSON = ARTIFACT_DIR / "top3_aggregation_evaluation.json"
OUTPUT_CSV = ARTIFACT_DIR / "top3_aggregation_details.csv"
SAFE_ARRANGED_MANIFEST = baseline.LAYER2_DIR / "test_data" / "safe_arranged" / "manifest.csv"
LAYERED_POSITIVE_MANIFEST = baseline.LAYER2_DIR / "test_data" / "synthetic_layered_positive" / "manifest.csv"
SEED = 20260930
TUNE_FRACTION = 0.60
HOLD_FPR_TARGET = 0.05
WARN_RECALL_TARGET = 0.90
TOP_K = 5


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 or UTF-8-with-BOM CSV manifest."""
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def group_split(group_ids: set[str]) -> dict[str, str]:
    """Assign whole source works to tune/test with a stable shuffled split."""
    ordered = sorted(group_ids)
    random.Random(SEED).shuffle(ordered)
    if len(ordered) < 2:
        return {group: "tune" for group in ordered}
    tune_count = min(len(ordered) - 1, max(1, round(len(ordered) * TUNE_FRACTION)))
    return {
        group: ("tune" if index < tune_count else "test")
        for index, group in enumerate(ordered)
    }


def unit_rows(vectors: np.ndarray) -> np.ndarray:
    """Normalize each vector and safely handle empty input."""
    if not len(vectors):
        return vectors.astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def non_overlapping_top3(scores: np.ndarray, offsets: list[float]) -> tuple[float, list[int]]:
    """Average up to three strongest query windows, suppressing overlap.

    A window can be selected only when it starts at least one full window
    duration after every already selected window. This avoids counting two
    nearly identical 5-second-overlap windows as independent evidence.
    """
    per_window = scores.max(axis=1)
    ranked = np.argsort(per_window)[::-1]
    selected: list[int] = []
    for index in ranked:
        if all(abs(offsets[int(index)] - offsets[other]) >= baseline.WINDOW_SECONDS
               for other in selected):
            selected.append(int(index))
            if len(selected) == 3:
                break
    if not selected:
        return float("-inf"), []
    return float(np.mean(per_window[selected])), selected


def score_all_tracks(
    query_vectors: np.ndarray,
    offsets: list[float],
    reference_vectors: np.ndarray,
    reference_ids: np.ndarray,
    reference_offsets: np.ndarray,
    center_mean: np.ndarray,
) -> dict[str, list[dict[str, Any]]]:
    """Score each reference track with three aggregators, raw and centered."""
    modes = [f"{aggregation}_{centering}" for aggregation in ("max", "mean_emb", "seg_top3")
             for centering in ("raw", "centered")]
    outputs: dict[str, list[dict[str, Any]]] = {mode: [] for mode in modes}

    # Centering follows the submitted proposal: subtract a global reference
    # embedding mean, then re-normalize vectors before cosine comparison.
    variants = {
        "raw": (unit_rows(query_vectors), unit_rows(reference_vectors)),
        "centered": (
            unit_rows(query_vectors - center_mean),
            unit_rows(reference_vectors - center_mean),
        ),
    }
    for centering, (queries, references) in variants.items():
        similarities = queries @ references.T
        for track_id in np.unique(reference_ids):
            indices = np.flatnonzero(reference_ids == track_id)
            ordered = indices[np.argsort(reference_offsets[indices], kind="stable")]
            local = similarities[:, ordered]
            # Strongest single pair; useful as a high-recall retrieval score,
            # but vulnerable to one accidental window match.
            q_idx, r_idx = np.unravel_index(np.argmax(local), local.shape)
            max_score = float(local[q_idx, r_idx])
            # One mean representation per complete track and query. This may
            # dilute short copied sections, so it is included as an ablation.
            query_mean = unit_rows(queries.mean(axis=0, keepdims=True))[0]
            track_mean = unit_rows(references[ordered].mean(axis=0, keepdims=True))[0]
            mean_score = float(query_mean @ track_mean)
            segment_score, chosen = non_overlapping_top3(local, offsets)
            common = {
                "track_id": str(track_id),
                "max_score": max_score,
                "mean_emb_score": mean_score,
                "seg_top3_score": segment_score,
                "query_start_seconds": float(offsets[int(q_idx)]),
                "reference_start_seconds": float(reference_offsets[ordered[int(r_idx)]]),
                "seg_top3_query_starts": [float(offsets[i]) for i in chosen],
            }
            for aggregation in ("max", "mean_emb", "seg_top3"):
                mode = f"{aggregation}_{centering}"
                outputs[mode].append({**common, "score": common[f"{aggregation}_score"]})

    for mode in modes:
        outputs[mode].sort(key=lambda row: float(row["score"]), reverse=True)
    return outputs


def build_queries(train_track_ids: set[str]) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    """Load positives, safe tracks, and unverified safe-arranged controls."""
    positives, held_out = baseline.read_positive_queries(train_track_ids)
    positives.extend(baseline.read_reperformance_queries(train_track_ids))
    # Add generated instrumental-layer tests under the same source group,
    # so every variant of one original stays together in tune or test.
    for row in read_csv(LAYERED_POSITIVE_MANIFEST):
        source_id = row.get("source_track_id", "").strip()
        query_path = Path(row.get("query_path", ""))
        source_path = Path(row.get("source_path", ""))
        if source_id in train_track_ids or not query_path.is_file() or not source_path.is_file():
            continue
        positives.append({
            "path": str(query_path), "label": "positive",
            "expected_track_id": source_id,
            "query_kind": "synthetic_instrument_layer_overlay",
        })
        held_out.setdefault(source_id, {"path": source_path})
    queries: list[dict[str, str]] = []
    for row in positives:
        group = "positive:" + row["expected_track_id"]
        queries.append({**row, "group_id": group, "dataset": "positive"})

    for path in baseline.audio_files(baseline.SAFE_QUERY_DIR):
        group = "safe:" + path.stem
        queries.append({
            "path": str(path), "label": "safe", "expected_track_id": "",
            "query_kind": "unmodified_safe_candidate", "group_id": group,
            "dataset": "safe_music",
        })

    # These altered tracks are generated from music/ controls, but their source
    # music has not been manually reviewed. Keep them out of calibration.
    for row in read_csv(SAFE_ARRANGED_MANIFEST):
        query_path = Path(row.get("query_path", ""))
        origin_path = Path(row.get("origin_path", ""))
        if query_path.is_file() and origin_path.is_file():
            queries.append({
                "path": str(query_path), "label": "unverified_safe_control",
                "expected_track_id": "", "query_kind": row.get("case_type", "safe_arranged"),
                "group_id": "safe:" + origin_path.stem, "dataset": "safe_arranged_unverified",
            })
    return queries, held_out


def load_reference_catalog(
    model: ClapAudioModelWithProjection,
    processor: ClapProcessor,
    device: torch.device,
    held_out: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the catalog from cached training vectors plus held-out originals."""
    cache_path = ARTIFACT_DIR / "clap_embeddings.npz"
    manifest_path = ARTIFACT_DIR / "segment_manifest.csv"
    raw_cache = np.load(cache_path, allow_pickle=False)
    rows = read_csv(manifest_path)
    paths = np.asarray([row["segment_path"] for row in rows])
    if not np.array_equal(raw_cache["paths"].astype(str), paths.astype(str)):
        raise RuntimeError("CLAP embeddings and segment_manifest.csv do not match.")
    ids = np.asarray([row["track_id"] for row in rows])
    vectors = [raw_cache["embeddings"].astype(np.float32)]
    track_ids = [ids]
    offsets = [baseline.training_window_offsets(raw_cache["paths"])]
    present = set(ids.tolist())

    for source_id, source in held_out.items():
        if source_id in present:
            continue
        embedded, starts = baseline.embed_file(
            source["path"], model, processor, device, all_reference_windows=True
        )
        if len(embedded):
            vectors.append(embedded)
            track_ids.append(np.full(len(embedded), source_id, dtype=f"<U{max(1, len(source_id))}"))
            offsets.append(np.asarray(starts, dtype=np.float32))
            present.add(source_id)

    for path in baseline.audio_files(baseline.ORIGINAL_DIR):
        track_id = baseline.track_id_from_original(path)
        if track_id in present:
            continue
        embedded, starts = baseline.embed_file(
            path, model, processor, device, all_reference_windows=True
        )
        if len(embedded):
            vectors.append(embedded)
            track_ids.append(np.full(len(embedded), track_id, dtype=f"<U{max(1, len(track_id))}"))
            offsets.append(np.asarray(starts, dtype=np.float32))
            present.add(track_id)
    return np.concatenate(vectors), np.concatenate(track_ids), np.concatenate(offsets)


def choose_thresholds(
    tune_safe_scores: list[float], tune_positive_source_scores: list[float]
) -> dict[str, Any]:
    """Choose thresholds on tune groups only; expose feasibility explicitly."""
    if not tune_safe_scores or not tune_positive_source_scores:
        return {"hold_threshold": None, "warn_threshold": None, "feasible": False,
                "reason": "tune split is missing safe or positive source examples"}
    candidates = sorted(set(tune_safe_scores + tune_positive_source_scores))
    # Lowest score satisfying the safe false-HOLD limit yields the best recall
    # under that constraint. Use strict > rather than >= at threshold ties.
    hold_options = [threshold for threshold in candidates
                    if sum(score >= threshold for score in tune_safe_scores) / len(tune_safe_scores)
                    <= HOLD_FPR_TARGET]
    hold = min(hold_options) if hold_options else math.inf
    positive_recall_at_hold = sum(score >= hold for score in tune_positive_source_scores) / len(tune_positive_source_scores)
    # WARN is the highest score that still meets the positive recall goal,
    # minimizing warnings among safe queries while meeting that recall target.
    warn_options = [threshold for threshold in candidates
                    if sum(score >= threshold for score in tune_positive_source_scores) / len(tune_positive_source_scores)
                    >= WARN_RECALL_TARGET]
    warn = max(warn_options) if warn_options else math.inf
    return {
        "hold_threshold": None if not math.isfinite(hold) else float(hold),
        "warn_threshold": None if not math.isfinite(warn) else float(warn),
        "target_safe_hold_rate": HOLD_FPR_TARGET,
        "target_positive_source_recall_for_warn": WARN_RECALL_TARGET,
        "tune_safe_hold_rate": (
            sum(score >= hold for score in tune_safe_scores) / len(tune_safe_scores)
            if math.isfinite(hold) else None
        ),
        "tune_positive_source_recall_at_hold": positive_recall_at_hold,
        "tune_positive_source_recall_at_warn": (
            sum(score >= warn for score in tune_positive_source_scores) / len(tune_positive_source_scores)
            if math.isfinite(warn) else None
        ),
        "tune_safe_warn_or_hold_rate": (
            sum(score >= warn for score in tune_safe_scores) / len(tune_safe_scores)
            if math.isfinite(warn) else None
        ),
        "feasible": bool(math.isfinite(hold) and math.isfinite(warn) and warn <= hold),
        "reason": None if math.isfinite(hold) and math.isfinite(warn) and warn <= hold
        else "No single ordered threshold pair met both tune targets; do not force the slide cutoffs.",
    }


def threshold_metrics(rows: list[dict[str, Any]], threshold: float | None, split: str) -> dict[str, Any]:
    """Evaluate the query-level top-result score on one already assigned split."""
    if threshold is None:
        return {"threshold": None, "positive_recall": None, "safe_false_positive_rate": None}
    part = [row for row in rows if row["split"] == split and row["dataset"] in ("positive", "safe_music")]
    positives = [row for row in part if row["dataset"] == "positive"]
    safes = [row for row in part if row["dataset"] == "safe_music"]
    positive_recall = sum(float(row["top_score"]) >= threshold for row in positives) / len(positives) if positives else None
    source_positive_recall = (
        sum(float(row["expected_source_score"]) >= threshold
            for row in positives if row["expected_source_score"] is not None)
        / sum(row["expected_source_score"] is not None for row in positives)
        if any(row["expected_source_score"] is not None for row in positives) else None
    )
    safe_fpr = sum(float(row["top_score"]) >= threshold for row in safes) / len(safes) if safes else None
    return {"threshold": threshold, "positive_query_recall": positive_recall,
            "positive_expected_source_recall": source_positive_recall,
            "safe_query_false_positive_rate": safe_fpr,
            "positive_query_count": len(positives), "safe_query_count": len(safes)}


def overlay_test_metrics(
    rows: list[dict[str, Any]], hold_threshold: float | None, warn_threshold: float | None
) -> dict[str, Any]:
    """Summarize held-out instrument-overlay queries separately from easier edits."""
    overlay = [row for row in rows if row["split"] == "test"
               and row["query_kind"] == "synthetic_instrument_layer_overlay"]
    if not overlay:
        return {"query_count": 0}
    ranks = [int(row["expected_source_rank"]) for row in overlay
             if row["expected_source_rank"] is not None]
    return {
        "query_count": len(overlay),
        "source_top1_rate": float(np.mean([rank == 1 for rank in ranks])) if ranks else None,
        "source_top3_rate": float(np.mean([rank <= 3 for rank in ranks])) if ranks else None,
        "source_at_hold_rate": (
            float(np.mean([float(row["expected_source_score"]) >= hold_threshold for row in overlay]))
            if hold_threshold is not None else None
        ),
        "source_at_warn_rate": (
            float(np.mean([float(row["expected_source_score"]) >= warn_threshold for row in overlay]))
            if warn_threshold is not None else None
        ),
    }


def main() -> None:
    """Generate separate comparison artifacts while reusing embedding caches."""
    if not (ARTIFACT_DIR / "clap_embeddings.npz").is_file():
        raise SystemExit("Missing layer2/artifacts/clap_embeddings.npz")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cpu":
        torch.set_num_threads(min(4, torch.get_num_threads()))
    model = ClapAudioModelWithProjection.from_pretrained(
        baseline.BASE_MODEL, local_files_only=True
    ).to(device)
    model.eval()
    processor = ClapProcessor.from_pretrained(baseline.BASE_MODEL, local_files_only=True)
    baseline.FFMPEG_EXE = baseline.find_ffmpeg()
    if baseline.FFMPEG_EXE is None:
        raise SystemExit("ffmpeg was not found in PATH or imageio-ffmpeg.")

    train_ids = set(row["track_id"] for row in read_csv(ARTIFACT_DIR / "segment_manifest.csv"))
    queries, held_out = build_queries(train_ids)
    all_groups = {row["group_id"] for row in queries if row["dataset"] != "safe_arranged_unverified"}
    # Keep safe-arranged examples in the same partition as their unmodified
    # source query without letting them affect the positive/safe split counts.
    all_groups.update(row["group_id"] for row in queries)
    splits = group_split(all_groups)
    reference_vectors, reference_ids, reference_offsets = load_reference_catalog(
        model, processor, device, held_out
    )
    center_mean = reference_vectors.mean(axis=0)

    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: list[str] = []
    for number, query in enumerate(queries, start=1):
        path = Path(query["path"])
        try:
            query_vectors, offsets = baseline.embed_file(
                path, model, processor, device,
                all_reference_windows=False, all_query_windows=True,
            )
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, TypeError) as error:
            skipped.append(f"{path} | {type(error).__name__}: {error}")
            print(f"[skip] {path.name} | {type(error).__name__}", flush=True)
            continue
        if not len(query_vectors):
            skipped.append(str(path))
            continue
        matches_by_mode = score_all_tracks(
            query_vectors, offsets, reference_vectors, reference_ids,
            reference_offsets, center_mean,
        )
        expected = query["expected_track_id"]
        for mode, matches in matches_by_mode.items():
            source = next((row for row in matches if row["track_id"] == expected), None) if expected else None
            row = {
                "aggregation": mode,
                "file": str(path.resolve()),
                "dataset": query["dataset"],
                "label": query["label"],
                "query_kind": query["query_kind"],
                "group_id": query["group_id"],
                "split": splits[query["group_id"]],
                "expected_track_id": expected,
                "top_track_id": matches[0]["track_id"],
                "top_score": matches[0]["score"],
                "expected_source_score": source["score"] if source else None,
                "expected_source_rank": next((i for i, m in enumerate(matches, 1) if m["track_id"] == expected), None) if expected else None,
                "expected_source_in_top5": bool(source and any(m["track_id"] == expected for m in matches[:TOP_K])) if expected else None,
                "top5_matches": matches[:TOP_K],
                "window_count": len(offsets),
            }
            by_mode[mode].append(row)
        print(f"[{number}/{len(queries)}] {path.name}", flush=True)

    report: dict[str, Any] = {
        "experiment": "six CLAP aggregation variants; reference-mean centering ablation",
        "split": {"method": "deterministic source-group split", "tune_fraction": TUNE_FRACTION,
                  "seed": SEED, "groups": {"tune": sum(v == "tune" for v in splits.values()),
                                            "test": sum(v == "test" for v in splits.values())}},
        "corpus": {"reference_tracks": int(len(np.unique(reference_ids)),),
                   "reference_windows": int(len(reference_ids)),
                   "train_reference_tracks": len(train_ids),
                   "positive_source_groups": len({q["group_id"] for q in queries if q["dataset"] == "positive"}),
                   "safe_arranged_unverified_queries": sum(q["dataset"] == "safe_arranged_unverified" for q in queries),
                   "synthetic_instrument_overlay_queries": sum(
                       q["query_kind"] == "synthetic_instrument_layer_overlay" for q in queries
                   ),
                   "safe_arranged_unverified_note": "Reported separately; excluded from threshold calibration because negative labels are unverified."},
        "protocol": {"window_seconds": baseline.WINDOW_SECONDS, "stride_seconds": baseline.STRIDE_SECONDS,
                     "positive_split_group": "source_track_id", "safe_split_group": "source/origin work",
                     "safe_arranged_controls_in_threshold_fit": False,
                     "thresholds_are_model_tuning_only": True,
                     "score_interpretation": "cosine similarity, not a plagiarism probability or legal finding"},
        "models": {}, "skipped_queries": skipped,
    }
    flat_rows: list[dict[str, Any]] = []
    for mode, rows in sorted(by_mode.items()):
        tune_safe = [float(r["top_score"]) for r in rows if r["split"] == "tune" and r["dataset"] == "safe_music"]
        tune_positive_sources = [float(r["expected_source_score"]) for r in rows
                                 if r["split"] == "tune" and r["dataset"] == "positive"
                                 and r["expected_source_score"] is not None]
        thresholds = choose_thresholds(tune_safe, tune_positive_sources)
        test_positives = [r for r in rows if r["split"] == "test" and r["dataset"] == "positive"]
        test_safes = [r for r in rows if r["split"] == "test" and r["dataset"] == "safe_music"]
        test_h = thresholds["hold_threshold"]
        test_w = thresholds["warn_threshold"]
        report["models"][mode] = {
            "thresholds_from_tune_split": thresholds,
            "held_out_test": {
                "positive_query_count": len(test_positives),
                "safe_query_count": len(test_safes),
                "positive_expected_source_top1_rate": float(np.mean([r["expected_source_rank"] == 1 for r in test_positives])) if test_positives else None,
                "positive_expected_source_top3_rate": float(np.mean([r["expected_source_rank"] is not None and r["expected_source_rank"] <= 3 for r in test_positives])) if test_positives else None,
                "positive_expected_source_top5_rate": float(np.mean([r["expected_source_in_top5"] for r in test_positives])) if test_positives else None,
                "positive_expected_source_score_median": float(np.median([r["expected_source_score"] for r in test_positives if r["expected_source_score"] is not None])) if test_positives else None,
                "safe_top1_score_median": float(np.median([r["top_score"] for r in test_safes])) if test_safes else None,
                "hold_policy_test": threshold_metrics(rows, test_h, "test"),
                "warn_policy_test": threshold_metrics(rows, test_w, "test"),
                "synthetic_instrument_overlay_test": overlay_test_metrics(rows, test_h, test_w),
                "unverified_safe_arranged_top_score_median": float(np.median([r["top_score"] for r in rows if r["split"] == "test" and r["dataset"] == "safe_arranged_unverified"])) if any(r["split"] == "test" and r["dataset"] == "safe_arranged_unverified" for r in rows) else None,
            },
            "tune_group_counts": {
                "positive_queries": sum(r["split"] == "tune" and r["dataset"] == "positive" for r in rows),
                "positive_sources": len({r["group_id"] for r in rows if r["split"] == "tune" and r["dataset"] == "positive"}),
                "safe_queries": sum(r["split"] == "tune" and r["dataset"] == "safe_music" for r in rows),
                "safe_source_groups": len({r["group_id"] for r in rows if r["split"] == "tune" and r["dataset"] == "safe_music"}),
            },
        }
        flat_rows.extend(rows)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ["aggregation", "file", "dataset", "label", "query_kind", "group_id", "split",
               "expected_track_id", "top_track_id", "top_score", "expected_source_score",
               "expected_source_rank", "expected_source_in_top5", "window_count", "top5_matches"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in flat_rows:
            writer.writerow({**row, "top5_matches": json.dumps(row["top5_matches"], ensure_ascii=False)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved {OUTPUT_JSON} and {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
