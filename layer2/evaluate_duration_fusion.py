"""Evaluate short-only fusion with the existing >=45s policy preserved.

This is an exploratory development protocol after observing the two earlier
prototypes, not a new blind study. Calibration uses tune normal works only.
"""
from pathlib import Path
import hashlib,json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import evaluate_retrieval_baseline as base
from evaluate_spectral_fusion import read_rows
import spectral_fusion as fusion

ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'layer2/artifacts'


def main():
    base.FFMPEG_EXE=base.find_ffmpeg()
    old=read_rows('secondary_precision_checkpoint.jsonl');crops=read_rows('duration_normal_checkpoint.jsonl')
    assert len({r['file'] for r in crops})==93
    rows={r['file']:r for r in old+crops}
    spec={r['file']:r for r in read_rows('spectral_release_checkpoint.jsonl') if r['scope']=='ai_labeled_catalog'}
    assert len(spec)==319
    with ThreadPoolExecutor(max_workers=4) as pool:durations=dict(zip(rows,pool.map(lambda p:base.get_duration_seconds(Path(p)),rows)))
    policy=json.loads((ART/'ai_precision_policy.json').read_text())
    warn,hold=policy['warn_threshold'],policy['hold_threshold']
    excluded={r['normal'] for r in json.loads((ART/'ai_near_duplicate_audit.json').read_text())['pairs'] if r['quarantine_normal_label']}
    groups={};spectral_groups={}
    for r in rows.values():
        if r['split']!='tune' or r['dataset']=='positive' or r['file'] in excluded or durations[r['file']]>=fusion.MAX_SHORT_SECONDS:continue
        g=r.get('group_id','normal:'+Path(r['file']).stem)
        groups[g]=max(groups.get(g,0.),r['score']);spectral_groups[g]=max(spectral_groups.get(g,0.),spec[r['file']]['score'])
    long_warns=set()
    for r in rows.values():
        if r['split']=='tune' and r['dataset']!='positive' and r['file'] not in excluded and durations[r['file']]>=fusion.MAX_SHORT_SECONDS and r['score']>=warn:
            long_warns.add(r.get('group_id','normal:'+Path(r['file']).stem))
    choices=sorted(set([warn]+list(groups.values())+[float(np.nextafter(max(groups.values()),np.inf))]))
    primary_cut=next(t for t in choices if len(long_warns|{g for g,s in groups.items() if s>=t})/len(groups)<=.1)
    spectral_cut=max(.30,1.05*max(spectral_groups.values()))
    results=[];regressions=[]
    for row in rows.values():
        candidates=fusion.combine(row['candidates'],spec[row['file']]['candidates'],primary_cut,spectral_cut,warn,hold) if durations[row['file']]<fusion.MAX_SHORT_SECONDS else sorted([{**c,'score':c.get('tonalScore',c.get('score'))} for c in row['candidates']],key=lambda c:c['score'],reverse=True)
        expected=next((c['score'] for c in candidates if c['trackId']==row['expected_track_id']),None)
        rank=next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)
        updated={**row,'duration_seconds':durations[row['file']],'group_id':row.get('group_id','normal:'+Path(row['file']).stem),'score':candidates[0]['score'],'expected_score':expected,'source_rank':rank,'candidates':candidates[:3]};results.append(updated)
        if row['dataset']=='positive' and row['expected_score']>=warn and row['source_rank_after_tonal']<=3 and not(expected is not None and expected>=warn and rank<=3):regressions.append(row['file'])
    def metrics(part,exclusions=excluded):
        pos=[r for r in part if r['dataset']=='positive'];neg=[r for r in part if r['dataset']!='positive' and r['file'] not in exclusions];works={}
        for r in neg:works[r['group_id']]=max(works.get(r['group_id'],0),r['score'])
        correct=sum(r['expected_score'] is not None and r['expected_score']>=warn and r['source_rank']<=3 for r in pos)
        return {'positive_queries':len(pos),'correct_source_count':correct,'recall':correct/len(pos) if pos else None,'normal_queries':len(neg),'normal_works':len(works),'warn_works':sum(v>=warn for v in works.values()),'hold_works':sum(v>=hold for v in works.values()),'warn_rate':sum(v>=warn for v in works.values())/len(works) if works else None,'hold_rate':sum(v>=hold for v in works.values())/len(works) if works else None}
    summary={split:metrics([r for r in results if r['split']==split]) for split in sorted({r['split'] for r in results})}
    report={'method':fusion.VERSION,'status':'completed_exploratory_development','active_policy_changed':False,
        'calibration':'Tune normal works only. The union of existing long-view warnings and short-view warnings must stay <=10%; spectral cutoff max(.30,1.05*max tune normal spectral evidence).',
        'primary_cutoff':primary_cut,'spectral_cutoff':spectral_cut,'short_seconds_exclusive':fusion.MAX_SHORT_SECONDS,
        'thresholds':{'warn':warn,'hold':hold},'summary':summary,
        'by_family':{kind:metrics([r for r in results if r['split']=='prospective_five_family' and r['query_kind']==kind]) for kind in ('basic','instrument_layer','long_auto_edit','room_effect','local_tempo')},
        'normal_crops':{split:metrics([r for r in results if r['split']==split and r['query_kind'].startswith('normal_30s_')]) for split in ('tune','test','external_diagnostic')},
        'raw_test':metrics([r for r in results if r['split']=='test'],set()),'per_query_source_regressions':regressions,
        'acceptance_met':not regressions and all(summary[s]['warn_rate']<=.10 and summary[s]['hold_rate']<=.02 for s in ('tune','test')) and summary['prospective_five_family']['recall']>=.9,
        'limits':'Known works and development-selected protocol. This is not fresh validation, pure-AI verification or a 1000-reference result.'}
    path=ART/'duration_fusion_evaluation.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (ART/'duration_fusion_checkpoint.jsonl').open('w',encoding='utf-8') as log:
        for row in results:log.write(json.dumps(row)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
