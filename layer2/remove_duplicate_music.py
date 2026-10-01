"""Find audio duplicates in music that also exist in original_music.

The comparison uses Chromaprint audio fingerprints, not file names. By default
the script only prints and saves a report. Pass --delete to remove files from
music whose complete fingerprint and duration match a file in original_music.
Files in original_music are never changed.

Examples:
    python layer2/remove_duplicate_music.py             # preview only
    python layer2/remove_duplicate_music.py --delete     # delete exact matches
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


# 프로젝트 폴더 안의 비교 대상 폴더와 결과 보고서 위치입니다.
PROJECT_DIR = Path(__file__).resolve().parent.parent
MUSIC_DIR = PROJECT_DIR / "music"
ORIGINAL_MUSIC_DIR = PROJECT_DIR / "original_music"
ARTIFACT_DIR = PROJECT_DIR / "layer2" / "artifacts"
REPORT_PATH = ARTIFACT_DIR / "music_duplicate_report.csv"

# 음원 지문 계산이 가능한 파일 형식만 검색합니다.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm", ".aac"}


@dataclass(frozen=True)
class AudioFingerprint:
    """한 음원 파일의 경로, 재생 길이, Chromaprint 지문을 보관합니다."""

    path: Path
    duration: float
    fingerprint: str


def find_fpcalc() -> str | None:
    """프로젝트 안의 fpcalc.exe 또는 시스템 PATH의 fpcalc를 찾습니다."""

    # 프로젝트 루트에 함께 둔 실행 파일을 우선 사용합니다.
    local_binary = PROJECT_DIR / "fpcalc.exe"
    if local_binary.is_file():
        return str(local_binary)

    # 다른 환경에서는 PATH에 등록된 fpcalc를 찾아 사용합니다.
    return shutil.which("fpcalc")


def find_audio_files(folder: Path) -> list[Path]:
    """폴더 아래에서 지원하는 음원 파일들을 정렬해 반환합니다."""

    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def calculate_fingerprint(fpcalc: str, audio_path: Path) -> AudioFingerprint:
    """fpcalc를 실행해 음원 길이와 전체 오디오 지문을 계산합니다."""

    # JSON 출력 모드를 사용해 길이와 지문을 안정적으로 읽습니다.
    result = subprocess.run(
        [fpcalc, "-json", str(audio_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    metadata = json.loads(result.stdout)
    return AudioFingerprint(
        path=audio_path,
        duration=float(metadata["duration"]),
        fingerprint=str(metadata["fingerprint"]),
    )


def is_exact_audio_duplicate(left: AudioFingerprint, right: AudioFingerprint) -> bool:
    """전체 지문이 일치하고 길이 차이가 1초 이내일 때만 중복으로 봅니다."""

    # 지문만 우연히 겹치는 경우를 더 줄이기 위해 재생 길이도 함께 확인합니다.
    return (
        left.fingerprint == right.fingerprint
        and abs(left.duration - right.duration) <= 1.0
    )


def save_report(rows: list[dict[str, str]]) -> None:
    """비교 결과 전체를 CSV 보고서로 기록합니다."""

    # 보고서 폴더를 만들고 UTF-8 BOM으로 저장해 Excel에서도 한글을 읽게 합니다.
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    columns = ["music_file", "matched_original_file", "status", "details"]
    with REPORT_PATH.open("w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def delete_music_file(path: Path) -> None:
    """검증된 중복 파일만 music 폴더 내부에서 삭제합니다."""

    # 경로가 music 폴더 내부인지 확인해 다른 폴더의 파일 삭제를 막습니다.
    resolved_music_dir = MUSIC_DIR.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_music_dir or resolved_music_dir not in resolved_path.parents:
        raise RuntimeError(f"삭제 경로가 music 폴더 밖입니다: {resolved_path}")

    # 파일만 삭제하며 폴더나 original_music의 원본은 건드리지 않습니다.
    resolved_path.unlink()


def main() -> None:
    """원본 폴더와 music 폴더를 대조하고, 요청 시 중복본만 삭제합니다."""

    # 기본 실행은 미리보기이며 --delete 옵션을 줘야 실제 파일을 삭제합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="original_music와 전체 지문이 일치하는 music 파일을 삭제합니다",
    )
    args = parser.parse_args()

    # 비교에 필요한 두 폴더와 fpcalc 실행 파일이 있는지 확인합니다.
    if not MUSIC_DIR.is_dir():
        raise SystemExit(f"비교 대상 폴더가 없습니다: {MUSIC_DIR}")
    if not ORIGINAL_MUSIC_DIR.is_dir():
        raise SystemExit(f"기준 원곡 폴더가 없습니다: {ORIGINAL_MUSIC_DIR}")
    fpcalc = find_fpcalc()
    if not fpcalc:
        raise SystemExit("fpcalc를 찾지 못했습니다. 프로젝트 루트에 fpcalc.exe를 두거나 PATH에 추가하세요.")

    # 기준 원곡들의 지문을 먼저 계산해 검색용 해시 표를 만듭니다.
    original_files = find_audio_files(ORIGINAL_MUSIC_DIR)
    music_files = find_audio_files(MUSIC_DIR)
    if not original_files:
        raise SystemExit(f"기준 원곡 파일이 없습니다: {ORIGINAL_MUSIC_DIR}")
    if not music_files:
        print(f"비교할 파일이 없습니다: {MUSIC_DIR}")
        return

    print(f"기준 원곡 {len(original_files)}개 지문 계산 중...")
    original_fingerprints: list[AudioFingerprint] = []
    rows: list[dict[str, str]] = []
    for audio_path in original_files:
        try:
            original_fingerprints.append(calculate_fingerprint(fpcalc, audio_path))
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
            rows.append(
                {
                    "music_file": "",
                    "matched_original_file": str(audio_path),
                    "status": "ORIGINAL_ERROR",
                    "details": str(error),
                }
            )
            print(f"[기준 파일 오류] {audio_path.name}: {error}")

    # music의 각 파일을 기준 원곡 전체와 비교합니다.
    deleted_count = 0
    duplicate_count = 0
    print(f"music 파일 {len(music_files)}개 비교 중...")
    for music_path in music_files:
        try:
            candidate = calculate_fingerprint(fpcalc, music_path)
            matches = [
                reference for reference in original_fingerprints
                if is_exact_audio_duplicate(candidate, reference)
            ]

            if matches:
                duplicate_count += 1
                matched_names = " | ".join(str(match.path) for match in matches)
                if args.delete:
                    delete_music_file(music_path)
                    status = "DELETED_EXACT_DUPLICATE"
                    deleted_count += 1
                    print(f"[삭제] {music_path.name} == {matches[0].path.name}")
                else:
                    status = "DUPLICATE_PREVIEW"
                    print(f"[중복 후보] {music_path.name} == {matches[0].path.name}")

                rows.append(
                    {
                        "music_file": str(music_path),
                        "matched_original_file": matched_names,
                        "status": status,
                        "details": "전체 Chromaprint 지문 일치, 길이 차이 1초 이내",
                    }
                )
            else:
                rows.append(
                    {
                        "music_file": str(music_path),
                        "matched_original_file": "",
                        "status": "NO_EXACT_MATCH",
                        "details": "완전 일치 지문 없음; 파일 유지",
                    }
                )
                print(f"[유지] {music_path.name}")

        except (OSError, ValueError, KeyError, subprocess.CalledProcessError, RuntimeError) as error:
            # 지문을 읽지 못한 파일은 중복 여부를 알 수 없으므로 절대 삭제하지 않습니다.
            rows.append(
                {
                    "music_file": str(music_path),
                    "matched_original_file": "",
                    "status": "ERROR_KEPT",
                    "details": str(error),
                }
            )
            print(f"[오류 - 유지] {music_path.name}: {error}")

    # 어떤 파일을 유지/삭제했는지 나중에 확인할 수 있도록 보고서를 저장합니다.
    save_report(rows)
    print(f"\n비교 완료: 중복 {duplicate_count}개, 실제 삭제 {deleted_count}개")
    print(f"보고서: {REPORT_PATH}")
    if not args.delete and duplicate_count:
        print("미리보기만 수행했습니다. 실제 삭제하려면 --delete 옵션을 붙여 다시 실행하세요.")


if __name__ == "__main__":
    main()
