# Track-AI Node 백엔드 MVP

브라우저 업로드를 받고 Python FastAPI에 분석을 맡긴 뒤 결과를 로컬 SQLite에 저장하는 연결 서버입니다. 프론트엔드는 Python API를 직접 호출하지 않습니다.

## 실행 순서

1. 별도 터미널에서 `C:\Users\82108\anaconda3\python.exe api\server.py`
2. `cd backend`
3. `npm install`
4. `npm start`

## 요청

`POST /api/tracks`에 `multipart/form-data`의 `file`을 보냅니다. 즉시 HTTP 202와 `trackId`, `statusUrl`을 받습니다. `GET /api/tracks/{trackId}`를 1초 간격으로 조회해 `ANALYZING`, `VERIFIED`, `FAILED`를 확인합니다.

`VERIFIED` 결과의 `decision`은 `PASS`, `WARN`, `HOLD`, `BLOCK`입니다. 업로드 임시 파일은 성공·실패와 관계없이 분석 후 삭제됩니다. AI가 실패한 경우 정상 처리하지 않고 `FAILED`로 저장합니다.

SQLite는 로컬 통합 확인용입니다. 팀 MySQL 서버가 준비되면 `tracks` 테이블 필드를 Prisma 모델로 옮기고, 현재 SQL 호출 부분만 저장소 모듈로 교체하면 됩니다.

두 서버를 실행한 상태에서 원본 중복 시나리오를 자동 확인할 수 있습니다.

```powershell
npm run test:e2e -- "C:\블록체인\original_music\검사용.mp3" BLOCK
```

2026-10-01 확인 결과 원본 중복은 `VERIFIED/BLOCK`, 변형 음원은 `VERIFIED/PASS`로 저장됐고 변형 음원 결과에 Top-3가 포함됐습니다. 분석 후 임시 업로드 폴더는 비어 있었습니다. 변형 양성이 `PASS`인 것은 현재 결과를 재현한 것이며, 바람직한 탐지 성공을 뜻하지 않습니다.
