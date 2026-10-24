"""Exploratory tune-only fusion after the fixed-floor spectral experiment.

Known-data development, not an untouched confirmation experiment. Neither
test scores nor positive labels select the two warning thresholds.
"""
from pathlib import Path
import hashlib,json
import numpy as np

ART=Path(__file__).resolve().parent/'artifacts'


def read_rows(name):
    return [json.loads(s) for s in (ART/name).read_text(encoding='utf-8').splitlines()]


def fuse(primary,spectral,primary_cut,spectral_cut,warn,hold):
    candidates={}
    for c in primary:
        track=c['trackId'];value=c.get('tonalScore',c.get('score'))
        candidates[track]={**c,'trackId':track,'score':float(value)*warn/primary_cut,'primaryRawScore':float(value)}
    for c in spectral:
        value=min(float(np.nextafter(hold,0)),warn*c['score']/spectral_cut)
        current=candidates.get(c['trackId'])
        if current is None or value>current['score']:
            candidates[c['trackId']]={**c,'score':value,'spectralRawScore':c['score']}
    return sorted(candidates.values(),key=lambda c:c['score'],reverse=True)


def main():
    old=read_rows('secondary_precision_checkpoint.jsonl')
    crops=read_rows('duration_normal_checkpoint.jsonl')
    assert len({r['file'] for r in crops})==93,'Finish actual duration-normal engine evaluation first.'
    spectral=read_rows('spectral_release_checkpoint.jsonl')
    spec={r['file']:r for r in spectral if r['scope']=='ai_labeled_catalog'}
    assert len(spec)==319,'Finish spectral experiment first.'
    rows={r['file']:r for r in old+crops}
    excluded={r['normal'] for r in json.loads((ART/'ai_near_duplicate_audit.json').read_text())['pairs'] if r['quarantine_normal_label']}
    normal={};spectral_normal={}
    for r in rows.values():
        if r['dataset']=='positive' or r['split']!='tune' or r['file'] in excluded:continue
        group=r.get('group_id','normal:'+Path(r['file']).stem)
        normal[group]=max(normal.get(group,0),r['score'])
        spectral_normal[group]=max(spectral_normal.get(group,0),spec[r['file']]['score'])
    policy=json.loads((ART/'ai_precision_policy.json').read_text())
    choices=sorted(set([policy['warn_threshold']]+list(normal.values())+[float(np.nextafter(max(normal.values()),np.inf))]))
    primary_cut=next(t for t in choices if sum(s>=t for s in normal.values())/len(normal)<=.10)
    spectral_cut=max(.30,1.05*max(spectral_normal.values()))
    warn=policy['warn_threshold'];hold=policy['hold_threshold']*warn/primary_cut
    results=[];regressions=[]
    for row in rows.values():
        s=spec[row['file']]
        candidates=fuse(row['candidates'],s['candidates'],primary_cut,spectral_cut,warn,hold)
        expected=next((c['score'] for c in candidates if c['trackId']==row['expected_track_id']),None)
        rank=next((i for i,c in enumerate(candidates,1) if c['trackId']==row['expected_track_id']),None)
        results.append({**row,'group_id':row.get('group_id','normal:'+Path(row['file']).stem),
                        'score':candidates[0]['score'],'expected_score':expected,'source_rank':rank,'candidates':candidates[:3]})
        if row['dataset']=='positive' and row['expected_score']>=warn and row['source_rank_after_tonal']<=3 and not(expected is not None and expected>=warn and rank<=3):regressions.append(row['file'])
    def metrics(part,exclusions=excluded):
        positives=[r for r in part if r['dataset']=='positive'];negatives=[r for r in part if r['dataset']!='positive' and r['file'] not in exclusions];groups={}
        for r in negatives:groups[r['group_id']]=max(groups.get(r['group_id'],0),r['score'])
        correct=sum(r['expected_score'] is not None and r['expected_score']>=warn and r['source_rank']<=3 for r in positives)
        return {'positive_queries':len(positives),'correct_source_count':correct,'recall':correct/len(positives) if positives else None,
                'normal_queries':len(negatives),'normal_works':len(groups),'warn_works':sum(v>=warn for v in groups.values()),
                'hold_works':sum(v>=hold for v in groups.values()),'warn_rate':sum(v>=warn for v in groups.values())/len(groups) if groups else None,
                'hold_rate':sum(v>=hold for v in groups.values())/len(groups) if groups else None}
    summary={split:metrics([r for r in results if r['split']==split]) for split in sorted({r['split'] for r in results})}
    families={kind:metrics([r for r in results if r['split']=='prospective_five_family' and r['query_kind']==kind]) for kind in sorted({r['query_kind'] for r in results if r['split']=='prospective_five_family'})}
    report={'status':'completed_exploratory_development','active_policy_changed':False,
        'protocol':'Tune-only primary cutoff at <=10% work-level false warnings; spectral cutoff max(.30,1.05*maximum tune normal work spectral score). Max of mapped candidate scores, spectral route cannot create HOLD.',
        'primary_cutoff':primary_cut,'spectral_cutoff':spectral_cut,'warn':warn,'hold':hold,
        'summary':summary,'by_family':families,'raw_test':metrics([r for r in results if r['split']=='test'],set()),
        'limits':'Protocol chosen after spectral development observations; all works already seen. Independent fresh AI evaluation remains required.',
        'per_query_source_regressions':regressions,
        'acceptance_met':not regressions and all(summary[s]['warn_rate']<=.10 and summary[s]['hold_rate']<=.02 for s in ('tune','test')) and summary['test']['recall']==1 and summary['prospective_five_family']['recall']>=.9}
    (ART/'spectral_fusion_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
