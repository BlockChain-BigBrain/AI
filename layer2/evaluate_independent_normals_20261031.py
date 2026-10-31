"""Evaluate 29 held-out normal works with frozen production thresholds."""
from __future__ import annotations
import hashlib, json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path
from scipy.stats import beta

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'; OUT=ROOT/'.runtime-tests/independent-normal-20261031'
SELECT=OUT/'selection.json'; CHECK=OUT/'results.jsonl'; REPORT=ART/'independent_normal_evaluation_20261031.json'

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(4*1024*1024),b''): h.update(c)
    return h.hexdigest()

def prior_names():
    names=set()
    # Exclude works that were already used in normal tuning or testing. Broad
    # inventory/audit reports are intentionally ignored because they list the
    # whole corpus rather than evaluated samples.
    prior_roots=[ROOT/'layer2/test_data/duration_matched_normal_20261024',ROOT/'layer2/test_data/fresh_audit']
    for p in [q for root in prior_roots if root.exists() for q in root.rglob('*')]:
        if p.is_file() and p.suffix.lower() in {'.json','.jsonl','.csv'}:
            try: text=p.read_text(encoding='utf-8',errors='ignore')
            except: continue
            names.update(re.findall(r'[A-Za-z0-9_()\- ]+\.mp3',text))
    return names

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if SELECT.exists(): frozen=json.loads(SELECT.read_text(encoding='utf-8'))
    else:
        excluded=prior_names()
        candidates=sorted([p for p in (ROOT/'music').glob('*.mp3') if p.name not in excluded], key=lambda p:hashlib.sha256(p.name.encode()).hexdigest())
        if len(candidates)<29: raise RuntimeError(f'Only {len(candidates)} independent candidates')
        rows=[{'name':p.name,'path':str(p),'sha256':digest(p)} for p in candidates[:29]]
        frozen={'date':'2026-10-31','policy_sha256':digest(ART/'ai_precision_policy.json'),'count':29,'rows':rows,'exclusion':'All mp3 names found in prior test_data and artifact reports'}
        SELECT.write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT))
    from api.engine import Engine
    import evaluate_retrieval_baseline as base
    ffmpeg=base.find_ffmpeg(); engine=Engine('ai_labeled')
    done={}
    if CHECK.exists():
        for line in CHECK.read_text(encoding='utf-8').splitlines():
            r=json.loads(line); done[(r['sha256'],r['kind'])]=r
    with CHECK.open('a',encoding='utf-8') as log:
        for i,item in enumerate(frozen['rows'],1):
            src=Path(item['path'])
            for kind,offset in [('full',None),('start30',0),('middle30',30),('end30',60)]:
                key=(item['sha256'],kind)
                if key in done: continue
                q=src
                if offset is not None:
                    q=OUT/f"{i:03d}_{kind}.wav"
                    subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(src),'-t','30','-ac','1','-ar','22050',str(q)],check=True,capture_output=True)
                result=engine.verify(q,item['sha256'])
                row={'name':item['name'],'sha256':item['sha256'],'kind':kind,'decision':result['decision'],'score':result.get('similarityScore'),'match':result.get('similarTracks',[])[:3]}
                done[key]=row; log.write(json.dumps(row,ensure_ascii=False)+'\n'); log.flush(); print(f'[{i}/29 {kind}] {row["decision"]}',flush=True)
    by=defaultdict(dict)
    for r in done.values(): by[r['sha256']][r['kind']]=r
    def warn(r): return r['decision'] in {'WARN','HOLD','BLOCK'}
    works=[]
    for item in frozen['rows']:
        rows=by[item['sha256']]; works.append({'name':item['name'],'full':rows['full'],'positions':{k:rows[k] for k in ('start30','middle30','end30')}})
    union=[w for w in works if any(w['positions'][k]['decision'] in {'WARN','HOLD','BLOCK'} for k in w['positions'])]
    full=[w for w in works if warn(w['full'])]
    pos={k:[w for w in works if warn(w['positions'][k])] for k in ('start30','middle30','end30')}
    def upper(n,k): return float(beta.ppf(.95,n+1,k-n)) if k and n<k else (1.0 if k else None)
    report={'status':'completed','date':'2026-10-31','works':len(works),'queries':len(done),'thresholds':engine.thresholds,'policy_sha256':digest(ART/'ai_precision_policy.json'),'independent_selection':True,'full':{'warnings':len(full),'warn_rate':len(full)/len(works),'one_sided_95_upper':upper(len(full),len(works))},'positions':{k:{'warnings':len(v),'warn_rate':len(v)/len(works),'warning_names':[x['name'] for x in v]} for k,v in pos.items()},'three_30s_union':{'warnings':len(union),'warn_rate':len(union)/len(works),'one_sided_95_upper':upper(len(union),len(works)),'warning_names':[x['name'] for x in union]},'rows':works}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({k:report[k] for k in ('works','queries','full','positions','three_30s_union')},ensure_ascii=False))
if __name__=='__main__': main()
