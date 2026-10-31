"""Activate only the accepted, hash-bound local AI supplementary policy."""
from pathlib import Path
import hashlib,json
import librosa

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    primary=json.loads((ART/'ai_improvement_policy.json').read_text(encoding='utf-8'))
    report=json.loads((ART/'secondary_precision_evaluation.json').read_text(encoding='utf-8'))
    assert report['protocol']['primary_policy_sha256']==sha(ART/'ai_improvement_policy.json')
    for split in ('tune','test'):
        m=report['summary'][split]
        assert m['normal_warn_rate']<=.10 and m['normal_hold_rate']<=.02
        assert m['correct_source_warn_top3_recall']==1.
    assert report['summary']['new_transform_stress']['correct_source_warn_top3_count']>=26
    assert report['summary']['new_replication']['correct_source_warn_top3_count']>=27
    assert report['summary']['prospective_five_family']['correct_source_warn_top3_recall']>=.90
    policy={**primary,'secondary_precision_rule':'secondary-clap-cqt-fragments-v1',
        'secondary_warn_threshold':report['secondary_warn_threshold'],'librosa_version':librosa.__version__,
        'primary_policy_sha256':sha(ART/'ai_improvement_policy.json'),
        'secondary_evaluation_sha256':sha(ART/'secondary_precision_evaluation.json'),
        'five_family_evaluation_sha256':sha(ART/'five_family_ai_evaluation.json'),
        'secondary_implementation_sha256':sha(ROOT/'layer2/secondary_precision.py'),
        'precision_features_implementation_sha256':sha(ROOT/'layer2/precision_chroma.py'),
        'fragment_implementation_sha256':sha(ROOT/'layer2/fragment_confirmation.py'),
        'tune':report['summary']['tune'],'test':report['summary']['test'],
        'test_audited':report['summary']['test'],'test_raw':report['raw_test'],
        'five_family':report['summary']['prospective_five_family'],'by_family':report['summary']['by_family'],
        'validation_status':report['protocol']['limits'],'production_readiness':False,'enabled':True}
    (ART/'ai_precision_policy.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    operating=json.loads((ART/'layer2_operating_policy.json').read_text(encoding='utf-8'))
    operating.update(current_evidence='ai_precision_policy.json',latest_report='MENTORING_FINAL_STATUS_20261023.md',
        risk_score={'score_name':'clap-top20+tonal-local-v1+expanded-square-v1+secondary-clap-cqt-fragments-v1',
                    'warn_threshold_inclusive':primary['warn_threshold'],'hold_threshold_inclusive':primary['hold_threshold'],
                    'secondary_raw_evidence_threshold':policy['secondary_warn_threshold']},
        five_family_metrics=policy['five_family'],by_family=policy['by_family'],validation_status=policy['validation_status'])
    (ART/'layer2_operating_policy.json').write_text(json.dumps(operating,indent=2),encoding='utf-8')
    print('Supplemental precision policy activated for local 34-track AI-labelled scope.')


if __name__=='__main__':main()
