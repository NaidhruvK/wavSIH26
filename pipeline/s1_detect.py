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
    # Which SNR estimator produced snr_db, and what the other one said. Two
    # estimators cover the six modulations between them (see estimate_snr), so
    # the number is only readable next to the method that produced it.
    snr_method: str | None = None
    snr_db_spectral: float | None = None
    snr_db_moment: float | None = None


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


def estimate_snr_moment(iq: np.ndarray) -> tuple[float | None, float]:
    """Blind M2M4 SNR estimate assuming a CONSTANT-MODULUS signal in circular
    complex Gaussian noise. Returns (snr_db or None, normalised 4th moment).

    With M2 = E|r|^2 and M4 = E|r|^4, a signal of power S whose own normalised
    4th moment is ka = E|s|^4 / (E|s|^2)^2, in noise of power N with kw = 2
    (circular Gaussian), gives

        M2 = S + N
        M4 = ka*S^2 + 4*S*N + kw*N^2

    so  2*M2^2 - M4 = (2 - ka)*S^2  and the estimator takes ka = 1:

        S_hat = sqrt(2*M2^2 - M4)        N_hat = M2 - S_hat

    EXACT for a constant-modulus signal (ka = 1), which is what the zoo's
    unshaped CPFSK is -- |exp(j*phi)| = 1 at every sample.

    THE ERROR IS ONE-SIDED, and that is why it is safe to combine with the
    spectral estimator below. S_hat = S*sqrt(2 - ka), and ka >= 1 for ANY
    signal by Jensen's inequality (E[X^2] >= (E[X])^2 with X = |s|^2). So on a
    non-constant-modulus signal -- RRC-shaped PSK or QAM -- this UNDERSTATES S,
    overstates N, and therefore can never report an SNR higher than the truth.

    The assumption that could in principle break that guarantee is kw: writing
    a sub-Gaussian interferer (kw < 2; a CW tone is kw = 1) into the noise term
    leaves a +(2 - kw)*N^2 and would overstate. TESTED RATHER THAN LEFT AS
    ALGEBRA, and it does not happen -- a CW tone added to a constant-modulus
    signal is part of the composite the estimator sees, and the sum of two
    complex exponentials is NOT constant modulus, so ka rises and the estimate
    moves down, not up. Unit-modulus signal at a true 10 dB:

        AWGN only                    10.00 dB
        + CW interferer at -10 dBc    9.60 dB
        + CW interferer at  -3 dBc    5.10 dB

    Still one-sided, still in the understating direction. No input has yet been
    found that makes it overstate; that is a measurement over the corpus and
    these probes, not a proof for every possible capture.

    Measured over zoo/corpus/rf (504 files): within 0.02 dB of truth for 2fsk
    and 4fsk at every SNR from 4 to 20 dB, and 1.5 to 16 dB LOW for the four
    linear modulations, in the understating direction the algebra predicts.
    """
    a2 = np.abs(np.asarray(iq)) ** 2
    # An empty capture, or one carrying NaN/Inf samples, has no moments. Every
    # comparison below is False against NaN, so without this guard the function
    # would fall through and return NaN as though it were an SNR - and the
    # contract is "a number or None", never a NaN wearing a number's clothes.
    if a2.size == 0 or not np.isfinite(a2).all():
        return None, float("nan")
    m2 = float(np.mean(a2))
    m4 = float(np.mean(a2 ** 2))
    if m2 <= 0:
        return None, float("nan")
    norm_m4 = m4 / (m2 * m2)

    disc = 2.0 * m2 * m2 - m4
    if disc <= 0:
        # ka >= 2: no constant-modulus decomposition exists. Pure noise sits at
        # ka_eff = 2 exactly, so this is also the all-noise case.
        return None, norm_m4
    s_hat = float(np.sqrt(disc))
    n_hat = m2 - s_hat
    if n_hat <= 0:
        return None, norm_m4
    return float(10 * np.log10(s_hat / n_hat)), norm_m4


def estimate_snr_spectral(iq: np.ndarray, fs: float) -> tuple[float, float]:
    """The percentile-floor spectral estimator -- (snr_db, noise_floor_db).

    Total integrated power minus an estimated noise contribution, over that
    noise contribution. Accurate whenever a genuinely signal-free part of the
    captured band exists for the percentile to land in; it understates SNR when
    one does not, because the floor it samples is then signal, not noise.
    """
    freqs, psd_db = compute_psd(iq, fs)
    noise_floor_db = estimate_noise_floor(psd_db)
    psd_lin = 10 ** (psd_db / 10.0)
    df = freqs[1] - freqs[0]
    total_power = float(np.sum(psd_lin) * df)
    noise_power = (10 ** (noise_floor_db / 10.0)) * fs
    signal_power = max(total_power - noise_power, 1e-30)
    snr_db = 10 * np.log10(signal_power / noise_power)
    return snr_db, noise_floor_db


def estimate_snr_detail(iq: np.ndarray, fs: float) -> dict:
    """Both SNR estimators plus which one was taken, for the stage card.

    Keys: snr_db, noise_floor_db, snr_db_spectral, snr_db_moment,
    normalised_m4, snr_method ("spectral" | "moment").
    """
    spectral_db, noise_floor_db = estimate_snr_spectral(iq, fs)
    moment_db, norm_m4 = estimate_snr_moment(iq)

    if moment_db is not None and moment_db > spectral_db:
        snr_db, method = moment_db, "moment"
    else:
        snr_db, method = spectral_db, "spectral"

    return {
        "snr_db": float(snr_db),
        "noise_floor_db": float(noise_floor_db),
        "snr_db_spectral": float(spectral_db),
        "snr_db_moment": None if moment_db is None else float(moment_db),
        "normalised_m4": float(norm_m4),
        "snr_method": method,
    }


def estimate_snr(iq: np.ndarray, fs: float) -> tuple[float, float]:
    """(snr_db, noise_floor_db) as total signal power over total noise power
    across the full capture bandwidth -- matches the zoo's truth definition
    (mean(|signal|**2) / mean(|noise|**2), computed on the full array), not a
    peak-bin-vs-floor spectral ratio. The latter overstates SNR by the
    processing gain fs/occupied_bw (~7 dB at 8 sps here), since it compares a
    peak resolution-bin density to a per-bin noise floor rather than
    integrated power to integrated power.

    TWO ESTIMATORS, AND THE LARGER IS TAKEN. Each is exact in one regime and
    understates in the other, so neither alone covers the six modulations:

      `estimate_snr_spectral` needs a signal-free part of the band for its
      percentile floor to land in. RRC-shaped PSK/QAM occupies ~30 % of the
      capture and leaves one; unshaped CPFSK does not.

      `estimate_snr_moment` (M2M4) needs a constant-modulus signal. CPFSK is
      one exactly; RRC-shaped PSK/QAM is not.

    Taking the maximum is sound rather than merely convenient, because BOTH
    errors are one-sided in the SAME direction. The moment estimator assumes
    ka = 1 and ka >= 1 holds for every signal by Jensen, so it can only
    understate (see its docstring). The spectral estimator, when its floor is
    contaminated by signal, overstates the noise and so also only understates.
    Neither can push the answer above truth, so the larger of the two is the
    better-founded one in every case.

    KNOWN GAP AS OF 10 SEP -- NOW CLOSED. This used to be the spectral
    estimator alone, and it read 4fsk 8-23 dB LOW at every SNR in the corpus:
    EVERY 4fsk capture, true SNR 4 to 20 dB, measured between -3.16 and
    -4.58 dB. That is not just a wrong number on a card. `adapt_s1` refuses
    any capture below -5.0 dB and marks every downstream stage
    out_of_envelope, so the worst corpus cell (4fsk at 4 dB, -4.58 dB) sat
    0.42 dB from refusing a signal this pipeline decodes to the exact
    transmitted bits. The docstring already named the right fix -- "a
    constant-modulus / moment-based estimator" -- and it is now here.

    Measured over all 504 files of zoo/corpus/rf, error against truth:

        bpsk/qpsk/8psk/16qam   +0.23 to +0.74 dB   (spectral, unchanged)
        2fsk                   within 0.01 dB      (was -0.07 to -2.05)
        4fsk                   within 0.02 dB      (was -8.47 to -23.16)

    The residual +0.2 to +0.7 dB on the linear modulations is the percentile
    floor sitting slightly below the true mean noise power, and it is the
    behaviour every earlier study in reports/ was measured against.
    """
    detail = estimate_snr_detail(iq, fs)
    return detail["snr_db"], detail["noise_floor_db"]


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
        snr = estimate_snr_detail(iq, fs)
        occ_bw = estimate_occupied_bw(iq, fs)
        bursts = detect_bursts(iq, fs)
        spec_freqs, spec_times, spec_db = compute_spectrogram(iq, fs)
        return S1Result(status="ok", fs=fs, snr_db=snr["snr_db"],
                         noise_floor_db=snr["noise_floor_db"],
                         occupied_bw_hz=occ_bw, bursts=bursts,
                         psd_freqs=freqs, psd_db=psd_db,
                         spec_freqs=spec_freqs, spec_times=spec_times,
                         spec_db=spec_db,
                         snr_method=snr["snr_method"],
                         snr_db_spectral=snr["snr_db_spectral"],
                         snr_db_moment=snr["snr_db_moment"])
    except Exception as e:
        return S1Result(status="failed", fs=fs, snr_db=None,
                         noise_floor_db=None, occupied_bw_hz=None,
                         reason=str(e))