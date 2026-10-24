# 미사용 AI 검증 자료 접수

실제 새 음원과 생성 기록이 아직 없으므로 이 폴더는 입력 양식입니다. 템플릿을 실제 AI 생성 증거로 취급하지 않습니다.

1. `manifest.example.csv`를 별도 CSV로 복사해 실제 파일 경로와 기록을 작성합니다. 상대 경로는 그 CSV가 있는 폴더 기준입니다.
2. 생성 기록 JSON에 실제 `generator`, `model`, `generation_id`, `human_performance`를 기록합니다. 기록의 ID·서비스·모델이 CSV와 일치해야 합니다. 원본 서비스 기록·URL·생성 시각을 함께 보관하세요. 실제 서비스 발급 기록의 진위나 순수 AI 제작 여부가 이 구조 검사만으로 인증되는 것은 아닙니다.
3. 정상곡은 `role=normal`, `expected_track_id`는 빈칸입니다. 독립 생성물마다 다른 `work_id`와 생성 ID를 사용합니다. 같은 생성물의 다른 인코딩·변형을 여러 독립 정상곡으로 세지 않습니다.
4. 양성은 `role=positive`이고 현재 AI 표시 기준 DB에 포함된 정확한 원곡 ID를 `expected_track_id`로 지정합니다. 새 원곡 자체를 기준 DB에 추가하는 평가는 별도 인덱스 설계가 필요합니다.

```powershell
python layer2/validate_fresh_ai.py --manifest C:/블록체인/my_validation/manifest.csv --output C:/블록체인/.runtime-tests/my-validation
python layer2/validate_fresh_ai.py --manifest C:/블록체인/my_validation/manifest.csv --output C:/블록체인/.runtime-tests/my-validation --evaluate
```

첫 명령은 입력·기록·해시 검사를 하고 정책과 입력 목록을 고정합니다. 두 번째 명령은 실제 Engine으로 평가합니다. 출력은 프로젝트 내부의 새 디렉터리를 사용하세요. 실행 중단 뒤에는 같은 입력·출력으로 재개할 수 있고 완료된 자료를 바꿔 다시 맞추는 것은 허용하지 않습니다.

- 기존 1,500곡과 기존 JSON manifest의 음원 해시를 재사용하면 거절합니다.
- 빈 양식, 생성 기록 불일치, 같은 생성 ID를 반복한 정상곡을 거절합니다.
- 실패한 분석은 PASS로 처리하지 않습니다. 정상으로 제출했으나 BLOCK이 나온 곡도 결과에서 조용히 제외하지 않습니다.
- `summary.json`에 관측 경고율과 단측 95% 이항 상한을 함께 기록합니다. 독립·대표 표본이라는 가정이 필요합니다.
- 경고 0건을 가정해도 WARN 10% 이하에는 최소 29곡, HOLD 2% 이하에는 최소 149곡이 필요합니다. 경고가 있으면 더 많은 자료가 필요하며, 여러 변형을 독립 정상곡으로 합산하면 안 됩니다.
- 사람의 독립 연주 자료는 요구하지 않습니다. 독립 AI 생성물과 실제 생성 기록이 필요합니다.

실제 자료를 받기 전 상태는 **접수·평가 도구 구현 완료 / 미사용 독립 AI 평가 미실행**입니다.
