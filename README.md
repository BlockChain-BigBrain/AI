# Track-AI 프로젝트 안내

음원 파일의 완전 중복을 찾아 업로드를 거절하는 Layer 1과, 유사 음원을 검색해 검토를 돕는 Layer 2를 개발합니다.

## 먼저 읽을 문서

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
| original_music/ | 기준 원본 음원 295곡 |
| music/ | 정상 대조 후보 음원 300곡 |
| segments/ | 10초·5초 간격 분할 파일 15,699개 |
| .vscode/ | IDE 설정 |
| fpcalc.exe | Chromaprint 실행 파일 |

오디오·모델·임베딩 캐시는 다시 만드는 데 시간이 걸려 보존합니다. Python 바이트코드만 정리하고 .gitignore로 재생성을 무시하도록 했습니다.
