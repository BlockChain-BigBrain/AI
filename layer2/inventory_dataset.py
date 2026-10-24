"""현재 음원·평가 manifest 구성을 한 번에 요약합니다.

이 스크립트는 오디오를 읽거나 임베딩을 만들지 않습니다. 파일 개수와 manifest
행 수만 세어, DB 확장 전 데이터 구성을 확인하는 용도로 사용합니다.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".webm", ".m4a", ".ogg", ".aac", ".wma"}


def count_audio(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)


def count_manifest(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def count_duplicate_status(path: Path, status: str) -> int | None:
    """Count one status in the current music-vs-reference duplicate report."""
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("status") == status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "layer2" / "artifacts" / "dataset_inventory.json")
    args = parser.parse_args()

    test_root = ROOT / "layer2" / "test_data"
    duplicate_report = ROOT / "layer2" / "artifacts" / "music_duplicate_report.csv"
    result = {
        "reference_tracks": count_audio(ROOT / "original_music"),
        "normal_audio_files": count_audio(ROOT / "music"),
        "normal_verified_no_exact_duplicate": count_duplicate_status(duplicate_report, "NO_EXACT_MATCH"),
        "normal_exact_duplicates_excluded": count_duplicate_status(duplicate_report, "DUPLICATE_PREVIEW"),
        "synthetic_positive": count_manifest(test_root / "plagiarism_positive" / "manifest.csv"),
        "synthetic_layered_positive": count_manifest(test_root / "synthetic_layered_positive" / "manifest.csv"),
        "synthetic_extended_positive": count_manifest(test_root / "extended_positive" / "manifest.csv"),
        "synthetic_arrangement_positive_excluded_by_default": count_manifest(test_root / "reperformed_positive" / "manifest.csv"),
        "safe_arranged_controls": count_manifest(test_root / "safe_arranged" / "manifest.csv"),
        "policy": {
            "primary_positive_scope": "synthetic_transformations_only",
            "reperformed_in_primary_evaluation": False,
            "reference_target": 1000,
            "synthetic_positive_target": 300,
            "normal_test_target": 200,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
