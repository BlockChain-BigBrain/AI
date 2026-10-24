"""Require three separated 10-second pitch-progress matches for long edits.

Experimental bounded score; no probability or independence guarantee.
"""
import numpy as np
import tonal_alignment as tonal

VERSION='three-fragment-contrast-v1'


def contrast(rows):
    x=rows-rows.mean(axis=0,keepdims=True)
    return np.ascontiguousarray(x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-8),dtype=np.float32)


def compare(query,reference,query_step,reference_step,center_time=True):
    if len(query)*query_step<45:return {'fragmentScore':0.,'fragments':[]}
    width=max(20,round(10/query_step))
    starts=list(range(0,len(query)-width+1,width))
    if len(starts)>12:starts=[starts[i] for i in np.linspace(0,len(starts)-1,12).astype(int)]
    a,b=(contrast(query),contrast(reference)) if center_time else (query,reference)
    matches=[]
    for start in starts:
        match=tonal.compare(a[start:start+width],b,query_step,reference_step)
        if match['queryEndSec']-match['queryStartSec']<8 or match['refEndSec']-match['refStartSec']<8:continue
        match['queryStartSec']+=start*query_step;match['queryEndSec']+=start*query_step;matches.append(match)
    selected=[]
    for match in sorted(matches,key=lambda r:r['tonalScore'],reverse=True):
        if all(max(0,min(match['refEndSec'],r['refEndSec'])-max(match['refStartSec'],r['refStartSec']))<4 for r in selected):
            selected.append(match)
        if len(selected)==3:break
    score=0.
    if len(selected)==3 and min(r['tonalScore'] for r in selected)>=.65:
        score=.5*float(np.mean([r['tonalScore'] for r in selected]))**2
    return {'fragmentScore':score,'fragments':selected}
