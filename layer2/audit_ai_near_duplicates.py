"""Audit suspicious normal labels with independent waveform/fingerprint evidence.

Quarantines evaluation labels only, never deletes audio or changes BLOCK rules.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import numpy as np
from scipy.signal import correlate
import evaluate_retrieval_baseline as base

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'layer2/artifacts'
sys.path.insert(0,str(ROOT/'layer1'))
import upload_guard_api as gate


def main():
    ffmpeg=base.find_ffmpeg()
    pairs=[('alex-morgan-dramatic-548632.mp3','alex-morgan-cinematic-591327.mp3'),
           ('oceanframemusic-music-no-copyright-motivation-463767.mp3','the_mountain-dramatic-610133 (1).mp3')]
    results=[]
    def decode(path,start):
        p=subprocess.run([ffmpeg,'-v','error','-nostdin','-ss',str(start),'-i',str(path),'-t','20','-ac','1','-ar','8000','-f','f32le','pipe:1'],check=True,capture_output=True)
        x=np.frombuffer(p.stdout,dtype='<f4').astype(np.float64);return x-x.mean()
    for normal,ref in pairs:
        a,b=ROOT/'music'/normal,ROOT/'original_music'/ref
        af,bf=[np.asarray(gate.extract_raw_fingerprint(p)['fingerprint_raw'],dtype=np.uint32) for p in (a,b)]
        errors=[]
        for offset in range(-40,41):
            x,y=af[max(0,offset):],bf[max(0,-offset):];n=min(len(x),len(y));x,y=x[:n],y[:n]
            if n>=100:errors.append((float(np.unpackbits(np.bitwise_xor(x,y).view(np.uint8)).mean()),offset))
        bit_error,offset=min(errors)
        correlations=[]
        for start in (5,40,80):
            x,y=decode(a,start),decode(b,start);n=min(len(x),len(y));x,y=x[:n],y[:n]
            c=correlate(x,y,mode='full',method='fft');center=len(y)-1
            correlations.append(float(np.max(np.abs(c[max(0,center-8000):center+8001]))/max(np.linalg.norm(x)*np.linalg.norm(y),1e-12)))
        confirmed=bit_error<.10 and min(correlations)>.98
        results.append({'normal':str(a),'reference':str(b),'normal_sha256':hashlib.sha256(a.read_bytes()).hexdigest(),
            'reference_sha256':hashlib.sha256(b.read_bytes()).hexdigest(),'fingerprint_mean_bit_error':bit_error,
            'fingerprint_offset_frames':offset,'waveform_correlations':correlations,
            'quarantine_normal_label':confirmed,'status':'near_identical_recording_evidence' if confirmed else 'not_confirmed'})
    artifact={'date':'2026-10-23','selection':'Known highest-tonal-score normal and another warned normal as negative control; not exhaustive collection deduplication.',
        'rule':{'fingerprint_mean_bit_error_max_exclusive':.10,'waveform_correlation_min_exclusive':.98,'excerpt_seconds':20,
                'excerpt_starts_seconds':[5,40,80],'waveform_lag_search_seconds':1,'fingerprint_lag_search_frames':40},
        'effect':'Evaluation normal-label quarantine only. Audio preserved. No automatic BLOCK change; no copyright conclusion.',
        'pairs':results,'excluded_normal_filenames':[Path(r['normal']).name for r in results if r['quarantine_normal_label']]}
    (ART/'ai_near_duplicate_audit.json').write_text(json.dumps(artifact,indent=2),encoding='utf-8')
    print(json.dumps(artifact,indent=2))


if __name__=='__main__':main()
