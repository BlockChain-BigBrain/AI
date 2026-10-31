# Track-AI 통합 검증 API

이 API는 Node 백엔드가 보낸 한 개의 음원을 임시 저장해 Layer 1과 Layer 2를 순서대로 검사합니다. `/verify`는 기준 DB를 수정하지 않습니다.

## 판정 순서

1. Layer 1에서 업로드 음원의 전체 Chromaprint 지문 시퀀스가 등록 지문 안에 정확히 존재하면 `BLOCK`
2. 그 외에는 10초 창, 5초 간격으로 CLAP 후보 검색
3. 현재 AI 표시군 정책에서는 후보 Top-20의 음높이 흐름을 확인하고, 조건에 따라 정밀 CQT와 세 구간 근거 추가
4. 확인 점수와 해당 검색 범위의 임계값으로 `PASS`, `WARN`, `HOLD` 산출; 응답에는 Top-3와 매칭 구간 반환

현재 로컬 팀 실행의 `TRACK_AI_SCOPE=ai_labeled` 모드는 Pixabay AI 표시 원곡 34곡을 검색하며, `ai_precision_policy.json`의 WARN `0.34748932160579077`, HOLD `0.8337449399145463`을 적용합니다. 이는 합성 데이터 기반의 잠정값이고 `provisional: true`로 표시합니다. `all` 모드는 다른 과거 정책을 사용하므로 실제 실행 서버의 `/health`와 결과에 있는 `evaluationScope`, `decisionPolicyVersion`, `scoreVersion`, `thresholds`를 기준으로 해석하세요. 점수는 확률이 아닙니다.

| AI 표시군 확인 점수 | 판정 | 처분 |
|---|---|---|
| WARN 미만 | PASS | `ALLOW` |
| WARN 이상·HOLD 미만 | WARN | `HUMAN_REVIEW`, `reviewRequired=true` |
| HOLD 이상 | HOLD | `HUMAN_REVIEW`, `reviewRequired=true` |
| 점수 비교 전 정확한 지문 시퀀스 일치 | BLOCK | `AUTO_BLOCK`, `similarityScore=null` |

최종 판정은 화면에서 반올림한 숫자로 다시 계산하지 말고 API의 `decision`을 사용하세요. 현재 척도에서 0.31은 PASS, 0.84와 0.93은 HOLD입니다. `0.70/0.85` 기준의 서비스 Risk Score가 별도로 있다면 원시 확인 점수와의 매핑·버전을 명시해야 하며, 그 기준을 AI 임계값으로 표시하면 안 됩니다.

## AI 작업과 서비스 상태의 경계

`PENDING`/`RUNNING`은 분석 대기·실행, `SUCCEEDED`는 분석 완료이며 그 안의 `result.decision`이 PASS/WARN/HOLD/BLOCK입니다. `SUCCEEDED`는 NFT 민팅 성공을 의미하지 않습니다. 분석 실패는 `FAILED`이며 PASS로 대체하지 않습니다.

이 FastAPI는 IPFS 업로드·NFT 민팅·정산 잠금·지분 서명 검증을 수행하지 않습니다. 따라서 AI WARN/HOLD만으로 ‘마켓 등록 성공’이나 ‘정산 잠금 완료’를 확정할 수 없습니다. 지갑 거부·컨트랙트 revert·서명 검증 실패·IPFS 실패는 AI 판정과 별도 상태로 다뤄야 합니다. 서명 검증 실패만으로 사용자 조작을 단정하지 않습니다. BLOCK은 정확한 지문 시퀀스 일치를 나타내며, 오디오 전체의 비트 단위 동일성이나 불법 복제·권리 침해를 확정하는 결과는 아닙니다.

## 실행

```powershell
C:\Users\82108\anaconda3\python.exe -m pip install -r api\requirements.txt
C:\Users\82108\anaconda3\python.exe api\server.py
```

서버 시작 후 `http://127.0.0.1:8000/docs`에서 요청 형식과 응답 스키마를 확인할 수 있습니다. 첫 기동은 CLAP과 기준 벡터를 메모리에 올리므로 시간이 걸립니다. 실제 검색 곡·창 수는 `/health`에서 확인합니다. MVP는 분석 작업자 한 개로 실행합니다.

## API 계약

- `GET /health`: 모델 및 기준 인덱스 준비 상태
- `POST /verify`: `multipart/form-data`의 `file`, `trackId`, `requestId`를 받고 HTTP 202와 작업 번호 반환
- `GET /verify/{jobId}`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED` 및 최종 결과 반환

`requestId`는 Node 백엔드가 요청마다 생성하고 재시도 때 그대로 사용합니다. 같은 ID에 다른 파일이나 `trackId`를 보내면 HTTP 409를 반환합니다. 분석 실패는 `FAILED`이며 `PASS`로 처리하지 않습니다.

## Node 연결 확인

Node 22 이상에서:

```powershell
node api\node-client.mjs "C:\음원\test.mp3" track-123 request-123
```

실제 Express 서비스에서는 `node-client.mjs`의 `verifyAudio()`를 불러 업로드 임시 경로, DB의 track ID, 요청 ID를 전달합니다. 결과를 받은 뒤 Node가 MySQL에 저장하고, 등록이 승인된 음원만 별도 기준 DB 등록 단계로 넘깁니다.

## 응답에서 반드시 저장할 필드

`audioHash`, `decision`, `similarityScore`, `similarTracks`, `thresholds`, `modelVersion`, `scoreVersion`, `corpusVersion`, `processingSeconds`를 저장해야 나중에 어떤 파일과 모델로 나온 결과인지 재현할 수 있습니다.
# 내부 API 인증

`POST /verify`는 백엔드와 FastAPI 사이의 내부 호출만 허용하도록
`X-Internal-API-Key` 헤더를 검사합니다. 프로젝트 루트 `.env`에
`TRACK_AI_API_KEY`를 설정하면 서버가 이를 사용합니다. `/health`는 모니터링을
위해 인증 없이 사용할 수 있습니다. `.env`는 Git에 커밋하지 말고 `.env.example`을
복사해 각 개발 환경에서 별도로 설정하세요.

검증 결과에는 `decision`, `decisionReason`, `disposition`, `reviewRequired`가 함께
포함됩니다. `BLOCK`만 자동 차단이고, `HOLD`와 `WARN`은 사람이 확인하는 상태이며,
`PASS`는 Layer 2 위험 기준을 넘지 않았다는 뜻입니다. Layer 2 결과는 법적 표절
확정이 아니라 위험 신호입니다.

## 현재 로컬 AI 표시군 모드

현재 정책은 `ai_precision_policy.json`입니다. 기존 Top-20 확인 점수가 0.60보다 낮을 때 원래 CLAP Top-3에 정밀 CQT와 세 구간 확인을 추가합니다. 주 WARN/HOLD는 유지하고 보조 경로 원시 증거 기준은 별도로 보정했습니다. 추가 경로의 점수는 기존 WARN 척도로 변환하고 0.80으로 제한합니다. 참고 구현 환경은 `librosa==1.0.0`이며 정책이 라이브러리 버전과 구현 해시를 검사합니다. 표본 구분과 목표 대비 결과는 [멘토링 최종 현황](../MENTORING_FINAL_STATUS_20261025.md)을 보세요.

팀 서비스는 루트에서 `python local_team.py --serve`로 실행합니다. 이 명령은 `TRACK_AI_SCOPE=ai_labeled`를 적용하며 Pixabay 곡별 페이지의 AI 표시가 관찰된 원본 34곡으로 지문·벡터 검색을 제한합니다. 활성 임계값과 한계는 [최신 검색 개선](../AI_IMPROVEMENT_20261023.md)을 보세요. 이는 순수 AI 생성 여부의 확정이 아닙니다.

`ai_improvement_policy.json`이 있으면 검증된 후보 Top-20 정책을 사용합니다. CLAP 1–5위의 음높이 흐름 점수는 유지하고 6–20위는 제곱해 약한 추가 후보를 낮춘 뒤 화면 Top-3를 정합니다. 점수 버전은 `clap-top20+tonal-local-v1+expanded-square-v1`입니다. 정책을 출처·DB·평가·추가 시험·감사·점수 구현 해시와 대조하며, 맞지 않으면 시작을 거절합니다. `/health`는 실제 `decisionPolicyVersion`, `thresholds`, `referenceTracks`를 반환합니다. 이 점수는 확률이 아닙니다.

`TRACK_AI_SCOPE=all`은 종전 혼합·미확인 1,000곡 DB와 기존 `tonal_confirmation_evaluation.json` 보정값을 유지하는 과거 실험 모드입니다. AI 질의로 1,000곡을 별도 비교한 오프라인 재평가 값은 `ai_labeled_recalibration.json`에 있으며 이 모드의 기존 보정값과 구분합니다. 결과·health의 `evaluationScope`와 결과의 `referenceTracks`로 실제 범위를 확인할 수 있습니다.
