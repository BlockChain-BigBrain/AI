"""Read-only adapter around the evaluated Layer 1 and CLAP pipeline."""
from pathlib import Path
import hashlib
import json
import sys
import os
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'layer1'), str(ROOT / 'layer2')]
import upload_guard_api as gate
import evaluate_retrieval_baseline as baseline
import evaluate_top3_aggregation as aggregation
import tonal_alignment as tonal
import selective_retrieval as selective


class Engine:
    """Load weights once; the API invokes this instance from one worker only."""
    def __init__(self, scope=None):
        scope = scope or os.environ.get('TRACK_AI_SCOPE', 'all')
        if scope not in ('all', 'ai_labeled'):
            raise RuntimeError('Unknown reference scope')
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
        if report.get('corpus', {}).get('reference_tracks') != len(self.groups):
            raise RuntimeError('Evaluation catalog size does not match the running catalog; complete full evaluation first.')
        full_version = hashlib.sha256(self.vectors.tobytes() + self.ids.tobytes() + self.offsets.tobytes()).hexdigest()
        if report.get('corpus', {}).get('embedding_sha256') != full_version:
            raise RuntimeError('Calibration is not bound to this reference catalog; complete a matching evaluation first.')
        if scope == 'ai_labeled':
            recalibration_path = baseline.ARTIFACT_DIR / 'ai_labeled_recalibration.json'
            recalibration = json.loads(recalibration_path.read_text('utf-8'))
            allowlist_path = baseline.ARTIFACT_DIR / 'pixabay_provenance/ai_label_allowlist.json'
            if recalibration['provenance_sha256'] != hashlib.sha256(allowlist_path.read_bytes()).hexdigest():
                raise RuntimeError('AI provenance changed; recalibration required.')
            policy = recalibration['profiles']['ai_labeled_catalog']
            improved_path = baseline.ARTIFACT_DIR / 'ai_improvement_policy.json'
            if improved_path.exists():
                improved = json.loads(improved_path.read_text('utf-8'))
                bindings = {'original_policy_sha256': recalibration_path,
                            'comparison_sha256': baseline.ARTIFACT_DIR / 'ai_improvement_comparison.json',
                            'stress_sha256': baseline.ARTIFACT_DIR / 'ai_improvement_stress_summary.json',
                            'selective_evaluation_sha256': baseline.ARTIFACT_DIR / 'ai_selective_retrieval_evaluation.json',
                            'replication_sha256': baseline.ARTIFACT_DIR / 'ai_selective_replication_summary.json',
                            'scoring_implementation_sha256': ROOT / 'layer2/selective_retrieval.py',
                            'near_duplicate_audit_sha256': baseline.ARTIFACT_DIR / 'ai_near_duplicate_audit.json',
                            'manifest_sha256': ROOT / 'layer2/test_data/ai_labeled_positive/manifest.json'}
                if any(improved[key] != hashlib.sha256(path.read_bytes()).hexdigest() for key, path in bindings.items()):
                    raise RuntimeError('Improvement evidence changed; recalibration required.')
                if improved['provenance_sha256'] != recalibration['provenance_sha256'] or improved['method'] != 'selective_top20' or improved['candidate_score_rule'] != selective.RULE:
                    raise RuntimeError('Unsupported or unbound AI improvement policy.')
                if improved['retrieval_top_k'] != 20:
                    raise RuntimeError('Candidate budget does not match the evaluated method.')
                policy = improved
            precision_policy_path = baseline.ARTIFACT_DIR / 'ai_precision_policy.json'
            if precision_policy_path.exists():
                precision_policy = json.loads(precision_policy_path.read_text('utf-8'))
                precision_bindings = {'primary_policy_sha256': improved_path,
                    'secondary_evaluation_sha256': baseline.ARTIFACT_DIR / 'secondary_precision_evaluation.json',
                    'five_family_evaluation_sha256': baseline.ARTIFACT_DIR / 'five_family_ai_evaluation.json',
                    'secondary_implementation_sha256': ROOT / 'layer2/secondary_precision.py',
                    'precision_features_implementation_sha256': ROOT / 'layer2/precision_chroma.py',
                    'fragment_implementation_sha256': ROOT / 'layer2/fragment_confirmation.py'}
                if any(precision_policy[k] != hashlib.sha256(p.read_bytes()).hexdigest() for k,p in precision_bindings.items()):
                    raise RuntimeError('Secondary precision evidence changed; recalibration required.')
                import precision_chroma
                import secondary_precision
                if precision_policy['secondary_precision_rule'] != secondary_precision.VERSION or precision_policy['librosa_version'] != precision_chroma.librosa.__version__:
                    raise RuntimeError('Secondary precision implementation/version mismatch.')
                if not 0 < precision_policy['secondary_warn_threshold'] <= .8:
                    raise RuntimeError('Invalid supplemental evidence cutoff.')
                policy = precision_policy
            if policy['full_catalog_version'] != full_version:
                raise RuntimeError('AI subset does not match this full catalog.')
            allowed = set(policy['allowed_reference_ids'])
            mask = np.isin(self.ids, list(allowed))
            self.vectors, self.ids, self.offsets = self.vectors[mask], self.ids[mask], self.offsets[mask]
            self.mean = self.vectors.mean(axis=0)
            self.centered = aggregation.unit_rows(self.vectors - self.mean)
            self.groups = [(str(t), np.flatnonzero(self.ids == t)) for t in np.unique(self.ids)]
            if len(self.groups) != policy['reference_tracks'] or {t for t, _ in self.groups} != allowed:
                raise RuntimeError('AI-labelled reference subset is incomplete.')
            self.records = {k: v for k, v in self.records.items() if Path(k).stem in allowed}
            if not self.records:
                raise RuntimeError('AI-labelled fingerprint subset is empty.')
        else:
            policy = json.loads((baseline.ARTIFACT_DIR / 'tonal_confirmation_evaluation.json').read_text('utf-8'))
        self.thresholds = {'warn': policy['warn_threshold'], 'hold': policy['hold_threshold']}
        if not policy.get('enabled') or policy.get('score_version') != tonal.VERSION or any(v is None for v in self.thresholds.values()) or self.thresholds['warn'] > self.thresholds['hold']:
            raise RuntimeError('No valid ordered WARN/HOLD policy is available.')
        self.policy_version = 'layer2-risk-' + hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:12]
        digest = hashlib.sha256(self.vectors.tobytes() + self.ids.tobytes() + self.offsets.tobytes())
        self.corpus_version = digest.hexdigest()
        if policy.get('catalog_version', policy.get('corpus_version')) != self.corpus_version:
            raise RuntimeError('Tonal calibration does not match the running catalog.')
        self.reference_paths = {baseline.track_id_from_original(p): p for p in baseline.audio_files(ROOT / 'original_music')}
        self.tonal_features = {}
        self.retrieval_top_k = policy.get('retrieval_top_k', 5)
        self.candidate_score_rule = policy.get('candidate_score_rule')
        self.score_version = f'clap-top{self.retrieval_top_k}+' + tonal.VERSION
        if self.candidate_score_rule:
            self.score_version += '+' + self.candidate_score_rule
        self.secondary_precision_rule = policy.get('secondary_precision_rule')
        self.secondary_warn_threshold = policy.get('secondary_warn_threshold')
        self.precision_reference_features = {}
        if self.secondary_precision_rule:
            self.score_version += '+' + self.secondary_precision_rule
        self.evaluation_scope = scope

    def verify(self, path, audio_hash):
        """Return evidence and a provisional policy decision; never register uploads."""
        fingerprint = gate.extract_raw_fingerprint(path)
        if fingerprint['duration'] > 1800:
            raise ValueError('Audio longer than 30 minutes is not supported')
        duplicate = gate.find_exact_duplicate(fingerprint['fingerprint_raw'], self.records)
        common = dict(audioHash=audio_hash, modelVersion=baseline.BASE_MODEL,
                      scoreVersion=self.score_version, corpusVersion=self.corpus_version,
                      thresholds=self.thresholds, provisional=True,
                      decisionPolicyVersion=self.policy_version,
                      evaluationScope=self.evaluation_scope, referenceTracks=len(self.groups), pureAiCreationVerified=False,
                      durationSeconds=fingerprint['duration'])
        if duplicate:
            return dict(common, decision='BLOCK', duplicate={'detected': True,
                        'matchedTrackId': duplicate['track_id']}, similarityScore=None,
                        decisionReason='EXACT_FINGERPRINT_MATCH',
                        disposition='AUTO_BLOCK', reviewRequired=False,
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
        # Confirm candidates using pitch progression, not shared timbre alone.
        # Upload features never persist in the path-based reference cache.
        q_tonal, _, q_step = tonal.features(path, baseline.FFMPEG_EXE, None)
        confirmed = []
        for retrieval_rank, candidate in enumerate(candidates[:self.retrieval_top_k], 1):
            track_id = candidate['trackId']
            if track_id not in self.tonal_features:
                self.tonal_features[track_id] = tonal.features(self.reference_paths[track_id], baseline.FFMPEG_EXE,
                                                             baseline.ARTIFACT_DIR / 'tonal_feature_cache')
            ref_tonal, _, ref_step = self.tonal_features[track_id]
            evidence = tonal.compare(q_tonal, ref_tonal, q_step, ref_step)
            if self.candidate_score_rule:
                evidence = selective.apply(evidence, retrieval_rank)
            confirmed.append(dict(trackId=track_id, score=evidence['tonalScore'], retrievalScore=candidate['score'],
                                  matchedSegments=[dict(queryStartSec=evidence['queryStartSec'], queryEndSec=min(fingerprint['duration'], evidence['queryEndSec']),
                                                       refStartSec=evidence['refStartSec'], refEndSec=evidence['refEndSec'], score=evidence['tonalScore'])]))
        if self.secondary_precision_rule and max(c['score'] for c in confirmed) < .60:
            import precision_chroma
            import secondary_precision
            query_precision, _, precision_step = precision_chroma.features(path, baseline.FFMPEG_EXE, None)
            for retrieved in candidates[:3]:
                track_id = retrieved['trackId']
                if track_id not in self.precision_reference_features:
                    self.precision_reference_features[track_id] = precision_chroma.features(
                        self.reference_paths[track_id], baseline.FFMPEG_EXE, baseline.ARTIFACT_DIR / 'cqt_feature_cache')
                ref_precision, ref_duration, ref_precision_step = self.precision_reference_features[track_id]
                extra = secondary_precision.compare(query_precision, ref_precision, precision_step, ref_precision_step,
                    retrieved['score'], self.thresholds['warn'], self.secondary_warn_threshold)
                candidate = next(c for c in confirmed if c['trackId'] == track_id)
                if extra['score'] > candidate['score']:
                    candidate['score'] = extra['score']
                    candidate['matchedSegments'] = [dict(queryStartSec=s['queryStartSec'],
                        queryEndSec=min(fingerprint['duration'],s['queryEndSec']),refStartSec=s['refStartSec'],
                        refEndSec=min(ref_duration,s['refEndSec']),score=s['tonalScore']) for s in extra['segments']]
        candidates = sorted(confirmed, key=lambda c: c['score'], reverse=True)
        score = candidates[0]['score']
        decision = 'HOLD' if score >= self.thresholds['hold'] else 'WARN' if score >= self.thresholds['warn'] else 'PASS'
        if decision == 'HOLD':
            reason, disposition, review = 'HIGH_TONAL_SEQUENCE_REVIEW', 'HUMAN_REVIEW', True
        elif decision == 'WARN':
            reason, disposition, review = 'TONAL_SEQUENCE_WARNING', 'HUMAN_REVIEW', True
        else:
            reason, disposition, review = 'BELOW_TONAL_SEQUENCE_THRESHOLD', 'ALLOW', False
        return dict(common, decision=decision, duplicate={'detected': False, 'matchedTrackId': None},
                    decisionReason=reason, disposition=disposition, reviewRequired=review,
                    similarityScore=score, similarTracks=candidates[:3], queryWindowCount=len(offsets))
