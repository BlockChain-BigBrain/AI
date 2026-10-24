"""Activate the tested AI-only policy; never apply mixed-catalog diagnostics."""
from pathlib import Path
import hashlib
import json
import compare_ai_improvements as experiment

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (ART/'ai_precision_policy.json').exists():
        raise SystemExit('A newer secondary precision policy is active. Preserve this historical primary policy.')
    old=experiment.read(ART/'ai_labeled_recalibration.json')
    comparison=experiment.read(ART/'ai_selective_retrieval_evaluation.json')
    stress=experiment.read(ART/'ai_selective_replication_summary.json')
    assert comparison['original_policy_sha256']==sha(ART/'ai_labeled_recalibration.json')
    assert stress['comparison_sha256']==sha(ART/'ai_selective_retrieval_evaluation.json')
    selected=comparison['profiles']['ai_labeled_catalog'];method=selected['method']
    assert method=='selective_top20' and selected['candidate_score_rule']=='expanded-square-v1'
    for split in ('tune','test_audited'):
        m=selected[split]
        assert m['normal_warn_rate']<=.10 and m['normal_hold_rate']<=.02
        assert m['correct_source_warn_top3_recall']>=.90
    assert stress['profiles']['ai_labeled_catalog']['selected']['all']['correct_source_warn_top3_recall']>=.90, 'New stress recall misses the predeclared 90% target.'
    assert selected['round1_stress']['correct_source_warn_top3_recall']>=.90
    original=old['profiles']['ai_labeled_catalog']
    policy={**original,'warn_threshold':selected['warn_threshold'],'hold_threshold':selected['hold_threshold'],
        'method':method,'retrieval_top_k':20,'candidate_score_rule':selected['candidate_score_rule'],
        'threshold_selection':comparison['protocol']['warn_rule'],
        'validation_status':comparison['protocol']['selection_status'],
        'original_policy_sha256':sha(ART/'ai_labeled_recalibration.json'),
        'comparison_sha256':sha(ART/'ai_improvement_comparison.json'),
        'stress_sha256':sha(ART/'ai_improvement_stress_summary.json'),
        'selective_evaluation_sha256':sha(ART/'ai_selective_retrieval_evaluation.json'),
        'replication_sha256':sha(ART/'ai_selective_replication_summary.json'),
        'scoring_implementation_sha256':sha(ROOT/'layer2/selective_retrieval.py'),
        'near_duplicate_audit_sha256':sha(ART/'ai_near_duplicate_audit.json'),
        'provenance_sha256':old['provenance_sha256'],'manifest_sha256':old['manifest_sha256'],
        'tune':selected['tune'],'test_raw':selected['test_raw'],'test_audited':selected['test_audited'],
        'test':selected['test_audited'],'premusic_diagnostic':selected['premusic_diagnostic'],
        'new_transform_stress':stress['profiles']['ai_labeled_catalog']['selected'],
        'round1_stress':selected['round1_stress'],
        'production_readiness':False,'enabled':True}
    (ART/'ai_improvement_policy.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    operating=experiment.read(ART/'layer2_operating_policy.json')
    operating.update(current_evidence='ai_improvement_policy.json',
        risk_score={'score_name':f'clap-top{policy["retrieval_top_k"]}+tonal-local-v1+expanded-square-v1',
                    'warn_threshold_inclusive':policy['warn_threshold'],'hold_threshold_inclusive':policy['hold_threshold']},
        calibration=policy['threshold_selection'],held_out_metrics=selected['test_audited'],
        held_out_metrics_raw=selected['test_raw'],new_transform_stress=policy['new_transform_stress'],
        validation_status=policy['validation_status'],latest_report='AI_IMPROVEMENT_20261023.md')
    operating['candidate_retrieval']['internal_top_k']=policy['retrieval_top_k']
    (ART/'layer2_operating_policy.json').write_text(json.dumps(operating,indent=2),encoding='utf-8')
    print(json.dumps({'status':'activated_local_experimental','method':method,'warn':policy['warn_threshold'],'hold':policy['hold_threshold']},indent=2))


if __name__=='__main__':main()
