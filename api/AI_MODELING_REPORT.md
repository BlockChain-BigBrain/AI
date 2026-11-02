# AI 중심 모델링 평가

## 시간 일관성

`pitch-rhythm-chroma-temporal-v3`는 기존 평균 점수에 다음을 추가한다.

- 매칭 구간 수와 곡 내 커버리지
- query/reference 시간 순서 보존률
- 가장 긴 연속 정렬 길이
- 구간별 pitch shift 일관성
- 구간 간 tempo ratio 중앙값과 일관성

이 특징들은 `pairwise_temporal-v3` 검증기에 입력된다. CLAP은 후보 검색에만 사용하고, 최종 후보 점수는 자동 provenance 양성/대조군으로 학습한 pairwise 검증기가 계산한다.

## 자동 라벨 평가

원본 ID, 변형 종류, seed, 파라미터가 매니페스트에 있는 AI 합성 데이터만 사용했다. 소스 그룹을 분리한 60/40 split에서 pairwise AUC는 0.961이다. 고재현율 운용점은 홀드아웃 양성 90.8%, 정상 대조군 오탐 55.3%이고, 고정밀도 HOLD 운용점은 양성 66.2%, 정상 대조군 오탐 2.1%다.

## 변형·생성 방식 홀드아웃

현재 manifest에는 실제 `generator_id`가 없으므로 변형 방식을 generator-family의 대리 단위로 사용했다. 한 family를 통째로 제외하고 나머지 family로 학습한 결과는 `generator_holdout_report.json`에 기록한다. 멜로디 유지 음색 재생성, 구조 유지 보컬 교체 데이터는 현재 존재하지 않으므로 추정하지 않고 미제공으로 표시한다.

## Diverse tempo/pitch augmentation

24개 원본에서 coupled speed/pitch, tempo-only, pitch-only를 336개 생성했다.
원본 곡 기준 분할은 train 17곡/238변형, validation 5곡/70변형, test 2곡/28변형이다.
train-only acoustic verifier의 validation 고재현율 지점은 양성 90.0%, 음성 오탐 55.7%였고,
완전히 보지 않은 test에서는 양성 57.1%, 음성 오탐 32.1%였다. 고정밀도 지점은
validation 양성 25.7%·오탐 4.3%, test 양성 14.3%·오탐 7.1%였다.
이 결과는 pitch/rhythm/chroma만으로는 tempo/pitch 변형을 충분히 분리하지 못한다는
진단이며, 운영 경로에서는 CLAP 검색 뒤 시간 일관성을 포함한 pairwise verifier를 함께
사용해야 한다. test 원본이 2곡이므로 이 수치는 최종 일반화 주장보다 augmentation
파이프라인 점검용으로 취급한다.

## premusic 분할

기존 413곡과 정확 중복 3곡을 제외한 남은 782곡을 train 469, validation 157, test 156으로 고정했다. 분할 파일은 `premusic_remaining_split.json`이다. 원본 premusic 파일은 삭제하거나 이동하지 않았다.
## Minimal premusic hard-negative audit and challenger retraining

Only 30 non-duplicate premusic tracks were consumed from the 782-track reserve: 12 train hard negatives, 8 validation controls, and 10 final test controls. All 752 unused tracks remain in `premusic/`.

The 12 train tracks were added to a challenger pairwise verifier; validation and test premusic tracks were never used for fitting. Challenger results are in `runtime/pairwise_with_premusic.json`:

- AI test recall operating point: 90.8% positive recall, 52.6% safe false-positive rate (old policy: 90.8%, 55.3%).
- AI test precision operating point: 75.4% positive recall, 5.3% safe false-positive rate (old policy: 66.2%, 2.1%).
- Premusic test controls still produce 4/10 WARN and 0/10 HOLD.

The first challenger was not deployed because it did not improve held-out premusic WARN. After the additional train-only hard-negative expansion below, the improved challenger is used for WARN calibration while the locked precision/HOLD threshold remains unchanged.

### Hard-negative expansion

An additional 24 train-split premusic tracks were screened with the deployed verifier. Ten observed WARN/HOLD cases (30 candidate pairs) were added to challenger fitting; validation and test tracks remained untouched. The expanded challenger reached 93.8% AI-test positive recall and about 49.1% safe false-positive rate at its WARN operating point, versus 90.8% and 55.3% for the previous policy. Runtime now uses this challenger for WARN calibration while preserving the original locked HOLD threshold.

## Query-level nonlinear hybrid (current runtime)

The remaining false positives were traced to the pairwise `max(top3)` decision: one accidental high candidate was sufficient to trigger WARN. A query-level verifier was therefore trained on the joint top-3 evidence (96 dimensions: candidate features, means, spreads, and inter-candidate gaps). Logistic, random forest, Extra Trees, and histogram gradient boosting were compared using a grouped 50/25/25 train/validation/test protocol. Model and thresholds were chosen on validation only; test was opened once.

Extra Trees was selected. Combined with the locked pairwise HOLD rule, the untouched test result is:

- Balanced positive detection recall: 91.1%.
- Balanced overall safe false-positive rate: 10.5%.
- Premusic held-out test false positives: 1/10 WARN, 0/10 HOLD.
- Strict HOLD positive recall: 55.4%.
- Strict HOLD safe false-positive rate: 2.6%.

This hybrid is the current runtime policy (`hybrid_query_top3_pairwise_hold-v5`). WARN uses the balanced query-level operating point selected at 100% validation recall; HOLD uses the conservative pairwise score and locked threshold. A precision-oriented operating point is also retained in the evaluation artifact (89.3% test recall, 2.6% safe false-positive rate). The deployed balanced point preserves greater than 90% AI recall while removing most isolated-candidate false alarms without training on validation or test controls.

Error analysis found five missed positives. Three of the five did not contain the true source in retrieval top-3, so no downstream verifier could recover them; the remaining two were verifier misses. The residual ceiling is therefore primarily retrieval under strong tempo/pitch, section-edit, and remix transformations rather than normal-control calibration. Four safe false positives remain in the combined test (three AI-dataset controls and one premusic control), with only one reaching HOLD.

## 300-track premusic lock audit

The current `premusic` directory was re-hashed before evaluation. Of 399 files, 104 exact duplicates were removed: internal duplicate copies or files already present in `premusic_used`/`original_music`. This left 295 unique unused files. Five additional never-evaluated files were taken from the prior unused pool to form a fixed 300-track audit set. Evaluation is resumable and writes per-track checkpoints to `runtime/premusic_lock300_part*.jsonl`; the final summary is written only when all 300 tracks are complete.

### Final lock300 result

The audit completed with 300/300 valid rows and zero processing errors. Results are fixed in `runtime/premusic_lock300_summary.json`:

- PASS 242, WARN 55, HOLD 3, BLOCK 0.
- WARN-or-higher: 58/300 = 19.33% (Wilson 95% CI 15.26–24.18%).
- HOLD-or-BLOCK: 3/300 = 1.00% (Wilson 95% CI 0.34–2.90%).
- The denominator excludes no rows because `errorCount=0`.

This is a normal-control false-positive audit, not an AI-positive recall measurement. It demonstrates that the strict HOLD gate is selective, while the broader WARN gate still overlaps with musically similar normal tracks. The meeting explanation and Layer 2 implementation details are in `MEETING_EXPLANATION.md` and `MEETING_LAYER2_DETAIL.md`.
