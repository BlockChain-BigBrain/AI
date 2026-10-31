"""Combine feature agreement and multiple raw-CQT fragments, recalibrate on tune.

This is an observed-data engineering study, not an independent validation.
"""
from pathlib import Path
import hashlib,json,math
import numpy as np
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    protocol={'date':'2026-10-23','method':'cqt-agreement-three-fragment-v1',
        'trigger':'Existing selective score<.60; original CLAP Top3 only.',
        'whole_rule':'sqrt(FFT whole score * CQT whole score).',
        'fragment_rule':'Three distinct 10s raw-CQT alignments, each span>=8s and score>=.65; score=.75*mean(fragment scores)^2.',
        'thresholds':'Recalibrate WARN/HOLD on original tune groups only; no held-out numerical threshold fit.',
        'limits':'Engineering combination after observed precision prototypes; all old scores observed, not blind validation.',
        'acceptance':'Tune/audited test normal WARN<=10%, HOLD<=2%; no old positive recall regression; five-family source recall>=90%.'}
    pp=ART/'precision_hybrid_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'precision_rescue_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);rows[r['file']]=r
    results=[];signature=hashlib.sha256(pp.read_bytes()).hexdigest()
    for row in rows.values():
        checks={c['trackId']:c for c in row['rescue_checked']};candidates=[]
        for c in row['candidates']:
            candidate=dict(c);raw=c['unpenalizedTonalScore'];baseline=raw if c['retrievalRank']<=5 else raw**2
            evidence=checks.get(c['trackId']);score=baseline
            if evidence:
                agreement=math.sqrt(max(0,raw)*max(0,evidence['whole_score']))
                matches=evidence['fragments'];fragment=0.
                if len(matches)==3 and min(s['tonalScore'] for s in matches)>=.65:
                    fragment=.75*float(np.mean([s['tonalScore'] for s in matches]))**2
                score=max(score,agreement,fragment)
                candidate['hybridEvidence']={'agreementScore':agreement,'fragmentScore':fragment,
                    'segments':matches if fragment>agreement else []}
            candidate['tonalScore']=score;candidates.append(candidate)
        candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
        results.append({**row,'signature':signature,'method':protocol['method'],'candidates':candidates,'score':candidates[0]['tonalScore'],
            'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
            'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)})
    calibration=exp.calibrate(results);policy={**calibration,'warn_threshold':calibration['normal_boundary']}
    excluded=exp.read(ART/'ai_selective_retrieval_evaluation.json')['excluded_normal_filenames'];summary={}
    for split in sorted({r['split'] for r in results}):
        part=[r for r in results if r['split']==split];summary[split]=exp.metrics(part,policy,excluded)
        if split=='prospective_five_family':summary['by_family']={kind:exp.metrics([r for r in part if r['query_kind']==kind],policy) for kind in sorted({r['query_kind'] for r in part})}
    with (ART/'precision_hybrid_checkpoint.jsonl').open('w',encoding='utf-8') as f:
        for row in results:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'protocol':protocol,'signature':signature,'policy':policy,'summary':summary,
        'raw_test':exp.metrics([r for r in results if r['split']=='test'],policy),'active_policy_changed':False}
    (ART/'precision_hybrid_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
