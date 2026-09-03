"""Blind equalisation - the Constant Modulus Algorithm.

1 Sep, Block B.

Godard's CMA drives every symbol towards a constant modulus without knowing
which symbol was sent, so it opens an eye closed by multipath before any
decisions exist. It is phase-blind - a rotated output has the same modulus -
which is why it runs between timing recovery and the Costas loop rather than
after it: it removes the ISI the carrier loop would otherwise have to survive,
and hands the rotation problem on unchanged.

`mma_equalise` below is the multi-modulus variant 16-QAM needs (2 Sep). CMA on
a QAM constellation converges to the wrong cost minimum because QAM has no
single modulus, so the two are kept as separate entry points and each scheme
asks for the one that fits it, rather than one function guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["CMAResult", "cma_equalise", "mma_equalise",
           "dispersion_constants"]


@dataclass
class CMAResult:
    symbols: np.ndarray
    taps: np.ndarray
    error: np.ndarray        # |y|^2 - R2 per symbol; the convergence trace
    converged: bool


def cma_equalise(
    symbols: np.ndarray,
    n_taps: int = 11,
    mu: float = 2e-3,
    R2: float = 1.0,
    warmup: int = 500,
    leak: float = 0.0,
) -> CMAResult:
    """Symbol-spaced CMA over the timing-recovered symbol stream.

    n_taps   odd; initialised to a centre spike so the equaliser starts as a
             pass-through and can only improve on it
    mu       step size. Too large and the modulus error never settles; the
             default is tuned for unit-power input at 8-20 dB
    R2       Godard dispersion constant, E|a|^4 / E|a|^2. 1.0 for any PSK
    warmup   symbols excluded from the convergence verdict
    leak     optional tap leakage, guards against slow tap blow-up on noise
    """
    y = np.asarray(symbols, dtype=np.complex128)
    if n_taps % 2 == 0:
        n_taps += 1
    if y.size < n_taps + warmup:
        return CMAResult(symbols=y.copy(), taps=np.array([1.0 + 0j]),
                         error=np.zeros(y.size), converged=False)

    # unit-power input keeps mu meaningful across files
    scale = np.sqrt(np.mean(np.abs(y) ** 2)) or 1.0
    y = y / scale

    w = np.zeros(n_taps, dtype=np.complex128)
    w[n_taps // 2] = 1.0
    centre = n_taps // 2

    n_out = y.size - n_taps + 1
    out = np.empty(n_out, dtype=np.complex128)
    err = np.empty(n_out, dtype=np.float64)

    for k in range(n_out):
        u = y[k : k + n_taps][::-1]          # newest sample first
        z = complex(np.dot(w, u))
        out[k] = z
        e = abs(z) ** 2 - R2
        err[k] = e
        w = (1.0 - leak) * w - mu * e * z * np.conj(u)

    tail = err[-min(2000, err.size):]
    head = err[warmup : warmup + min(2000, max(1, err.size - warmup))]
    converged = bool(np.mean(tail**2) <= np.mean(head**2) + 1e-12)

    # keep the output aligned with the input's symbol index
    return CMAResult(symbols=out * scale, taps=w, error=err, converged=converged)


def dispersion_constants(points: np.ndarray) -> tuple[float, float]:
    """Godard/MMA dispersion constants for a constellation.

    R2  = E|a|^4 / E|a|^2                    (CMA, one modulus)
    R2a = E[a_R^4] / E[a_R^2]                (MMA, per axis)

    Computed from the constellation rather than tabulated, so a new scheme
    cannot arrive with a stale constant attached to it.
    """
    a = np.asarray(points, dtype=np.complex128)
    a = a / (np.sqrt(np.mean(np.abs(a) ** 2)) or 1.0)
    r2 = float(np.mean(np.abs(a) ** 4) / max(np.mean(np.abs(a) ** 2), 1e-12))
    ar = np.real(a)
    r2a = float(np.mean(ar**4) / max(np.mean(ar**2), 1e-12))
    return r2, r2a


def mma_equalise(
    symbols: np.ndarray,
    points: np.ndarray,
    n_taps: int = 11,
    mu: float = 1e-3,
    warmup: int = 500,
) -> CMAResult:
    """Multi-modulus blind equalisation, for constellations CMA cannot handle.

    2 Sep - the equaliser 16-QAM needs.

    CMA drives every symbol towards one modulus. QAM has three, so CMA's cost
    function has no minimum at the right answer: it converges confidently to a
    constellation that is not the transmitted one, and it does so quietly.
    MMA splits the cost across the real and imaginary axes, each of which *is*
    single-modulus for a square QAM, and recovers the minimum.

    Like CMA it is phase-blind, so it still runs before the carrier loop and
    still leaves the rotation for S4 to resolve.
    """
    y = np.asarray(symbols, dtype=np.complex128)
    if n_taps % 2 == 0:
        n_taps += 1
    if y.size < n_taps + warmup:
        return CMAResult(symbols=y.copy(), taps=np.array([1.0 + 0j]),
                         error=np.zeros(y.size), converged=False)

    scale = np.sqrt(np.mean(np.abs(y) ** 2)) or 1.0
    y = y / scale
    _, r2a = dispersion_constants(points)

    w = np.zeros(n_taps, dtype=np.complex128)
    w[n_taps // 2] = 1.0

    n_out = y.size - n_taps + 1
    out = np.empty(n_out, dtype=np.complex128)
    err = np.empty(n_out, dtype=np.float64)

    for k in range(n_out):
        u = y[k : k + n_taps][::-1]
        z = complex(np.dot(w, u))
        out[k] = z
        er = z.real * (z.real * z.real - r2a)
        ei = z.imag * (z.imag * z.imag - r2a)
        e = complex(er, ei)
        err[k] = abs(e)
        w = w - mu * e * np.conj(u)

    tail = err[-min(2000, err.size):]
    head = err[warmup : warmup + min(2000, max(1, err.size - warmup))]
    converged = bool(np.mean(tail**2) <= np.mean(head**2) + 1e-12)
    return CMAResult(symbols=out * scale, taps=w, error=err, converged=converged)
