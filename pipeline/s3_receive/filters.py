"""Pulse shaping and matched filtering.

29 Aug · Block A — RRC matched filter.
31 Aug · Block B — blind roll-off estimation.

Nothing in this module may read the zoo's answer key.  Roll-off is measured
from the signal; symbol rate arrives from S2.
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sps_signal

__all__ = ["rrc_taps", "matched_filter", "estimate_rolloff",
           "estimate_occupied_band"]


MAX_TAPS = 8191
"""Hard cap on the matched filter length.

Tap count is span * sps, so it scales with the samples-per-symbol S2 hands
over - and S2 will be wrong sometimes, deliberately so once the 4 Sep
hypothesis loop starts sweeping candidate rates. A symbol rate of 1 Hz against
a 200 kHz sample rate asks for a two-million-tap filter and a convolution that
took 257 seconds in a unit test before this cap existed. That is risk #5,
unbounded work driven by file content, inside S3 rather than S4.

8191 taps is ~20 symbols at 400 samples/symbol, far past anything a real
capture needs.
"""


def rrc_taps(beta: float, sps: float, span: int = 10) -> np.ndarray:
    """Root-raised-cosine impulse response, unit energy.

    beta  excess-bandwidth factor
    sps   samples per symbol (may be fractional)
    span  filter length in symbols (taps = span*sps + 1, forced odd)
    """
    if not 0.0 < beta <= 1.0:
        raise ValueError(f"beta must be in (0, 1], got {beta}")
    n_taps = int(round(span * sps))
    if n_taps > MAX_TAPS:
        raise ValueError(
            f"{sps:.1f} samples/symbol needs {n_taps} taps, over the "
            f"{MAX_TAPS} cap; the symbol rate estimate is implausible")
    if n_taps % 2 == 0:
        n_taps += 1
    t = (np.arange(n_taps) - (n_taps - 1) / 2.0) / sps  # in symbol periods

    h = np.empty_like(t)
    # three analytic branches: t=0, the |t|=1/(4beta) singularity, and the rest
    sing = np.isclose(np.abs(t), 1.0 / (4.0 * beta), atol=1e-8)
    zero = np.isclose(t, 0.0, atol=1e-12)
    rest = ~(sing | zero)

    h[zero] = 1.0 - beta + 4.0 * beta / np.pi

    if sing.any():
        h[sing] = (beta / np.sqrt(2.0)) * (
            (1.0 + 2.0 / np.pi) * np.sin(np.pi / (4.0 * beta))
            + (1.0 - 2.0 / np.pi) * np.cos(np.pi / (4.0 * beta))
        )

    tr = t[rest]
    num = np.sin(np.pi * tr * (1.0 - beta)) + 4.0 * beta * tr * np.cos(
        np.pi * tr * (1.0 + beta)
    )
    den = np.pi * tr * (1.0 - (4.0 * beta * tr) ** 2)
    h[rest] = num / den

    return h / np.sqrt(np.sum(h**2))


def matched_filter(x: np.ndarray, beta: float, sps: float, span: int = 10) -> np.ndarray:
    """Filter x with the RRC matched to the transmit shaping. Group delay removed,
    so sample k of the output aligns with sample k of the input."""
    h = rrc_taps(beta, sps, span)
    y = np.convolve(x, h, mode="full")
    d = (len(h) - 1) // 2
    return y[d : d + len(x)]


def _welch_psd(x: np.ndarray, fs: float, nperseg: int = 4096):
    nperseg = int(np.clip(max(256, len(x) // 8), 16, min(nperseg, len(x))))
    f, p = sps_signal.welch(
        x, fs=fs, nperseg=nperseg, noverlap=nperseg // 2,
        return_onesided=False, detrend=False, scaling="density",
    )
    order = np.argsort(f)
    return f[order], p[order]


def estimate_occupied_band(x: np.ndarray, fs: float = 1.0) -> tuple[float, float, float]:
    """Return (f_lo, f_hi, plateau_power) of the occupied band, measured at the
    half-power points of a smoothed PSD.  Blind - no labels, no S2."""
    f, p = _welch_psd(x, fs)
    # smooth so the threshold crossings are not chasing periodogram variance
    win = max(3, (len(p) // 128) | 1)
    p = sps_signal.savgol_filter(p, win, 2) if win >= 5 else p
    p = np.maximum(p, 1e-30)

    noise = np.percentile(p, 10.0)
    peak = np.percentile(p, 99.0)
    plateau = max(peak - noise, 1e-30)

    def crossing(level: float) -> tuple[float, float]:
        above = (p - noise) >= level * plateau
        idx = np.flatnonzero(above)
        if idx.size == 0:
            return f[0], f[-1]
        return float(f[idx[0]]), float(f[idx[-1]])

    lo, hi = crossing(0.5)
    return lo, hi, float(plateau)


def _raised_cosine_psd(f: np.ndarray, rs: float, beta: float) -> np.ndarray:
    """The power spectrum an RRC-shaped stream actually has.

    |H_RRC(f)|^2 is the raised cosine: flat to Rs(1-b)/2, a cosine skirt to
    Rs(1+b)/2, zero beyond. Writing it out is what lets the roll-off be fitted
    rather than inferred from two threshold crossings.
    """
    a = np.abs(f)
    flat = rs * (1.0 - beta) / 2.0
    edge = rs * (1.0 + beta) / 2.0
    out = np.zeros_like(a)
    out[a <= flat] = 1.0
    if beta > 0:
        skirt = (a > flat) & (a <= edge)
        out[skirt] = 0.5 * (1.0 + np.cos(np.pi / (beta * rs) * (a[skirt] - flat)))
    return out


def estimate_rolloff(x: np.ndarray, fs: float = 1.0,
                     symbol_rate: float | None = None,
                     grid: int = 192) -> float:
    """Blind excess-bandwidth estimate, by fitting the raised-cosine shape.

    Two earlier versions of this are worth knowing about, because both were
    reasonable and both were biased.

    The first measured the PSD width at two levels (0.9 and 0.1 of the plateau)
    and solved the analytic relation between them. Exact on an ideal spectrum,
    biased on a measured one - it read 0.60 for a true 0.50, because a wide
    roll-off keeps most of its information in the shallow tail that smoothing
    and noise-floor subtraction eat into.

    The second fitted the whole raised-cosine skirt, but normalised the measured
    PSD by a percentile first. That made the answer depend on where the 99th
    percentile of a noisy spectrum happened to land, and it got worse, not
    better, when the resolution was raised.

    This one fits amplitude and roll-off together. For each candidate beta the
    best scale is a closed-form least-squares projection, so no normalisation
    constant has to be guessed at all - only the SHAPE is being compared, which
    is the only thing beta actually controls. Checked against the transmit
    filter's own exact spectrum, the shape fit is accurate to about 0.01.

    Rs comes from S2; without it the half-power width is used, which for a
    raised cosine is beta-independent and so is a safe fallback.
    """
    f, p = _welch_psd(x, fs, nperseg=8192)
    win = max(3, (len(p) // 256) | 1)
    if win >= 5:
        p = sps_signal.savgol_filter(p, win, 2)

    noise = float(np.percentile(p, 5.0))
    p = np.maximum(p - noise, 0.0)
    if not np.any(p > 0):
        return 0.35

    if symbol_rate:
        rs = float(symbol_rate)
    else:
        half = 0.5 * float(np.percentile(p, 99.0))
        idx = np.flatnonzero(p >= half)
        if idx.size < 2:
            return 0.35
        rs = float(f[idx[-1]] - f[idx[0]])
    if not np.isfinite(rs) or rs <= 0:
        return 0.35

    # the occupied band plus a margin; the far stopband is noise floor only, and
    # including it lets the fit trade skirt accuracy against baseline
    band = np.abs(f) <= rs * 1.15
    fb, pb = f[band], p[band]
    if fb.size < 32:
        return 0.35

    best_beta, best_err = 0.35, np.inf
    for beta in np.linspace(0.02, 1.0, grid):
        m = _raised_cosine_psd(fb, rs, beta)
        mm = float(np.dot(m, m))
        if mm <= 0:
            continue
        scale = float(np.dot(pb, m)) / mm          # least-squares amplitude
        err = float(np.sum((pb - scale * m) ** 2))
        if err < best_err:
            best_err, best_beta = err, beta

    return float(np.clip(best_beta, 0.05, 1.0))
