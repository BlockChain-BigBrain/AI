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


class SimilarTrack(BaseModel):
    trackId: str
    score: float
    matchedSegments: list[MatchedSegment]


class VerificationResult(BaseModel):
    audioHash: str
    modelVersion: str
    scoreVersion: str
    corpusVersion: str
    thresholds: dict[Literal['warn', 'hold'], float]
    provisional: bool
    durationSeconds: float
    decision: Literal['PASS', 'WARN', 'HOLD', 'BLOCK']
    decisionPolicyVersion: str
    decisionReason: str
    disposition: Literal['ALLOW', 'HUMAN_REVIEW', 'AUTO_BLOCK']
    reviewRequired: bool
    duplicate: DuplicateEvidence
    similarityScore: float | None
    similarTracks: list[SimilarTrack]
    queryWindowCount: int
    processingSeconds: float


class VerificationJob(BaseModel):
    jobId: str
    trackId: str
    state: Literal['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED']
    result: VerificationResult | None
    error: str | None
