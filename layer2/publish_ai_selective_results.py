"""Finalize the human-readable report and machine-readable current status."""
from pathlib import Path
import hashlib
import json
import csv

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def read(name):return json.loads((ART/name).read_text(encoding='utf-8'))


def main():
    if (ART/'ai_precision_policy.json').exists():
        raise SystemExit('A newer secondary precision policy is active; use publish_mentoring_completion.py.')
    policy=read('ai_improvement_policy.json')
    selected=read('ai_selective_retrieval_evaluation.json')['profiles']['ai_labeled_catalog']
    replication=read('ai_selective_replication_summary.json')['profiles']['ai_labeled_catalog']
    live,team,local=[read(name) for name in ('ai_scope_live_validation.json','team_live_ai_e2e_validation.json','local_stack_validation.json')]
    assert live['status']==team['status']==local['status']=='passed'
    assert live['policy_file']==team['active_policy_file']=='ai_improvement_policy.json'
    thresholds={'warn':policy['warn_threshold'],'hold':policy['hold_threshold']}
    assert live['thresholds']==team['thresholds']==local['thresholds']==thresholds
    assert all(abs(team['persisted_thresholds'][k]-thresholds[k])<=1e-12 for k in thresholds)
    expected='clap-top20+tonal-local-v1+expanded-square-v1'
    assert live['score_version']==team['ai_score_version']==local['score_version']==expected
    excluded=set(read('ai_near_duplicate_audit.json')['excluded_normal_filenames'])
    cases=[]
    for checkpoint,stage in [('ai_selective_retrieval_checkpoint.jsonl','original_test_and_first_stress'),
                              ('ai_selective_replication_checkpoint.jsonl','new_transform_replication')]:
        unique={}
        for line in (ART/checkpoint).read_text(encoding='utf-8').splitlines():
            row=json.loads(line);unique[(row['scope'],row['file'])]=row
        for row in unique.values():
            scoring=row['selected'] if stage=='new_transform_replication' else row
            profile=read('ai_selective_retrieval_evaluation.json')['profiles'][row['scope']]
            source_ok=(scoring['expected_score'] is not None and scoring['expected_score']>=profile['warn_threshold']
                       and scoring['source_rank_after_tonal']<=3)
            normal=row['dataset']!='positive'
            if (normal and scoring['score']<profile['warn_threshold']) or (not normal and source_ok):continue
            reason=('quarantined_near_identical_recording' if Path(row['file']).name in excluded else 'normal_candidate_warning') if normal else (
                'source_outside_top20' if scoring['expected_score'] is None else 'source_below_warn' if scoring['expected_score']<profile['warn_threshold'] else 'source_outside_display_top3')
            cases.append({'stage':stage,'scope':row['scope'],'split':row['split'],'kind':row['query_kind'],
                'file':row['file'],'expected_track':row['expected_track_id'],'reason':reason,
                'best_track':scoring['candidates'][0]['trackId'],'best_score':scoring['score'],
                'expected_score':scoring['expected_score'],'source_display_rank':scoring['source_rank_after_tonal']})
    if cases:
        with (ART/'ai_improvement_failure_cases.csv').open('w',encoding='utf-8-sig',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=list(cases[0]));writer.writeheader();writer.writerows(cases)
    report=ROOT/'AI_IMPROVEMENT_20261023.md'
    assert '진행 중입니다' not in report.read_text(encoding='utf-8'), 'Finalize report only after actual checks.'
    status={'date':'2026-10-23','status':'completed_local_experimental','active_scope':'ai_labeled','reference_tracks':34,
        'policy_file':'ai_improvement_policy.json','score_version':expected,'thresholds':thresholds,
        'test_raw':selected['test_raw'],'test_audited':selected['test_audited'],
        'round1_stress':selected['round1_stress'],'replication':replication['selected']['all'],
        'production_readiness':False,
        'remaining':['Fresh independent AI normal and source validation','Pure AI creation provenance','Scale-up dual retrieval validation'],
        'report':report.name,'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest()}
    (ART/'ai_improvement_completion_status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    old=read('ai_scope_completion_status.json')
    old.update(updated_date='2026-10-23',latest_report=report.name,latest_policy='ai_improvement_policy.json',
        thresholds=thresholds,test=selected['test_audited'],test_raw=selected['test_raw'],production_readiness=False)
    (ART/'ai_scope_completion_status.json').write_text(json.dumps(old,indent=2),encoding='utf-8')
    print('Current selective-retrieval report and status finalized.')


if __name__=='__main__':main()
