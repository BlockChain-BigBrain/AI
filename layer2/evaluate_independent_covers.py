"""Covers80 independent-performance pilot; isolated from production calibration."""
import csv
import argparse
import json
import random
import subprocess
from pathlib import Path
import numpy as np
import torch
from transformers import ClapAudioModelWithProjection, ClapProcessor
import evaluate_retrieval_baseline as baseline
import evaluate_top3_aggregation as aggregation

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'layer2/external_data/covers80'
ART = ROOT / 'layer2/artifacts'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pairs',type=int,choices=(20,80),default=20)
    args=parser.parse_args()
    prefix='independent_cover_pilot' if args.pairs==20 else 'independent_cover_benchmark'
    # The benchmark pairs alternate performances, rather than asserting an
    # original/derivative direction or legal plagiarism label.
    a = (DATA/'list1.txt').read_text().splitlines()
    b = (DATA/'list2.txt').read_text().splitlines()
    assert len(a)==len(b)==80
    mp3 = list(DATA.rglob('*.mp3'))
    def locate(name):
        hits=[p for p in mp3 if p.as_posix().endswith(name+'.mp3')]
        assert len(hits)==1, name
        return hits[0]
    pairs=[]
    for left,right in zip(a,b):
        work=left.split('/')[0]
        assert work==right.split('/')[0]
        pairs.append({'work_id':work,'reference_path':str(locate(left)),
                      'query_path':str(locate(right)), 'label':'same_work_independent_performance',
                      'source_url':'https://www.labrosa.org/projects/coversongs/covers80/'})
    with (DATA/'pairs_manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(pairs[0]));w.writeheader();w.writerows(pairs)
    random.Random(20261022).shuffle(pairs)
    pairs=pairs[:args.pairs]
    torch.set_num_threads(2)
    baseline.FFMPEG_EXE=baseline.find_ffmpeg()
    device=torch.device('cpu')
    model=ClapAudioModelWithProjection.from_pretrained(baseline.BASE_MODEL,local_files_only=True).eval()
    processor=ClapProcessor.from_pretrained(baseline.BASE_MODEL,local_files_only=True)
    clips=DATA/'pilot_clips';clips.mkdir(exist_ok=True)
    vectors={}
    for i,pair in enumerate(pairs):
        for role in ('reference','query'):
            source=Path(pair[role+'_path']);out=clips/f"{pair['work_id']}__{role}.wav"
            if not out.exists():
                duration=baseline.get_duration_seconds(source)
                subprocess.run([baseline.FFMPEG_EXE,'-v','error','-nostdin','-ss',str(max(0,(duration-30)/2)),
                                '-i',str(source),'-t','30','-ac','1','-ar','48000',str(out)],check=True)
            v,starts=baseline.embed_file(out,model,processor,device,False,all_query_windows=True)
            vectors[(pair['work_id'],role)]=(v,starts)
        print(f'[independent {i+1}/{len(pairs)}] {pair["work_id"]}',flush=True)
    refs=np.concatenate([vectors[(p['work_id'],'reference')][0] for p in pairs])
    ids=np.concatenate([np.full(len(vectors[(p['work_id'],'reference')][0]),p['work_id']) for p in pairs])
    offsets=np.concatenate([vectors[(p['work_id'],'reference')][1] for p in pairs])
    mean=refs.mean(axis=0)
    results=[];negatives=[]
    for p in pairs:
        q,starts=vectors[(p['work_id'],'query')]
        matches=aggregation.score_all_tracks(q,starts,refs,ids,offsets,mean)['seg_top3_centered']
        rank=next(i for i,m in enumerate(matches,1) if m['track_id']==p['work_id'])
        results.append({**p,'expected_source_rank':rank,'top_work_id':matches[0]['track_id'],
                        'top_score':matches[0]['score'],'same_work_score':next(m['score'] for m in matches if m['track_id']==p['work_id'])})
        for m in matches:
            if m['track_id']!=p['work_id']:
                negatives.append({'query_work_id':p['work_id'],'candidate_work_id':m['track_id'],
                                  'score':m['score'],'label':'different_benchmark_work_candidate',
                                  'expert_review':'pending'})
    negatives.sort(key=lambda r:r['score'],reverse=True)
    negative_name='hard_negative_review_queue.csv' if args.pairs==20 else 'independent_cover_80_hard_negative_candidates.csv'
    for name,rows in [(prefix+'_results.csv',results),(negative_name,negatives)]:
        with (ART/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary={'dataset':'Covers80','acquired_annotated_pairs':80,'evaluated_pairs':len(pairs),
             'reference_tracks':len(pairs),'query_tracks':len(pairs),'clip_protocol':'center 30 seconds; all 10s windows at 5s stride',
            'selection_seed':20261022,'score':'seg_top3_centered; mean of selected independent reference vectors',
             'recall_at_1':float(np.mean([r['expected_source_rank']<=1 for r in results])),
             'recall_at_3':float(np.mean([r['expected_source_rank']<=3 for r in results])),
             'recall_at_5':float(np.mean([r['expected_source_rank']<=5 for r in results])),
             'mrr':float(np.mean([1/r['expected_source_rank'] for r in results])),
             'different_work_review_candidates':len(negatives),
             'limitations':[f'{len(pairs)}-work independent benchmark, not the 1000-work production catalog','No production thresholds fitted on this independent benchmark',
                             'Different work IDs are benchmark labels; expert musical review remains pending',
                             'No commercial redistribution license asserted'],
             'source_url':'https://www.labrosa.org/projects/coversongs/covers80/'}
    (ART/(prefix+'_summary.json')).write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
