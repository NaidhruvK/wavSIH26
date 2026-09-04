"""tests/unit/test_features.py"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import f1_score

from models.features import (
    FEATURE_NAMES,
    FeatureVector,
    baseline_predict,
    envelope_variance,
    extract_features,
    phase_diff_entropy,
)
from zoo.rf import through_channel

DATASET_CSV = Path(__file__).resolve().parents[2] / "models" / "dataset_train.csv"


def _load_dataset():
    if not DATASET_CSV.exists():
        pytest.skip(f"{DATASET_CSV} missing -- run python -m models.build_dataset first")
    rows = []
    with DATASET_CSV.open() as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _make_window(scheme: str, snr_db: float, seed: int, sps: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, size=3000, dtype=np.uint8)
    iq, _ = through_channel(bits, scheme, sps=sps, beta=0.35, snr_db=snr_db,
                             cfo_norm=0.0, phase_rad=0.4, timing_offset_sym=0.0,
                             seed=seed)
    start = (iq.size - 4096) // 2
    w = iq[start:start + 4096]
    p = np.sqrt(np.mean(np.abs(w) ** 2))
    return w / (p if p > 0 else 1.0)


def test_extract_features_shape_and_order():
    w = _make_window("qpsk", 15.0, seed=1)
    fv = extract_features(w, fs=200_000.0)
    assert fv.values.shape == (12,)
    assert fv.names == FEATURE_NAMES
    assert np.isfinite(fv.values).all()


def test_extract_features_never_takes_truth():
    import inspect
    params = list(inspect.signature(extract_features).parameters)
    assert params == ["window", "fs"]


@pytest.mark.parametrize("scheme,expected_peaks", [
    ("bpsk", 1), ("qpsk", 1), ("8psk", 1), ("16qam", 1), ("2fsk", 2), ("4fsk", 4),
])
def test_if_hist_peak_count_matches_scheme(scheme, expected_peaks):
    """Measured on the real corpus (see models/features.py docstring):
    PSK/QAM always show 1 IF-histogram peak, 2fsk shows 2, 4fsk shows 4.
    This is the feature the baseline leans on to split FSK from linear
    modulations."""
    w = _make_window(scheme, 15.0, seed=42)
    fv = extract_features(w, fs=200_000.0)
    assert fv.as_dict()["if_hist_peak_count"] == expected_peaks


def test_envelope_variance_lower_for_fsk_than_qam():
    """FSK is constant-envelope by construction; RRC-shaped QAM is not."""
    fsk = _make_window("4fsk", 20.0, seed=7)
    qam = _make_window("16qam", 20.0, seed=7)
    assert envelope_variance(fsk) < envelope_variance(qam)


def test_phase_diff_entropy_is_bounded():
    w = _make_window("bpsk", 15.0, seed=3)
    e = phase_diff_entropy(w)
    assert 0.0 <= e <= 5.0   # log2(32 bins) = 5 is the hard ceiling


def test_cumulant_ratios_hold_at_high_snr():
    """Theoretical |C42| ratios (bpsk:qpsk:16qam = 2.00:1.00:0.68) survive
    as RATIOS even though the absolute scale is noise-biased (see module
    docstring) -- checked at 20dB where the bias is smallest."""
    bpsk = extract_features(_make_window("bpsk", 20.0, seed=11), 200_000.0).as_dict()
    qpsk = extract_features(_make_window("qpsk", 20.0, seed=11), 200_000.0).as_dict()
    qam16 = extract_features(_make_window("16qam", 20.0, seed=11), 200_000.0).as_dict()
    assert bpsk["abs_C42"] > qpsk["abs_C42"] > qam16["abs_C42"]


def test_baseline_predict_structural():
    """The known gap, exercised directly: qpsk and 8psk are identical
    under |C42| + peak-count, so the baseline must return the same class
    for both given the same feature vector."""
    fv = FeatureVector(values=np.array([0, 1, 0, 0, 0.66, 0, 4, 1.3, 0, 1, 0.1, 3]),
                        names=FEATURE_NAMES)
    assert baseline_predict(fv) == "qpsk"


def test_baseline_macro_f1_on_training_set():
    """Pins the 2 Sep gate: baseline macro-F1 reported and written down.
    Regenerate models/dataset_train.csv (python -m models.build_dataset)
    if this ever needs updating -- don't hand-edit the CSV."""
    rows = _load_dataset()
    y_true = [r["scheme"] for r in rows]
    y_pred = []
    for r in rows:
        vals = np.array([float(r[k]) for k in FEATURE_NAMES])
        y_pred.append(baseline_predict(FeatureVector(values=vals, names=FEATURE_NAMES)))

    overall = f1_score(y_true, y_pred, average="macro")
    assert overall > 0.45, f"baseline macro-F1 regressed: {overall:.4f}"

    by_snr = defaultdict(lambda: ([], []))
    for r, p in zip(rows, y_pred):
        by_snr[r["snr_db"]][0].append(r["scheme"])
        by_snr[r["snr_db"]][1].append(p)
    f1_10db = f1_score(*by_snr["10"], average="macro")
    assert f1_10db > 0.6, f"baseline macro-F1 at 10dB regressed: {f1_10db:.4f}"

    f1_0db = f1_score(*by_snr["0"], average="macro")
    assert f1_0db < 0.3, (
        "baseline macro-F1 at 0dB improved past the documented known gap "
        f"({f1_0db:.4f}) -- if this is real, update the module docstring "
        "and this bound rather than leaving the old number stale"
    )


def test_dataset_has_at_least_2000_windows_per_class():
    rows = _load_dataset()
    counts = defaultdict(int)
    for r in rows:
        counts[r["scheme"]] += 1
    for scheme, n in counts.items():
        assert n >= 2000, f"{scheme}: only {n} windows"
