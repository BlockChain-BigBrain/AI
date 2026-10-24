"""CQT-based pitch features for the secondary confirmation experiment."""
from pathlib import Path
import hashlib,os,subprocess
import numpy as np
import librosa

VERSION='cqt36-centered-0.5s-v1'
SAMPLE_RATE=22050
HOP=2048


def features(path,ffmpeg,cache=None):
    path=Path(path)
    signature=f'{VERSION}|librosa={librosa.__version__}|{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}'
    target=Path(cache)/(hashlib.sha256(signature.encode()).hexdigest()+'.npz') if cache else None
    if target and target.exists():
        with np.load(target,allow_pickle=False) as f:return f['rows'],float(f['duration']),float(f['step'])
    p=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(path),'-ac','1','-ar',str(SAMPLE_RATE),'-f','f32le','pipe:1'],capture_output=True,check=True)
    audio=np.frombuffer(p.stdout,dtype='<f4').copy()
    raw=librosa.feature.chroma_cqt(y=audio,sr=SAMPLE_RATE,hop_length=HOP,bins_per_octave=36,n_octaves=7,tuning=None,norm=2)
    width=round(.5*SAMPLE_RATE/HOP)
    rows=np.stack([raw[:,i:i+width].mean(axis=1) for i in range(0,raw.shape[1],width)])
    rows-=rows.mean(axis=1,keepdims=True)
    rows=(rows/np.maximum(np.linalg.norm(rows,axis=1,keepdims=True),1e-8)).astype(np.float32)
    duration=len(audio)/SAMPLE_RATE;step=width*HOP/SAMPLE_RATE
    if target:
        target.parent.mkdir(exist_ok=True,parents=True);temp=target.with_suffix(f'.{os.getpid()}.tmp.npz')
        np.savez_compressed(temp,rows=rows,duration=duration,step=step);temp.replace(target)
    return rows,duration,step
