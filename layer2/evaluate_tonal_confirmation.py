"""Evaluate a predeclared tonal confirmation recipe on cached CLAP Top-5.

Tune only on the existing tune source groups. Historical test groups are reused
and explicitly not called a fresh unseen validation set. No refitting on test.
"""
import csv
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import evaluate_retrieval_baseline as baseline
import tonal_alignment as tonal

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'


def main():
    rows = [r for r in csv.DictReader((ART / 'top3_aggregation_details.csv').open(encoding='utf-8-sig'))
            if r['aggregation'] == 'seg_top3_centered' and r['dataset'] in ('positive', 'safe_music')]
    originals = {baseline.track_id_from_original(p): p for p in baseline.audio_files(ROOT / 'original_music')}
    ffmpeg = baseline.find_ffmpeg()
    memory = {}
    cache = ART / 'tonal_feature_cache'
    def features(path):
        key = str(path.resolve())
        if key not in memory:
            memory[key] = tonal.features(path, ffmpeg, cache)
        return memory[key]
    results = []
    checkpoint = ART / 'tonal_confirmation_checkpoint.jsonl'
    previous = {}
    signature = hashlib.sha256((ART / 'top3_aggregation_details.csv').read_bytes() + tonal.VERSION.encode()).hexdigest()
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            if line.strip():
                saved = json.loads(line)
                if saved.get('signature') == signature:
                    previous[saved['file']] = saved
    with checkpoint.open('a', encoding='utf-8') as log:
        for i, row in enumerate(rows, 1):
            if row['file'] in previous:
                results.append(previous[row['file']]); continue
            started = time.monotonic()
            q, _, qs = features(Path(row['file']))
            candidates = []
            for match in json.loads(row['top5_matches']):
                ref, _, rs = features(originals[match['track_id']])
                candidates.append({'trackId': match['track_id'], 'clapScore': match['score'], **tonal.compare(q, ref, qs, rs)})
            candidates.sort(key=lambda c: c['tonalScore'], reverse=True)
            expected = next((c['tonalScore'] for c in candidates if c['trackId'] == row['expected_track_id']), None)
            result = {k: row[k] for k in ('file', 'dataset', 'query_kind', 'group_id', 'split', 'expected_track_id')}
            result.update(signature=signature, candidates=candidates, score=candidates[0]['tonalScore'],
                          expected_score=expected, original_top_score=float(row['top_score']))
            results.append(result); log.write(json.dumps(result, ensure_ascii=False) + '\n'); log.flush()
            print(f'[{i}/{len(rows)}] {Path(row["file"]).name}: tonal={result["score"]:.4f} {time.monotonic()-started:.1f}s', flush=True)
    tune = [r for r in results if r['split'] == 'tune']
    test = [r for r in results if r['split'] == 'test']
    normals = [r['score'] for r in tune if r['dataset'] == 'safe_music']
    # Highest recall possible subject to <=10% normal WARN / <=2% HOLD on tune.
    def threshold(target):
        for t in sorted(set(normals + [float(np.nextafter(max(normals), np.inf))])):
            if np.mean([s >= t for s in normals]) <= target:
                return float(t)
        raise RuntimeError('No threshold')
    warn, hold = threshold(.10), threshold(.02)
    def metrics(subset, threshold):
        safe = [r for r in subset if r['dataset'] == 'safe_music']
        positive = [r for r in subset if r['dataset'] == 'positive']
        return {'normal_count': len(safe), 'positive_count': len(positive),
                'normal_false_positive_rate': float(np.mean([r['score'] >= threshold for r in safe])),
                'positive_query_recall': float(np.mean([r['score'] >= threshold for r in positive])),
                'correct_source_recall': float(np.mean([r['expected_score'] is not None and r['expected_score'] >= threshold for r in positive]))}
    baseline_report = json.loads((ART / 'top3_aggregation_evaluation.json').read_text(encoding='utf-8'))
    report = {'score_version': tonal.VERSION, 'recipe_frozen_before_run': True,
              'reference_tracks': 1000, 'positive_queries': 340, 'normal_queries': 300,
              'candidate_pool': 'existing CLAP seg_top3_centered top5, no expected-source injection',
              'warn_threshold': warn, 'hold_threshold': hold,
              'tune_normal_fpr_targets': {'warn': .10, 'hold': .02},
              'tune': {'warn': metrics(tune, warn), 'hold': metrics(tune, hold)},
              'reused_test': {'warn': metrics(test, warn), 'hold': metrics(test, hold)},
              'corpus_version': baseline_report['corpus']['embedding_sha256'], 'signature': signature,
              'limitations': ['Historical test groups reused after aggregate failure was seen; not a fresh blind test.',
                              'Synthetic positives and fingerprint-unique normal candidates; no legal labels.',
                              'Sources outside CLAP Top-5 cannot be recovered by confirmation.']}
    report['enabled'] = report['tune']['warn']['correct_source_recall'] >= .50
    (ART / 'tonal_confirmation_evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
