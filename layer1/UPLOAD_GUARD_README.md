# Layer 1 중복 업로드 차단 API

## 동작

`POST /api/v1/uploads`에 `file` 이름의 multipart 오디오 파일을 보내면 Chromaprint 지문을 비교합니다.

- 등록된 음원의 지문 안에 업로드 음원의 전체 지문이 연속해서 정확히 포함되면 HTTP `409 Conflict` (`DUPLICATE_AUDIO`)로 거절합니다.
- 일치 항목이 없으면 파일을 `layer1/accepted_uploads`에 저장하고 지문 DB에도 추가합니다. 이후 같은 음원은 중복으로 거절됩니다.
- 10초 미만 음원, 지원하지 않는 확장자, 손상 파일, 빈 인덱스는 정상 통과 처리하지 않습니다.
- 지문 비교는 Chromaprint `-raw`의 정수 프레임 배열을 사용합니다. 분위기나 장르가 비슷한 곡, 변주·재연주 곡을 표절로 판정하는 기능은 아닙니다.

## 설치 및 실행 (PowerShell, 저장소 루트 `C:\블록체인`)

```powershell
python -m pip install -r layer1/requirements-upload-guard.txt
python layer1/upload_guard_api.py --build-index
python layer1/upload_guard_api.py
```

서버는 기본적으로 `127.0.0.1:8000`에만 열립니다. API 문서는 `http://127.0.0.1:8000/docs`, 준비 상태는 `http://127.0.0.1:8000/health`에서 확인합니다.

## 요청 예시

```powershell
curl.exe -F "file=@C:\path\to\song.mp3" http://127.0.0.1:8000/api/v1/uploads
```

중복이면 응답 코드는 409이고, 예시는 다음과 같습니다.

```json
{
  "detail": {
    "code": "DUPLICATE_AUDIO",
    "message": "An exact Chromaprint sequence is already registered.",
    "matched_track_id": "original_music/example.mp3"
  }
}
```

## 범위

현재 저장소에는 기존 프론트엔드/백엔드 업로드 경로가 없어서, 이 코드는 독립 실행형 업로드 게이트입니다. 이 API에 파일을 직접 보내면 중복은 파일 저장 전에 409로 거절합니다. 기존 서비스 화면에서 업로드를 막으려면 프론트엔드 업로드 목적지를 이 API로 바꾸거나 기존 백엔드 업로드 경로에서 이 검사 함수를 호출해야 합니다. 기본 바인딩은 로컬 시연용이며, 외부 공개 전에는 인증과 요청 제한을 적용해야 합니다.
