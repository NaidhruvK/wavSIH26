"""pipeline/s2_estimate.py

S2 -- blind parameter estimation: symbol rate, carrier frequency offset,
FSK order. Everything here is blind by construction -- no function in this
module ever reads a truth file; every number comes from the IQ samples
alone. tests/unit/test_s2_estimate.py checks the numbers against truth,
which is a different thing from using truth to produce them.

Ported from tests/fixtures/local_s2.py (Nehal's throwaway stand-in, written
so S3's 1 Sep blindness gate had something other than truth to consume
before this module existed) plus a new FSK-order estimator. The ported
estimators are unchanged in method, verified before porting: symbol rate
24/24 exact (0.00% error) and CFO order-hint correct across the full RF
corpus at >=10dB.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks, medfilt

__all__ = ["S2Result", "estimate_symbol_rate", "estimate_symbol_rate_fsk",
           "estimate_cfo", "estimate_cfo_fsk", "estimate_fsk_order", "estimate"]


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
class S2Result:
    status: str            # "ok" | "failed"
    fs: float
    symbol_rate_hz: float | None
    symbol_rate_hypotheses: list = field(default_factory=list)   # [(rate_hz, score), ...] ranked
    cfo_hz: float | None = None
    cfo_hypotheses: list = field(default_factory=list)           # [(cfo_hz, order_m, score), ...] ranked, one per M
    cfo_alias_hypotheses: list = field(default_factory=list)     # [(cfo_hz, order_m, score), ...] EVERY alias per M, 0Hz guaranteed present
    fsk_order_hint: int | None = None
    fsk_order_hypotheses: list = field(default_factory=list)     # [(order, score), ...] ranked
    constant_envelope: bool | None = None
    envelope_cv: float | None = None      # raw std(|x|)/mean(|x|) constant_envelope was decided from
    symbol_rate_estimator: str | None = None   # "fsk" | "linear" - which one symbol_rate_hz came from
    symbol_rate_dominance: float | None = None # winning estimator's top peak over its own runner-up
    modulation_hypotheses: list = field(default_factory=list)    # [(class_name, prob), ...] ranked
    modulation_low_confidence: bool | None = None
    reason: str | None = None

    def as_params(self) -> dict:
        """The mapping S3 is handed. No truth key exists to leak."""
        return {"fs": self.fs, "symbol_rate": self.symbol_rate_hz, "cfo_hz": self.cfo_hz}


def _peak_dominance(hyps: list) -> float:
    """Top peak over the runner-up, within one estimator's own ranked list.

    The two symbol-rate estimators score peaks as height over the local median,
    but on DIFFERENT transforms - |x|^2 for the linear one, instantaneous
    frequency for the FSK one - so their scores are not comparable and the
    larger number does not mean the better answer. On the first off-air capture
    ever run through this pipeline the linear estimator reported 112.4 and the
    FSK one 34.3, and the FSK one was right to within 0.003%.

    This ratio is comparable because it is dimensionless and computed inside a
    single estimator against its own runner-up. It answers the question that
    actually distinguishes the two cases: did this transform find ONE line, or
    a forest of peaks all about the same height? On that same capture the
    linear list was 1590(112.4), 2030(108.5), 2989(105.1) - dominance 1.04, a
    forest - against the FSK list 9766(34.3), 8865(4.8), 12850(4.7) -
    dominance 7.1, one line.

    Returns inf for a single-hypothesis list (nothing to be beaten by) and 0.0
    for an empty one (no peak at all).
    """
    if not hyps:
        return 0.0
    if len(hyps) < 2:
        return float("inf")
    try:
        top = float(hyps[0][1])
        runner_up = float(hyps[1][1])
    except (TypeError, IndexError, ValueError):
        return 0.0
    if not np.isfinite(top) or not np.isfinite(runner_up) or runner_up <= 0.0:
        return float("inf") if top > 0.0 else 0.0
    return top / runner_up


def estimate_symbol_rate(x: np.ndarray, fs: float,
                          sps_range: tuple[float, float] = (2.5, 40.0),
                          nfft: int | None = None, n_hypotheses: int = 3
                          ) -> tuple[float, float, list[tuple[float, float]]]:
    """Symbol rate from the squared-magnitude spectrum.

    Linear modulation with non-zero excess bandwidth is cyclostationary at
    the symbol rate, so |x|^2 carries a discrete line there. Returns
    (rate_hz, score, hypotheses) -- hypotheses are the top in-band peaks,
    ranked by height over the local median, in case the strongest peak is
    a harmonic rather than the fundamental.
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
        return float("nan"), 0.0, []
    idx = np.flatnonzero(band)
    median = np.median(spec[idx]) + 1e-30

    peaks, _ = find_peaks(spec[idx], distance=max(1, idx.size // 50))
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(spec[idx]))])
    ranked = sorted(peaks, key=lambda p: spec[idx[p]], reverse=True)[:n_hypotheses]
    hyps = []
    for p in ranked:
        k = int(idx[p])
        kf = _parabolic_peak(spec, k)
        hyps.append((float(kf * fs / n), float(spec[k] / median)))

    rate, score = hyps[0]
    return rate, score, hyps


def estimate_symbol_rate_fsk(x: np.ndarray, fs: float,
                              sps_range: tuple[float, float] = (2.5, 40.0),
                              n_hypotheses: int = 3
                              ) -> tuple[float, float, list[tuple[float, float]]]:
    """Symbol rate for a constant-envelope signal.

    |x|^2 is flat for FSK, so the cyclostationary line the PSK estimator
    uses is not there. The instantaneous frequency is piecewise constant
    instead, and its derivative is a train of impulses at the symbol
    boundaries -- which puts the line back, in a different signal.
    """
    x = np.asarray(x, dtype=np.complex128)
    inst = np.diff(np.unwrap(np.angle(x)))
    inst = medfilt(inst, kernel_size=5)
    d = np.abs(np.diff(inst))
    d = d - np.mean(d)
    n = min(1 << 20, _next_pow2(d.size))
    spec = np.abs(np.fft.rfft(d * np.hanning(d.size), n))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    lo, hi = fs / sps_range[1], fs / sps_range[0]
    idx = np.flatnonzero((freqs >= lo) & (freqs <= hi))
    if idx.size == 0:
        return float("nan"), 0.0, []
    median = np.median(spec[idx]) + 1e-30

    peaks, _ = find_peaks(spec[idx], distance=max(1, idx.size // 50))
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(spec[idx]))])
    ranked = sorted(peaks, key=lambda p: spec[idx[p]], reverse=True)[:n_hypotheses]
    hyps = []
    for p in ranked:
        k = int(idx[p])
        hyps.append((float(_parabolic_peak(spec, k) * fs / n), float(spec[k] / median)))

    rate, score = hyps[0]
    return rate, score, hyps


def _instantaneous_freq_hz(x: np.ndarray, fs: float, med_k: int = 11) -> np.ndarray:
    inst = np.diff(np.unwrap(np.angle(x))) / (2 * np.pi) * fs
    return medfilt(inst, kernel_size=med_k)


def _fsk_tone_peaks(inst: np.ndarray, bins: int = 60, smooth_k: int = 7,
                     height_frac: float = 0.3
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(peak bin indices, bin centres, smoothed histogram) of the
    instantaneous-frequency histogram -- shared by estimate_fsk_order (peak
    count -> order) and estimate_cfo_fsk (peak positions -> CFO), so the
    two never see a different notion of "how many tones are there"."""
    hist, edges = np.histogram(inst, bins=bins)
    kernel = np.ones(smooth_k) / smooth_k
    smooth = np.convolve(hist, kernel, mode="same")
    peaks, _ = find_peaks(smooth, height=smooth.max() * height_frac,
                           distance=max(2, bins // 15))
    centers = 0.5 * (edges[:-1] + edges[1:])
    return peaks, centers, smooth


def estimate_cfo_fsk(x: np.ndarray, fs: float, candidates: tuple[int, ...] = (2, 4),
                      med_k: int = 11, bins: int = 60, smooth_k: int = 7,
                      height_frac: float = 0.3
                      ) -> tuple[float, int, float, list[tuple[float, int, float]],
                                 list[tuple[float, int, float]]]:
    """Carrier offset for constant-envelope (FSK) signals, by IF-tone centroid.

    5 Sep, reported by a teammate: estimate_cfo's M-th-power line search
    was being run on FSK signals too (estimate() called it unconditionally,
    regardless of constant_envelope), and it is the wrong tool there -- an
    M-FSK signal has no suppressed carrier for x**M to expose; it has M
    discrete tones, and raising it to a power just mixes tone-spacing
    products together. The result was every clean FSK file reporting
    ~symbol_rate/2, the exact same alias-trap shape as the bug fixed in
    426a780, but from an estimator that was never applicable to this
    signal class in the first place, not a demeaning bug in an applicable
    one. Measured effect, not just theory: this cost 4-FSK recovery
    outright (correct without the CFO estimate applied, wrong with it) at
    both 13 and 20dB, while 2-FSK happened to tolerate it.

    Fix: an M-FSK signal's tones are, by construction, an evenly-spaced
    ladder centred on zero IF (that centring is what "zero CFO" means for
    FSK) -- so a real CFO shifts every tone by the same amount, and the
    MEAN of the tone centres recovers exactly that shift, independent of
    how many bits landed on each tone in this particular window. Reuses
    _fsk_tone_peaks (same histogram estimate_fsk_order already computes,
    so the two never disagree on how many tones are present), then refines
    each coarse histogram-bin peak to the mean of the raw instantaneous-
    frequency samples nearest it -- the coarse bin alone is too wide
    (~fs/bins) to hit the sub-100Hz tolerance every other S2 gate uses.

    Measured on the real RF corpus (tests/unit/test_s2_estimate.py): worst
    case 85Hz across every 2fsk/4fsk file at >=10dB (was ~25000Hz, i.e.
    symbol_rate/2, before this fix)."""
    inst = _instantaneous_freq_hz(x, fs, med_k)
    peaks, centers, smooth = _fsk_tone_peaks(inst, bins, smooth_k, height_frac)
    default_order = candidates[0]

    if peaks.size == 0:
        return 0.0, default_order, 0.0, [], [(0.0, default_order, 0.0)]

    coarse = np.sort(centers[peaks])
    if coarse.size > 1:
        boundaries = (coarse[:-1] + coarse[1:]) / 2.0
        bucket = np.searchsorted(boundaries, inst)
        refined = np.array([
            float(inst[bucket == i].mean()) if np.any(bucket == i) else float(coarse[i])
            for i in range(coarse.size)
        ])
    else:
        refined = coarse

    cfo = float(np.mean(refined))
    n_peaks = int(peaks.size)
    order_hyps = sorted(
        ((c, 1.0 / (1.0 + abs(n_peaks - c))) for c in candidates),
        key=lambda h: h[1], reverse=True,
    )
    order_m = order_hyps[0][0]
    score = float(np.mean(smooth[peaks]) / (np.median(smooth) + 1e-30))

    hyps = [(cfo, order_m, score)]
    all_aliases = list(hyps)
    if abs(cfo) >= 1.0:
        all_aliases.append((0.0, order_m, 0.0))
    return cfo, order_m, score, hyps, all_aliases


def estimate_cfo(x: np.ndarray, fs: float, orders: tuple[int, ...] = (2, 4, 8)
                  ) -> tuple[float, int, float, list[tuple[float, int, float]],
                             list[tuple[float, int, float]]]:
    """Carrier offset by M-th power line search, ranked over every M tried.

    LINEAR (non-constant-envelope) modulations only -- see estimate_cfo_fsk
    for FSK. 5 Sep, reported by a teammate: estimate() was calling this
    unconditionally, on FSK captures too. It does not apply there: raising
    an M-FSK signal to the M-th power has no suppressed carrier to expose
    (FSK has M discrete tones, not one x**M-invariant carrier under a
    memoryless nonlinearity), so it locks onto a tone-spacing artifact
    instead -- every clean FSK file reported ~symbol_rate/2, the exact
    alias shape the 426a780 fix solved for PSK/QAM, but from an estimator
    that was never the right tool for this signal class to begin with.
    Now routed by constant_envelope in estimate() instead.

    Raising an M-PSK signal to the M-th power strips the data modulation
    and leaves a tone at M times the carrier offset. Whichever M produces
    the sharpest line is also a usable hint at the modulation order, which
    is why the full ranking is returned rather than just the winner -- S3
    can fall back to the second-best M if the top hint turns out wrong.

    FIXED 4 Sep -- classic M-th power spectral-line trap, caught by a
    teammate: this used to demean z (`z = z - np.mean(z)`) before the
    FFT, which nulls out exactly the bin the estimator most needs --
    the DC line is where the true tone sits when CFO genuinely is 0.
    With DC removed, argmax locks onto the next-strongest line instead,
    which for an M-th-power PSK spectrum is a symbol-rate-related
    cyclostationary artifact, not the carrier -- so every clean
    (zero-CFO) file reported a false CFO of Rs/M, confirmed on bpsk (Rs/2),
    qpsk (Rs/4) and 8psk (Rs/8) captures in the corpus. EVM doesn't catch
    this (a residual phase ramp doesn't move symbols off their decision
    regions much), but Stage 4's algebraic recovery does, since it isn't
    tolerant of any rotation at all. Fixed by not demeaning -- verified
    the true peak then lands at k=0 with a HIGHER score than any false
    alias, on every modulation tested, not just a plausible-looking one.

    Also now returns the FULL alias set per M (every `m`-th root of the
    detected line, not just the one closest to zero) rather than
    silently collapsing to a single guess, and explicitly guarantees a
    0 Hz candidate is present in that set even if no M's peak search
    happens to land there -- so a residual edge case still leaves 0 Hz
    available for S3/S4 to try, rather than depending entirely on the
    peak search being right.
    """
    x = np.asarray(x, dtype=np.complex128)
    x = x / (np.sqrt(np.mean(np.abs(x) ** 2)) or 1.0)
    n = min(1 << 20, _next_pow2(x.size))

    hyps: list[tuple[float, int, float]] = []
    all_aliases: list[tuple[float, int, float]] = []
    for m in orders:
        z = x**m
        spec = np.abs(np.fft.fft(z * np.hanning(z.size), n))
        k = int(np.argmax(spec))
        score = float(spec[k] / (np.median(spec) + 1e-30))
        kf = _parabolic_peak(spec, k)
        f_m = kf / n
        if f_m > 0.5:
            f_m -= 1.0
        # the line sits at m * cfo modulo 1, so fold to EVERY alias --
        # all m of them are exposed, not just the one closest to zero
        cands = (f_m + np.arange(m)) / m
        cands = np.where(cands > 0.5 / m * m, cands - 1.0, cands)
        for c in cands:
            all_aliases.append((float(c) * fs, m, score))
        cfo = float(cands[int(np.argmin(np.abs(cands)))])
        hyps.append((cfo * fs, m, score))

    if not any(abs(c) < 1.0 for c, _m, _s in all_aliases):
        all_aliases.append((0.0, orders[0], 0.0))

    hyps.sort(key=lambda h: h[2], reverse=True)
    all_aliases.sort(key=lambda h: h[2], reverse=True)
    best_cfo, best_m, best_score = hyps[0]
    return best_cfo, best_m, best_score, hyps, all_aliases


def estimate_fsk_order(x: np.ndarray, fs: float, candidates: tuple[int, ...] = (2, 4),
                        med_k: int = 11, bins: int = 60, smooth_k: int = 7,
                        height_frac: float = 0.3
                        ) -> tuple[int, float, list[tuple[int, float]]]:
    """FSK order from the instantaneous-frequency histogram.

    An M-FSK signal's IF sits at one of M discrete tones almost all the
    time (transition samples between tones are the exception, not the
    rule), so a histogram of IF values has M modes. Counted via a smoothed,
    median-filtered histogram and scipy's peak finder, then matched to the
    nearest registered order.

    Measured on the full RF corpus (tests/unit/test_s2_estimate.py):
    11/12 exact (2fsk and 4fsk, 4-20 dB) -- the one miss is 4fsk at 4 dB,
    below every other stated target floor in this project (all gates are
    anchored at >=10 dB). Median filter kernel and height threshold were
    tuned by sweeping against this corpus, not guessed.
    """
    x = np.asarray(x, dtype=np.complex128)
    inst = _instantaneous_freq_hz(x, fs, med_k)
    peaks, _centers, _smooth = _fsk_tone_peaks(inst, bins, smooth_k, height_frac)
    n_peaks = max(len(peaks), 1)

    hyps = sorted(
        ((c, 1.0 / (1.0 + abs(n_peaks - c))) for c in candidates),
        key=lambda h: h[1], reverse=True,
    )
    order, score = hyps[0]
    return order, score, hyps


def estimate(iq: np.ndarray, fs: float, constant_envelope: bool | None = None,
             classify: bool = True) -> S2Result:
    """Top-level S2 entry point.

    constant_envelope=None picks the estimator by measuring the envelope
    variation, which is itself blind -- the trained classifier (3 Sep)
    makes the same call internally too; this is what runs before the
    classifier has anything to say (e.g. while deciding which resample
    ratio to hand it).

    7 Sep, Nehal: this routing statistic (std(|x|)/mean(|x|) < 0.25) is an
    SNR test wearing a modulation test's name -- measured identically for
    2fsk and 4fsk to three decimal places at every SNR, and it tracks
    1/sqrt(2*SNR_linear) almost exactly. It is not choosing between
    modulations; it is choosing between "SNR above ~9dB" and not, and below
    that line it silently misroutes FSK to the linear CFO path with no
    failure signal (status stays "ok"). His ask, explicitly not a redesign:
    a decision that is really an SNR test should say so in the result
    rather than only in a report a caller has to already know to read.
    envelope_cv below is that -- the raw statistic, always populated (even
    when constant_envelope is passed in explicitly and this function never
    had to decide anything from it), so any consumer can apply its own
    policy instead of trusting `constant_envelope`/`cfo_hz` blind. Not
    resolved here: what threshold on envelope_cv should make a caller
    distrust cfo_hz is exactly the crossover reports/s2_envelope.md already
    proved has no single right answer -- surfacing the number is the
    honest move, inventing a second undocumented threshold is not.

    classify=True runs the trained modulation classifier in-process
    (models.classify, loaded once at its own import, not retrained here)
    on S2's own symbol-rate estimate -- never on truth. Imported lazily,
    inside the call, because models.features imports estimate_symbol_rate
    from this module: importing models.classify at module level here
    would be circular. classify=False skips it (used by tests that don't
    care about classification and don't want the model-load cost).
    """
    if iq is None or len(iq) < 16:
        return S2Result(status="failed", fs=fs, symbol_rate_hz=None,
                         reason="capture too short to estimate anything")
    try:
        a = np.abs(iq)
        envelope_cv = float(np.std(a) / (np.mean(a) + 1e-30))
        if constant_envelope is None:
            constant_envelope = bool(envelope_cv < 0.25)

        # SYMBOL RATE: run both estimators and keep the one whose own peak
        # stood out, rather than the one envelope_cv nominated. See
        # _peak_dominance for why that statistic is comparable across the two
        # transforms and why this is not a second threshold on envelope_cv.
        #
        # Measured over all 252 captures in zoo/corpus/rf, rate within 1% of
        # truth: envelope_cv routing 224/252 (88.9%), dominance routing 252/252
        # (100.0%), zero regressions and 28 rescues. Every rescue is 2FSK or
        # 4FSK at 4 dB or 8 dB - the exact population the 7 Sep note predicted,
        # where noise lifts envelope_cv over 0.25 and a genuine FSK capture is
        # handed to the linear estimator with status still "ok".
        #
        # CFO ROUTING IS DELIBERATELY UNCHANGED. This study measured symbol
        # rate and nothing else, so constant_envelope still selects the CFO
        # estimator and the FSK order search. The two can now disagree; when
        # they do, symbol_rate_estimator says so rather than leaving a caller
        # to infer it from constant_envelope, which no longer implies it.
        lin_rate, lin_score, lin_hyps = estimate_symbol_rate(iq, fs)
        fsk_rate, fsk_score, fsk_hyps = estimate_symbol_rate_fsk(iq, fs)
        lin_dom = _peak_dominance(lin_hyps)
        fsk_dom = _peak_dominance(fsk_hyps)

        if fsk_dom > lin_dom:
            rate, rate_score, rate_hyps = fsk_rate, fsk_score, fsk_hyps
            rate_estimator, rate_dominance = "fsk", fsk_dom
        else:
            rate, rate_score, rate_hyps = lin_rate, lin_score, lin_hyps
            rate_estimator, rate_dominance = "linear", lin_dom

        if constant_envelope:
            cfo, order_m, cfo_score, cfo_hyps, cfo_alias_hyps = estimate_cfo_fsk(iq, fs)
        else:
            cfo, order_m, cfo_score, cfo_hyps, cfo_alias_hyps = estimate_cfo(iq, fs)

        fsk_order = fsk_order_score = None
        fsk_order_hyps: list = []
        if constant_envelope:
            fsk_order, fsk_order_score, fsk_order_hyps = estimate_fsk_order(iq, fs)

        mod_hyps: list = []
        mod_low_conf = None
        if classify:
            try:
                from models.classify import classify as _classify
                result = _classify(iq, fs, rate)
                mod_hyps = result["hypotheses"]
                mod_low_conf = result["low_confidence"]
            except Exception:
                # model not trained in this checkout (FileNotFoundError), or
                # classification itself failed on this capture -- either way,
                # degrade to no classification rather than lose the rate/cfo
                # estimate already computed above. 9 Sep guard pass: this used
                # to catch only FileNotFoundError, so any other exception from
                # classify() (a corrupt model file, a feature-extraction edge
                # case on adversarial input) fell through to estimate()'s
                # outer handler and reported the WHOLE S2 result as failed,
                # discarding a valid rate/cfo for a classifier-only problem.
                pass

        return S2Result(status="ok", fs=fs, symbol_rate_hz=rate,
                         symbol_rate_hypotheses=rate_hyps, cfo_hz=cfo,
                         cfo_hypotheses=cfo_hyps,
                         cfo_alias_hypotheses=cfo_alias_hyps, fsk_order_hint=fsk_order,
                         fsk_order_hypotheses=fsk_order_hyps,
                         constant_envelope=constant_envelope,
                         envelope_cv=envelope_cv,
                         symbol_rate_estimator=rate_estimator,
                         symbol_rate_dominance=rate_dominance,
                         modulation_hypotheses=mod_hyps,
                         modulation_low_confidence=mod_low_conf)
    except Exception as e:
        return S2Result(status="failed", fs=fs, symbol_rate_hz=None, reason=str(e))
