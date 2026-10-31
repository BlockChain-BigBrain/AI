"""Prospective queries across five automatic transformation families.

Freeze policy/method hashes before generating queries. Source works have been
seen before: this is transformation stress validation, never fresh-work proof.
"""
from pathlib import Path
import hashlib,json,subprocess,time
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve
from threadpoolctl import threadpool_limits
import torch
import evaluate_retrieval_baseline as base
import evaluate_top3_aggregation as agg
import tonal_alignment as tonal
import dual_tonal_retrieval as dual
import compare_ai_improvements as exp

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
OUT=ROOT/'layer2/test_data/five_family_ai'
SEED=20261023


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    threadpool_limits(limits=4);torch.set_num_threads(4)
    base.FFMPEG_EXE=base.find_ffmpeg();OUT.mkdir(exist_ok=True)
    original=exp.read(ART/'ai_labeled_recalibration.json')
    frozen=exp.read(ART/'ai_selective_retrieval_evaluation.json')
    proposed=exp.read(ART/'dual_route_guard_evaluation.json')
    protocol={'date':'2026-10-23','seed':SEED,'sources':'Previously observed 14 test works; not independent unseen works.',
        'active_policy_sha256':sha(ART/'ai_improvement_policy.json'),
        'proposed_evaluation_sha256':sha(ART/'dual_route_guard_evaluation.json'),
        'families':['basic','instrument_layer','long_auto_edit','room_effect','local_tempo'],
        'calibration':'No fitting to these new queries; use previously frozen thresholds.',
        'deployment':'Diagnostic new-transformation test; keep active AI policy unless separately validated runtime change is justified.'}
    protocol_path=ART/'five_family_ai_protocol.json'
    if protocol_path.exists():assert exp.read(protocol_path)==protocol
    else:protocol_path.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    sources=exp.read(ROOT/'layer2/test_data/ai_labeled_positive/manifest.json')['rows']
    ids=sorted({r['expected_track_id'] for r in sources if r['dataset']=='positive' and r['split']=='test'})
    paths={base.track_id_from_original(p):p for p in base.audio_files(ROOT/'original_music')}
    manifest=OUT/'manifest.json'
    if manifest.exists():prepared=exp.read(manifest)['rows']
    else:
        prepared=[]
        for i,track in enumerate(ids):
            source=paths[track];duration=base.get_duration_seconds(source);offset=max(0,(duration-65)/2)
            p=subprocess.run([base.FFMPEG_EXE,'-v','error','-nostdin','-ss',str(offset),'-i',str(source),'-t','60','-ac','1','-ar','22050','-f','f32le','pipe:1'],check=True,capture_output=True)
            audio=np.frombuffer(p.stdout,dtype='<f4').copy();assert len(audio)>=20*22050
            if len(audio)<60*22050:audio=np.tile(audio,int(np.ceil(60*22050/len(audio))))[:60*22050]
            audio30=audio[:30*22050];rng=np.random.default_rng(SEED+i)
            for kind in protocol['families']:
                path=OUT/f'{i:03}__{kind}.wav';parameters={'source_offset':offset}
                if kind in ('basic','local_tempo'):
                    if kind=='basic':
                        filters=['-af','aresample=22050,asetrate=20812,aresample=22050,atempo=1.1336,lowpass=f=4400'];parameters.update(pitch_semitones=-1,speed=1.07)
                    else:
                        filters=['-filter_complex','[0:a]aresample=22050,asplit=2[a][b];[a]atrim=0:10,asetpts=PTS-STARTPTS,atempo=1.18[a1];[b]atrim=10:30,asetpts=PTS-STARTPTS,atempo=0.86[b1];[a1][b1]concat=n=2:v=0:a=1[out]','-map','[out]'];parameters.update(first_rate=1.18,second_rate=.86)
                    subprocess.run([base.FFMPEG_EXE,'-v','error','-nostdin','-y','-ss',str(offset),'-i',str(source),*filters,'-t','32','-ac','1','-ar','22050',str(path)],check=True,capture_output=True)
                else:
                    if kind=='instrument_layer':
                        t=np.arange(len(audio30))/22050
                        pad=(np.sin(2*np.pi*220*t)+.6*np.sin(2*np.pi*329.6276*t)+.4*np.sin(2*np.pi*440*t))
                        envelope=np.exp(-8*np.mod(t,.47));layer=pad*(.4+.6*envelope)
                        layer*=np.sqrt(np.mean(audio30**2))*.35/max(np.sqrt(np.mean(layer**2)),1e-9)
                        y=audio30+layer;parameters.update(added_layer='deterministic_synthetic_pad_and_pulse',layer_relative_rms=.35)
                    elif kind=='room_effect':
                        t=np.arange(int(.8*22050))/22050;ir=rng.normal(size=len(t))*np.exp(-6.907755*t/.8)
                        ir*=.45/max(np.linalg.norm(ir),1e-9);ir[0]+=1
                        y=fftconvolve(audio30,ir)[:len(audio30)]
                        noise=rng.normal(size=len(y));noise*=np.sqrt(np.mean(y*y))/(10**(18/20)*max(np.sqrt(np.mean(noise*noise)),1e-9));y+=noise
                        parameters.update(synthetic_rt60=.8,noise_snr_db=18)
                    else:
                        order=[2,0,3,1,0,2,1,3];rates=[1.03,.97,1.05,.95]*2;chunks=[]
                        for segment,rate in zip(order,rates):
                            part=audio[segment*15*22050:(segment+1)*15*22050]
                            chunks.append(np.interp(np.arange(0,len(part),rate),np.arange(len(part)),part))
                        y=np.concatenate(chunks);parameters.update(section_order=order,resample_rates=rates,pitch_and_speed_joint_change=True)
                    y*=min(1,.96/max(np.max(np.abs(y)),1e-9));sf.write(path,y.astype(np.float32),22050,subtype='PCM_16')
                prepared.append({'file':str(path),'dataset':'positive','split':'prospective_five_family','query_kind':kind,
                    'expected_track_id':track,'source_sha256':sha(source),'sha256':sha(path),'parameters':parameters})
            print(f'[prepare five families {i+1}/{len(ids)}]',flush=True)
        manifest.write_text(json.dumps({'protocol_sha256':sha(protocol_path),'rows':prepared},indent=2),encoding='utf-8')
    assert exp.read(manifest)['protocol_sha256']==sha(protocol_path)
    model=agg.ClapAudioModelWithProjection.from_pretrained(base.BASE_MODEL,local_files_only=True).eval()
    processor=agg.ClapProcessor.from_pretrained(base.BASE_MODEL,local_files_only=True);device=torch.device('cpu')
    with np.load(ART/'current_reference_catalog.npz',allow_pickle=False) as f:vectors,all_ids=f['vectors'].astype(np.float32),f['ids']
    with np.load(ART/'dual_tonal_index.npz',allow_pickle=False) as f:
        index=dual.Index.__new__(dual.Index);index.matrix=f['vectors'];index.ids=f['ids'].tolist();index.starts=f['starts'].tolist()
    catalogs={}
    for scope,profile in original['profiles'].items():
        allowed=set(profile['allowed_reference_ids']) if scope=='ai_labeled_catalog' else None
        mask=np.isin(all_ids,list(allowed)) if allowed else np.ones(len(all_ids),bool)
        v,ids_=vectors[mask],all_ids[mask];mean=v.mean(axis=0)
        catalogs[scope]=(mean,agg.unit_rows(v-mean),[(str(t),np.flatnonzero(ids_==t)) for t in np.unique(ids_)],allowed)
    features={}
    def tonal_features(path):
        key=str(path)
        if key not in features:features[key]=tonal.features(path,base.FFMPEG_EXE,ART/'tonal_feature_cache')
        return features[key]
    signature=sha(manifest);checkpoint=ART/'five_family_ai_checkpoint.jsonl';done={};results=[]
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['signature']==signature:done[(r['scope'],r['file'])]=r
    with checkpoint.open('a',encoding='utf-8') as log:
        for n,row in enumerate(prepared,1):
            if all((scope,row['file']) in done for scope in catalogs):results.extend(done[(scope,row['file'])] for scope in catalogs);continue
            path=Path(row['file']);assert sha(path)==row['sha256']
            q,starts=base.embed_file(path,model,processor,device,False,all_query_windows=True);qt,_,qs=tonal_features(path)
            for scope,(mean,centered,groups,allowed) in catalogs.items():
                sim=agg.unit_rows(q-mean)@centered.T
                ranked=sorted([{'trackId':t,'clapScore':agg.non_overlapping_top3(sim[:,indices],starts)[0]} for t,indices in groups],key=lambda r:r['clapScore'],reverse=True)
                ranks={r['trackId']:i for i,r in enumerate(ranked,1)};by_id={r['trackId']:r for r in ranked}
                first={c['trackId'] for c in ranked[:20]};union=first|{c['trackId'] for c in index.search(qt,allowed,20)}
                confirmed=[]
                for track in sorted(union):
                    ref,_,rs=tonal_features(paths[track]);confirmed.append({**by_id[track],**tonal.compare(qt,ref,qs,rs),'retrievalRank':ranks[track]})
                def convert(proposal):
                    candidates=[]
                    for c in confirmed:
                        if not proposal and c['trackId'] not in first:continue
                        rank=c['retrievalRank'];raw=c['tonalScore'];power=1 if rank<=5 else 2 if rank<=20 else proposed['profiles'][scope]['selected_second_route_power']
                        candidates.append({**c,'unpenalizedTonalScore':raw,'tonalScore':raw**power})
                    candidates.sort(key=lambda c:c['tonalScore'],reverse=True)
                    return {'candidates':candidates,'score':candidates[0]['tonalScore'],
                        'expected_score':next((c['tonalScore'] for c in candidates if c['trackId']==row['expected_track_id']),None),
                        'source_rank_after_tonal':next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)}
                result={**row,'scope':scope,'signature':signature,'current':convert(False),'proposed':convert(True)}
                results.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n');log.flush()
            print(f'[five-family query {n}/{len(prepared)}] {row["query_kind"]}',flush=True)
    profiles={}
    for scope in catalogs:
        selected_power=str(proposed['profiles'][scope]['selected_second_route_power'])
        policies={'current':frozen['profiles'][scope],'proposed':proposed['profiles'][scope]['methods'][selected_power]}
        profiles[scope]={}
        for method,policy in policies.items():
            part=[{**r,**r[method]} for r in results if r['scope']==scope]
            profiles[scope][method]={'all':exp.metrics(part,policy),'by_family':{kind:exp.metrics([r for r in part if r['query_kind']==kind],policy) for kind in protocol['families']}}
    report={'date':'2026-10-23','protocol':protocol,'manifest_sha256':signature,'queries':len(prepared),'source_works':len(ids),
        'profiles':profiles,'active_policy_changed':False}
    (ART/'five_family_ai_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
