"""Publish a concise mentoring release from actual artifacts, including failures."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'layer2/artifacts'


def read(name):return json.loads((ART/name).read_text(encoding='utf-8'))


def main():
    active=read('mentoring_final_completion_status.json')
    normal=read('duration_normal_evaluation.json');prototype=read('duration_fusion_evaluation.json')
    front=read('frontend_release_validation.json');back=read('backend_release_validation.json')
    integration=read('release_integration_validation.json');unit=read('release_unit_validation.json')
    publication=read('github_publication_status.json')
    assert all(r['status']=='passed' for r in (front,back,integration,unit))
    assert not prototype['acceptance_met'] and not prototype['active_policy_changed']
    assert front['production_deployed'] is False
    short=normal['summary']['test'];p=prototype['summary'];q=prototype['normal_crops']['test']
    family_names={'basic':'기본 변형','instrument_layer':'악기 레이어','long_auto_edit':'긴 자동 변형','room_effect':'잔향·공간 효과','local_tempo':'구간별 속도 변형'}
    family_table='\n'.join(f"| {label} | {active['by_family'][key]['correct_source_warn_top3_count']}/14 | {prototype['by_family'][key]['correct_source_count']}/14 |" for key,label in family_names.items())
    regressions='\n'.join('- `'+str(Path(path).relative_to(ROOT)).replace('\\','/')+'`' for path in prototype['per_query_source_regressions'])
    github_lines='\n'.join(f"- [{name}]({item['url']}): `{item['branch']}` → `{item['base']}`; {item['state']}." for name,item in publication['repositories'].items())
    report=f'''# 멘토링 최종 정리 — 2026-10-25

## 지금 결론

**데이터 감사·평가·실패 분석과 최신 팀 코드의 로컬 AI·DB 연동은 완료했습니다. 운영 배포와 성능 목표 전체 달성은 아직 아닙니다.** 이번에는 정상곡의 길이를 맞춰 재평가했고, 기존에 보이지 않던 짧은 업로드의 오탐 문제를 확인했습니다. 새 모델 후보는 일부 개선에도 기존 양성을 놓쳐 적용하지 않았습니다. GitHub에는 코드·결과와 검토용 PR을 올렸으며 main 병합·서비스 배포는 하지 않았습니다.

검색 범위는 **Pixabay AI 표시 원곡 34곡**입니다. 보관 중인 원곡 1,000곡 전체의 성능이나 순수 AI 생성 검증 결과로 해석하면 안 됩니다. 사람 연주·커버 확보는 이번 범위에서 제외합니다.

## 목표와 실제 결과

| 항목 | 목표 | 현재 적용 모델 결과 | 판정 |
|---|---|---|---|
| 기존 양성 원곡 확인 | WARN 이상·Top3 재현율 ≥90% | 28/28, 100% | 기존 개발 자료에서 달성 |
| 새 5종 변형 | 전체 재현율 ≥90% | 63/70, 90% | 전체는 달성, 변형별 편차 남음 |
| 정상 전체 길이 | WARN 이상 ≤10% | 중복 라벨 격리 후 1/11, 9.09% | 작은 기존 표본에서 달성 |
| 정상 30초, 길이 일치 재평가 | WARN 이상 ≤10% | **{short['warn_works']}/{short['works']}, {short['warn_rate']:.2%}** | **미달** |
| 정상 HOLD 이상 | ≤2% | 전체 길이·30초 각각 0/11, 0% | 점추정 달성, 통계적 입증 아님 |
| 최신 팀 코드에서 실제 AI→DB | 대응 근거 저장·실패 구분 | 실제 WARN·매칭 3구간 저장, 소유자 거부, 실패 저장 | 로컬 완료 |
| 독립된 새 AI 작품 검증 | 미사용 작품·생성 기록·정책 동결 | 실제 신규 자료 없음 | 미완료 |
| 운영 Google 로그인·HTTPS·실부하 | 실제 배포 환경에서 확인 | 운영 자격증명·배포 검증 없음 | 미완료 |

‘정상 경고’는 WARN·HOLD를 포함하고, 지문 BLOCK이 나오면 별도 확인합니다. 원곡 재현율은 예상 원곡이 표시 Top3에 있고 그 원곡 점수가 WARN 이상일 때만 성공입니다. 다른 곡이 높게 경고하는 것은 성공으로 세지 않습니다.

기존 전체 길이 평가에서 중복 의심 라벨을 격리하기 전 수치는 WARN 2/12(16.67%), HOLD 1/12(8.33%)입니다. 격리 후 11곡 수치와 함께 보존했습니다. 데이터는 삭제하지 않았습니다. 격리 여부와 무관하게 새로운 30초 정상 11작품은 33개 조각으로 검사했으며, 같은 작품의 조각 중 하나라도 경고하면 그 작품을 경고 작품으로 셉니다.

11작품에서 0건이어도 단측 95% 오탐률 신뢰상한은 약 23.84%입니다. 기존 1/11 WARN의 상한은 약 36.44%입니다. 따라서 0%·9.09%만으로 목표를 안정적으로 입증했다고 말할 수 없습니다. 오탐 0건을 가정해도 WARN ≤10%의 상한 확인에는 독립 정상 29작품, HOLD ≤2%에는 149작품이 필요합니다.

## 이번 추가 실험과 채택 결정

정상 31작품에서 시작·중간·끝 30초 조각 **93개**를 생성했습니다. 튜닝 18작품(54조각), 기존 테스트 11작품(33조각), premusic 진단 2작품(6조각)입니다. 모두 기존에 본 작품이며 독립 신규 AI 자료가 아닙니다. 현재 실제 판정기로 93개 전부 실행했습니다. 튜닝 경고는 5/18(27.78%), 테스트는 2/11(18.18%), premusic은 1/2(50%)였습니다. HOLD·BLOCK은 0건입니다.

84개 음높이 대역의 시간 변화를 보존하는 정렬을 추가 개발했습니다. AI 34곡은 전수 비교하고, 혼합 원곡 1,000곡은 CLAP Top20과 음높이 검색 Top20의 합집합으로 비교했습니다. 기존 226개 쿼리와 새 정상 조각 93개, 총 **319개 × 2개 검색 범위 = 638개 결과**를 계산했습니다. 단독 교체 후보는 기존 양성 재현율을 떨어뜨려 기각했습니다. 낮은 임계값의 결합 후보도 개발용 비교로만 보관했습니다.

짧은 업로드에만 보정을 적용하고 45초 이상 기존 판정은 유지하는 후보는 다음 결과를 냈습니다. 임계값은 튜닝 정상 작품만으로 결정했지만, 실험 설계 자체는 기존 결과를 본 뒤 정했으므로 맹검 결과가 아닙니다.

| 변형 | 현재 적용 | 길이별 결합 후보 — 미적용 |
|---|---:|---:|
{family_table}
| 합계 | 63/70 (90%) | 69/70 (98.57%) |

후보의 길이 일치 정상 테스트는 {q['warn_works']}/{q['normal_works']} 경고, 전체 길이까지 작품별로 합치면 {p['test']['warn_works']}/{p['test']['normal_works']} 경고입니다. 그러나 스트레스 재현율은 기존 26/28→{p['new_transform_stress']['correct_source_count']}/28, 반복 변형은 27/28→{p['new_replication']['correct_source_count']}/28로 낮아졌습니다. **기존에 맞추던 양성 {len(prototype['per_query_source_regressions'])}개를 새로 놓쳐 채택 기준을 통과하지 못했습니다.** 전체 평균 98.57%만 보고 기존 모델을 교체하지 않았습니다.

새로 놓친 회귀 사례:

{regressions}

현재 적용 임계값은 WARN **0.3474893216**, HOLD **0.8337449399**이며 `ai_precision_policy.json`을 유지합니다. 새 후보의 보정값은 `duration_fusion_evaluation.json`에만 있으며 실행 판정기에는 연결하지 않았습니다. 현재 판정기도 실험용이며 짧은 정상 업로드의 오탐 목표가 미달이므로 운영 자동 판정에 충분하다고 권고하지 않습니다.

## 멘토링 기준 완료·미완료

| 과제 | 상태 | 완료 내용 / 남은 내용 |
|---|---|---|
| 정상후보 17곡 교체 | 완료 | premusic 교체·지문 중복 검사, 기존 파일 백업 |
| 합성 양성 2종 추가 | 완료 | 기존 기본·악기·긴 변형에 잔향·구간 속도 추가, 역사적 340개 평가 |
| 정상·premusic 감사 | 완료 | 500개 시도, 499개 지문 분석, 너무 짧은 1개; music 유사 녹음 3개·premusic 75개 라벨 격리 |
| AI 생성 여부 확인 | 부분 완료 | 플랫폼 표시 원곡34·music30·premusic7 확인; 순수 AI 생성은 미확정 |
| 1,000·300·340 전체 평가 | 기준 평가 완료 | 역사적 혼합 DB 기준 평가 보존; AI 전용 현재 성능과 구분 |
| 임계값·실패 분석 | 수행 완료, 목표 미완료 | 기존·새 보정 비교, 길이 편향·회귀 5개 공개; 짧은 정상 오탐 해결 필요 |
| 새로운 독립 AI 작품 검증 | 미완료 | 입고 검사·중복 거부·정책 동결 도구 준비, 실제 미사용 생성 자료 필요 |
| 최신 프론트·백엔드 연동 | 로컬 완료 | 최신 main 기반 포팅, 실제 AI·MySQL 저장·대응 구간·오류·소유자 검사 |
| 운영 검증 | 미완료 | 실제 Google OAuth·HTTPS·운영 MySQL·동시 사용자 부하·권리 거래 검증 필요 |
| GitHub 업데이트 | PR 게시 | 아래 3개 저장소의 검토 브랜치. 병합·배포는 미수행 |

역사적 1,000곡 기준 CLAP 평가의 높은 정상 경고율과, 후속 혼합 DB 복합 변형의 낮은 성능을 숨기지 않았습니다. 새 84대역 단독 후보의 혼합 1,000곡 성능도 기존 테스트 원곡 확인 21/28, 새 5종 59/70이므로 채택하지 않았습니다. 34곡의 높은 수치를 1,000곡 성능으로 확대 주장하지 않습니다.

## 코드·운영 시험

- AI 단위 검증: **{unit['passed']}/{unit['tests']} 통과**. 피치·시간 위치, 무음·무관 음원, 구간 분리, 데이터 오염, 정책 동결과 점수 보정 검사 포함.
- 최신 Frontend: **{front['tests']}개 통과**, 타입 검사 통과. 실제 메타데이터로 만든 대응 구간 컴포넌트를 1440px·390px에서 확인. 동일 설정으로 production 2회 빌드 결과 일치, 기존 HTTPS API 주소 보존, `docs/` 생성물 포함.
- 최신 Backend: **{back['tests']}개 중 {back['passed']} 통과, 실패 0, {back['skipped']} 건너뜀**. 4개는 기존 DB·Hardhat 환경 의존, 1개는 Windows 심볼릭 링크 권한 제약. 경로 탐색 차단 검사는 수행했습니다.
- 최신 HTTP AI 공급자→실제 AI→격리 MySQL: **통과**. WARN, 대응 구간 3개 저장, 소유자 거부, 명시적 공급자 실패 처리. 실패 공급자는 이 항목만 의도적인 시험 대역입니다. 실제 성공 분석은 대역 없이 실행했습니다.
- 예전 팀 코드의 업로드→결과 저장→새로고침 전체 시험도 기존 산출물로 보존했습니다. 최신 화면 시험은 대응 근거 컴포넌트 검증이며 실제 운영 Google 로그인·지갑 거래 완료를 의미하지 않습니다.

## GitHub 업데이트

{github_lines}

최신 팀 코드 기준 Frontend `25fdf3a`, Backend `9216133`에서 별도 worktree로 작업했습니다. 이전 로컬 수정 폴더를 덮어쓰지 않았습니다. 음원·가중치·실제 `.env`·비밀키는 게시 대상에서 제외했습니다. AI 저장소 PR은 기존 공개 main의 7개 선행 커밋도 포함해 기본 브랜치 `branch1`을 대상으로 합니다.

## 다음에 할 일 — 우선순위

1. **미사용 AI 생성 자료 확보:** 원본 파일, 서비스·모델 버전, 생성 ID·기록을 가진 양성 원곡과 독립 정상 작품을 준비합니다. 동일 생성물·파생 파일은 같은 그룹으로 묶고, 정책을 먼저 동결합니다. 사람 연주 자료는 요구하지 않습니다.
2. **길이 편향과 구간 재배열을 함께 해결:** 정상 30초 오탐을 줄인 후보가 기존 재배열 양성을 놓칩니다. 길이별 점수 보정과 재배열에 강한 지역 대응 근거를 함께 검증해야 합니다. 같은 11작품을 반복 튜닝해 최종 성능으로 주장하지 않습니다.
3. **1,000곡 확장:** 후보 검색에서 원곡이 누락되는 문제와 재정렬 실패를 나눠 측정합니다. AI 출처 확인 범위도 확대해야 합니다.
4. **배포 환경 시험:** 팀이 운영 환경 설정을 로컬에 제공하면 HTTPS·Google 로그인·운영 DB·실부하·검토 보류 흐름을 확인합니다. 지금 기록은 로컬 검증입니다.
5. **다음 멘토링 결정:** [질문지](MENTORING_QUESTIONS_20261025.md)의 범위·작품 단위 기준·통계적 합격선·실패 비용부터 확정합니다.

## 바로 확인할 근거

- [현재 적용 5종·기존 테스트](layer2/artifacts/mentoring_final_completion_status.json)
- [실제 판정기 정상 30초 평가](layer2/artifacts/duration_normal_evaluation.json)
- [미채택 길이별 후보와 회귀 목록](layer2/artifacts/duration_fusion_evaluation.json)
- [AI 34곡·혼합 1,000곡 새 비교](layer2/artifacts/spectral_release_evaluation.json)
- [최신 실제 AI·MySQL 시험](layer2/artifacts/release_integration_validation.json)
- [프론트 검증](layer2/artifacts/frontend_release_validation.json) · [백엔드 검증](layer2/artifacts/backend_release_validation.json)
- [데스크톱 화면](layer2/artifacts/modern_evidence_desktop.png) · [모바일 화면](layer2/artifacts/modern_evidence_mobile.png)

재생성: `python layer2/publish_release_status.py`. 평가 코드와 manifest는 저장소에 포함하고, 음원·모델·평가 캐시는 로컬에 보관합니다. 새 clone에서 평가를 재실행하려면 해당 데이터와 모델을 별도로 준비해야 합니다.
'''
    report_path=ROOT/'MENTORING_FINAL_STATUS_20261025.md';report_path.write_text(report,encoding='utf-8')
    status={'date':'2026-10-25','status':'local_release_work_completed_with_unmet_research_and_production_goals',
        'active_policy':'ai_precision_policy.json','active_policy_changed_this_release':False,
        'active_five_family':active['five_family'],'duration_matched_normal_test':short,
        'prototype_five_family':p['prospective_five_family'],'prototype_accepted':False,
        'source_regressions':len(prototype['per_query_source_regressions']),
        'fresh_independent_ai_validation':False,'pure_ai_creation_verified':False,'production_deployed':False,
        'github':publication,'report':report_path.name,'report_sha256':hashlib.sha256(report_path.read_bytes()).hexdigest(),
        'mentor_questions':'MENTORING_QUESTIONS_20261025.md'}
    (ART/'mentoring_release_status_20261025.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    print('Published '+report_path.name)


if __name__=='__main__':main()
