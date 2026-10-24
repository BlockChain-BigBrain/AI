"""Calibrate a supplemental route on primary-PASS tune normals.

Keep the primary policy and score scale intact. The supplemental route gets
its own cutoff and is mapped to the existing WARN scale, capped below HOLD.
"""
from pathlib import Path
import hashlib,json
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    policy=exp.read(ART/'ai_improvement_policy.json')
    protocol={'date':'2026-10-23','method':'secondary-clap-cqt-fragments-v1',
        'primary_policy_sha256':hashlib.sha256((ART/'ai_improvement_policy.json').read_bytes()).hexdigest(),
        'route_score':'min(.80, (max(0,CLAP)*max(CQT whole, three valid fragment mean))^2).',
        'secondary_cutoff':'1.05 * maximum secondary evidence on primary-PASS tune normals; minimum .05.',
        'mapping':'max(primary score, min(.80, primary_WARN * secondary evidence / secondary cutoff)).',
        'purpose':'Preserve primary decisions while adding no new tune-normal warnings. Tune-only residual cutoff with fixed 5% margin.',
        'limits':'Development engineering after observed prototypes; no independent blind claim.',
        'acceptance':'Tune and audited-test normal targets, no old source-recall regression, aggregate five-family >=90%.'}
    pp=ART/'secondary_precision_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'precision_rescue_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);rows[r['file']]=r
    def evidence(c,check):
        if check is None:return 0.
        matches=check['fragments'];fragment=0.
        if len(matches)==3 and min(s['tonalScore'] for s in matches)>=.65:
            fragment=sum(s['tonalScore'] for s in matches)/3
        return min(.8,(max(0,c['clapScore'])*max(check['whole_score'],fragment))**2)
    residual=[]
    for row in rows.values():
        if row['split']!='tune' or row['dataset']!='safe_music':continue
        baseline=max(c['unpenalizedTonalScore'] if c['retrievalRank']<=5 else c['unpenalizedTonalScore']**2 for c in row['candidates'])
        if baseline>=policy['warn_threshold']:continue
        checks={c['trackId']:c for c in row['rescue_checked']}
        residual.append(max(evidence(c,checks.get(c['trackId'])) for c in row['candidates']))
    cutoff=max(.05,1.05*max(residual));results=[];signature=hashlib.sha256(pp.read_bytes()).hexdigest()
    for row in rows.values():
        checks={c['trackId']:c for c in row['rescue_checked']};candidates=[]
        for c in row['candidates']:
            candidate=dict(c);raw=c['unpenalizedTonalScore'];baseline=raw if c['retrievalRank']<=5 else raw**2
            extra=evidence(c,checks.get(c['trackId']));mapped=min(.8,policy['warn_threshold']*extra/cutoff)
            candidate['tonalScore']=max(baseline,mapped);candidate['secondaryEvidenceScore']=extra
            candidates.append(candidate)
        candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
        results.append({**row,'signature':signature,'method':protocol['method'],'candidates':candidates,'score':candidates[0]['tonalScore'],
            'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
            'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)})
    excluded=exp.read(ART/'ai_selective_retrieval_evaluation.json')['excluded_normal_filenames'];summary={}
    for split in sorted({r['split'] for r in results}):
        part=[r for r in results if r['split']==split];summary[split]=exp.metrics(part,policy,excluded)
        if split=='prospective_five_family':summary['by_family']={kind:exp.metrics([r for r in part if r['query_kind']==kind],policy) for kind in sorted({r['query_kind'] for r in part})}
    with (ART/'secondary_precision_checkpoint.jsonl').open('w',encoding='utf-8') as f:
        for row in results:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'protocol':protocol,'signature':signature,'secondary_warn_threshold':cutoff,'residual_tune_normals':len(residual),
        'primary_thresholds':{'warn':policy['warn_threshold'],'hold':policy['hold_threshold']},'summary':summary,
        'raw_test':exp.metrics([r for r in results if r['split']=='test'],policy),'active_policy_changed':False}
    (ART/'secondary_precision_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
