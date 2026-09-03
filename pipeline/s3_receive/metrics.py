"""Receiver quality metrics.

30 Aug: EVM per corpus file.
3 Sep:  the LLR quality diagnostics S4 needs at the junction.

Everything here is decision-directed against the registered constellation. None
of it reads the zoo's answer key, so every number is one the receiver can also
produce on a file nobody has labels for - which is the only kind of number worth
putting on a screen in front of a judge.
"""
from __future__ import annotations

import numpy as np

from .schemes import Scheme

__all__ = ["evm_percent", "hard_decisions", "symbol_error_rate",
           "magnitude_dispersion", "normalise"]


def normalise(symbols: np.ndarray) -> np.ndarray:
    y = np.asarray(symbols, dtype=np.complex128)
    scale = np.sqrt(np.mean(np.abs(y) ** 2)) if y.size else 1.0
    return y / (scale or 1.0)


def hard_decisions(symbols: np.ndarray, sch: Scheme) -> tuple[np.ndarray, np.ndarray]:
    """Nearest constellation point per symbol. Returns (indices, points)."""
    y = normalise(symbols)
    pts = np.asarray(sch.points, dtype=np.complex128)
    pts = pts / (np.sqrt(np.mean(np.abs(pts) ** 2)) or 1.0)
    idx = np.argmin(np.abs(y[:, None] - pts[None, :]), axis=1)
    return idx, pts[idx]


def evm_percent(symbols: np.ndarray, sch: Scheme) -> float:
    """RMS error-vector magnitude against the nearest constellation point, as a
    percentage of the reference RMS amplitude."""
    y = normalise(symbols)
    if y.size == 0:
        return float("nan")
    _, ref = hard_decisions(y, sch)
    num = np.sqrt(np.mean(np.abs(y - ref) ** 2))
    den = np.sqrt(np.mean(np.abs(ref) ** 2))
    return float(100.0 * num / den) if den else float("nan")


def magnitude_dispersion(symbols: np.ndarray) -> float:
    """Standard deviation of |y| after unit-mean normalisation.

    A timing-quality proxy needing neither decisions nor a constellation: a
    constant-modulus stream sampled at the wrong instant picks up ISI, and ISI
    shows as amplitude spread first. Meaningless for QAM, whose points genuinely
    differ in modulus - the QAM plug-in reports EVM instead.
    """
    y = np.asarray(symbols)
    m = np.mean(np.abs(y))
    if m <= 0:
        return float("nan")
    return float(np.std(np.abs(y) / m))


def symbol_error_rate(rx_idx: np.ndarray, tx_idx: np.ndarray) -> float:
    """Harness-only: needs the transmitted symbols, which S3 never has."""
    n = min(rx_idx.size, tx_idx.size)
    if n == 0:
        return float("nan")
    return float(np.mean(rx_idx[:n] != tx_idx[:n]))
