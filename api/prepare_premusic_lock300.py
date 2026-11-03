"""Deduplicate premusic and select 300 never-used files for a locked audit."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'premusic').resolve(); USED=(ROOT/'premusic_used').resolve(); ORIGINAL=(ROOT/'original_music').resolve()
REPORT=ROOT/'api/runtime/premusic_lock300_preparation.json';SELECTION=ROOT/'api/runtime/premusic_lock300_selection.json'
EXT={'.mp3','.wav','.flac','.m4a','.ogg','.aac'}
def audio(root):return sorted(p.resolve() for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXT)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def safe_source(path):
 path.resolve().relative_to(SOURCE)
 return path.resolve()
def main():
 source=audio(SOURCE); comparison=audio(USED)+audio(ORIGINAL)
 known=set()
 for i,p in enumerate(comparison,1):
  known.add(sha(p))
  if i%100==0:print(f'comparison-hash {i}/{len(comparison)}',flush=True)
 seen={};kept=[];duplicates=[]
 for i,p in enumerate(source,1):
  digest=sha(p);reason=None;duplicate_of=None
  if digest in known:reason='already_used_or_original_exact_duplicate'
  elif digest in seen:reason='internal_exact_duplicate';duplicate_of=seen[digest]
  else:seen[digest]=str(p);kept.append({'path':str(p),'name':p.name,'sha256':digest})
  if reason:duplicates.append({'path':str(p),'sha256':digest,'reason':reason,'duplicateOf':duplicate_of})
  if i%25==0:print(f'source-hash {i}/{len(source)}',flush=True)
 supplemental=[]
 if len(kept)<300:
  evaluated=set()
  for name in ('premusic_minimal_results.jsonl','premusic_mined_train.jsonl'):
   p=ROOT/'api/runtime'/name
   if p.is_file():
    for line in p.read_text('utf-8').splitlines():evaluated.add(json.loads(line)['sha256'])
  remaining=json.loads((ROOT/'api/runtime/premusic_remaining_split.json').read_text('utf-8'))['rows']
  by_name={}
  for p in audio(USED):by_name.setdefault(p.name,[]).append(p)
  need=300-len(kept)
  for row in sorted(remaining,key=lambda r:r['contentKey']):
   matches=by_name.get(row['name'],[])
   target=matches[0] if matches else None
   if target is None:continue
   digest=sha(target)
   if digest in evaluated or digest in seen:continue
   supplemental.append({'path':str(target),'name':target.name,'sha256':digest,'source':'premusic_used_unused_pool'})
   seen[digest]=str(target)
   if len(supplemental)==need:break
  if len(supplemental)<need:raise RuntimeError(f'Only {len(kept)+len(supplemental)} unique unused files; need 300')
 # The user explicitly requested deletion. Resolve every target under premusic
 # immediately before unlinking; the report retains hashes and paths.
 for row in duplicates:
  target=safe_source(Path(row['path']))
  if target.is_file() and sha(target)==row['sha256']:target.unlink()
 selected=sorted(kept,key=lambda r:r['sha256'])[:300]
 selected.extend(supplemental)
 report={'method':'SHA-256 exact content dedupe against premusic_used and original_music',
         'sourceFilesBefore':len(source),'comparisonFiles':len(comparison),'deletedDuplicateCount':len(duplicates),
         'uniqueUnusedAfter':len(kept),'supplementalUnusedFromPriorPool':len(supplemental),
         'selectedForLockedAudit':len(selected),'unselectedRemaining':max(0,len(kept)-300),
         'deletedDuplicates':duplicates}
 REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 SELECTION.write_text(json.dumps({'method':'first 300 by SHA-256 after exact dedupe; frozen before scoring','selected':selected},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
