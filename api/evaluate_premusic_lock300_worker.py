"""Parallel worker for the fixed premusic lock300 audit."""
from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
from engine import Engine
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'api/runtime'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--part',type=int,required=True);a.add_argument('--start',type=int,required=True);a.add_argument('--end',type=int,required=True);x=a.parse_args()
 rows=json.loads((R/'premusic_lock300_selection.json').read_text('utf-8'))['selected'][x.start:x.end];out=R/f'premusic_lock300_part{x.part}.jsonl';done={}
 if out.exists():
  for line in out.read_text('utf-8').splitlines():done[json.loads(line)['sha256']]=1
 engine=Engine()
 for offset,row in enumerate(rows,x.start+1):
  p=Path(row['path']);d=sha(p)
  if d in done:continue
  t=time.perf_counter()
  try:
   r=engine.verify(p,d);item={'index':offset,'sha256':d,'path':str(p),'decision':r['decision'],'similarityScore':r['similarityScore'],'queryVerifierScore':r.get('queryVerifierScore'),'scoreVersion':r['scoreVersion'],'decisionPolicyVersion':r['decisionPolicyVersion'],'thresholds':r['thresholds'],'top3':r['similarTracks'],'processingSeconds':round(time.perf_counter()-t,3)}
  except Exception as e:item={'index':offset,'sha256':d,'path':str(p),'decision':'ERROR','error':f'{type(e).__name__}: {e}','processingSeconds':round(time.perf_counter()-t,3)}
  with out.open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
  print(f'part{x.part} {offset}/300 {item["decision"]} {p.name}',flush=True)
if __name__=='__main__':main()
