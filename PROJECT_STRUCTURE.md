# Track-AI 프로젝트 구조

이 문서는 처음 프로젝트를 여는 사람이 **어떤 폴더를 실행하고, 어떤 자료를 보존하며,
무엇을 무시해도 되는지** 바로 알 수 있도록 정리한 안내서입니다.

## 현재 운영 경로

| 경로 | 역할 | 주요 파일 |
|---|---|---|
| `api/` | AI 검증 FastAPI 서버 | `server.py`, `engine.py`, `schemas.py` |
| `backend/` | Node/Express 업로드 API와 SQLite 저장 | `src/server.ts`, `src/track-ai-client.ts`, `test/e2e.ts` |
| `layer1/` | Chromaprint 기반 완전 중복 차단 | `upload_guard_api.py`, `fingerprints_db.json` |
| `layer2/` | CLAP 후보 검색 및 연속성·Top-3 평가 | `evaluate_retrieval_baseline.py`, `chroma_comparator.py`, `evaluate_chroma_dtw_rerank.py` |
| `original_music/` | Layer 2 검색 기준 원본 음원 | 원본 데이터, 삭제하지 않음 |
| `music/` | 정상 대조 음원 | 평가용 데이터, 삭제하지 않음 |
| `segments/` | 10초 길이·5초 간격 분할 결과 | 재생성 가능하지만 평가에 사용 |
| `layer2/test_data/` | 양성·정상 대조군 manifest | 테스트 구성과 매핑 기록 |
| `review_handoff/` | 최종 검수 CSV와 전처리 자료 | 멘토링·팀 공유용 |

## 문서와 설정

- `README.md`: 프로젝트 전체 개요
- `MENTORING_GUIDE.md`: 지금까지의 모델·수치·한계·멘토링 질문
- `GITHUB_UPLOAD_GUIDE.md`: 공유 GitHub에 올릴 파일과 실행 순서
- `api/README.md`, `backend/README.md`, `layer1/README.md`, `layer2/README.md`: 각 모듈 설명
- `.env`: 로컬 FastAPI↔Node 내부 API 키. **Git에 올리지 않음**
- `.env.example`: 팀원이 복사해서 사용할 환경 변수 템플릿

## 실행 순서

1. `layer1/upload_guard_api.py`로 동일 음원 여부를 먼저 확인합니다.
2. Node 백엔드가 `api/server.py`의 `/verify`를 호출합니다.
3. FastAPI가 Layer 2 CLAP으로 후보를 찾고 Top-3 결과와 PASS/WARN/HOLD를 반환합니다.
4. Node가 결과를 SQLite에 저장합니다.

FastAPI와 Node 사이에는 `X-Internal-API-Key` 인증을 사용합니다. 두 프로세스가 같은
`.env`의 `TRACK_AI_API_KEY`를 읽어야 합니다.

## Layer 2의 현재 범위

- 운영 후보 검색은 `seg_top3_centered-v1` CLAP 경로입니다.
- CoverHunter와 예전 MetricHead 학습 코드는 운영 경로에서 제외했습니다.
- CLAP 점수는 표절 확률이 아니라 후보 검색 신호이므로, 결과는 자동 법적 판정이 아닌
  `PASS/WARN/HOLD` 위험 신호로 사용합니다.
- 실제 서비스 품질을 높이려면 재연주·편곡 양성 데이터와 장르·템포가 비슷한 정상곡을
  추가하고, 독립 테스트셋으로 임계값을 다시 보정해야 합니다.

## `_archive/`

현재 운영에서 사용하지 않는 구버전 코드, CoverHunter 실험 파일, 캐시, 상세 CSV를
되돌릴 수 있게 보관한 폴더입니다. 운영 코드와 혼동하지 마세요.
