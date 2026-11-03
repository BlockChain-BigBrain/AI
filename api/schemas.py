"""Versioned public response contract for the Track-AI verification API."""
from typing import Literal
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal['ready']
    referenceTracks: int
    referenceWindows: int
    modelVersion: str
    scoreVersion: str


class JobAccepted(BaseModel):
    jobId: str
    statusUrl: str


class DuplicateEvidence(BaseModel):
    detected: bool
    matchedTrackId: str | None


class MatchedSegment(BaseModel):
    queryStartSec: float
    queryEndSec: float
    refStartSec: float
    refEndSec: float
    score: float


class FeatureSegment(BaseModel):
    queryStartSec: float
    refStartSec: float
    pitchScore: float
    rhythmScore: float
    chromaScore: float
    pitchShift: int


class FeatureEvidence(BaseModel):
    version: str
    segments: list[FeatureSegment]
    pitchScore: float
    rhythmScore: float
    chromaScore: float
    matchedSegmentCount: int
    orderedMatchFraction: float
    orderedMatches: bool
    pitchShiftConsistency: float
    tempoRatioMedian: float
    tempoRatioConsistency: float
    longestOrderedChainSeconds: float
    queryCoverage: float
    referenceCoverage: float


class SimilarTrack(BaseModel):
    trackId: str
    score: float
    fusionScore: float
    verifierScore: float
    matchedSegments: list[MatchedSegment]
    featureEvidence: FeatureEvidence


class VerificationResult(BaseModel):
    audioHash: str
    modelVersion: str
    scoreVersion: str
    decisionPolicyVersion: str
    corpusVersion: str
    thresholds: dict[Literal['warn', 'hold'], float]
    provisional: bool
    durationSeconds: float
    decision: Literal['PASS', 'WARN', 'HOLD', 'BLOCK']
    duplicate: DuplicateEvidence
    similarityScore: float | None
    queryVerifierScore: float | None
    similarTracks: list[SimilarTrack]
    queryWindowCount: int
    processingSeconds: float


class VerificationJob(BaseModel):
    jobId: str
    trackId: str
    state: Literal['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED']
    result: VerificationResult | None
    error: str | None
