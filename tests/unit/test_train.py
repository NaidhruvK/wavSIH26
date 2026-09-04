"""tests/unit/test_train.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from models.train import (
    CLASSES,
    HOLDOUT_CSV,
    TRAIN_CSV,
    _load,
    evaluate_and_report,
    expected_calibration_error,
    predict,
    train,
)


def _require_datasets():
    if not TRAIN_CSV.exists() or not HOLDOUT_CSV.exists():
        pytest.skip("run python -m models.build_dataset && python -m models.build_holdout first")


def test_train_is_deterministic():
    """Regression guard for a real bug found this session: without
    num_threads=1 + force_row_wise=True + deterministic=True, LightGBM
    produced different predictions on repeated training runs with the
    same seed -- confirmed by loading two separately-trained models and
    comparing predictions, not by assumption."""
    _require_datasets()
    X_hold, _y_hold, _snr = _load(HOLDOUT_CSV)
    b1 = train()
    p1, _ = predict(b1, X_hold)
    b2 = train()
    p2, _ = predict(b2, X_hold)
    assert np.array_equal(p1, p2)


def test_model_beats_baseline_overall():
    _require_datasets()
    results = evaluate_and_report()
    assert results["macro_f1_holdout"] > results["baseline_macro_f1_holdout"]


def test_holdout_never_overlaps_training_grid():
    """The mistake the plan calls out explicitly: validating on the
    training SNR grid makes the number meaningless."""
    _require_datasets()
    _X, _y, snr_train = _load(TRAIN_CSV)
    _X, _y, snr_hold = _load(HOLDOUT_CSV)
    assert set(np.unique(snr_train)) & set(np.unique(snr_hold)) == set()


def test_ece_is_a_valid_probability_bound():
    proba = np.array([[0.9, 0.05, 0.05], [0.4, 0.4, 0.2]])
    y_true = np.array([0, 1])
    ece = expected_calibration_error(proba, y_true)
    assert 0.0 <= ece <= 1.0


def test_all_six_classes_have_holdout_rows():
    _require_datasets()
    _X, y, _snr = _load(HOLDOUT_CSV)
    assert set(np.unique(y)) == set(range(len(CLASSES)))
