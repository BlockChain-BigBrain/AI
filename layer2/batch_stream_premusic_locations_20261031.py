"""Chunked location evaluation that keeps at most 64 queries in memory."""
from __future__ import annotations
import argparse, hashlib, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np, torch

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--selection',type=Path,required=True); ap.add_argument('--cache',type=Path,required=True); ap.add_argument('--report',type=Path,required=True); ap.add_argument('--checkpoint',type=Path,required=True); args=ap.parse_args()
    plan=json.loads(args.plan.read_text(encoding='utf-8')); selection=json.loads(args.selection.read_text(encoding='utf-8'))
    qs=[q for q in plan['queries'] if q['kind']!='full']; sources={x['sha256']:Path(x['path']) for x in selection['selected']}
    sys.path.insert(0,str(ROOT/'api')); from engine import Engine
    import evaluate_retrieval_baseline as base, evaluate_top3_aggregation as agg, tonal_alignment as tonal, selective_retrieval as selective
    engine=Engine(scope='ai_labeled'); torch.set_num_threads(16); ffmpeg=base.find_ffmpeg(); base.FFMPEG_EXE=ffmpeg
    done={}
    if args.checkpoint.exists():
        for line in args.checkpoint.read_text(encoding='utf-8').splitlines():
            row=json.loads(line); done[(row['work_id'],row['kind'])]=row
    args.checkpoint.parent.mkdir(parents=True,exist_ok=True); ref_tonal={}
    with args.checkpoint.open('a',encoding='utf-8') as log:
      for start in range(0,len(qs),64):
        batch=qs[start:start+64]; pending=[]; audio_rows=[]; flat=[]
        for q in batch:
            key=(q['work_id'],q['kind'])
            if key in done: continue
            cache=args.cache/(q['sha256']+'.v3.npz')
            with np.load(cache,allow_pickle=False) as saved: audio,offsets=saved['audio'],saved['offsets'].tolist()
            pending.append((q,offsets)); flat.extend(audio.tolist()); audio_rows.append(len(audio))
        if not pending: continue
        inputs=engine.processor(audio=flat,sampling_rate=base.SAMPLE_RATE,return_tensors='pt',padding=True).to(engine.device)
        with torch.inference_mode(): vec=torch.nn.functional.normalize(engine.model(**inputs).audio_embeds,dim=-1).cpu().numpy()
        cursor=0
        for q,offsets in pending:
            n=3; qv=vec[cursor:cursor+n]; cursor+=n; sims=qv@engine.centered.T; candidates=[]
            for track,idx in engine.groups:
                idx=idx[np.argsort(engine.offsets[idx],kind='stable')]; score,selected=agg.non_overlapping_top3(sims[:,idx],offsets); candidates.append((float(score),track))
            candidates.sort(reverse=True); qpath=Path(q['file']); q_tonal=tonal.features(qpath,ffmpeg,None)[0]; confirmed=[]
            for rank,(retrieval,track) in enumerate(candidates[:3],1):
                if track not in ref_tonal: ref_tonal[track]=tonal.features(engine.reference_paths[track],ffmpeg,ROOT/'.runtime-tests/location-tonal-cache-20261031')[0]
                ev=tonal.compare(q_tonal,ref_tonal[track]); ev=selective.apply(ev,rank) if engine.candidate_score_rule else ev; confirmed.append((ev['tonalScore'],track,ev,retrieval))
            confirmed.sort(reverse=True,key=lambda x:x[0]); score,track,ev,retrieval=confirmed[0]; decision='HOLD' if score>=engine.thresholds['hold'] else 'WARN' if score>=engine.thresholds['warn'] else 'PASS'
            row={'work_id':q['work_id'],'name':q['name'],'kind':q['kind'],'decision':decision,'score':score,'best_track':track,'match_start_seconds':ev['queryStartSec'],'match_end_seconds':ev['queryEndSec'],'retrieval_score':retrieval}; done[(q['work_id'],q['kind'])]=row; log.write(json.dumps(row,ensure_ascii=False)+'\n'); log.flush()
        print(f'[batch {min(start+64,len(qs))}/{len(qs)}]',flush=True)
    results=list(done.values()); by=defaultdict(dict)
    for r in results: by[r['work_id']][r['kind']]=r
    def warn(r): return r['decision'] in {'WARN','HOLD','BLOCK'}
    positions={}
    for kind in ('start30','middle30','end30'):
        rows=[d[kind] for d in by.values() if kind in d]; bad=[r for r in rows if warn(r)]; positions[kind]={'works':len(rows),'warnings':len(bad),'warning_rate':len(bad)/len(rows) if rows else None,'holds':sum(r['decision'] in {'HOLD','BLOCK'} for r in rows),'warning_names':[r['name'] for r in bad]}
    union=[d for d in by.values() if any(k in d and warn(d[k]) for k in ('start30','middle30','end30'))]
    report={'date':'2026-10-31','status':'completed' if len(results)==len(qs) else 'incomplete','method':'chunked CLAP windows plus top-3 tonal confirmation','thresholds':engine.thresholds,'query_count':len(results),'works':len(by),'positions':positions,'three_30s_union':{'works':len(by),'warnings':len(union),'warning_rate':len(union)/len(by) if by else None,'warning_names':[next(iter(d.values()))['name'] for d in union]},'results':results}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'status':report['status'],'works':len(by),'positions':positions,'union_warnings':len(union)},ensure_ascii=False))
if __name__=='__main__': main()
