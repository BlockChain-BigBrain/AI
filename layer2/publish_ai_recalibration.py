"""Current AI-label scope report, preserving all earlier experiment artifacts."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
import math

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def read(name):
    return json.loads((ART/name).read_text(encoding='utf-8'))


def wilson(k,n):
    if not n:return (None,None)
    z=1.959963984540054;p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0,mid-half),min(1,mid+half)


def main():
    if (ART/'ai_improvement_policy.json').exists():
        raise SystemExit('A newer selective-retrieval policy is active. Use publish_ai_selective_results.py; preserve this historical report.')
    report=read('ai_labeled_recalibration.json')
    provenance=read('pixabay_provenance/audit_summary.json')
    live=read('ai_scope_live_validation.json')
    local=read('local_stack_validation.json')
    team=read('team_live_ai_e2e_validation.json')
    integrity=read('ai_scope_integrity_validation.json')
    assert integrity['status']=='passed'
    assert live['status']==local['status']==team['status']=='passed'
    assert local['evaluation_scope']==team['evaluation_scope']=='ai_labeled'
    a=report['profiles']['ai_labeled_catalog'];b=report['profiles']['full_catalog']
    assert a['enabled']
    manifest_path=ROOT/'layer2/test_data/ai_labeled_positive/manifest.json'
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest()==report['manifest_sha256']
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for dataset in ('positive','safe_music'):
        tune={r['group_id'] for r in manifest['rows'] if r['dataset']==dataset and r['split']=='tune'}
        test={r['group_id'] for r in manifest['rows'] if r['dataset']==dataset and r['split']=='test'}
        assert tune and test and not tune.intersection(test)
    pct=lambda x:'—' if x is None else f'{100*x:.2f}%'
    names={'original_music':'원본','music':'정상후보','premusic':'premusic'}
    lines=['# Pixabay 확인 및 AI 표시군 재평가 결과','',
           '**현재 로컬 서비스는 Pixabay AI 표시 원본 34곡을 검색하는 실험 모드입니다. 기존 원본 1,000곡과 정상후보 300곡은 삭제하지 않았습니다.**','',
           '## 1. AI 생성곡인지 확인한 결과','',
           '| 구분 | 전체 | AI 표시 관찰 | AI 표시 미관찰 | 페이지 미확인·접근 불가 |','|---|---:|---:|---:|---:|']
    for folder,c in provenance['folders'].items():
        lines.append(f"| {names[folder]} | {sum(c.values())} | {c.get('pixabay_ai_label_observed',0)} | {c.get('page_no_ai_label_observed',0)} | {c.get('no_matched_page',0)+c.get('page_fetch_unavailable',0)} |")
    lines+=['','AI 표시 미관찰은 사람이 만들었다는 뜻이 아닙니다. Pixabay 표시는 AI 수정도 포함하고 오분류 가능성이 있어, 이번 확인으로 “사람의 음악적 개입이 없는 순수 AI 생성”을 확정할 수는 없습니다. 파일명 미디어 ID를 공식 페이지에 연결했으며 로컬 SHA-256도 기록했습니다.',
            '1,500개 파일 메타데이터에는 명시적 AI 생성 도구나 Pixabay URL이 없었습니다. 곡별 근거는 [출처 확인표](layer2/artifacts/pixabay_provenance/file_audit.csv), 방법은 [Pixabay 조사 보고서](PIXABAY_AI_AUDIT.md)에 있습니다.',
            '공식 설명: [Pixabay AI 오디오 표시 안내](https://pixabay.com/blog/posts/audio-quality-guidelines-182/).','',
            '## 2. 재평가한 데이터와 분리 방식','',
            '- 검색 기준: AI 표시 원본 34곡. 비교 실험으로 기존 혼합·미확인 1,000곡 DB도 동일 질의로 측정.',
            '- 합성 양성: AI 표시 원본 34곡에서 국소 템포 변형·공간 재녹음 모사를 각각 1개 생성한 68개. 기존 340개와 별도로 보관.',
            '- 정상 대조: AI 표시 정상후보 30곡. 기존 지문 중복 검사 통과 후보이며 음악적으로 독립된 작품이라는 전문가 확정 라벨은 아님.',
            '- 원곡 단위 60% 튜닝·40% 테스트 분리를 계산 전에 고정. 동일 원곡의 두 변형이 양쪽에 섞이지 않음.',
            f"- premusic AI 표시 7곡 중 같은 미디어 ID 등 중복 {len(report['premusic_excluded'])}곡은 정상 평가에서 제외. 남은 {a['premusic_diagnostic']['normal_candidates']}곡은 임계값 보정에 쓰지 않은 별도 진단.",'',
            '## 3. 다시 보정한 임계값과 테스트 결과','',
            '| 구분 | AI 표시 34곡 검색 | 기존 1,000곡 검색 비교 |','|---|---:|---:|',
            f"| WARN | {a['warn_threshold']:.6f} | {b['warn_threshold']:.6f} |",
            f"| HOLD | {a['hold_threshold']:.6f} | {b['hold_threshold']:.6f} |",
            f"| 테스트 양성 / 원곡 수 | {a['test']['positive_queries']} / {a['test']['positive_source_works']} | {b['test']['positive_queries']} / {b['test']['positive_source_works']} |",
            f"| 테스트 정상 후보 | {a['test']['normal_candidates']} | {b['test']['normal_candidates']} |",
            f"| 정상 WARN 이상 비율 | {pct(a['test']['normal_warn_or_hold_rate'])} | {pct(b['test']['normal_warn_or_hold_rate'])} |",
            f"| 정상 HOLD 비율 | {pct(a['test']['normal_hold_rate'])} | {pct(b['test']['normal_hold_rate'])} |",
            f"| 양성 원곡 확인 재현율 · 내부 Top-5 | {pct(a['test']['correct_source_warn_recall_top5'])} | {pct(b['test']['correct_source_warn_recall_top5'])} |",
            f"| 양성 원곡 확인 재현율 · 화면 Top-3 | {pct(a['test']['correct_source_warn_recall_display_top3'])} | {pct(b['test']['correct_source_warn_recall_display_top3'])} |",
            f"| CLAP 원곡 검색 Recall@5 | {pct(a['test']['source_retrieval_at_5'])} | {pct(b['test']['source_retrieval_at_5'])} |",'',
            'WARN는 튜닝 정상 경고 10% 이하의 가장 낮은 기준으로 선택했습니다. HOLD는 튜닝 정상 HOLD 2% 이하에 더해, 튜닝 양성 원곡 점수의 하위 25% 경계 이상을 요구합니다. 정상 튜닝 18곡만으로 만든 두 기준이 부동소수점 한 단계 차이로 붙는 문제를 막기 위한 규칙입니다.',
            '초기 FPR 전용 HOLD의 퇴화 문제를 확인한 뒤 튜닝 자료로 이 규칙을 고쳤습니다. 테스트 점수는 그 과정에서 이미 관찰했으므로 새로운 블라인드 검증으로 주장하지 않습니다. 테스트나 premusic 점수로 임계값 자체를 적합하지는 않았습니다.','']
    n=a['test']['normal_candidates'];k=round(n*a['test']['normal_warn_or_hold_rate']);lo,hi=wilson(k,n)
    lines += ['**테스트 정상 경고 16.67%와 HOLD 8.33%는 목표 10%·2%에 미달했습니다. 임계값 보정과 로컬 적용 완료를 실사용 성능 목표 달성으로 표시하지 않습니다.**', '',
              f'AI 표시군 테스트 정상 경고는 **{k}/{n}곡**입니다. 표본이 작아 정상 경고율의 Wilson 95% 구간은 약 **{pct(lo)}–{pct(hi)}**입니다. 확정된 운영 오탐률이나 전체 모집단의 수치로 해석하지 않습니다.',
              f"premusic 별도 진단 정상 경고율: **{pct(a['premusic_diagnostic']['normal_warn_or_hold_rate'])}** ({a['premusic_diagnostic']['normal_candidates']}곡). 이 수량만으로 성능을 확정할 수 없습니다.",'',
              '## 4. 로컬 적용과 검증','',
              '실시간 분석에서 검색 벡터와 지문 인덱스를 모두 AI 표시 34곡으로 제한했습니다. 출처 허용 목록·검색 DB 해시·보정 기준이 맞지 않으면 시작을 거절합니다. 결과 화면에는 검색 범위와 실제 곡 수를 표시합니다.',
              '실제 분석 점수·후보 순위가 오프라인 평가와 일치하는지 확인했고, 정확 중복 BLOCK과 React 가입·로그인→업로드→AI→Prisma/MySQL→화면 표시도 검증했습니다. 로컬 4개 서버 실행 점검 후 시험용 프로세스는 종료했습니다.','',
              '```powershell','python local_team.py --serve','```','',
              '브라우저: http://localhost:8443/Frontend/ . 표의 1,000곡 비교는 `evaluate_ai_labeled.py`가 같은 AI 표시 질의로 별도 산출한 오프라인 진단입니다. `TRACK_AI_SCOPE=all`은 종전 혼합 DB 보정값을 쓰는 과거 실험 모드로 구분합니다. 원본·정상후보 파일을 삭제하거나 자동 재분류하지 않았습니다.','',
              '## 5. 남은 한계','',
              '- 플랫폼 표시를 넘어 순수 AI 생성임을 증명하려면 생성 서비스의 원본 기록·생성 ID 등 추가 자료가 필요합니다.',
              '- AI 표시 정상 테스트가 12곡뿐이고 양성도 합성 두 종류입니다. 기존 340개 전체 변형 성능이나 실제 독립 AI 생성곡 간 복제 관계 성능으로 일반화하지 않습니다.',
              '- Google OAuth 실제 설정과 운영 배포는 이번 출처 확인·재보정과 별개입니다.','',
              '이전 평가와 비교할 때는 검색 DB 크기·평가 음원·점수 버전을 함께 밝혀야 합니다. 34곡 결과를 1,000곡 전체 성능으로 발표하지 않습니다.']
    (ROOT/'PIXABAY_AI_RECALIBRATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    status={'status':'completed_experimental','completed_utc':datetime.now(timezone.utc).isoformat(),
            'active_local_scope':'ai_labeled','reference_tracks':34,'full_reference_files_preserved':1000,
            'thresholds':{'warn':a['warn_threshold'],'hold':a['hold_threshold']},'test':a['test'],
            'provenance_verified_to':'Official per-track AI label only; not pure-AI generation',
            'production_readiness':False,'source_report':'PIXABAY_AI_AUDIT.md',
            'recalibration_report':'PIXABAY_AI_RECALIBRATION.md'}
    (ART/'ai_scope_completion_status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    operating_path=ART/'layer2_operating_policy.json'
    backup=ART/'pixabay_provenance/pre_ai_scope_operating_policy.json'
    if operating_path.exists() and not backup.exists():backup.write_bytes(operating_path.read_bytes())
    operating={'policy_status':'experimental_pixabay_ai_label_subset_not_pure_ai_verified',
               'active_local_scope':'ai_labeled','reference_tracks':a['reference_tracks'],
               'full_reference_files_preserved':1000,'corpus_version':a['catalog_version'],
               'current_evidence':'ai_labeled_recalibration.json',
               'risk_score':{'score_name':'clap-top5+tonal-local-v1',
                             'warn_threshold_inclusive':a['warn_threshold'],'hold_threshold_inclusive':a['hold_threshold']},
               'candidate_retrieval':{'internal_top_k':5,'display_top_k':3,'positive_queries':68,
                                      'positive_source_works':34,'held_out_source_recall_at_5':a['test']['source_retrieval_at_5']},
               'held_out_metrics':a['test'],'premusic_diagnostic':a['premusic_diagnostic'],
               'calibration':a['threshold_selection'],'hold_additional_rule':a['hold_additional_rule'],
               'validation_status':a['validation_status'],'limitations':report['limits'],
               'production_readiness':False}
    operating_path.write_text(json.dumps(operating,ensure_ascii=False,indent=2),encoding='utf-8')
    from write_run_summary import main as update
    update()
    print(json.dumps(status,indent=2))


if __name__=='__main__':main()
