"""Compare fixed second-route penalties on tune; reused tests stay diagnostic."""
from pathlib import Path
import json,hashlib
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    source=exp.read(ART/'dual_retrieval_evaluation.json')
    original=exp.read(ART/'ai_selective_retrieval_evaluation.json')
    protocol={'date':'2026-10-23','method':'dual-route-guard','powers':[2,3],
        'score_rule':'CLAP ranks 1-5 unchanged; ranks 6-20 squared; ranks >20 use compared second-route power.',
        'selection':'Tune correct-source recall, then prefer cube when tied; normal tune targets calibrated independently.',
        'limits':'Engineering follow-up after dual-route diagnostics; existing test/stress observed, not blind validation.',
        'deployment':'No active AI-only policy change without added recall in its own 34-track scope.'}
    target=ART/'dual_route_guard_protocol.json'
    if target.exists():assert exp.read(target)==protocol
    else:target.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'dual_retrieval_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['signature']==source['signature']:rows[(row['scope'],row['file'])]=row
    variants={};all_rows=[]
    for power in protocol['powers']:
        variants[power]=[]
        for row in rows.values():
            candidates=[]
            for c in row['candidates']:
                raw=c['unpenalizedTonalScore'];rank=c['retrievalRank']
                exponent=1 if rank<=5 else 2 if rank<=20 else power
                candidates.append({**c,'tonalScore':raw**exponent,'scorePower':exponent})
            candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
            result={**row,'method':'dual-route-guard','second_route_power':power,'candidates':candidates,'score':candidates[0]['tonalScore'],
                'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
                'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)}
            variants[power].append(result);all_rows.append(result)
    profiles={}
    for scope in source['profiles']:
        methods={}
        for power,rows_ in variants.items():
            part=[r for r in rows_ if r['scope']==scope];cal=exp.calibrate(part);policy={**cal,'warn_threshold':cal['normal_boundary']}
            methods[str(power)]={**policy,'tune':exp.metrics([r for r in part if r['split']=='tune'],policy),
                'test_raw':exp.metrics([r for r in part if r['split']=='test'],policy),
                'test_audited':exp.metrics([r for r in part if r['split']=='test'],policy,original['excluded_normal_filenames']),
                'first_stress':exp.metrics([r for r in part if r['split']=='new_transform_stress'],policy),
                'replication':exp.metrics([r for r in part if r['split']=='new_replication'],policy)}
        selected=max(methods,key=lambda p:(methods[p]['tune']['correct_source_warn_top3_recall'],int(p)))
        profiles[scope]={'selected_second_route_power':int(selected),'methods':methods}
    with (ART/'dual_route_guard_checkpoint.jsonl').open('w',encoding='utf-8') as f:
        for row in all_rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'protocol':protocol,'profiles':profiles,'active_policy_changed':False,
        'parent_evaluation_sha256':hashlib.sha256((ART/'dual_retrieval_evaluation.json').read_bytes()).hexdigest()}
    (ART/'dual_route_guard_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
