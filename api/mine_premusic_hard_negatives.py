"""Resumable premusic hard-negative mining using the deployed Engine."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from engine import Engine

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['train','validation','test'],required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--output',type=Path,default=ROOT/'api/runtime/premusic_hard_negatives.jsonl');a=p.parse_args()
    rows=json.loads((ROOT/'api/runtime/premusic_remaining_split.json').read_text('utf-8'))['rows']; rows=[r for r in rows if r['split']==a.split]; rows=rows[:a.limit] if a.limit else rows
    done={}
    if a.output.exists():
        for line in a.output.read_text('utf-8').splitlines():
            item=json.loads(line);done[item['sha256']]=item
    engine=Engine();a.output.parent.mkdir(parents=True,exist_ok=True)
    for i,row in enumerate(rows,1):
        path=Path(row['path']); sha=digest(path)
        if sha in done: continue
        result=engine.verify(path,sha)
        item={'sha256':sha,'path':str(path),'split':a.split,'decision':result['decision'],'similarityScore':result['similarityScore'],'similarTracks':result['similarTracks']}
        with a.output.open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
        print(f'{i}/{len(rows)} {result["decision"]} {path.name}',flush=True)
if __name__=='__main__':main()
