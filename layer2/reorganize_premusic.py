"""Move evaluated premusic assets to labelled folders and remove exact duplicates.

Every deleted file must have a byte-identical surviving copy. A reviewed plan
is written before --apply. No recursive filesystem operations are used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "premusic"
USED = ROOT / "premusic_used"
ART = ROOT / "layer2" / "artifacts"
HOLDOUT = ROOT / ".runtime-tests" / "premusic-holdout-20261029"
PLAN = USED / "reorganization_plan_20261029.json"
RESULT = USED / "reorganization_result_20261029.json"
AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inside(path: Path, parent: Path):
    path = path.resolve()
    if not path.is_relative_to(parent.resolve()):
        raise RuntimeError(f"Unsafe path outside {parent}: {path}")
    return path


def prior_usage():
    uses = defaultdict(set)
    old = json.loads((ROOT / "layer2/test_data/fresh_audit/manifest.json").read_text(encoding="utf-8"))
    for row in old["rows"]:
        if row.get("label") == "unverified_normal_candidate" and Path(row.get("source_path", "")).parent.name == "premusic":
            uses[Path(row["source_path"]).name].add("fresh_audit_20261023")
    old = json.loads((ROOT / "layer2/test_data/ai_labeled_positive/manifest.json").read_text(encoding="utf-8"))
    for row in old["rows"]:
        if row.get("dataset") == "premusic_audit":
            uses[Path(row["file"]).name].add("ai_labeled_diagnostic_20261024")
    fresh = json.loads((HOLDOUT / "frozen_selection.json").read_text(encoding="utf-8"))
    if fresh["selected_count"] != 50:
        raise RuntimeError("Unexpected holdout selection")
    for row in fresh["selected"]:
        uses[row["name"]].add("premusic_holdout_20261029")
    if len(uses) != 81:
        raise RuntimeError(f"Expected 81 distinct evaluated premusic originals, found {len(uses)}")
    return uses


def build_plan():
    if RESULT.exists():
        raise RuntimeError("Reorganization has already been applied")
    provenance = ART / "pixabay_provenance/file_audit.csv"
    with provenance.open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    if len(records) != 1500:
        raise RuntimeError("Expected the audited 1,500-file inventory")
    premusic = sorted(p for p in PRE.iterdir() if p.is_file() and p.suffix.lower() in AUDIO)
    if len(premusic) != 200:
        raise RuntimeError(f"Expected original 200 premusic files, found {len(premusic)}")
    by_file = {(r["folder"], Path(r["file"]).name): r for r in records}
    by_sha = defaultdict(list)
    for row in records:
        by_sha[row["sha256"]].append((row["folder"], Path(row["file"]).name))
    uses = prior_usage()
    for path in premusic:
        expected = by_file[("premusic", path.name)]["sha256"]
        if sha(path) != expected:
            raise RuntimeError(f"Premusic file changed since identity audit: {path.name}")

    moves = []
    for name, labels in sorted(uses.items()):
        source = inside(PRE / name, PRE)
        if not source.is_file():
            raise RuntimeError(f"Evaluated original missing: {name}")
        primary = "premusic_holdout_20261029" if "premusic_holdout_20261029" in labels else (
            "fresh_audit_20261023" if "fresh_audit_20261023" in labels else "ai_labeled_diagnostic_20261024")
        dest = inside(USED / primary / name, USED)
        moves.append({"original_path": str(source), "new_path": str(dest),
                      "sha256": by_file[("premusic", name)]["sha256"], "used_in": sorted(labels)})
    move_by_name = {Path(m["original_path"]).name: m for m in moves}

    # Delete only exact-byte duplicates. Keep indexed/catalog copies, evaluated
    # copies in USED, and one canonical premusic copy for internal-only pairs.
    delete = []
    remain = []
    for path in premusic:
        if path.name in move_by_name:
            continue
        entry = by_file[("premusic", path.name)]
        matches = by_sha[entry["sha256"]]
        keepers = []
        for folder, name in matches:
            if folder in ("original_music", "music"):
                keepers.append(ROOT / folder / name)
            elif name in move_by_name:
                keepers.append(Path(move_by_name[name]["new_path"]))
        if not keepers:
            other_premusic = [name for folder, name in matches if folder == "premusic"]
            if len(other_premusic) > 1:
                canonical = min(other_premusic, key=lambda n: ("(1)" in n, n.casefold()))
                if canonical != path.name:
                    keepers.append(PRE / canonical)
        if keepers:
            keeper = keepers[0]
            if keeper == path:
                raise RuntimeError("A duplicate cannot be its own retained copy")
            delete.append({"deleted_path": str(inside(path, PRE)), "sha256": entry["sha256"],
                           "identical_copy_retained_at": str(keeper)})
        else:
            remain.append(path.name)
    if len(moves) != 81 or len(delete) != 78 or len(remain) != 41:
        raise RuntimeError(f"Unexpected partition: move={len(moves)}, delete={len(delete)}, remain={len(remain)}")
    deleted_names = {Path(d["deleted_path"]).name for d in delete}
    for item in delete:
        keeper = Path(item["identical_copy_retained_at"])
        if keeper.parent == PRE and keeper.name in deleted_names:
            raise RuntimeError("Plan would delete all copies of a duplicate group")
    return {"date": "2026-10-29", "status": "reviewed_before_mutation",
        "original_premusic_count": 200, "move_count": 81, "delete_exact_duplicate_count": 78,
        "remain_count": 41, "all_deletes_have_identical_surviving_copy": True,
        "moves": moves, "exact_duplicate_deletions": delete, "remaining_filenames": sorted(remain),
        "historical_manifest_paths_remain_original": True,
        "note": "Use the relocation manifest to resolve old evaluation paths; do not rewrite frozen historical manifests."}


def apply(plan):
    if RESULT.exists():
        existing = json.loads(RESULT.read_text(encoding="utf-8"))
        print(json.dumps({"status": "already_applied", "moved": existing["moved"],
                          "exact_duplicates_deleted": existing["exact_duplicates_deleted"],
                          "premusic_remaining": existing["premusic_remaining"]}, ensure_ascii=False))
        return
    # Validate the entire plan before the first mutation.
    for move in plan["moves"]:
        src = inside(Path(move["original_path"]), PRE)
        dst = inside(Path(move["new_path"]), USED)
        if dst.exists():
            if sha(dst) != move["sha256"]:
                raise RuntimeError(f"Destination collision: {dst}")
        elif not src.is_file() or sha(src) != move["sha256"]:
            raise RuntimeError(f"Move source missing/changed: {src}")
    for item in plan["exact_duplicate_deletions"]:
        src = inside(Path(item["deleted_path"]), PRE)
        if src.exists() and sha(src) != item["sha256"]:
            raise RuntimeError(f"Delete candidate changed: {src}")
    for i, move in enumerate(plan["moves"], 1):
        src, dst = Path(move["original_path"]), Path(move["new_path"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            src.rename(dst)
        if sha(dst) != move["sha256"] or src.exists():
            raise RuntimeError(f"Move verification failed: {src}")
        if i % 20 == 0:
            print(f"[move] {i}/81", flush=True)
    # Recheck every retained copy after all moves before any unlink.
    for item in plan["exact_duplicate_deletions"]:
        keeper = Path(item["identical_copy_retained_at"])
        if not keeper.is_file() or sha(keeper) != item["sha256"]:
            raise RuntimeError(f"Identical surviving copy absent: {keeper}")
    for i, item in enumerate(plan["exact_duplicate_deletions"], 1):
        src = inside(Path(item["deleted_path"]), PRE)
        if src.exists():
            if sha(src) != item["sha256"]:
                raise RuntimeError(f"Delete candidate changed: {src}")
            src.unlink()
        if i % 20 == 0:
            print(f"[remove exact duplicate] {i}/78", flush=True)
    remaining = sorted(p.name for p in PRE.iterdir() if p.is_file() and p.suffix.lower() in AUDIO)
    if remaining != plan["remaining_filenames"]:
        raise RuntimeError("Remaining premusic files do not match the reviewed plan")
    for move in plan["moves"]:
        if sha(Path(move["new_path"])) != move["sha256"]:
            raise RuntimeError("A moved file changed after reorganization")
    result = {"date": "2026-10-29", "status": "completed", "moved": 81,
        "exact_duplicates_deleted": 78, "premusic_remaining": 41,
        "deleted_audio_has_identical_retained_copy": True,
        "used_folder_counts": {folder: len(list((USED / folder).glob("*.mp3")))
                               for folder in ("fresh_audit_20261023", "ai_labeled_diagnostic_20261024", "premusic_holdout_20261029")},
        "historical_usage_relocations": str(PLAN),
        "pure_ai_creation_verified_by_this_operation": False}
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "premusic_reorganization_20261029.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (USED / "usage_manifest.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["original_path", "new_path", "sha256", "used_in"])
        writer.writeheader()
        for move in plan["moves"]:
            writer.writerow({**move, "used_in": ";".join(move["used_in"])})
    (USED / "README.md").write_text(
        "# premusic 사용 이력\n\n"
        "Pixabay에서 받은 premusic 원본 중 평가에 사용한 81곡을 용도별로 옮겼습니다. "
        "`usage_manifest.csv`에 이전 위치, 현재 위치, SHA-256, 사용한 평가를 기록했습니다. "
        "한 곡은 2026-10-23 진단과 2026-10-24 AI 표시군 진단에 모두 사용돼 사용 이력이 두 개입니다.\n\n"
        "- `fresh_audit_20261023/`: 이전 정상후보 진단 30곡\n"
        "- `ai_labeled_diagnostic_20261024/`: 이전 AI 표시군 진단에서만 사용한 1곡\n"
        "- `premusic_holdout_20261029/`: 이번 신규 정상후보 진단 50곡\n\n"
        "premusic에서 제거한 중복 파일 78개는 원곡·music·이 폴더 또는 남은 premusic에 바이트 단위로 동일한 보존본이 있습니다. "
        "각 삭제 파일과 보존본의 경로는 `reorganization_plan_20261029.json`에 있습니다. "
        "과거 평가 manifest의 원래 경로는 연구 기록으로 남겼으며, 재현 시 이 대응표로 현재 파일을 찾으세요.\n\n"
        "Pixabay 다운로드 출처만으로 AI 생성 여부가 입증되지는 않습니다.\n",
        encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    USED.mkdir(exist_ok=True)
    if RESULT.exists():
        completed = json.loads(RESULT.read_text(encoding="utf-8"))
        print(json.dumps({k: completed[k] for k in ("status", "moved", "exact_duplicates_deleted",
            "premusic_remaining", "used_folder_counts")}, ensure_ascii=False, indent=2))
        return
    if PLAN.exists():
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
    else:
        plan = build_plan()
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        apply(plan)
    else:
        print(json.dumps({k: plan[k] for k in ("status", "original_premusic_count", "move_count",
            "delete_exact_duplicate_count", "remain_count", "all_deletes_have_identical_surviving_copy")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
