"""Train query-level verifiers using the joint evidence of all top-3 candidates."""
from __future__ import annotations
import json, random
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from evaluate_pairwise_verifier import features

ROOT=Path(__file__).resolve().parents[1]; R=ROOT/'api/runtime'
FILES=[R/'locked_full_v2/results.jsonl',R/'locked_shard_a/results.jsonl',R/'locked_shard_b/results.jsonl']
def read(p):return [json.loads(x) for x in p.read_text('utf-8').splitlines()]

def vector(row):
    z=np.stack(sorted((features(c) for c in row['top3']),key=lambda v:v[0],reverse=True))
    # Candidate identities are irrelevant; their joint evidence, gaps and spread are not.
    gaps=np.concatenate([z[0]-z[1],z[1]-z[2]])
    return np.concatenate([z.ravel(),z.max(0),z.mean(0),z.std(0),gaps])

def threshold(scores,y,recall):
    return max(t for t in sorted(set(scores.tolist())) if np.mean(scores[y==1]>=t)>=recall)
def hold_threshold(scores,y):
    ok=[t for t in sorted(set(scores.tolist())) if np.mean(scores[y==0]>=t)<=.05]
    return min(ok) if ok else max(scores)
def met(s,y,t):return {'positiveRecall':float(np.mean(s[y==1]>=t)),'safeFalsePositiveRate':float(np.mean(s[y==0]>=t)),'positiveCount':int((y==1).sum()),'safeCount':int((y==0).sum())}

def main():
    ai=sum((read(p) for p in FILES),[]);g=sorted({r['groupId'] for r in ai});random.Random(20261102).shuffle(g);a,b=round(.5*len(g)),round(.75*len(g));sp={x:'train' if i<a else 'validation' if i<b else 'test' for i,x in enumerate(g)}
    mini=read(R/'premusic_minimal_results.jsonl');mined=read(R/'premusic_mined_train.jsonl') if (R/'premusic_mined_train.jsonl').exists() else []
    train=[(r,int(r['dataset']=='positive')) for r in ai if sp[r['groupId']]=='train']
    train += [(r,0) for r in mini if r['selectionSplit']=='train']
    train += [({'top3':r['similarTracks']},0) for r in mined if r.get('decision') in ('WARN','HOLD')]
    def evaluation(name):
        q=[(r,int(r['dataset']=='positive')) for r in ai if sp[r['groupId']]==name]
        q += [(r,0) for r in mini if r['selectionSplit']==name]
        return q
    val,test=evaluation('validation'),evaluation('test')
    x=np.stack([vector(r) for r,_ in train]);y=np.array([v for _,v in train])
    vx=np.stack([vector(r) for r,_ in val]);vy=np.array([v for _,v in val]);tx=np.stack([vector(r) for r,_ in test]);ty=np.array([v for _,v in test])
    models={
      'logistic':make_pipeline(StandardScaler(),LogisticRegression(C=.08,class_weight='balanced',max_iter=5000,random_state=20261102)),
      'random_forest':RandomForestClassifier(n_estimators=800,max_depth=5,min_samples_leaf=3,max_features=.45,class_weight='balanced_subsample',n_jobs=-1,random_state=20261102),
      'extra_trees':ExtraTreesClassifier(n_estimators=800,max_depth=6,min_samples_leaf=3,max_features=.45,class_weight='balanced',n_jobs=-1,random_state=20261102),
      'hist_gradient_boosting':HistGradientBoostingClassifier(max_iter=250,learning_rate=.035,max_leaf_nodes=8,min_samples_leaf=8,l2_regularization=2,class_weight='balanced',random_state=20261102)}
    report={}
    for name,m in models.items():
        m.fit(x,y);s=m.predict_proba(vx)[:,1];w=threshold(s,vy,.95);h=hold_threshold(s,vy)
        report[name]={'warnThreshold':float(w),'holdThreshold':float(h),'validationWarn':met(s,vy,w),'validationHold':met(s,vy,h)}
    chosen=min(report,key=lambda n:(report[n]['validationWarn']['safeFalsePositiveRate'],-report[n]['validationHold']['positiveRecall']))
    m=models[chosen];s=m.predict_proba(tx)[:,1]
    selected_val_scores=m.predict_proba(vx)[:,1]
    balanced=threshold(selected_val_scores,vy,1.0)
    report[chosen]['balancedWarnThreshold']=float(balanced)
    report[chosen]['validationBalanced']=met(selected_val_scores,vy,balanced)
    report[chosen]['testBalanced']=met(s,ty,balanced)
    report[chosen]['testWarn']=met(s,ty,report[chosen]['warnThreshold']);report[chosen]['testHold']=met(s,ty,report[chosen]['holdThreshold'])
    out={'protocol':'query-level top3 joint evidence; grouped 50/25/25; validation selection at >=95% recall','selectedModel':chosen,'featureCount':int(x.shape[1]),'trainQueries':len(train),'models':report}
    (R/'query_level_verifier_evaluation.json').write_text(json.dumps(out,indent=2),encoding='utf-8');joblib.dump(m,R/'query_level_verifier.joblib');print(json.dumps(out))
if __name__=='__main__':main()
