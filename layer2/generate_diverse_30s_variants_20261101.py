"""Generate diverse 30-second positive variants from the frozen AI source catalog."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
import librosa, numpy as np, soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime-tests/diverse-30s-20261101'; MANIFEST=ROOT/'layer2/artifacts/diverse_30s_variants_20261101.csv'; SR=22050

def write_variant(path,y):
    y=np.clip(np.nan_to_num(np.asarray(y,dtype=np.float32)),-.98,.98)
    if len(y)<30*SR: y=np.pad(y,(0,30*SR-len(y)))
    sf.write(path,y[:30*SR],SR,subtype='PCM_16')

def sha(p):
    h=hashlib.sha256();
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def main():
    manifest=json.loads((ROOT/'layer2/test_data/ai_labeled_positive/manifest.json').read_text(encoding='utf-8'))
    ids=[]
    for row in manifest['rows']:
        if row['expected_track_id'] not in ids: ids.append(row['expected_track_id'])
    sources={p.stem:p for p in (ROOT/'original_music').glob('*.mp3')}
    selected=[(sid,sources[sid]) for sid in ids if sid in sources][:30]
    if len(selected)<30: raise RuntimeError(f'Expected 30 source files, found {len(selected)}')
    OUT.mkdir(parents=True,exist_ok=True); rows=[]
    for i,(sid,src) in enumerate(selected):
        audio,_=librosa.load(src,sr=SR,mono=True)
        offsets={'start':0,'middle':30,'end':60}
        for name,offset in offsets.items():
            target=OUT/f'{i:02d}__{sid}__cut_{name}.wav'
            write_variant(target,audio[int(offset*SR):int((offset+30)*SR)])
            rows.append({'source_track_id':sid,'variant':f'cut_{name}','query_path':str(target),'source_path':str(src),'split':'calibration' if i<21 else 'final_evaluation','sha256':sha(target)})
        base=audio[30*SR:60*SR]; d=int(.25*SR); delayed=np.pad(base[:-d],(d,0))[:len(base)] if len(base)>d else base
        variants={'pitch_plus2':librosa.effects.pitch_shift(base,sr=SR,n_steps=2),'tempo_slow':librosa.effects.time_stretch(base,rate=.90),'reverb_echo':base+.22*delayed,'shuffle_2x15':np.concatenate([base[15*SR:],base[:15*SR]])}
        for variant,y in variants.items():
            target=OUT/f'{i:02d}__{sid}__{variant}.wav'; write_variant(target,y); rows.append({'source_track_id':sid,'variant':variant,'query_path':str(target),'source_path':str(src),'split':'calibration' if i<21 else 'final_evaluation','sha256':sha(target)})
        if (i+1)%5==0: print(f'[{i+1}/30]',flush=True)
    MANIFEST.write_text('',encoding='utf-8');
    with MANIFEST.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(json.dumps({'sources':len(selected),'variants':len(rows),'calibration':sum(r['split']=='calibration' for r in rows),'final_evaluation':sum(r['split']=='final_evaluation' for r in rows)},ensure_ascii=False))
if __name__=='__main__':main()
