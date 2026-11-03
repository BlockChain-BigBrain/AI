"""Retrain the pair verifier with selected premusic train hard negatives only."""
from __future__ import annotations
import json, random
from pathlib import Path
import numpy as np
from evaluate_pairwise_verifier import features, fit, sigmoid

ROOT=Path(__file__).resolve().parents[1]
AI_FILES=[ROOT/'api/runtime/locked_full_v2/results.jsonl',ROOT/'api/runtime/locked_shard_a/results.jsonl',ROOT/'api/runtime/locked_shard_b/results.jsonl']
PREMUSIC=ROOT/'api/runtime/premusic_minimal_results.jsonl'; OUT=ROOT/'api/runtime/pairwise_with_premusic.json'
MINED=ROOT/'api/runtime/premusic_mined_train.jsonl'

def load_ai():
    rows=[]
    for p in AI_FILES: rows += [json.loads(x) for x in p.read_text('utf-8').splitlines()]
    groups=sorted({r['groupId'] for r in rows}); random.Random(20261101).shuffle(groups); split={g:'tune' if i<round(.6*len(groups)) else 'test' for i,g in enumerate(groups)}
    for r in rows:r['evalSplit']=split[r['groupId']]
    return rows

def load_premusic(): return [json.loads(x) for x in PREMUSIC.read_text('utf-8').splitlines()]
def pairs(row,label): return [(features(c),label) for c in row['top3']]
def score_rows(rows,model):
    return [{**r,'score':max(float(sigmoid(((features(c)-model[0])/model[1])@model[2]+model[3])) for c in r['top3'])} for r in rows]
def metrics(rows,threshold):
    p=[r for r in rows if r['label']=='positive'];n=[r for r in rows if r['label']=='safe']
    return {'positiveRecall':sum(r['score']>=threshold for r in p)/len(p) if p else None,'safeFalsePositiveRate':sum(r['score']>=threshold for r in n)/len(n) if n else None,'positiveCount':len(p),'safeCount':len(n)}

def main():
    ai=load_ai(); prem=load_premusic()
    mined=[]
    if MINED.exists():
        for line in MINED.read_text('utf-8').splitlines():
            row=json.loads(line)
            if row.get('decision') in ('WARN','HOLD'):
                mined.append(row)
    ai_tune=[r for r in ai if r['evalSplit']=='tune'];ai_test=[r for r in ai if r['evalSplit']=='test']
    def normalize_p(rows,split):
        return [{'top3':r['top3'],'label':'safe','split':split,'selectionSplit':r['selectionSplit']} for r in rows]
    prem_tune=normalize_p([r for r in prem if r['selectionSplit']=='train'],'validation')
    prem_val=normalize_p([r for r in prem if r['selectionSplit']=='validation'],'validation')
    prem_test=normalize_p([r for r in prem if r['selectionSplit']=='test'],'test')
    train_pairs=[]
    for r in ai_tune:
        for c in r['top3']: train_pairs.append((features(c),int(r['dataset']=='positive' and c['trackId']==r['expectedTrackId'])))
    for r in prem_tune:
        for c in r['top3']: train_pairs.append((features(c),0))
    # Add only observed false-alarm candidates; PASS controls remain audit-only.
    for r in mined:
        for c in r['similarTracks']: train_pairs.append((features(c),0))
    x=np.stack([v for v,_ in train_pairs]);y=np.asarray([l for _,l in train_pairs]);model=fit(x,y)
    def label_ai(r):
        # Keep the verifier's binary semantics independent of the source
        # report's dataset naming (safe_music is the negative class).
        return {'top3':r['top3'],'label':('positive' if r['dataset']=='positive' else 'safe'),'split':r['evalSplit']}
    validation=[label_ai(r) for r in ai_tune if r['dataset'] in ('positive','safe_music')]+prem_val
    test=[label_ai(r) for r in ai_test if r['dataset'] in ('positive','safe_music')]+prem_test
    validation=score_rows(validation,model);test=score_rows(test,model)
    vp=[r['score'] for r in validation if r['label']=='positive'];vs=[r['score'] for r in validation if r['label']=='safe'];cand=sorted(set(vp+vs))
    warn=max(t for t in cand if sum(x>=t for x in vp)/len(vp)>=.9)
    hold=min(t for t in cand if sum(x>=t for x in vs)/len(vs)<=.05)
    report={'training':{'aiTunePairs':len(ai_tune)*3,'premusicTrainQueries':len(prem_tune),'premusicTrainPairs':len(prem_tune)*3,'minedHardNegativeQueries':len(mined),'minedHardNegativePairs':len(mined)*3},'validation':metrics(validation,warn),'validationHold':metrics(validation,hold),'test':metrics(test,warn),'testHold':metrics(test,hold),'thresholds':{'warn':warn,'hold':hold},'model':{'mean':model[0].tolist(),'std':model[1].tolist(),'weights':model[2].tolist(),'bias':float(model[3])},'note':'Premusic train and mined WARN/HOLD controls affect fitting; premusic validation/test are evaluation-only.'}
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
