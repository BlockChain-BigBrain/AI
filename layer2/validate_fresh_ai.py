"""Freeze and evaluate new locally supplied AI validation evidence.

No source audio is moved or registered. Supplied generation records are checked
for internal consistency; their issuer/authenticity is not inferred.
"""
import argparse,csv,hashlib,json,math,sys
from pathlib import Path
from scipy.stats import beta

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
REQUIRED=('audio_path','role','work_id','generator','model','generation_id','generation_record_path','expected_track_id')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while data:=f.read(1024*1024):h.update(data)
    return h.hexdigest()


def upper95(events,total):
    if not total:return None
    if events==total:return 1.
    return float(beta.ppf(.95,events+1,total-events))


def intake(manifest):
    manifest=manifest.resolve()
    with manifest.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not set(REQUIRED).issubset(reader.fieldnames or []):raise ValueError('Missing required manifest columns.')
        inputs=list(reader)
    if not inputs:raise ValueError('Manifest is empty. No evaluation was performed.')
    allow=json.loads((ART/'pixabay_provenance/ai_label_allowlist.json').read_text(encoding='utf-8'))
    reference_ids={r['track_id'] for r in allow['original_music']}
    known=set()
    with (ART/'pixabay_provenance/file_audit.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r.get('sha256'):known.add(r['sha256'])
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='sha256' and isinstance(item,str):known.add(item)
                elif isinstance(item,(dict,list)):collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    for path in (ROOT/'layer2/test_data').rglob('manifest.json'):
        collect(json.loads(path.read_text(encoding='utf-8-sig')))
    seen=set();works={};generations={};rows=[]
    for row in inputs:
        if row['role'] not in ('normal','positive'):raise ValueError('role must be normal or positive.')
        for name in ('audio_path','work_id','generator','model','generation_id','generation_record_path'):
            if not row[name].strip():raise ValueError(f'Missing {name}.')
            if row[name].startswith('REPLACE_'):raise ValueError('Template placeholders are not generation evidence.')
        def resolve(value):
            p=Path(value);return (manifest.parent/p).resolve() if not p.is_absolute() else p.resolve()
        audio,record_path=resolve(row['audio_path']),resolve(row['generation_record_path'])
        record=json.loads(record_path.read_text(encoding='utf-8-sig'))
        for key in ('generator','model','generation_id'):
            if record.get(key)!=row[key]:raise ValueError(f'Generation record mismatch: {key}.')
        if record.get('human_performance') is not False:raise ValueError('Record must explicitly declare human_performance=false; this remains a supplied claim.')
        digest=sha(audio)
        if digest in known or digest in seen:raise ValueError('Previously evaluated or duplicate file SHA256; use unused validation audio.')
        seen.add(digest)
        if row['role']=='normal':
            if row['work_id'] in works:raise ValueError('Each normal work_id may occur only once.')
            if row['expected_track_id']:raise ValueError('A normal candidate must not declare an expected source.')
        generation=(row['generator'],row['model'],row['generation_id'])
        if generation in generations and (row['role']=='normal' or generations[generation]!=row['role']):
            raise ValueError('Repeated generation cannot count as independent normal works.')
        generations[generation]=row['role']
        if row['role']=='positive' and row['expected_track_id'] not in reference_ids:
            raise ValueError('Positive expected_track_id must belong to the frozen 34-track catalog; new-reference studies require a separate catalog.')
        if row['work_id'] in works and works[row['work_id']]!=row['role']:raise ValueError('Same work cannot be both normal and positive.')
        works[row['work_id']]=row['role']
        rows.append({**row,'audio_path':str(audio),'generation_record_path':str(record_path),
            'sha256':digest,'generation_record_sha256':sha(record_path)})
    policy_path=ART/('ai_precision_policy.json' if (ART/'ai_precision_policy.json').exists() else 'ai_improvement_policy.json')
    return {'manifest_sha256':sha(manifest),'policy_sha256':sha(policy_path),
        'policy_file':policy_path.name,
        'generation_provenance':'Supplied consistent records; issuer/authenticity/pure-AI claims not independently verified.',
        'rows':rows}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime-tests/fresh-ai-validation')
    parser.add_argument('--evaluate',action='store_true');args=parser.parse_args()
    output=args.output.resolve()
    # Tool owns only workspace output. Input evidence may be elsewhere read-only.
    if not output.is_relative_to(ROOT):raise ValueError('Output must remain inside this workspace.')
    plan=intake(args.manifest);output.mkdir(parents=True,exist_ok=True);frozen=output/'frozen_intake.json'
    if frozen.exists():
        if json.loads(frozen.read_text(encoding='utf-8'))!=plan:raise ValueError('Frozen intake/policy changed. Use a new output directory; do not refit a completed validation.')
    else:frozen.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    if not args.evaluate:
        print('Intake checks passed and plan frozen. Use --evaluate with the same manifest and output.');return
    sys.path.insert(0,str(ROOT/'api'))
    from engine import Engine
    engine=Engine(scope='ai_labeled');results=[];checkpoint=output/'results.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line);done[r['sha256']]=r
    with checkpoint.open('a',encoding='utf-8') as log:
        for row in plan['rows']:
            if row['sha256'] in done:results.append(done[row['sha256']]);continue
            if sha(row['audio_path'])!=row['sha256']:raise ValueError('Input audio changed after freeze.')
            active_policy=ART/('ai_precision_policy.json' if (ART/'ai_precision_policy.json').exists() else 'ai_improvement_policy.json')
            if sha(active_policy)!=plan['policy_sha256']:raise ValueError('Active policy changed during validation.')
            try:result={**row,'state':'completed','result':engine.verify(Path(row['audio_path']),row['sha256'])}
            except Exception as exc:result={**row,'state':'failed','error_type':type(exc).__name__}
            results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[fresh validation {len(results)}/{len(plan["rows"])}] {result["state"]}',flush=True)
    normals=[r for r in results if r['role']=='normal'];positives=[r for r in results if r['role']=='positive']
    complete=[r for r in normals if r['state']=='completed']
    n=len(complete);warn=sum(r['result']['decision'] in ('WARN','HOLD','BLOCK') for r in complete)
    hold=sum(r['result']['decision'] in ('HOLD','BLOCK') for r in complete)
    # BLOCK remains visible as a normal-label conflict, not silently excluded.
    correct=sum(r['state']=='completed' and r['result']['decision'] in ('WARN','HOLD','BLOCK') and (
        r['result']['duplicate'].get('matchedTrackId','').removesuffix('.mp3')==r['expected_track_id'] if r['result']['decision']=='BLOCK'
        else any(c['trackId']==r['expected_track_id'] and c['score']>=engine.thresholds['warn'] for c in r['result']['similarTracks'])) for r in positives)
    failed=sum(r['state']!='completed' for r in results)
    report={'status':'completed' if not failed else 'incomplete_failed_queries','normal_rows':len(normals),'evaluated_normals':n,
        'normal_warn_count':warn,'normal_hold_count':hold,'normal_warn_rate':warn/n if n else None,
        'normal_hold_rate':hold/n if n else None,'warn_upper95':upper95(warn,n),'hold_upper95':upper95(hold,n),
        'positive_rows':len(positives),'correct_source_warn_top3_count':correct,
        'correct_source_warn_top3_recall':correct/len(positives) if positives else None,'failed_queries':failed,
        'empirical_normal_targets_met':bool(n and warn/n<=.10 and hold/n<=.02 and not failed),
        'normal_targets_supported_under_binomial_assumptions':bool(n and upper95(warn,n)<=.10 and upper95(hold,n)<=.02 and not failed),
        'sampling_limits':'Confidence bounds require independent representative sampling; repeated derivatives do not increase independent normal works.',
        'policy_sha256':plan['policy_sha256'],'pure_ai_creation_independently_verified':False}
    (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:
        print(f'Validation stopped: {exc}',file=sys.stderr)
        raise SystemExit(2)
