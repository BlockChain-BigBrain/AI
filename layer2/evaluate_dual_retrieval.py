"""Compare CLAP+tonal candidates to the frozen selective retrieval policy.

Existing queries are reused diagnostics. No active policy is overwritten.
"""
from pathlib import Path
import hashlib,json,time
import numpy as np
from threadpoolctl import threadpool_limits
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal
import dual_tonal_retrieval as dual
import selective_retrieval as selective
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    threadpool_limits(limits=4)
    protocol={'date':'2026-10-23','method':'clap20-union-pitch-fourier20',
        'candidate_only_index':dual.VERSION,'decision_score_rule':selective.RULE,
        'limits':'All existing queries observed. Diagnostic comparison, no blind validation or automatic activation.',
        'selection':'Tune source recall and normal targets; keep active AI policy if no positive source-recall gain.',
        'candidates':{'clap':20,'pitch_sequence':20,'union_max':40}}
    pp=ART/'dual_retrieval_protocol.json'
    if pp.exists():assert exp.read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    old=exp.read(ART/'ai_labeled_recalibration.json');current=exp.read(ART/'ai_selective_retrieval_evaluation.json')
    rows={}
    for line in (ART/'ai_selective_retrieval_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);rows[(r['scope'],r['file'])]=r
    for line in (ART/'ai_selective_replication_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);r={**r,**r['selected'],'split':'new_replication'};rows[(r['scope'],r['file'])]=r
    base.FFMPEG_EXE=base.find_ffmpeg()
    paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    index=dual.Index(paths,base.FFMPEG_EXE,ART/'tonal_feature_cache')
    np.savez_compressed(ART/'dual_tonal_index.npz',vectors=index.matrix,ids=np.asarray(index.ids),starts=index.starts)
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,ids=f['vectors'].astype(np.float32),f['ids']
    catalogs={}
    for scope,profile in old['profiles'].items():
        allowed=set(profile['allowed_reference_ids']) if scope=='ai_labeled_catalog' else None
        mask=np.isin(ids,list(allowed)) if allowed else np.ones(len(ids),bool)
        v,i=vectors[mask],ids[mask];mean=v.mean(axis=0)
        catalogs[scope]=(mean,agg.unit_rows(v-mean),[(str(t),np.flatnonzero(i==t)) for t in np.unique(i)],allowed)
    signature=hashlib.sha256((pp.read_text(encoding='utf-8')+current['signature']).encode()).hexdigest()
    checkpoint=ART/'dual_retrieval_checkpoint.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['file'])]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,((scope,file),row) in enumerate(rows.items(),1):
            if (scope,file) in done:results.append(done[(scope,file)]);continue
            path=Path(file);qt,_,qs=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
            mean,centered,groups,allowed=catalogs[scope]
            with np.load(base.cache_key(path,False,all_query_windows=True),allow_pickle=False) as f:q,starts=f['vectors'].astype(np.float32),f['offsets'].tolist()
            sim=agg.unit_rows(q-mean)@centered.T
            ranked=sorted([{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups],key=lambda r:r['clapScore'],reverse=True)
            clap={r['trackId']:{**r,'retrievalRank':i} for i,r in enumerate(ranked,1)}
            begin=time.perf_counter();secondary=index.search(qt,allowed,20);search_seconds=time.perf_counter()-begin
            secondary_ids={c['trackId'] for c in secondary};selected={c['trackId'] for c in ranked[:20]}|secondary_ids
            candidates=[]
            existing={c['trackId']:c for c in row['candidates']}
            for track in sorted(selected):
                if track in existing:
                    evidence=existing[track].copy()
                    evidence['tonalScore']=evidence.get('unpenalizedTonalScore',evidence['tonalScore'])
                else:
                    ref,_,rs=index.features[track];evidence=tonal.compare(qt,ref,qs,rs)
                candidates.append({**selective.apply(evidence,clap[track]['retrievalRank']),**clap[track]})
            candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
            source_score=next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None)
            result={**row,'signature':signature,'method':protocol['method'],'score':candidates[0]['tonalScore'],
                'expected_score':source_score,'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None),
                'candidates':candidates,'candidate_count':len(candidates),'secondary_search_seconds':search_seconds,
                'secondary_source_retrieved':row['expected_track_id'] in secondary_ids}
            results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[dual retrieval {n}/{len(rows)}] {scope}',flush=True)
    excluded=current['excluded_normal_filenames'];profiles={}
    for scope in catalogs:
        part=[r for r in results if r['scope']==scope];cal=exp.calibrate(part);policy={**cal,'warn_threshold':cal['normal_boundary']}
        profiles[scope]={**policy,'tune':exp.metrics([r for r in part if r['split']=='tune'],policy),
            'test_raw':exp.metrics([r for r in part if r['split']=='test'],policy),
            'test_audited':exp.metrics([r for r in part if r['split']=='test'],policy,excluded),
            'first_stress':exp.metrics([r for r in part if r['split']=='new_transform_stress'],policy),
            'replication':exp.metrics([r for r in part if r['split']=='new_replication'],policy),
            'source_candidate_recall':float(np.mean([r['expected_score'] is not None for r in part if r['dataset']=='positive'])),
            'mean_candidates':float(np.mean([r['candidate_count'] for r in part])),
            'secondary_search_p95_seconds':float(np.quantile([r['secondary_search_seconds'] for r in part],.95))}
    report={'protocol':protocol,'signature':signature,'profiles':profiles,'active_policy_changed':False,
        'index_descriptors':len(index.matrix),'index_dimension':index.matrix.shape[1],
        'index_sha256':hashlib.sha256((ART/'dual_tonal_index.npz').read_bytes()).hexdigest()}
    (ART/'dual_retrieval_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
