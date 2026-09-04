"""pipeline/s1_detect.py

S1 -- signal detection: PSD, noise-floor/SNR estimate, occupied bandwidth,
spectrogram (the UI's waterfall source), burst detection with hysteresis.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import spectrogram as _spectrogram
from scipy.signal import welch


@dataclass
class S1Result:
    status: str                 # "ok" | "failed"
    fs: float
    snr_db: float | None
    noise_floor_db: float | None
    occupied_bw_hz: float | None
    bursts: list = field(default_factory=list)   # list of (start_idx, end_idx)
    psd_freqs: np.ndarray | None = None
    psd_db: np.ndarray | None = None
    spec_freqs: np.ndarray | None = None
    spec_times: np.ndarray | None = None
    spec_db: np.ndarray | None = None   # shape (n_freqs, n_times), for the waterfall
    reason: str | None = None


def compute_psd(iq: np.ndarray, fs: float, nperseg: int = 1024
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Welch PSD of the complex baseband signal, in dB."""
    freqs, psd = welch(iq, fs=fs, nperseg=min(nperseg, len(iq)),
                        return_onesided=False)
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)
    psd_db = 10 * np.log10(psd + 1e-30)
    return freqs, psd_db


def compute_spectrogram(iq: np.ndarray, fs: float, nperseg: int = 256,
                         noverlap: int | None = None
                         ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(freqs, times, spec_db) -- the waterfall's data source. Time-frequency
    power over the capture, complex baseband so two-sided (negative and
    positive frequencies both carry signal, unlike a real-valued input)."""
    nperseg = min(nperseg, len(iq))
    if noverlap is None:
        noverlap = nperseg // 2
    noverlap = min(noverlap, nperseg - 1) if nperseg > 1 else 0
    freqs, times, spec = _spectrogram(iq, fs=fs, nperseg=nperseg,
                                       noverlap=noverlap, return_onesided=False,
                                       mode="psd")
    freqs = np.fft.fftshift(freqs)
    spec = np.fft.fftshift(spec, axes=0)
    spec_db = 10 * np.log10(spec + 1e-30)
    return freqs, times, spec_db


def estimate_noise_floor(psd_db: np.ndarray, floor_percentile: float = 10.0
                          ) -> float:
    """Noise floor as a low percentile of the PSD -- robust to a single
    strong occupied band, since most bins in a typical capture are noise."""
    return float(np.percentile(psd_db, floor_percentile))


def estimate_snr(iq: np.ndarray, fs: float) -> tuple[float, float]:
    """(snr_db, noise_floor_db) as total signal power over total noise power
    across the full capture bandwidth -- matches the zoo's truth definition
    (mean(|signal|**2) / mean(|noise|**2), computed on the full array), not a
    peak-bin-vs-floor spectral ratio. The latter overstates SNR by the
    processing gain fs/occupied_bw (~7 dB at 8 sps here), since it compares a
    peak resolution-bin density to a per-bin noise floor rather than
    integrated power to integrated power.

    KNOWN GAP, measured not guessed (see tests/unit/test_s1_detect.py):
    this is validated to within ~0.7 dB of truth for bpsk/qpsk/8psk/16qam
    across 4-20 dB, and for 2fsk up to ~15 dB. It breaks for 4fsk (off by
    8-23 dB) and 2fsk at high SNR, because the zoo's FSK is unshaped CPFSK
    (modulation_index=1.0, no RRC) -- its spectral sidelobes decay so slowly
    that they never reach the true noise floor anywhere in the captured
    band (verified: even the single lowest PSD bin sits ~4 dB above the
    ideal floor for 4fsk at 10 dB). There is no clean noise-only region for
    a percentile-based floor to sample, so no percentile choice fixes it --
    checked at 1st through 50th percentile, all within 2 dB of each other
    and none within 4 dB of truth. A constant-modulus / moment-based
    estimator would be the right fix; not attempted here."""
    freqs, psd_db = compute_psd(iq, fs)
    noise_floor_db = estimate_noise_floor(psd_db)
    psd_lin = 10 ** (psd_db / 10.0)
    df = freqs[1] - freqs[0]
    total_power = float(np.sum(psd_lin) * df)
    noise_power = (10 ** (noise_floor_db / 10.0)) * fs
    signal_power = max(total_power - noise_power, 1e-30)
    snr_db = 10 * np.log10(signal_power / noise_power)
    return snr_db, noise_floor_db


def estimate_occupied_bw(iq: np.ndarray, fs: float, power_fraction: float = 0.99
                          ) -> float:
    """Bandwidth containing `power_fraction` of SIGNAL power (noise floor
    subtracted first). The naive version (cumulative power without
    subtracting the floor) reported 89-99% of fs for every modulation
    including PSK, because AWGN spread across the whole capture always
    contributes a near-constant background to the cumulative sum -- at
    10dB SNR the noise alone is ~9% of total power spread over the full
    band, which alone pushes a naive 99%-of-total-power threshold out to
    nearly the full band regardless of how narrow the signal actually is.
    Subtracting the estimated per-bin noise floor before integrating fixes
    it: measured ~30-32% of fs for RRC-shaped PSK/QAM at beta=0.35,
    sps=4 (theoretical (1+beta)/sps = 34%), vs 89%+ before."""
    freqs, psd_db = compute_psd(iq, fs)
    psd_lin = 10 ** (psd_db / 10.0)
    floor_db = estimate_noise_floor(psd_db)
    floor_lin = 10 ** (floor_db / 10.0)
    excess = np.clip(psd_lin - floor_lin, 0.0, None)
    cum = np.cumsum(excess)
    total = cum[-1]
    if total <= 0:
        return 0.0
    cum = cum / total
    lo_idx = int(np.searchsorted(cum, (1 - power_fraction) / 2))
    hi_idx = int(np.searchsorted(cum, 1 - (1 - power_fraction) / 2))
    lo_idx = max(0, min(lo_idx, len(freqs) - 1))
    hi_idx = max(0, min(hi_idx, len(freqs) - 1))
    return float(abs(freqs[hi_idx] - freqs[lo_idx]))


def detect_bursts(iq: np.ndarray, fs: float, window: int = 256,
                   high_thresh_db: float = 6.0, low_thresh_db: float = 3.0
                   ) -> list[tuple[int, int]]:
    """Burst detection via hysteresis on windowed power."""
    if len(iq) < window:
        return []

    n_windows = len(iq) // window
    power = np.array([
        10 * np.log10(np.mean(np.abs(iq[i * window:(i + 1) * window]) ** 2) + 1e-30)
        for i in range(n_windows)
    ])
    floor = float(np.percentile(power, 10.0))

    bursts = []
    in_burst = False
    start = 0
    for i, p in enumerate(power):
        rel = p - floor
        if not in_burst and rel > high_thresh_db:
            in_burst = True
            start = i
        elif in_burst and rel < low_thresh_db:
            in_burst = False
            bursts.append((start * window, i * window))
    if in_burst:
        bursts.append((start * window, n_windows * window))
    return bursts


def detect(iq: np.ndarray, fs: float) -> S1Result:
    """Top-level S1 entry point."""
    if iq is None or len(iq) == 0:
        return S1Result(status="failed", fs=fs, snr_db=None,
                         noise_floor_db=None, occupied_bw_hz=None,
                         reason="empty or missing IQ array")
    try:
        freqs, psd_db = compute_psd(iq, fs)
        snr_db, noise_floor_db = estimate_snr(iq, fs)
        occ_bw = estimate_occupied_bw(iq, fs)
        bursts = detect_bursts(iq, fs)
        spec_freqs, spec_times, spec_db = compute_spectrogram(iq, fs)
        return S1Result(status="ok", fs=fs, snr_db=snr_db,
                         noise_floor_db=noise_floor_db,
                         occupied_bw_hz=occ_bw, bursts=bursts,
                         psd_freqs=freqs, psd_db=psd_db,
                         spec_freqs=spec_freqs, spec_times=spec_times,
                         spec_db=spec_db)
    except Exception as e:
        return S1Result(status="failed", fs=fs, snr_db=None,
                         noise_floor_db=None, occupied_bw_hz=None,
                         reason=str(e))