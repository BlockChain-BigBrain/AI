"""Revised precision fallback; fixed existing thresholds, no activation."""
from pathlib import Path
import hashlib,json
from threadpoolctl import threadpool_limits
import evaluate_retrieval_baseline as base
import precision_chroma as precision
import precision_rescue as rescue
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    threadpool_limits(limits=4)
    policy=exp.read(ART/'ai_improvement_policy.json')
    protocol={'date':'2026-10-23','method':rescue.VERSION,'trigger':'Baseline score<.60, original CLAP Top3 only.',
        'score_rule':'max(baseline, sqrt(FFT_whole*CQT_whole), .75*mean(three time-centered CQT fragments)^2).',
        'fragment_rule':'Same separated-fragment guards; minimum 45s query, 3 distinct reference spans, each >=8s and score>=.65.',
        'thresholds':{'warn':policy['warn_threshold'],'hold':policy['hold_threshold']},
        'limits':'Revised after observed prototype errors; all data are reused development diagnostics, no blind claim.',
        'acceptance':'Tune WARN<=10%, HOLD<=2%; no old source-recall regression; >=90% aggregate five-family recall and audited normal test targets.'}
    pp=ART/'precision_consensus_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for line in (ART/'precision_rescue_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line);rows[row['file']]=row
    base.FFMPEG_EXE=base.find_ffmpeg();paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    cache={}
    def features(path):
        key=str(path)
        if key not in cache:cache[key]=precision.features(path,base.FFMPEG_EXE,ART/'cqt_feature_cache')
        return cache[key]
    signature=hashlib.sha256(pp.read_bytes()).hexdigest();checkpoint=ART/'precision_consensus_checkpoint.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[r['file']]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,(file,row) in enumerate(rows.items(),1):
            if file in done:results.append(done[file]);continue
            candidates=[]
            for old in row['candidates']:
                c=dict(old);raw=c['unpenalizedTonalScore'];c['tonalScore']=raw if c['retrievalRank']<=5 else raw**2
                for key in ('rescue_whole','rescue_fragments'):c.pop(key,None)
                candidates.append(c)
            checked=[]
            if row['rescue_checked']:
                qt,_,qs=features(Path(file))
                for match in row['rescue_checked']:
                    track=match['trackId'];candidate=next(c for c in candidates if c['trackId']==track)
                    ref,_,rs=features(paths[track]);evidence=rescue.compare(qt,ref,qs,rs,candidate['unpenalizedTonalScore'])
                    if evidence['score']>candidate['tonalScore']:
                        candidate['tonalScore']=evidence['score'];candidate['precisionEvidence']=evidence
                    checked.append({'trackId':track,**evidence})
            candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
            result={**row,'signature':signature,'method':rescue.VERSION,'candidates':candidates,'score':candidates[0]['tonalScore'],
                'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
                'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None),
                'rescue_checked':checked}
            results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[precision consensus {n}/{len(rows)}]',flush=True)
    excluded=exp.read(ART/'ai_selective_retrieval_evaluation.json')['excluded_normal_filenames'];summary={}
    for split in sorted({r['split'] for r in results}):
        part=[r for r in results if r['split']==split];summary[split]=exp.metrics(part,policy,excluded)
        if split=='prospective_five_family':summary['by_family']={kind:exp.metrics([r for r in part if r['query_kind']==kind],policy) for kind in sorted({r['query_kind'] for r in part})}
    report={'protocol':protocol,'signature':signature,'summary':summary,'raw_test':exp.metrics([r for r in results if r['split']=='test'],policy),'active_policy_changed':False}
    (ART/'precision_consensus_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
