"""LOCAL STAND-IN for Dheeraj's S2 - dies when pipeline/s2_estimate.py lands.

S3's 1 Sep gate is that the receiver stops reading the answers. Proving that
needs something other than truth to feed it, and on 1 Sep the real S2 does not
exist in this working copy yet. So the harness carries a throwaway blind
estimator: squared-magnitude spectrum for the symbol rate, M-th power line
search for the carrier offset. These are the standard estimators Dheeraj is
building properly - this version exists only to make S3's blindness testable
today, and its numbers are never reported anywhere.

Death condition: pipeline/s2_estimate.py exists. Delete this file and call the
real stage.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["S2Estimate", "estimate_blind", "estimate_symbol_rate",
           "estimate_symbol_rate_fsk", "estimate_cfo"]


def _next_pow2(n: int) -> int:
    return 1 << (int(n) - 1).bit_length()


def _parabolic_peak(mag: np.ndarray, k: int) -> float:
    """Sub-bin peak location by parabolic interpolation on three log points."""
    if k <= 0 or k >= mag.size - 1:
        return float(k)
    a, b, c = np.log(mag[k - 1] + 1e-30), np.log(mag[k] + 1e-30), np.log(mag[k + 1] + 1e-30)
    denom = a - 2.0 * b + c
    if abs(denom) < 1e-30:
        return float(k)
    return float(k) + 0.5 * (a - c) / denom


@dataclass
class S2Estimate:
    fs: float
    symbol_rate: float
    cfo_hz: float
    order_hint: int
    symbol_rate_score: float
    cfo_score: float

    def as_params(self) -> dict:
        """Exactly the mapping S3 is handed. No truth key exists to leak."""
        return {"fs": self.fs, "symbol_rate": self.symbol_rate,
                "cfo_hz": self.cfo_hz}


def estimate_symbol_rate(x: np.ndarray, fs: float,
                         sps_range: tuple[float, float] = (2.5, 40.0),
                         nfft: int | None = None) -> tuple[float, float]:
    """Symbol rate from the squared-magnitude spectrum.

    Linear modulation with non-zero excess bandwidth is cyclostationary at the
    symbol rate, so |x|^2 carries a discrete line there. Returns (rate_hz, score)
    where score is the line's height over the local median.
    """
    x = np.asarray(x, dtype=np.complex128)
    y = np.abs(x) ** 2
    y = y - np.mean(y)
    n = nfft or min(1 << 20, _next_pow2(y.size))
    spec = np.abs(np.fft.rfft(y * np.hanning(y.size), n))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    lo, hi = fs / sps_range[1], fs / sps_range[0]
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any():
        return float("nan"), 0.0
    idx = np.flatnonzero(band)
    k = idx[int(np.argmax(spec[idx]))]
    kf = _parabolic_peak(spec, int(k))
    rate = kf * fs / n
    score = float(spec[k] / (np.median(spec[idx]) + 1e-30))
    return float(rate), score


def estimate_symbol_rate_fsk(x: np.ndarray, fs: float,
                             sps_range: tuple[float, float] = (2.5, 40.0)
                             ) -> tuple[float, float]:
    """Symbol rate for a constant-envelope signal.

    |x|^2 is flat for FSK, so the cyclostationary line the PSK estimator uses is
    not there. The instantaneous frequency is piecewise constant instead, and
    its derivative is a train of impulses at the symbol boundaries - which puts
    the line back, in a different signal.
    """
    from scipy.signal import medfilt

    x = np.asarray(x, dtype=np.complex128)
    inst = np.diff(np.unwrap(np.angle(x)))
    # the IF of a noisy FSK signal is spiky; a short median filter removes the
    # spikes without rounding off the symbol transitions, which a low-pass would
    inst = medfilt(inst, kernel_size=5)
    d = np.abs(np.diff(inst))
    d = d - np.mean(d)
    n = min(1 << 20, _next_pow2(d.size))
    spec = np.abs(np.fft.rfft(d * np.hanning(d.size), n))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    lo, hi = fs / sps_range[1], fs / sps_range[0]
    idx = np.flatnonzero((freqs >= lo) & (freqs <= hi))
    if idx.size == 0:
        return float("nan"), 0.0
    k = idx[int(np.argmax(spec[idx]))]
    rate = _parabolic_peak(spec, int(k)) * fs / n
    score = float(spec[k] / (np.median(spec[idx]) + 1e-30))
    return float(rate), score


def estimate_cfo(x: np.ndarray, fs: float,
                 orders: tuple[int, ...] = (2, 4, 8)) -> tuple[float, int, float]:
    """Carrier offset by M-th power line search.

    Raising an M-PSK signal to the M-th power strips the data modulation and
    leaves a tone at M times the carrier offset. Whichever M produces the
    sharpest line is also a usable hint at the modulation order, which is why it
    is returned - S3 does not have to trust it, and does not use it.
    """
    x = np.asarray(x, dtype=np.complex128)
    x = x / (np.sqrt(np.mean(np.abs(x) ** 2)) or 1.0)
    n = min(1 << 20, _next_pow2(x.size))

    best = (0.0, orders[0], 0.0)
    for m in orders:
        z = x**m
        z = z - np.mean(z)
        spec = np.abs(np.fft.fft(z * np.hanning(z.size), n))
        k = int(np.argmax(spec))
        score = float(spec[k] / (np.median(spec) + 1e-30))
        kf = _parabolic_peak(spec, k)
        f_m = kf / n
        if f_m > 0.5:
            f_m -= 1.0
        # the line sits at m * cfo modulo 1, so fold to the smallest offset
        cands = (f_m + np.arange(m)) / m
        cands = np.where(cands > 0.5 / m * m, cands - 1.0, cands)
        cfo = float(cands[int(np.argmin(np.abs(cands)))])
        if score > best[2]:
            best = (cfo * fs, m, score)
    return best


def estimate_blind(x: np.ndarray, fs: float, constant_envelope: bool | None = None
                   ) -> S2Estimate:
    """constant_envelope=None picks the estimator by measuring the envelope
    variation, which is itself blind - the real S2 makes the same call from its
    classifier output."""
    if constant_envelope is None:
        a = np.abs(np.asarray(x))
        constant_envelope = bool(np.std(a) / (np.mean(a) + 1e-30) < 0.25)
    if constant_envelope:
        rate, rate_score = estimate_symbol_rate_fsk(x, fs)
    else:
        rate, rate_score = estimate_symbol_rate(x, fs)
    cfo, order_hint, cfo_score = estimate_cfo(x, fs)
    return S2Estimate(fs=fs, symbol_rate=rate, cfo_hz=cfo,
                      order_hint=order_hint, symbol_rate_score=rate_score,
                      cfo_score=cfo_score)
