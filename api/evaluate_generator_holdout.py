"""Leave-one-transformation-family-out evaluation for automatic AI labels."""
from __future__ import annotations
import csv, json
from pathlib import Path
import numpy as np
from evaluate_pairwise_verifier import features, fit, sigmoid

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "api/runtime/locked_full_v2/results.jsonl",
         ROOT / "api/runtime/locked_shard_a/results.jsonl",
         ROOT / "api/runtime/locked_shard_b/results.jsonl"]
MANIFESTS = [ROOT / "layer2/test_data/plagiarism_positive/manifest.csv",
             ROOT / "layer2/test_data/reperformed_positive/manifest.csv",
             ROOT / "layer2/test_data/synthetic_layered_positive/manifest.csv"]

def family_map():
    result={}
    for path in MANIFESTS:
        with path.open(newline="",encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name=Path(row["query_path"]).name
                if "variant" in row:
                    result[name]={"1":"partial_reencode","2":"eq_volume","3":"tempo_pitch"}.get(row["variant"],"partial_reencode")
                elif row.get("case_type") == "section_edit": result[name]="section_edit"
                elif row.get("case_type") == "tempo_pitch_eq": result[name]="tempo_pitch"
                elif row.get("case_type") == "remix_fx": result[name]="remix_fx"
                elif row.get("case_type") == "synth_pad_bass_percussion_overlay": result[name]="instrument_overlay"
    return result

def main():
    rows=[]
    for path in FILES: rows += [json.loads(x) for x in path.read_text("utf-8").splitlines()]
    fmap=family_map()
    for row in rows: row["family"] = fmap.get(Path(row["file"]).name, "unknown")
    families=sorted({r["family"] for r in rows if r["dataset"]=="positive" and r["family"]!="unknown"})
    report={"holdoutUnit":"transformation family (generator IDs are not present in current manifests)","families":{}}
    for heldout in families:
        train=[r for r in rows if r["family"]!=heldout]
        test=[r for r in rows if r["family"]==heldout and r["dataset"]=="positive"]
        pairs=[(features(c),int(r["dataset"]=="positive" and c["trackId"]==r["expectedTrackId"]))
               for r in train for c in r["top3"]]
        x=np.stack([p[0] for p in pairs]); y=np.asarray([p[1] for p in pairs]); mean,std,w,b=fit(x,y)
        def score(c): return float(sigmoid(((features(c)-mean)/std)@w+b))
        report["families"][heldout]={"queryCount":len(test),
            "sourceTop3Ceiling":sum(r["expectedTrackId"] in [c["trackId"] for c in r["top3"]] for r in test)/len(test),
            "sourceTop1AfterVerifier":sum(max(r["top3"],key=score)["trackId"]==r["expectedTrackId"] for r in test)/len(test),
            "bestPairScoreMean":float(np.mean([max(score(c) for c in r["top3"]) for r in test]))}
    report["unavailableFamilies"]=["melody_timbre_regeneration","vocal_replacement"]
    report["note"]="These are transform-family holdouts. A true unseen-generator test requires generator_id in the manifest and is not claimed here."
    out=ROOT/"api/runtime/generator_holdout_report.json";out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()
