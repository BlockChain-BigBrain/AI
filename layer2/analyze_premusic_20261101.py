"""Summarize the frozen 2026-11-01 intake without refitting on final evaluation."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from scipy.stats import beta
ROOT=Path(__file__).resolve().parents[1]
WARN={'WARN','HOLD','BLOCK'}
def upper(e,n): return float(beta.ppf(.95,e+1,n-e)) if e<n else 1.0
def main():
    intake=json.loads((ROOT/'layer2/artifacts/premusic_intake_20261101.json').read_text(encoding='utf-8'))
    split=json.loads((ROOT/'layer2/artifacts/premusic_evaluation_split_20261101.json').read_text(encoding='utf-8'))
    raw=json.loads((ROOT/'layer2/artifacts/premusic_warning_locations_20261101.json').read_text(encoding='utf-8'))
    part={x['sha256']:x['partition'] for x in split['threshold_calibration']+split['final_evaluation']}; by=defaultdict(dict)
    for r in raw['results']: by[r['work_id']][r['kind']]=r
    def stats(ds,threshold=None):
        out={'works':len(ds),'positions':{}}
        for k in ('start30','middle30','end30'):
            e=sum((d[k]['score']>=threshold) if threshold is not None else (d[k]['decision'] in WARN) for d in ds); out['positions'][k]={'warnings':e,'rate':e/len(ds),'one_sided_95_upper':upper(e,len(ds))}
        for n in (1,2,3):
            e=sum(sum((v['score']>=threshold) if threshold is not None else (v['decision'] in WARN) for v in d.values())>=n for d in ds); out[f'at_least_{n}_of_3']={'warnings':e,'rate':e/len(ds),'one_sided_95_upper':upper(e,len(ds))}
        out['hold_or_block_works']=sum(any(v['decision'] in {'HOLD','BLOCK'} for v in d.values()) for d in ds); return out
    cal=[d for w,d in by.items() if part[w]=='threshold_calibration']; final=[d for w,d in by.items() if part[w]=='final_evaluation']
    values=sorted({v['score'] for d in cal for v in d.values()}); candidate=None
    for t in values:
        x=stats(cal,t)['at_least_2_of_3']
        if x['one_sided_95_upper']<=.10: candidate=t; break
    report={'date':'2026-11-01','production_thresholds_changed':False,'intake':{'candidates':intake['candidates_seen'],'exact_duplicates_removed':len(intake['exact_duplicates']),'unique_archived':len(intake['unique_new'])},'current_policy':{'calibration':stats(cal),'locked_final':stats(final)},'tune_only_candidate':{'warn_threshold':candidate,'selection':'minimum calibration-only threshold whose 2-of-3 one-sided 95% WARN upper bound is <=10%','calibration':stats(cal,candidate),'locked_final':stats(final,candidate),'accepted':False,'reason':'Locked-final 2-of-3 WARN point estimate and 95% upper bound exceed 10%; positive recall was not re-established.'},'release_recommendation':'Freeze current AI API and evidence schema; do not change production thresholds. Treat WARN/HOLD as human-review signals and prioritize end-to-end integration.'}
    (ROOT/'layer2/artifacts/premusic_final_analysis_20261101.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
