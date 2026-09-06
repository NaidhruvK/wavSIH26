"""The MODULATIONS plug-in protocol, and how S2's estimates reach S3.

Every modulation plug-in implements the same three methods, so the orchestrator
iterates the registry and never names a scheme. Adding a modulation is one file
here and one register_modulation() line in __init__.

    classify_features(iq)      measured features this scheme contributes to S2
    demodulate(iq, params)     the receiver chain, returning a StageResult
    theoretical_cumulants()    closed-form values for this constellation

`demodulate` returns the LLR array itself - `registry/protocols.py` says
"-> LLRs" and S4 and S5 consume exactly that, so the protocol is satisfied
literally rather than approximately. `receive()` on each plug-in returns an
S3Result carrying the same array plus the diagnostics, for callers that want
them. See result.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

__all__ = ["S2Params", "ModulationPlugin", "unusable_reason"]


def unusable_reason(p: "S2Params") -> str | None:
    """Why these parameters cannot be used, or None if they can.

    4 Sep. `estimate_symbol_rate` returns `float("nan")` when it finds no
    in-band peak, so NaN is a value S2 really produces and really hands over -
    it is not a synthetic case. It used to travel all the way to
    `rrc_taps`, where `int(round(span * sps))` raised
    `ValueError: cannot convert float NaN to integer`. The catch-all in
    `receive()` turned that into a `failed` with the exception text as its
    reason, so nothing crashed and nobody could tell what had happened either.

    A comparison against NaN is False, which is why none of the ordinary bounds
    caught it: `nan <= 0`, `nan < 2.0` and `nan > x` are all False, so an
    unusable number walks through every guard written as an inequality. Non-
    finite values have to be excluded by name.
    """
    if not np.isfinite(p.fs) or p.fs <= 0:
        return f"sample rate {p.fs} is not a usable number"
    if not np.isfinite(p.symbol_rate) or p.symbol_rate <= 0:
        return (f"S2 reports a symbol rate of {p.symbol_rate}, which is not a "
                "usable number - it had no in-band peak to report")
    if not np.isfinite(p.cfo_hz):
        return f"S2 reports a carrier offset of {p.cfo_hz}"
    if p.beta is not None and (not np.isfinite(p.beta)
                               or not 0.0 < p.beta <= 1.0):
        return f"roll-off {p.beta} is outside (0, 1]"
    return None


@dataclass
class S2Params:
    """What S3 is allowed to know before it starts.

    Every field arrives from S2's blind estimation. None of it is read from the
    zoo's answer key - the 1 Sep gate is exactly that no path from the labels
    into this stage exists.
    """

    fs: float
    symbol_rate: float
    cfo_hz: float = 0.0
    beta: float | None = None          # None -> estimate it blind
    order: int | None = None           # None -> the plug-in's own order

    @property
    def sps(self) -> float:
        if self.symbol_rate <= 0:
            raise ValueError("symbol_rate from S2 must be positive")
        return self.fs / self.symbol_rate

    @classmethod
    def from_mapping(cls, params: dict[str, Any]) -> "S2Params":
        fs = float(params["fs"])
        if "symbol_rate" in params:
            rs = float(params["symbol_rate"])
        elif "sps" in params:
            rs = fs / float(params["sps"])
        else:
            raise KeyError("S2 must supply symbol_rate (or sps)")
        return cls(
            fs=fs,
            symbol_rate=rs,
            cfo_hz=float(params.get("cfo_hz", 0.0)),
            beta=params.get("beta"),
            order=params.get("order"),
        )


@runtime_checkable
class ModulationPlugin(Protocol):
    name: str
    family: str
    order: int

    def classify_features(self, iq: np.ndarray) -> dict[str, float]: ...

    def demodulate(self, iq: np.ndarray, params: dict[str, Any]) -> np.ndarray: ...

    def theoretical_cumulants(self) -> dict[str, complex]: ...
