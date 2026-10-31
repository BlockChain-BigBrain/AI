"""Freeze calibration and final-evaluation partitions for the 2026-10-31 intake."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    report=json.loads((ROOT/'layer2/artifacts/premusic_intake_20261031.json').read_text(encoding='utf-8'))
    rows=[{'name':x['name'],'sha256':x['sha256'],'path':str(Path(report['archive'])/x['name'])} for x in report['unique_new']]
    rows.sort(key=lambda x:hashlib.sha256(('premusic-split-20261031:'+x['sha256']).encode()).hexdigest())
    n=round(len(rows)*.60); cal=rows[:n]; final=rows[n:]
    for x in cal:x['partition']='threshold_calibration'
    for x in final:x['partition']='final_evaluation'
    out={'date':'2026-10-31','policy':{'production_thresholds_changed':False,'split_method':'sha256 deterministic hash; 60% calibration / 40% final evaluation','final_evaluation_unseen_until_lock':True},'counts':{'unique_new':len(rows),'threshold_calibration':len(cal),'final_evaluation':len(final)},'threshold_calibration':cal,'final_evaluation':final}
    p=ROOT/'layer2/artifacts/premusic_evaluation_split_20261031.json'; p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'counts':out['counts']},ensure_ascii=False))
if __name__=='__main__':main()
