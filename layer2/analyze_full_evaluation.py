"""Publish fresh calibration evidence and auditable failures after a complete run."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'

def main():
    report=json.loads((ART/'top3_aggregation_evaluation.json').read_text(encoding='utf-8'))
    assert report['corpus']['reference_tracks']==1000
    assert report['protocol'].get('full_synthetic_frozen_clap')
    rows=[r for r in csv.DictReader((ART/'top3_aggregation_details.csv').open(encoding='utf-8-sig')) if r['aggregation']=='seg_top3_centered']
    positive=[r for r in rows if r['dataset']=='positive']
    safe=[r for r in rows if r['dataset']=='safe_music']
    assert len(positive)==340 and len(safe)==300, (len(positive),len(safe),report['skipped_queries'])
    assert not report['skipped_queries'], 'Skipped queries require review before publication'
    model=report['models']['seg_top3_centered']
    thresholds=model['thresholds_from_tune_split']
    warn,hold=thresholds['warn_threshold'],thresholds['hold_threshold']
    assert thresholds['feasible'] and warn is not None and hold is not None and warn<=hold
    failures=[]
    for r in rows:
        if r['dataset'] not in {'positive','safe_music'}:continue
        score=float(r['top_score'])
        issue=[]
        if r['dataset']=='positive':
            rank=int(r['expected_source_rank']) if r['expected_source_rank'] else None
            if rank is None or rank>5:issue.append('source_missing_from_top5')
            if float(r['expected_source_score'])<warn:issue.append('expected_source_below_warn')
            if score<warn:issue.append('positive_query_passed')
        else:
            if score>=hold:issue.append('normal_candidate_hold')
            elif score>=warn:issue.append('normal_candidate_warn')
        if issue:failures.append({**r,'issues':' | '.join(issue)})
    if failures:
        with (ART/'full_failure_analysis.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(failures[0]));w.writeheader();w.writerows(failures)
    hard=sorted(safe,key=lambda r:float(r['top_score']),reverse=True)[:50]
    for r in hard:r['expert_review']='pending; fingerprint-unique normal candidate, not a certified non-plagiarism label'
    with (ART/'production_hard_normal_review_queue.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(hard[0]));w.writeheader();w.writerows(hard)
    stamp=datetime.now(timezone.utc).isoformat()
    policy={'status':'calibrated_experimental','calibrated_at_utc':stamp,
            'score_version':'seg_top3_centered-v1','warn_threshold':warn,'hold_threshold':hold,
            'reference_tracks':1000,'positive_queries':340,'normal_queries':300,
            'threshold_selection':'tune groups only; held-out test never used for fitting',
            'tune':thresholds,'test':model['held_out_test'],
            'evaluation_sha256':hashlib.sha256((ART/'top3_aggregation_evaluation.json').read_bytes()).hexdigest(),
            'legal_plagiarism_probability':False}
    (ART/'calibrated_policy_20261022.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
    test=model['held_out_test']
    old_policy_path=ART/'layer2_operating_policy.json'
    operating=json.loads(old_policy_path.read_text(encoding='utf-8')) if old_policy_path.is_file() else {}
    operating.update(policy_status='calibrated_experimental_not_production_validated', evaluated_at=stamp,
                     corpus_version=report['corpus']['embedding_sha256'])
    operating['risk_score']={**operating.get('risk_score',{}),'score_name':'seg_top3_centered',
                             'hold_threshold_inclusive':hold,'warn_threshold_inclusive':warn}
    operating['candidate_retrieval']={'internal_top_k':5,'display_top_k':3,'positive_queries':340,
                                      'top3_source_recall':test['positive_expected_source_top3_rate'],
                                      'top5_source_recall':test['positive_expected_source_top5_rate'],
                                      'decision_reason':'Existing display policy retained; recalls are from the new held-out source groups.'}
    operating['held_out_metrics']={'positive_queries':test['positive_query_count'],'safe_queries':test['safe_query_count'],
        'hold_positive_recall':test['hold_policy_test']['positive_expected_source_recall'],
        'hold_safe_false_positive_rate':test['hold_policy_test']['safe_query_false_positive_rate'],
        'warn_positive_recall':test['warn_policy_test']['positive_expected_source_recall'],
        'warn_or_hold_safe_false_positive_rate':test['warn_policy_test']['safe_query_false_positive_rate'],
        'seg_top3_centered_source_recall_at_3':test['positive_expected_source_top3_rate'],
        'seg_top3_centered_source_recall_at_5':test['positive_expected_source_top5_rate']}
    operating['limitations']=['Historical CLAP-only baseline. Current tonal-confirmation evidence is in tonal_confirmation_evaluation.json when present.',
                             'Synthetic edits do not establish real plagiarism detection accuracy.',
                             'Normal controls are fingerprint-unique candidates, not expert-certified negative labels.',
                             'Independent cover benchmark uses a separate 80-work corpus; do not combine it with synthetic metrics.',
                             'Team integration tests are reported separately; Google Cloud login requires actual credentials.']
    old_policy_path.write_text(json.dumps(operating,ensure_ascii=False,indent=2),encoding='utf-8')
    pct=lambda x:'—' if x is None else f'{100*x:.2f}%'
    lines=['# 최신 DB 전체 평가 결과','',f'완료 시각(UTC): {stamp}',
           '',f'원본 1,000곡 · 정상후보 300곡 · 합성 양성 340개. 원곡 단위 분리, 10초 창·5초 간격 전체 검사.',
           '',f'WARN **{warn:.6f}**, HOLD **{hold:.6f}**. 튜닝 그룹에서만 선택한 실험용 임계값입니다.',
           '', '| 홀드아웃 지표 | 결과 |','|---|---:|',
           f"| 평가 양성 / 정상 | {test['positive_query_count']} / {test['safe_query_count']} |",
           f"| 원곡 Recall@1 | {pct(test['positive_expected_source_top1_rate'])} |",
           f"| 원곡 Recall@3 | {pct(test['positive_expected_source_top3_rate'])} |",
           f"| 원곡 Recall@5 | {pct(test['positive_expected_source_top5_rate'])} |",
           f"| WARN 이상 원곡 재현율 | {pct(test['warn_policy_test']['positive_expected_source_recall'])} |",
           f"| 정상 WARN 이상 오탐률 | {pct(test['warn_policy_test']['safe_query_false_positive_rate'])} |",
           f"| 정상 HOLD 오탐률 | {pct(test['hold_policy_test']['safe_query_false_positive_rate'])} |",
           '', '## 변형별 홀드아웃 결과','', '| 유형 | 쿼리 | 원곡 ID | Recall@5 | 원곡별 평균 Recall@5 |','|---|---:|---:|---:|---:|']
    for kind,m in test['positive_by_transformation'].items():
        lines.append(f"| {kind} | {m['query_count']} | {m['independent_source_count']} | {pct(m['expected_source_top5_rate'])} | {pct(m['source_macro_top5_rate'])} |")
    lines+=['','## 실패와 검수 대상','',f'실패·경고 사례 {len(failures)}개는 `layer2/artifacts/full_failure_analysis.csv`에 기록했습니다.',
            '같은 사례에 여러 문제가 겹칠 수 있습니다. 튜닝과 홀드아웃 구분을 유지한 채 분석하세요.',
            '정상후보 중 가장 비슷하게 검색된 50개는 `production_hard_normal_review_queue.csv`에서 청취 검수할 수 있습니다.',
            '', '## 해석 범위','',
            '합성 양성은 실제 표절 판정 데이터가 아닙니다. 독립 연주 파일럿은 별도 `independent_cover_pilot_summary.json`을 참고하세요.',
            '정상후보는 지문 중복을 제거한 후보이며 음악적 독립성 확정 라벨이 아닙니다.',
            'WARN 재현율 90%, HOLD 정상 오탐률 5%는 튜닝 목표입니다. 위 홀드아웃 결과가 목표에 못 미치면 미달로 보고하며 테스트 결과로 임계값을 다시 맞추지 않습니다.']
    (ROOT/'FULL_EVALUATION_RESULTS_20261022.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'completed':True,'warn':warn,'hold':hold,'failures':len(failures),'hard_normal_candidates':50},indent=2))
    from write_run_summary import main as update_summary
    update_summary()

if __name__=='__main__':main()
