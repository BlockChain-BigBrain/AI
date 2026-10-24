"""Duration-aware short-query recording confirmation; long policy unchanged."""
import numpy as np

VERSION='duration-dynamic-cqt84-v1'
MAX_SHORT_SECONDS=45.


def remap_primary(score,cutoff,warn,hold):
    if score>=hold:return score
    if score<cutoff:return score*warn/cutoff
    return warn+(score-cutoff)*(hold-warn)/(hold-cutoff)


def combine(primary,spectral,primary_cut,spectral_cut,warn,hold):
    if not 0<warn<=primary_cut<hold<=1 or not 0<spectral_cut<=1:
        raise ValueError('Invalid duration-fusion thresholds.')
    candidates={}
    for c in primary:
        raw=float(c.get('tonalScore',c.get('score')))
        candidates[c['trackId']]={**c,'score':remap_primary(raw,primary_cut,warn,hold)}
    for c in spectral:
        score=min(float(np.nextafter(hold,0)),warn*c['score']/spectral_cut)
        current=candidates.get(c['trackId'])
        if current is None or score>current['score']:
            candidates[c['trackId']]={**c,'score':score}
    return sorted(candidates.values(),key=lambda c:c['score'],reverse=True)
