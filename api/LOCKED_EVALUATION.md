# Runtime acoustic evidence and locked evaluation

The API returns `featureEvidence` for each of its three CLAP candidates. It
contains pitch, rhythm, and chroma scores for the matched ten-second segments.
Pitch measures the dominant spectral peak, rhythm measures onset periodicity,
and chroma groups spectral energy by pitch class. The feature version is
`pitch-rhythm-chroma-v2`. Only matched reference excerpts are decoded. These
scores are review evidence, not calibrated
probabilities. They do not alter the `seg_top3_centered-v1` decision.

Run the existing held-out source-group partition through the real API engine:

```powershell
C:\Users\82108\anaconda3\python.exe api\evaluate_locked_runtime.py
```

The command freezes the CSV hash, score version, thresholds, and corpus digest
in `api/runtime/locked_evaluation/lock.json`, checkpoints every query in
`results.jsonl`, and writes counts to `summary.json`. Re-running resumes from
the checkpoint and rejects a changed lock. Use `--limit 1 --output
api/runtime/locked_smoke` for a one-query integration check.

The historical safe controls are not a replacement for new, independently
reviewed normal songs. The current 1,000-track catalog also differs from the
295-track corpus used to fit the existing thresholds. This run measures the
current runtime without fitting new cutoffs.

The current AI-focused policy uses a calibrated fusion score:

`0.5 * CLAP score + 0.5 * (0.4 * pitch + 0.35 * chroma + 0.25 * rhythm)`.

Its thresholds are fitted only on source-group-separated, automatically labeled
AI variants. No human listening label is used for this calibration. The fusion
evaluation is recorded in `api/runtime/feature_fusion_evaluation.json` and the
policy in `api/runtime/ai_calibrated_policy.json`.
