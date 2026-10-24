"""Verify replacement evidence, generated assets and evaluation integration."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import numpy as np
import soundfile as sf
import evaluate_retrieval_baseline as baseline
import evaluate_top3_aggregation as top3

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'layer2/artifacts'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    changes = json.loads((ART/'control_replacement_20261022/changes.json').read_text(encoding='utf-8'))
    assert Counter(r['action'] for r in changes) == {'removed_duplicate':17,'moved_from_premusic':17}
    for r in changes:
        p = Path(r['file'])
        if r['action'] == 'removed_duplicate':
            assert not p.exists()
            assert digest(ART/'control_replacement_20261022'/p.name) == r['sha256']
        else:
            assert digest(p) == r['sha256'] and not Path(r['previous_path']).exists()
    normal = list(csv.DictReader((ART/'music_duplicate_report.csv').open(encoding='utf-8-sig')))
    assert len(normal) == 300 and all(r['status']=='NO_EXACT_MATCH' for r in normal)
    assert len(baseline.audio_files(ROOT/'original_music')) == 1000
    assert len(baseline.audio_files(ROOT/'music')) == 300
    assert len(baseline.audio_files(ROOT/'premusic')) == 200
    extended = list(csv.DictReader((ROOT/'layer2/test_data/extended_positive/manifest.csv').open(encoding='utf-8-sig')))
    assert len(extended)==180
    assert Counter(r['case_type'] for r in extended)=={'room_rerecord_simulation':90,'local_tempo_warp':90}
    for r in extended:
        p = Path(r['query_path'])
        assert digest(p)==r['sha256'] and Path(r['source_path']).is_file()
        x,sr = sf.read(p)
        assert sr==22050 and np.isfinite(x).all() and 59<len(x)/sr<63
        assert 0<float(np.sqrt(np.mean(x*x))) and float(np.max(np.abs(x)))<0.98
    queries,_ = top3.build_queries(set(), True)
    positive = [q for q in queries if q['label']=='positive']
    assert len(positive)==340
    assert all(q['group_id']=='positive:'+q['expected_track_id'] for q in positive)
    sid=extended[0]['source_track_id']
    filtered,_=top3.build_queries({sid},True)
    assert all(q['expected_track_id']!=sid for q in filtered if q['label']=='positive')
    # Macro rate must weight works equally, rather than count every variant equally.
    test_rows=[{'query_kind':'test','group_id':g,'expected_source_in_top5':hit,'expected_source_score':score}
               for g,hit,score in [('a',True,.9),('a',False,.2),('b',True,.95)]]
    m=top3.positive_family_metrics(test_rows,.8)['test']
    assert m['independent_source_count']==2 and m['source_macro_top5_rate']==.75
    summary={'checks':'passed','original_tracks':1000,'normal_tracks':300,'premusic_tracks':200,
             'removed_duplicates':17,'replacement_tracks':17,'extended_generated_and_validated':180,
             'total_synthetic_positives':340,'source_track_ids':len({q['expected_track_id'] for q in positive}),
             'loader_source_exclusion':'passed','family_macro_metric_check':'passed','clap_full_reevaluation':'not_run'}
    (ART/'dataset_refresh_validation.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
