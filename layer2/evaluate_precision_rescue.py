"""CQT/three-fragment fallback on ambiguous AI-only queries; fixed thresholds.

All existing queries have been observed, so this is development diagnostics.
The experiment never changes the active policy automatically.
"""
from pathlib import Path
import hashlib,json,time
import numpy as np
from threadpoolctl import threadpool_limits
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import precision_chroma as precision
import fragment_confirmation as fragments
import tonal_alignment as tonal
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    threadpool_limits(limits=4)
    policy=exp.read(ART/'ai_improvement_policy.json');old=exp.read(ART/'ai_labeled_recalibration.json')
    protocol={'date':'2026-10-23','method':'ambiguous-cqt3-fragment-rescue','precision_features':precision.VERSION,
        'trigger':'Current selective score <0.60; evaluate only original CLAP Top3 candidates.',
        'score_rule':'Keep original scores; max with 0.5*CQT_whole_score^2 or 0.5*mean(3 separated CQT fragments)^2.',
        'fragment_rule':'Query>=45s; up to twelve nonoverlapping 10s windows; each>=8s alignment, three distinct reference spans, each score>=.65.',
        'thresholds':{'warn':policy['warn_threshold'],'hold':policy['hold_threshold']},
        'status':'Development diagnostics after observed five-family failures; no blind-validation claim.',
        'deployment':'Not automatic. Reject if tune normal target or old source recall regresses.'}
    pp=ART/'precision_rescue_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    rows={}
    for name,kind in [('ai_selective_retrieval_checkpoint.jsonl','flat'),('ai_selective_replication_checkpoint.jsonl','selected'),('five_family_ai_checkpoint.jsonl','current')]:
        for line in (ART/name).read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['scope']!='ai_labeled_catalog':continue
            if kind!='flat':r={**r,**r[kind],'split':'new_replication' if kind=='selected' else r['split']}
            rows[r['file']]=r
    base.FFMPEG_EXE=base.find_ffmpeg();paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,ids=f['vectors'].astype(np.float32),f['ids']
    mask=np.isin(ids,policy['allowed_reference_ids']);v,ids=vectors[mask],ids[mask];mean=v.mean(axis=0);centered=agg.unit_rows(v-mean)
    groups=[(str(t),np.flatnonzero(ids==t)) for t in np.unique(ids)]
    cache={}
    def features(path):
        key=str(path)
        if key not in cache:cache[key]=precision.features(path,base.FFMPEG_EXE,ART/'cqt_feature_cache')
        return cache[key]
    signature=hashlib.sha256(pp.read_bytes()).hexdigest();checkpoint=ART/'precision_rescue_checkpoint.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[r['file']]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,(file,row) in enumerate(rows.items(),1):
            if file in done:results.append(done[file]);continue
            candidates=[dict(c) for c in row['candidates']];begin=time.perf_counter();checked=[]
            if row['score']<.60:
                with np.load(base.cache_key(Path(file),False,all_query_windows=True),allow_pickle=False) as f:q,starts=f['vectors'].astype(np.float32),f['offsets'].tolist()
                sim=agg.unit_rows(q-mean)@centered.T
                ranked=sorted([{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups],key=lambda r:r['clapScore'],reverse=True)
                qt,_,qs=features(Path(file))
                for match in ranked[:3]:
                    ref,_,rs=features(paths[match['trackId']]);whole=tonal.compare(qt,ref,qs,rs);fragment=fragments.compare(qt,ref,qs,rs,center_time=False)
                    score=max(.5*whole['tonalScore']**2,fragment['fragmentScore'])
                    candidate=next(c for c in candidates if c['trackId']==match['trackId'])
                    if score>candidate['tonalScore']:
                        candidate['tonalScore']=score;candidate['rescue_whole']=whole;candidate['rescue_fragments']=fragment['fragments']
                    checked.append({'trackId':match['trackId'],'rescue_score':score,'whole_score':whole['tonalScore'],'fragments':fragment['fragments']})
            candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
            result={**row,'signature':signature,'method':protocol['method'],'candidates':candidates,'score':candidates[0]['tonalScore'],
                'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
                'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None),
                'rescue_checked':checked,'rescue_seconds':time.perf_counter()-begin}
            results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[precision rescue {n}/{len(rows)}] checked={len(checked)}',flush=True)
    excluded=exp.read(ART/'ai_selective_retrieval_evaluation.json')['excluded_normal_filenames']
    summary={}
    for split in sorted({r['split'] for r in results}):
        part=[r for r in results if r['split']==split]
        summary[split]=exp.metrics(part,policy,excluded)
        if split=='prospective_five_family':summary['by_family']={kind:exp.metrics([r for r in part if r['query_kind']==kind],policy) for kind in sorted({r['query_kind'] for r in part})}
    report={'protocol':protocol,'signature':signature,'summary':summary,'raw_test':exp.metrics([r for r in results if r['split']=='test'],policy),
        'active_policy_changed':False,'rescue_queries':sum(bool(r['rescue_checked']) for r in results)}
    (ART/'precision_rescue_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
