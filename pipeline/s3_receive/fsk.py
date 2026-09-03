"""Non-coherent FSK demodulation.

31 Aug, Block D: register the FSK non-coherent branch.

FSK carries its information in frequency, so a carrier phase reference buys
nothing - the energy in each tone bin is the whole decision statistic. That is
what 'non-coherent' means here, and it is why this branch shares the matched
filter and the registry interface with the PSK plug-ins but none of the
carrier-recovery machinery. No Costas loop, and therefore no phase ambiguity to
carry forward either.

Tone frequencies come from S2 when it has them. When they do not arrive, they
are measured from this file's own spectrum - which is blind estimation, not a
lookup in the answer key.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps_signal

__all__ = ["FSKResult", "estimate_tones", "fsk_demod_noncoherent"]


@dataclass
class FSKResult:
    indices: np.ndarray       # detected tone index per symbol
    metrics: np.ndarray       # (n_symbols, order) |correlation| - the soft input
    margin: np.ndarray        # best minus runner-up correlation, per symbol
    tones: np.ndarray         # normalised tone frequencies used, cycles/sample
    offset: int               # chosen integer sample offset of the symbol grid
    confidence: float         # mean normalised margin, 0..1


def estimate_tones(x: np.ndarray, order: int = 2, nperseg: int = 4096) -> np.ndarray:
    """Blind tone estimate: the `order` strongest separated peaks in the PSD."""
    nperseg = int(np.clip(max(256, len(x) // 8), 16, min(nperseg, len(x))))
    f, p = sps_signal.welch(x, fs=1.0, nperseg=nperseg, noverlap=nperseg // 2,
                            return_onesided=False, detrend=False)
    o = np.argsort(f)
    f, p = f[o], p[o]
    # a peak must stand clear of its neighbours by at least a bin group, or one
    # broad tone is reported twice
    min_sep = max(2, nperseg // 128)
    peaks, _ = sps_signal.find_peaks(p, distance=min_sep)
    if peaks.size < order:
        peaks = np.argsort(p)[-order:]
    best = peaks[np.argsort(p[peaks])[-order:]]
    return np.sort(f[best])


def fsk_demod_noncoherent(
    x: np.ndarray,
    sps: float,
    tones: np.ndarray | None = None,
    order: int = 2,
) -> FSKResult:
    """Correlate each symbol window against every tone and take the largest
    magnitude. Symbol timing is found by trying each integer offset and keeping
    the one with the widest average decision margin - with only a handful of
    offsets to try, a search is cheaper and steadier than a tracking loop, and
    unlike a loop it cannot drift."""
    x = np.asarray(x, dtype=np.complex128)
    n = int(round(sps))
    if n < 2:
        raise ValueError(f"FSK needs at least 2 samples/symbol, got {sps}")
    if tones is None:
        tones = estimate_tones(x, order)
    tones = np.asarray(tones, dtype=np.float64)

    t = np.arange(n)
    bank = np.exp(-2j * np.pi * np.outer(tones, t))     # order x n

    best: FSKResult | None = None
    for off in range(n):
        usable = (x.size - off) // n
        if usable < 16:
            continue
        w = x[off : off + usable * n].reshape(usable, n)
        corr = np.abs(w @ bank.T)                        # usable x order
        part = np.sort(corr, axis=1)
        margin = part[:, -1] - part[:, -2]
        denom = np.mean(part[:, -1]) or 1.0
        conf = float(np.mean(margin) / denom)
        if best is None or conf > best.confidence:
            best = FSKResult(indices=np.argmax(corr, axis=1), metrics=corr,
                             margin=margin, tones=tones, offset=off,
                             confidence=conf)

    if best is None:
        raise ValueError("record too short for FSK demodulation")
    return best
