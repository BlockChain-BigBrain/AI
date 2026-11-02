"""Read-only adapter around the evaluated Layer 1 and CLAP pipeline."""
from pathlib import Path
import hashlib
import json
import os
import sys
import joblib
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'layer1'), str(ROOT / 'layer2')]
import upload_guard_api as gate
import evaluate_retrieval_baseline as baseline
import evaluate_top3_aggregation as aggregation
import independent_features


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
        thread_setting = int(os.getenv('TRACK_AI_TORCH_THREADS', '8'))
        torch.set_num_threads(min(max(1, thread_setting), max(1, os.cpu_count() or 4)))
        self.model = aggregation.ClapAudioModelWithProjection.from_pretrained(
            baseline.BASE_MODEL, local_files_only=True).to(self.device).eval()
        self.processor = aggregation.ClapProcessor.from_pretrained(
            baseline.BASE_MODEL, local_files_only=True)
        train_ids = {r['track_id'] for r in aggregation.read_csv(
            baseline.ARTIFACT_DIR / 'segment_manifest.csv')}
        _, held_out = aggregation.build_queries(train_ids)
        self.reference_paths = {
            baseline.track_id_from_original(path): path
            for path in baseline.audio_files(baseline.ORIGINAL_DIR)
        }
        self.reference_paths.update({key: Path(value['path']) for key, value in held_out.items()})
        catalog_cache = baseline.ARTIFACT_DIR / 'current_reference_catalog.npz'
        expected_ids = set(self.reference_paths)
        cache_is_fresh = (catalog_cache.is_file() and
                          all(path.stat().st_mtime_ns <= catalog_cache.stat().st_mtime_ns
                              for path in self.reference_paths.values() if path.is_file()))
        if cache_is_fresh:
            with np.load(catalog_cache, allow_pickle=False) as cached:
                cached_ids = set(cached['ids'].astype(str).tolist())
                if cached_ids == expected_ids:
                    self.vectors = cached['vectors'].astype(np.float32)
                    self.ids = cached['ids'].astype(str)
                    self.offsets = cached['offsets'].astype(np.float32)
                else:
                    cache_is_fresh = False
        if not cache_is_fresh:
            self.vectors, self.ids, self.offsets = aggregation.load_reference_catalog(
                self.model, self.processor, self.device, held_out)
        self.mean = self.vectors.mean(axis=0)
        self.centered = aggregation.unit_rows(self.vectors - self.mean)
        self.groups = [(str(t), np.flatnonzero(self.ids == t)) for t in np.unique(self.ids)]
        # Bind thresholds to the actual score formula, rather than raw CLAP cosine.
        policy_path = ROOT / 'api' / 'runtime' / 'ai_calibrated_policy.json'
        verifier_path = ROOT / 'api' / 'runtime' / 'pairwise_verifier_evaluation.json'
        self.verifier = json.loads(verifier_path.read_text('utf-8')) if verifier_path.is_file() else None
        challenger_path = ROOT / 'api' / 'runtime' / 'pairwise_with_premusic.json'
        if self.verifier and challenger_path.is_file():
            challenger = json.loads(challenger_path.read_text('utf-8'))
            model = challenger.get('model', {})
            if model.get('mean') and model.get('weights'):
                # Use mined-premusic challenger for WARN calibration, but retain
                # the locked precision/HOLD threshold for conservative blocking.
                self.verifier.update({
                    'standardizationMean': model['mean'],
                    'standardizationStd': model['std'],
                    'weights': model['weights'],
                    'bias': model['bias'],
                    'recallOperatingPoint': {'threshold': challenger['thresholds']['warn']},
                    'challengerSource': 'pairwise_with_premusic.json',
                })
        if policy_path.is_file():
            policy = json.loads(policy_path.read_text('utf-8'))
            self.thresholds = {'warn': policy['warn'], 'hold': policy['hold']}
            self.score_version = 'seg_top3_centered_fusion-v2'
        else:
            report = json.loads((baseline.ARTIFACT_DIR / 'top3_aggregation_evaluation.json').read_text('utf-8'))
            policy = report['models']['seg_top3_centered']['thresholds_from_tune_split']
            self.thresholds = {'warn': policy['warn_threshold'], 'hold': policy['hold_threshold']}
            self.score_version = 'seg_top3_centered-v1'
        if self.verifier:
            self.thresholds = {
                'warn': self.verifier['recallOperatingPoint']['threshold'],
                'hold': self.verifier['precisionOperatingPoint']['threshold'],
            }
            self.score_version = ('pairwise_temporal-premusic-hardneg-v4'
                                  if self.verifier.get('challengerSource')
                                  else 'pairwise_temporal-v3')
        self.query_verifier = None
        query_model_path = ROOT / 'api' / 'runtime' / 'query_level_verifier.joblib'
        query_report_path = ROOT / 'api' / 'runtime' / 'query_level_verifier_evaluation.json'
        if query_model_path.is_file() and query_report_path.is_file():
            self.query_verifier = joblib.load(query_model_path)
            if hasattr(self.query_verifier, 'n_jobs'):
                self.query_verifier.n_jobs = 1
            query_report = json.loads(query_report_path.read_text('utf-8'))
            selected = query_report['selectedModel']
            selected_report = query_report['models'][selected]
            self.thresholds['warn'] = selected_report.get('balancedWarnThreshold', selected_report['warnThreshold'])
            self.score_version = 'hybrid_query_top3_pairwise_hold-v5'
        self.decision_policy_version = 'track-ai-balanced-policy-v5-20261102'
        digest = hashlib.sha256(self.vectors.tobytes() + self.ids.tobytes() + self.offsets.tobytes())
        self.corpus_version = digest.hexdigest()

    def verify(self, path, audio_hash):
        """Return evidence and a provisional policy decision; never register uploads."""
        fingerprint = gate.extract_raw_fingerprint(path)
        if fingerprint['duration'] > 1800:
            raise ValueError('Audio longer than 30 minutes is not supported')
        duplicate = gate.find_exact_duplicate(fingerprint['fingerprint_raw'], self.records)
        common = dict(audioHash=audio_hash, modelVersion=baseline.BASE_MODEL,
                      scoreVersion=self.score_version, corpusVersion=self.corpus_version,
                      decisionPolicyVersion=self.decision_policy_version,
                      thresholds=self.thresholds, provisional=True,
                      durationSeconds=fingerprint['duration'])
        if duplicate:
            return dict(common, decision='BLOCK', duplicate={'detected': True,
                        'matchedTrackId': duplicate['track_id']}, similarityScore=None,
                        queryVerifierScore=None, similarTracks=[], queryWindowCount=0)
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
        query_features = independent_features.extract(Path(path), baseline.FFMPEG_EXE)
        for candidate in candidates[:3]:
            reference_path = self.reference_paths.get(candidate['trackId'])
            if reference_path is None or not reference_path.is_file():
                raise RuntimeError(f"Reference audio missing for {candidate['trackId']}")
            candidate['featureEvidence'] = independent_features.compare_file(
                query_features, reference_path, candidate['matchedSegments'], baseline.FFMPEG_EXE)
            evidence = candidate['featureEvidence']
            feature_score = (0.4 * evidence['pitchScore'] +
                             0.35 * evidence['chromaScore'] +
                             0.25 * evidence['rhythmScore'])
            candidate['fusionScore'] = 0.5 * candidate['score'] + 0.5 * feature_score
            if self.verifier:
                vector = independent_features.pairwise_vector(candidate)
                mean = np.asarray(self.verifier['standardizationMean'], dtype=np.float64)
                std = np.asarray(self.verifier['standardizationStd'], dtype=np.float64)
                weights = np.asarray(self.verifier['weights'], dtype=np.float64)
                linear = float(((vector - mean) / np.maximum(std, 1e-8)) @ weights + self.verifier['bias'])
                candidate['verifierScore'] = float(1.0 / (1.0 + np.exp(-np.clip(linear, -30, 30))))
        candidates.sort(key=lambda x: x.get('fusionScore', x['score']), reverse=True)
        if self.verifier:
            candidates.sort(key=lambda x: x.get('verifierScore', 0.0), reverse=True)
        score = candidates[0].get('verifierScore', candidates[0].get('fusionScore', candidates[0]['score']))
        query_score = score
        if self.query_verifier is not None:
            vectors = np.stack([independent_features.pairwise_vector(c) for c in candidates[:3]])
            z = np.stack(sorted(vectors, key=lambda v: v[0], reverse=True))
            gaps = np.concatenate([z[0] - z[1], z[1] - z[2]])
            query_vector = np.concatenate([z.ravel(), z.max(0), z.mean(0), z.std(0), gaps])
            query_score = float(self.query_verifier.predict_proba(query_vector.reshape(1, -1))[0, 1])
        decision = 'HOLD' if score >= self.thresholds['hold'] else 'WARN' if query_score >= self.thresholds['warn'] else 'PASS'
        return dict(common, decision=decision, duplicate={'detected': False, 'matchedTrackId': None},
                    similarityScore=score, queryVerifierScore=query_score,
                    similarTracks=candidates[:3], queryWindowCount=len(offsets))
