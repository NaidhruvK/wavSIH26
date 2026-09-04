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

THE GUARANTEED KEYS (4 Sep, at Nehal's request)
-----------------------------------------------
`estimated_output_ber` and `estimated_output_ber_valid` are now PRIMARY: every
`S3Result` carries them, on every path, including the ones that emitted no bits
at all. They were previously present only on the success path, so
`values["estimated_output_ber"]` raised `KeyError` on precisely the inputs a
defensive short-circuit exists to catch - which is the worst place for a lookup
to raise, because the caller is by then in its own failure handling.

`REQUIRED_VALUES` is the contract. `__post_init__` fills anything absent, so a
plug-in cannot forget one, and `test_estimated_ber_is_a_primary_key` asserts it
across every registered modulation and every adversarial input.

The default when nothing was emitted is `estimated_output_ber = 1.0`, flagged
INVALID. There is no output to be right about, and 1.0 is the reading that
cannot make a consumer optimistic about a stream that does not exist. It
matches `softmap.llr_health`, which already returns 1.0 for an empty array.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["S3Result", "Hypothesis", "REQUIRED_VALUES", "STATUSES"]

STATUSES = ("ok", "low_confidence", "failed")
"""The status values S3 emits today.

The Command Center's `StageResult` also names `out_of_envelope`, and S3 now has
the information to raise it - `values["envelope"]` says whether the input was
inside what this stage claims to support. The status enum is deliberately NOT
widened today: Naidhruv has not landed `contracts/`, so there is no consumer to
serve, and adding a fourth value that every existing `status == "ok"` branch
has never seen is a poor trade on an integration day. The distinction is
carried in `values["envelope"]` instead, and the status follows the moment the
real Pydantic model arrives.
"""

REQUIRED_VALUES: dict[str, Any] = {
    "modulation": "",
    "estimated_output_ber": 1.0,
    "estimated_output_ber_valid": False,
    "envelope": "inside",
}
"""Keys every S3Result carries whatever happened. See the module docstring.

`envelope` is "inside" or "outside": "outside" means the input is beyond what
S3 claims to support (an impossible samples-per-symbol, a record too short for
the loops to settle) rather than something having gone wrong inside the stage.
Naidhruv - this is the field the `/envelope` endpoint wants; it is set on the
same code paths that produce the `reason` string beside it.
"""


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

    def __post_init__(self) -> None:
        for key, default in REQUIRED_VALUES.items():
            self.values.setdefault(key, default)

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
