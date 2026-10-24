"""Fuse CLAP retrieval and CQT progression evidence; recalibrate on tune.

All existing examples have been observed. An engineering comparison only.
"""
from pathlib import Path
import hashlib,json
import numpy as np
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    protocol={'date':'2026-10-23','method':'clap-cqt-three-fragment-v1',
        'trigger':'Baseline score<.60; original CLAP Top3.',
        'score_rule':'max(baseline, min(.80, (max(0,CLAP)*max(CQT_whole, valid_3fragment_mean))^2)).',
        'fragment_guard':'Three separated >=8s reference spans, each CQT score>=.65; query>=45s.',
        'threshold_rule':'Original tune groups only; normal WARN<=10%, HOLD<=2% plus tune positive lower quartile.',
        'limits':'Engineering revision after observed prototypes. No blind-validation claim.',
        'acceptance':'No old source-recall regression, tune/audited-test normal targets, aggregate five-family recall>=90%.'}
    pp=ART/'precision_multievidence_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'precision_rescue_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);rows[r['file']]=r
    results=[];signature=hashlib.sha256(pp.read_bytes()).hexdigest()
    for row in rows.values():
        checks={c['trackId']:c for c in row['rescue_checked']};candidates=[]
        for c in row['candidates']:
            candidate=dict(c);raw=c['unpenalizedTonalScore'];score=raw if c['retrievalRank']<=5 else raw**2
            evidence=checks.get(c['trackId'])
            if evidence:
                matches=evidence['fragments'];fragment=0.
                if len(matches)==3 and min(s['tonalScore'] for s in matches)>=.65:fragment=float(np.mean([s['tonalScore'] for s in matches]))
                confirmation=max(evidence['whole_score'],fragment)
                enhanced=min(.80,(max(0,c['clapScore'])*confirmation)**2)
                if enhanced>score:
                    score=enhanced;candidate['precisionEvidence']={'method':protocol['method'],'score':score,'segments':matches if fragment>evidence['whole_score'] else [],
                        'wholeScore':evidence['whole_score'],'fragmentMean':fragment}
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
    with (ART/'precision_multievidence_checkpoint.jsonl').open('w',encoding='utf-8') as f:
        for row in results:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'protocol':protocol,'signature':signature,'policy':policy,'summary':summary,
        'raw_test':exp.metrics([r for r in results if r['split']=='test'],policy),'active_policy_changed':False}
    (ART/'precision_multievidence_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
