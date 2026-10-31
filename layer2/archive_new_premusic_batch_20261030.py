"""Move the screened 179-song premusic batch into the usage archive."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; PRE=ROOT/'premusic'; USED=ROOT/'premusic_used'; SEL=ROOT/'.runtime-tests/new-premusic-20261030/all_selection.json'; DEST=USED/'new_premusic_20261030'; REPORT=ROOT/'layer2/artifacts/new_premusic_reorganization_20261030.json'; MANIFEST=USED/'usage_manifest.csv'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while c:=f.read(4*1024*1024): h.update(c)
 return h.hexdigest()
def main():
 selected=json.loads(SEL.read_text(encoding='utf-8'))['selected']; DEST.mkdir(parents=True,exist_ok=True); moves=[]
 for item in selected:
  src=Path(item['path']); dst=DEST/src.name
  if src.resolve().parent!=PRE.resolve() or dst.resolve().parent!=DEST.resolve(): raise RuntimeError('unsafe path')
  if dst.exists():
   if sha(dst)!=item['sha256'] or src.exists(): raise RuntimeError(f'collision {dst}')
  elif not src.is_file() or sha(src)!=item['sha256']: raise RuntimeError(f'changed source {src}')
  moves.append({'original_path':str(src),'new_path':str(dst),'sha256':item['sha256'],'used_in':'new_premusic_batch_20261030'})
 for m in moves:
  src,dst=Path(m['original_path']),Path(m['new_path'])
  if src.exists(): src.rename(dst)
  if not dst.is_file() or sha(dst)!=m['sha256'] or src.exists(): raise RuntimeError(f'move failed {src}')
 with MANIFEST.open(encoding='utf-8-sig',newline='') as f: old=list(csv.DictReader(f))
 existing={r['original_path'] for r in old}; additions=[m for m in moves if m['original_path'] not in existing]
 with MANIFEST.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['original_path','new_path','sha256','used_in']); w.writeheader(); w.writerows(old+additions)
 result={'date':'2026-10-30','status':'completed','new_files_seen':181,'exact_duplicates_deleted':2,'unique_new_files_used_and_moved':len(additions),'premusic_remaining':len(list(PRE.glob('*.mp3'))),'premusic_used_total':len(old)+len(additions),'destination':str(DEST),'moves':moves}
 REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:result[k] for k in ('status','new_files_seen','exact_duplicates_deleted','unique_new_files_used_and_moved','premusic_remaining','premusic_used_total')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
