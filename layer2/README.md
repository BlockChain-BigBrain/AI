# Layer 2

Layer 2는 CLAP 임베딩으로 음악 후보를 검색하고, 연속 구간 점수와 Top-3 집계로 유사 위험 신호를 계산합니다. 법적 표절 확률을 직접 출력하는 모델이 아닙니다.

## 운영·평가 코드

| 파일 | 역할 |
|---|---|
| `evaluate_retrieval_baseline.py` | CLAP 후보 검색 기준선 평가 |
| `rank_positive_retrieval.py` | 양성곡의 원곡 Recall@K 계산 |
| `chroma_comparator.py` | 크로마그램 기반 구간 유사도 계산 |
| `evaluate_chroma_dtw_rerank.py` | CLAP 후보를 크로마·DTW로 재정렬 |
| `evaluate_top3_aggregation.py` | Top-3 집계 방식 평가 |
| `make_plagiarism_samples.py` | 변형 양성 사례 생성 |
| `make_arranged_positives.py` | 편곡형 평가 사례 생성 |
| `make_safe_arranged_controls.py` | 정상 편집 대조군 생성 |
| `make_synthetic_layered_positives.py` | 합성 변형 사례 생성 |
| `remove_duplicate_music.py` | `music/`과 `original_music/` 중복 점검 |
| `music_cutter` | 10초 창, 5초 stride 분할 |
| `download_youtube_reverse` | 테스트 음원 수집용 다운로드 스크립트 |

## 자료 폴더

- `test_data/`: 양성·정상 대조군 manifest
- `artifacts/`: 요약 평가 JSON과 운영 정책
- `music/`: 정상 대조 음원
- `../original_music/`: 검색 기준 원본 음원
- `../segments/`: 분할된 세그먼트

상세 CSV와 계산 캐시는 `_archive/`로 이동했습니다. 운영에 필요한 요약 리포트만 `artifacts/`에 남겨 두었습니다.
