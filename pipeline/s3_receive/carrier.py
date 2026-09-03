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
) -> CostasResult:
    """Second-order carrier recovery, run at symbol rate after timing recovery.

    One sample per symbol is all the detector needs, and the slower loop rate
    means a narrower effective bandwidth for the same coefficients.
    """
    y = np.asarray(symbols, dtype=np.complex128)
    kp, ki = loop_coefficients(loop_bw, damping)

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
    for k in range(y.size):
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
