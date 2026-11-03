"""Report temporal consistency and automatic-label performance by variant family."""
from __future__ import annotations
import csv, json, math, statistics
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RESULT_FILES = [ROOT / "api/runtime/locked_full_v2/results.jsonl",
                ROOT / "api/runtime/locked_shard_a/results.jsonl",
                ROOT / "api/runtime/locked_shard_b/results.jsonl"]
MANIFESTS = [ROOT / "layer2/test_data/plagiarism_positive/manifest.csv",
             ROOT / "layer2/test_data/reperformed_positive/manifest.csv",
             ROOT / "layer2/test_data/synthetic_layered_positive/manifest.csv"]

def family_for(row, by_name):
    name = Path(row["file"]).name
    if name in by_name: return by_name[name]
    q = row["queryKind"]
    if q == "unmodified_safe_candidate": return "safe_control"
    return "unknown"

def temporal(candidate):
    segments = sorted(candidate.get("matchedSegments", []), key=lambda x: x["queryStartSec"])
    if not segments: return {"count": 0}
    refs = [float(x["refStartSec"]) for x in segments]
    shifts = [int(x.get("pitchShift", 0)) for x in segments]
    ordered = sum(b >= a for a, b in zip(refs, refs[1:])) / max(1, len(refs) - 1)
    longest = chain = 1
    for a, b in zip(refs, refs[1:]):
        chain = chain + 1 if b >= a else 1
        longest = max(longest, chain)
    q = [float(x["queryStartSec"]) for x in segments]
    dq = [b-a for a,b in zip(q,q[1:]) if b>a]
    dr = [b-a for a,b in zip(refs,refs[1:]) if b>a]
    ratios = [a/b for a,b in zip(dq,dr) if b>0]
    return {"count": len(segments), "orderedMatchFraction": ordered,
            "pitchShiftConsistency": max(shifts.count(s) for s in set(shifts))/len(shifts),
            "tempoRatioMedian": statistics.median(ratios) if ratios else 1.0,
            "tempoRatioConsistency": math.exp(-statistics.pstdev([math.log(x) for x in ratios])) if len(ratios)>1 else 1.0 if len(ratios)==1 else 0.0,
            "longestOrderedChainSeconds": 10 * longest}

def main():
    by_name = {}
    for path in MANIFESTS:
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = Path(row["query_path"]).name
                if path.name == "manifest.csv" and "variant" in row:
                    by_name[name] = {"1": "부분 추출·재인코딩", "2": "EQ·볼륨 변경", "3": "속도·피치 변경"}.get(row["variant"], "부분 추출·재인코딩")
                elif row.get("case_type") == "section_edit": by_name[name] = "섹션 재배열"
                elif row.get("case_type") == "tempo_pitch_eq": by_name[name] = "속도·피치 변경"
                elif row.get("case_type") == "remix_fx": by_name[name] = "리믹스 효과"
                elif row.get("case_type") == "synth_pad_bass_percussion_overlay": by_name[name] = "AI 악기 레이어 추가"
    rows=[]
    for path in RESULT_FILES:
        rows.extend(json.loads(line) for line in path.read_text("utf-8").splitlines())
    groups=defaultdict(list); temporal_rows=[]
    for row in rows:
        family=family_for(row,by_name); groups[family].append(row)
        if row["dataset"] == "positive" and row["expectedTrackId"] in [c["trackId"] for c in row["top3"]]:
            candidate=next(c for c in row["top3"] if c["trackId"] == row["expectedTrackId"])
            temporal_rows.append({"family":family,**temporal(candidate)})
    report={"families":{},"missingRequestedFamilies":[]}
    requested=["부분 추출·재인코딩","EQ·볼륨 변경","속도·피치 변경","섹션 재배열","리믹스 효과","AI 악기 레이어 추가","멜로디 유지·음색 재생성","구조 유지·보컬 교체"]
    for family in requested:
        part=[r for r in groups.get(family,[]) if r["dataset"]=="positive"]
        temporal_part=[r for r in temporal_rows if r["family"]==family]
        report["families"][family]={"queryCount":len(part),
            "warnOrHoldRate":sum(r["decision"] in ("WARN","HOLD") for r in part)/len(part) if part else None,
            "sourceTop3Rate":sum(r["expectedTrackId"] in [c["trackId"] for c in r["top3"]] for r in part)/len(part) if part else None,
            "temporalEvidenceCount":len(temporal_part),
            "orderedMatchFractionMedian":statistics.median([r["orderedMatchFraction"] for r in temporal_part]) if temporal_part else None,
            "pitchShiftConsistencyMedian":statistics.median([r["pitchShiftConsistency"] for r in temporal_part]) if temporal_part else None,
            "tempoRatioConsistencyMedian":statistics.median([r["tempoRatioConsistency"] for r in temporal_part]) if temporal_part else None,
            "longestOrderedChainSecondsMedian":statistics.median([r["longestOrderedChainSeconds"] for r in temporal_part]) if temporal_part else None}
        if not part: report["missingRequestedFamilies"].append(family)
    report["note"]="Melody/timbre regeneration and vocal replacement are not present in the current manifests; they are reported as missing rather than inferred."
    out=ROOT/"api/runtime/variant_temporal_report.json"; out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__": main()
