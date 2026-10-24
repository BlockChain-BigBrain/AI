"""Engineering revision after observed failures; no blind-test claims."""
from pathlib import Path
import hashlib
import json
import numpy as np
import compare_ai_improvements as exp
import selective_retrieval as selective

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def convert(row):
    ranked=sorted(row['candidates'],key=lambda c:c['clapScore'],reverse=True)
    candidates=[selective.apply(c,i) for i,c in enumerate(ranked,1)]
    candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
    return {**row,'method':'selective_top20','candidates':candidates,'score':candidates[0]['tonalScore'],
        'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
        'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)}


def main():
    first=exp.read(ART/'ai_improvement_comparison.json')
    protocol={'date':'2026-10-23','method':'selective_top20','candidate_score_rule':selective.RULE,
        'score_rule':'Keep tonal score for CLAP ranks 1-5; square [0,1] tonal score for ranks 6-20 before reranking.',
        'warn_rule':'Lowest inclusive threshold meeting original tune normal FPR<=10%.',
        'hold_rule':'Tune normal FPR<=2% and confirmed tune-positive lower quartile, whichever is higher.',
        'selection_status':'Engineering revision after observing round-1 and round-2 diagnostic failures; not blind validation.',
        'reason':'Margin policy lost new-transform recall; unpenalized Top-20 added weak normal warnings. Require stronger sequence evidence for expanded candidates.',
        'new_replication':'Freeze before new +2-semitone/0.94-tempo/AAC96k and alternate-splice/1.08-tempo queries, same 14 previously seen works.',
        'acceptance':'Audited test WARN<=10%, HOLD<=2%; source WARN Top3 recall>=90% on old test, round1 stress and new replication.'}
    target=ART/'ai_selective_retrieval_protocol.json'
    if target.exists():assert exp.read(target)==protocol
    else:target.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'ai_improvement_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line)
        if r['signature']==first['signature'] and r['method']=='margin_top20':rows[(r['scope'],r['file'])]=convert(r)
    stress={}
    for line in (ART/'ai_recall_guard_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);stress[(r['scope'],r['file'])]=convert(r)
    all_rows=list(rows.values())+list(stress.values())
    signature=hashlib.sha256(target.read_bytes()).hexdigest()
    with (ART/'ai_selective_retrieval_checkpoint.jsonl').open('w',encoding='utf-8') as f:
        for row in all_rows:f.write(json.dumps({**row,'signature':signature},ensure_ascii=False)+'\n')
    profiles={}
    for scope in first['profiles']:
        part=[r for r in rows.values() if r['scope']==scope]
        cal=exp.calibrate(part);policy={**cal,'warn_threshold':cal['normal_boundary']}
        profiles[scope]={**policy,'method':'selective_top20','retrieval_top_k':20,'candidate_score_rule':selective.RULE,
            'score_version':'tonal-local-v1','tune':exp.metrics([r for r in part if r['split']=='tune'],policy),
            'test_raw':exp.metrics([r for r in part if r['split']=='test'],policy),
            'test_audited':exp.metrics([r for r in part if r['split']=='test'],policy,first['excluded_normal_filenames']),
            'premusic_diagnostic':exp.metrics([r for r in part if r['split']=='external_diagnostic'],policy),
            'round1_stress':exp.metrics([r for r in stress.values() if r['scope']==scope],policy)}
    output={'protocol':protocol,'signature':signature,'profiles':profiles,
        'original_policy_sha256':first['original_policy_sha256'],
        'comparison_sha256':hashlib.sha256((ART/'ai_improvement_comparison.json').read_bytes()).hexdigest(),
        'excluded_normal_filenames':first['excluded_normal_filenames']}
    (ART/'ai_selective_retrieval_evaluation.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
