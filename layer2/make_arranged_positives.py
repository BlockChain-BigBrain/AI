"""Create 3-minute synthetic arrangement tests from held-out original tracks.

By default, the script selects 10 original tracks that are not in the current
training catalog and creates three 4-minute-source transformations per track.
The generated queries and their source metadata are recorded in the manifest
already read by evaluate_retrieval_baseline.py.

Run from the project root:
    python layer2/make_arranged_positives.py

These are automated robustness tests, not human performances or proof of
plagiarism. Each resulting audio file is checked to be at least 180 seconds.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


# Find project data relative to the script, not the shell's current directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
LAYER2_DIR = PROJECT_DIR / "layer2"
SOURCE_DIR = PROJECT_DIR / "original_music"
CATALOG_PATH = LAYER2_DIR / "artifacts" / "segment_manifest.csv"
OUTPUT_DIR = LAYER2_DIR / "test_data" / "reperformed_positive"
MANIFEST_PATH = OUTPUT_DIR / "manifest.csv"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm", ".aac"}
SAMPLE_RATE = 22_050
SOURCE_EXCERPT_SECONDS = 240.0
MIN_QUERY_SECONDS = 180.0
MIN_SOURCE_SECONDS = 90.0
CASE_TYPES = ("section_edit", "tempo_pitch_eq", "remix_fx")


def find_ffmpeg() -> str:
    """Find FFmpeg on PATH or use the executable bundled with imageio-ffmpeg."""
    import shutil

    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        raise SystemExit(
            "ffmpeg를 찾지 못했습니다. imageio-ffmpeg를 설치하거나 PATH에 ffmpeg.exe를 추가하세요."
        ) from error


def audio_files(folder: Path) -> list[Path]:
    """List supported audio files under a folder in a stable order."""
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def read_training_ids() -> set[str]:
    """Read source IDs already used for training, to keep these queries held out."""
    if not CATALOG_PATH.is_file():
        raise SystemExit(f"Training segment manifest is missing: {CATALOG_PATH}")
    with CATALOG_PATH.open("r", newline="", encoding="utf-8-sig") as manifest_file:
        rows = csv.DictReader(manifest_file)
        if "track_id" not in (rows.fieldnames or []):
            raise SystemExit(f"Training manifest has no track_id column: {CATALOG_PATH}")
        return {row["track_id"] for row in rows if row.get("track_id")}


def duration_seconds(ffmpeg: str, path: Path) -> float:
    """Ask FFmpeg for a source duration without fully decoding the audio."""
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError("ffmpeg에서 원본 음원의 길이를 읽지 못했습니다.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def decode_excerpt(ffmpeg: str, path: Path, offset: float) -> np.ndarray:
    """Decode a four-minute mono excerpt to float32 samples."""
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1",
            "-ss", f"{offset:.3f}",
            "-i", str(path), "-t", str(SOURCE_EXCERPT_SECONDS), "-vn", "-ac", "1",
            "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1",
        ],
        capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    samples = np.frombuffer(result.stdout, dtype="<f4").copy()
    if len(samples) < int(MIN_QUERY_SECONDS * SAMPLE_RATE):
        raise ValueError("원본에서 3분 이상 테스트 음원을 만들 만큼 오디오를 읽지 못했습니다.")
    return samples


def save_wav(path: Path, samples: np.ndarray) -> float:
    """Normalize and save generated audio, returning its duration in seconds."""
    samples = np.nan_to_num(samples.astype(np.float32), copy=False)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 0.98:
        samples *= 0.98 / peak
    sf.write(path, samples, SAMPLE_RATE, subtype="PCM_16")
    return len(samples) / SAMPLE_RATE


def make_section_edit(samples: np.ndarray, rng: random.Random) -> tuple[np.ndarray, dict]:
    """Reorder 24-second sections and repeat one section to change song structure."""
    block_size = 24 * SAMPLE_RATE
    blocks = [samples[i:i + block_size] for i in range(0, len(samples), block_size)]
    blocks = [block for block in blocks if len(block) == block_size]
    order = list(range(len(blocks)))
    rng.shuffle(order)
    order.insert(rng.randrange(len(order) + 1), rng.choice(order))
    return np.concatenate([blocks[index] for index in order]), {
        "edit": "reorder_and_repeat_sections", "section_seconds": 24, "section_order": order,
    }


def make_filtered_case(
    ffmpeg: str, source: Path, offset: float, output: Path, case_type: str,
    rng: random.Random,
) -> dict:
    """Create a long tempo/key/EQ variation with FFmpeg's fast audio filters."""
    if case_type == "tempo_pitch_eq":
        # Changing the sample rate changes pitch and playback speed together.
        rate = round(rng.uniform(1.03, 1.12), 4)
        eq_db = round(rng.uniform(-3.0, 3.0), 1)
        filters = (
            f"asetrate={SAMPLE_RATE}*{rate},aresample={SAMPLE_RATE},"
            f"equalizer=f=1200:t=q:w=1:g={eq_db}"
        )
        parameters = {"speed_and_pitch_ratio": rate, "eq_1200hz_db": eq_db}
    else:
        # A mild tempo change, EQ, and short echo produce a different mix.
        tempo = round(rng.uniform(0.94, 0.98), 4)
        bass_db = round(rng.uniform(-2.0, 2.0), 1)
        filters = (
            f"atempo={tempo},equalizer=f=180:t=q:w=1:g={bass_db},"
            "aecho=0.8:0.75:70:0.12"
        )
        parameters = {"tempo_rate": tempo, "bass_eq_db": bass_db, "echo": "mild"}

    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-stream_loop", "-1",
            "-ss", f"{offset:.3f}",
            "-i", str(source), "-t", str(SOURCE_EXCERPT_SECONDS), "-vn", "-af", filters,
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return parameters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="Сонголт ба хувиргалтыг давтан гаргах үр")
    parser.add_argument("--sources", type=int, default=10, help="고를 원곡 개수 (기본값 10)")
    args = parser.parse_args()
    if args.sources < 1:
        raise SystemExit("--sources는 1 이상이어야 합니다.")
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"원곡 폴더가 없습니다: {SOURCE_DIR}")

    ffmpeg = find_ffmpeg()
    trained_ids = read_training_ids()
    candidates = [path for path in audio_files(SOURCE_DIR) if path.stem not in trained_ids]
    eligible: list[tuple[Path, float]] = []
    for index, path in enumerate(candidates, start=1):
        try:
            length = duration_seconds(ffmpeg, path)
        except Exception as error:
            print(f"[건너뜀] {path.name}: {error}", flush=True)
            continue
        if length >= MIN_SOURCE_SECONDS:
            eligible.append((path, length))
        if index % 25 == 0:
            print(f"원곡 길이 확인: {index}/{len(candidates)}", flush=True)

    if len(eligible) < args.sources:
        raise SystemExit(
            f"미학습 원곡 중 90초 이상인 곡은 {len(eligible)}개입니다. "
            f"요청한 {args.sources}개를 고를 수 없습니다."
        )

    rng = random.Random(args.seed)
    chosen = rng.sample(eligible, args.sources)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_rows: list[dict[str, str]] = []
    if MANIFEST_PATH.is_file():
        with MANIFEST_PATH.open("r", newline="", encoding="utf-8-sig") as manifest:
            existing_rows = list(csv.DictReader(manifest))
    existing_queries = {row.get("query_path", "") for row in existing_rows}
    new_rows: list[dict[str, str]] = []

    for song_index, (source, source_duration) in enumerate(chosen, start=1):
        song_rng = random.Random(args.seed * 1000 + song_index)
        max_offset = max(0.0, source_duration - SOURCE_EXCERPT_SECONDS)
        offset = song_rng.uniform(0.0, max_offset) if max_offset else 0.0
        source_audio = decode_excerpt(ffmpeg, source, offset)
        # First case: make and save reordered/repeated song sections.
        case_rng = random.Random(args.seed + song_index * 101)
        edited_audio, edit_parameters = make_section_edit(source_audio.copy(), case_rng)
        cases: list[tuple[str, Path, dict, float]] = []
        section_path = OUTPUT_DIR / f"{source.stem}__section_edit__seed{args.seed}.wav"
        section_duration = save_wav(section_path, edited_audio)
        cases.append(("section_edit", section_path, edit_parameters, section_duration))

        # Second and third cases use FFmpeg filters and preserve a full-length excerpt.
        for case_type in CASE_TYPES[1:]:
            output = OUTPUT_DIR / f"{source.stem}__{case_type}__seed{args.seed}.wav"
            parameters = make_filtered_case(
                ffmpeg, source, offset, output, case_type,
                random.Random(args.seed + song_index * 100 + len(cases)),
            )
            case_duration = duration_seconds(ffmpeg, output)
            cases.append((case_type, output, parameters, case_duration))

        for case_type, output, parameters, case_duration in cases:
            resolved_output = str(output.resolve())
            if case_duration < MIN_QUERY_SECONDS:
                raise RuntimeError(f"생성된 음원이 3분보다 짧습니다: {output.name}")
            if resolved_output in existing_queries:
                raise SystemExit(
                    f"Manifest-д өмнө нь бүртгэлтэй файл байна: {output.name}. "
                    "중복 생성을 막기 위해 중단했습니다."
                )
            new_rows.append({
                "query_path": resolved_output,
                "source_path": str(source.resolve()),
                "source_track_id": source.stem,
                "recording_type": "synthetic_arrangement_test",
                "case_type": case_type,
                "source_offset_seconds": f"{offset:.3f}",
                "source_duration_seconds": f"{source_duration:.3f}",
                "query_duration_seconds": f"{case_duration:.3f}",
                "seed": str(args.seed),
                "parameters_json": json.dumps(parameters, ensure_ascii=False),
                "label": "positive_synthetic_arrangement",
            })
            print(f"[{song_index}/{args.sources}] {case_type}: {output.name} ({case_duration/60:.2f} мин)", flush=True)

    # Keep any earlier manual arrangement rows and append the generated cases.
    columns = [
        "query_path", "source_path", "source_track_id", "recording_type", "case_type",
        "source_offset_seconds", "source_duration_seconds", "query_duration_seconds",
        "seed", "parameters_json", "label",
    ]
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8-sig") as manifest:
        writer = csv.DictWriter(manifest, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing_rows + new_rows)
    print(f"完成: {len(new_rows)} 사례 ({args.sources}곡 × 3종)")
    print(f"Manifest: {MANIFEST_PATH}")
    print("참고: 자동 생성된 유사성 시험 사례로, 사람이 직접 연주한 편곡은 아닙니다.")


if __name__ == "__main__":
    main()
