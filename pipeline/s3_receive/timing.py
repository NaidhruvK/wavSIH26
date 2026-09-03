"""Symbol timing recovery - Gardner timing-error detector.

29 Aug, Block A/B/C: derive the TED, implement it, lock it on a zoo file.

Gardner's detector is non-data-aided and independent of carrier phase, which is
why it runs *before* the Costas loop: it needs two samples per symbol and
nothing else. For a symbol stream y, with y_mid the sample halfway between
consecutive symbols,

    e[k] = Re{ (y[k] - y[k-1]) * conj(y_mid[k]) }

The intuition: at correct timing the midpoint sits on the zero crossing between
two differing symbols, so the product averages to zero. Sampling early or late
biases the midpoint onto one side and the sign of e says which. A constant
carrier phase rotation cancels between the conjugate pair, which is what makes
it usable before carrier recovery.

Timing is recovered by interpolation rather than by resampling the whole record,
so a fractional and slowly-drifting samples-per-symbol is tracked rather than
assumed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "GardnerResult",
    "gardner_sync",
    "loop_coefficients",
    "smoothed_error",
]


def loop_coefficients(loop_bw: float, damping: float = np.sqrt(0.5)) -> tuple[float, float]:
    """Second-order PI loop gains from a normalised noise bandwidth.

    The same parameterisation is used for the Costas loop, so one 'loop_bw' knob
    means the same thing in both places.
    """
    denom = 1.0 + 2.0 * damping * loop_bw + loop_bw * loop_bw
    kp = (4.0 * damping * loop_bw) / denom
    ki = (4.0 * loop_bw * loop_bw) / denom
    return kp, ki


def _cubic(x: np.ndarray, i: int, mu: float) -> complex:
    """Four-point cubic Lagrange interpolation at x[i + mu], mu in [0, 1)."""
    xm1, x0, x1, x2 = x[i - 1], x[i], x[i + 1], x[i + 2]
    m = mu
    c_m1 = -m * (m - 1.0) * (m - 2.0) / 6.0
    c_0 = (m + 1.0) * (m - 1.0) * (m - 2.0) / 2.0
    c_1 = -(m + 1.0) * m * (m - 2.0) / 2.0
    c_2 = (m + 1.0) * m * (m - 1.0) / 6.0
    return xm1 * c_m1 + x0 * c_0 + x1 * c_1 + x2 * c_2


@dataclass
class GardnerResult:
    symbols: np.ndarray          # one complex sample per recovered symbol
    positions: np.ndarray        # absolute sample position each symbol was taken at
    error: np.ndarray            # raw TED output per symbol
    sps_track: np.ndarray        # tracked samples-per-symbol per symbol
    converged_at: int | None     # symbol index at which the loop settled
    locked: bool


def gardner_sync(
    x: np.ndarray,
    sps: float,
    loop_bw: float = 0.004,
    acq_bw: float | None = None,
    acq_symbols: int = 400,
    damping: float = np.sqrt(0.5),
    max_rate_dev: float = 0.05,
    settle_tol: float = 3.0,
    settle_run: int = 200,
    settle_smooth: int = 128,
) -> GardnerResult:
    """Recover symbol timing from an oversampled complex baseband stream.

    sps            samples per symbol, from S2 - never from the answer key
    loop_bw        normalised loop noise bandwidth in the tracking phase
    acq_bw         wider bandwidth used for the first `acq_symbols` symbols.
                   Gear-shifting is the whole tuning story here: one fixed
                   bandwidth either acquires slowly or jitters forever. Wide
                   then narrow gets a fractional-symbol offset pulled in inside
                   a few hundred symbols and still leaves a quiet steady state.
    acq_symbols    length of the acquisition phase, in symbols
    max_rate_dev   how far the tracked period may wander from the S2 estimate
    settle_tol     convergence band, in multiples of the loop's own steady-state
                   error RMS. Measuring the band against the tail rather than
                   against a fixed number is what makes one threshold work from
                   20 dB down to 8 dB: the residual jitter floor rises with
                   noise, and a fixed tolerance would simply report 'never
                   converged' for every low-SNR file that had in fact locked.
    settle_run     how many consecutive symbols must stay inside the band
    settle_smooth  moving-average length. The raw per-symbol TED output is far
                   too noisy to threshold directly - its instantaneous value is
                   driven by which symbol transitions happen to occur.
    """
    x = np.asarray(x, dtype=np.complex128)
    if sps < 2.0:
        raise ValueError(f"Gardner needs at least 2 samples/symbol, got {sps}")
    if x.size < 8 * sps:
        raise ValueError("record too short for timing recovery")

    power = float(np.mean(np.abs(x) ** 2)) or 1.0
    if acq_bw is None:
        acq_bw = 5.0 * loop_bw
    kp_acq, ki_acq = loop_coefficients(acq_bw, damping)
    kp_trk, ki_trk = loop_coefficients(loop_bw, damping)
    kp, ki = kp_acq, ki_acq

    period = float(sps)          # tracked samples per symbol
    p_min, p_max = sps * (1.0 - max_rate_dev), sps * (1.0 + max_rate_dev)
    integ = 0.0

    n_sym = int((x.size - 4) / sps) - 2
    symbols = np.empty(n_sym, dtype=np.complex128)
    positions = np.empty(n_sym, dtype=np.float64)
    errors = np.empty(n_sym, dtype=np.float64)
    tracks = np.empty(n_sym, dtype=np.float64)

    pos = 2.0 + period                       # leave room for the interpolator
    prev = _cubic(x, int(pos), pos - int(pos))
    pos += period / 2.0
    k = 0
    limit = x.size - 4

    while k < n_sym and pos < limit:
        i = int(pos)
        mid = _cubic(x, i, pos - i)
        pos += period / 2.0
        if pos >= limit:
            break
        i = int(pos)
        cur = _cubic(x, i, pos - i)

        # Gardner TED. Sign convention: the raw detector is positive when the
        # current sample is LATE, so it is negated before the loop filter, which
        # then advances the tracked period. Get this backwards and the loop still
        # settles - on the zero crossing half a symbol away. Stable, and
        # completely wrong. The eye is what tells the two apart.
        e = -float(((cur - prev) * np.conj(mid)).real) / power
        e = float(np.clip(e, -2.0, 2.0))     # one bad sample must not throw the loop

        if k == acq_symbols:
            kp, ki = kp_trk, ki_trk       # gear shift into tracking

        # The loop filter works in RELATIVE period units, not samples. A
        # correction expressed in samples would make the effective loop gain
        # scale with sps - the same normalised timing error would be corrected
        # half as hard at 8 sps as at 4, which shows up as a slow rate bias and
        # a constellation that decays over a long record.
        integ += ki * e
        integ = float(np.clip(integ, -max_rate_dev, max_rate_dev))
        period = float(np.clip(sps * (1.0 + kp * e + integ), p_min, p_max))

        symbols[k] = cur
        positions[k] = pos
        errors[k] = e
        tracks[k] = period
        prev = cur
        k += 1
        pos += period / 2.0

    symbols, positions = symbols[:k], positions[:k]
    errors, tracks = errors[:k], tracks[:k]

    converged_at = _first_settled(errors, settle_tol, settle_run, settle_smooth)
    return GardnerResult(
        symbols=symbols,
        positions=positions,
        error=errors,
        sps_track=tracks,
        converged_at=converged_at,
        locked=converged_at is not None,
    )


def smoothed_error(err: np.ndarray, window: int = 64) -> np.ndarray:
    """Moving average of the TED output - this is the trace worth plotting."""
    if err.size < window or window < 2:
        return err.copy()
    k = np.ones(window) / window
    return np.convolve(err, k, mode="same")


def _first_settled(err: np.ndarray, tol: float, run: int, window: int = 128) -> int | None:
    """First symbol index after which the smoothed TED output settles into its
    own steady-state band and stays there for `run` consecutive symbols.

    This is the number the 29 Aug gate asks for: convergence inside 2000 symbols.
    """
    if err.size < max(run, 4 * window):
        return None
    sm = smoothed_error(err, window)
    tail = sm[-max(run, err.size // 4):]
    band = max(tol * float(np.sqrt(np.mean(tail ** 2))), 2e-3)
    inside = (np.abs(sm) < band).astype(np.int8)
    csum = np.concatenate(([0], np.cumsum(inside)))
    window_sum = csum[run:] - csum[:-run]
    hit = np.flatnonzero(window_sum == run)
    if hit.size == 0:
        return None
    return int(hit[0])
