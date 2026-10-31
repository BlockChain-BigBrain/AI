# Track-AI 프로젝트 안내

> 2026-10-30: 추가 `premusic` 181곡 중 완전 중복 2곡을 삭제하고 고유 179곡을 사용 이력 폴더로 이동했습니다. 30곡 기반 기본 변형·악기 레이어 변형 60개를 만들었고, 키 보정 Chroma/CQT는 두 유형 모두 Top-1 30/30, 별도 리듬 검색은 악기 레이어 30/30·기본 변형 Top-5 10/30이었습니다. 위치 결과는 생산 WARN과 다른 CLAP 후보 진단으로 보존했습니다.

> 2026-10-30: [추가 premusic 43곡 선별·평가 결과](layer2/artifacts/new_premusic_43_work_results_20261029.csv). 기존 사용곡·기준 음원과 SHA-256, Pixabay 미디어 ID, 제한된 음향 지문 대조에서 겹침 0곡이었고, 완곡 경고 0/43, 30초 구간 경고 9/43입니다. 43곡을 `premusic_used/new_premusic_20261029/`로 이동했으며 삭제한 겹침 파일은 0곡입니다.

> 2026-10-29: [premusic 50곡 신규 진단·중복 정리 결과](PREMUSIC_HOLDOUT_20261029.md). 완곡 6/50, 30초 작품 23/50 경고입니다. 사용곡 81곡은 [용도별 보관 폴더](premusic_used/README.md)로 이동했고, 동일 SHA 보존본이 있는 중복 78개를 제거했습니다. 이 50곡의 순수 AI 생성 출처는 확인되지 않았습니다.

> 2026-10-25: [최신 완료·미완료와 목표 비교](MENTORING_FINAL_STATUS_20261025.md) / [다음 멘토링 질문](MENTORING_QUESTIONS_20261025.md). 정상 30초 평가에서 경고율 목표 미달을 확인했으며, 98.57% 실험 후보는 회귀 때문에 미채택입니다.

음원 파일의 완전 중복을 찾아 업로드를 거절하는 Layer 1과, 유사 음원을 검색해 검토를 돕는 Layer 2를 개발합니다.

## 먼저 읽을 문서

- [premusic 50곡 신규 진단·정리](PREMUSIC_HOLDOUT_20261029.md): 전체 해시·녹음 중복 대조, 완곡과 30초 작품 경고율, AI 출처의 한계
- [멘토링 기준 최종 현황·목표 비교](MENTORING_FINAL_STATUS_20261023.md): 500곡 감사, 새 5종 70개 평가, 긴 편집 복원, 완료·미완료와 다음 준비물
- [2026-10-23 검색 개선 결과](AI_IMPROVEMENT_20261023.md): 후보 확대·추가 후보 감점, 복합 변형 원곡 확인 개선과 정상 경고율의 정확한 분모
- [최신 Pixabay AI 표시군 재평가](PIXABAY_AI_RECALIBRATION.md): AI 표시 34곡 검색 범위·정상 경고율·원곡 재현율·새 임계값
- [Pixabay 출처 조사](PIXABAY_AI_AUDIT.md): 원본·정상후보·premusic 1,500개 파일의 곡별 AI 표시 확인
- [AI 전용 평가 범위](AI_ONLY_SCOPE.md): 사람의 연주·편곡 자료를 제외한 현재 범위와 데이터 출처 확인 과제
- [최신 후속 개선 결과](MENTORING_REVISION_20261022.md): 정상 경고 감소·독립 연주 검색·추가 분리 점검과 남은 한계
- [실제 팀 서비스 연결 검토본](TEAM_INTEGRATION_REVIEW_20261022.md): React·인증·Prisma·MySQL 변경과 검증 범위
- [현재 실행 현황](MENTORING_EXECUTION_20261022.md): 전체 평가 진행·독립 연주 파일럿·실제 화면과 DB 시험
- [현재 상태 정리](STATUS_SUMMARY_20261022.md): 2026-10-22 대조곡 17개 교체, 합성 양성 340개, 검증 결과와 남은 일
- MENTORING_GUIDE.md: 목표, 구조, 기술, 데이터, 수치, 한계, 다음 단계와 멘토링 질문
- layer1/README.md: 업로드 지문 검사 API
- layer2/README.md: Layer 2 코드 파일별 역할
- layer2/test_data/README.md: 평가용 양성·정상 대조 데이터
- layer2/artifacts/README.md: 결과와 캐시 파일

## 폴더 지도

| 위치 | 보관 내용 |
|---|---|
| layer1/ | Chromaprint DB와 업로드 API |
| layer2/ | CLAP·Chroma 코드, 시험 자료와 결과 (CoverHunter는 제외한 실험 보관분) |
| layer2/test_data/ | 합성 쿼리 및 출처 manifest |
| layer2/artifacts/ | 평가 JSON/CSV, 임베딩과 캐시 |
| original_music/ | 기준 원본 음원 1,000곡 |
| music/ | 정상 대조 후보 음원 300곡 |
| premusic/ | 아직 평가에 사용하지 않은 premusic 41곡 |
| premusic_used/ | 사용한 premusic 원본 81곡, 용도·이전 경로·SHA-256 대응표 |
| segments/ | 10초·5초 간격 분할 파일 15,699개 |
| .vscode/ | IDE 설정 |
| fpcalc.exe | Chromaprint 실행 파일 |

오디오·모델·임베딩 캐시는 다시 만드는 데 시간이 걸려 보존합니다. Python 바이트코드만 정리하고 .gitignore로 재생성을 무시하도록 했습니다.
# 먼저 읽을 문서

프로젝트 폴더별 역할과 실행 순서는 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)를
먼저 확인하세요.
