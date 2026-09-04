"""tests/unit/test_s2_estimate.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.s0_ingest import ingest
from pipeline.s2_estimate import estimate, estimate_cfo, estimate_fsk_order

CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "rf"


def _corpus_files(pattern: str = "*dB_*.wav") -> list[Path]:
    files = sorted(CORPUS.glob(pattern))
    if not files:
        pytest.skip(f"no files matching {pattern} in {CORPUS} -- run python -m zoo.build_rf_corpus")
    return files


def test_symbol_rate_within_1pct_at_10db_and_above():
    """The 1 Sep gate: symbol-rate error <1% on >=18/20 files at >=10dB."""
    n_ok = n_total = 0
    failures = []
    for f in _corpus_files():
        truth = json.loads(f.with_suffix(".json").read_text())
        if truth["snr_db"] < 10:
            continue
        r = ingest(f)
        result = estimate(r.iq, r.fs)
        assert result.status == "ok"
        true_rate = r.fs / truth["sps"]
        err_pct = abs(result.symbol_rate_hz - true_rate) / true_rate * 100
        n_total += 1
        if err_pct < 1.0:
            n_ok += 1
        else:
            failures.append(f"{f.name}: true={true_rate:.0f} measured={result.symbol_rate_hz:.0f} err={err_pct:.2f}%")
    assert n_ok >= 18, f"only {n_ok}/{n_total} within 1% -- failures: {failures}"


def test_fsk_order_hint_correct_at_10db_and_above():
    expected = {"2fsk": 2, "4fsk": 4}
    for f in _corpus_files():
        truth = json.loads(f.with_suffix(".json").read_text())
        if truth["scheme"] not in expected or truth["snr_db"] < 10:
            continue
        r = ingest(f)
        order, score, hyps = estimate_fsk_order(r.iq, r.fs)
        assert order == expected[truth["scheme"]], f"{f.name}: expected {expected[truth['scheme']]}, got {order}"


def test_fsk_order_known_gap_at_low_snr():
    """4fsk at 4dB (below every other stated target floor in this project)
    is a measured miss, not silently swept under the rug."""
    f = CORPUS / "4fsk_4dB_2030.wav"
    if not f.exists():
        pytest.skip("corpus file not present")
    r = ingest(f)
    order, score, hyps = estimate_fsk_order(r.iq, r.fs)
    assert order != 4, "if this now passes, tighten the gate and drop this test"


def test_estimate_never_reads_truth():
    """Grep-style structural check: estimate() takes only iq, fs and
    behaviour toggles -- no truth parameter exists to leak through."""
    import inspect
    from pipeline.s2_estimate import estimate as est_fn
    params = list(inspect.signature(est_fn).parameters)
    assert params == ["iq", "fs", "constant_envelope", "classify"]


def test_estimate_fails_cleanly_on_short_input():
    result = estimate(np.zeros(4, dtype=complex), fs=200_000.0)
    assert result.status == "failed"
    assert result.reason is not None


def test_estimate_detects_constant_envelope_for_fsk():
    f = _corpus_files("2fsk_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    assert result.constant_envelope is True


def test_estimate_detects_non_constant_envelope_for_qam():
    f = _corpus_files("16qam_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    assert result.constant_envelope is False


def test_cfo_hypotheses_ranked_by_score():
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    cfo, order_m, score, hyps = estimate_cfo(r.iq, r.fs)
    scores = [h[2] for h in hyps]
    assert scores == sorted(scores, reverse=True)
    assert (cfo, order_m, score) == hyps[0]


def test_result_hypotheses_are_ranked_descending():
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    rate_scores = [h[1] for h in result.symbol_rate_hypotheses]
    assert rate_scores == sorted(rate_scores, reverse=True)
