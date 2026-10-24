# 음원 데이터 폴더 분류와 현재 상태

> 생성 방식은 [Pixabay 출처 조사](PIXABAY_AI_AUDIT.md)에서 별도 확인했습니다. 전체 1,000곡을 AI 생성곡으로 확정하지 않았으며, AI 표시 34곡 검색은 파일 삭제 없이 별도 마스크로 적용합니다. 최신 성능은 [AI 표시군 재보정](PIXABAY_AI_RECALIBRATION.md)을 보세요.

2026-10-22 기준 데이터 위치, 용도, 중복 검사 결과입니다. **폴더 이름은 기존 코드가 직접 참조하므로 유지합니다.** 원본 음원 파일명도 source/track ID와 manifest 및 Layer 1 인덱스 연결에 사용되므로 일괄 변경하지 않습니다.

## 폴더별 분류

| 분류 | 폴더/파일 | 현재 규모 | 용도와 주의점 |
|---|---|---:|---|
| 원본 검색 기준 DB | `original_music/` | **1,000곡** | Layer 1 Chromaprint와 Layer 2 CLAP이 대조할 원곡 라이브러리. 이전 295곡 + 이번 중복 검사를 통과한 705곡. |
| Layer 1 지문 인덱스 | `layer1/fingerprints_db.json` | 1,000개 원본 인덱싱 완료 | 이번 원본 추가 후 `python layer1/upload_guard_api.py --build-index`로 갱신함. 보고상 searchable 1,001개인 것은 기존 테스트 업로드 레코드 1개(`track_01.wav`, 10초 미만)가 남아 있기 때문이며, 원본 라이브러리 자체는 1,000곡. |
| 정상 대조 후보 | `music/` | **300곡 모두 `NO_EXACT_MATCH`** | 중복 17곡 삭제 후 premusic 검증곡 17곡으로 교체. SHA-256·Chromaprint 기본 분석 구간으로 원본 DB 및 정상대조군 내부 비교. 음악적 독립성 확정 라벨이 아님. |
| 예비 추가 음원 | `premusic/` | **200곡 남음** | 이전 217곡에서 정상대조군 교체용 검증곡 17곡을 music으로 이동. 이전 예비곡 분류 보고서는 교체 전 이력. |
| 기본 합성 양성 테스트 | `layer2/test_data/plagiarism_positive/` | 90곡 | 원곡 오디오의 자르기/속도/피치/EQ 등 자동 변형 테스트. 사람이 재연주한 곡이 아님. `manifest.csv`가 변형본과 출처 원곡을 연결함. |
| 악기 레이어 합성 양성 | `layer2/test_data/synthetic_layered_positive/` | 10곡 | 원곡 위에 악기/레이어를 추가한 자동 합성 시험. 원곡을 알아볼 수 있는 변형 테스트이며 실제 편곡의 대표 표본은 아님. |
| 긴 자동 변형 양성 | `layer2/test_data/reperformed_positive/` | **60곡** | 폴더명은 예전 호환 이름. 실제 사람 재연주가 아니라 자동 편곡/구간 재배열/템포·피치·EQ·효과 변형. 기존 30곡 + 이번 신규 원곡 10곡에서 생성한 30곡. 신규 30곡은 모두 4분이며 `manifest.csv`에 원곡과 변형 방식이 기록됨. |
| 추가 두 방식 합성 양성 | `layer2/test_data/extended_positive/` | **180개** | 재녹음 시뮬레이션 90개 + 구간별 비균일 템포 90개. 각 방식은 원곡 30개 × 3단계. 전체 합성 양성은 340개. |
| 정상 편집 대조 | `layer2/test_data/safe_arranged/` | 30곡 | `music/`의 정상 후보에 유사 편집 효과를 적용한 대조군. 정상으로 독립 검증되지 않아 주 임계값 보정에 사용하지 않고 별도 관찰해야 함. |
| 분할 세그먼트 파일 | `segments/` | 15,699개 파일 | 기존 오디오를 잘라 만든 분석/임베딩 입력 산출물. 원곡 파일이나 양성/정상 라벨 데이터와 혼동하지 않음. |
| 실험 결과 | `layer2/artifacts/` | CSV/JSON/NPZ | 평가 결과·manifest·임베딩 캐시·중복 보고서. 음원 원본 폴더가 아님. |

## 이번 추가 작업 기록

최신 교체·증강 작업과 심사 대응 설명은 [현재 상태 정리](STATUS_SUMMARY_20261022.md)를 참고하세요. 아래 705곡 확장 기록은 교체 전 이력입니다.

- `premusic/` 922곡 중 목표 1,000곡에 필요한 **705곡만** `original_music/`으로 이동했습니다. 선정은 파일명에 담긴 제공자 슬러그를 기준으로 interleave하여 앞쪽 한 제공자에 편중되지 않도록 했습니다.
- 남은 217곡을 새 원본 DB에 다시 대조해 75곡 중복, 142곡 고유 예비곡으로 확인했습니다. 중복은 삭제하지 않았습니다.
- 새 원곡은 자동으로 양성으로 분류하지 않았습니다. 10곡을 출처로 골라 3종씩 자동 변형한 **별도 양성 테스트 30곡**을 생성했습니다.
- Layer 1 지문 인덱스는 새 1,000곡을 반영해 재생성했습니다.
- 이후 `music/` 중복 17곡을 백업 후 삭제하고 premusic에서 검증곡 17곡을 옮겼습니다. 최신 중복 보고서는 300개 모두 `NO_EXACT_MATCH`입니다. 교체 파일명·해시는 `layer2/artifacts/control_replacement_20261022/changes.json`에 기록했습니다.
- 보고서: `layer2/artifacts/pixabay_import_report.csv`, `layer2/artifacts/pixabay_source_log.csv`, `layer2/artifacts/music_duplicate_report.csv`.

## 지금 주의할 상태: Layer 2 CLAP 인덱스

`original_music/`에 곡을 추가해도 CLAP 임베딩 인덱스와 점수 임계값은 자동으로 완성되지 않습니다. 전체 재평가를 시작했지만 새 원본 815곡의 임베딩이 필요하고 실행 환경에서 GPU를 사용할 수 없어 장시간 작업으로 판단해 중단했습니다. 부분 계산 캐시는 `layer2/artifacts/evaluation_embedding_cache/`에 보존되어 있습니다.

따라서 현재 상태는 다음과 같습니다.

- Layer 1 검색 DB: 새 원본 1,000곡 반영 완료.
- Layer 2 CLAP 기준 라이브러리/임계값: **새 1,000곡 기준 재평가 미완료**. 현재 `top3_aggregation_evaluation.json`의 임계값을 새 DB에서 검증된 값으로 소개하면 안 됩니다.
- Layer 2 API 서버를 새 기준 라이브러리로 다시 시작하려면 CLAP 임베딩 생성/평가를 완료해야 합니다. CPU에서 시간이 오래 걸리므로 GPU 환경에서 실행하는 것을 권장합니다.

기존 점수 정책 파일을 읽는 API는 잠정값 `WARN 0.856638`, `HOLD 0.894406`을 사용합니다. 새 1,000곡 인덱스에 대한 재평가 전까지는 이를 최종 임계값으로 취급하지 않습니다.

## 다시 실행할 때

PowerShell에서 프로젝트 루트(`C:\블록체인`)를 기준으로 실행합니다.

```powershell
# 새 원본 폴더 기준 Layer 1 Chromaprint 인덱스 갱신
python layer1/upload_guard_api.py --build-index

# music 정상 대조 후보와 original_music 중복 보고서 갱신 (삭제하지 않는 미리보기)
python layer2/remove_duplicate_music.py

# Layer 2 전체 평가와 새 reference 임베딩 생성 (GPU 권장, 오래 걸릴 수 있음)
python layer2/evaluate_retrieval_baseline.py --include-reperformed
python layer2/evaluate_top3_aggregation.py --include-reperformed
```

## 출처 및 파일명 관리

가져온 Pixabay 파일은 기존 제공자명/음원 ID가 있는 파일명을 보존했습니다. `layer2/artifacts/pixabay_source_log.csv`에는 SHA-256이 기록되지만, 현재 `source_url`, `contributor`, `license_url` 칸은 비어 있습니다. 데이터셋을 팀 외부로 전달하거나 서비스 검증 자료로 쓸 때는 원 출처와 이용 조건을 확인해 채워야 합니다.

파일명을 바꾸면 `segment_manifest.csv`, 양성 manifest, 지문 인덱스와 source ID 참조가 끊길 수 있으므로 이름 변경 대신 이 분류표와 manifest를 기준으로 관리합니다.
