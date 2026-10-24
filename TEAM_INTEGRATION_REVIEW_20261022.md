# 실제 팀 프론트·백엔드 연결 검토본

> 최신 로컬 실행은 AI 표시 원본 34곡 범위와 별도 보정값을 사용합니다. [Pixabay 출처 확인·AI 표시군 재평가](PIXABAY_AI_RECALIBRATION.md)에 현재 데이터 수량과 한계를 정리했습니다. 원본 1,000곡 파일은 보존합니다.

> 현재 음높이 흐름 확인 기준·개선 성능·추가 점검 한계는 [후속 개선 정리본](MENTORING_REVISION_20261022.md)에 있습니다. 아래의 최초 연결 설명 이후 실제 AI 성공 경로도 시험을 마쳤습니다.

작업 복사본은 `integrations/Frontend`, `integrations/Backend`입니다. 원격 커밋·push·GitHub Pages 배포는 하지 않았습니다.

기준 커밋: Frontend `913527591ad910fcef6c282e76e656f481f1bbf9`, Backend `c5428999a92beb440d2e823ede6dad9b152f5dd8`.

## 변경한 동작

| 부분 | 이전 | 변경 후 |
|---|---|---|
| 업로드 | HTTP 성공 후 고정 Mint 완료 표시 | 실제 AI 접수·상태 조회·결과 표시 |
| 결과 | 고정 점수·후보·가짜 타이머 코드 | 서버의 PASS/WARN/HOLD/BLOCK·Top-3·매칭 구간 |
| 실패 | 실제 AI 연동 없음 | FAILED 저장·표시, 같은 음원 재분석 |
| 인증 | Google·HttpOnly 쿠키·메모리 Access token | 기존 `src/auth.ts` 유지, `auth.apiFetch`로 업로드·조회·재분석 |
| DB | PENDING 기록만 생성 | 요청 키·AI 작업 ID·판정·근거 JSON·오류 상태 영속 저장 |
| 재시작 | AI 복구 경로 없음 | DB의 AI PENDING 작업 복구, 같은 요청 키 사용 |
| 권한 | 기존 검증·삭제 소유자 검사 없음 | 검증 조회·재요청·삭제는 소유자만 허용 |
| 모바일 | 상단 계정·메뉴 잘림 | 두 줄 헤더와 스크롤 메뉴 |
| 입력 정보 | 예시 플랫폼·프롬프트 기본값 | 플랫폼 미선택·프롬프트 빈 값으로 시작, 사용자가 입력 |
| 로그아웃 | 기존 세션 정리 | 쿠키·메모리 토큰과 저장된 검증 조회 ID 정리 |

`VERIFIED`는 분석 완료 상태입니다. 실제 위험 등급은 `decision`과 `riskStatus`로 구분합니다. WARN/HOLD는 검토 대상으로 표시하며, 지문 중복 BLOCK은 REJECTED, 분석 실패는 FAILED로 저장합니다. 이 검증으로 온체인 Mint나 독창성 인증이 자동 실행되지는 않습니다.

외부 원곡 ID·점수·매칭 구간은 `Verification.resultJson`에 보존합니다. 검색 DB의 문자열 원곡 ID와 팀 서비스의 숫자 `Track.id` 사이의 대응은 별도 관리 대상입니다.

## API와 DB

- `POST /api/tracks`: 기존 `audio` multipart·Bearer 인증 유지. 음원과 PENDING 검증을 함께 저장하고 201 응답.
- `GET /api/tracks/:id/verification`: 소유자의 최신 검증 상태·근거 조회.
- `POST /api/tracks/:id/verify`: 소유자의 재분석 요청, 202 응답. 진행 중 검증은 재사용하고 동시 요청은 DB 잠금으로 조정.
- 내부 AI 설정: `TRACK_AI_URL`, `TRACK_AI_API_KEY`. 키는 백엔드에만 둡니다.
- 마이그레이션: `integrations/Backend/prisma/migrations/20261022140000_connect_ai_verification/migration.sql`.

기존 사용자·음원·기여도 모델을 유지하면서 Verification에 FAILED 상태와 AI 근거 필드를 추가했습니다. 실제 마이그레이션은 격리 MySQL에 적용해 시험했으며 운영 DB에는 적용하지 않았습니다.

## 검증 범위

프론트 TypeScript 검사·인증/검증 테스트 10개 통과, `npm run build`로 `docs/`를 생성했습니다. 백엔드 빌드·테스트 28개 통과, 소켓 전용 레거시 보존 테스트 1개는 환경 조건상 건너뛰었습니다. 별도로 기존 4개와 새 마이그레이션을 실제 MySQL에 모두 적용해 통합 시험을 했습니다.

실제 Chrome에서 React → HttpOnly 쿠키 복원 → 인증 업로드 → Prisma → MySQL → FAILED 표시를 확인했습니다. 새로고침 복원·동일 음원 재분석·타 계정 403·모바일 검사도 통과했습니다. 증거는 `layer2/artifacts/team_frontend_integration_validation.json`, `team_upload_failed_desktop.png`, `team_upload_failed_mobile.png`입니다.

실패 경로와 별도로, 현재 음높이 흐름 판정 버전의 실제 FastAPI BLOCK을 팀 DB에 저장하고 React에서 확인하는 성공 경로 시험도 통과했습니다. 결과 파일은 `layer2/artifacts/team_live_ai_e2e_validation.json`이며 실제 점수 버전 검사와 React 화면의 가입·로그인 시험을 포함합니다.

실제 Google Cloud 계정 로그인은 비밀 설정이 없어 실행하지 못했습니다. Google 콜백·state·쿠키·갱신·로그아웃 회귀 테스트는 통과했으며, 브라우저 시험은 로컬 계정으로 같은 쿠키/Access token 흐름을 사용했습니다.

## 로컬 실행 설정

사용자의 로컬 환경 선택에 맞춰 `integrations/Frontend/.env.local`, `integrations/Backend/.env`를 생성했습니다. 기존 루트 `.env`는 보존했고 내부 AI 키를 일치시켰습니다. JWT 키와 DB 비밀번호는 무작위 생성했으며 모두 Git 제외 파일에만 저장합니다.

`python local_team.py`는 별도 영속 MySQL을 127.0.0.1:3307에 잠시 실행해 전용 계정·DB를 준비하고 마이그레이션을 적용한 뒤 종료합니다. 최초 준비와 재실행 모두 통과했습니다. 데이터는 `.runtime-tests/local-team/`에 유지하며 기존 3306 DB와 시험용 3308 DB를 사용하지 않습니다.

전체 평가·보정이 끝난 뒤 `python local_team.py --serve`로 MySQL·실제 AI·팀 백엔드·React를 실행하고 `http://localhost:8443/Frontend/`에서 확인할 수 있습니다. 터미널에서 Ctrl+C로 해당 프로세스를 종료하며 DB·업로드는 보존합니다. 평가 미완료 상태에서는 시작을 거절합니다. 이 명령은 기존 `Start-TrackAI.ps1`의 별도 MVP와 구분됩니다.

Google Client ID·Secret은 제공되지 않아 비워 두었습니다. 화면의 Google 로그인은 해당 값을 Backend `.env`에 설정하고 Google Cloud에 로컬 콜백 URI를 등록해야 사용할 수 있습니다. 로컬 DB 준비가 실제 Google 로그인 검증을 뜻하지는 않습니다.

현재 개발 모드에서는 `VITE_LOCAL_LOGIN=true`일 때 로컬 계정 가입·로그인 화면을 표시합니다. 기존 팀 백엔드의 가입·로그인 API를 사용하며 인증을 건너뛰지 않습니다. 실제 Chrome에서 화면 가입·로그인→업로드→재발급 쿠키→검증→로그아웃 흐름을 확인했습니다. 운영 빌드에는 이 개발용 화면을 포함하지 않습니다. 원래 Google 인증용 `src/auth.ts`는 변경하지 않았습니다.

## 운영 배포를 선택할 경우 남은 설정

운영 배포에는 별도의 실제 MySQL·Google OAuth 설정이 필요합니다. 받은 README에는 해당 값이 없습니다. 비밀번호·JWT/Google 비밀키를 채팅이나 `VITE_*`에 넣지 마세요.

로컬 기본값은 Backend `.env.example`에 맞춰 PORT 3000, FRONTEND_URL `http://localhost:8443/Frontend/`, Google 콜백 `http://localhost:3000/api/v1/auth/callback/google`입니다. 내부 AI 주소는 `http://127.0.0.1:8000`이며 두 서버의 내부 키가 일치해야 합니다.

운영 Google 콜백·CORS·쿠키와 실제 HTTPS API 주소는 운영 환경에서 추가 확인해야 합니다. 기존 `/Frontend/` base와 `main /docs` 방식을 유지했고 `docs/`는 빌드로만 갱신했습니다. 현재 산출물은 기본 로컬 API 주소를 사용하는 검토용입니다. 배포 전 `VITE_API_BASE_URL`을 실제 HTTPS API로 설정해 다시 빌드해야 합니다.

검토 시 각 작업 복사본에서 `git diff`, `git status --short`를 확인하고 새 파일과 변경·추가·삭제된 `docs/`를 함께 보세요. Marketplace 상세·구매·인증서 등 기존 예시 화면은 이번 검증 연결과 별도입니다. 전체 평가 진행은 [멘토링 실행 현황](MENTORING_EXECUTION_20261022.md)을 참고하세요.
