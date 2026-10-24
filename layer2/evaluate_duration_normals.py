"""Run the actual active engine on known-work, duration-matched negatives.

The three crops of a work are correlated views, never three independent works.
"""
from pathlib import Path
import hashlib,json,sys
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.engine import Engine

ART=ROOT/'layer2/artifacts'


def main():
    threadpool_limits(limits=4)
    manifest=ROOT/'layer2/test_data/duration_matched_normal_20261024/manifest.json'
    policy=ART/'ai_precision_policy.json'
    signature=hashlib.sha256(manifest.read_bytes()+policy.read_bytes()).hexdigest()
    checkpoint=ART/'duration_normal_checkpoint.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row['signature']==signature:done[row['file']]=row
    engine=Engine('ai_labeled');results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,row in enumerate(json.loads(manifest.read_text())['rows'],1):
            if row['file'] in done:results.append(done[row['file']]);continue
            path=Path(row['file']);result=engine.verify(path,hashlib.sha256(path.read_bytes()).hexdigest())
            saved={**row,'signature':signature,'decision':result['decision'],'score':result['similarityScore'],
                   'scoreVersion':result['scoreVersion'],'candidates':result['similarTracks']}
            results.append(saved);log.write(json.dumps(saved)+'\n');log.flush()
            print(f'[actual duration normals {n}/93] {saved["decision"]}',flush=True)
    thresholds=engine.thresholds;summary={}
    for split in sorted({r['split'] for r in results}):
        part=[r for r in results if r['split']==split];works={}
        for row in part:works.setdefault(row['group_id'],[]).append(row)
        summary[split]={'queries':len(part),'works':len(works),
            'warn_works':sum(any(r['decision'] in ('WARN','HOLD','BLOCK') for r in rows) for rows in works.values()),
            'hold_works':sum(any(r['decision'] in ('HOLD','BLOCK') for r in rows) for rows in works.values()),
            'block_queries':sum(r['decision']=='BLOCK' for r in part)}
        for level in ('warn','hold'):summary[split][level+'_rate']=summary[split][level+'_works']/len(works)
    previous=[json.loads(s) for s in (ART/'secondary_precision_checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
    excluded={r['normal'] for r in json.loads((ART/'ai_near_duplicate_audit.json').read_text())['pairs'] if r['quarantine_normal_label']}
    all_view_summary={}
    for split in sorted(summary):
        works={}
        for r in previous+results:
            if r['dataset']=='positive' or r['split']!=split or r['file'] in excluded:continue
            group=r.get('group_id','normal:'+Path(r['file']).stem)
            works[group]=max(works.get(group,0),r['score'])
        all_view_summary[split]={'normal_works':len(works),'warn_works':sum(s>=thresholds['warn'] for s in works.values()),'hold_works':sum(s>=thresholds['hold'] for s in works.values())}
    report={'status':'passed','meaning':'Execution completed; not a statement that false-positive targets passed.',
        'scope':'ai_labeled','reference_tracks':34,'queries':len(results),'works':len({r['group_id'] for r in results}),
        'policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest(),'thresholds':thresholds,
        'normal_unit':'A work warns if any of its three 30s crops warns; existing known works, not independent new validation.',
        'summary':summary,'full_and_crop_work_summary':all_view_summary,'failures':[r for r in results if r['decision']!='PASS']}
    (ART/'duration_normal_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='failures'},indent=2))


if __name__=='__main__':main()
