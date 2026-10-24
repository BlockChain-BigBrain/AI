# 프론트엔드 전달 자료: Track-AI 음원 검증 결과

> 실제 팀 React·Prisma 연결은 [팀 서비스 연결 검토본](TEAM_INTEGRATION_REVIEW_20261022.md)을 우선 참고하세요. 로컬 작업 복사본에서 수정·시험했으며 원격 push는 하지 않았습니다.

> 최신 데이터는 정상대조후보 300곡·합성 양성 340개입니다. 변경 내역과 새 DB 재평가 상태는 [현재 상태 정리](STATUS_SUMMARY_20261022.md)를 우선 참고하세요.

프론트엔드에서 업로드 화면, 분석 중 상태, 결과 화면을 구현할 때 참고할 AI 계약과 화면 권장사항입니다. API 기준은 현재 `backend` Node API와 `api` FastAPI 구현입니다.

## 1. AI 레이어 이름과 역할

| 레이어 | 화면/문서 표기 | 실제 기술과 역할 |
|---|---|---|
| Layer 1 | **정확 음원 지문 중복 검사** | Chromaprint (`fpcalc`) 전체 지문을 비교합니다. 등록 음원과 완전한 지문 구간이 일치하면 `BLOCK` 처리합니다. |
| Layer 2 | **음악 유사 후보 분석** | LAION-CLAP (`laion/clap-htsat-unfused`) 오디오 임베딩을 사용합니다. 10초 오디오 구간을 5초 간격으로 비교하고, 비중복 Top-3 매칭을 집계해 유사 후보와 점수를 반환합니다. |

Layer 2는 법적 표절 여부나 표절 확률을 판정하지 않습니다. 결과는 **유사성 기반 검토 신호**입니다.

## 2. 업로드와 조회 API

브라우저는 Node API만 호출합니다. FastAPI 내부 API 키를 프론트엔드에 넣거나 브라우저에서 FastAPI를 직접 호출하면 안 됩니다.

### 업로드

`POST /api/tracks` — `multipart/form-data`, 필드 `file`

즉시 분석 결과가 오는 대신 `202 Accepted`와 작업 ID가 반환됩니다.

```json
{
  "trackId": "<track-id>",
  "state": "ANALYZING",
  "statusUrl": "/api/tracks/<track-id>"
}
```

### 결과 조회

`GET /api/tracks/{trackId}`를 조회합니다. 응답의 `state`가 `ANALYZING`인 동안 로딩 화면을 보여주고, `VERIFIED` 또는 `FAILED`가 될 때까지 주기적으로 다시 조회합니다.

`VERIFIED` 예시:

```json
{
  "id": "<track-id>",
  "originalName": "my-track.mp3",
  "state": "VERIFIED",
  "decision": "WARN",
  "audioHash": "<sha256>",
  "similarityScore": 0.872,
  "aiJobId": "<ai-job-id>",
  "result": {
    "decision": "WARN",
    "decisionReason": "SIMILARITY_WARNING",
    "disposition": "HUMAN_REVIEW",
    "reviewRequired": true,
    "duplicate": { "detected": false, "matchedTrackId": null },
    "similarityScore": 0.872,
    "thresholds": { "warn": 0.856638, "hold": 0.894406 },
    "provisional": true,
    "similarTracks": [
      {
        "trackId": "<candidate-track-id>",
        "score": 0.872,
        "matchedSegments": [
          {
            "queryStartSec": 35.0,
            "queryEndSec": 45.0,
            "refStartSec": 10.0,
            "refEndSec": 20.0,
            "score": 0.901
          }
        ]
      }
    ],
    "queryWindowCount": 35,
    "durationSeconds": 180.0,
    "processingSeconds": 8.42,
    "modelVersion": "laion/clap-htsat-unfused",
    "scoreVersion": "seg_top3_centered-v1",
    "corpusVersion": "<corpus-hash>",
    "decisionPolicyVersion": "layer2-risk-v1",
    "audioHash": "<sha256>"
  },
  "review": null,
  "provenance": null,
  "error": null,
  "createdAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

필드값은 응답 예시입니다. 실제 후보 수는 최대 3개이며, `matchedSegments`는 후보별로 최대 3개의 매칭 구간을 담습니다.

## 3. 판정값과 UI 표현

| 값 | 의미 | 권장 UI |
|---|---|---|
| `BLOCK` | Layer 1에서 등록 음원과 정확한 지문 일치 | 빨간 상태. “등록된 음원과 동일한 지문이 확인되어 자동 차단되었습니다.” 일치 후보의 제목/등록 정보는 백엔드가 제공하는 경우에만 표시합니다. |
| `HOLD` | Layer 2 점수가 HOLD 기준 이상 | 진한 주의 상태. “유사도가 높아 사람의 확인이 필요합니다.” `reviewRequired: true`를 반영합니다. |
| `WARN` | Layer 2 점수가 WARN 기준 이상, HOLD 미만 | 노란 상태. “유사 후보가 확인되어 검토가 필요합니다.” Top-3 후보와 매칭 구간을 보여줍니다. |
| `PASS` | Layer 2 점수가 WARN 기준 미만 | 통과 상태. “현재 기준에서 높은 유사 후보가 확인되지 않았습니다.” 저작권 안전 또는 독창성을 보증하는 뜻은 아닙니다. |

`decisionReason`, `disposition`, `reviewRequired`를 활용해 화면 상태를 보조할 수 있습니다. `HOLD`와 `WARN`은 자동 차단이 아니라 검토 상태입니다. `BLOCK`만 Layer 1의 정확 지문 중복 차단입니다.

## 4. 점수와 임계값 표시 주의

- 현재 Layer 2 점수는 `seg_top3_centered-v1`의 **코사인 기반 검색 집계 점수**입니다. 표절 확률(%)이 아닙니다. `0.872`를 “표절 확률 87.2%” 또는 “87.2% 동일”로 표시하지 마세요.
- 코드가 읽는 현재 잠정 기준은 `WARN >= 0.856638`, `HOLD >= 0.894406`, 그 미만은 `PASS`입니다. 응답의 `thresholds`를 사용하고 임계값을 프론트엔드 코드에 별도 하드코딩하지 마세요.
- `provisional: true`이면 “실험용 기준” 또는 “검토 기준(잠정)”을 표시하세요. 서비스 최종 기준처럼 표현하지 마세요.
- 후보 `score`와 전체 `similarityScore`는 0~1 범위의 유사도 지표입니다. UI에서는 원점수와 설명 문구를 함께 보여주고, 퍼센트 확률처럼 시각화하지 않는 편이 안전합니다.

## 5. 결과 화면 권장 구성

1. **상단 상태 배지:** `BLOCK / HOLD / WARN / PASS`, 업로드 분석 상태, 검토 필요 여부.
2. **요약:** Layer 1 정확 지문 결과, Layer 2 유사도 결과, 잠정 기준 안내.
3. **유사 후보 최대 3개:** 후보 제목(서버에서 실제 제목을 제공할 때), 후보 점수, 일치 구간.
4. **구간 비교:** 업로드 음원의 `queryStartSec–queryEndSec`와 기준 음원의 `refStartSec–refEndSec`를 타임라인에 표시. 예: “업로드 00:35–00:45 ↔ 후보 00:10–00:20”.
5. **검토/이의제기 동선:** `HOLD`·`WARN`이면 검토 대기 상태를 보여줍니다. `review`가 null이면 아직 검토 기록이 없습니다.
6. **기술 정보(상세/접기):** `modelVersion`, `scoreVersion`, `corpusVersion`, `durationSeconds`, `processingSeconds`, `audioHash`.

현재 후보에는 `trackId`만 있으므로, 사람이 읽을 제목·아티스트·작품 페이지를 보여주려면 Node 백엔드가 그 ID를 메타데이터와 연결해 응답해야 합니다. UI에서 ID를 제목처럼 노출하지 마세요.

## 6. 상태와 오류 처리

| 상태/오류 | 처리 |
|---|---|
| `ANALYZING` | 진행 표시와 취소/대기 안내. 분석 완료 전 PASS로 간주하지 않습니다. |
| `VERIFIED` | `decision`과 `result`를 렌더링합니다. |
| `FAILED` | 실패 메시지와 재시도 안내. `FAILED`는 PASS가 아닙니다. |
| `415 UNSUPPORTED_FORMAT` | 지원하지 않는 오디오 형식 안내 |
| `413 FILE_TOO_LARGE` | 최대 250 MiB 제한 안내 |
| `422 EMPTY_FILE` 또는 `AUDIO_FILE_REQUIRED` | 파일 선택/유효성 안내 |
| `429 QUEUE_FULL` | 잠시 후 재시도 안내 |
| `404 TRACK_NOT_FOUND` | 결과를 찾을 수 없다는 안내 |

지원 형식: MP3, WAV, WEBM, FLAC, M4A, AAC, OGG, WMA. FastAPI 분석은 최대 30분 음원을 지원하며, 업로드 최대 크기는 250 MiB입니다.

## 7. 현재 평가 결과와 한계

현재 기준 데이터는 295곡, 9,847개 세그먼트 윈도우입니다. Top-3 집계 방식의 홀드아웃 시험은 양성 32개와 정상 119개를 사용했습니다.

**데이터셋 업데이트 주의:** 2026-10-22에 `original_music`을 1,000곡으로 확장했지만, 새 CLAP 전체 임베딩 및 재평가가 CPU 처리 시간 때문에 완료되지 않았습니다. 아래 성능 수치와 임계값은 확장 전 295곡 기준의 과거 평가 결과이며, 현재 1,000곡 검색 DB의 검증 결과가 아닙니다. 프론트엔드 시연 자료에는 이를 “기존 295곡 기준”으로 표기하고 최종 성능으로 설명하지 마세요.

- 원곡 검색 포함률: Top-1 93.8%, Top-3 96.9%.
- HOLD 기준: 양성 검출률 78.1%, 정상곡 HOLD 오탐률 5.0% (6/119).
- WARN 이상 기준: 양성 검출률 87.5%, 정상곡 WARN 이상 오탐률 18.5% (22/119).
- 따라서 점수는 사용자에게 설명 가능한 **위험 신호**로 제시하고, 법적 표절 판정이나 자동 업로드 거절 근거로 과장하지 않습니다. 특히 HOLD/WARN은 사람의 검토 절차가 필요합니다.
- 평가 양성에는 합성 변형 데이터가 포함되며, 사람의 재연주/편곡 일반 성능을 입증하지 않습니다. 운영 데이터가 늘면 재평가하고 임계값을 다시 보정해야 합니다.

## 8. 업로드/등록 동작 관련 주의

`POST /api/tracks`는 업로드를 접수하고 `ANALYZING` 상태로 작업을 시작합니다. 이 API 자체가 최초 업로드 요청을 HTTP 409로 즉시 거절하는 구조는 아닙니다. 검사 후 `BLOCK`으로 판정된 음원이 공개·판매·정산 단계로 넘어가지 않도록 제품 백엔드가 상태를 강제해야 합니다. Layer 2 `HOLD/WARN`은 차단 대신 검토/위험 표시 정책으로 연결합니다.

---

구현 출처: `api/engine.py`, `api/server.py`, `api/schemas.py`, `backend/src/server.ts`, `layer2/LAYER2_DECISION_POLICY.md`, `layer2/artifacts/top3_aggregation_evaluation.json`.
