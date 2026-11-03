# Track-AI 연동 계약

## 공통 버전

- `scoreVersion`: `hybrid_query_top3_pairwise_hold-v5`
- `decisionPolicyVersion`: `track-ai-balanced-policy-v5-20261102`
- WARN threshold: `0.351229127861893`
- HOLD threshold: `0.9471999941293027`

세 계층은 위 값을 임의로 재계산하거나 변경하지 않는다. 정책을 바꾸면 새 버전 문자열을 발급하고, 이전 결과를 소급 변경하지 않는다.

## AI 모델 요약

Layer 1은 Chromaprint 정확 중복을 BLOCK한다. Layer 2는 10초 창·5초 stride CLAP 후보 검색 후 pitch, rhythm, chroma, 시간 순서, 연속 정렬 길이, coverage, pitch-shift 일관성, tempo-ratio 일관성을 계산한다. pairwise temporal verifier가 원곡-검사곡 관계를 평가하고, top-3 후보의 joint evidence를 query-level verifier가 재평가한다.

## 최종 운영 결과

AI 변형 평가:

- Positive recall: 91.1%
- 안전 오탐률: 10.5%
- 엄격 HOLD 오탐률: 2.6%

고정 정상 대조군 300곡:

- PASS 242, WARN 55, HOLD 3, BLOCK 0
- WARN 이상: 58/300 = 19.33%
- HOLD 이상: 3/300 = 1.00%
- 처리 오류: 0

정상 음악의 WARN 중첩 때문에 WARN은 침해 확정이 아닌 검토 후보로만 사용한다. HOLD는 증거 구간과 원본 확인을 거쳐 최종 판단한다.

## 백엔드 계약

백엔드는 AI 응답의 `scoreVersion`, `decisionPolicyVersion`, `similarityScore`, `queryVerifierScore`, 후보 구간, 모델 버전, threshold 버전을 저장한다. AI 실패를 PASS로 우회하지 않으며, HOLD는 보류 상태로 저장한다.

## 프론트엔드 계약

프론트엔드는 권리 확인 전 업로드를 막고, 백엔드 정책 버전을 그대로 표시한다. 프론트엔드에서 점수나 threshold를 재계산하지 않는다. WARN/HOLD/BLOCK의 의미를 정책 정의와 동일하게 표시한다.

## 블록체인 계약

블록체인은 점수만 기록하지 않고 모델·정책·threshold 버전과 evidence CID를 함께 기록한다. HOLD는 `isHold=true` 검토 상태로 남기며 자동 소유권 확정으로 해석하지 않는다. 정책 버전 불일치와 `InvalidSignature`는 거래 검증 단계에서 거부한다.
