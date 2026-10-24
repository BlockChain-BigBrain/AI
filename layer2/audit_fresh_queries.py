"""Locked-policy audit on additional source works and unused premusic candidates.

The manifest is generated before revised policy fitting finishes. Its sources
are excluded from all existing 340 synthetic positives; results never fit policy.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import numpy as np
import evaluate_retrieval_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'layer2/test_data/fresh_audit'
ART = ROOT / 'layer2/artifacts'
sys.path.insert(0, str(ROOT / 'layer1'))
import upload_guard_api as gate


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare-only', action='store_true'); args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    manifest = OUT / 'manifest.json'
    ffmpeg = baseline.find_ffmpeg()
    baseline.FFMPEG_EXE = ffmpeg
    if not manifest.exists():
        used = {r['expected_track_id'] for r in csv.DictReader((ART / 'top3_aggregation_details.csv').open(encoding='utf-8-sig')) if r['dataset'] == 'positive'}
        originals = [p for p in baseline.audio_files(ROOT / 'original_music') if baseline.track_id_from_original(p) not in used]
        random.Random(20261023).shuffle(originals)
        rows = []
        for source in originals:
            duration = baseline.get_duration_seconds(source)
            if duration < 40: continue
            for kind, af in [('tempo_113', 'atempo=1.13'), ('pitch_plus_2', 'asetrate=48000*1.122462,aresample=48000,atempo=0.890899')]:
                target = OUT / f'{len(rows):03}_{kind}.wav'
                subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-ss', str((duration-35)/2), '-i', str(source),
                                '-t', '30', '-ar', '48000', '-ac', '1', '-af', 'aresample=48000,' + af, str(target)], check=True)
                rows.append({'file': str(target), 'label': 'synthetic_positive', 'kind': kind,
                             'expected_track_id': baseline.track_id_from_original(source), 'source_path': str(source),
                             'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
            if len(rows) == 40: break
        assert len(rows) == 40
        known = gate._load_db()
        normals = baseline.audio_files(ROOT / 'premusic'); random.Random(20261023).shuffle(normals)
        accepted = []
        existing_hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('original_music', 'music') for p in baseline.audio_files(ROOT / folder)}
        for source in normals:
            if hashlib.sha256(source.read_bytes()).hexdigest() in existing_hashes: continue
            try:
                fingerprint = gate.extract_raw_fingerprint(source)
            except ValueError:
                continue
            if fingerprint['duration'] < 35 or gate.find_exact_duplicate(fingerprint['fingerprint_raw'], known): continue
            if any(gate._contains_exact_sequence(fingerprint['fingerprint_raw'], f) or gate._contains_exact_sequence(f, fingerprint['fingerprint_raw']) for f in accepted): continue
            accepted.append(fingerprint['fingerprint_raw'])
            target = OUT / f'{len(rows):03}_unused_normal.wav'
            subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-ss', str((fingerprint['duration']-30)/2),
                            '-i', str(source), '-t', '30', '-ar', '48000', '-ac', '1', str(target)], check=True)
            rows.append({'file': str(target), 'label': 'unverified_normal_candidate', 'kind': 'unused_premusic_center30',
                         'expected_track_id': '', 'source_path': str(source), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
            if len(accepted) == 30: break
        assert len(accepted) == 30
        manifest.write_text(json.dumps({'render_version': 2, 'seed': 20261023, 'positive_works': 20, 'positive_queries': 40,
                                       'normal_candidates': 30, 'policy_fitting': False, 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Reserved 40 synthetic queries from 20 new source works and 30 unused normal candidates.', flush=True)
    reserved = json.loads(manifest.read_text(encoding='utf-8'))
    if reserved.get('render_version') != 2:
        # Correct source sample-rate normalization before any audit results exist.
        assert not (ART / 'fresh_audit_results.json').exists()
        for row in reserved['rows']:
            if row['label'] != 'synthetic_positive': continue
            source = Path(row['source_path'])
            af = 'atempo=1.13' if row['kind'] == 'tempo_113' else 'asetrate=48000*1.122462,aresample=48000,atempo=0.890899'
            duration = baseline.get_duration_seconds(source)
            subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-ss', str((duration-35)/2), '-i', str(source),
                            '-t', '30', '-ar', '48000', '-ac', '1', '-af', 'aresample=48000,' + af, row['file']], check=True)
            row['sha256'] = hashlib.sha256(Path(row['file']).read_bytes()).hexdigest()
        reserved['render_version'] = 2
        manifest.write_text(json.dumps(reserved, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.prepare_only: return
    policy = ART / 'tonal_confirmation_evaluation.json'
    assert policy.exists(), 'Lock tonal calibration before reading audit results'
    policy_hash = hashlib.sha256(policy.read_bytes()).hexdigest()
    sys.path.insert(0, str(ROOT / 'api'))
    from engine import Engine
    engine = Engine()
    results = []
    for i, row in enumerate(json.loads(manifest.read_text(encoding='utf-8'))['rows'], 1):
        path = Path(row['file']); assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
        result = engine.verify(path, row['sha256'])
        result['expected_source_warn'] = row['expected_track_id'] in [c['trackId'] for c in result['similarTracks'] if c['score'] >= result['thresholds']['warn']]
        results.append({**row, 'result': result})
        print(f'[audit {i}/70] {row["kind"]}: {result["decision"]}', flush=True)
    assert hashlib.sha256(policy.read_bytes()).hexdigest() == policy_hash
    positives = [r for r in results if r['label'] == 'synthetic_positive']
    normals = [r for r in results if r['label'] == 'unverified_normal_candidate']
    report = {'policy_sha256': policy_hash, 'source_works_excluded_from_existing_positives': True,
              'policy_refit_on_audit': False, 'positive_queries': len(positives), 'normal_candidates': len(normals),
              'positive_query_recall': float(np.mean([r['result']['decision'] != 'PASS' for r in positives])),
              'correct_source_warn_recall': float(np.mean([r['result']['expected_source_warn'] for r in positives])),
              'normal_warn_or_hold_rate': float(np.mean([r['result']['decision'] in ('WARN', 'HOLD', 'BLOCK') for r in normals])),
              'limitations': ['Additional positives are synthetic, not independently performed covers.',
                              'Unused normal candidates pass fingerprint checks but lack expert musical labels.',
                              'Only 20 new positive works and 30 normal candidates; estimates are uncertain.']}
    (ART / 'fresh_audit_results.json').write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
    (ART / 'fresh_audit_summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__': main()
