"""Memory bounded start/middle/end location evaluation for the 2026-10-31 batch."""
from __future__ import annotations
import argparse, hashlib, json, sys, subprocess
from collections import defaultdict
from pathlib import Path
import numpy as np, torch

ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(4*1024*1024),b''): h.update(c)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--selection',type=Path,required=True); ap.add_argument('--cache',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    plan=json.loads(args.plan.read_text(encoding='utf-8')); selection=json.loads(args.selection.read_text(encoding='utf-8'))
    queries=[q for q in plan['queries'] if q['kind']!='full']; sources={x['sha256']:Path(x['path']) for x in selection['selected']}
    sys.path.insert(0,str(ROOT/'api')); from engine import Engine
    import evaluate_retrieval_baseline as base, evaluate_top3_aggregation as agg, tonal_alignment as tonal, selective_retrieval as selective
    engine=Engine(scope='ai_labeled'); ffmpeg=base.find_ffmpeg(); base.FFMPEG_EXE=ffmpeg
    args.out.parent.mkdir(parents=True,exist_ok=True); checkpoint=args.out.with_suffix('.jsonl'); done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line); done[(r['work_id'],r['kind'])]=r
    ref_tonal={}; results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for i,qry in enumerate(queries,1):
            key=(qry['work_id'],qry['kind'])
            if key in done: results.append(done[key]); continue
            path=Path(qry['file']); cache=args.cache/(qry['sha256']+'.v3.npz'); cache.parent.mkdir(parents=True,exist_ok=True)
            if cache.exists():
                with np.load(cache,allow_pickle=False) as saved: audio,offsets=saved['audio'],saved['offsets'].tolist()
            else:
                source=sources[qry['work_id']]; subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-ss',str({'start30':0,'middle30':30,'end30':60}[qry['kind']]),'-i',str(source),'-t','30','-ac','1','-ar','22050',str(path)],check=True,capture_output=True)
                audio,offsets=base.extract_windows(path,False,query_window_count=3,all_query_windows=False); np.savez_compressed(cache,audio=audio,offsets=np.asarray(offsets,dtype=np.float32))
            inputs=engine.processor(audio=audio.tolist(),sampling_rate=base.SAMPLE_RATE,return_tensors='pt',padding=True).to(engine.device)
            with torch.inference_mode(): vec=torch.nn.functional.normalize(engine.model(**inputs).audio_embeds,dim=-1).cpu().numpy()
            sims=vec@engine.centered.T; candidates=[]
            for track,idx in engine.groups:
                idx=idx[np.argsort(engine.offsets[idx],kind='stable')]; score,selected=agg.non_overlapping_top3(sims[:,idx],offsets); candidates.append((float(score),track))
            candidates.sort(reverse=True); q_tonal=tonal.features(path,ffmpeg,None)[0]; confirmed=[]
            for rank,(retrieval,track) in enumerate(candidates[:3],1):
                if track not in ref_tonal: ref_tonal[track]=tonal.features(engine.reference_paths[track],ffmpeg,ROOT/'.runtime-tests/location-tonal-cache-20261031')[0]
                ev=tonal.compare(q_tonal,ref_tonal[track]); ev=selective.apply(ev,rank) if engine.candidate_score_rule else ev
                confirmed.append((ev['tonalScore'],track,ev))
            confirmed.sort(reverse=True,key=lambda x:x[0]); score,track,ev=confirmed[0]
            decision='HOLD' if score>=engine.thresholds['hold'] else 'WARN' if score>=engine.thresholds['warn'] else 'PASS'
            row={'work_id':qry['work_id'],'name':qry['name'],'kind':qry['kind'],'decision':decision,'score':score,'best_track':track,'match_start_seconds':ev['queryStartSec'],'match_end_seconds':ev['queryEndSec'],'retrieval_score':confirmed[0][2].get('retrievalScore')}
            done[key]=row; results.append(row); log.write(json.dumps(row,ensure_ascii=False)+'\n'); log.flush()
            if i%25==0: print(f'[stream {i}/{len(queries)}]',flush=True)
    by=defaultdict(dict)
    for r in results: by[r['work_id']][r['kind']]=r
    def warn(r): return r['decision'] in {'WARN','HOLD','BLOCK'}
    positions={}
    for kind in ('start30','middle30','end30'):
        rows=[d[kind] for d in by.values() if kind in d]; bad=[r for r in rows if warn(r)]; positions[kind]={'works':len(rows),'warnings':len(bad),'warning_rate':len(bad)/len(rows),'holds':sum(r['decision'] in {'HOLD','BLOCK'} for r in rows),'warning_names':[r['name'] for r in bad]}
    union=[d for d in by.values() if any(kind in d and warn(d[kind]) for kind in ('start30','middle30','end30'))]
    full={'date':'2026-10-31','method':'streaming CLAP windows plus top-3 tonal confirmation','thresholds':engine.thresholds,'query_count':len(results),'works':len(by),'positions':positions,'three_30s_union':{'works':len(by),'warnings':len(union),'warning_rate':len(union)/len(by),'warning_names':[next(iter(d.values()))['name'] for d in union]},'results':results}
    args.out.write_text(json.dumps(full,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'works':len(by),'positions':positions,'union_warnings':len(union)},ensure_ascii=False))
if __name__=='__main__': main()
