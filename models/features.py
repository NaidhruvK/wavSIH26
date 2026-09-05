"""models/features.py

The 12-feature extractor for 6-class modulation classification (2 Sep
column), plus the deterministic baseline rule the trained model has to
beat (3 Sep). Everything here runs on a single fixed-length complex
baseband window and never touches truth.

Reuses Anvith's pipeline.s3_receive.cumulants for the 7 higher-order
cumulants -- same estimator the UI shows beside its theoretical value, so
a measured feature here and a measured value there can never disagree with
each other by definition. theoretical_cumulants() per registered
modulation gives the NOISELESS ratios, and they hold up empirically as
ratios, not as absolute thresholds -- measured on the real training set
(models/dataset_train.csv), not assumed:

    theoretical |C42|: bpsk=2.00 qpsk=8psk=1.00 16qam=0.68 fsk~0.95-0.98
    measured @10dB SNR (median): bpsk=1.338 qpsk=8psk=0.661 16qam=0.438

The ratios match closely (qpsk/16qam: theory 1.47, measured 1.51), but
the ABSOLUTE scale shrinks hard with noise -- roughly 4x smaller at 0dB
than at 20dB for every class alike -- because normalise_power() divides
by total (signal+noise) power, and a finite-sample 4th-order cumulant
estimate is well known to be SNR-biased this way (the same effect blind
M2M4 SNR estimators exploit deliberately). A genuinely fixed |C42|
threshold therefore cannot span the full 0-20dB training grid; it is
calibrated at the 10dB medians instead, since every gate and target in
this project is anchored at >=10dB. Measured consequence, not
hidden: baseline accuracy degrades at 0-5dB and is solid from 10dB up
(see tests/unit/test_features.py for the numbers).

|C42| alone separates {bpsk} / {16qam} / {qpsk,8psk,2fsk,4fsk}. The last
group is separated by IF-histogram peak count instead (measured on the
real RF corpus, not assumed): PSK/QAM show exactly 1 peak (no discrete
IF tones), 2fsk shows 2, 4fsk shows 4. qpsk and 8psk are NOT separated by
either feature -- both land in the same leaf. That is a known, deliberate
gap in the baseline (see BASELINE_KNOWN_GAP below), not an oversight: the
baseline only gets |C42| and peak-count by spec, and no combination of
those two features tells qpsk from 8psk apart (both have identical
theoretical |C40|=|C41|=|C60|=0 too, at this cumulant order -- the
telling difference is |C40| magnitude: qpsk=1.0, 8psk=0.0 -- which the
trained model gets to use and the baseline deliberately does not).

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, medfilt

from pipeline.s1_detect import estimate_occupied_bw
from pipeline.s2_estimate import estimate_symbol_rate, estimate_symbol_rate_fsk
from pipeline.s3_receive.cumulants import CUMULANT_KEYS, cumulants, normalise_power

FEATURE_NAMES = [
    "abs_C20", "abs_C21", "abs_C40", "abs_C41", "abs_C42", "abs_C60", "abs_C63",
    "occupied_bw_ratio", "if_hist_kurtosis", "if_hist_peak_count",
    "envelope_variance", "phase_diff_entropy",
]

BASELINE_KNOWN_GAP = "qpsk vs 8psk: identical under |C42| + peak-count, baseline cannot distinguish them"


def _instantaneous_freq_hz(x: np.ndarray, fs: float, med_k: int = 11) -> np.ndarray:
    inst = np.diff(np.unwrap(np.angle(x))) / (2 * np.pi) * fs
    return medfilt(inst, kernel_size=med_k)


def if_histogram_features(x: np.ndarray, fs: float, bins: int = 60,
                           smooth_k: int = 7, height_frac: float = 0.3
                           ) -> tuple[float, int]:
    """(kurtosis, peak_count) of the instantaneous-frequency histogram.

    Tone-counting only means something for a constant-envelope signal --
    that is the whole premise behind IF carrying discrete plateaus in the
    first place (see pipeline.s2_estimate.estimate_fsk_order's docstring).
    Measured on a short window (4096 samples/8sps, the size this actually
    runs on -- NOT the much longer full captures S2 validated against):
    applying the peak-finder to shaped PSK/QAM anyway (no envelope gate)
    returns garbage, 1-6 spurious peaks depending on seed and tuning, none
    of it separable from 2fsk/4fsk's real 2/4. Gating on envelope
    constancy first fixes it -- non-constant-envelope signals report
    peak_count=1 by definition rather than running a peak-finder on a
    signal it was never meaningful for.

    5 Sep: tried removing this gate to fix 2fsk/4fsk sitting at 0%
    live-classification accuracy below 10dB (see reports/s2_envelope.md),
    on the theory that envelope_variance is already its own feature so
    the classifier could learn the right cutoff contextually instead of a
    fixed one. Measured, not assumed, and reverted: ungated,
    test_if_hist_peak_count_matches_scheme started failing at 15dB
    (qpsk/8psk/16qam picking up spurious peaks even well above the
    original gate's design point), test_baseline_macro_f1_on_training_set
    dropped below its regression floor, and the retrained classifier
    regressed a previously-solid 4fsk-at-15dB case to 2fsk. Root cause is
    the same crossover proven for s2_estimate's own 0.25 threshold in
    reports/s2_envelope_study.py: FSK's noise-induced envelope variance at
    4dB is numerically closer to "non-constant" than clean 20dB PSK/QAM's
    is, so no single fixed threshold -- including "no threshold" -- can
    get both ends of the SNR range right off this one statistic. Gate
    restored; the 4-8dB gap stays open and documented rather than traded
    for a >=10dB regression the night before CORE LOCK."""
    inst = _instantaneous_freq_hz(x, fs, med_k=1 if x.size < 32 else 11)
    if inst.size < 4 or np.allclose(inst, inst[0]):
        return 0.0, 1

    m = np.mean(inst)
    s = np.std(inst)
    kurt = float(np.mean(((inst - m) / s) ** 4) - 3.0) if s > 0 else 0.0

    if envelope_variance(x) >= 0.05:
        return kurt, 1

    hist, edges = np.histogram(inst, bins=bins)
    kernel = np.ones(smooth_k) / smooth_k
    smooth = np.convolve(hist, kernel, mode="same")
    peaks, _ = find_peaks(smooth, height=max(smooth.max() * height_frac, 1e-9),
                           distance=max(2, bins // 15))
    return kurt, max(len(peaks), 1)


def envelope_variance(x: np.ndarray) -> float:
    """var(|x|) / mean(|x|)**2 -- near 0 for constant-envelope FSK, larger
    for RRC-shaped PSK/QAM whose envelope fluctuates with the pulse shape."""
    a = np.abs(x)
    mean = np.mean(a)
    return float(np.var(a) / (mean**2 + 1e-30))


def phase_diff_entropy(x: np.ndarray, bins: int = 32) -> float:
    """Shannon entropy (bits) of the histogram of consecutive phase
    differences. A discrete symbol alphabet clusters phase differences
    into a few bins (low entropy); noise or a dense constellation spreads
    them out (higher entropy)."""
    dphi = np.angle(x[1:] * np.conj(x[:-1]))
    hist, _ = np.histogram(dphi, bins=bins, range=(-np.pi, np.pi))
    p = hist / (hist.sum() + 1e-30)
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def occupied_bw_ratio(x: np.ndarray, fs: float, constant_envelope: bool) -> float:
    """occupied bandwidth / estimated symbol rate. Reuses S1's (fixed,
    noise-subtracted) occupied_bw and S2's symbol-rate estimators rather
    than reimplementing either."""
    bw = estimate_occupied_bw(x, fs)
    if constant_envelope:
        rate, _score, _hyps = estimate_symbol_rate_fsk(x, fs)
    else:
        rate, _score, _hyps = estimate_symbol_rate(x, fs)
    if not np.isfinite(rate) or rate <= 0:
        return 0.0
    return float(bw / rate)


@dataclass
class FeatureVector:
    values: np.ndarray   # shape (12,), order == FEATURE_NAMES
    names: list

    def as_dict(self) -> dict:
        return dict(zip(self.names, self.values.tolist()))


def extract_features(window: np.ndarray, fs: float) -> FeatureVector:
    """The twelve features, in FEATURE_NAMES order. `window` should already
    be power-normalised and resampled to a fixed samples/symbol by the
    caller (the training/inference pipeline does this once per window,
    not per feature, so every feature sees the same normalisation)."""
    x = np.asarray(window, dtype=np.complex128)

    c = cumulants(x, normalise=True)
    cum_feats = [abs(c[k]) for k in CUMULANT_KEYS]

    kurt, peak_count = if_histogram_features(x, fs)
    env_var = envelope_variance(x)
    constant_envelope = env_var < 0.05
    bw_ratio = occupied_bw_ratio(x, fs, constant_envelope)
    entropy = phase_diff_entropy(x)

    values = np.array(cum_feats + [bw_ratio, kurt, float(peak_count), env_var, entropy])
    return FeatureVector(values=values, names=list(FEATURE_NAMES))


def baseline_predict(features: FeatureVector) -> str:
    """Deterministic decision tree on |C42| and IF-peak-count only, fixed
    thresholds calibrated at the 10dB measured medians (see module
    docstring) -- this project's targets are anchored at >=10dB
    everywhere else, and a noiseless-theory threshold does not survive
    real noise (measured, not assumed). This is the number the trained
    model has to beat -- implemented first, on purpose, per the plan.
    Known gap: cannot separate qpsk from 8psk (see BASELINE_KNOWN_GAP);
    returns "qpsk" for that leaf, an arbitrary tie-break, not a real
    answer."""
    d = features.as_dict()
    c42 = d["abs_C42"]
    peaks = d["if_hist_peak_count"]

    if peaks >= 4:
        return "4fsk"
    if peaks >= 2:
        return "2fsk"
    if c42 > 1.0:
        return "bpsk"
    if c42 < 0.55:
        return "16qam"
    return "qpsk"
