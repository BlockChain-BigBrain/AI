"""Full-file symmetric fingerprint checks for the AI-labelled evaluation set."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'layer1'))
import upload_guard_api as gate


def main():
    art=ROOT/'layer2/artifacts'
    allow=json.loads((art/'pixabay_provenance/ai_label_allowlist.json').read_text(encoding='utf-8'))
    inputs=[{**r,'role':f} for f in ('original_music','music') for r in allow[f]]
    def extract(row):
        path=Path(row['file']);assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
        return row,gate.extract_raw_fingerprint(path)['fingerprint_raw']
    with ThreadPoolExecutor(max_workers=2) as pool:pairs=list(pool.map(extract,inputs))
    references=gate._load_db()
    issues=[]
    def same(a,b):
        short,long=sorted((a,b),key=len)
        return gate._contains_exact_sequence(short,long)
    for i,(left,lfp) in enumerate(pairs):
        for right,rfp in pairs[i+1:]:
            if same(lfp,rfp):issues.append({'left':left['file'],'right':right['file'],'kind':'shared_full_shorter_fingerprint'})
        if left['role']=='music':
            for key,value in references.items():
                if value.get('fingerprint_raw') and same(lfp,value['fingerprint_raw']):
                    issues.append({'left':left['file'],'right':key,'kind':'normal_exact_recording_match_to_full_catalog'})
                    break
    report={'status':'passed' if not issues else 'failed','reference_files':len(allow['original_music']),
            'normal_files':len(allow['music']),'fingerprint_window':'full files up to fpcalc 1800s bound',
            'comparison':'complete shorter fingerprint inside longer, both directions', 'issues':issues,
            'musical_independence_verified':False}
    (art/'ai_scope_integrity_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if issues:raise SystemExit(1)


if __name__=='__main__':main()
