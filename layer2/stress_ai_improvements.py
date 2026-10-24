"""New-transform stress check after development-only method selection.

These are new queries from previously evaluated works, not blind unseen works.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time
import numpy as np
import torch
import compare_ai_improvements as experiment
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal
import selective_retrieval as selective

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
OUT=ROOT/'layer2/test_data/ai_improvement_stress'


def main():
    global OUT
    replication='--replication' in sys.argv
    base.FFMPEG_EXE=base.find_ffmpeg()
    comparison_path=ART/('ai_selective_retrieval_evaluation.json' if replication else 'ai_improvement_comparison.json')
    comparison=experiment.read(comparison_path)
    frozen_hash=hashlib.sha256(comparison_path.read_bytes()).hexdigest()
    if replication:
        OUT=ROOT/'layer2/test_data/ai_selective_replication'
        comparison={'profiles':{scope:{'selected_method':'margin_top20','methods':{'margin_top20':p}} for scope,p in comparison['profiles'].items()}}
    old=experiment.read(ART/'ai_labeled_recalibration.json')
    manifest=experiment.read(ROOT/'layer2/test_data/ai_labeled_positive/manifest.json')
    ids=sorted({r['expected_track_id'] for r in manifest['rows'] if r['split']=='test' and r['dataset']=='positive'})
    paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    OUT.mkdir(exist_ok=True)
    prepared=[]
    for i,track in enumerate(ids):
        source=paths[track];duration=base.get_duration_seconds(source)
        offset=max(0,(duration-45)/2)
        variants={
            'pitch_tempo_codec':('m4a',[base.FFMPEG_EXE,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(source),'-t','30',
                '-af','aresample=22050,asetrate=26222,aresample=22050,atempo=0.8409,atempo=1.12,lowpass=f=3200,acompressor=threshold=0.125:ratio=3',
                '-ac','1','-ar','22050','-c:a','aac','-b:a','64k']),
            'spliced_sections':('wav',[base.FFMPEG_EXE,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(source),
                '-filter_complex','[0:a]aresample=22050,asplit=2[a][b];[a]atrim=18:30,asetpts=PTS-STARTPTS[a1];[b]atrim=0:12,asetpts=PTS-STARTPTS[b1];[a1][b1]concat=n=2:v=0:a=1,atempo=0.92[out]',
                '-map','[out]','-ac','1','-ar','22050']),
        }
        if replication:
            variants['pitch_tempo_codec'][1][variants['pitch_tempo_codec'][1].index('-af')+1]='aresample=22050,asetrate=24751,aresample=22050,atempo=0.8909,atempo=0.94,lowpass=f=4200,acompressor=threshold=0.125:ratio=3'
            variants['pitch_tempo_codec'][1][-1]='96k'
            variants['spliced_sections'][1][variants['spliced_sections'][1].index('-filter_complex')+1]='[0:a]aresample=22050,asplit=2[a][b];[a]atrim=20:33,asetpts=PTS-STARTPTS[a1];[b]atrim=2:15,asetpts=PTS-STARTPTS[b1];[a1][b1]concat=n=2:v=0:a=1,atempo=1.08[out]'
        for kind,(extension,command) in variants.items():
            path=OUT/f'{i:03}__{kind}.{extension}'
            if not path.exists():subprocess.run(command+[str(path)],check=True,capture_output=True)
            prepared.append({'file':str(path),'dataset':'positive','split':'new_transform_stress','query_kind':kind,
                'expected_track_id':track,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_offset_seconds':offset,
                'ffmpeg_arguments':command[1:]})
    locked={'comparison_sha256':frozen_hash,'works':ids,'status':'New transformations, previously observed works; not blind validation.',
        'rows':prepared}
    target=OUT/'manifest.json'
    if target.exists():assert experiment.read(target)==locked,'Frozen stress manifest changed.'
    else:target.write_text(json.dumps(locked,indent=2),encoding='utf-8')
    torch.set_num_threads(4);device=torch.device('cpu')
    model=agg.ClapAudioModelWithProjection.from_pretrained(base.BASE_MODEL,local_files_only=True).eval()
    processor=agg.ClapProcessor.from_pretrained(base.BASE_MODEL,local_files_only=True)
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,all_ids=f['vectors'].astype(np.float32),f['ids']
    catalogs={}
    for scope,profile in old['profiles'].items():
        mask=np.isin(all_ids,profile['allowed_reference_ids']) if scope=='ai_labeled_catalog' else np.ones(len(all_ids),bool)
        v,ids_=vectors[mask],all_ids[mask];mean=v.mean(axis=0)
        catalogs[scope]=(mean,agg.unit_rows(v-mean),[(str(t),np.flatnonzero(ids_==t)) for t in np.unique(ids_)])
    cache={}
    def features(path):
        key=str(path)
        if key not in cache:cache[key]=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
        return cache[key]
    checkpoint=ART/('ai_selective_replication_checkpoint.jsonl' if replication else 'ai_improvement_stress_checkpoint.jsonl')
    signature=hashlib.sha256(target.read_bytes()).hexdigest()
    done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['file'])]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,row in enumerate(prepared,1):
            path=Path(row['file']);q,starts=base.embed_file(path,model,processor,device,False,all_query_windows=True)
            qt,_,qs=features(path)
            for scope,(mean,centered,groups) in catalogs.items():
                if (scope,row['file']) in done:results.append(done[(scope,row['file'])]);continue
                selected=comparison['profiles'][scope]['selected_method']
                sim=agg.unit_rows(q-mean)@centered.T
                ranked=[{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups]
                ranked.sort(key=lambda r:r['clapScore'],reverse=True)
                confirmed=[]
                t0=time.perf_counter()
                for index,match in enumerate(ranked[:20 if selected=='margin_top20' else 5]):
                    ref,_,rs=features(paths[match['trackId']])
                    confirmed.append({**match,'retrievalRank':index+1,**tonal.compare(qt,ref,qs,rs)})
                baseline=sorted(confirmed[:5],key=lambda r:r['tonalScore'],reverse=True)
                if selected=='contrast_top5':
                    selected_candidates=[]
                    for match in ranked[:5]:
                        ref,_,rs=features(paths[match['trackId']])
                        selected_candidates.append({**match,**tonal.compare(experiment.contrast(qt),experiment.contrast(ref),qs,rs)})
                else:selected_candidates=confirmed
                if replication:
                    selected_candidates=[selective.apply(c,i) for i,c in enumerate(selected_candidates,1)]
                def convert(candidates):
                    candidates=sorted(candidates,key=lambda r:r['tonalScore'],reverse=True)
                    return {'candidates':candidates,'score':candidates[0]['tonalScore'],
                        'expected_score':next((r['tonalScore'] for r in candidates if r['trackId']==row['expected_track_id']),None),
                        'source_rank_after_tonal':next((i for i,r in enumerate(candidates,1) if r['trackId']==row['expected_track_id']),None)}
                result={**row,'scope':scope,'signature':signature,'selected_method':selected,
                    'baseline':convert(baseline),'selected':convert(selected_candidates),'confirmation_seconds':time.perf_counter()-t0}
                results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[new stress {n}/{len(prepared)}] {row["query_kind"]}',flush=True)
    summary={}
    for scope,profile in comparison['profiles'].items():
        rows=[r for r in results if r['scope']==scope];selected=profile['selected_method'];policy=profile['methods'][selected]
        summary[scope]={'selected_method':selected}
        for method,p in [('baseline',old['profiles'][scope]),('selected',policy)]:
            part=[{**r,**r[method]} for r in rows]
            summary[scope][method]={
                'all':experiment.metrics(part,p),
                'by_transformation':{kind:experiment.metrics([r for r in part if r['query_kind']==kind],p) for kind in variants}}
    report={'date':'2026-10-23','comparison_sha256':frozen_hash,'manifest_sha256':signature,'source_works':len(ids),
        'positive_queries':len(prepared),'status':locked['status'],'profiles':summary}
    (ART/('ai_selective_replication_summary.json' if replication else 'ai_improvement_stress_summary.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
