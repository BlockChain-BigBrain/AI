"""Publish the completed revision evidence without rewriting historical metrics."""
import json
import csv
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'


def read(name):
    path = ART / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def main():
    tonal = read('tonal_confirmation_evaluation.json')
    cover = read('tonal_cover_summary.json')
    audit = read('fresh_audit_summary.json')
    review = read('listening_review_preparation.json')
    operations = read('operational_test_summary.json')
    team = read('team_live_ai_e2e_validation.json')
    failure = read('team_frontend_integration_validation.json')
    assert tonal.get('enabled') and cover and audit and review
    assert operations.get('status') == team.get('status') == failure.get('status') == 'passed'
    assert team.get('ai_score_version') == 'clap-top5+tonal-local-v1'
    failures=[]
    by_kind=defaultdict(list)
    for line in (ART/'tonal_confirmation_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        positive=r['dataset']=='positive'
        if positive and r['split']=='test': by_kind[r['query_kind']].append(r)
        issue='positive_source_not_confirmed' if positive and (r['expected_score'] is None or r['expected_score']<tonal['warn_threshold']) else 'normal_candidate_warn' if not positive and r['score']>=tonal['warn_threshold'] else None
        if issue:
            failures.append({k:r[k] for k in ('file','dataset','query_kind','split','expected_track_id','score','expected_score')})
            failures[-1].update(issue=issue, top_candidate=r['candidates'][0]['trackId'])
    with (ART/'tonal_failure_analysis.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(failures[0]));writer.writeheader();writer.writerows(failures)
    breakdown=['## 어떤 변형을 놓치는지', '', '| 기존 테스트 그룹 변형 | 쿼리 / 원곡 수 | 원곡 확인 재현율 |', '|---|---:|---:|']
    names={'room_rerecord_simulation':'공간 재녹음 모사','local_tempo_warp':'국소 가변 템포',
           'synthetic_same_recording_excerpt':'기본 변형','synthetic_arrangement_or_audio_transform':'긴 자동 편곡·오디오 변형',
           'synthetic_instrument_layer_overlay':'악기 레이어 합성'}
    for kind, rows in sorted(by_kind.items()):
        rate=sum(r['expected_score'] is not None and r['expected_score']>=tonal['warn_threshold'] for r in rows)/len(rows)
        breakdown.append(f"| {names.get(kind,kind)} | {len(rows)} / {len({r['group_id'] for r in rows})} | {100*rate:.2f}% |")
    breakdown += ['', f'새 기준의 실패·정상 경고 {len(failures)}건은 `layer2/artifacts/tonal_failure_analysis.csv`에 구분해 기록했습니다. 원곡 수가 적은 변형의 결과는 특히 불확실합니다.', '']
    baseline = read('calibrated_policy_20261022.json')
    pct = lambda value: f'{100*value:.2f}%'
    previous = baseline['test']['warn_policy_test']
    current = tonal['reused_test']['warn']
    hold = tonal['reused_test']['hold']
    # Point consumers at the current score; preserve the historical calibration.
    operating_path = ART / 'layer2_operating_policy.json'
    operating = read('layer2_operating_policy.json')
    backup = ART / 'pre_full_evaluation_20261022/pre_tonal_operating_policy.json'
    if not backup.exists(): backup.write_text(json.dumps(operating, indent=2), encoding='utf-8')
    operating.update(policy_status='tonal_confirmation_experimental', evaluated_at=datetime.now(timezone.utc).isoformat(),
                     current_evidence='tonal_confirmation_evaluation.json', fresh_audit='fresh_audit_summary.json',
                     risk_score={'score_name': 'clap-top5+' + tonal['score_version'],
                                 'warn_threshold_inclusive': tonal['warn_threshold'], 'hold_threshold_inclusive': tonal['hold_threshold']},
                     held_out_metrics=current, test_set_status='historical groups reused, additional fresh source audit separately reported',
                     independent_cover_benchmark=cover['tonal'],
                     limitations=tonal['limitations'] + cover['limitations'] + audit['limitations'])
    operating_path.write_text(json.dumps(operating, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 멘토링 후속 개선 결과 · 2026-10-22', '',
             '**범위 수정: 사용자 지시에 따라 AI 생성 음원만 주 평가 대상으로 합니다. 사람의 독립 연주 자료 확보는 필수 과제에서 제외했습니다. [AI 전용 평가 범위](AI_ONLY_SCOPE.md)를 먼저 참고하세요. 기존 데이터 전체의 AI 생성 출처는 아직 확인되지 않았습니다.**', '',
             '**현재 로컬 실험용 판정 기준입니다. 이전 수치는 보존했으며, 추가 정상 후보 경고율이 목표에 못 미쳐 실사용 검증 완료로 표시하지 않습니다.**', '',
             '| 항목 | 처리 결과 |', '|---|---|',
             '| 정상 경고 개선 | 음색 검색 Top-5를 음높이 흐름으로 재확인. 튜닝 정상 WARN 10%·HOLD 2% 이내로 기준 선택 |',
             '| 독립 연주 검색 | 음높이 흐름으로 전체 80곡 검색하는 별도 검색기 구현·비교 완료 |',
             f"| 추가 분리 점검 | 새 원곡 20곡의 합성 변형 40개·premusic 정상 후보 30곡, 임계값 재학습 없이 점검 |",
             f"| 청취 검수 준비 | 두 음원 A/B 재생·시작점 이동·검수자/근거 저장·JSON 내보내기. {review['cases']}건 준비 |",
             '| 로컬 사용 | 개발용 계정 가입·로그인 → 업로드 → 실제 AI → MySQL 저장·화면 표시 시험 통과 |',
             '| 장애·운영 시험 | 실패·재분석·권한·새로고침·3분 음원·동시 요청·재시작 시험 통과 |', '',
             '## 정상 경고와 양성 재현율', '',
             f"현재 WARN **{tonal['warn_threshold']:.6f}**, HOLD **{tonal['hold_threshold']:.6f}**. 점수 버전 `clap-top5+{tonal['score_version']}`.", '',
             '| 기존 테스트 그룹 재사용 결과 | 이전 음색 점수 기준 | 음높이 흐름 확인 후 |', '|---|---:|---:|',
             f"| 정상 WARN 이상 비율 | {pct(previous['safe_query_false_positive_rate'])} | {pct(current['normal_false_positive_rate'])} |",
             f"| 양성 원곡 WARN 이상 재현율 | {pct(previous['positive_expected_source_recall'])} | {pct(current['correct_source_recall'])} |",
             f"| 정상 HOLD 비율 | {pct(baseline['test']['hold_policy_test']['safe_query_false_positive_rate'])} | {pct(hold['normal_false_positive_rate'])} |", '',
             '기존 실패를 본 뒤 같은 테스트 그룹을 다시 사용했으므로 새로운 블라인드 검증으로 주장하지 않습니다. 새 기준은 CLAP Top-5 안에서만 원곡을 확인하며, 경고 감소와 함께 놓치는 양성도 확인해야 합니다.', '',
             *breakdown, '## 추가 분리 점검', '',
             f"원곡 확인 재현율 **{pct(audit['correct_source_warn_recall'])}**, 양성 질의 경고율 **{pct(audit['positive_query_recall'])}**, 정상 후보 경고율 **{pct(audit['normal_warn_or_hold_rate'])}**.",
             '**추가 정상 후보 경고율 26.67%(8/30)는 목표 10%를 넘었습니다. 추가 점검 결과로 임계값을 다시 조정하지 않았으며, 경고 일반화 문제는 아직 남아 있습니다.**',
             '추가 평가 음원·원곡 ID·해시를 먼저 고정했고 결과로 임계값을 다시 맞추지 않았습니다. 정상 후보는 지문 중복 검사를 통과했지만 전문가가 다른 작품임을 확정한 라벨은 아닙니다. 양성은 합성 변형이며 실제 커버와 구분합니다.', '',
             '## 독립 연주 검색', '',
             '| 동일한 Covers80 중앙 30초·80곡 후보 | 기존 CLAP | 새 음높이 흐름 검색 |', '|---|---:|---:|',
             *[f"| Recall@{k} | {pct(cover['clap_baseline'][f'recall_at_{k}'])} | {pct(cover['tonal'][f'recall_at_{k}'])} |" for k in (1,3,5)], '',
             '이미 관찰한 벤치마크의 탐색적 비교이며, 운영 1,000곡 DB의 독립 연주 검색 성능으로 일반화하지 않습니다. 실시간 판정은 CLAP Top-5 확인 방식이고, 독립 연주 실험은 음높이 흐름으로 80곡 전체를 검색합니다. 따라서 두 수치를 섞지 않습니다.', '',
             '방법 참고: [Essentia CoverSongSimilarity](https://essentia.upf.edu/reference/std_CoverSongSimilarity.html). 이번 구현은 연속 코사인 기반 자체 알고리즘이며 Essentia 구현과 동일하지 않습니다.', '',
             '## 바로 확인하는 방법', '',
             '```powershell', 'python local_team.py --serve', '```', '',
             '브라우저: http://localhost:8443/Frontend/ → 로컬 계정 만들기 → 로그인 → Upload. 계정 정보는 본인이 정하며 Access token은 기존 메모리 방식, 재발급은 HttpOnly 쿠키를 사용합니다. 개발용 로그인 화면은 DEV 모드와 `VITE_LOCAL_LOGIN=true`일 때만 표시합니다.', '',
             '청취 검수 화면: [review_workbench/index.html](review_workbench/index.html). 로컬 파일을 직접 열고 두 녹음을 듣고 검수자·판단·근거를 기록한 뒤 JSON으로 내보내세요. 이 페이지는 음원 파일이 있는 이 PC에서 사용합니다.', '',
             '## 아직 사람이 해야 하는 부분', '',
             '- 청취 검수: 준비와 자동 비교는 완료했지만 사람이 듣고 판단한 것으로 표시하지 않았습니다.',
             '- Google OAuth: 실제 Client ID·Secret이 없어 Google Cloud 로그인을 시험하지 못했습니다. 로컬 가입·로그인으로 서비스 시험은 가능합니다.',
             '- AI 생성 출처가 확인된 자료에서 다시 평가해야 합니다. 사람의 독립 연주 자료 확보는 현재 범위의 필수 과제가 아닙니다.', '',
             '기존 원본·정상곡·합성 340개와 과거 평가 결과는 보존했습니다. 추가 합성 40개·정상 후보 30개는 기존 수량에 섞지 않은 별도 점검 자료입니다. 커밋·push·운영 배포는 하지 않았습니다.']
    (ROOT / 'MENTORING_REVISION_20261022.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (ART/'revision_completion_status.json').write_text(json.dumps({
        'status':'completed_with_limitations', 'completed_utc':datetime.now(timezone.utc).isoformat(),
        'primary_scope':'AI-generated audio and automatic transforms only',
        'independent_human_performance_required':False,
        'ai_only_dataset_provenance_verified':False,
        'score_version':'clap-top5+'+tonal['score_version'],
        'implemented_and_evaluated':['tonal confirmation','false warning calibration','80-cover tonal search',
                                   'separate 70-query audit','listening workbench','local signup/login','real stack regression tests'],
        'unmet_performance_goal':'Additional normal candidate warning rate 8/30 (26.67%) exceeds 10% target.',
        'remaining_external_actions':['Human listening and annotation','Real Google OAuth client credentials'],
        'production_readiness':False, 'automatic_legal_verdict':False},indent=2),encoding='utf-8')
    from write_run_summary import main as update
    update()
    print('Published current revision results and preserved historical evaluation.')


if __name__ == '__main__': main()
