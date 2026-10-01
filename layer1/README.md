# Layer 1 안내

Layer 1은 등록 오디오와 정확히 겹치는 Chromaprint 지문이 있는 업로드를 거절합니다. 장르나 멜로디가 비슷한 곡의 표절 여부를 판단하지는 않습니다.

## 파일별 역할

| 파일 | 내용 |
|---|---|
| upload_guard_api.py | 지문 인덱스 생성, 중복 비교, POST /api/v1/uploads |
| fingerprints_db.json | 생성 지문 DB. 직접 편집 금지 |
| requirements-upload-guard.txt | FastAPI/Uvicorn/multipart 의존성 |
| UPLOAD_GUARD_README.md | 상세 설치·실행·요청 안내 |
| auto music expert | 이전 배치 추출 스크립트. 새 API 인덱서로 사용하지 않음 |

## 설치 및 실행

저장소 루트 PowerShell에서:

~~~powershell
python -m pip install -r layer1/requirements-upload-guard.txt
python layer1/upload_guard_api.py --build-index
python layer1/upload_guard_api.py
~~~

기준 원본을 original_music에 추가한 뒤에는 --build-index를 다시 실행합니다. API는 기본 127.0.0.1:8000에서 동작합니다. multipart 파일 필드 이름은 file입니다. 중복은 HTTP 409로 거절하고, 통과 파일은 저장 후 인덱스에 추가합니다.

현재 저장소에는 기존 서비스 업로드 경로가 없습니다. 실제 제품에서 막으려면 기존 프론트엔드/백엔드가 이 API를 호출하도록 연결해야 합니다. 10초 미만, 손상 파일, 미지원 확장자는 통과시키지 않고 오류를 반환합니다.
