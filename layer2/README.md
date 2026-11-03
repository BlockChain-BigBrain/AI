# Layer 2 코드 안내

Layer 2는 CLAP으로 유사 기준 음원을 검색하고 CoverHunter·크로마를 재정렬에 활용할 수 있는지 평가합니다. 결과는 법률상 표절 판정이나 표절 확률이 아닙니다.

## 검색 및 평가

| 파일 | 역할 |
|---|---|
| evaluate_retrieval_baseline.py | CLAP 임베딩, 기준선 검색과 평가 |
| evaluate_top3_aggregation.py | 집계 방식 비교, 그룹 분리 임계값 평가 |
| rank_positive_retrieval.py | 양성 원곡 순위와 Recall@K |
| coverhunter_csi.py | CoverHunter 추론·캐시·기준 인덱스·검색 |
| evaluate_coverhunter_csi.py | CoverHunter 단독 Recall@K/MRR |
| evaluate_coverhunter_clap_hybrid.py | CLAP 후보와 CoverHunter 재정렬 비교 |
| evaluate_coverhunter_controls.py | 양성/미검증 정상 점수 분포 |
| chroma_comparator.py | 크로마 구간 비교 |
| evaluate_chroma_separation.py | 크로마 분포와 AUC |
| evaluate_chroma_dtw_rerank.py | CLAP 후보의 크로마/DTW 재정렬 |

## 데이터 준비 및 유틸리티

| 파일 | 역할 |
|---|---|
| make_plagiarism_samples.py | 동일 녹음 기반 합성 양성 쿼리 |
| make_arranged_positives.py | 10곡의 긴 자동 편집 변형. 인간 재연주 아님 |
| make_synthetic_layered_positives.py | 원곡에 합성 악기층을 추가한 양성 쿼리 |
| make_safe_arranged_controls.py | 라벨 미검증 정상 대조 후보 생성 |
| remove_duplicate_music.py | music/original_music 중복 리포트. --delete에서만 삭제 |
| music_cutter | 10초·5초 stride로 segments/ 분할 |
| music/_cutter | music_cutter를 부르는 호환 래퍼 |
| download_youtube_reverse | YouTube 재생목록 다운로드 |

확장자가 없는 파일도 Python 스크립트입니다. 과거 곡 ID 기반 MetricHead 코드는 legacy/train_layer2.py로 옮겨 현재 코드와 분리했습니다.

## 문서

| 파일 | 역할 |
|---|---|
| README.md | Layer 2 코드와 폴더 지도 |
| COVERHUNTER_README.md | CoverHunter 설치·검색·평가 방법 |
| LAYER2_REVIEW_AND_EXPERIMENTS.md | 실험 결과 요약 |
| LAYER2_DECISION_POLICY.md | Top-K 및 데모 임계값 정책 제안 |
| artifacts/README.md | 결과·캐시 파일별 설명 |
| test_data/README.md | 시험 데이터 의미와 라벨 한계 |

## 하위 폴더

- test_data/: 쿼리 오디오와 원본·변형 manifest
- artifacts/: 요약 JSON, 상세 CSV, 인덱스와 재사용 캐시
- .vendor/: CoverHunter 공식 코드, SHS100k 가중치와 격리 의존성
- legacy/: 현재 검색 흐름에서 사용하지 않는 이전 학습 코드
- music/: _cutter 호환 실행기만 보관. 실제 음악은 저장소 루트 music/입니다.

전체 구조·주요 수치·멘토링 질문은 저장소 루트 MENTORING_GUIDE.md를 보세요.


## 문서

| 파일 | 역할 |
|---|---|
| COVERHUNTER_README.md | CoverHunter 설치·검색·평가 상세 |
| LAYER2_REVIEW_AND_EXPERIMENTS.md | 핵심 실험 수치 요약 |
| LAYER2_DECISION_POLICY.md | Top-K·데모 위험 임계값 제안 |
| artifacts/README.md | 평가 결과·캐시 파일 지도 |
| test_data/README.md | 시험 데이터 구성과 라벨 한계 |

전체 설명과 멘토링 질문은 저장소 루트 MENTORING_GUIDE.md를 보세요.
