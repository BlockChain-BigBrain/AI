"""Offline calibration study for multi-window consensus; never changes production policy."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WARN={"WARN","HOLD","BLOCK"}

def summarize(rows, key):
    by=defaultdict(dict)
    for r in rows: by[r.get("work_id",r.get("name"))][r["kind"]]=r
    out={}
    for n in (1,2,3):
        selected=[d for d in by.values() if sum(d.get(k,{}).get("decision") in WARN for k in ("start30","middle30","end30"))>=n]
        out[f"at_least_{n}_windows"]={"works":len(selected),"rate":len(selected)/len(by) if by else None}
    return {"works":len(by),"rules":out}

def main():
    loc=json.loads((ROOT/"layer2/artifacts/premusic_warning_locations_20261031.json").read_text(encoding="utf-8"))
    normal=json.loads((ROOT/"layer2/artifacts/independent_normal_evaluation_20261031.json").read_text(encoding="utf-8"))
    normal_rows=[]
    for item in normal.get("rows",[]):
        for kind,q in item.get("positions",{}).items():
            if kind in ("start30","middle30","end30"):
                normal_rows.append({"name":item.get("name","normal"),"kind":kind,"decision":q.get("decision")})
    report={"date":"2026-11-01","production_thresholds_changed":False,"method":"offline at-least-N-of-3 WARN consensus; no refit on final evaluation","premusic_277":summarize(loc["results"],"decision"),"independent_normals":summarize(normal_rows,"decision"),"recommendation":"Use at-least-2-of-3 as a calibration candidate only; validate positive recall on locked final set before any policy change."}
    out=ROOT/"layer2/artifacts/consensus_calibration_20261101.json"; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__": main()
