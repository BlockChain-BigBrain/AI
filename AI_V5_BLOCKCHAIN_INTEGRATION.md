# AI v5 블록체인 연동

이 브랜치는 AI 저장소 `origin/main` 최신 커밋(`0b384b7`)에서 분기했습니다. 저장소의 `main`은 변경하지 않았습니다.

## 동일하게 고정할 값

```text
scoreVersion          = hybrid_query_top3_pairwise_hold-v5
decisionPolicyVersion = track-ai-balanced-policy-v5-20261102
modelVersion          = laion/clap-htsat-unfused
WARN                  = queryVerifierScore >= 0.351229127861893
HOLD                  = similarityScore >= 0.9471999941293027
```

`BLOCK`은 Layer 1 Chromaprint exact duplicate일 때 사용합니다. `WARN`은 query-level top-3 verifier 결과이고, `HOLD`는 pairwise temporal score 결과이므로 두 임계값은 같은 점수 구간에서 나온 값이 아닙니다. 두 조건이 모두 충족되지 않으면 `PASS`입니다.

## 온체인 기록 규칙

증거 기록에는 `trackId`, `audioHash`, `manifestHash`, `scoreVersion`, `decisionPolicyVersion`, `modelVersion`, `thresholds`, `similarityScore`, `queryVerifierScore`, `isHold`, `provisional` 및 evidence CID를 포함합니다. 정책 버전·모델 버전·임계값이 요청과 다르면 서명을 거부하고, `BLOCK`에는 등록/민팅 서명을 발행하지 않습니다.

`HOLD`는 `isHold=true`인 보류 상태이며 자동 소유권 확정이 아닙니다. 최종 권리 판단과 정산은 기존 검토 정책을 따릅니다.

## 검증 성능 참고

현재 잠금 결과는 AI positive recall 91.1%, 전체 safe FPR 10.5%, strict HOLD FPR 2.6%입니다. 300곡 정상 대조군에서는 PASS 242, WARN 55, HOLD 3, BLOCK 0(오류 0)이었습니다.
