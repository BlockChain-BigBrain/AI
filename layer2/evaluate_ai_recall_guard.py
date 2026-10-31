"""Round 2: reject margin-only policy, expand retrieval with recall guard.

Round-1 stress has been observed and is now diagnostic development evidence.
Threshold uses only old tune normals; no numerical fit to stress scores.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import compare_ai_improvements as exp
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    first=exp.read(ART/'ai_improvement_comparison.json')
    old=exp.read(ART/'ai_labeled_recalibration.json')
    protocol={'date':'2026-10-23','round':2,'method':'recall_guard_top20','retrieval_top_k':20,
        'reason':'Round-1 midpoint thresholds rejected: 17/28 vs baseline 25/28 on new-transform diagnostic.',
        'warn_rule':'Lowest inclusive threshold meeting tune normal FPR<=10%, unchanged from original calibration recipe.',
        'hold_rule':'Maximum of tune normal FPR<=2% boundary and tune confirmed-positive source 25th percentile.',
        'selection_status':'Round-1 test/stress observed; engineering revision, not blind method selection.',
        'replication':'Freeze this policy, then run +2-semitone/0.94-tempo/AAC96k and alternate splicing/1.08-tempo queries on same 14 works.',
        'acceptance':'Tune and audited existing-test normal WARN<=10%, HOLD<=2%; source recall >=90% on existing test, old stress and new replication.'}
    target=ART/'ai_recall_guard_protocol.json'
    if target.exists():assert exp.read(target)==protocol
    else:target.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    excluded=first['excluded_normal_filenames']
    saved={}
    for line in (ART/'ai_improvement_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line)
        if r['signature']==first['signature'] and r['method']=='margin_top20':saved[(r['scope'],r['file'])]=r
    stress={}
    for line in (ART/'ai_improvement_stress_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);stress[(r['scope'],r['file'])]=r
    base.FFMPEG_EXE=base.find_ffmpeg()
    paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,ids=f['vectors'].astype(np.float32),f['ids']
    catalogs={}
    for scope,profile in old['profiles'].items():
        mask=np.isin(ids,profile['allowed_reference_ids']) if scope=='ai_labeled_catalog' else np.ones(len(ids),bool)
        v,i=vectors[mask],ids[mask];mean=v.mean(axis=0)
        catalogs[scope]=(mean,agg.unit_rows(v-mean),[(str(t),np.flatnonzero(i==t)) for t in np.unique(i)])
    feature_cache={}
    def features(path):
        key=str(path)
        if key not in feature_cache:feature_cache[key]=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
        return feature_cache[key]
    checkpoint=ART/'ai_recall_guard_checkpoint.jsonl';done={}
    signature=hashlib.sha256((target.read_text(encoding='utf-8')+first['signature']).encode()).hexdigest()
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['file'])]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,((scope,file),row) in enumerate(stress.items(),1):
            if (scope,file) in done:results.append(done[(scope,file)]);continue
            path=Path(file)
            if scope=='full_catalog':candidates=row['selected']['candidates']
            else:
                with np.load(base.cache_key(path,False,all_query_windows=True),allow_pickle=False) as f:q,starts=f['vectors'].astype(np.float32),f['offsets'].tolist()
                mean,centered,groups=catalogs[scope];sim=agg.unit_rows(q-mean)@centered.T
                ranked=[{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups]
                ranked.sort(key=lambda r:r['clapScore'],reverse=True)
                existing={c['trackId']:c for c in row['selected']['candidates']}
                other=stress[('full_catalog',file)]
                existing.update({c['trackId']:c for c in other['selected']['candidates']})
                qt,_,qs=features(path);candidates=[]
                for match in ranked[:20]:
                    if match['trackId'] in existing:evidence=existing[match['trackId']]
                    else:
                        ref,_,rs=features(paths[match['trackId']]);evidence=tonal.compare(qt,ref,qs,rs)
                    candidates.append({**evidence,**match})
            candidates=sorted(candidates,key=lambda r:r['tonalScore'],reverse=True)
            result={**{k:v for k,v in row.items() if k not in ('baseline','selected')},'signature':signature,
                'method':'recall_guard_top20','candidates':candidates,'score':candidates[0]['tonalScore'],
                'expected_score':next((r['tonalScore'] for r in candidates if r['trackId']==row['expected_track_id']),None),
                'source_rank_after_tonal':next((i for i,r in enumerate(candidates,1) if r['trackId']==row['expected_track_id']),None)}
            results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[recall guard {n}/{len(stress)}] {scope}',flush=True)
    profiles={}
    for scope,profile in old['profiles'].items():
        rows=[r for (s,_),r in saved.items() if s==scope]
        calibrated=exp.calibrate(rows)
        policy={**calibrated,'warn_threshold':calibrated['normal_boundary']}
        profiles[scope]={**policy,'score_version':tonal.VERSION,'retrieval_top_k':20,'method':'recall_guard_top20',
            'tune':exp.metrics([r for r in rows if r['split']=='tune'],policy),
            'test_raw':exp.metrics([r for r in rows if r['split']=='test'],policy),
            'test_audited':exp.metrics([r for r in rows if r['split']=='test'],policy,excluded),
            'premusic_diagnostic':exp.metrics([r for r in rows if r['split']=='external_diagnostic'],policy),
            'round1_stress':exp.metrics([r for r in results if r['scope']==scope],policy)}
    output={'protocol':protocol,'signature':signature,'original_policy_sha256':first['original_policy_sha256'],
        'comparison_sha256':hashlib.sha256((ART/'ai_improvement_comparison.json').read_bytes()).hexdigest(),
        'profiles':profiles,'excluded_normal_filenames':excluded}
    (ART/'ai_recall_guard_evaluation.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
