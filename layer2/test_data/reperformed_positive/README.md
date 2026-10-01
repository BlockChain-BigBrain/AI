# 실제 재연주·편곡 양성 평가 데이터

이 폴더는 원곡과 별도로 연주하거나 편곡해 만든 양성 쿼리를 저장합니다.
`plagiarism_positive`의 속도·EQ·MP3 변형 파일은 같은 녹음의 변형이므로 이 폴더에 복사하지 않습니다.

## 추가 방법

1. 원곡과 다른 연주/편곡으로 만든 오디오를 이 폴더에 둡니다.
2. `manifest.csv`에 한 줄을 추가합니다.
3. `query_path`에는 재연주/편곡 파일의 전체 경로를, `source_path`에는 `original_music`의 대응 원곡 전체 경로를 씁니다.
4. `source_track_id`에는 대응 원곡의 확장자를 뺀 파일명을 씁니다.
5. `recording_type`에는 `cover`, `rearrangement`, `melody_reperformance` 중 해당하는 유형을 적고, `notes`에는 만든 방법을 기록합니다.

예시:

```csv
query_path,source_path,source_track_id,recording_type,notes
C:\\블록체인\\layer2\\test_data\\reperformed_positive\\cover_01.wav,C:\\블록체인\\original_music\\source_song.mp3,source_song,cover,기타로 멜로디를 다시 연주
```

현재 프로젝트에 이런 실제 재연주 파일이 아직 없으면 매니페스트만 비어 있게 둡니다.
원곡 파일에 EQ나 피치 변경만 적용한 음원은 실제 재연주 사례로 라벨링하지 않습니다.
