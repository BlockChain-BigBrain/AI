"""Inventory local audio and explicit provenance evidence, without audio AI guessing."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import evaluate_retrieval_baseline as baseline

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
PRIVATE=ROOT/'.runtime-tests/pixabay-provenance'
OUT=ART/'pixabay_provenance'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inventory-json',action='store_true');args=parser.parse_args()
    OUT.mkdir(exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    inventory_path=OUT/'inventory.json'
    if args.inventory_json:
        print(inventory_path.read_text(encoding='utf-8'));return
    ffmpeg=baseline.find_ffmpeg()
    positive_ids={r['expected_track_id'] for r in csv.DictReader((ART/'top3_aggregation_details.csv').open(encoding='utf-8-sig')) if r['dataset']=='positive'}
    jobs=[(folder,path) for folder in ('original_music','music','premusic') for path in baseline.audio_files(ROOT/folder)]
    def inspect(job):
        folder,path=job
        signature=f'{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}'
        cached=PRIVATE/(hashlib.sha256(signature.encode()).hexdigest()+'.json')
        if cached.exists():return json.loads(cached.read_text(encoding='utf-8'))
        completed=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(path),'-f','ffmetadata','pipe:1'],capture_output=True,timeout=45)
        metadata=completed.stdout.decode('utf-8',errors='replace')
        match=re.search(r'-(\d{5,8})(?:\s*\(\d+\))?$',path.stem)
        media_id=match.group(1) if match else ''
        urls=re.findall(r'https?://[^\s<>"\\]+',metadata)
        platform_urls=[u for u in urls if 'pixabay.com/' in u]
        # A model/tool string is evidence of involvement, not proof of a pure AI workflow.
        ai_hits=re.findall(r'\b(?:suno(?:\.ai|\.com)?|udio(?:\.com)?|stable audio|aiva|soundraw|boomy|AI[- _]generated)\b',metadata,re.I)
        row={'file':str(path.resolve()),'folder':folder,'track_id':path.stem,
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'media_id_candidate':media_id,
             'pixabay_urls_in_metadata':platform_urls,'ai_tool_metadata_terms':sorted(set(x.lower() for x in ai_hits)),
             'metadata_read_ok':completed.returncode==0,'positive_source':path.stem in positive_ids,
             'status':'metadata_ai_involvement' if ai_hits else 'unverified',
             'pure_ai_creation_verified':False,'user_reported_source':'Pixabay',
             'file_signature':hashlib.sha256(signature.encode()).hexdigest()}
        cached.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
        return row
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i,row in enumerate(pool.map(inspect,jobs),1):
            rows.append(row)
            if i%100==0:print(f'[metadata {i}/{len(jobs)}]',flush=True)
    inventory_path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'files':len(rows),'folders':{f:sum(r['folder']==f for r in rows) for f in ('original_music','music','premusic')},
             'numeric_media_id_candidates':sum(bool(r['media_id_candidate']) for r in rows),
             'explicit_ai_tool_metadata_files':sum(bool(r['ai_tool_metadata_terms']) for r in rows),
             'metadata_pixabay_url_files':sum(bool(r['pixabay_urls_in_metadata']) for r in rows),
             'pure_ai_creation_verified':0,'audio_based_ai_detector_used':False,
             'note':'AI labels may include modification; neither royalty-free nor missing AI labels establishes creation method.'}
    (OUT/'inventory_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
