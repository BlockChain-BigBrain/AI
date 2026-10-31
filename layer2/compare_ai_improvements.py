"""Development-only choice; reused test results are explicitly diagnostic.

No database/audio deletion. Cached embeddings remain bound to file metadata.
Run before deployment; writes a comparison, never activates it automatically.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'
PROTOCOL = {
    'date': '2026-10-23',
    'candidates': ['margin_top5', 'contrast_top5', 'margin_top20'],
    'warn_rule': 'Midpoint between tune normal FPR<=10% boundary and tune positive source 5th percentile, if feasible.',
    'hold_rule': 'Maximum of strict tune normal FPR<=2% boundary and tune positive source 25th percentile.',
    'selection': 'Tune only: maximize correct-source WARN recall in display Top3; then prefer margin_top5, margin_top20, contrast_top5. No test-driven selection.',
    'test_status': 'Previously observed source-disjoint test; not fresh blind validation.',
    'normal_exclusion': 'Only independently audited near-identical recording; report both raw and audited counts.',
    'new_stress': 'After selection: all 14 test works, pitch+tempo+codec and spliced-section variants; not unseen works.',
    'targets': {'normal_warn_max': .10, 'normal_hold_max': .02, 'correct_source_warn_min': .90},
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def contrast(rows):
    """Remove the persistent pitch profile, preserving time-varying evidence."""
    x = rows - rows.mean(axis=0, keepdims=True)
    return np.ascontiguousarray(x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-8), dtype=np.float32)


def calibrate(rows):
    tune = [r for r in rows if r['split'] == 'tune']
    normal = [r['score'] for r in tune if r['dataset'] == 'safe_music']
    positive = [r['expected_score'] for r in tune if r['dataset'] == 'positive' and r['expected_score'] is not None]
    def boundary(target):
        choices = sorted(set(normal + [float(np.nextafter(max(normal), np.inf))]))
        return next(t for t in choices if np.mean([x >= t for x in normal]) <= target)
    lower, upper = boundary(.10), float(np.quantile(positive, .05))
    warn = (lower + upper) / 2 if upper > lower else lower
    hold = max(boundary(.02), float(np.quantile(positive, .25)), float(np.nextafter(warn, np.inf)))
    return {'warn_threshold': warn, 'hold_threshold': hold,
            'normal_boundary': lower, 'positive_fifth_percentile': upper,
            'feasible_margin': max(0, upper-lower)}


def metrics(rows, policy, excluded=()):
    pos = [r for r in rows if r['dataset'] == 'positive']
    neg = [r for r in rows if r['dataset'] != 'positive' and Path(r['file']).name not in excluded]
    warn, hold = policy['warn_threshold'], policy['hold_threshold']
    source_ok = [r['expected_score'] is not None and r['expected_score'] >= warn and r['source_rank_after_tonal'] <= 3 for r in pos]
    n_warn, n_hold = sum(r['score'] >= warn for r in neg), sum(r['score'] >= hold for r in neg)
    return {'positive_queries': len(pos), 'correct_source_warn_top3_count': sum(source_ok),
            'correct_source_warn_top3_recall': float(np.mean(source_ok)) if pos else None,
            'normal_candidates': len(neg), 'normal_warn_count': n_warn, 'normal_hold_count': n_hold,
            'normal_warn_rate': n_warn/len(neg) if neg else None,
            'normal_hold_rate': n_hold/len(neg) if neg else None}


def main():
    protocol_path = ART/'ai_improvement_protocol.json'
    if protocol_path.exists():
        assert read(protocol_path) == PROTOCOL, 'Do not silently change a frozen protocol.'
    else:
        protocol_path.write_text(json.dumps(PROTOCOL, indent=2), encoding='utf-8')
    old = read(ART/'ai_labeled_recalibration.json')
    base.FFMPEG_EXE = base.find_ffmpeg()
    profiles = old['profiles']
    signature = hashlib.sha256((old['manifest_sha256']+profiles['ai_labeled_catalog']['full_catalog_version']+tonal.VERSION).encode()).hexdigest()
    saved = {}
    for line in (ART/'ai_labeled_checkpoint.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line)
        if r['signature']==signature: saved[(r['scope'],r['file'])]=r
    paths = {base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    feature_cache = {}
    def features(path):
        key=str(path)
        if key not in feature_cache: feature_cache[key]=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
        return feature_cache[key]
    with np.load(ART/'current_reference_catalog.npz', allow_pickle=False) as f:
        vectors, ids=f['vectors'].astype(np.float32),f['ids']
    catalogs={}
    for scope in profiles:
        mask=np.isin(ids,profiles[scope]['allowed_reference_ids']) if scope=='ai_labeled_catalog' else np.ones(len(ids),bool)
        v,i=vectors[mask],ids[mask];mean=v.mean(axis=0)
        catalogs[scope]=(mean,agg.unit_rows(v-mean),[(str(t),np.flatnonzero(i==t)) for t in np.unique(i)])
    checkpoint=ART/'ai_improvement_checkpoint.jsonl'
    done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['method'],r['file'])]=r
    rows=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,((scope,file),row) in enumerate(saved.items(),1):
            for method in PROTOCOL['candidates']:
                key=(scope,method,file)
                if key in done:rows.append(done[key]);continue
                start=time.perf_counter()
                if method=='margin_top5':
                    result={**row,'method':method}
                else:
                    qt,_,qs=features(Path(file))
                    if method=='contrast_top5':
                        qt=contrast(qt);ranked=row['candidates']
                    else:
                        cache=base.cache_key(Path(file),False,all_query_windows=True)
                        assert cache.exists(),f'Expected precomputed embedding: {file}'
                        with np.load(cache,allow_pickle=False) as f:q,starts=f['vectors'].astype(np.float32),f['offsets'].tolist()
                        mean,centered,groups=catalogs[scope];sim=agg.unit_rows(q-mean)@centered.T
                        ranked=[{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups]
                        ranked.sort(key=lambda r:r['clapScore'],reverse=True);ranked=ranked[:20]
                    candidates=[];existing={r['trackId']:r for r in row['candidates']}
                    for match in ranked:
                        if method=='margin_top20' and match['trackId'] in existing:
                            candidates.append(existing[match['trackId']]);continue
                        ref,_,rs=features(paths[match['trackId']])
                        if method=='contrast_top5':ref=contrast(ref)
                        candidates.append({**match,**tonal.compare(qt,ref,qs,rs)})
                    candidates.sort(key=lambda r:r['tonalScore'],reverse=True)
                    source=next((r['tonalScore'] for r in candidates if r['trackId']==row['expected_track_id']),None)
                    rank=next((i for i,r in enumerate(candidates,1) if r['trackId']==row['expected_track_id']),None)
                    result={**row,'method':method,'candidates':candidates,'score':candidates[0]['tonalScore'],
                            'expected_score':source,'source_rank_after_tonal':rank}
                result['incremental_seconds']=time.perf_counter()-start
                rows.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[comparison {n}/{len(saved)}] {scope} {Path(file).name}',flush=True)
    excluded=read(ART/'ai_near_duplicate_audit.json')['excluded_normal_filenames']
    result={}
    for scope in profiles:
        methods={}
        for method in PROTOCOL['candidates']:
            part=[r for r in rows if r['scope']==scope and r['method']==method];policy=calibrate(part)
            methods[method]={**policy,'tune':metrics([r for r in part if r['split']=='tune'],policy),
                'test_raw':metrics([r for r in part if r['split']=='test'],policy),
                'test_audited':metrics([r for r in part if r['split']=='test'],policy,excluded),
                'premusic_diagnostic':metrics([r for r in part if r['split']=='external_diagnostic'],policy)}
        preference={'margin_top5':2,'margin_top20':1,'contrast_top5':0}
        selected=max(methods,key=lambda m:(methods[m]['tune']['correct_source_warn_top3_recall'],preference[m]))
        result[scope]={'selected_method':selected,'methods':methods}
    report={'protocol':PROTOCOL,'original_policy_sha256':hashlib.sha256((ART/'ai_labeled_recalibration.json').read_bytes()).hexdigest(),
            'manifest_sha256':old['manifest_sha256'],'signature':signature,'excluded_normal_filenames':excluded,
            'profiles':result,'test_status':PROTOCOL['test_status']}
    (ART/'ai_improvement_comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
