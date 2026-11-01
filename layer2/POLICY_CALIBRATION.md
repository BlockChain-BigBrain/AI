# HOLD/WARN 정책 보정

## 적용 규칙

- HOLD는 비중첩 10초 구간 중 기본 2개 이상이 HOLD 점수이고, 보조 corroboration 조건을 만족할 때만 확정한다.
- WARN은 2개 이상 구간이 WARN이면 확정 WARN이다.
- WARN 구간이 1개이면 공개 결정은 WARN으로 유지하되 reviewState=RECHECK로 표시해 즉시 최종 WARN으로 집계하지 않는다.
- 장르·템포·반복 패턴 보정값은 reference corpus에서 계산하며, 잠금 평가 세트에서는 재추정하지 않는다.
- 임계값은 동결하고, layer2/calibrate_policy.py는 tune split에서 집계 규칙 후보만 선택한다.
- 최종 test split에서 Wilson 95% 상한을 계산하며, 결과가 목표를 충족하기 전에는 운영 정책을 변경하지 않는다.

## 실행

python layer2/evaluate_top3_aggregation.py
python layer2/calibrate_policy.py

policy_calibration_candidate.json은 후보 결과일 뿐이며 runtimeChangeAuthorized=false를 유지한다.

## 운영 매핑

- PASS: 등록 가능
- WARN + CONFIRMED: 등록 가능, 위험 고지
- WARN + RECHECK: 재검증 큐
- HOLD + CONFIRMED: 등록은 가능하지만 Marketplace 구매 차단
- BLOCK: AI exact duplicate 또는 정책상 자동 차단

현재 runtime은 Chroma/CQT·pitch·rhythm 독립 특징을 아직 직접 산출하지 않으므로, 그 feature vote가 제공되기 전까지는 비중첩 시간 구간 일치를 corroboration으로 사용한다. 독립 특징을 연결하면 classify_segments(..., corroborating_scores=...)에 보조 점수를 전달하고 동일한 잠금 평가 절차를 다시 실행해야 한다.