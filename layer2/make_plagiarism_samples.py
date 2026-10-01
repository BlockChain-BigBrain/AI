"""Create synthetic positive queries from original tracks for Layer 2 evaluation.

This script does not modify originals and does not train a model. It creates
short altered excerpts that should still match their source recording, then
records the source/transform details in a CSV manifest.

Example (default: first 30 source tracks, 3 queries per track):
    python layer2/make_plagiarism_samples.py

To process a different number of source tracks:
    python layer2/make_plagiarism_samples.py --limit 50
    python layer2/make_plagiarism_samples.py --limit 0  # all source tracks
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
from pathlib import Path


# 프로젝트의 원곡 보관 폴더입니다. 원곡 파일은 읽기만 합니다.
PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_DIR / "original_music"

# 생성한 양성 테스트 파일과 정답 목록을 별도 폴더에 저장합니다.
OUTPUT_DIR = PROJECT_DIR / "layer2" / "test_data" / "plagiarism_positive"
MANIFEST_PATH = OUTPUT_DIR / "manifest.csv"

# 처리할 수 있는 오디오 파일 확장자입니다.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm", ".aac"}

# CLAP 비교를 위한 표준 샘플레이트입니다.
SAMPLE_RATE = 48_000


def find_ffmpeg() -> str | None:
    """PATH, 환경 변수 또는 imageio-ffmpeg에서 ffmpeg 실행 파일을 찾습니다."""

    # 사용자가 직접 지정한 ffmpeg 경로를 가장 먼저 사용합니다.
    configured_path = os.environ.get("FFMPEG_EXE")
    if configured_path and Path(configured_path).is_file():
        return configured_path

    # 시스템 PATH에 ffmpeg가 등록되어 있으면 해당 실행 파일을 사용합니다.
    path_command = shutil.which("ffmpeg")
    if path_command:
        return path_command

    # imageio-ffmpeg 패키지가 설치되어 있으면 패키지에 포함된 실행 파일을 씁니다.
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def audio_duration_seconds(ffmpeg: str, source_path: Path) -> float:
    """ffmpeg의 입력 분석 결과에서 원곡 길이를 초 단위로 가져옵니다."""

    # ffmpeg가 출력하는 메타정보(stderr)를 읽어 duration 값을 찾습니다.
    result = subprocess.run(
        [ffmpeg, "-i", str(source_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined_output = result.stderr + result.stdout

    # 예: Duration: 00:03:12.45 형식의 정보를 시간/분/초로 변환합니다.
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", combined_output)
    if not match:
        raise RuntimeError("ffmpeg 출력에서 음원 길이를 읽지 못했습니다.")

    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def make_output_name(source_path: Path, variant_number: int) -> str:
    """원곡 파일명과 변형 번호를 이용해 충돌 가능성이 낮은 출력 이름을 만듭니다."""

    # 파일명에 포함된 공백과 한글은 유지하고, 확장자만 MP3로 바꿉니다.
    return f"{source_path.stem}__positive_v{variant_number:02d}.mp3"


def transform_filters(variant_number: int) -> tuple[str, str]:
    """테스트 변형별 ffmpeg 필터와 사람이 읽을 설명을 돌려줍니다."""

    # 첫 변형은 원본 음색을 유지하고 MP3로 다시 인코딩합니다.
    if variant_number == 1:
        return "anull", "부분 구간 추출 + MP3 재인코딩"

    # 두 번째 변형은 음량과 EQ를 조정해도 원곡을 찾는지 시험합니다.
    if variant_number == 2:
        return "volume=0.78,equalizer=f=250:t=q:w=1:g=-2", "부분 구간 + 음량/EQ 변경"

    # 세 번째 변형은 속도와 피치를 약 2% 높여 변형에 대한 견고성을 시험합니다.
    # asetrate로 피치를 올린 뒤 atempo로 길이를 거의 원래대로 맞춥니다.
    speed_factor = 1.02
    tempo_factor = 1.0 / speed_factor
    return (
        f"asetrate={SAMPLE_RATE}*{speed_factor},aresample={SAMPLE_RATE},atempo={tempo_factor:.8f}",
        "부분 구간 + 속도/피치 약 2% 변경",
    )


def create_query(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
    variant_number: int,
) -> str:
    """원곡에서 일부 구간을 뽑아 변형 MP3 테스트 파일을 생성합니다."""

    filters, transform_description = transform_filters(variant_number)

    # -ss/-t로 원곡의 일부만 추출하고, 필터를 적용해 MP3로 저장합니다.
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(source_path),
        "-t",
        f"{duration_seconds:.3f}",
        "-vn",
        "-af",
        filters,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output_path),
    ]

    # 실패한 파일은 성공한 것처럼 남지 않도록, 오류 내용을 그대로 보여줍니다.
    subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return transform_description


def main() -> None:
    """원곡 일부를 변형해 양성 쿼리와 출처 매니페스트를 생성합니다."""

    # 기본은 원곡 30곡만 사용해 디스크와 처리 시간을 관리합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="처리할 원곡 수 (0은 전체)")
    parser.add_argument("--variants", type=int, default=3, help="원곡마다 만들 변형 쿼리 수 (1~3)")
    parser.add_argument("--duration", type=float, default=30.0, help="각 테스트 조각 길이(초)")
    parser.add_argument("--seed", type=int, default=42, help="구간 위치를 재현하기 위한 난수 시드")
    args = parser.parse_args()

    # 잘못된 옵션으로 예기치 않은 양의 파일을 만들지 않도록 입력을 검사합니다.
    if args.limit < 0:
        raise SystemExit("--limit은 0 이상이어야 합니다.")
    if not 1 <= args.variants <= 3:
        raise SystemExit("--variants는 1, 2, 3 중 하나여야 합니다.")
    if args.duration < 10:
        raise SystemExit("--duration은 10초 이상으로 지정해 주세요.")
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"원곡 폴더를 찾을 수 없습니다: {SOURCE_DIR}")

    # 지원하는 형식의 원곡만 정렬해서 선택합니다.
    source_files = sorted(
        path for path in SOURCE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    if args.limit:
        source_files = source_files[: args.limit]
    if not source_files:
        raise SystemExit(f"처리할 오디오 파일이 없습니다: {SOURCE_DIR}")

    # ffmpeg가 없으면 실행 가능한 경로와 해결 방법을 안내합니다.
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SystemExit(
            "ffmpeg를 찾지 못했습니다. imageio-ffmpeg를 설치하거나 "
            "FFMPEG_EXE 환경 변수에 ffmpeg.exe 경로를 지정하세요."
        )

    # 결과 폴더를 만들고 기존 매니페스트가 있으면 뒤에 이어 씁니다.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_exists = MANIFEST_PATH.exists()
    written_count = 0
    skipped_count = 0
    failed_count = 0
    rng = random.Random(args.seed)

    with MANIFEST_PATH.open("a", newline="", encoding="utf-8-sig") as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=[
                "query_path",
                "source_path",
                "source_track_id",
                "variant",
                "start_seconds",
                "duration_seconds",
                "transform",
                "label",
            ],
        )

        # 새 매니페스트에만 열 이름을 한 번 씁니다.
        if not manifest_exists or MANIFEST_PATH.stat().st_size == 0:
            writer.writeheader()

        # 각 원곡의 서로 다른 위치에서 변형된 테스트 구간을 만듭니다.
        for source_index, source_path in enumerate(source_files, start=1):
            try:
                source_duration = audio_duration_seconds(ffmpeg, source_path)
                clip_duration = min(args.duration, source_duration)
                if clip_duration < 10:
                    print(f"[건너뜀] 10초 미만 음원: {source_path.name}")
                    skipped_count += args.variants
                    continue

                # 변형마다 구간 위치를 다르게 골라 원곡 여러 부분을 시험합니다.
                max_start = max(0.0, source_duration - clip_duration)
                candidate_positions = [
                    max_start * 0.15,
                    max_start * 0.50,
                    max_start * 0.80,
                ]
                rng.shuffle(candidate_positions)

                for variant_number in range(1, args.variants + 1):
                    output_path = OUTPUT_DIR / make_output_name(source_path, variant_number)
                    if output_path.exists():
                        print(f"[건너뜀] 이미 존재: {output_path.name}")
                        skipped_count += 1
                        continue

                    start_seconds = candidate_positions[variant_number - 1]
                    transform_description = create_query(
                        ffmpeg,
                        source_path,
                        output_path,
                        start_seconds,
                        clip_duration,
                        variant_number,
                    )

                    # 테스트 쿼리와 기준 원곡을 연결하는 정답 정보를 기록합니다.
                    writer.writerow(
                        {
                            "query_path": str(output_path.resolve()),
                            "source_path": str(source_path.resolve()),
                            "source_track_id": source_path.stem,
                            "variant": variant_number,
                            "start_seconds": round(start_seconds, 3),
                            "duration_seconds": round(clip_duration, 3),
                            "transform": transform_description,
                            "label": "positive_same_source",
                        }
                    )
                    manifest_file.flush()
                    written_count += 1
                    print(f"[생성] {source_index}/{len(source_files)} {output_path.name}")

            except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
                # 특정 파일이 손상됐어도 나머지 원곡 처리를 계속합니다.
                failed_count += args.variants
                details = getattr(error, "stderr", None) or str(error)
                print(f"[오류] {source_path.name}: {details}")

    # 결과를 요약해 다음 평가 단계에서 확인하기 쉽게 출력합니다.
    summary = {
        "source_dir": str(SOURCE_DIR),
        "selected_source_count": len(source_files),
        "variants_per_source": args.variants,
        "generated_query_count": written_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "output_dir": str(OUTPUT_DIR),
        "manifest": str(MANIFEST_PATH),
    }
    summary_path = OUTPUT_DIR / "generation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
