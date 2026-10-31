# 멘토링 실행 현황 · 2026-10-22

**현재 최종 상태는 [멘토링 기준 최종 현황](MENTORING_FINAL_STATUS_20261023.md)입니다. 새 5종 70개·정밀 보조 경로·500곡 감사·목표 대비 미완료 항목을 구분합니다.**

**2026-10-23 최신 적용 결과는 [AI 검색 개선 정리본](AI_IMPROVEMENT_20261023.md)을 먼저 보세요. 후보 Top-20·추가 후보 감점과 정상 라벨 감사가 반영됐습니다. 아래 표의 이전 실험과 구분합니다.**

**완료 여부는 실제 결과 파일 기준입니다. 계산 중인 작업을 완료로 표시하지 않습니다.**

**범위 수정: AI 생성 음원만 주 평가 대상으로 합니다. 독립 연주 확보는 필수 과제에서 제외하며, 기존 데이터의 AI 생성 출처 확인이 필요합니다. [평가 범위](AI_ONLY_SCOPE.md)**

**현재 개선 결과는 [후속 개선 정리본](MENTORING_REVISION_20261022.md)을 먼저 보세요. 기존 CLAP 평가와 새 음높이 흐름 판정을 구분합니다.**

**최신 AI 표시군 출처 확인·재보정 결과는 [Pixabay AI 재평가](PIXABAY_AI_RECALIBRATION.md)에 별도로 정리했습니다. AI 표시가 순수 AI 생성의 증명이라는 뜻은 아닙니다.**

| 요청 항목 | 상태 | 현재 결과 |
|---|---|---|
| 정상 대조곡 17곡 교체 | 완료 | 지문 중복 제거·premusic에서 검사 통과한 17곡 보충, 정상후보 300곡 유지 |
| 합성 양성 확장 | 완료 | 공간 재녹음 모사·국소 가변 템포 2종 추가, 합계 340개 |
| Pixabay AI 표시 출처 조사 | 완료 | 1,500개 메타데이터·곡별 공개 페이지 조사: 원본 34·정상후보 30·premusic 7곡에 AI 표시 관찰 |
| AI 표시군 별도 재보정 | completed_experimental | AI 표시 원본 34곡 검색, WARN 0.347489 / HOLD 0.833745 |
| 최신 DB 전체 평가 | 완료 | 원본 1,000곡·합성 양성 340개·정상후보 300곡, 10초 창·5초 간격 전체 평가 |
| 종전 혼합 DB 임계값 | 과거 실험 보존 | 음높이 흐름 WARN 0.3303172208078136 / HOLD 0.5440137575316275 |
| 정상 경고 감소 검증 | 평가 완료 | 기존 테스트 그룹 정상 경고 10.74%, 원곡 확인 재현율 85.61% |
| 별도 원곡·정상 후보 추가 점검 | 완료·목표 미달 확인 | 신규 합성 40개·정상 후보 30곡: 정상 경고 26.67%, 임계값 재학습 없음 |
| 실패 사례 분석 | 완료 | 유형별 성능·원곡별 평균·누락 원곡·정상 경고 목록 생성 |
| 독립 연주 자료 확보 | 80쌍 확보·20쌍 파일럿 완료 | 공식 Covers80, 기존 1,000곡 DB와 별도 보관 |
| 독립 연주 80쌍 전체 벤치마크 | 완료 | 중앙 30초 발췌, 독립된 80곡 후보 검색. 운영 1,000곡 평가와 분리 |
| 독립 연주 검색 개선 비교 | 완료 | 음높이 흐름 검색 Top-1 23.75% / Top-5 33.75% |
| A/B 청취 검수 화면 | 준비 완료·사람 검수 대기 | 69건의 음원 쌍·시작점 이동·근거 기록·JSON 내보내기 |
| 어려운 대조 후보 | 6320쌍 추출 완료 | 다른 작품 ID 간 유사 후보. 전문가 청취 검수는 미완료 |
| 로컬 실제 업로드 화면 | 구현 완료 | 업로드·분석 상태·Top-3·매칭 구간·작업 ID 재조회 |
| 브라우저 실패 처리 시험 | 통과 | 실제 Chrome→Node→SQLite FAILED 저장, PASS 오표시 방지·모바일 확인 |
| MySQL 선택형 저장소 | 구현 완료 / 로컬 엔진 시험 passed | DATABASE_URL 설정 시 MySQL 사용. 팀 DB 접속 시험과 별개 |
| 정상 완료·3분 곡·동시 업로드·재시작 시험 | passed | 격리된 실제 FastAPI·Node·SQLite와 브라우저 사용 |
| 팀 React·인증·Prisma·MySQL 연결 | passed | 실제 저장소를 받아 격리 MySQL에서 브라우저 실패 처리·새로고침·권한 검증 |
| 팀 화면의 실제 AI 성공 경로 | passed | 실제 FastAPI의 중복 BLOCK 결과를 팀 Prisma에 저장하고 React에서 확인 |
| 로컬 팀 실행 설정 | passed | localhost:8443 → localhost:3000 → 별도 MySQL 3307, local_team.py로 준비·실행 |
| 로컬 Google OAuth | 설정 필요 | 실제 Google Client ID·Secret 미제공, 기존 인증 회귀 시험만 통과 |
| 운영 배포 DB·Google OAuth | 설정 필요 | 실제 운영 MySQL·Google 설정 파일 및 HTTPS API 주소 미제공 |

## 독립 연주 파일럿 결과

20개 작품의 다른 연주 버전을 검색한 파일럿에서 Recall@1 **15.0%**, Recall@3 **50.0%**, Recall@5 **50.0%**입니다.
중앙 30초 발췌, 후보 20곡으로 측정했습니다. 전체 길이·원본 1,000곡 DB의 실제 커버 성능으로 일반화하지 않습니다.
현재 CLAP의 독립 연주 검색은 보완이 필요합니다. 공개 사전학습 데이터와의 중복 여부도 검증되지 않았습니다.
다른 작품 간 후보 380쌍은 합성 음원이 아닌 실제 녹음 간 대조 후보지만, 법적 비표절 확정 라벨은 아닙니다.
출처: [Covers80 공식 안내](https://www.labrosa.org/projects/coversongs/covers80/). 연구 자료로 별도 보관하며 상업적 재배포 권한을 확인한 것으로 취급하지 않습니다.

80쌍 전체의 중앙 30초 벤치마크: Recall@1 **10.00%**, Recall@3 **17.50%**, Recall@5 **26.25%**, MRR **0.1899**.
다른 작품 간 검수 후보는 6,320쌍입니다. 같은 160개 녹음의 조합이므로 독립 음원 수로 세지 않습니다.

## 실행 중인 작업과 확인 방법

- 워크플로 상태: `completed_local` / 단계: `local_work_complete`.
- 실시간 상태: [mentoring_workflow_status.json](layer2/artifacts/mentoring_workflow_status.json)
- 평가 로그: `layer2/artifacts/workflow_full_evaluation.log`
- 독립 연주 수치: [independent_cover_pilot_summary.json](layer2/artifacts/independent_cover_pilot_summary.json)
- 어려운 대조 후보: `layer2/artifacts/hard_negative_review_queue.csv`
- 전체 평가가 끝나면 [전체 평가 결과](FULL_EVALUATION_RESULTS_20261022.md)가 생성됩니다.
- 운영 시험 결과: `layer2/artifacts/operational_test_summary.json` (시험 후 생성).

```powershell
# 현재 상태와 로그 확인
Get-Content -Encoding UTF8 layer2/artifacts/mentoring_workflow_status.json
Get-Content -Encoding UTF8 layer2/artifacts/workflow_full_evaluation.log -Tail 12

# 중단된 경우에만 재개: 진행 중인 인스턴스와 중복 실행하지 마세요.
python run_mentoring_workflow.py

# 상태 문서를 최신 결과로 갱신
python layer2/write_run_summary.py

# 로컬 팀 DB 준비 (반복 실행 시 데이터 유지)
python local_team.py
# 전체 평가와 보정 완료 후 실제 팀 React·Backend·AI·MySQL 실행
python local_team.py --serve

# 전체 평가와 보정 완료 후 별도 로컬 MVP 실행 (팀 React 서버와 구분)
./Start-TrackAI.ps1
```

장시간 계산은 숨김 백그라운드 프로세스로 실행되며 임베딩·쿼리별 결과를 저장합니다. PC가 종료되거나 절전 상태가 되면 완료되지 않습니다. 중단 후에는 같은 명령으로 캐시를 재사용할 수 있습니다.
팀 저장소 작업 복사본은 `integrations/Frontend`, `integrations/Backend`입니다. 연결 범위와 검토 방법은 [실제 팀 연결 검토본](TEAM_INTEGRATION_REVIEW_20261022.md)을 참고하세요. 커밋·push는 하지 않았습니다. 운영 MySQL·Google OAuth 설정과 실제 HTTPS API 주소가 없어서 운영 배포 연결 완료 여부는 확인할 수 없습니다. 비밀번호는 채팅에 적지 말고 로컬 설정 파일이나 환경변수로 제공하세요.
