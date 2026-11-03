"""Combine parallel lock300 workers and write the confidence summary."""
from __future__ import annotations
import json,math
from pathlib import Path
R=Path(__file__).resolve().parents[1]/'api/runtime'
def wilson(k,n,z=1.959963984540054):
 if not n:return {'low':None,'high':None}
 p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;m=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d;return {'low':c-m,'high':c+m}
def main():
 rows=[]
 for i in range(4):
  p=R/f'premusic_lock300_part{i}.jsonl'
  if p.exists():rows.extend(json.loads(x) for x in p.read_text('utf-8').splitlines())
 rows=sorted({r['sha256']:r for r in rows}.values(),key=lambda r:r['index']);out=R/'premusic_lock300_results.jsonl';out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
 counts={d:sum(r['decision']==d for r in rows) for d in ('PASS','WARN','HOLD','BLOCK')};errors=sum(r['decision']=='ERROR' for r in rows);n=len(rows);valid=n-errors;warn=counts['WARN']+counts['HOLD']+counts['BLOCK'];hold=counts['HOLD']+counts['BLOCK']
 s={'protocol':'frozen unused normal-control lock300; selection fixed before scoring','rows':n,'complete':n==300,'counts':counts,'errorCount':errors,'validRows':valid,'warnOrHigher':{'count':warn,'rate':warn/valid if valid else None,'wilson95':wilson(warn,valid)},'holdOrBlock':{'count':hold,'rate':hold/valid if valid else None,'wilson95':wilson(hold,valid)},'scoreVersion':'hybrid_query_top3_pairwise_hold-v5','decisionPolicyVersion':'track-ai-balanced-policy-v5-20261102','thresholds':{'warn':0.351229127861893,'hold':0.9471999941293027}}
 (R/'premusic_lock300_summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=False))
if __name__=='__main__':main()
