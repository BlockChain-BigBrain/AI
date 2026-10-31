"""Build explicit quarantine/provenance lists; preserve every audio file."""
from pathlib import Path
import csv,json

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'


def main():
    audit=json.loads((ART/'control_collection_near_duplicate_audit.json').read_text(encoding='utf-8'))
    with (ART/'control_collection_near_duplicate_files.csv').open(encoding='utf-8-sig',newline='') as f:inputs=list(csv.DictReader(f))
    with (ART/'pixabay_provenance/file_audit.csv').open(encoding='utf-8-sig',newline='') as f:
        provenance={str(Path(r['file']).resolve()).casefold():r for r in csv.DictReader(f)}
    duplicates={}
    for row in audit['near_identical_pairs']:duplicates.setdefault(row['file'],[]).append(row['reference'])
    errors={r['file']:r['error'] for r in audit['unscorable_files']}
    rows=[]
    for row in inputs:
        path=row['file'];source=provenance.get(str(Path(path).resolve()).casefold(),{})
        label=source.get('status')=='pixabay_ai_label_observed'
        eligibility='near_identical_recording_quarantine' if path in duplicates else 'audio_quality_quarantine' if path in errors else 'ai_label_candidate_not_pure_ai_verified' if label else 'ai_creation_provenance_unverified'
        rows.append({'folder':row['folder'],'file':path,'sha256':row['sha256'],'eligibility':eligibility,
            'source_url':source.get('source_url',''),'page_ai_label_observed':label,
            'matching_references':json.dumps(duplicates.get(path,[]),ensure_ascii=False),
            'quality_issue':errors.get(path,''),'audio_file_preserved':True})
    for name,selected in [('control_collection_eligibility.csv',rows),('control_collection_quarantine.csv',[r for r in rows if 'quarantine' in r['eligibility']])]:
        with (ART/name).open('w',encoding='utf-8-sig',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(selected)
    summary={'date':'2026-10-23','files_reviewed':len(rows),'files_deleted_or_moved':0,
        'counts':{folder:{status:sum(r['folder']==folder and r['eligibility']==status for r in rows)
            for status in sorted({r['eligibility'] for r in rows})} for folder in ('music','premusic')},
        'candidate_pure_ai_creation_verified':False,'fresh_validation_completed':False,
        'note':'AI label candidates have already been observed; these counts are not a fresh blind validation sample.'}
    (ART/'control_collection_eligibility_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
