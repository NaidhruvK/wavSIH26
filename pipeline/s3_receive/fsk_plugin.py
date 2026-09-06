"""FSKDemod - the non-coherent FSK branch as a registry plug-in.

31 Aug: the branch itself, registered.
2 Sep:  soft output. LLRs from tone energies rather than from distances.

Shares the registry interface with LinearDemod and almost nothing else. There
is no matched filter to a pulse shape, no equaliser and no carrier loop, and
therefore **no phase ambiguity to hand to S4** - the tone carrying the most
energy in the symbol window is the decision, and energy does not care about
phase. That is the point of non-coherent detection and it is why this plug-in
returns no rotation candidates while every linear one returns several.

4 Sep, and this correction is the whole reason for the paragraph above being
qualified: there is no PHASE ambiguity, and there is a FREQUENCY one. Shift an
M-FSK signal by exactly one tone spacing and the tone bank finds the same M
tones in the same places while every tone's LABEL has moved by one, so every
symbol decodes to its neighbour. Measured on `4fsk_13dB_2033`: a -49 951 Hz
offset against a 50 kHz spacing, tones recovered identically to the true ones,
and a bit error rate of 0.248 - one position of slip on a Gray-labelled 4-ary
alphabet - with every check passing.

It is not resolvable from the signal, exactly as the linear family's rotation
is not. The linear family carries its ambiguity forward as candidates and lets
S4 choose; this branch instead REFUSES the hypothesis (`lockcheck.tone_alias`),
because a carrier offset that is a whole number of tone spacings is one S3 was
never able to justify applying. Emitting M label-rotations the way the linear
branch emits S phase-rotations is the symmetric fix and would multiply S4's
per-file work by the FSK order; that is a cross-stream decision, so it is
written down here for the 7 Sep FSK row rather than taken quietly today.

2-FSK and 4-FSK are the same code and two registrations; the tone bank and the
Gray bit labelling both generalise on `order`.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import S2Params, unusable_reason
from .cumulants import cumulants
from .fsk import estimate_tones, fsk_demod_noncoherent
from .lockcheck import (LockReport, carrier_alignment, loop_check,
                        output_usable, signal_presence, tone_alias)
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
            return self._fail(t0, f"{type(exc).__name__}: {exc}")

    def _fail(self, t0: float, reason: str, envelope: str = "inside",
              report: LockReport | None = None) -> S3Result:
        """Every failure path, with the guaranteed keys filled in.
        See `LinearDemod._fail` and `result.REQUIRED_VALUES`."""
        values: dict[str, Any] = {"modulation": self.name,
                                  "family": self.family,
                                  "envelope": envelope,
                                  "estimated_output_ber": 1.0,
                                  "estimated_output_ber_valid": False}
        if report is not None:
            values.update(report.as_values())
        return S3Result(status="failed", confidence=0.0, values=values,
                        reason=reason,
                        elapsed_ms=(time.perf_counter() - t0) * 1e3)

    def _run(self, x: np.ndarray, params: dict[str, Any], t0: float) -> S3Result:
        p = S2Params.from_mapping(params)
        bad = unusable_reason(p)          # see base.unusable_reason
        if bad is not None:
            return self._fail(t0, bad, envelope="outside")

        sps = p.sps
        if sps < 2.0:
            return self._fail(
                t0, f"S2 reports {sps:.2f} samples/symbol; S3 needs at least 2",
                envelope="outside")

        if p.cfo_hz:
            x = x * np.exp(-2j * np.pi * (p.cfo_hz / p.fs) * np.arange(x.size))

        # Degenerate input must come back as `failed` with a reason, not as a
        # short run of zero-information LLRs. Zero LLRs are not harmless: they
        # are indistinguishable from "every bit is a coin flip", which is a
        # claim about the data rather than about the receiver, and S4 would
        # spend its sweep budget on them.
        min_symbols = 64
        if sps > x.size:
            return self._fail(
                t0, f"{sps:.1f} samples/symbol over {x.size} samples is not "
                    "a plausible rate", envelope="outside")
        if x.size < min_symbols * sps:
            return self._fail(
                t0, f"{x.size} samples is under the {int(min_symbols * sps)} "
                    f"needed for {min_symbols} symbols at {sps:.1f} sps",
                envelope="outside")
        power = float(np.mean(np.abs(x) ** 2))
        if power <= 1e-20:
            return self._fail(t0, "input carries no energy")

        # The same two spectral checks the linear chain runs, on the same
        # evidence. FSK reaches them by a different statistic - see
        # lockcheck.symbol_rate_line - because a constant-envelope signal has
        # no cyclostationary line in |x|^2 at all.
        report = LockReport()
        presence = signal_presence(x, p.fs, p.symbol_rate, self.family)
        report.add(presence)
        if presence.failed:
            return self._fail(t0, presence.detail, report=report)

        # A wrong CFO hypothesis is not harmless here even though detection is
        # non-coherent and `estimate_tones` finds the tones wherever they sit.
        # De-rotating a wideband CPFSK signal far enough wraps its outer tones
        # around the band edge, and the tone bank then finds an alias.
        # Measured: 4fsk_10dB_2032 demodulates exactly at cfo 0 and to a bit
        # error rate of 0.247 after S2's 25 kHz de-rotation.
        alignment = carrier_alignment(x, p.fs, p.symbol_rate)
        report.add(alignment)

        tones = params.get("tones")
        tones = (np.asarray(tones, dtype=float) if tones is not None
                 else estimate_tones(x, self.order))

        res = fsk_demod_noncoherent(x, sps, tones=tones, order=self.order)
        llrs = noncoherent_llr(res.metrics, self.order)

        # The tone bank is measured, so its spacing is known here and nowhere
        # earlier - which is why this check sits after the demodulation rather
        # than in the pre-chain screen with the other two.
        spacing = (float(np.diff(res.tones).mean() * p.fs)
                   if res.tones.size > 1 else 0.0)
        report.add(tone_alias(p.cfo_hz, spacing))

        ber_est = float(estimated_ber(llrs))
        report.add(output_usable(ber_est))

        report.add(loop_check(
            "tone_margin", res.confidence >= self.confidence_threshold,
            f"mean tone margin {res.confidence:.3f} at or above "
            f"{self.confidence_threshold:.3f}",
            f"mean tone margin {res.confidence:.3f} below "
            f"{self.confidence_threshold:.3f}",
            value=float(res.confidence)))

        locked = report.locked
        status = "ok" if locked else "low_confidence"
        reason = report.reason

        return S3Result(
            status=status,
            confidence=float(res.confidence),
            values={
                **report.as_values(),
                "modulation": self.name,
                "family": self.family,
                "order": self.order,
                "bits_per_symbol": int(self.order).bit_length() - 1,
                "rotational_symmetry": 1,
                "tones_normalised": res.tones.tolist(),
                "tone_spacing_hz": spacing,
                "symbol_offset": int(res.offset),
                "n_symbols": int(res.indices.size),
                "n_llrs": int(llrs.size),
                "mean_margin": float(res.confidence),
                "residual_cfo_hz": float(alignment.value or 0.0),
                "estimated_output_ber": ber_est,
                # see the note in linear.py - the same caveat applies, with the
                # tone margin standing in for carrier lock, and the flag now
                # gated on every check rather than on the margin alone
                "estimated_output_ber_valid": bool(locked),
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
