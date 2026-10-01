# Layer 2 평가 산출물

JSON은 요약, CSV는 쿼리별 상세 결과입니다. NPZ 임베딩과 캐시는 다시 만들 수 있지만 음원 처리와 모델 추론이 필요하므로 보존합니다.

## 주요 결과 파일

| 파일 | 설명 |
|---|---|
| layer2_operating_policy.json | 내부 Top-5/표시 Top-3 및 데모 임계값 제안 |
| top3_aggregation_evaluation.json | 집계·임계값 그룹 평가 요약 |
| top3_aggregation_details.csv | 여섯 점수 집계의 쿼리별 결과 |
| top3_aggregation_evaluation_pre_instrument_overlay.json | 악기 레이어 양성 추가 전 결과 |
| top3_aggregation_details_pre_instrument_overlay.csv | 이전 평가 상세 |
| retrieval_baseline_report.json | CLAP 원시 기준선과 threshold 문제 |
| retrieval_baseline_details.csv | 기준선 상세 결과 |
| retrieval_continuity_candidates.csv | 연속 구간 후보 순위 |
| positive_source_rank_summary.json | 90 합성 양성의 원곡 Recall@K |
| positive_source_ranks.csv | 양성 쿼리별 원곡 순위 |
| false_positive_diagnostics.csv | 원시 점수에 걸린 정상 쿼리와 후보 구간 |
| chroma_evaluation_summary.json 및 chroma_evaluation_results.csv | 크로마 분포/AUC와 상세 |
| chroma_dtw_rerank_summary.json | CLAP Top-5/20 + DTW 요약 |
| chroma_dtw_rerank_details.csv | DTW 쿼리별 상세 |
| chroma_dtw_rerank_candidates.csv | DTW 평가 후보 목록 |
| music_duplicate_report.csv | music와 original_music 중복 검사 |
| segment_manifest.csv | 분할 조각과 원본/시작 시간 매핑 |

## CoverHunter 결과

| 위치 | 내용 |
|---|---|
| coverhunter_evaluation/ | 짧은 합성 양성 90개 |
| coverhunter_full_track_synthetic_evaluation/ | 긴 합성 쿼리 30개 |
| coverhunter_clap_hybrid/ | CLAP 후보와 CoverHunter 순위 비교 |
| coverhunter_control_scores/ | 양성 및 라벨 미검증 정상 대조 분포 |
| coverhunter_reference_index.npz | 295곡 참조 임베딩 인덱스 |
| coverhunter_cache/ | CoverHunter 오디오 임베딩 캐시 |

## 재사용 임베딩 캐시

- clap_embeddings.npz: CLAP 임베딩
- evaluation_embedding_cache/: 기준선 평가 임베딩
- chroma_feature_cache/: 크로마 계산 캐시

