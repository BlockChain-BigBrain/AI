# Track-AI 멘토링 정리

기준일: 2026-10-01

처음 보는 멘토가 이 문서만 읽어도 프로젝트 목표, 사용 기술, 현재 결과와 한계를 이해하도록 정리했습니다.

## 1. 한 문장 소개

Track-AI는 Layer 1에서 등록 음원과 오디오 지문이 정확히 겹치는 업로드를 거절하고, Layer 2에서 유사한 기준 음원을 찾아 사람이 추가 검토하도록 후보와 위험 정보를 제공하려는 시스템입니다. Layer 2 점수는 표절 확률이나 법률 판결이 아닙니다.

## 2. 목표와 구성

| 영역 | 목적 | 현재 상태 |
|---|---|---|
| Layer 1 | 이미 등록된 음원의 중복 업로드 방지 | 통합 FastAPI `/verify`에서 실제 지문 검사와 BLOCK 반환 확인 |
| Layer 2 | 음색·편집이 달라진 유사 음원 후보 검색 | 통합 FastAPI에서 전체곡 5초 간격 CLAP 분석, Top-3와 임시 등급 반환 확인 |
| 최종 표절 판정 | 법률상 표절 여부 결정 | 모델 단독 자동 판정 범위 밖. 사람의 검토 필요 |

현재 통합 흐름: Node가 `/verify`에 임시 파일 전송 → Layer 1 Chromaprint 지문 비교 → 정확 중복이면 BLOCK → 아니면 Layer 2가 10초 창·5초 간격으로 전체곡 분석 → CLAP Top-3와 PASS/WARN/HOLD 반환 → Node가 결과 저장. 검사는 기준 DB를 변경하지 않으며, 등록 승인된 곡의 기준 DB 추가는 별도 단계로 남겨두었습니다.

Layer 2 HOLD는 업로드 자체의 자동 거절과 구분합니다. Layer 2는 검토·정산 보류 같은 위험 처리 제안이고, 자동 업로드 거절은 Layer 1의 확인된 중복에 한정합니다.

## 3. 사용 기술

| 기술 | 역할 | 실제 사용 상태 |
|---|---|---|
| Chromaprint / fpcalc.exe | 오디오 지문 프레임 생성과 비교 | Layer 1 API에 사용 |
| FastAPI / Uvicorn | 비동기 분석 접수, 작업 조회, 결과 스키마 | 통합 API 실행과 Node/Express 호출까지 확인. 실제 팀 화면·MySQL에는 미연결 |
| LAION-CLAP | 오디오 구간 임베딩과 유사 후보 검색 | 사전학습 모델 사용. 이 프로젝트가 CLAP 본체를 다시 학습한 것은 아님 |
| CoverHunter SHS100k | 서로 다른 녹음의 같은 곡 검색 | 사전학습 모델의 로컬 CPU 평가 |
| Chroma / OTI / DTW | 음높이 패턴 비교와 시간축 재정렬 | 오프라인 보조 신호 실험 |
| NumPy / NPZ | 임베딩·인덱스 보관과 유사도 계산 | 현재 로컬 검색 방식 |
| Milvus | 벡터 검색 DB | 아직 연결하지 않음 |
| IPFS / EIP-712 / ERC-1155 / Polygon | 파일 증명·서명·온체인 구상 | 현재 코드에서 실제 통합 확인 안 됨 |

과거 코드 layer2/legacy/train_layer2.py는 곡 ID를 라벨로 MetricHead를 학습한 실험입니다. 현재 CLAP 검색 파이프라인에는 쓰지 않으며 표절 판정 모델의 학습도 아닙니다.

## 4. 데이터 현황

| 폴더 | 수량 | 의미 |
|---|---:|---|
| original_music/ | 295곡 | 기준 검색 라이브러리. CLAP 가중치 학습 데이터라는 뜻은 아님 |
| music/ | 300곡 | 미학습 정상 대조 후보 음원 |
| segments/ | 15,699개 | 10초 길이, 5초 stride로 자른 오디오 조각 |
| layer2/test_data/plagiarism_positive/ | 90개 | 같은 녹음을 발췌하거나 속도·피치·효과를 바꾼 합성 양성 |
| layer2/test_data/reperformed_positive/ | 30개 | 10개 출처에 3종 자동 편집. 사람이 재연주한 커버는 아님 |
| layer2/test_data/safe_arranged/ | 30개 | 정상 대조 후보. 전문가가 비표절을 판정한 확정 라벨은 아님 |
| layer2/test_data/synthetic_layered_positive/ | 10개 | 원곡 위에 합성 패드·베이스·퍼커션을 더한 인공 테스트 |

각 test_data 폴더의 manifest.csv가 쿼리와 원본/변형 유형을 연결합니다. 원곡 출처 단위로 튜닝과 홀드아웃을 나눠 동일 원본의 변형본이 양쪽에 섞이는 일을 줄였습니다.

Layer 1 지문 DB에는 검색 가능한 296건이 있습니다: original_music 295곡과 과거 music/test.mp3 한 건. 과거 music/track_01.wav는 6.67초라 최소 10초 검사 기준에 미달해 검색 인덱스에서 제외됐습니다.

## 5. 핵심 수치

### CLAP 후보 검색: Top-3와 Top-5

같은 원본에서 만든 합성 변형 쿼리 90개, 기준 라이브러리 295곡에서 원곡 검색 성공률:

| 후보 수 | 원곡 포함 | 비율 |
|---:|---:|---:|
| Top-1 | 70/90 | 77.8% |
| Top-3 | 80/90 | 88.9% |
| Top-5 | 85/90 | 94.4% |

내부 검색 후보는 Top-5, 검토 화면은 재정렬 후 Top-3를 권장합니다. Top-5는 Top-3보다 후보 두 곡이 더 필요하지만 원곡을 5건 더 포함했습니다. 이 수치는 합성 변형에서 원곡을 검색한 비율이지 실제 표절 검출률은 아닙니다.

### CLAP 원시 점수의 문제

기준선 양성 63개·정상 299개에서 원시 CLAP 코사인 점수 0.85 이상을 HOLD로 적용하면 정상 293/299개가 걸려 정상 오탐률 98.0%였습니다. 0.70 이상을 WARN으로 하면 정상 299/299개가 경고됐습니다. 코사인 점수를 표절 확률이나 백분율로 해석하면 안 됩니다.

### 구간 집계와 임계값

2026-09-30 실행한 evaluate_top3_aggregation.py는 기준곡 295개, 참조 창 9,847개, 양성 쿼리 73개, 일반 정상 쿼리 299개로 여섯 가지 점수 집계를 비교했습니다. 출처 그룹 기준 60% 튜닝·40% 홀드아웃으로 나눴습니다. 미검증 safe_arranged 30개는 임계값 적합에서 제외했습니다.

선택 점수는 seg_top3_centered입니다. 기준 임베딩 평균을 제거한 뒤 서로 겹치지 않는 강한 매칭 구간 최대 3개 점수를 평균합니다.

| 구간 | 점수 기준 | 홀드아웃 양성 검출 | 홀드아웃 정상 오탐 |
|---|---:|---:|---:|
| HOLD | >= 0.894406 | 25/32 = 78.1% | 6/119 = 5.04% |
| WARN 또는 HOLD | >= 0.856638 | 28/32 = 87.5% | 22/119 = 18.5% |

정상 HOLD 5% 이하와 양성 WARN 재현율 90% 목표를 동시에 충족하지 못했습니다. 양성 홀드아웃도 32개뿐입니다. 이 값은 해당 집계 방식의 데모 제안이지 제품 임계값이 아닙니다.

### Chroma / DTW

- 크로마 비교 양성 90·정상 59에서 AUC 0.856, Cohen’s d 1.449. 양성 중앙값 0.929, 정상 중앙값 0.873.
- 이 양성은 같은 녹음의 발췌·변형입니다. 정상 59곡은 CLAP Top-1 후보와 비교한 것이므로 법률 판정 데이터가 아닙니다.
- 63개 양성 DTW 실험에서 CLAP Top-5 안에 원곡이 든 비율은 60/63=95.2%, DTW 이후 Top-1은 52/63=82.5%, AUC는 0.849였습니다.
- Top-20은 원곡 후보 커버리지를 98.4%로 높였지만 재정렬 Top-1은 73.0%, Top-5는 82.5%로 낮아졌습니다. 후보를 늘리는 것만으로 성능이 좋아지지 않았습니다.

### CoverHunter

| 데이터 | 쿼리 | Top-1 | Top-3 | Top-5 |
|---|---:|---:|---:|---:|
| 짧은 합성 변형 | 90 | 68.9% | 77.8% | 80.0% |
| 긴 4분 합성 편집 | 30 | 80.0% | 86.7% | 86.7% |

긴 합성 세트에서 section edit와 remix FX는 각각 10/10 Top-5에 포함됐지만 tempo/pitch/EQ는 6/10이었습니다. CLAP 뒤 CoverHunter를 붙인 실험은 Top-1이 77.8%에서 80.0%로 조금 올랐고 Top-3는 88.9%에서 86.7%로 낮아졌습니다. 일관된 개선은 확인되지 않았습니다. 정상 대조 점수는 양성 점수와 많이 겹칩니다.

## 6. 파일별 역할

### Layer 1

| 파일 | 역할 |
|---|---|
| layer1/upload_guard_api.py | 지문 인덱스 생성, 중복 비교, 업로드 API |
| layer1/fingerprints_db.json | 검색 가능 지문 DB. 수동 편집 금지 |
| layer1/requirements-upload-guard.txt | FastAPI/Uvicorn/multipart 의존성 |
| layer1/UPLOAD_GUARD_README.md | API 설치·실행·요청 설명 |
| layer1/README.md | Layer 1 파일 및 실행 안내 |
| layer1/auto music expert | 과거 배치 추출 코드. 새 API 흐름에서는 사용하지 않음 |

### 통합 API

| 파일 | 역할 |
|---|---|
| api/server.py | `/health`, `POST /verify`, `GET /verify/{jobId}`와 SQLite 작업 상태 관리 |
| api/engine.py | Layer 1 읽기 전용 중복 검사와 Layer 2 `seg_top3_centered-v1` 실행 |
| api/schemas.py | OpenAPI에 노출되는 요청 결과 자료형과 상태값 고정 |
| api/node-client.mjs | Node 22 이상에서 파일 전송·결과 폴링을 수행하는 연결 예제 |
| api/README.md | 실행법, API 계약, Node 연결법, 저장해야 할 결과 필드 |

### Node 백엔드 MVP

| 파일 | 역할 |
|---|---|
| backend/src/server.ts | 브라우저 업로드 접수, AI 비동기 호출, 결과 조회 API와 로컬 SQLite 저장 |
| backend/src/track-ai-client.ts | FastAPI 작업 제출과 완료까지 폴링 |
| backend/test/e2e.ts | Node → FastAPI → 판정 → DB 저장 자동 확인 |
| backend/README.md | 두 서버 실행 순서와 요청 방법 |

2026-10-01 자동 E2E에서 기준 원본은 Node 업로드부터 DB 저장까지 `VERIFIED/BLOCK`으로 완료됐고 AI 처리시간은 0.253초였습니다. 13.2초 합성 변형은 Layer 2 Top-3와 함께 `VERIFIED/PASS`로 저장됐으며 AI 처리시간은 2.249초였습니다. 이 PASS는 연결 성공과 현재 결과의 재현을 뜻하며, 변형 양성 탐지에는 실패한 사례입니다. 두 작업 후 임시 업로드 파일은 0개였습니다. 두 시간은 짧은 시험 파일의 단일 실행값이라 3분 곡 운영 성능으로 일반화하지 않습니다.

### Layer 2

| 파일 | 역할 |
|---|---|
| evaluate_retrieval_baseline.py | CLAP 임베딩과 검색 기준선 평가 |
| evaluate_top3_aggregation.py | 6가지 집계와 임계값 튜닝/홀드아웃 평가 |
| rank_positive_retrieval.py | 합성 양성 원곡 순위와 Recall@K |
| coverhunter_csi.py | CoverHunter 추론·캐시·기준 인덱스·검색 |
| evaluate_coverhunter_csi.py | CoverHunter 단독 Recall@K/MRR |
| evaluate_coverhunter_clap_hybrid.py | CLAP 후보와 CoverHunter 재정렬 비교 |
| evaluate_coverhunter_controls.py | 양성/미검증 정상 점수 분포 |
| chroma_comparator.py | 크로마 비교 모듈 |
| evaluate_chroma_separation.py | 크로마 분포와 AUC |
| evaluate_chroma_dtw_rerank.py | CLAP 후보의 크로마/DTW 재정렬 |
| make_plagiarism_samples.py | 같은 녹음 기반 합성 양성 쿼리 생성 |
| make_arranged_positives.py | 10개 원본에 긴 자동 편집 변형 생성 |
| make_synthetic_layered_positives.py | 원곡 위 합성 악기 레이어 양성 생성 |
| make_safe_arranged_controls.py | 미검증 정상 대조 후보 생성 |
| remove_duplicate_music.py | music/original_music 지문 중복 보고. --delete일 때만 삭제 |
| music_cutter | 10초·5초 stride 오디오 분할 |
| music/_cutter | music_cutter 실행 래퍼 |
| download_youtube_reverse | YouTube 재생목록 수집 도구 |
| legacy/train_layer2.py | 곡 ID MetricHead 과거 학습 실험. 현재 미사용 |

확장자가 없는 music_cutter, download_youtube_reverse, music/_cutter도 Python 스크립트입니다. 기존 실행 경로를 깨지 않도록 파일명을 유지했습니다.

## 7. 폴더별 분류와 정리 원칙

- layer2/test_data/: 시험 음원과 출처/변형 manifest. 이름을 바꾸면 manifest도 갱신해야 합니다.
- layer2/artifacts/: JSON/CSV 결과, 검색 임베딩과 재사용 캐시. 재생성에 시간이 들어 보존했습니다.
- layer2/.vendor/: CoverHunter 소스, SHS100k 체크포인트와 격리 의존성. 삭제하지 않습니다.
- layer2/legacy/: 현재 경로에서 제외한 MetricHead 과거 학습 코드.
- layer2/music/: 구 경로 실행기만 있습니다.
- 저장소 루트 segments/: 15,699개 분할 오디오.
- 저장소 루트 .vscode/: IDE 설정.
- 저장소 루트 fpcalc.exe: Layer 1 실행 파일.
- 저장소 루트 PDF: 피칭덱.
- 자동 생성 Python 바이트코드 layer2/__pycache__는 삭제했고 .gitignore로 재생성을 무시합니다. 다른 모델/임베딩 캐시는 보존했습니다.

## 8. 남은 일의 우선순위

1. 현재 Node MVP의 SQLite 저장 부분을 팀의 실제 Prisma/MySQL 저장소로 교체하고 프론트 업로드 화면을 연결합니다.
2. 등록 승인된 곡만 지문·벡터 기준 DB에 추가하는 ingest API와 자기 곡 재검증 제외 규칙을 구현합니다.
3. 재인코딩·앞뒤 무음·부분 구간의 Layer 1 지문 매칭을 권리 확인된 샘플로 측정합니다. 지금은 지문 프레임 전체가 정확히 연속 일치하는 경우만 BLOCK입니다.
4. 독립 재연주/편곡 양성과 어려운 정상곡을 추가하고, 정상 WARN 오탐 18.5%와 양성 WARN 재현율 87.5%를 개선합니다.
5. 실제 3분 곡의 처리시간 중앙값·p95, 동시 업로드, 재시작·오류 처리를 측정합니다. Milvus/IPFS/블록체인은 실제로 연결한 뒤에만 완료로 표시합니다.

## 9. 멘토링 질문

1. Layer 1의 “정확 중복”은 파일 SHA-256 동일, Chromaprint 지문 동일, 재인코딩 허용 중 어디까지가 적절한가요?
2. 정상 음원 차단 비용과 중복 음원 통과 비용 중 어떤 것을 더 크게 평가해야 하나요?
3. 독립 편곡 검증에 필요한 출처 곡·연주자·변형 유형 수는 어느 정도인가요?
4. 멜로디는 다르지만 장르·템포가 유사한 정상 대조곡을 어떻게 검수·라벨링해야 하나요?
5. 후보 검색과 재정렬 성공 기준을 Recall@K, 오탐률, 지연시간 중 어떤 조합으로 정해야 하나요?
6. 현재 합성 데이터 결과와 실제 커버/표절 성능 주장을 발표에서 어떻게 분리해야 과장으로 보이지 않을까요?
7. Layer 2 WARN/HOLD 사용자 안내, 사람 검토, 이의제기 흐름을 어떤 식으로 설계해야 하나요?

## 10. 멘토링용 1분 소개

“Track-AI는 두 단계를 분리합니다. Layer 1은 Chromaprint 지문으로 등록 음원과 정확히 겹치는 업로드를 찾아 HTTP 409로 거절하는 독립 API를 만들었고 기준 원본 295곡의 지문 인덱스를 구축했습니다. Layer 2는 사전학습 CLAP으로 후보를 찾고 CoverHunter와 크로마/DTW를 평가했습니다. 합성 변형 쿼리 90개에서 CLAP 원곡 Top-5 포함률은 94.4%여서 내부 후보 Top-5, 검토 화면 Top-3를 권장합니다. 하지만 홀드아웃 WARN 이상 양성 검출률은 87.5%, 정상 오탐률은 18.5%이고 양성 대부분은 원본 녹음의 합성 편집입니다. 실제 사람이 재연주한 표절 판정 성능으로 주장하지 않습니다. 다음 단계는 Layer 1 API를 업로드 화면에 연결하고 독립 편곡과 어려운 정상 데이터로 Layer 2를 검증하는 것입니다.”
