# 추가 합성 양성

30개 원곡 × 3단계 × 2방식 = 180개. `manifest.csv`에 원곡·변형·seed·파라미터·SHA-256을 기록합니다.

- `room_rerecord_simulation`: 공간 잔향과 잡음 합성, 90개.
- `local_tempo_warp`: 피치를 유지하는 구간별 비균일 템포, 90개.

재생성: `python layer2/make_extended_positives.py`

같은 원곡의 모든 변형은 같은 평가 분할에 두세요. 실제 재녹음·사람 재연주·법적 표절 사례가 아닙니다. 설계와 전체 현황은 [현재 상태 정리](../../../STATUS_SUMMARY_20261022.md)를 참고하세요.
