# Layer 2 평가 산출물

`artifacts/`에는 재현에 도움이 되는 요약 JSON과 CLAP 임베딩 캐시만 남깁니다. 상세 CSV와 실험 캐시는 `_archive/layer2/artifacts/`로 이동했습니다.

| 파일 | 내용 |
|---|---|
| `layer2_operating_policy.json` | Top-3 후보와 PASS/WARN/HOLD 운영 정책 |
| `retrieval_baseline_report.json` | CLAP 기준선과 정상곡 오탐 분석 요약 |
| `positive_source_rank_summary.json` | 양성곡 원곡 Recall@K 요약 |
| `top3_aggregation_evaluation.json` | Top-3 집계 평가 요약 |
| `top3_aggregation_evaluation_pre_instrument_overlay.json` | 보정 전 평가 요약 |
| `chroma_evaluation_summary.json` | 크로마 분리 평가 요약 |
| `chroma_dtw_rerank_summary.json` | CLAP 후보의 크로마·DTW 재정렬 요약 |
| `clap_embeddings.npz` | 평가에 사용한 CLAP 임베딩 캐시 |
| `README.md` | 이 폴더의 산출물 안내 |

운영 API는 `api/engine.py`의 `seg_top3_centered-v1` 경로를 사용합니다. CoverHunter
실험 자료는 현재 운영에서 제외되어 `_archive/`에 보관되어 있습니다.
