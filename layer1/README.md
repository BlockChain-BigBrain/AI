# Layer 1

Layer 1은 Chromaprint 오디오 지문으로 완전히 같거나 거의 같은 음원의 중복 업로드를 먼저 차단합니다. Layer 2의 의미적 유사도 분석보다 앞에서 동작합니다.

## 파일

- `upload_guard_api.py`: 지문 생성, 기존 DB 비교, 업로드 API
- `fingerprints_db.json`: 등록된 원본 지문 DB
- `requirements-upload-guard.txt`: Layer 1 실행 의존성
- `UPLOAD_GUARD_README.md`: 설치·실행·요청 예시

## 실행 개요

```powershell
python layer1/upload_guard_api.py --build-index
python layer1/upload_guard_api.py
```

동일 음원은 HTTP 409로 거절하고, 통과한 음원만 Layer 2 검증으로 전달합니다.
