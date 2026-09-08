"""Universal data contracts for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Frozen on 29 Aug per the project specifications.
"""
from __future__ import annotations

from .stage_result import StageStatus, Hypothesis, StageResult
from .report import AnalysisReport

__all__ = [
    "StageStatus",
    "Hypothesis",
    "StageResult",
    "AnalysisReport",
]
