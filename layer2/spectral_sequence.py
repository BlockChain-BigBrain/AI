"""Experimental octave-preserving dynamic CQT recording confirmation.

Unlike 12-class chroma, retain 84 semitone bands. Remove persistent band
energy before alignment to reduce shared instrumentation/pad matches.
"""
from pathlib import Path
import hashlib,os,subprocess
import numpy as np
import librosa
from numba import njit

VERSION='dynamic-cqt84-local-v1'
SR=22050
HOP=1024
WIDTH=5
STEP=WIDTH*HOP/SR


def features(path,ffmpeg,cache=None):
    path=Path(path);key=f'{VERSION}|{librosa.__version__}|{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}'
    target=Path(cache)/(hashlib.sha256(key.encode()).hexdigest()+'.npz') if cache else None
    if target and target.exists():
        with np.load(target,allow_pickle=False) as f:return f['rows'],float(f['duration']),STEP
    p=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(path),'-ac','1','-ar',str(SR),'-f','f32le','pipe:1'],check=True,capture_output=True)
    audio=np.frombuffer(p.stdout,dtype='<f4').copy()
    c=np.abs(librosa.cqt(y=audio,sr=SR,hop_length=HOP,n_bins=84,bins_per_octave=12,tuning=None))
    c=np.log1p(c/max(float(np.median(c)),1e-5))
    rows=np.stack([c[:,i:i+WIDTH].mean(axis=1) for i in range(0,c.shape[1],WIDTH)])
    rows-=np.median(rows,axis=0,keepdims=True)
    rows=(rows/np.maximum(np.linalg.norm(rows,axis=1,keepdims=True),1e-8)).astype(np.float32)
    duration=len(audio)/SR
    if target:
        target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_suffix(f'.{os.getpid()}.tmp.npz')
        np.savez_compressed(tmp,rows=rows,duration=duration);tmp.replace(target)
    return rows,duration,STEP


@njit(cache=True)
def _path(sim):
    n,m=sim.shape;dp=np.zeros((n+1,m+1),np.float32)
    si=np.zeros((n+1,m+1),np.int32);sj=np.zeros((n+1,m+1),np.int32)
    best=0.;best_i=0;best_j=0;start_i=0;start_j=0
    for i in range(1,n+1):
        for j in range(1,m+1):
            pi,pj=i-1,j-1;prior=dp[pi,pj]
            if i>=2 and dp[i-2,j-1]-.15>prior:pi,pj=i-2,j-1;prior=dp[pi,pj]-.15
            if j>=2 and dp[i-1,j-2]-.15>prior:pi,pj=i-1,j-2;prior=dp[pi,pj]-.15
            value=max(0.,prior+2*sim[i-1,j-1]-1)
            dp[i,j]=value
            if prior>0:si[i,j]=si[pi,pj];sj[i,j]=sj[pi,pj]
            else:si[i,j]=i-1;sj[i,j]=j-1
            if value>best:best=value;best_i=i;best_j=j;start_i=si[i,j];start_j=sj[i,j]
    return best,start_i,best_i,start_j,best_j


def compare(query,reference,query_step=STEP,reference_step=STEP):
    best=None
    for shift in range(-4,5):
        a,b=(query[:,max(0,-shift):84-max(0,shift)],reference[:,max(0,shift):84-max(0,-shift)])
        a=a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-8)
        b=b/np.maximum(np.linalg.norm(b,axis=1,keepdims=True),1e-8)
        value,qi,qe,ri,re=_path(np.ascontiguousarray(a@b.T))
        score=min(1.,value/max(round(10/query_step),min(len(a),len(b))))
        if best is None or score>best['spectralScore']:
            best={'spectralScore':float(score),'queryStartSec':qi*query_step,'queryEndSec':qe*query_step,
                  'refStartSec':ri*reference_step,'refEndSec':re*reference_step,'pitchShift':shift}
    return best
