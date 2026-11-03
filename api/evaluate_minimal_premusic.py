"""Evaluate only the minimal selected non-duplicate premusic controls."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from engine import Engine

ROOT=Path(__file__).resolve().parents[1]
SELECTION=ROOT/'api/runtime/premusic_minimal_selection.json'
OUT=ROOT/'api/runtime/premusic_minimal_results.jsonl'
SUMMARY=ROOT/'api/runtime/premusic_minimal_summary.json'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    selected=json.loads(SELECTION.read_text('utf-8'))['selected']
    done={}
    if OUT.exists():
        for line in OUT.read_text('utf-8').splitlines():
            row=json.loads(line);done[row['sha256']]=row
    engine=Engine()
    for i,row in enumerate(selected,1):
        path=Path(row['path']); digest=sha(path)
        if digest in done: continue
        started=time.perf_counter(); result=engine.verify(path,digest)
        item={'sha256':digest,'path':str(path),'selectionSplit':row['selectionSplit'],'useFor':row['useFor'],'decision':result['decision'],'score':result['similarityScore'],'top3':result['similarTracks'],'processingSeconds':round(time.perf_counter()-started,3)}
        with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
        done[digest]=item;print(f'{i}/{len(selected)} {row["selectionSplit"]} {item["decision"]} {path.name}',flush=True)
    results=list(done.values())
    summary={'rows':len(results),'counts':{s:sum(r['selectionSplit']==s for r in results) for s in ('train','validation','test')},'decisions':{s:{d:sum(r['selectionSplit']==s and r['decision']==d for r in results) for d in ('PASS','WARN','HOLD','BLOCK')} for s in ('train','validation','test')},'featureEvidenceComplete':all(all('featureEvidence' in c and 'verifierScore' in c for c in r['top3']) for r in results),'scoreVersion':engine.score_version,'thresholds':engine.thresholds}
    SUMMARY.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
