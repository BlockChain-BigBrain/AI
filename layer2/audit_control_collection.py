"""Read-only near-recording audit of all music/premusic against original_music.

Fingerprint seeds shortlist candidates; aligned bit error and three waveform
excerpts corroborate. This is a bounded screen, not proof of independence.
"""
from pathlib import Path
from collections import defaultdict,Counter
from concurrent.futures import ThreadPoolExecutor
import csv,hashlib,json,subprocess,sys
import numpy as np
from scipy.signal import correlate
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
CACHE=ROOT/'.runtime-tests/collection-fingerprint-audit'
sys.path.insert(0,str(ROOT/'layer1'))
import upload_guard_api as gate


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_error(a,b,offset):
    # Offset is reference frame minus query frame.
    a,b=a[max(0,-offset):],b[max(0,offset):]
    n=min(len(a),len(b))
    if n<240:return 1.,n
    return float(np.unpackbits(np.bitwise_xor(a[:n],b[:n]).view(np.uint8)).mean()),n


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    records=gate._load_db();references=[]
    for key,row in records.items():
        path=Path(row.get('file_path',''))
        if path.parent.resolve()==(ROOT/'original_music').resolve() and row.get('fingerprint_raw'):
            references.append((path,np.asarray(row['fingerprint_raw'],dtype=np.uint32),float(row['duration'])))
    assert len(references)==1000
    postings=defaultdict(list)
    for ri,(_,fp,_) in enumerate(references):
        for frame,value in enumerate(fp):postings[int(value>>16)].append((ri,frame))
    # Repetitive subfingerprints produce uninformative huge buckets.
    postings={key:values for key,values in postings.items() if len(values)<=2000}
    paths=sorted([p for folder in ('music','premusic') for p in (ROOT/folder).iterdir() if p.suffix.lower() in ('.mp3','.wav','.m4a','.flac','.ogg','.webm')])
    assert len(paths)==500
    def load(path):
        sha=digest(path);cache=CACHE/(sha+'.json')
        if cache.exists():r=json.loads(cache.read_text(encoding='utf-8'))
        else:
            try:r=gate.extract_raw_fingerprint(path)
            except ValueError as exc:r={'error':str(exc)}
            cache.write_text(json.dumps(r),encoding='utf-8')
        return path,sha,r
    def waveform(path,start):
        p=subprocess.run([ffmpeg,'-v','error','-nostdin','-ss',str(max(0,start)),'-i',str(path),'-t','20','-ac','1','-ar','8000','-f','f32le','pipe:1'],check=True,capture_output=True)
        x=np.frombuffer(p.stdout,dtype='<f4').astype(np.float64);return x-x.mean()
    details=[];candidates=[];errors=[]
    checkpoint=CACHE/'audit_checkpoint.jsonl';done={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line);done[(r['detail']['file'],r['detail']['sha256'])]=r
    with ThreadPoolExecutor(max_workers=2) as pool:
        for n,(path,sha,record) in enumerate(pool.map(load,paths),1):
            if (str(path),sha) in done:
                previous=done[(str(path),sha)];details.append(previous['detail']);candidates.extend(previous['candidates']);continue
            if 'error' in record:
                errors.append({'file':str(path),'error':record['error']})
                details.append({'folder':path.parent.name,'file':str(path),'sha256':sha,'fingerprint_frames':0,
                    'screened_candidate_count':0,'low_bit_error_candidates':0,'near_identical_reference_ids':[]})
                print(f'[collection audit {n}/{len(paths)}] unscorable short/invalid audio',flush=True);continue
            fp=np.asarray(record['fingerprint_raw'],dtype=np.uint32);votes=Counter()
            for qi in range(0,len(fp),8):
                for ri,rj in postings.get(int(fp[qi]>>16),()):votes[(ri,(rj-qi)//3)]+=1
            best={}
            for (ri,bucket),count in votes.most_common(32):
                for offset in range(bucket*3-2,bucket*3+5):
                    err,overlap=bit_error(fp,references[ri][1],offset)
                    if ri not in best or err<best[ri][0]:best[ri]=(err,offset,overlap,count)
            confirmed=[];suspect_count=0;pair_start=len(candidates)
            for ri,(err,offset,overlap,count) in sorted(best.items(),key=lambda kv:kv[1][0])[:5]:
                if err>=.18:continue
                suspect_count+=1;ref,_,duration=references[ri]
                delta=offset*(1365/11025)
                q0=max(0,-delta);r0=max(0,delta)
                available=min(record['duration']-q0,duration-r0)
                correlations=[]
                if available>=30:
                    for part in (.05,.45,.80):
                        start=max(0,(available-20)*part)
                        a,b=waveform(path,q0+start),waveform(ref,r0+start);size=min(len(a),len(b));a,b=a[:size],b[:size]
                        c=correlate(a,b,mode='full',method='fft');center=len(b)-1
                        correlations.append(float(np.max(np.abs(c[max(0,center-8000):center+8001]))/max(np.linalg.norm(a)*np.linalg.norm(b),1e-12)))
                near=err<.10 and len(correlations)==3 and min(correlations)>.98
                candidate={'folder':path.parent.name,'file':str(path),'sha256':sha,'reference':str(ref),
                    'reference_sha256':digest(ref),'fingerprint_bit_error':err,'offset_frames':offset,
                    'overlap_frames':overlap,'waveform_correlations':correlations,'near_identical_recording':near}
                candidates.append(candidate)
                if near:confirmed.append(ref.stem)
            details.append({'folder':path.parent.name,'file':str(path),'sha256':sha,'fingerprint_frames':len(fp),
                'screened_candidate_count':len(best),'low_bit_error_candidates':suspect_count,
                'near_identical_reference_ids':confirmed})
            with checkpoint.open('a',encoding='utf-8') as log:log.write(json.dumps({'detail':details[-1],'candidates':candidates[pair_start:]})+'\n')
            print(f'[collection audit {n}/{len(paths)}] {path.parent.name} confirmed={len(confirmed)}',flush=True)
    report={'date':'2026-10-23','status':'completed_bounded_near_recording_screen','reference_tracks':1000,
        'fingerprint_index_sha256':digest(ROOT/'layer1/fingerprints_db.json'),
        'normal_candidate_files':300,'premusic_files':200,'all_files_preserved':True,
        'method':'High-16-bit seed votes; top 32 offset buckets, top 5 aligned candidates; BER<.18 triggers waveform checks; BER<.10 and three correlations>.98 corroborate.',
        'limits':['Uses existing full-file reference fingerprint snapshot.','Not robust to substantial tempo changes or heavily edited copies.',
                  'No match is not proof of musical independence, pure AI creation or copyright status.','No automatic BLOCK or source-label rewrite.'],
        'counts':{folder:{'files':sum(r['folder']==folder for r in details),'near_identical_files':sum(r['folder']==folder and bool(r['near_identical_reference_ids']) for r in details)} for folder in ('music','premusic')},
        'unscorable_files':errors,'near_identical_pairs':[r for r in candidates if r['near_identical_recording']],
        'fingerprint_suspect_pairs':candidates}
    (ART/'control_collection_near_duplicate_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (ART/'control_collection_near_duplicate_files.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(details[0]));writer.writeheader();writer.writerows(details)
    print(json.dumps(report['counts'],indent=2))


if __name__=='__main__':main()
