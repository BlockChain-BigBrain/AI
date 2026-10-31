"""AI-labelled catalog/threshold binding and live/offline parity."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
from engine import Engine


def main():
    art=ROOT/'layer2/artifacts'
    report=json.loads((art/'ai_labeled_recalibration.json').read_text(encoding='utf-8'))
    profile=report['profiles']['ai_labeled_catalog']
    improvement_path=art/'ai_improvement_policy.json'
    if improvement_path.exists():
        profile=json.loads(improvement_path.read_text(encoding='utf-8'))
    precision_path=art/'ai_precision_policy.json'
    if precision_path.exists():profile=json.loads(precision_path.read_text(encoding='utf-8'))
    engine=Engine(scope='ai_labeled')
    assert len(engine.groups)==34
    assert all(Path(key).stem in set(profile['allowed_reference_ids']) for key in engine.records)
    assert engine.corpus_version==profile['catalog_version']
    assert engine.thresholds=={'warn':profile['warn_threshold'],'hold':profile['hold_threshold']}
    rows=[json.loads(line) for line in (art/'ai_labeled_checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
    manifest_hash=report['manifest_sha256']
    # Select only the checkpoint version bound to this final manifest.
    signature=hashlib.sha256((manifest_hash+profile['full_catalog_version']+'tonal-local-v1').encode()).hexdigest()
    rows=[r for r in rows if r['scope']=='ai_labeled_catalog' and r['signature']==signature]
    if improvement_path.exists():
        rows=[json.loads(line) for line in (art/'ai_selective_retrieval_checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
        signature=json.loads((art/'ai_selective_retrieval_evaluation.json').read_text(encoding='utf-8'))['signature']
        rows=[r for r in rows if r['scope']=='ai_labeled_catalog' and r['signature']==signature and r['method']==profile['method']]
    if precision_path.exists():
        report_precision=json.loads((art/'secondary_precision_evaluation.json').read_text(encoding='utf-8'))
        rows=[json.loads(line) for line in (art/'secondary_precision_checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
        rows=[r for r in rows if r['signature']==report_precision['signature']]
    cases=[next(r for r in rows if r['dataset']=='positive' and r['query_kind']=='room_rerecord_simulation'),
           next(r for r in rows if r['dataset']=='safe_music'),
           next(r for r in rows if Path(r['file']).name=='turtlebeats-dark-synthwave-spectral-251688.mp3')]
    if improvement_path.exists():
        cases.append(next(r for r in rows if Path(r['file']).name=='006__pitch_tempo_codec.m4a'))
    if precision_path.exists():
        cases.append(next(r for r in rows if Path(r['file']).name=='001__long_auto_edit.wav'))
    checked=[]
    for row in cases:
        path=Path(row['file']);live=engine.verify(path,hashlib.sha256(path.read_bytes()).hexdigest())
        assert live['decision']!='BLOCK'
        assert live['evaluationScope']=='ai_labeled' and live['referenceTracks']==34
        assert live['pureAiCreationVerified'] is False
        assert abs(live['similarityScore']-row['score'])<1e-5,(live['similarityScore'],row['score'])
        assert [r['trackId'] for r in live['similarTracks']]==[r['trackId'] for r in row['candidates'][:3]]
        expected='HOLD' if row['score']>=profile['hold_threshold'] else 'WARN' if row['score']>=profile['warn_threshold'] else 'PASS'
        assert live['decision']==expected
        if improvement_path.exists() and Path(row['file']).name=='turtlebeats-dark-synthwave-spectral-251688.mp3':
            assert live['decision']=='PASS', 'Expanded candidates must not add a weak normal warning.'
        if improvement_path.exists() and Path(row['file']).name=='006__pitch_tempo_codec.m4a':
            assert live['decision'] in ('WARN','HOLD')
            assert row['expected_track_id'] in [r['trackId'] for r in live['similarTracks']]
        if precision_path.exists() and Path(row['file']).name=='001__long_auto_edit.wav':
            assert live['decision']=='WARN'
            source=next(c for c in live['similarTracks'] if c['trackId']==row['expected_track_id'])
            assert len(source['matchedSegments'])==3
        checked.append({'file':path.name,'decision':live['decision'],'score':live['similarityScore']})
    source=Path(json.loads((art/'pixabay_provenance/ai_label_allowlist.json').read_text(encoding='utf-8'))['original_music'][0]['file'])
    exact=engine.verify(source,hashlib.sha256(source.read_bytes()).hexdigest())
    assert exact['decision']=='BLOCK'
    (art/'ai_scope_live_validation.json').write_text(json.dumps({'status':'passed','scope':'ai_labeled','reference_tracks':34,
        'policy_version':engine.policy_version,'thresholds':engine.thresholds,
        'policy_file':'ai_precision_policy.json' if precision_path.exists() else 'ai_improvement_policy.json' if improvement_path.exists() else 'ai_labeled_recalibration.json',
        'score_version':engine.score_version,
        'checks':['matching policy/catalog/provenance binding','noneligible fingerprint records excluded','exact duplicate BLOCK','live/offline score, ranking and decision parity','weak expanded normal match PASS','source beyond CLAP Top5 recovered'],
        'cases':checked},ensure_ascii=False,indent=2),encoding='utf-8')
    print('AI-labelled scope and live/offline parity passed.')


if __name__=='__main__':main()
