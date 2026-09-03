"""What S3 returns, in the shape the stage contract will want.

`main` still has no `contracts/` - Naidhruv has not landed - so this mirrors
what Nehal did with `RecoveryResult` in `rank_collapse.py`: carry the fields the
Command Center names for `StageResult` (`status`, `confidence`, `values`,
`hypotheses`, `reason`, `elapsed_ms`) under this stream's own ownership, and
conform exactly once the real Pydantic model exists.

The registry protocol says `demodulate(iq, params) -> LLRs`, and S4 and S5
consume precisely that, so `demodulate()` returns the bare float array and
nothing else. `receive()` returns this object for the callers that want the
diagnostics too - the harness, the envelope reports, and eventually the UI. One
protocol satisfied literally, one richer path beside it, and no downstream code
forced to unpack something it did not ask for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["S3Result", "Hypothesis"]


@dataclass
class Hypothesis:
    value: Any
    score: float
    evidence: str = ""


@dataclass
class S3Result:
    status: str                                  # ok | low_confidence | failed
    confidence: float = 0.0
    values: dict[str, Any] = field(default_factory=dict)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    reason: str | None = None
    elapsed_ms: float = 0.0
    stage: str = "s3_receive"

    # payload
    llrs: np.ndarray | None = None               # primary rotation
    llrs_by_rotation: list[np.ndarray] = field(default_factory=list)
    symbols: np.ndarray | None = None

    def as_stage_result(self) -> dict[str, Any]:
        """The dict form, with the bulk arrays left out.

        Artifacts belong on disk and in the artifact store; a report that
        carries a 200 000-element float array inside it is one that cannot be
        logged, cached or sent over a socket.
        """
        return {
            "stage": self.stage,
            "status": self.status,
            "confidence": self.confidence,
            "values": {k: v for k, v in self.values.items()
                       if not isinstance(v, np.ndarray)},
            "hypotheses": [{"value": h.value, "score": h.score,
                            "evidence": h.evidence} for h in self.hypotheses],
            "reason": self.reason,
            "elapsed_ms": self.elapsed_ms,
        }
