# GitHub 업로드 범위

이 저장소는 코드와 재현 문서를 올리고, 개인 음원·모델 가중치·생성 캐시는 올리지 않는 구성으로 정리했습니다.

## 올릴 것

| 경로 | 이유 |
|---|---|
| `README.md`, `MENTORING_GUIDE.md` | 프로젝트 설명, 구조, 실측 수치와 한계 |
| `layer1/*.py`, `layer1/*.md`, `layer1/requirements-upload-guard.txt` | Chromaprint 중복 검사 API와 설명 |
| `layer2/*.py`, `layer2/*.md` | 현재 사용하는 CLAP·Chroma 평가 코드와 정책 |
| `layer2/test_data/**/manifest.csv`, `README.md` | 시험 데이터의 출처·변형 메타데이터 |
| `layer2/artifacts/*summary.json`, `*report.json`, `layer2_operating_policy.json` | 용량이 작은 재현 결과 요약 |
| `api/*.py`, `api/*.mjs`, `api/README.md`, `api/requirements.txt` | 통합 FastAPI |
| `backend/package.json`, `backend/package-lock.json`, `backend/tsconfig.json` | Node 실행 환경 고정 |
| `backend/src/`, `backend/test/`, `backend/README.md` | Node → FastAPI → DB 연결 코드와 E2E 테스트 |
| `.gitignore`, `GITHUB_UPLOAD_GUIDE.md` | 업로드 범위와 대용량 파일 방지 |
| `Track-AI_피칭덱.pptx (1).pdf` | 공개해도 되는 발표 자료일 때만 포함 |
| `fpcalc.exe` | Windows 데모에 필요. 배포 권한을 확인한 뒤 포함 |

## 올리지 않을 것

- `original_music/`, `music/`, `segments/`: 음원과 15,699개 분할 파일
- `layer2/test_data`의 mp3/wav 등: 시험 음원 원본과 합성 파일
- `layer2/.vendor/`: CoverHunter 모델 가중치와 대용량 외부 자료
- `layer2/coverhunter_csi.py`, `evaluate_coverhunter_*.py`, `COVERHUNTER_README.md`: 비교 실험용 CoverHunter 경로. 현재 서비스 API에는 사용하지 않음
- `layer2/artifacts/*.npz`, `*cache*/`: 임베딩·특징 캐시
- `layer2/artifacts/*details.csv`, `*candidates.csv`, `segment_manifest.csv`: 대형 상세 결과와 로컬 절대 경로
- `layer1/fingerprints_db.json`: 로컬 음원 경로가 들어간 생성 인덱스
- `api/.deps/`, `api/.tools/`, `backend/node_modules/`: 설치 폴더
- `api/runtime/`, `backend/runtime/`: SQLite·작업 임시 파일
- `review_handoff/`: 친구에게 별도 전달하는 검수 ZIP

## 업로드 전에 실행

저장소 루트에서 다음을 실행합니다.

```powershell
git add .
git status --short
```

`original_music`, `music`, `segments`, `node_modules`, `.vendor`, `.npz`가 목록에 보이면 추가하지 말고 `.gitignore` 적용 상태를 먼저 확인합니다.

그 다음 커밋합니다.

```powershell
git commit -m "Add Track-AI audio verification pipeline"
git branch -M main
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```

## 친구가 clone한 뒤 준비할 것

```powershell
python -m pip install -r layer1/requirements-upload-guard.txt
python -m pip install -r api/requirements.txt
cd backend
npm ci
```

음원은 별도로 준비하고, Layer 1 기준 지문 인덱스와 CLAP 임베딩 캐시는 각 환경에서 생성해야 합니다. 따라서 GitHub의 코드만으로는 대용량 음원 검색이 즉시 재현되지 않으며, 이 점을 README와 발표에서 명시해야 합니다.
