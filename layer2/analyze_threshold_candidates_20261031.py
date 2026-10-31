"""Compute threshold candidates on tuning data only; never edits policy."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'

def work_max(rows):
    grouped=defaultdict(list)
    for r in rows: grouped[r.get('group_id',r['file'])].append(float(r['score']))
    return {k:max(v) for k,v in grouped.items()}

def main():
    rows=[json.loads(x) for x in (ART/'duration_fusion_checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
    tune_norm=work_max([r for r in rows if r['dataset']=='safe_music' and r['split']=='tune'])
    tune_pos=work_max([r for r in rows if r['dataset']=='positive' and r['split'] in {'tune','prospective_five_family'}])
    test_pos=work_max([r for r in rows if r['dataset']=='positive' and r['split'] in {'test','new_transform_stress','new_replication'}])
    current=json.loads((ART/'ai_precision_policy.json').read_text(encoding='utf-8'))
    warn=float(current['warn_threshold']); hold=float(current['hold_threshold'])
    candidates=sorted({warn,hold,*tune_norm.values(),*tune_pos.values()})
    evaluated=[]
    for t in candidates:
        fp=sum(v>=t for v in tune_norm.values())/len(tune_norm)
        rec=sum(v>=t for v in tune_pos.values())/len(tune_pos)
        if rec>=.90:
            evaluated.append({'warn_candidate':t,'tune_normal_warn_rate':fp,'tune_positive_recall':rec})
    chosen=min(evaluated,key=lambda r:(r['tune_normal_warn_rate'],r['warn_candidate'])) if evaluated else None
    report={'date':'2026-10-31','production_policy_changed':False,'source':'duration_fusion_checkpoint.jsonl','selection':'tune rows only for candidate selection; test rows are report-only','current':{'warn':warn,'hold':hold},'tune_counts':{'normal_works':len(tune_norm),'positive_works':len(tune_pos)},'candidate_count':len(evaluated),'best_tune_candidate':chosen,'candidates':evaluated,'hold_candidates_unchanged':True,'test_positive_recall_at_best_candidate':(sum(v>=chosen['warn_candidate'] for v in test_pos.values())/len(test_pos) if chosen and test_pos else None),'independent_normal_29_not_used_for_selection':True}
    (ART/'threshold_candidates_20261031.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({k:report[k] for k in ('current','tune_counts','best_tune_candidate','test_positive_recall_at_best_candidate')},ensure_ascii=False))
if __name__=='__main__': main()
