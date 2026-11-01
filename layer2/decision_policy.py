"""Policy layer for conservative HOLD/WARN decisions.

This module is deliberately separate from model scoring. Thresholds and
weights are fit only on the tuning split; the locked evaluation split must
never be passed to fit_policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PolicyConfig:
    warn_threshold: float
    hold_threshold: float
    min_hold_segments: int = 2
    min_warn_segments: int = 2
    corroboration_threshold: float = 0.70
    recheck_max_segments: int = 1
    genre_penalty: float = 0.0
    tempo_penalty: float = 0.0
    repetition_penalty: float = 0.0


def calibrated_score(
    score: float,
    *,
    genre_prior: float = 0.0,
    tempo_gap: float = 0.0,
    repetitive_fraction: float = 0.0,
    config: PolicyConfig,
) -> float:
    """Apply only non-model calibration corrections.

    genre_prior and tempo_gap must be estimated from the reference corpus,
    never from the locked evaluation set. Repetitive material is discounted
    because a short generic loop can match by accident.
    """
    corrected = score
    corrected -= max(0.0, genre_prior) * config.genre_penalty
    corrected -= max(0.0, tempo_gap) * config.tempo_penalty
    corrected -= max(0.0, repetitive_fraction) * config.repetition_penalty
    return max(-1.0, min(1.0, corrected))


def classify_segments(
    segment_scores: Iterable[float],
    *,
    config: PolicyConfig,
    corroborating_scores: Iterable[float] = (),
    metadata: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Return a stable operational state.

    The public API keeps decision=WARN for RECHECK so older consumers stay
    compatible. reviewState distinguishes a single weak segment from a
    confirmed multi-segment warning.
    """
    metadata = metadata or {}
    scores = [
        calibrated_score(
            float(value),
            genre_prior=float(metadata.get("genrePrior", 0.0)),
            tempo_gap=float(metadata.get("tempoGap", 0.0)),
            repetitive_fraction=float(metadata.get("repetitiveFraction", 0.0)),
            config=config,
        )
        for value in segment_scores
    ]
    if not scores:
        return {"decision": "PASS", "reviewState": "NONE", "segmentCount": 0, "holdSegmentCount": 0, "warnSegmentCount": 0}

    hold_count = sum(score >= config.hold_threshold for score in scores)
    warn_count = sum(score >= config.warn_threshold for score in scores)
    corroboration = sum(float(score) >= config.corroboration_threshold for score in corroborating_scores)

    # HOLD requires repeated high similarity plus an independent supporting
    # feature (pitch/rhythm/chroma vote). A single CLAP peak cannot HOLD.
    if hold_count >= config.min_hold_segments and corroboration >= 2:
        return {
            "decision": "HOLD",
            "reviewState": "CONFIRMED",
            "segmentCount": len(scores),
            "holdSegmentCount": hold_count,
            "warnSegmentCount": warn_count,
        }
    if warn_count >= config.min_warn_segments:
        return {
            "decision": "WARN",
            "reviewState": "CONFIRMED",
            "segmentCount": len(scores),
            "holdSegmentCount": hold_count,
            "warnSegmentCount": warn_count,
        }
    if warn_count == config.recheck_max_segments:
        return {
            "decision": "WARN",
            "reviewState": "RECHECK",
            "segmentCount": len(scores),
            "holdSegmentCount": hold_count,
            "warnSegmentCount": warn_count,
        }
    return {
        "decision": "PASS",
        "reviewState": "NONE",
        "segmentCount": len(scores),
        "holdSegmentCount": hold_count,
        "warnSegmentCount": warn_count,
    }


def wilson_upper(successes: int, trials: int, z: float = 1.959963984540054) -> float:
    """Two-sided 95% Wilson upper bound for a binomial rate."""
    if trials <= 0:
        return 1.0
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    margin = z * ((p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) ** 0.5) / denominator
    return min(1.0, center + margin)


def evaluate_rates(
    *,
    warn_or_hold_false_positives: int,
    hold_false_positives: int,
    normal_count: int,
    positive_warn_or_hold_hits: int,
    positive_hold_hits: int,
    positive_count: int,
) -> dict[str, float | int]:
    """Summarize point estimates and 95% upper/lower bounds."""
    return {
        "normalCount": normal_count,
        "warnOrHoldFpr": warn_or_hold_false_positives / normal_count if normal_count else 0.0,
        "holdFpr": hold_false_positives / normal_count if normal_count else 0.0,
        "warnOrHoldFpr95Upper": wilson_upper(warn_or_hold_false_positives, normal_count),
        "holdFpr95Upper": wilson_upper(hold_false_positives, normal_count),
        "positiveCount": positive_count,
        "warnOrHoldRecall": positive_warn_or_hold_hits / positive_count if positive_count else 0.0,
        "holdRecall": positive_hold_hits / positive_count if positive_count else 0.0,
    }
