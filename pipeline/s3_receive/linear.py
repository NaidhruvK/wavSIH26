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
from .lockcheck import (UNKNOWN, Check, LockReport, alphabet_used,
                        carrier_alignment, loop_check, output_usable,
                        signal_presence)
from .metrics import evm_percent, magnitude_dispersion
from .result import Hypothesis, S3Result
from .schemes import scheme
from .softmap import (estimate_noise_variance, estimated_ber,
                      windowed_llr)
from .timing import gardner_sync

__all__ = ["LinearDemod"]

# Carrier lock threshold, per SCHEME. It was per family - {"psk": 0.60,
# "qam": 0.55} - until 5 Sep, and one key too coarse.
#
# The metric is |E[u^S]| with S the constellation's rotational symmetry: 2 for
# BPSK, 4 for QPSK and 16-QAM, 8 for 8-PSK. Raising a noisy symbol to the S-th
# power raises its phase error to the S-th power with it, so at a fixed symbol
# error rate the metric falls as S rises. The three PSK schemes therefore
# cannot share a number, for the same structural reason the old constant
# already split PSK from QAM - one level finer. MEASURED at 8 dB, correct
# hypothesis, over the 252-file corpus: bpsk 0.950, qpsk 0.837, 8psk 0.488,
# 16qam 0.680. A single number across those is either loose enough to be
# meaningless for BPSK or tight enough to refuse working 8-PSK, and 0.60 was
# doing the second: every 8-PSK file at 8 dB demodulates at a bit error rate
# of 0.0025-0.0034 and every one was reported `low_confidence`.
#
# Each value is the geometric midpoint of the gap between the two populations
# this threshold is responsible for, measured in `reports/s3_lock_threshold.md`
# over 1008 runs (every corpus file through every linear plug-in):
#
#     scheme   worst that decodes   best that does not   ratio   chosen
#     bpsk           0.857                0.059         14.61x    0.23
#     qpsk           0.636                0.328          1.94x    0.46
#     8psk           0.488                0.184          2.65x    0.30
#     16qam          0.784                0.437          1.79x    0.59
#
# Re-measured after the acquisition gear-shift landed, because these were first
# taken against a loop that then changed underneath them - the study has to be
# newer than the code it describes or it is describing something else. Every
# gap survived. BPSK's geometric midpoint comes out at 0.226 on the current
# loop against 0.227 before it; 0.23 is kept, since a thousandth is not an
# improvement and the incumbent wins ties.
#
# "Best that does not" counts only genuine failures - runs at 2% raw bit error
# rate or worse - and only runs that no OTHER check already vetoed, since a
# hypothesis refused by `alphabet_used` on the same run cannot be admitted
# whatever this number says. Seven 16-QAM files at 8 dB sit between the two
# populations at 0.680-0.788 and 1.17-1.24% BER; they are in neither, because
# they are a decode line drawn at 1% cutting a continuum, not a lock failure -
# the receiver's own estimate on them is 1.00-1.09%, which is right, and they
# pass at 0.59 as they should. That exclusion is the one judgement in this
# table and it is stated rather than buried: include them and no threshold
# separates 16-QAM at all, because the worst file that decodes reads 0.784 and
# the best that does not reads 0.788.
#
# Note 16-QAM goes UP. The row for today says lower the thresholds and three
# of the four come down hard; the measurement says this one was slightly loose
# and it is reported as measured rather than as expected.
_LOCK_THRESHOLD = {"bpsk": 0.23, "qpsk": 0.46, "8psk": 0.30, "16qam": 0.59}

# Fallback for a scheme registered after this table was measured. A new
# constellation gets the old family number until someone runs the study for
# it, which is conservative in the direction that matters: too tight refuses a
# working file, too loose claims a lock that is not there.
_LOCK_THRESHOLD_BY_FAMILY = {"psk": 0.60, "qam": 0.55}

# Symbols discarded after blind equalisation, before the carrier loop sees
# anything. Measured, not guessed: with the equaliser output fed straight
# through, a 16-QAM file at 22 dB carried 312 bit errors - every single one of
# them inside the first 2000 bits, and the remaining 38 000 bits were exact.
# The blind equaliser converges from a centre spike, so its early output is
# genuinely wrong rather than merely noisy, and the carrier loop then acquires
# on top of that. MMA is given longer because it is adapting two moduli.
_EQ_WARMUP = {"psk": 600, "qam": 1200}

# Loop noise bandwidths, per SCHEME and not per family. Both loops ran at one
# global number until 5 Sep - `costas_loop`'s 0.02 and `gardner_sync`'s 0.004 -
# and the two knobs are here rather than at the call site so that one place
# answers "what bandwidth does this modulation use, and on what evidence".
#
# Per scheme rather than per family because the quantity that sets the right
# bandwidth is the DETECTOR's self-noise, and that is a property of the
# constellation, not of the family: QPSK and 8-PSK are both "psk" and their
# decision-directed phase detectors do not behave alike. A wider loop acquires
# sooner and tracks a drifting offset better; it also feeds more of the
# detector's own noise back into the phase estimate, and past some point that
# costs more than the tracking gains.
#
# MEASURED 5 Sep, `reports/s3_loop_bw.md`: 112 files x 5 bandwidths x 2 arms
# per knob, where the second arm carries the impairment the loop exists to
# remove. NOTHING MOVED. Every value below is the pre-5-Sep global, kept
# because the sweep either found nothing better or found something that turned
# out to be worse for a reason the sweep could not see. Both are results:
#
#   bpsk, qpsk    28/28 in all ten cells of both arms. The sweep has no
#                 discriminating power here and the honest output is "no
#                 change", not the smallest number in the grid.
#   8psk          0.02 -> 0.04 was measured, shipped, and REVERTED the same
#                 day. The sweep said clean arm identical at 21/28 and impaired
#                 20/28 -> 21/28, monotone, so the direction looked real. What
#                 the sweep could not see is that it only ever runs the CORRECT
#                 plug-in. Run a QPSK capture through the 8-PSK plug-in - the
#                 subset trap `alphabet_used` exists for - and the wider loop
#                 smears the four-point cloud across all eight decision
#                 regions: on `qpsk_8dB_2007`, normalised alphabet entropy goes
#                 0.691 (fail, refused) at 0.02 to 0.947 (pass) at 0.04, and
#                 the stage returns `status: ok` with a self-estimated output
#                 BER of 0.0035 over a stream that is 48.4% wrong. That is the
#                 4 Sep failure reintroduced through a different door, for one
#                 file on an injected-offset arm. Not a trade worth making, and
#                 a reminder that a per-scheme sweep over correct hypotheses
#                 cannot see a check that only wrong hypotheses exercise.
#   16qam         stays at 0.02. 0.04 reaches 13/28 on the impaired arm
#                 against 9/28, and costs `16qam_10dB_4020` on the clean arm -
#                 raw BER 0.0029 -> 0.0299. That is a 10 dB file, and >=10 dB
#                 is the region the day gate is written on, so it is not
#                 traded for an injected scenario. Stated rather than
#                 silently taken: a residual of 0.02 x Rs passes
#                 `CARRIER_OFFSET_LIMIT` and does reach the loop uncorrected,
#                 so the exposure is real and the number to beat is 9/28.
#
# Timing bandwidth: no scheme moved. 16-QAM's grid reads 12/14/13/14/13 on the
# clean arm with median BER 0.020/0.009/0.015/0.009/0.019 - non-monotone across
# a 16x range, which is a response with no reliable signal in it rather than an
# optimum at 0.002. Picking the best cell of an alternating sequence is fitting
# this corpus, not tuning a loop.
#
# NO TRACKING BANDWIDTH CHANGED. The whole carrier-loop result of the day is
# that `costas_loop` had no acquisition phase at all - see `carrier.ACQ_SYMBOLS`
# - and that is a structural fix rather than a number in this table.
_CARRIER_LOOP_BW = {"bpsk": 0.02, "qpsk": 0.02, "8psk": 0.02, "16qam": 0.02}
_TIMING_LOOP_BW = {"bpsk": 0.004, "qpsk": 0.004, "8psk": 0.004, "16qam": 0.004}


class LinearDemod:
    def __init__(self, scheme_name: str, settle_symbols: int = 500,
                 lock_threshold: float | None = None,
                 carrier_loop_bw: float | None = None,
                 timing_loop_bw: float | None = None):
        self.scheme = scheme(scheme_name)
        self.name = self.scheme.name
        self.family = self.scheme.family
        self.order = self.scheme.order
        self.detail = self.scheme.detail
        self.settle_symbols = settle_symbols
        self.lock_threshold = float(
            lock_threshold if lock_threshold is not None
            else _LOCK_THRESHOLD.get(
                self.name, _LOCK_THRESHOLD_BY_FAMILY[self.scheme.family]))
        # Overridable so the sweep can drive the real chain rather than a copy
        # of it. A study that measures a reimplementation measures the
        # reimplementation; this is the same class of mistake as the two
        # channel models `tests/fixtures/corpus.py` was written to delete.
        self.carrier_loop_bw = float(
            carrier_loop_bw if carrier_loop_bw is not None
            else _CARRIER_LOOP_BW.get(self.name, 0.02))
        self.timing_loop_bw = float(
            timing_loop_bw if timing_loop_bw is not None
            else _TIMING_LOOP_BW.get(self.name, 0.004))

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

        timing = gardner_sync(y, sps, loop_bw=self.timing_loop_bw)
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
                              loop_bw=self.carrier_loop_bw,
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
        # Last, because it needs the demodulated symbols - and the only
        # check that can refuse a constellation which CONTAINS the true
        # one. Everything above asks whether the receiver locked; this
        # asks whether it locked to the right alphabet.
        report.add(alphabet_used(sym, self.scheme.points))

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
