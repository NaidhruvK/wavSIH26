"""LinearDemod - the receiver chain for every linearly modulated scheme.

31 Aug: timing and carrier wired into one plug-in.
1 Sep:  CMA in the chain; S2's estimates in, the answer key out.
2 Sep:  soft demapper; 16-QAM registered with MMA and a decision-directed carrier.

BPSK, QPSK, 8-PSK and 16-QAM differ in four things - their constellation, their
rotational symmetry, which blind equaliser suits them, and where their lock
threshold sits. Everything else is identical, so they are one class and four
registrations rather than four files that drift apart.

Chain order, and why:

    coarse CFO removal (S2)   a frequency offset biases the Gardner detector,
                              because the phase cancellation it relies on holds
                              for a constant phase, not a rotating one
    lock checks, spectral     4 Sep: is a signal at this rate actually here,
                              and is it still centred after that de-rotation?
                              Both are FFTs on the raw stream, so they cost
                              about 10 ms and can refuse the other 500
    matched filter            RRC, roll-off from S2 or measured blind
    Gardner timing            non-data-aided, so it runs before carrier recovery
    CMA / MMA                 phase-blind, so it opens the eye without
                              disturbing the rotation the Costas loop will find
    Costas                    residual carrier, leaving an S-fold ambiguity
    soft demapper             max-log LLRs, log P(0)/P(1), from a measured sigma^2
    rotations                 all S emitted, unranked, for S4 to choose between

4 Sep, Block B: `status` no longer comes from the carrier lock metric alone.
See `lockcheck.py` for why one number could not have caught the failure this
chain was actually producing - locking, confidently, to a constellation
advancing one symmetry step per symbol.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import S2Params, unusable_reason
from .carrier import costas_loop, phase_rotation_candidates
from .cumulants import cumulants
from .equalise import cma_equalise, mma_equalise
from .filters import estimate_rolloff, matched_filter
from .lockcheck import (UNKNOWN, Check, LockReport, carrier_alignment,
                        loop_check, output_usable, signal_presence)
from .metrics import evm_percent, magnitude_dispersion
from .result import Hypothesis, S3Result
from .schemes import scheme
from .softmap import (estimate_noise_variance, estimated_ber,
                      windowed_llr)
from .timing import gardner_sync

__all__ = ["LinearDemod"]

# The 4th-power line a square QAM constellation produces is genuinely weaker
# than PSK's, because its points do not share a radius. One threshold across
# both families would either fail every good QAM lock or accept every bad PSK
# one, so the number lives with the family it describes.
_LOCK_THRESHOLD = {"psk": 0.60, "qam": 0.55}

# Symbols discarded after blind equalisation, before the carrier loop sees
# anything. Measured, not guessed: with the equaliser output fed straight
# through, a 16-QAM file at 22 dB carried 312 bit errors - every single one of
# them inside the first 2000 bits, and the remaining 38 000 bits were exact.
# The blind equaliser converges from a centre spike, so its early output is
# genuinely wrong rather than merely noisy, and the carrier loop then acquires
# on top of that. MMA is given longer because it is adapting two moduli.
_EQ_WARMUP = {"psk": 600, "qam": 1200}


class LinearDemod:
    def __init__(self, scheme_name: str, settle_symbols: int = 500,
                 lock_threshold: float | None = None):
        self.scheme = scheme(scheme_name)
        self.name = self.scheme.name
        self.family = self.scheme.family
        self.order = self.scheme.order
        self.detail = self.scheme.detail
        self.settle_symbols = settle_symbols
        self.lock_threshold = (lock_threshold if lock_threshold is not None
                               else _LOCK_THRESHOLD[self.scheme.family])

    # -- registry protocol ------------------------------------------------

    def theoretical_cumulants(self) -> dict[str, complex]:
        return cumulants(self.scheme.points)

    def classify_features(self, iq: np.ndarray) -> dict[str, float]:
        """Measured cumulant magnitudes, keyed the same way the theoretical
        values come back, so the UI can put them side by side."""
        return {k: float(abs(v)) for k, v in cumulants(np.asarray(iq)).items()}

    def demodulate(self, iq: np.ndarray, params: dict[str, Any]) -> np.ndarray:
        """The protocol's method: LLRs out, nothing else.

        On failure this returns an EMPTY float array rather than raising or
        returning None. S4 iterating the registry should be able to try a
        modulation that does not fit and get a zero-length stream back, not an
        exception it has to know how to catch. The reason for the failure is on
        `receive()`, which is where a caller that cares goes looking.
        """
        res = self.receive(iq, params)
        if res.llrs is None:
            return np.zeros(0, dtype=np.float64)
        return res.llrs

    # -- the full chain ---------------------------------------------------

    def receive(self, iq: np.ndarray, params: dict[str, Any]) -> S3Result:
        t0 = time.perf_counter()
        try:
            return self._run(np.asarray(iq, dtype=np.complex128), params, t0)
        except Exception as exc:                       # noqa: BLE001
            return self._fail(t0, f"{type(exc).__name__}: {exc}")

    def _run(self, x: np.ndarray, params: dict[str, Any], t0: float) -> S3Result:
        p = S2Params.from_mapping(params)
        # Non-finite values first: every bound below is an inequality, and NaN
        # compares False against all of them. See base.unusable_reason.
        bad = unusable_reason(p)
        if bad is not None:
            return self._fail(t0, bad, envelope="outside")

        sps = p.sps
        if sps < 2.0:
            return self._fail(
                t0, f"S2 reports {sps:.2f} samples/symbol; S3 needs at least 2",
                envelope="outside")

        # Check the rate against the record BEFORE building any filter. Every
        # stage of this chain scales with sps, so an implausible rate does not
        # produce a wrong answer slowly - it produces no answer at all, very
        # slowly, which is worse. Bounded here rather than at the first thing
        # that happens to overflow.
        needed = self.settle_symbols * 2 + _EQ_WARMUP[self.scheme.family]
        available = x.size / sps
        if available < needed:
            return self._fail(
                t0, f"{sps:.1f} samples/symbol over {x.size} samples gives "
                    f"{available:.0f} symbols; this chain needs {needed}",
                envelope="outside")

        if p.cfo_hz:
            x = x * np.exp(-2j * np.pi * (p.cfo_hz / p.fs) * np.arange(x.size))

        # The two spectral checks, on the de-rotated stream and BEFORE the
        # matched filter - which is centred at zero and would drag an offset
        # spectrum back toward the middle, hiding exactly what is being looked
        # for. Both are single FFTs; together they cost about a fiftieth of the
        # chain they are standing in front of.
        report = LockReport()
        presence = signal_presence(x, p.fs, p.symbol_rate, self.family)
        report.add(presence)
        if presence.failed:
            # Nothing of this description is here. Emitting LLRs anyway would
            # hand S4 a stream of confident noise and spend its search budget
            # on it - risk #5 reached through the front door. This is the
            # clean give-up the 4 Sep row asks for.
            return self._fail(t0, presence.detail, report=report)

        alignment = carrier_alignment(x, p.fs, p.symbol_rate)
        report.add(alignment)

        beta = p.beta if p.beta is not None else estimate_rolloff(
            x, fs=1.0, symbol_rate=1.0 / sps)
        y = matched_filter(x, beta, sps)

        timing = gardner_sync(y, sps)
        if timing.symbols.size < self.settle_symbols * 2:
            return self._fail(t0, "record too short to settle the timing loop",
                              envelope="outside", report=report)
        settled = timing.symbols[self.settle_symbols:]
        report.add(loop_check(
            "timing_converged", bool(timing.locked),
            f"Gardner converged at symbol {timing.converged_at}",
            "the timing loop never converged, so every symbol after it was "
            "sampled at the wrong instant",
            # `converged_at` is None precisely when the loop did NOT converge,
            # which is the branch this check exists to report. float(None)
            # raises, and `receive()`'s catch-all would have turned an ordinary
            # unlocked file into "TypeError" with the real reason lost.
            value=(float(timing.converged_at)
                   if timing.converged_at is not None else None)))

        if self.scheme.family == "qam":
            eq = mma_equalise(settled, self.scheme.points)
        else:
            eq = cma_equalise(settled)
        # Recorded, deliberately NOT voting. `CMAResult.converged` asks whether
        # the modulus error IMPROVED between the warm-up window and the tail,
        # which is the right question on a channel with inter-symbol
        # interference and a meaningless one on a channel without: with nothing
        # to equalise the loop starts at its answer, tail and head are the same
        # noise, and the flag is a coin toss. Measured on qpsk_20dB_2011, a file
        # that demodulates to a bit error rate of exactly zero, it reads False.
        # Letting it veto would have failed a perfect file.
        #
        # The zoo has no multipath yet, so there is no evidence to set an
        # absolute dispersion threshold against either. Rather than invent one,
        # this stays `unknown`: looked at, reported, not counted. It becomes a
        # vote the day the corpus grows a channel that needs an equaliser.
        report.add(Check(
            "equaliser_converged", UNKNOWN,
            "modulus error %s between warm-up and tail; not counted, because "
            "this corpus has no inter-symbol interference for the equaliser to "
            "remove" % ("fell" if eq.converged else "did not fall")))

        warm = _EQ_WARMUP[self.scheme.family]
        if eq.symbols.size <= warm + 512:
            return self._fail(t0, "record too short for the equaliser to converge",
                              envelope="outside", report=report)
        equalised = eq.symbols[warm:]

        carrier = costas_loop(equalised, self.scheme,
                              lock_threshold=self.lock_threshold)
        report.add(loop_check(
            "carrier_locked", bool(carrier.locked),
            f"carrier lock {carrier.lock:.2f} at or above "
            f"{self.lock_threshold:.2f}",
            f"carrier lock {carrier.lock:.2f} below {self.lock_threshold:.2f}",
            value=float(carrier.lock)))

        # Drop the acquisition prefix. Emitting LLRs from symbols the carrier
        # loop had not yet acquired hands S4 a run of confidently wrong bits at
        # the head of every stream.
        sym = carrier.symbols[carrier.settled_at:]
        if sym.size < 256:
            return self._fail(t0, "carrier never settled long enough to demap",
                              report=report)

        # sigma^2 per block, not per file - see softmap.windowed_llr. The
        # file-wide number is still reported, because it is the one that
        # summarises the run.
        tail = sym[-min(4000, sym.size):]
        sigma2 = estimate_noise_variance(tail, self.scheme.points)

        rotations = phase_rotation_candidates(sym, self.scheme)
        llrs_by_rot = [windowed_llr(r, self.scheme.points) for r in rotations]
        llrs = llrs_by_rot[0]

        evm = evm_percent(tail, self.scheme)
        ber_est = estimated_ber(llrs)
        lock = carrier.lock
        report.add(output_usable(ber_est))

        hyps = [
            Hypothesis(
                value={"rotation_index": k,
                       "rotation_rad": 2.0 * np.pi * k / self.scheme.symmetry},
                score=1.0 / self.scheme.symmetry,
                evidence="constellation is invariant under this rotation; "
                         "S4's rank test is the first evidence that separates them",
            )
            for k in range(self.scheme.symmetry)
        ]

        # Every check votes. `ok` means no piece of evidence said otherwise -
        # not merely that the S-th power metric was happy, which it is even
        # when the constellation is stepping one symmetry position per symbol.
        locked = report.locked
        status = "ok" if locked else "low_confidence"
        reason = report.reason

        return S3Result(
            status=status,
            confidence=float(lock),
            values={
                **report.as_values(),
                "modulation": self.name,
                "family": self.family,
                "order": self.order,
                "bits_per_symbol": self.scheme.bits,
                "rotational_symmetry": self.scheme.symmetry,
                "sps_estimated": float(np.mean(timing.sps_track)),
                "rolloff_beta": float(beta),
                "timing_converged_at": timing.converged_at,
                "timing_locked": bool(timing.locked),
                "carrier_lock": float(lock),
                "carrier_settled_at": int(carrier.settled_at),
                "residual_cfo_rad_per_sym": float(carrier.freq[-1]),
                "equaliser": "mma" if self.scheme.family == "qam" else "cma",
                "equaliser_converged": bool(eq.converged),
                "equaliser_warmup_dropped": int(warm),
                "evm_percent": float(evm),
                "magnitude_dispersion": (float(magnitude_dispersion(tail))
                                         if self.scheme.family != "qam" else None),
                "noise_variance": float(sigma2),
                "n_symbols": int(sym.size),
                "n_llrs": int(llrs.size),
                # The correction this run would need, in Hz, on top of the CFO
                # it was given. Reported rather than applied: `search.py`
                # retries with it as one more hypothesis, and leaving it
                # visible is what keeps an upstream estimator's bug pointed at
                # rather than quietly absorbed here.
                "residual_cfo_hz": float(alignment.value or 0.0),
                "estimated_output_ber": float(ber_est),
                # The estimate is derived from LLR magnitudes, which are
                # calibrated against a noise variance measured on a
                # constellation the receiver believes it has locked. When it has
                # not, that reference is wrong and the number comes out
                # optimistic - measured at 0.003 against an actual 0.035 on
                # 8-PSK at 8 dB, and at 0.000000 against an actual 0.485 on the
                # de-rotation failure lockcheck.py describes. The flag exists so
                # a consumer cannot read the number without also being told
                # whether to believe it, and it is now gated on EVERY check
                # rather than on carrier lock alone - which was what let the
                # 0.000000 through.
                "estimated_output_ber_valid": bool(locked),
            },
            hypotheses=hyps,
            reason=reason,
            elapsed_ms=(time.perf_counter() - t0) * 1e3,
            llrs=llrs,
            llrs_by_rotation=llrs_by_rot,
            symbols=sym,
        )

    def _fail(self, t0: float, reason: str, envelope: str = "inside",
              report: LockReport | None = None) -> S3Result:
        """Every failure path, with the guaranteed keys filled in.

        `envelope="outside"` means the INPUT was beyond what this stage claims
        to support - an impossible samples-per-symbol, a record shorter than
        the loops need. `"inside"` means the input was fair game and there was
        simply nothing recoverable in it. Naidhruv's `/envelope` endpoint wants
        that distinction; `result.py` says why it is a value rather than a
        fourth status.
        """
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

    def __repr__(self) -> str:            # pragma: no cover
        return f"LinearDemod({self.name})"
