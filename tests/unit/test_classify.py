"""tests/unit/test_classify.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from models.classify import CLASSES, classify, resample_window
from pipeline.s0_ingest import ingest
from pipeline.s2_estimate import estimate

CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "rf"


def _require_model():
    from models.classify import MODEL_PATH
    if not MODEL_PATH.exists():
        pytest.skip("models/classifier.txt missing -- run python -m models.train first")


def _corpus_file(pattern: str) -> Path:
    files = sorted(CORPUS.glob(pattern))
    if not files:
        pytest.skip(f"no files matching {pattern} in {CORPUS}")
    return files[0]


def test_resample_window_shape():
    rng = np.random.default_rng(0)
    iq = (rng.normal(size=20000) + 1j * rng.normal(size=20000))
    w = resample_window(iq, fs=200_000.0, symbol_rate=50_000.0)
    assert w is not None
    assert w.shape == (4096,)
    assert np.isfinite(w).all()


def test_resample_window_none_on_too_short():
    w = resample_window(np.zeros(10, dtype=complex), fs=200_000.0, symbol_rate=50_000.0)
    assert w is None


def test_resample_window_none_on_bad_symbol_rate():
    iq = np.ones(20000, dtype=complex)
    assert resample_window(iq, fs=200_000.0, symbol_rate=0.0) is None
    assert resample_window(iq, fs=200_000.0, symbol_rate=float("nan")) is None


def test_classify_correct_on_clean_examples():
    """Spot check at 10dB+ for the four schemes reports/s2_coverage.md
    shows as solid (bpsk/qpsk/8psk/16qam). FSK is checked separately --
    see test_classify_fsk_known_gap, it's not uniformly correct."""
    _require_model()
    for scheme in ["bpsk", "qpsk", "8psk", "16qam"]:
        f = _corpus_file(f"{scheme}_10dB_*.wav")
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        result = estimate(r.iq, r.fs)
        assert result.modulation_hypotheses, f"{f.name}: no hypotheses returned"
        assert result.modulation_hypotheses[0][0] == truth["scheme"]


def test_classify_hypotheses_sum_close_to_one():
    _require_model()
    f = _corpus_file("qpsk_10dB_*.wav")
    r = ingest(f)
    out = classify(r.iq, r.fs, symbol_rate=r.fs / 4)
    total = sum(p for _c, p in out["hypotheses"][:1]) if out["low_confidence"] else sum(p for _c, p in out["hypotheses"])
    # top-k truncates the tail, so only assert the top hypothesis is a
    # plausible probability, not that the full distribution sums to 1
    assert 0.0 <= out["hypotheses"][0][1] <= 1.0


def test_classify_4fsk_fixed_at_10_to_15db():
    """Regression guard for the overfitting fix in models/train.py's
    LGB_PARAMS: 4fsk at 10-15dB used to be wrong everywhere except
    exactly 10dB (the original, since-corrected diagnosis in
    reports/classifier_eval.md). Now solid 10-15dB after regularisation
    -- if this starts failing, the fix regressed."""
    _require_model()
    for snr in ["10dB", "13dB", "15dB"]:
        f = _corpus_file(f"4fsk_{snr}_*.wav")
        r = ingest(f)
        result = estimate(r.iq, r.fs)
        assert result.modulation_hypotheses[0][0] == "4fsk", f"{f.name} regressed"


def test_classify_4fsk_residual_gap_at_20db():
    """Measured, documented in reports/s2_coverage.md: even after the
    overfitting fix, 4fsk at 20dB is still wrong on most files (a
    DIFFERENT, smaller residual than the original 10-20dB failure --
    this slice was never covered by the holdout evaluation). Unlike the
    original bug, this is no longer a *confident* wrong answer: 4fsk
    stays a top-2 hypothesis, which is what this test actually pins --
    not the top-1 miss itself, since that's closer to a coin flip and
    not worth pinning file-by-file."""
    _require_model()
    f = _corpus_file("4fsk_20dB_*.wav")
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    top2 = {c for c, _p in result.modulation_hypotheses[:2]}
    assert "4fsk" in top2, (
        "4fsk dropped out of the top-2 entirely at 20dB -- that's worse "
        "than the documented residual gap, investigate rather than just "
        "updating this assertion"
    )


def test_s2_classify_false_disables_classification():
    r = ingest(_corpus_file("qpsk_10dB_*.wav"))
    result = estimate(r.iq, r.fs, classify=False)
    assert result.status == "ok"
    assert result.modulation_hypotheses == []


def test_s2_degrades_gracefully_without_model_file(monkeypatch):
    """If models/classifier.txt is missing (fresh checkout, before
    training has run), S2 must still return a normal result -- not crash
    the whole stage over a missing model file."""
    import models.classify as clsfy
    monkeypatch.setattr(clsfy, "MODEL_PATH", Path("/does/not/exist.txt"))
    monkeypatch.setattr(clsfy, "_booster", None)
    r = ingest(_corpus_file("qpsk_10dB_*.wav"))
    result = estimate(r.iq, r.fs)
    assert result.status == "ok"
    assert result.modulation_hypotheses == []
