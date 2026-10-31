"""Audit all current premusic files; delete exact copies and archive unique works."""
from __future__ import annotations
import argparse, csv, hashlib, json, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT/'premusic'; USED=ROOT/'premusic_used'; ARCHIVE=USED/'new_premusic_20261101'
REPORT=ROOT/'layer2/artifacts/premusic_intake_20261101.json'; MANIFEST=USED/'usage_manifest.csv'
EXT={'.mp3','.wav','.flac','.m4a','.ogg','.webm','.aac','.wma'}

def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def audio_files(folder:Path):
    return sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in EXT)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true'); args=ap.parse_args()
    candidates=audio_files(PRE)
    known=audio_files(ROOT/'original_music')+audio_files(ROOT/'music')+audio_files(USED)
    keepers={}
    for p in known: keepers.setdefault(digest(p),p)
    unique=[]; duplicates=[]
    for p in candidates:
        h=digest(p); survivor=keepers.get(h)
        if survivor: duplicates.append({'name':p.name,'path':str(p),'sha256':h,'survivor':str(survivor)})
        else: unique.append({'name':p.name,'path':str(p),'sha256':h}); keepers[h]=p
    report={'date':'2026-11-01','status':'planned','candidates_seen':len(candidates),'exact_duplicates':duplicates,'unique_new':unique,'archive':str(ARCHIVE)}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply:
        if ARCHIVE.exists(): raise RuntimeError(f'Archive already exists: {ARCHIVE}')
        for row in duplicates:
            if digest(Path(row['path']))!=row['sha256'] or digest(Path(row['survivor']))!=row['sha256']: raise RuntimeError(f"Duplicate evidence changed: {row['name']}")
        for row in unique:
            if digest(Path(row['path']))!=row['sha256']: raise RuntimeError(f"Unique source changed: {row['name']}")
        ARCHIVE.mkdir(parents=True)
        for row in unique:
            src=Path(row['path']); dst=ARCHIVE/src.name
            if dst.exists(): raise RuntimeError(f'Destination exists: {dst}')
            shutil.move(str(src),str(dst)); row['archived_path']=str(dst)
        for row in duplicates:
            src=Path(row['path']); survivor=Path(row['survivor'])
            if survivor.parent==PRE and not survivor.exists(): survivor=ARCHIVE/survivor.name
            if digest(survivor)!=row['sha256']: raise RuntimeError(f"Retained copy changed: {row['name']}")
            src.unlink(); row['survivor']=str(survivor)
        with MANIFEST.open('a',encoding='utf-8',newline='') as f:
            w=csv.writer(f)
            for row in unique: w.writerow([row['path'],row['archived_path'],row['sha256'],'new_premusic_batch_20261101'])
        report['status']='completed'; report['remaining_premusic']=len(audio_files(PRE)); REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'candidates_seen':len(candidates),'exact_duplicates':len(duplicates),'unique_new':len(unique)},ensure_ascii=False))
if __name__=='__main__': main()
