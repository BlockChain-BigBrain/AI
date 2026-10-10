# Track-AI 통합 검증 API

이 API는 Node 백엔드가 보낸 한 개의 음원을 임시 저장해 Layer 1과 Layer 2를 순서대로 검사합니다. `/verify`는 기준 DB를 수정하지 않습니다.

## 판정 순서

1. Layer 1 Chromaprint가 등록 음원의 전체 지문과 정확히 일치하면 `BLOCK`
2. 그 외에는 전체 곡을 10초 창, 5초 간격으로 CLAP 분석
3. `seg_top3_centered-v1` 점수로 `PASS`, `WARN`, `HOLD` 산출
4. 내부 후보 전체를 계산하고 응답에는 Top-3와 매칭 구간을 반환

현재 임계값은 WARN `0.856638`, HOLD `0.894406`이며 제품 확정값이 아니라 합성 데이터 기반의 잠정값입니다. 응답의 `provisional: true`가 이를 표시합니다.

## 실행

```powershell
C:\Users\82108\anaconda3\python.exe -m pip install -r api\requirements.txt
C:\Users\82108\anaconda3\python.exe api\server.py
```

서버 시작 후 `http://127.0.0.1:8000/docs`에서 요청 형식과 응답 스키마를 확인할 수 있습니다. 첫 기동은 CLAP과 9,847개 기준 벡터를 메모리에 올리므로 시간이 걸립니다. MVP는 분석 작업자 한 개로 실행합니다.

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
