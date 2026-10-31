"""Agreement of FFT/CQT and three distinct centered CQT fragments.

Used only when existing score<.60 and only for original CLAP Top3.
The resulting fallback cannot reach the active HOLD threshold.
"""
import math
import tonal_alignment as tonal
import fragment_confirmation as fragments

VERSION='cqt-consensus-fragments-v1'


def compare(query,reference,query_step,reference_step,fft_score):
    whole=tonal.compare(query,reference,query_step,reference_step)
    agreement=math.sqrt(max(0.,fft_score)*max(0.,whole['tonalScore']))
    fragment=fragments.compare(query,reference,query_step,reference_step,center_time=True)
    fragment_score=1.5*fragment['fragmentScore']
    score=max(agreement,fragment_score)
    segments=fragment['fragments'] if fragment_score>agreement else [whole]
    return {'score':score,'wholeScore':whole['tonalScore'],'agreementScore':agreement,
            'fragmentScore':fragment_score,'segments':segments}
