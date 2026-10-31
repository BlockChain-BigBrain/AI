"""Supplemental CQT evidence on its own calibrated WARN cutoff."""
import tonal_alignment as tonal
import fragment_confirmation as fragments

VERSION='secondary-clap-cqt-fragments-v1'


def compare(query,reference,query_step,reference_step,clap_score,primary_warn,secondary_cutoff):
    whole=tonal.compare(query,reference,query_step,reference_step)
    fragment=fragments.compare(query,reference,query_step,reference_step,center_time=False)
    selected=fragment['fragments'];fragment_mean=0.
    if len(selected)==3 and min(s['tonalScore'] for s in selected)>=.65:
        fragment_mean=sum(s['tonalScore'] for s in selected)/3
    raw=min(.8,(max(0,clap_score)*max(whole['tonalScore'],fragment_mean))**2)
    mapped=min(.8,primary_warn*raw/secondary_cutoff)
    return {'score':mapped,'rawScore':raw,'wholeScore':whole['tonalScore'],'fragmentMean':fragment_mean,
        'segments':selected if fragment_mean>whole['tonalScore'] else [whole]}
