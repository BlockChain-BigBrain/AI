"""Generate two additional synthetic robustness families, 30 works x 3 levels each."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve
from make_synthetic_layered_positives import ffmpeg_path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'layer2/test_data/extended_positive'
SR = 22050
SEED = 20261022

def main():
    rows = list(csv.DictReader((ROOT / 'layer2/test_data/plagiarism_positive/manifest.csv').open(encoding='utf-8-sig')))
    sources = {r['source_track_id']: r for r in reversed(rows)}
    assert len(sources) == 30
    OUT.mkdir(exist_ok=True)
    manifest = []
    ffmpeg = ffmpeg_path()
    for i, (sid, row) in enumerate(sorted(sources.items())):
        source = Path(row['source_path'])
        offset = float(row['start_seconds'])
        # Loop only if the chosen excerpt ends before 60s; record this explicitly.
        decoded = subprocess.run([ffmpeg,'-v','error','-nostdin','-stream_loop','-1','-ss',str(offset),'-i',str(source),'-t','65','-ac','1','-ar',str(SR),'-f','f32le','pipe:1'], capture_output=True, check=True)
        x = np.frombuffer(decoded.stdout, dtype='<f4').copy()[:60*SR]
        assert len(x) == 60 * SR and np.isfinite(x).all()
        for level in range(1, 4):
            seed = SEED + i * 10 + level
            rng = np.random.default_rng(seed)
            for kind in ('room_rerecord_simulation', 'local_tempo_warp'):
                params = {'level': level, 'source_offset_seconds': offset, 'source_window_seconds': 60, 'loop_if_needed': True}
                if kind == 'room_rerecord_simulation':
                    rt60 = (0.25, 0.55, 0.9)[level-1]
                    snr = (35, 25, 18)[level-1]
                    t = np.arange(int(SR * rt60)) / SR
                    ir = rng.normal(size=len(t)) * np.exp(-6.907755 * t / rt60)
                    ir *= 0.35 / max(np.linalg.norm(ir), 1e-9)
                    ir[0] += 1
                    y = fftconvolve(x, ir)[:len(x)]
                    noise = rng.normal(size=len(y))
                    noise *= np.sqrt(np.mean(y*y)) / (10**(snr/20) * np.sqrt(np.mean(noise*noise)))
                    y += noise
                    params.update(rt60_seconds=rt60, noise_snr_db=snr, rir_model='synthetic exponentially decaying noise plus direct path')
                else:
                    delta = (0.06, 0.12, 0.20)[level-1]
                    rates = [1-delta, 1+delta, 1.0]
                    parts = []
                    for k, rate in enumerate(rates):
                        chunk = x[k*20*SR:(k+1)*20*SR]
                        p = subprocess.run([ffmpeg,'-v','error','-nostdin','-f','f32le','-ar',str(SR),'-ac','1','-i','pipe:0','-af',f'atempo={rate},afade=t=in:d=0.02,areverse,afade=t=in:d=0.02,areverse','-f','f32le','pipe:1'], input=chunk.astype('<f4').tobytes(), capture_output=True, check=True)
                        parts.append(np.frombuffer(p.stdout, dtype='<f4'))
                    y = np.concatenate(parts)
                    params.update(segment_seconds=20, tempo_rates=rates, pitch_preserved=True, boundary_fade_seconds=0.02)
                peak = float(np.max(np.abs(y)))
                gain = min(1., 0.97 / max(peak, 1e-9))
                y = (y * gain).astype(np.float32)
                target = OUT / f'{sid}__{kind}__L{level}.wav'
                sf.write(target, y, SR, subtype='PCM_16')
                check, sr = sf.read(target)
                assert sr == SR and len(check) == len(y) and np.isfinite(check).all()
                assert 0 < np.sqrt(np.mean(check**2)) and np.max(np.abs(check)) < 0.98
                params['peak_normalization_gain'] = gain
                manifest.append(dict(query_path=str(target), source_path=str(source), source_track_id=sid, case_type=kind, duration_seconds=f'{len(y)/SR:.3f}', seed=seed, parameters_json=json.dumps(params), label='positive_synthetic_robustness', sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
        print(f'[{i+1}/30] generated and validated six files: {sid}', flush=True)
    with (OUT/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w = csv.DictWriter(f,fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    print(f'Generated and validated {len(manifest)} synthetic positives', flush=True)

if __name__ == '__main__':
    main()
