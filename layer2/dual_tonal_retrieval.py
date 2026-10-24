"""Pitch-rotation-invariant short-sequence index, used only for candidates.

Four short profiles plus adjacent Fourier cross-power retain chord shape and
relative motion while removing a constant pitch rotation. No labels are fit.
"""
from pathlib import Path
import numpy as np
import tonal_alignment as tonal

VERSION='pitch-fourier-crosspower-v1'


def descriptors(rows):
    if len(rows)<8:rows=np.pad(rows,((0,8-len(rows)),(0,0)))
    starts=list(range(0,len(rows)-7,4))
    if starts[-1]!=len(rows)-8:starts.append(len(rows)-8)
    chunks=np.stack([rows[i:i+8].reshape(4,2,12).mean(axis=1) for i in starts])
    chunks/=np.maximum(np.linalg.norm(chunks,axis=2,keepdims=True),1e-8)
    fourier=np.fft.rfft(chunks,axis=2)[:,:,1:]
    cross=fourier[:,1:]*np.conj(fourier[:,:-1])
    features=np.concatenate([np.abs(fourier).reshape(len(chunks),-1),cross.real.reshape(len(chunks),-1),cross.imag.reshape(len(chunks),-1)],axis=1)
    features/=np.maximum(np.linalg.norm(features,axis=1,keepdims=True),1e-8)
    return features.astype(np.float32)


class Index:
    def __init__(self,paths,ffmpeg,cache):
        self.paths=paths;self.ids=sorted(paths);parts=[];self.starts=[];count=0
        self.features={}
        for i,track in enumerate(self.ids):
            rows,duration,step=tonal.features(paths[track],ffmpeg,cache)
            self.features[track]=(rows,duration,step)
            part=descriptors(rows);self.starts.append(count);count+=len(part);parts.append(part)
            if (i+1)%100==0:print(f'[tonal index {i+1}/{len(self.ids)}]',flush=True)
        self.matrix=np.concatenate(parts)

    def search(self,rows,allowed=None,top_k=20):
        query=descriptors(rows)
        # Largest three local descriptor hits are a shortlist proxy only,
        # never independent evidence or an upload verdict.
        per_track=np.maximum.reduceat(query@self.matrix.T,self.starts,axis=1)
        k=min(3,len(query));scores=np.partition(per_track,-k,axis=0)[-k:].mean(axis=0)
        ranked=sorted([{'trackId':track,'tonalRetrievalScore':float(scores[i])} for i,track in enumerate(self.ids)
                       if allowed is None or track in allowed],key=lambda r:r['tonalRetrievalScore'],reverse=True)
        return ranked[:top_k]
