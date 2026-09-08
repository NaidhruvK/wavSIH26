"""Universal analysis report contract for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Frozen on 29 Aug per the project specifications.

Represents the complete end-to-end report for an analysis run.
"""
from __future__ import annotations

from typing import Any

from .stage_result import StageResult

try:
    from pydantic import BaseModel, ConfigDict, Field

    class AnalysisReport(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        run_id: str
        file_meta: dict[str, Any] = Field(default_factory=dict)
        envelope_verdict: str = "in_envelope"
        stages: list[StageResult] = Field(default_factory=list)
        final: dict[str, Any] = Field(default_factory=dict)

except ImportError:
    from .stage_result import BaseModel, Field

    class AnalysisReport(BaseModel):
        run_id: str
        file_meta: dict[str, Any] = Field(default_factory=dict)
        envelope_verdict: str = "in_envelope"
        stages: list[StageResult] = Field(default_factory=list)
        final: dict[str, Any] = Field(default_factory=dict)
