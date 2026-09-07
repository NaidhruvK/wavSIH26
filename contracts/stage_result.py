"""Universal stage result contract for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Frozen on 29 Aug per the project specifications.

Every pipeline stage returns data conformant to this shape. Downstream
consumers (orchestrator, service, UI, test suite) consume this uniform interface
and never need stage-specific unpacking.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class StageStatus(str, Enum):
    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"
    FAILED = "failed"
    OUT_OF_ENVELOPE = "out_of_envelope"


try:
    from pydantic import BaseModel, ConfigDict, Field

    class Hypothesis(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        value: Any
        score: float
        evidence: str = ""

    class StageResult(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        stage: str
        status: StageStatus
        confidence: float = Field(..., ge=0.0, le=1.0)
        values: dict[str, Any] = Field(default_factory=dict)
        hypotheses: list[Hypothesis] = Field(default_factory=list)
        artifacts: dict[str, str] = Field(default_factory=dict)
        elapsed_ms: float = 0.0
        reason: Optional[str] = None

except ImportError:
    # Graceful fallback shim when pydantic is not yet installed in host environment.
    # Enables manual import verification and testing without external dependencies.
    class _FieldInfo:
        def __init__(self, default=..., *, default_factory=None, ge=None, le=None, **kwargs):
            self.default = default
            self.default_factory = default_factory
            self.ge = ge
            self.le = le

    def Field(default=..., *, default_factory=None, ge=None, le=None, **kwargs):
        return _FieldInfo(default=default, default_factory=default_factory, ge=ge, le=le)

    class BaseModel:
        def __init__(self, **kwargs):
            # Collect all annotated fields from class hierarchy
            annotations: dict[str, Any] = {}
            for cls in reversed(self.__class__.__mro__):
                if hasattr(cls, "__annotations__"):
                    annotations.update(cls.__annotations__)

            for k in annotations:
                if k in kwargs:
                    setattr(self, k, kwargs[k])
                elif hasattr(self.__class__, k):
                    val = getattr(self.__class__, k)
                    if isinstance(val, _FieldInfo):
                        if val.default_factory is not None:
                            setattr(self, k, val.default_factory())
                        elif val.default is not ...:
                            setattr(self, k, val.default)
                        else:
                            setattr(self, k, None)
                    else:
                        setattr(self, k, val)
                else:
                    setattr(self, k, None)

            for k, v in kwargs.items():
                setattr(self, k, v)

            if hasattr(self, "confidence") and isinstance(self.confidence, (int, float)):
                if not (0.0 <= self.confidence <= 1.0):
                    raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")

        def model_dump(self, *args, **kwargs) -> dict[str, Any]:
            annotations: dict[str, Any] = {}
            for cls in reversed(self.__class__.__mro__):
                if hasattr(cls, "__annotations__"):
                    annotations.update(cls.__annotations__)
            keys = list(annotations.keys()) if annotations else list(self.__dict__.keys())

            out = {}
            for k in keys:
                if k.startswith("_"):
                    continue
                v = getattr(self, k, None)
                if isinstance(v, BaseModel):
                    out[k] = v.model_dump()
                elif isinstance(v, list):
                    out[k] = [x.model_dump() if isinstance(x, BaseModel) else x for x in v]
                elif isinstance(v, Enum):
                    out[k] = v.value
                else:
                    out[k] = v
            return out

        dict = model_dump

    class Hypothesis(BaseModel):
        value: Any
        score: float
        evidence: str = ""

    class StageResult(BaseModel):
        stage: str
        status: StageStatus
        confidence: float = Field(..., ge=0.0, le=1.0)
        values: dict[str, Any] = Field(default_factory=dict)
        hypotheses: list[Hypothesis] = Field(default_factory=list)
        artifacts: dict[str, str] = Field(default_factory=dict)
        elapsed_ms: float = 0.0
        reason: Optional[str] = None
