"""Evaluate query-level WARN plus locked pairwise HOLD on untouched test groups."""
import json, random
from pathlib import Path
import joblib
import numpy as np
from evaluate_pairwise_verifier import features, sigmoid
from evaluate_query_level_verifier import vector

ROOT=Path(__file__).resolve().parents[1];R=ROOT/'api/runtime'
def read(p):return [json.loads(x) for x in p.read_text('utf-8').splitlines()]
def main():
    rows=sum((read(R/p/'results.jsonl') for p in ('locked_full_v2','locked_shard_a','locked_shard_b')),[])
    g=sorted({r['groupId'] for r in rows});random.Random(20261102).shuffle(g);a,b=round(.5*len(g)),round(.75*len(g));sp={x:'train' if i<a else 'validation' if i<b else 'test' for i,x in enumerate(g)}
    mini=read(R/'premusic_minimal_results.jsonl');qm=joblib.load(R/'query_level_verifier.joblib')
    if hasattr(qm,'n_jobs'): qm.n_jobs=1
    qr=json.loads((R/'query_level_verifier_evaluation.json').read_text('utf-8'));selected=qr['models'][qr['selectedModel']];qt=selected.get('balancedWarnThreshold',selected['warnThreshold'])
    pr=json.loads((R/'pairwise_with_premusic.json').read_text('utf-8'));base=json.loads((R/'pairwise_verifier_evaluation.json').read_text('utf-8'));mean=np.array(pr['model']['mean']);std=np.array(pr['model']['std']);w=np.array(pr['model']['weights']);bias=pr['model']['bias'];ht=base['precisionOperatingPoint']['threshold']
    def pair(r):return max(float(sigmoid(((features(c)-mean)/std)@w+bias)) for c in r['top3'])
    def query(r):return float(qm.predict_proba(vector(r).reshape(1,-1))[0,1])
    test=[(r,int(r['dataset']=='positive'),'ai') for r in rows if sp[r['groupId']]=='test']+[(r,0,'premusic') for r in mini if r['selectionSplit']=='test']
    report={'warnThreshold':qt,'holdThreshold':ht,'parts':{}}
    for source in ('all','ai','premusic'):
        z=[x for x in test if source=='all' or x[2]==source];y=np.array([x[1] for x in z]);q=np.array([query(x[0]) for x in z]);p=np.array([pair(x[0]) for x in z]);det=(q>=qt)|(p>=ht);hold=p>=ht;pos=y==1;neg=y==0
        report['parts'][source]={'count':len(z),'positiveRecall':float(det[pos].mean()) if pos.any() else None,'safeFalsePositiveRate':float(det[neg].mean()) if neg.any() else None,'holdPositiveRecall':float(hold[pos].mean()) if pos.any() else None,'holdSafeFalsePositiveRate':float(hold[neg].mean()) if neg.any() else None,'warnCount':int((det&~hold).sum()),'holdCount':int(hold.sum())}
    errors=[]
    for row,label,source in test:
        q,p=query(row),pair(row);det=q>=qt or p>=ht
        if (label==1 and not det) or (label==0 and det):
            errors.append({'kind':'missed_positive' if label else 'safe_false_positive','source':source,
                           'file':Path(row.get('file',row.get('path','unknown'))).name,
                           'queryKind':row.get('queryKind'),'queryScore':q,'pairScore':p,
                           'decision':'HOLD' if p>=ht else 'WARN' if q>=qt else 'PASS'})
    report['errors']=errors
    (R/'hybrid_policy_evaluation.json').write_text(json.dumps(report,indent=2),'utf-8');print(json.dumps(report))
if __name__=='__main__':main()
