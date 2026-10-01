"""Read-only adapter around the evaluated Layer 1 and CLAP pipeline."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'layer1'), str(ROOT / 'layer2')]
import upload_guard_api as gate
import evaluate_retrieval_baseline as baseline
import evaluate_top3_aggregation as aggregation


class Engine:
    """Load weights once; the API invokes this instance from one worker only."""
    def __init__(self):
        self.records = gate._load_db()
        if not any(r.get('fingerprint_raw') for r in self.records.values()):
            raise RuntimeError('Build the Layer 1 fingerprint index first.')
        baseline.FFMPEG_EXE = baseline.find_ffmpeg()
        if not baseline.FFMPEG_EXE:
            raise RuntimeError('ffmpeg is missing')
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        torch.set_num_threads(4)
        self.model = aggregation.ClapAudioModelWithProjection.from_pretrained(
            baseline.BASE_MODEL, local_files_only=True).to(self.device).eval()
        self.processor = aggregation.ClapProcessor.from_pretrained(
            baseline.BASE_MODEL, local_files_only=True)
        train_ids = {r['track_id'] for r in aggregation.read_csv(
            baseline.ARTIFACT_DIR / 'segment_manifest.csv')}
        _, held_out = aggregation.build_queries(train_ids)
        self.vectors, self.ids, self.offsets = aggregation.load_reference_catalog(
            self.model, self.processor, self.device, held_out)
        self.mean = self.vectors.mean(axis=0)
        self.centered = aggregation.unit_rows(self.vectors - self.mean)
        self.groups = [(str(t), np.flatnonzero(self.ids == t)) for t in np.unique(self.ids)]
        # Bind thresholds to the actual score formula, rather than raw CLAP cosine.
        report = json.loads((baseline.ARTIFACT_DIR / 'top3_aggregation_evaluation.json').read_text('utf-8'))
        policy = report['models']['seg_top3_centered']['thresholds_from_tune_split']
        self.thresholds = {'warn': policy['warn_threshold'], 'hold': policy['hold_threshold']}
        digest = hashlib.sha256(self.vectors.tobytes() + self.ids.tobytes() + self.offsets.tobytes())
        self.corpus_version = digest.hexdigest()

    def verify(self, path, audio_hash):
        """Return evidence and a provisional policy decision; never register uploads."""
        fingerprint = gate.extract_raw_fingerprint(path)
        if fingerprint['duration'] > 1800:
            raise ValueError('Audio longer than 30 minutes is not supported')
        duplicate = gate.find_exact_duplicate(fingerprint['fingerprint_raw'], self.records)
        common = dict(audioHash=audio_hash, modelVersion=baseline.BASE_MODEL,
                      scoreVersion='seg_top3_centered-v1', corpusVersion=self.corpus_version,
                      thresholds=self.thresholds, provisional=True,
                      durationSeconds=fingerprint['duration'])
        if duplicate:
            return dict(common, decision='BLOCK', duplicate={'detected': True,
                        'matchedTrackId': duplicate['track_id']}, similarityScore=None,
                        similarTracks=[], queryWindowCount=0)
        # Extract all 10-second windows at 5-second stride (including final tail).
        # Temporary uploads bypass path-based evaluation caches to avoid accumulating files.
        windows, offsets = baseline.extract_windows(path, False, all_query_windows=True)
        vectors = []
        for start in range(0, len(windows), baseline.BATCH_SIZE):
            inputs = self.processor(audio=list(windows[start:start + baseline.BATCH_SIZE]),
                                    sampling_rate=48000, return_tensors='pt', padding=True).to(self.device)
            with torch.inference_mode():
                v = self.model(**inputs).audio_embeds
                vectors.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy())
        q = aggregation.unit_rows(np.concatenate(vectors) - self.mean)
        similarities = q @ self.centered.T
        candidates = []
        for track_id, indices in self.groups:
            indices = indices[np.argsort(self.offsets[indices], kind='stable')]
            local = similarities[:, indices]
            score, selected = aggregation.non_overlapping_top3(local, offsets)
            matches = []
            for qi in selected:
                ri = int(np.argmax(local[qi]))
                matches.append(dict(queryStartSec=offsets[qi], queryEndSec=offsets[qi] + 10,
                    refStartSec=float(self.offsets[indices[ri]]),
                    refEndSec=float(self.offsets[indices[ri]]) + 10, score=float(local[qi, ri])))
            candidates.append(dict(trackId=track_id, score=score, matchedSegments=matches))
        candidates.sort(key=lambda x: x['score'], reverse=True)
        score = candidates[0]['score']
        decision = 'HOLD' if score >= self.thresholds['hold'] else 'WARN' if score >= self.thresholds['warn'] else 'PASS'
        return dict(common, decision=decision, duplicate={'detected': False, 'matchedTrackId': None},
                    similarityScore=score, similarTracks=candidates[:3], queryWindowCount=len(offsets))
