"""Prepare fixed 30-second position queries and memory-bounded caches."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]; RUN=ROOT/'.runtime-tests/premusic-20261101-location'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(4*1024*1024),b''):h.update(c)
    return h.hexdigest()
def main():
    split=json.loads((ROOT/'layer2/artifacts/premusic_evaluation_split_20261101.json').read_text(encoding='utf-8'))
    selected=split['threshold_calibration']+split['final_evaluation']; RUN.mkdir(parents=True,exist_ok=True); qdir=RUN/'queries'; cache=RUN/'window_cache'; qdir.mkdir(exist_ok=True); cache.mkdir(exist_ok=True)
    (RUN/'selection.json').write_text(json.dumps({'date':'2026-11-01','selected':selected,'count':len(selected)},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'layer2')); import evaluate_retrieval_baseline as base
    ff=base.find_ffmpeg(); base.FFMPEG_EXE=ff; queries=[]
    for i,item in enumerate(selected):
        src=Path(item['path']); duration=base.get_duration_seconds(src)
        positions=[('start30',0.0),('middle30',max(0.0,(duration-30.0)/2)),('end30',max(0.0,duration-30.0))]
        for kind,off in positions:
            target=qdir/f'{i:04d}_{kind}.wav'
            regenerate=not target.exists()
            if not regenerate:
                try: regenerate=base.get_duration_seconds(target)<29.9
                except Exception: regenerate=True
            if regenerate:
                cmd=[ff,'-v','error','-nostdin','-y']
                if duration<30: cmd+=['-stream_loop','-1']
                cmd+=['-ss',str(off),'-i',str(src),'-t','30','-ac','1','-ar','22050',str(target)]
                subprocess.run(cmd,check=True,capture_output=True)
            qsha=sha(target); cpath=cache/(qsha+'.v3.npz')
            if not cpath.exists():
                audio,offsets=base.extract_windows(target,False,query_window_count=3,all_query_windows=False); np.savez(cpath,audio=audio,offsets=np.asarray(offsets,dtype=np.float32))
            queries.append({'work_id':item['sha256'],'name':item['name'],'kind':kind,'file':str(target),'sha256':qsha,'partition':item['partition']})
        if (i+1)%25==0:print(f'[prepare {i+1}/{len(selected)}]',flush=True)
    plan={'date':'2026-11-01','query_count':len(queries),'works':len(selected),'queries':queries}; (RUN/'query_plan_all.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'works':len(selected),'queries':len(queries)},ensure_ascii=False))
if __name__=='__main__':main()
