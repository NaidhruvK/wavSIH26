"""Pulse shaping and matched filtering.

29 Aug · Block A — RRC matched filter.
31 Aug · Block B — blind roll-off estimation.

Nothing in this module may read the zoo's answer key.  Roll-off is measured
from the signal; symbol rate arrives from S2.
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sps_signal

__all__ = ["rrc_taps", "matched_filter", "estimate_rolloff", "estimate_occupied_band"]


def rrc_taps(beta: float, sps: float, span: int = 10) -> np.ndarray:
    """Root-raised-cosine impulse response, unit energy.

    beta  excess-bandwidth factor
    sps   samples per symbol (may be fractional)
    span  filter length in symbols (taps = span*sps + 1, forced odd)
    """
    if not 0.0 < beta <= 1.0:
        raise ValueError(f"beta must be in (0, 1], got {beta}")
    n_taps = int(round(span * sps))
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


def estimate_rolloff(x: np.ndarray, fs: float = 1.0, symbol_rate: float | None = None) -> float:
    """Blind excess-bandwidth estimate.

    The PSD of an RRC-shaped stream is a raised cosine: flat to Rs(1-b)/2,
    exactly half power at Rs/2 whatever b is, and zero at Rs(1+b)/2.  Two
    crossings of that skirt pin b down without knowing Rs:

        P = 0.9  ->  f_a = Rs(1-b)/2 + 0.6435 b Rs / pi
        P = 0.1  ->  f_b = Rs(1-b)/2 + 2.4981 b Rs / pi
        f_b - f_a = 0.5900 b Rs

    Rs comes from the half-power width when S2 has not supplied it.
    Returned clipped to [0.05, 1.0] — outside that the measurement is noise.
    """
    f, p = _welch_psd(x, fs)
    win = max(3, (len(p) // 128) | 1)
    if win >= 5:
        p = sps_signal.savgol_filter(p, win, 2)
    noise = np.percentile(p, 10.0)
    p = np.maximum(p - noise, 0.0)
    plateau = np.percentile(p, 99.0)
    if plateau <= 0:
        return 0.35
    p = p / plateau

    def width(level: float) -> float:
        idx = np.flatnonzero(p >= level)
        if idx.size < 2:
            return float("nan")
        return float(f[idx[-1]] - f[idx[0]])

    w50 = width(0.5)
    rs = symbol_rate if symbol_rate else w50
    if not np.isfinite(rs) or rs <= 0:
        return 0.35

    w90, w10 = width(0.9), width(0.1)
    if not (np.isfinite(w90) and np.isfinite(w10)):
        return 0.35

    beta = (w10 - w90) / (2.0 * 0.5900 * rs)
    if not np.isfinite(beta):
        return 0.35
    return float(np.clip(beta, 0.05, 1.0))
