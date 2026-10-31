"""Verify live inference matches the locked offline tonal evaluation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'api'))
from engine import Engine


def main():
    rows = [json.loads(line) for line in (ROOT / 'layer2/artifacts/tonal_confirmation_checkpoint.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    normal = next(r for r in rows if r['dataset'] == 'safe_music')
    positive = next(r for r in rows if r['query_kind'] == 'room_rerecord_simulation' and 'L3' in r['file'])
    engine = Engine()
    checked = []
    for row in (normal, positive):
        path = Path(row['file'])
        live = engine.verify(path, hashlib.sha256(path.read_bytes()).hexdigest())
        assert live['decision'] != 'BLOCK', 'Parity cases must exercise nonduplicate inference'
        assert live['scoreVersion'] == 'clap-top5+tonal-local-v1'
        assert abs(live['similarityScore'] - row['score']) < 1e-5, (live['similarityScore'], row['score'])
        offline = row['candidates'][:3]
        assert [c['trackId'] for c in live['similarTracks']] == [c['trackId'] for c in offline]
        expected = 'HOLD' if row['score'] >= engine.thresholds['hold'] else 'WARN' if row['score'] >= engine.thresholds['warn'] else 'PASS'
        assert live['decision'] == expected
        checked.append({'file': path.name, 'decision': expected, 'score': live['similarityScore']})
    (ROOT / 'layer2/artifacts/tonal_live_parity_validation.json').write_text(json.dumps({'status': 'passed', 'cases': checked}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Live/offline ranking, tonal score, policy and version parity passed for normal and positive queries.')


if __name__ == '__main__': main()
