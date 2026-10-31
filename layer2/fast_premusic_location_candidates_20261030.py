"""Fast CLAP-only candidate location screen from cached window embeddings."""
from __future__ import annotations
import hashlib, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'.runtime-tests/new-premusic-20261030'; PLAN=OUT/'query_plan_all.json'; REPORT=ROOT/'layer2/artifacts/premusic_location_candidate_screen_20261030.json'
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  while c:=f.read(4*1024*1024): h.update(c)
 return h.hexdigest()
def main():
 plan=json.loads(PLAN.read_text(encoding='utf-8')); qs=[q for q in plan['queries'] if q['kind']!='full']
 sys.path.insert(0,str(ROOT/'api')); from engine import Engine
 import evaluate_top3_aggregation as agg
 engine=Engine(scope='ai_labeled')
 flat=[]
 for p in sorted((OUT/'embedding_cache').glob('*.npy'),key=lambda p:int(p.stem)): flat.append(np.load(p,allow_pickle=False))
 allv=np.concatenate(flat)
 records=[]; cursor=0
 for i,q in enumerate(qs):
  offsets=[0.0,10.0,20.0]
  # Embedding batches are concatenated in query order; rebuild the query slice.
  count=3; qv=allv[cursor:cursor+count]; cursor+=count
  sims=qv@engine.centered.T; candidates=[]
  for track,idx in engine.groups:
   idx=idx[np.argsort(engine.offsets[idx],kind='stable')]; score,_=agg.non_overlapping_top3(sims[:,idx],offsets); candidates.append((float(score),track))
  candidates.sort(reverse=True)
  records.append({'name':q['name'],'kind':q['kind'],'clap_candidate_score':candidates[0][0],'best_track':candidates[0][1],'top3':candidates[:3]})
  if (i+1)%50==0: print(f'[candidate {i+1}/{len(qs)}]',flush=True)
 by=defaultdict(dict)
 for r in records: by[r['name']][r['kind']]=r
 positions={}
 for kind in ('start30','middle30','end30'):
  rows=[r for r in records if r['kind']==kind]; positions[kind]={'count':len(rows),'candidate_score_ge_warn':sum(r['clap_candidate_score']>=engine.thresholds['warn'] for r in rows),'scores':[r['clap_candidate_score'] for r in rows]}
 union=[name for name,d in by.items() if any(r['clap_candidate_score']>=engine.thresholds['warn'] for r in d.values())]
 REPORT.write_text(json.dumps({'date':'2026-10-30','method':'CLAP candidate score only; not final production decision','thresholds':engine.thresholds,'works':len(by),'positions':positions,'union_candidate_warnings':len(union),'union_names':union,'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'works':len(by),'positions':{k:{a:v for a,v in x.items() if a!='scores'} for k,x in positions.items()},'union_candidate_warnings':len(union)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
