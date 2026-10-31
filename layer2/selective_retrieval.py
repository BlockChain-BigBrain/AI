"""Conservative evidence penalty for candidates outside the first five.

This is a bounded engineering score, not a calibrated probability or a
multiple-testing correction. Original Top-5 candidates keep their score.
"""
RULE='expanded-square-v1'


def apply(evidence, retrieval_rank):
    raw=float(evidence['tonalScore'])
    return {**evidence,'unpenalizedTonalScore':raw,
            'tonalScore':raw if retrieval_rank<=5 else raw*raw,
            'retrievalRank':retrieval_rank}
