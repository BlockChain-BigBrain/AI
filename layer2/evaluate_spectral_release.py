"""Octave-preserving confirmation and duration-matched grouped negatives.

Reuses known source works; new crops are not independently generated works.
Normal decisions are aggregated by work, never counted as independent crops.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess
import numpy as np
from threadpoolctl import threadpool_limits
import torch
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal
import dual_tonal_retrieval as dual
import spectral_sequence as spectral

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
OUT=ROOT/'layer2/test_data/duration_matched_normal_20261024'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def fragments(query,ref,qs,rs):
    if len(query)*qs<45:return 0.,[]
    width=round(10/qs);starts=list(range(0,len(query)-width+1,width))
    if len(starts)>12:starts=[starts[i] for i in np.linspace(0,len(starts)-1,12).astype(int)]
    matches=[]
    for start in starts:
        evidence=spectral.compare(query[start:start+width],ref,qs,rs)
        if evidence['queryEndSec']-evidence['queryStartSec']<8 or evidence['refEndSec']-evidence['refStartSec']<8:continue
        evidence['queryStartSec']+=start*qs;evidence['queryEndSec']+=start*qs;matches.append(evidence)
    selected=[]
    for evidence in sorted(matches,key=lambda c:c['spectralScore'],reverse=True):
        if all(max(0,min(evidence['refEndSec'],r['refEndSec'])-max(evidence['refStartSec'],r['refStartSec']))<4 for r in selected):selected.append(evidence)
        if len(selected)==3:break
    score=float(np.mean([r['spectralScore'] for r in selected])) if len(selected)==3 and min(r['spectralScore'] for r in selected)>=.65 else 0.
    return score,selected


def metrics(rows,warn,hold,excluded):
    pos=[r for r in rows if r['dataset']=='positive'];neg=[r for r in rows if r['dataset']!='positive' and r['file'] not in excluded]
    grouped={}
    for row in neg:grouped[row['group_id']]=max(grouped.get(row['group_id'],0.),row['score'])
    correct=sum(r['expected_score'] is not None and r['expected_score']>=warn and r['source_rank']<=3 for r in pos)
    return {'positive_queries':len(pos),'positive_source_works':len({r['expected_track_id'] for r in pos}),
        'correct_source_warn_top3_count':correct,'correct_source_warn_top3_recall':correct/len(pos) if pos else None,
        'normal_queries':len(neg),'normal_works':len(grouped),'normal_warn_works':sum(s>=warn for s in grouped.values()),
        'normal_hold_works':sum(s>=hold for s in grouped.values()),'normal_warn_rate':sum(s>=warn for s in grouped.values())/len(grouped) if grouped else None,
        'normal_hold_rate':sum(s>=hold for s in grouped.values())/len(grouped) if grouped else None}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--summary-only',action='store_true');args=parser.parse_args()
    threadpool_limits(limits=4);torch.set_num_threads(4);base.FFMPEG_EXE=base.find_ffmpeg();OUT.mkdir(exist_ok=True)
    protocol={'date':'2026-10-24','features':spectral.VERSION,'short_negative_views':['start','middle','end'],
        'normal_unit':'Maximum warning score across all available views of each normal work; crops are not independent works.',
        'ai_candidates':'All 34 eligible references, no CLAP cutoff.',
        'full_candidates':'Union of CLAP Top20 and pitch-sequence Top20; maximum 40 references.',
        'fragment_rule':'For query>=45s, three separated >=8s spectral matches; each score>=.65; up to twelve 10s windows.',
        'warn_rule':'Tune normal-work FPR<=10% with minimum .55; HOLD tune FPR<=2% and minimum .85, ordered gap>=.05.',
        'limits':'Known works and previously observed positives; new duration-matched queries are diagnostic, not pure-AI or independent-work proof.'}
    pp=ART/'spectral_release_protocol.json'
    if pp.exists():assert read(pp)==protocol
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    previous={}
    for line in (ART/'secondary_precision_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line);row['group_id']=row.get('group_id','normal:'+Path(row['file']).stem) if row['dataset']!='positive' else 'positive:'+row['expected_track_id'];previous[row['file']]=row
    excluded={r['normal'] for r in read(ART/'ai_near_duplicate_audit.json')['pairs'] if r['quarantine_normal_label']}
    manifest=OUT/'manifest.json'
    if manifest.exists():crops=read(manifest)['rows']
    else:
        crops=[]
        for i,row in enumerate([r for r in previous.values() if r['dataset']!='positive' and r['file'] not in excluded]):
            path=Path(row['file']);duration=base.get_duration_seconds(path)
            for view,offset in [('start',0.),('middle',max(0,(duration-30)/2)),('end',max(0,duration-30))]:
                target=OUT/f'{i:03}__{view}.wav'
                subprocess.run([base.FFMPEG_EXE,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(path),'-t','30','-ac','1','-ar','22050',str(target)],capture_output=True,check=True)
                crops.append({**{k:row[k] for k in ('dataset','split','group_id','expected_track_id')},'file':str(target),
                    'query_kind':'normal_30s_'+view,'sha256':sha(target),'source_file':str(path),'source_sha256':sha(path),'offset_seconds':offset})
        manifest.write_text(json.dumps({'protocol_sha256':sha(pp),'rows':crops},indent=2),encoding='utf-8')
    queries=list(previous.values())+crops
    paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    old=read(ART/'ai_labeled_recalibration.json');allowed=set(old['profiles']['ai_labeled_catalog']['allowed_reference_ids'])
    if not args.summary_only:
        model=agg.ClapAudioModelWithProjection.from_pretrained(base.BASE_MODEL,local_files_only=True).eval()
        processor=agg.ClapProcessor.from_pretrained(base.BASE_MODEL,local_files_only=True);device=torch.device('cpu')
        with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,ids=f['vectors'].astype(np.float32),f['ids']
        mean=vectors.mean(axis=0);centered=agg.unit_rows(vectors-mean);groups=[(str(t),np.flatnonzero(ids==t)) for t in np.unique(ids)]
        with np.load(ART/'dual_tonal_index.npz',allow_pickle=False) as f:
            index=dual.Index.__new__(dual.Index);index.matrix=f['vectors'];index.ids=f['ids'].tolist();index.starts=f['starts'].tolist()
    cache={}
    def features(path):
        key=str(path)
        if key not in cache:cache[key]=spectral.features(path,base.FFMPEG_EXE,ART/'spectral_sequence_cache')
        return cache[key]
    signature=hashlib.sha256((sha(pp)+sha(manifest)+sha(ROOT/'layer2/spectral_sequence.py')).encode()).hexdigest()
    cp=ART/'spectral_release_checkpoint.jsonl';done={}
    if cp.exists():
        for line in cp.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['file'])]=r
    results=[]
    with cp.open('a',encoding='utf-8') as log:
        for n,row in enumerate(queries,1):
            scopes=('ai_labeled_catalog','full_catalog')
            if all((scope,row['file']) in done for scope in scopes):results.extend(done[(scope,row['file'])] for scope in scopes);continue
            if args.summary_only:raise RuntimeError('Missing or stale checkpoint row; run the full evaluation first.')
            path=Path(row['file']);q,_,qs=features(path)
            embedded,starts=base.embed_file(path,model,processor,device,False,all_query_windows=True)
            sim=agg.unit_rows(embedded-mean)@centered.T
            ranked=sorted([{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,ix],starts)[0]} for t,ix in groups],key=lambda c:c['clapScore'],reverse=True)
            qt,_,_=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
            full={c['trackId'] for c in ranked[:20]}|{c['trackId'] for c in index.search(qt,top_k=20)}
            all_scored={}
            for track in sorted(full|allowed):
                ref,_,rs=features(paths[track]);whole=spectral.compare(q,ref,qs,rs);fragment_score,selected=fragments(q,ref,qs,rs)
                score=max(whole['spectralScore'],fragment_score)
                all_scored[track]={'trackId':track,'score':score,'wholeScore':whole['spectralScore'],
                    'matchedSegments':selected if fragment_score>whole['spectralScore'] else [whole]}
            for scope,selected_ids in [('ai_labeled_catalog',allowed),('full_catalog',full)]:
                if (scope,row['file']) in done:results.append(done[(scope,row['file'])]);continue
                candidates=sorted([all_scored[t] for t in selected_ids],key=lambda c:c['score'],reverse=True)
                result={**{k:row.get(k) for k in ('file','dataset','split','group_id','query_kind','expected_track_id')},'signature':signature,'scope':scope,
                    'score':candidates[0]['score'],'expected_score':next((c['score'] for c in candidates if c['trackId']==row['expected_track_id']),None),
                    'source_rank':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None),'candidates':candidates}
                results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[spectral release {n}/{len(queries)}] {row["query_kind"]}',flush=True)
    profiles={}
    for scope in ('ai_labeled_catalog','full_catalog'):
        part=[r for r in results if r['scope']==scope];tune=[r for r in part if r['split']=='tune'];normal={}
        for r in tune:
            if r['dataset']!='positive' and r['file'] not in excluded:normal[r['group_id']]=max(normal.get(r['group_id'],0.),r['score'])
        scores=list(normal.values())
        def threshold(target,floor):
            choices=sorted(set([floor]+[max(floor,s) for s in scores]+[max(floor,float(np.nextafter(max(scores),np.inf)))]))
            return next(t for t in choices if sum(s>=t for s in scores)/len(scores)<=target)
        warn=threshold(.10,.55);hold=max(threshold(.02,.85),warn+.05)
        summary={split:metrics([r for r in part if r['split']==split],warn,hold,excluded) for split in sorted({r['split'] for r in part})}
        summary['five_family']={kind:metrics([r for r in part if r['split']=='prospective_five_family' and r['query_kind']==kind],warn,hold,excluded) for kind in ('basic','instrument_layer','long_auto_edit','room_effect','local_tempo')}
        profiles[scope]={'warn_threshold':warn,'hold_threshold':hold,'enabled':hold<1 and summary['tune']['correct_source_warn_top3_recall']>=.9,
            'summary':summary,'raw_test':metrics([r for r in part if r['split']=='test'],warn,hold,set())}
    report={'date':'2026-10-24','protocol':protocol,'signature':signature,'profiles':profiles,'normal_crop_queries':len(crops),'active_policy_changed':False}
    (ART/'spectral_release_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
