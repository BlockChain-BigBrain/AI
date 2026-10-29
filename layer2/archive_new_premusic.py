"""Archive newly evaluated premusic originals and publish a reproducible result table."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime-tests" / "new-premusic-20261029"
PRE = ROOT / "premusic"
USED = ROOT / "premusic_used"
DEST = USED / "new_premusic_20261029"
ART = ROOT / "layer2" / "artifacts"
MOVE_REPORT = ART / "new_premusic_reorganization_20261029.json"
RESULTS = ART / "new_premusic_43_work_results_20261029.csv"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    frozen = json.loads((OUT / "frozen_selection.json").read_text(encoding="utf-8"))
    selected = frozen["selected"]
    screen_path = ART / "new_premusic_screen_20261029.json"
    screen = json.loads(screen_path.read_text(encoding="utf-8"))
    if digest(screen_path) != frozen["screen_sha256"] or len(selected) != len(screen["rows"]):
        raise RuntimeError("The frozen selection differs from the screen")
    if any(row["same_sha"] or row["same_media_id"] or row["fingerprint_matches"] for row in screen["rows"]):
        raise RuntimeError("Overlapping files require separate review before archiving")
    plan = json.loads((OUT / "query_plan.json").read_text(encoding="utf-8"))
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    if plan["selection_sha256"] != digest(OUT / "frozen_selection.json"):
        raise RuntimeError("Query plan does not match the frozen selection")
    if summary["status"] != "completed" or summary["selected_works"] != len(selected) or summary["queries_recorded"] != len(plan["queries"]):
        raise RuntimeError("Evaluation is not complete; no files moved")
    results = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["work_id"], row["kind"])
        if key in results or row["state"] != "completed":
            raise RuntimeError("Duplicate or failed evaluation result")
        results[key] = row
    if len(results) != len(plan["queries"]):
        raise RuntimeError("Checkpoint result count differs from the query plan")

    moves = []
    for row in selected:
        src = Path(row["file"])
        dst = DEST / src.name
        if src.resolve().parent != PRE.resolve() or dst.resolve().parent != DEST.resolve():
            raise RuntimeError("Path outside the intended audio folders")
        if dst.exists():
            if digest(dst) != row["sha256"] or src.exists():
                raise RuntimeError(f"Archive collision: {dst}")
        elif not src.is_file() or digest(src) != row["sha256"]:
            raise RuntimeError(f"Source missing or changed: {src}")
        moves.append({"original_path": str(src), "new_path": str(dst), "sha256": row["sha256"],
                      "used_in": "new_premusic_diagnostic_20261029"})
    if len({m["new_path"] for m in moves}) != len(moves):
        raise RuntimeError("Archive destination collision")

    DEST.mkdir(parents=True, exist_ok=True)
    for item in moves:
        src, dst = Path(item["original_path"]), Path(item["new_path"])
        if src.exists():
            src.rename(dst)
        if not dst.is_file() or digest(dst) != item["sha256"] or src.exists():
            raise RuntimeError(f"Move verification failed: {src}")

    result_rows = []
    for item in selected:
        work = item["sha256"]
        queries = {kind: results[(work, kind)] for kind in ("full", "start30", "middle30", "end30")}
        crop_decisions = [queries[kind]["result"]["decision"] for kind in ("start30", "middle30", "end30")]
        result_rows.append({"file": Path(item["file"]).name, "sha256": work,
                            "full_decision": queries["full"]["result"]["decision"],
                            "full_similarity_score": queries["full"]["result"].get("similarityScore"),
                            "start30_decision": crop_decisions[0], "middle30_decision": crop_decisions[1],
                            "end30_decision": crop_decisions[2],
                            "three_30s_work_warning": any(d in {"WARN", "HOLD", "BLOCK"} for d in crop_decisions),
                            "archive_path": str(DEST / Path(item["file"]).name)})
    with RESULTS.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result_rows[0]))
        writer.writeheader()
        writer.writerows(result_rows)

    manifest = USED / "usage_manifest.csv"
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        old_rows = list(csv.DictReader(stream))
    existing = {row["original_path"]: row for row in old_rows}
    for item in moves:
        if item["original_path"] in existing and existing[item["original_path"]] != item:
            raise RuntimeError("Existing usage record differs from the completed move")
    additions = [item for item in moves if item["original_path"] not in existing]
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["original_path", "new_path", "sha256", "used_in"])
        writer.writeheader()
        writer.writerows(old_rows + additions)
    move_report = {"date": "2026-10-29", "status": "completed", "new_files_screened": len(screen["rows"]),
                   "new_files_used_and_moved": len(moves), "overlaps_deleted": 0,
                   "premusic_remaining": len(list(PRE.glob("*.mp3"))),
                   "premusic_used_total": len(old_rows) + len(additions),
                   "moves": moves}
    MOVE_REPORT.write_text(json.dumps(move_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: move_report[key] for key in ("status", "new_files_used_and_moved", "overlaps_deleted", "premusic_remaining", "premusic_used_total")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
