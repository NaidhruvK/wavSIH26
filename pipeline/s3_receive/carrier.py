"""Carrier recovery - Costas loop and the phase ambiguity it leaves behind.

30 Aug: derive the phase detector, implement it, wire it on top of the timing
loop, and emit every phase rotation as a candidate rather than one guess.
2 Sep: decision-directed detector for 16-QAM, over the same loop.

The Costas loop is a PLL whose phase detector is built from decisions rather
than from a pilot, so it works on a suppressed-carrier signal. For BPSK and
QPSK the classical detectors are cheap sign operations; above that a
decision-directed detector against the constellation is simpler than deriving
another special case, and behaves the same near lock. 16-QAM needs the
decision-directed form regardless, because its points do not share a modulus.

Every one of these loops locks to any rotation the constellation is invariant
under - the detector cannot see the difference, because a rotated constellation
*is* the constellation. Resolving it needs information S3 does not have. So S3
does not guess: it emits all of them as candidates and lets S4's rank test pick
the one that produces a code structure. That is risk #9, and carrying the
ambiguity forward is the whole mitigation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .schemes import Scheme, psk_constellation
from .timing import loop_coefficients

__all__ = [
    "CostasResult",
    "costas_loop",
    "phase_rotation_candidates",
    "lock_metric",
    "carrier_settle_index",
    "constellation",
]


def constellation(order: int) -> np.ndarray:
    """Back-compatible M-PSK accessor. New code should use schemes.scheme()."""
    if order not in (2, 4, 8):
        raise ValueError(f"unsupported PSK order {order}")
    return psk_constellation(order)


def _classical_psk_error(y: complex, order: int) -> float:
    mag = abs(y)
    if mag < 1e-12:
        return 0.0
    if order == 2:
        return float(np.sign(y.real) * y.imag) / mag
    return float(np.sign(y.real) * y.imag - np.sign(y.imag) * y.real) / mag


ACQ_BW_RATIO = 4.0
"""How much wider the acquisition phase runs than the tracking phase.

`gardner_sync` uses 5.0 for the same job. This is 4.0 because the Costas loop
runs at symbol rate rather than sample rate, so the same normalised bandwidth
is a wider real one, and because the detector it drives is decision-directed:
past a point a wider loop feeds its own decision errors back as phase. Both
values are the same idea and neither is a fitted constant - the sweep in
`reports/s3_loop_bw.md` measures the TRACKING bandwidth, which is the one that
sets steady-state noise, and the acquisition multiplier only has to be large
enough to pull in an offset the alignment check would have passed.
"""

ACQ_SYMBOLS = 100
"""How long the acquisition phase lasts, in symbols. MEASURED, and the way it
had to be measured is the point.

MEASURED over 8-PSK and 16-QAM, 4-13 dB, 56 files, two arms: a clean one and
one carrying a residual carrier offset of 0.02 x Rs that
`lockcheck.CARRIER_OFFSET_LIMIT` permits and therefore does reach this loop.
A "regression" is a clean-arm file whose raw bit error rate more than doubles
against the single-speed loop:

    ratio x symbols   clean decodes   offset decodes   regressions
      1.0 x   0           35/56            22/56            0        single speed
      2.0 x 150           35/56            25/56            0
      4.0 x  50           35/56            28/56            0
      4.0 x 100           35/56            31/56            0        <- chosen
      4.0 x 150           35/56            30/56            1        34x on one file
      6.0 x  50           35/56            29/56            0
      8.0 x  50           34/56            32/56            4        up to 8254x

The last row is why the regression column exists at all. A wide acquisition on
a decision-directed detector can slew the phase into a wrong rotation, and the
narrow tracking loop that follows then holds it there - so "wider acquires
better" stops being true well before the decode count notices.

THE COLUMN THAT MATTERS IS THE LAST ONE, AND IT IS NOT THE ONE THIS WAS FIRST
CHOSEN ON. The first version of this constant was 150, picked from the clean
and offset decode counts alone. Those two columns are identical at 100 and
150. What they cannot see is `16qam_8dB_5019`, which sits at a raw BER of
0.0119 - above the 1% line either way, so it is a non-decode before and after
and contributes nothing to any count - and which at 4.0 x 150 loses carrier
lock outright: metric 0.696 -> 0.023, raw BER 0.0119 -> 0.4093. A binary
decode count is blind to a file that was already failing getting 34 times
worse, and this loop's failure mode lives exactly there. 100 keeps that file
at 0.0119 and decodes one MORE offset-arm file than 150 did.

The asymmetry with `gardner_sync`'s 400 is not an inconsistency. That loop runs
at sample rate on a stream that has not been equalised; this one runs at symbol
rate on one that has, after `_EQ_WARMUP` has already spent 1200 symbols of the
record, and its detector is decision-directed - so every extra wide-bandwidth
symbol here is one more symbol of decision noise fed back as phase.
"""

MAX_LOOP_BW = 0.25
"""Ceiling on the acquisition bandwidth, so a wide tracking value cannot
multiply into an unstable one. A second-order PI loop this far open is no
longer tracking anything; the coefficients stop meaning what their derivation
says at around a quarter, and `max_freq` is at the same number for the
neighbouring reason."""


@dataclass
class CostasResult:
    symbols: np.ndarray       # de-rotated symbols
    phase: np.ndarray         # NCO phase per symbol
    freq: np.ndarray          # NCO frequency per symbol, radians/symbol
    lock: float               # 0..1
    locked: bool
    settled_at: int = 0       # first symbol at which the loop had acquired


def costas_loop(
    symbols: np.ndarray,
    sch: Scheme,
    loop_bw: float = 0.02,
    damping: float = np.sqrt(0.5),
    max_freq: float = 0.25,
    lock_threshold: float = 0.60,
    acq_bw: float | None = None,
    acq_symbols: int = ACQ_SYMBOLS,
) -> CostasResult:
    """Second-order carrier recovery, run at symbol rate after timing recovery.

    One sample per symbol is all the detector needs, and the slower loop rate
    means a narrower effective bandwidth for the same coefficients.

    GEAR-SHIFTED since 5 Sep, the same way `gardner_sync` always was: a wider
    bandwidth for the first `acq_symbols` symbols to pull the offset in, then
    the tracking bandwidth for the rest. This loop ran at one bandwidth from
    end to end until today, and `reports/s3_loop_bw.md` is what showed the
    cost. Handed a residual carrier offset of 0.02 x Rs - which
    `lockcheck.CARRIER_OFFSET_LIMIT` explicitly permits, so the pipeline does
    hand it over - 16-QAM at loop_bw 0.02 decoded **1 of 28** files. At 0.04
    it decoded 11, and lost a 10 dB file that had been decoding at 0.0029 to
    0.0299, because the wider loop that acquires better also tracks noisier.

    Two bandwidths dissolve that trade instead of choosing a side of it, and
    the corpus cannot see the problem at all: every file in it has a true
    offset of exactly zero, so the acquisition transient this fixes only
    exists on a real capture or an injected one. That is the argument for
    gear-shifting rather than for widening.

    `acq_bw=None` means `ACQ_BW_RATIO x loop_bw`. Pass `acq_bw=loop_bw` to get
    the pre-5-Sep single-speed behaviour back, which is what the sweep does
    when it measures one bandwidth end to end.
    """
    y = np.asarray(symbols, dtype=np.complex128)
    if acq_bw is None:
        acq_bw = ACQ_BW_RATIO * loop_bw
    kp_acq, ki_acq = loop_coefficients(min(float(acq_bw), MAX_LOOP_BW), damping)
    kp_trk, ki_trk = loop_coefficients(loop_bw, damping)
    kp, ki = kp_acq, ki_acq

    pts = np.asarray(sch.points, dtype=np.complex128)
    pts = pts / (np.sqrt(np.mean(np.abs(pts) ** 2)) or 1.0)
    classical = sch.family == "psk" and sch.order in (2, 4)
    # QAM decisions need the received scale to match the reference scale, or
    # every symbol slices to an inner point and the detector goes quiet
    y_rms = np.sqrt(np.mean(np.abs(y) ** 2)) or 1.0

    out = np.empty_like(y)
    ph = np.empty(y.size, dtype=np.float64)
    fr = np.empty(y.size, dtype=np.float64)

    phase = 0.0
    freq = 0.0
    shift_at = max(0, int(acq_symbols))
    for k in range(y.size):
        if k == shift_at:
            # Down to the tracking bandwidth. The NCO's phase and frequency
            # carry across untouched - only the gains change - so this is a
            # narrowing of the loop, not a restart of it.
            kp, ki = kp_trk, ki_trk
        d = y[k] * np.exp(-1j * phase)
        out[k] = d
        ph[k] = phase
        fr[k] = freq

        if classical:
            e = _classical_psk_error(d, sch.order)
        else:
            u = d / y_rms
            mag = abs(u)
            if mag < 1e-12:
                e = 0.0
            else:
                dec = pts[int(np.argmin(np.abs(u - pts)))]
                e = float((u * np.conj(dec)).imag) / max(abs(dec) * mag, 1e-12)

        e = float(np.clip(e, -1.0, 1.0))
        freq = float(np.clip(freq + ki * e, -max_freq, max_freq))
        phase = float(np.mod(phase + freq + kp * e + np.pi, 2 * np.pi) - np.pi)

    lock = lock_metric(out[-min(2000, out.size):], sch)
    settled = carrier_settle_index(out, sch, lock_threshold)
    return CostasResult(symbols=out, phase=ph, freq=fr, lock=lock,
                        locked=lock >= lock_threshold, settled_at=settled)


def lock_metric(symbols: np.ndarray, sch: Scheme) -> float:
    """|E[(y/|y|)^S]| where S is the constellation's rotational symmetry.

    1 when the constellation sits on its grid, 0 while the phase is still
    spinning, and blind to *which* of the S rotations was reached - exactly
    what a lock detector should be. It is deliberately not decision-directed:
    a decision-directed measure stays high on a spinning constellation, because
    the decisions spin with it.

    For square QAM the raw fourth-power line is nearly useless: the inner points
    do not sit at multiples of 45 degrees, so they contribute phase noise to the
    very statistic meant to detect phase noise. Measured across 10-20 dB it
    moved only between 0.24 and 0.33 - and 0.24 was a stream decoding at 49 %
    BER while 0.27 was a clean one. A threshold cannot live in that gap.

    The fix is the standard reduced-constellation trick: keep only the
    highest-magnitude quarter of the symbols. For 16-QAM those are the four
    corners, which DO sit at exact multiples of 45 degrees, so their fourth
    powers add coherently and the metric behaves like a PSK one again.
    """
    y = np.asarray(symbols)
    y = y[np.abs(y) > 1e-12]
    if y.size == 0:
        return 0.0
    if sch.family == "qam" and y.size >= 16:
        mag = np.abs(y)
        keep = mag >= np.quantile(mag, 0.75)
        y = y[keep]
    u = y / np.abs(y)
    return float(np.abs(np.mean(u ** sch.symmetry)))


def carrier_settle_index(symbols: np.ndarray, sch: Scheme,
                         threshold: float, window: int = 256,
                         sustain: int = 2, fraction: float = 0.9) -> int:
    """First symbol from which the loop is properly acquired.

    Everything before it is acquisition: the constellation is still rotating,
    so the demapper produces LLRs that are large and wrong. Large-and-wrong is
    strictly worse for a soft decoder than an erasure - it does not merely fail
    to help, it argues for the wrong bit with confidence. Trimming the prefix is
    part of emitting honest LLRs, not an optimisation.

    The bar is set against the stream's OWN settled quality, not only against an
    absolute threshold. An absolute bar has to be low enough to pass at the
    worst usable SNR, and at that height a still-converging equaliser clears it:
    on a 16-QAM file at 11.5 dB, 97 of 122 bit errors sat in the first 2000 bits
    after an absolute-threshold trim had declared the loop settled. Requiring
    the windowed metric to reach `fraction` of the tail metric, and to stay
    there for `sustain` windows, adapts the bar to the file.

    S4 tolerates an arbitrary start offset (its per-file label JSON has
    carried `start_offset` since the 29th), so dropping a prefix costs nothing
    downstream.
    """
    y = np.asarray(symbols)
    n = y.size
    if n < 4 * window:
        return 0

    tail = lock_metric(y[-min(4 * window, n // 2):], sch)
    bar = max(threshold, fraction * tail)

    step = window // 2
    good = 0
    first = 0
    for start in range(0, n - window, step):
        if lock_metric(y[start : start + window], sch) >= bar:
            if good == 0:
                first = start
            good += 1
            if good >= sustain:
                return first
        else:
            good = 0
    return 0


def phase_rotation_candidates(symbols: np.ndarray, sch: Scheme) -> list[np.ndarray]:
    """The S rotations of a locked constellation, ascending in angle.

    Unranked and unscored on purpose. S3 has no evidence that separates them -
    the constellation is invariant under all of them - so any score would be
    invented. S4's rank test is the first place real evidence exists.
    """
    s = sch.symmetry
    return [symbols * np.exp(2j * np.pi * k / s) for k in range(s)]
