"""Independent Covers80: same central-30-second protocol, full tonal search.

All 80 works are scored; unlike CLAP reranking, no candidate can be filtered
out by timbre. These previously inspected works are an exploratory benchmark.
"""
import csv
import json
from pathlib import Path
import numpy as np
import evaluate_retrieval_baseline as baseline
import tonal_alignment as tonal

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'
DATA = ROOT / 'layer2/external_data/covers80'


def main():
    baseline_rows = list(csv.DictReader((ART / 'independent_cover_benchmark_results.csv').open(encoding='utf-8-sig')))
    ffmpeg = baseline.find_ffmpeg()
    features = {}
    for i, row in enumerate(baseline_rows, 1):
        for role in ('query', 'reference'):
            clip = DATA / 'pilot_clips' / f"{row['work_id']}__{role}.wav"
            features[(row['work_id'], role)] = tonal.features(clip, ffmpeg, ART / 'tonal_feature_cache')
        print(f'[features {i}/80] {row["work_id"]}', flush=True)
    results = []
    for i, row in enumerate(baseline_rows, 1):
        q, _, qs = features[(row['work_id'], 'query')]
        matches = []
        for candidate in baseline_rows:
            r, _, rs = features[(candidate['work_id'], 'reference')]
            matches.append({'work_id': candidate['work_id'], **tonal.compare(q, r, qs, rs)})
        matches.sort(key=lambda r: r['tonalScore'], reverse=True)
        rank = next(j for j, r in enumerate(matches, 1) if r['work_id'] == row['work_id'])
        results.append({'work_id': row['work_id'], 'tonal_rank': rank,
                        'clap_rank': int(row['expected_source_rank']), 'top_work_id': matches[0]['work_id'],
                        'top_score': matches[0]['tonalScore'], 'matches': matches})
        print(f'[query {i}/80] {row["work_id"]}: tonal rank {rank}; CLAP {row["expected_source_rank"]}', flush=True)
    def metrics(key):
        return {**{f'recall_at_{k}': float(np.mean([r[key] <= k for r in results])) for k in (1, 3, 5)},
                'mrr': float(np.mean([1/r[key] for r in results]))}
    report = {'score_version': tonal.VERSION, 'evaluated_pairs': 80,
              'protocol': 'same cached center 30-second clips as historical CLAP; 80 references, no CLAP prefilter',
              'tonal': metrics('tonal_rank'), 'clap_baseline': metrics('clap_rank'),
              'limitations': ['Exploratory evaluation on previously inspected Covers80 works; not fresh blind validation.',
                              'No production risk thresholds fitted on these covers.',
                              'This corpus does not establish recall in the production 1000-song catalog.']}
    (ART / 'tonal_cover_results.json').write_text(json.dumps(results), encoding='utf-8')
    (ART / 'tonal_cover_summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
