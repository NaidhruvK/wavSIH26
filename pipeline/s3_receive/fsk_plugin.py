"""FSKDemod - the non-coherent FSK branch as a registry plug-in.

31 Aug: the branch itself, registered.
2 Sep:  soft output. LLRs from tone energies rather than from distances.

Shares the registry interface with LinearDemod and almost nothing else. There
is no matched filter to a pulse shape, no equaliser and no carrier loop, and
therefore **no phase ambiguity to hand to S4** - the tone carrying the most
energy in the symbol window is the decision, and energy does not care about
phase. That is the point of non-coherent detection and it is why this plug-in
returns no rotation candidates while every linear one returns several.

2-FSK and 4-FSK are the same code and two registrations; the tone bank and the
Gray bit labelling both generalise on `order`.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import S2Params
from .cumulants import cumulants
from .fsk import estimate_tones, fsk_demod_noncoherent
from .result import Hypothesis, S3Result
from .softmap import estimated_ber, noncoherent_llr

__all__ = ["FSKDemod"]


class FSKDemod:
    family = "fsk"

    def __init__(self, order: int = 2, name: str | None = None,
                 confidence_threshold: float = 0.15,
                 reference_separation: float = 0.05):
        self.order = order
        self.name = name or f"{order}fsk"
        self.confidence_threshold = confidence_threshold
        self.reference_separation = reference_separation
        self.detail = (f"{order}-FSK, non-coherent tone bank, "
                       f"{int(order).bit_length() - 1} bit(s)/symbol, "
                       "no phase ambiguity")

    # -- registry protocol ------------------------------------------------

    def theoretical_cumulants(self) -> dict[str, complex]:
        """FSK has no fixed complex constellation, so these are the cumulants of
        an ideal noiseless CPFSK reference waveform at the plug-in's nominal
        tone separation - not of a symbol alphabet. Documented rather than
        omitted: a NaN row beside the PSK plug-ins reads as a bug, and this is
        the value a classifier actually compares against."""
        n_sym, sps = 512, 8
        rng = np.random.default_rng(0)
        syms = rng.integers(0, self.order, n_sym)
        tones = (np.arange(self.order) - (self.order - 1) / 2.0) * (
            self.reference_separation / max(self.order - 1, 1))
        inst = np.repeat(tones[syms], sps)
        return cumulants(np.exp(2j * np.pi * np.cumsum(inst)))

    def classify_features(self, iq: np.ndarray) -> dict[str, float]:
        return {k: float(abs(v)) for k, v in cumulants(np.asarray(iq)).items()}

    def demodulate(self, iq: np.ndarray, params: dict[str, Any]) -> np.ndarray:
        res = self.receive(iq, params)
        if res.llrs is None:
            return np.zeros(0, dtype=np.float64)
        return res.llrs

    # -- the chain --------------------------------------------------------

    def receive(self, iq: np.ndarray, params: dict[str, Any]) -> S3Result:
        t0 = time.perf_counter()
        try:
            return self._run(np.asarray(iq, dtype=np.complex128), params, t0)
        except Exception as exc:                       # noqa: BLE001
            return S3Result(status="failed", confidence=0.0,
                            values={"modulation": self.name},
                            reason=f"{type(exc).__name__}: {exc}",
                            elapsed_ms=(time.perf_counter() - t0) * 1e3)

    def _run(self, x: np.ndarray, params: dict[str, Any], t0: float) -> S3Result:
        p = S2Params.from_mapping(params)
        sps = p.sps
        if sps < 2.0:
            return S3Result(
                status="failed", confidence=0.0,
                values={"modulation": self.name},
                reason=f"S2 reports {sps:.2f} samples/symbol; S3 needs at least 2",
                elapsed_ms=(time.perf_counter() - t0) * 1e3)

        if p.cfo_hz:
            x = x * np.exp(-2j * np.pi * (p.cfo_hz / p.fs) * np.arange(x.size))

        # Degenerate input must come back as `failed` with a reason, not as a
        # short run of zero-information LLRs. Zero LLRs are not harmless: they
        # are indistinguishable from "every bit is a coin flip", which is a
        # claim about the data rather than about the receiver, and S4 would
        # spend its sweep budget on them.
        min_symbols = 64
        if x.size < min_symbols * sps:
            return S3Result(
                status="failed", confidence=0.0,
                values={"modulation": self.name},
                reason=f"{x.size} samples is under the {int(min_symbols * sps)} "
                       f"needed for {min_symbols} symbols at {sps:.1f} sps",
                elapsed_ms=(time.perf_counter() - t0) * 1e3)
        power = float(np.mean(np.abs(x) ** 2))
        if power <= 1e-20:
            return S3Result(
                status="failed", confidence=0.0,
                values={"modulation": self.name},
                reason="input carries no energy",
                elapsed_ms=(time.perf_counter() - t0) * 1e3)

        tones = params.get("tones")
        tones = (np.asarray(tones, dtype=float) if tones is not None
                 else estimate_tones(x, self.order))

        res = fsk_demod_noncoherent(x, sps, tones=tones, order=self.order)
        llrs = noncoherent_llr(res.metrics, self.order)

        locked = res.confidence >= self.confidence_threshold
        status = "ok" if locked else "low_confidence"
        reason = None if locked else (
            f"mean tone margin {res.confidence:.3f} below "
            f"{self.confidence_threshold:.3f}")

        return S3Result(
            status=status,
            confidence=float(res.confidence),
            values={
                "modulation": self.name,
                "family": self.family,
                "order": self.order,
                "bits_per_symbol": int(self.order).bit_length() - 1,
                "rotational_symmetry": 1,
                "tones_normalised": res.tones.tolist(),
                "tone_spacing_hz": (float(np.diff(res.tones).mean() * p.fs)
                                    if res.tones.size > 1 else 0.0),
                "symbol_offset": int(res.offset),
                "n_symbols": int(res.indices.size),
                "n_llrs": int(llrs.size),
                "mean_margin": float(res.confidence),
                "estimated_output_ber": float(estimated_ber(llrs)),
            },
            hypotheses=[Hypothesis(value={"tones": res.tones.tolist()},
                                   score=float(res.confidence),
                                   evidence="strongest separated PSD peaks")],
            reason=reason,
            elapsed_ms=(time.perf_counter() - t0) * 1e3,
            llrs=llrs,
            llrs_by_rotation=[llrs],
            symbols=None,
        )

    def __repr__(self) -> str:            # pragma: no cover
        return f"FSKDemod({self.name})"
