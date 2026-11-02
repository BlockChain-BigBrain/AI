"""Select only the premusic controls needed for the next evaluation."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'api/runtime/premusic_remaining_split.json'
OUT=ROOT/'api/runtime/premusic_minimal_selection.json'

def order(row):
    return hashlib.sha256(row['name'].encode('utf-8')).hexdigest()

def main():
    rows=json.loads(SOURCE.read_text('utf-8'))['rows']
    chosen=[]
    for split, count in (('train',12),('validation',8),('test',10)):
        candidates=sorted((r for r in rows if r['split']==split), key=order)
        chosen.extend({**r,'useFor': 'hard_negative_training' if split=='train' else 'threshold_validation' if split=='validation' else 'final_normal_control', 'selectionSplit':split} for r in candidates[:count])
    output={'method':'deterministic minimal non-duplicate premusic selection','counts':{s:sum(r['selectionSplit']==s for r in chosen) for s in ('train','validation','test')},'selected':chosen,'unusedRemaining':len(rows)-len(chosen),'note':'All selected rows came from the exact-deduplicated premusic pool; unused files remain in premusic_used.'}
    OUT.write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'counts':output['counts'],'unusedRemaining':output['unusedRemaining']},ensure_ascii=False))
if __name__=='__main__':main()
