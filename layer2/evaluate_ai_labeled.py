"""Recalibrate on official-page AI-labelled assets; labels are not pure-AI proof.

Compare 34-label reference subset and the unchanged 1000-reference catalog.
New source-group splits are locked before scoring. Premusic is diagnostic only.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve
import torch
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
OUT=ROOT/'layer2/test_data/ai_labeled_positive'
SEED=20261024
sys.path.insert(0,str(ROOT/'layer1'))
import upload_guard_api as gate


def digest_catalog(vectors,ids,offsets):
    return hashlib.sha256(vectors.tobytes()+ids.tobytes()+offsets.tobytes()).hexdigest()


def prepare(allow,ffmpeg):
    OUT.mkdir(exist_ok=True)
    path=OUT/'manifest.json'
    if path.exists():
        manifest=json.loads(path.read_text(encoding='utf-8'))
        assert manifest['source_ids']==sorted(r['track_id'] for r in allow['original_music'])
        if 'premusic_excluded' not in manifest:
            known={r['media_id_candidate'] for folder in ('original_music','music') for r in allow[folder]}
            by_path={r['file']:r for r in allow['premusic']}
            fingerprints=gate._load_db();retained=[];excluded=[]
            for row in manifest['rows']:
                reason=None
                if row['dataset']=='premusic_audit':
                    if by_path[row['file']]['media_id_candidate'] in known:reason='same_media_id_as_reference_or_control'
                    else:
                        fp=gate.extract_raw_fingerprint(Path(row['file']))
                        if gate.find_exact_duplicate(fp['fingerprint_raw'],fingerprints):reason='exact_fingerprint_match_to_catalog'
                if reason:excluded.append({'file':row['file'],'reason':reason})
                else:retained.append(row)
            manifest.update(rows=retained,premusic_excluded=excluded)
            path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        return manifest
    rows=[]
    for i,row in enumerate(allow['original_music']):
        source=Path(row['file']);assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
        duration=base.get_duration_seconds(source)
        offset=max(0,(duration-35)/2)
        # Force a known sample rate before pitch-preserving tempo processing.
        proc=subprocess.run([ffmpeg,'-v','error','-nostdin','-ss',str(offset),'-i',str(source),'-t','30',
                             '-ac','1','-ar','22050','-f','f32le','pipe:1'],check=True,capture_output=True)
        audio=np.frombuffer(proc.stdout,dtype='<f4').copy()
        assert len(audio)>=10*22050
        for kind in ('local_tempo_warp','room_rerecord_simulation'):
            target=OUT/f'{i:03}__{kind}.wav'
            if kind=='local_tempo_warp':
                subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(source),'-t','30',
                    '-filter_complex','[0:a]aresample=22050,asplit=2[a][b];[a]atrim=0:15,asetpts=PTS-STARTPTS,atempo=0.9[a1];[b]atrim=15:30,asetpts=PTS-STARTPTS,atempo=1.12[b1];[a1][b1]concat=n=2:v=0:a=1[out]',
                    '-map','[out]','-ac','1','-ar','22050',str(target)],check=True)
                parameters={'first_rate':.9,'second_rate':1.12,'split_seconds':15,'source_offset':offset}
            else:
                rng=np.random.default_rng(SEED+i)
                t=np.arange(int(.5*22050))/22050
                ir=rng.normal(size=len(t))*np.exp(-6.907755*t/.5)
                ir*=.3/max(np.linalg.norm(ir),1e-9);ir[0]+=1
                y=fftconvolve(audio,ir)[:len(audio)]
                noise=rng.normal(size=len(y));noise*=np.sqrt(np.mean(y*y))/(10**(25/20)*max(np.sqrt(np.mean(noise*noise)),1e-9))
                y+=noise;y*=min(1,.96/max(np.max(np.abs(y)),1e-9))
                sf.write(target,y.astype(np.float32),22050,subtype='PCM_16')
                parameters={'synthetic_rt60':.5,'noise_snr_db':25,'source_offset':offset}
            rows.append({'file':str(target),'dataset':'positive','expected_track_id':row['track_id'],
                         'group_id':'positive:'+row['track_id'],'query_kind':kind,
                         'source_sha256':row['sha256'],'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                         'source_url':row['source_url'],'parameters':parameters})
        print(f'[prepared {i+1}/{len(allow["original_music"])}]',flush=True)
    excluded=[]
    known_ids={r['media_id_candidate'] for folder in ('original_music','music') for r in allow[folder]}
    known_fingerprints=gate._load_db()
    for folder in ('music','premusic'):
        for row in allow[folder]:
            if folder=='premusic':
                reason='same_media_id_as_reference_or_control' if row['media_id_candidate'] in known_ids else None
                if not reason:
                    fp=gate.extract_raw_fingerprint(Path(row['file']))
                    if gate.find_exact_duplicate(fp['fingerprint_raw'],known_fingerprints):reason='exact_fingerprint_match_to_catalog'
                if reason:
                    excluded.append({'file':row['file'],'reason':reason});continue
            rows.append({'file':row['file'],'dataset':'safe_music' if folder=='music' else 'premusic_audit',
                         'expected_track_id':'','group_id':'normal:'+row['track_id'],'query_kind':'ai_label_normal_candidate',
                         'sha256':row['sha256'],'source_url':row['source_url']})
    # Same source is never on both sides. Separate class splits prevent empty classes.
    for dataset in ('positive','safe_music'):
        groups=sorted({r['group_id'] for r in rows if r['dataset']==dataset})
        import random
        random.Random(SEED).shuffle(groups)
        n=round(len(groups)*.6);mapping={g:'tune' if i<n else 'test' for i,g in enumerate(groups)}
        for r in rows:
            if r['dataset']==dataset:r['split']=mapping[r['group_id']]
    for r in rows:
        if r['dataset']=='premusic_audit':r['split']='external_diagnostic'
    manifest={'seed':SEED,'source_ids':sorted(r['track_id'] for r in allow['original_music']),
              'labels':'Official platform AI label, generated or modified, not pure-AI verified',
              'selection_before_scoring':True,'premusic_excluded':excluded,'rows':rows}
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def main():
    base.FFMPEG_EXE=base.find_ffmpeg()
    allow_path=ART/'pixabay_provenance/ai_label_allowlist.json'
    allow=json.loads(allow_path.read_text(encoding='utf-8'))
    manifest=prepare(allow,base.FFMPEG_EXE)
    manifest_hash=hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()
    torch.set_num_threads(4)
    device=torch.device('cpu')
    model=agg.ClapAudioModelWithProjection.from_pretrained(base.BASE_MODEL,local_files_only=True).eval()
    processor=agg.ClapProcessor.from_pretrained(base.BASE_MODEL,local_files_only=True)
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as saved:
        vectors,ids,offsets=saved['vectors'].astype(np.float32),saved['ids'],saved['offsets']
    full_version=digest_catalog(vectors,ids,offsets)
    assert full_version==json.loads((ART/'top3_aggregation_evaluation.json').read_text(encoding='utf-8'))['corpus']['embedding_sha256']
    selected=np.isin(ids,manifest['source_ids'])
    catalogs={}
    for name,mask in [('ai_labeled_catalog',selected),('full_catalog',np.ones(len(ids),dtype=bool))]:
        v,i,o=vectors[mask],ids[mask],offsets[mask]
        catalogs[name]={'vectors':v,'ids':i,'offsets':o,'mean':v.mean(axis=0),
                        'groups':[(str(t),np.flatnonzero(i==t)) for t in np.unique(i)],
                        'catalog_version':digest_catalog(v,i,o)}
        catalogs[name]['centered']=agg.unit_rows(v-catalogs[name]['mean'])
    feature_cache={}
    original_paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    def features(path):
        key=str(path.resolve())
        if key not in feature_cache:feature_cache[key]=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
        return feature_cache[key]
    checkpoint=ART/'ai_labeled_checkpoint.jsonl'
    signature=hashlib.sha256((manifest_hash+full_version+tonal.VERSION).encode()).hexdigest()
    saved_rows={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:saved_rows[(r['scope'],r['file'])]=r
    results=[]
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,row in enumerate(manifest['rows'],1):
            path=Path(row['file']);assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            if all((scope,row['file']) in saved_rows for scope in catalogs):
                results.extend(saved_rows[(scope,row['file'])] for scope in catalogs);continue
            q,starts=base.embed_file(path,model,processor,device,False,all_query_windows=True)
            qt,_,qs=features(path)
            for scope,c in catalogs.items():
                if (scope,row['file']) in saved_rows:
                    results.append(saved_rows[(scope,row['file'])]);continue
                similarity=agg.unit_rows(q-c['mean'])@c['centered'].T
                ranked=[]
                for track_id,indices in c['groups']:
                    score,_=agg.non_overlapping_top3(similarity[:,indices],starts)
                    ranked.append({'trackId':track_id,'clapScore':score})
                ranked.sort(key=lambda r:r['clapScore'],reverse=True)
                retrieval_rank=next((j for j,r in enumerate(ranked,1) if r['trackId']==row['expected_track_id']),None)
                candidates=[]
                for match in ranked[:5]:
                    ref,_,rs=features(original_paths[match['trackId']])
                    candidates.append({**match,**tonal.compare(qt,ref,qs,rs)})
                candidates.sort(key=lambda r:r['tonalScore'],reverse=True)
                source=next((r['tonalScore'] for r in candidates if r['trackId']==row['expected_track_id']),None)
                source_rank=next((j for j,r in enumerate(candidates,1) if r['trackId']==row['expected_track_id']),None)
                result={**row,'scope':scope,'signature':signature,'score':candidates[0]['tonalScore'],
                        'expected_score':source,'source_rank_after_tonal':source_rank,'retrieval_rank':retrieval_rank,'candidates':candidates}
                results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[query {n}/{len(manifest["rows"])}] {row["query_kind"]}',flush=True)
    profiles={}
    for scope,c in catalogs.items():
        rows=[r for r in results if r['scope']==scope]
        tune=[r for r in rows if r['split']=='tune']
        normal=[r['score'] for r in tune if r['dataset']=='safe_music']
        def choose(target):
            candidates=sorted(set(normal+[float(np.nextafter(max(normal),np.inf))]))
            return next(float(t) for t in candidates if np.mean([s>=t for s in normal])<=target)
        warn,hold_fpr=choose(.10),choose(.02)
        tune_source_scores=[r['expected_score'] for r in tune if r['dataset']=='positive' and r['expected_score'] is not None]
        # With only 18 normals, FPR-only cutoffs can differ by one floating-point
        # ULP. HOLD additionally requires the lower quartile of confirmed tune
        # source scores, rather than presenting a fictitious second risk band.
        hold=max(hold_fpr,float(np.quantile(tune_source_scores,.25)))
        def metrics(split):
            part=[r for r in rows if r['split']==split]
            pos=[r for r in part if r['dataset']=='positive'];neg=[r for r in part if r['dataset']!='positive']
            rate=lambda xs:float(np.mean(xs)) if xs else None
            return {'positive_queries':len(pos),'positive_source_works':len({r['group_id'] for r in pos}),'normal_candidates':len(neg),
                    'normal_warn_or_hold_rate':rate([r['score']>=warn for r in neg]),'normal_hold_rate':rate([r['score']>=hold for r in neg]),
                    'positive_query_warn_recall':rate([r['score']>=warn for r in pos]),
                    'correct_source_warn_recall_top5':rate([r['expected_score'] is not None and r['expected_score']>=warn for r in pos]),
                    'correct_source_warn_recall_display_top3':rate([r['expected_score'] is not None and r['expected_score']>=warn and r['source_rank_after_tonal']<=3 for r in pos]),
                    'source_retrieval_at_5':rate([r['retrieval_rank'] is not None and r['retrieval_rank']<=5 for r in pos])}
        tune_metrics=metrics('tune')
        profiles[scope]={'score_version':tonal.VERSION,'warn_threshold':warn,'hold_threshold':hold,
                         'reference_tracks':len(c['groups']),'catalog_version':c['catalog_version'],
                         'full_catalog_version':full_version,'allowed_reference_ids':manifest['source_ids'] if scope=='ai_labeled_catalog' else [],
                         'tune_targets':{'normal_warn':.10,'normal_hold':.02},'threshold_selection':'Tune source groups only; no refit on test or premusic.',
                         'hold_additional_rule':'At least the 25th percentile of confirmed tune positive source scores; prevents a one-ULP WARN/HOLD band.',
                         'validation_status':'Disjoint source groups; held-out scores reused after fixing a degenerate FPR-only HOLD band. Not fresh blind validation.',
                         'tune':tune_metrics,'test':metrics('test'),'premusic_diagnostic':metrics('external_diagnostic'),
                         'enabled':bool(tune_metrics['correct_source_warn_recall_top5']>=.5 and hold-warn>=1e-4)}
    report={'status':'experimental_ai_label_subset','pure_ai_generation_verified':False,'score_version':tonal.VERSION,
            'premusic_excluded':manifest['premusic_excluded'],
            'provenance_sha256':hashlib.sha256(allow_path.read_bytes()).hexdigest(),'manifest_sha256':manifest_hash,
            'profiles':profiles,'limits':['Platform AI labels include AI modification and may be inaccurate.',
              'Only 34 labelled reference works and 30 normal candidates; test FPR has coarse resolution.',
              'New positive queries cover two automatic transformations, not all five historical families.',
              'Premusic labels and independent-work relationships are unverified; diagnostic only.',
              'The full-catalog profile contains unverified reference creation methods; not AI-only.']}
    (ART/'ai_labeled_recalibration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
