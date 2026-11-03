"""Run the frozen runtime against the fixed 300-track unused normal lock set."""
from __future__ import annotations
import hashlib,json,math,time
from pathlib import Path
from engine import Engine

ROOT=Path(__file__).resolve().parents[1];R=ROOT/'api/runtime'
SELECTION=R/'premusic_lock300_selection.json';OUT=R/'premusic_lock300_results.jsonl';SUMMARY=R/'premusic_lock300_summary.json'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def wilson(k,n,z=1.959963984540054):
 if not n:return {'low':None,'high':None}
 p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;m=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d
 return {'low':c-m,'high':c+m}
def main():
 selected=json.loads(SELECTION.read_text('utf-8'))['selected'];done={}
 if OUT.exists():
  for line in OUT.read_text('utf-8').splitlines():
   row=json.loads(line);done[row['sha256']]=row
 engine=Engine()
 for i,row in enumerate(selected,1):
  p=Path(row['path']);digest=sha(p)
  if digest!=row['sha256']:raise RuntimeError(f'hash changed: {p}')
  if digest in done:continue
  started=time.perf_counter()
  try:
   result=engine.verify(p,digest)
   item={'index':i,'sha256':digest,'path':str(p),'decision':result['decision'],
         'similarityScore':result['similarityScore'],'queryVerifierScore':result.get('queryVerifierScore'),
         'scoreVersion':result['scoreVersion'],'decisionPolicyVersion':result['decisionPolicyVersion'],
         'thresholds':result['thresholds'],'top3':result['similarTracks'],
         'processingSeconds':round(time.perf_counter()-started,3)}
  except Exception as error:
   item={'index':i,'sha256':digest,'path':str(p),'decision':'ERROR','error':f'{type(error).__name__}: {error}',
         'processingSeconds':round(time.perf_counter()-started,3)}
  with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
  done[digest]=item;print(f'{i}/300 {item["decision"]} {p.name}',flush=True)
 rows=[done[r['sha256']] for r in selected if r['sha256'] in done]
 counts={d:sum(r['decision']==d for r in rows) for d in ('PASS','WARN','HOLD','BLOCK')};n=len(rows)
 warn=counts['WARN']+counts['HOLD']+counts['BLOCK'];hold=counts['HOLD']+counts['BLOCK']
 summary={'protocol':'frozen unused normal-control lock300; selection fixed before scoring','rows':n,
          'complete':n==300,'counts':counts,'errorCount':sum(r['decision']=='ERROR' for r in rows),
          'warnOrHigher':{'count':warn,'rate':warn/n if n else None,'wilson95':wilson(warn,n)},
          'holdOrBlock':{'count':hold,'rate':hold/n if n else None,'wilson95':wilson(hold,n)},
          'scoreVersion':engine.score_version,'decisionPolicyVersion':engine.decision_policy_version,
          'thresholds':engine.thresholds,'meanProcessingSeconds':sum(r['processingSeconds'] for r in rows)/n if n else None}
 SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
