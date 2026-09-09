"""tests/unit/test_s2_estimate.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.s0_ingest import ingest
from pipeline.s2_estimate import estimate, estimate_cfo, estimate_cfo_fsk, estimate_fsk_order

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
    cfo, order_m, score, hyps, aliases = estimate_cfo(r.iq, r.fs)
    scores = [h[2] for h in hyps]
    assert scores == sorted(scores, reverse=True)
    assert (cfo, order_m, score) == hyps[0]


@pytest.mark.parametrize("scheme", ["bpsk", "qpsk", "8psk", "16qam"])
def test_cfo_zero_on_clean_files(scheme):
    """Regression guard for the M-th power spectral-line trap: a teammate
    found every clean (zero-CFO) file reporting a false CFO of Rs/M,
    caused by demeaning the M-th power signal before the FFT -- which
    nulls the DC bin, exactly where the true line sits when CFO is
    genuinely 0. Every file in this corpus has cfo_norm=0.0 (see
    zoo/rf.py), so this is checkable directly against truth, not just
    plausibility. Tolerance is loose (100 Hz) because this is a spectral
    peak estimate, not exact arithmetic.

    LINEAR modulations only -- estimate_cfo is the M-th-power-line
    estimator, which has no meaning for FSK (see
    test_cfo_fsk_zero_on_clean_files and estimate_cfo_fsk's docstring for
    the FSK path and the second bug found in this same area)."""
    for f in _corpus_files(f"{scheme}_*dB_*.wav"):
        truth = json.loads(f.with_suffix(".json").read_text())
        if truth["snr_db"] < 10:
            continue
        r = ingest(f)
        cfo, order_m, score, hyps, aliases = estimate_cfo(r.iq, r.fs)
        assert abs(cfo) < 100, (
            f"{f.name}: measured CFO {cfo:.1f} Hz, expected ~0 -- "
            f"Rs/order_m would be {r.fs / truth['sps'] / order_m:.1f} Hz, "
            "check for the demean-before-FFT regression"
        )


@pytest.mark.parametrize("scheme", ["2fsk", "4fsk"])
def test_cfo_fsk_zero_on_clean_files(scheme):
    """5 Sep, reported by a teammate: estimate() ran the M-th-power line
    search (estimate_cfo) on FSK captures too, unconditionally. That
    estimator has no meaning for FSK -- there is no suppressed carrier
    for x**M to expose, only M discrete tones -- and it locked onto a
    tone-spacing artifact instead: every clean 2fsk/4fsk file reported
    ~symbol_rate/2 (e.g. 25000 Hz on this corpus's 50000 Hz-symbol-rate
    files), identical in shape to the bug 426a780 fixed for PSK/QAM but
    from an inapplicable estimator, not a demeaning bug in an applicable
    one. The teammate also measured real downstream cost: 4-FSK recovery
    succeeded WITHOUT this CFO estimate applied and failed WITH it, at
    both 13 and 20dB.

    estimate_cfo_fsk (IF-tone centroid) is the fix, verified against the
    same 100Hz tolerance every other S2 CFO gate in this project uses."""
    for f in _corpus_files(f"{scheme}_*dB_*.wav"):
        truth = json.loads(f.with_suffix(".json").read_text())
        if truth["snr_db"] < 10:
            continue
        r = ingest(f)
        cfo, order_m, score, hyps, aliases = estimate_cfo_fsk(r.iq, r.fs)
        assert abs(cfo) < 100, (
            f"{f.name}: measured CFO {cfo:.1f} Hz, expected ~0 -- "
            f"symbol_rate/2 would be {r.fs / truth['sps'] / 2:.1f} Hz, "
            "check estimate_cfo_fsk's tone-centroid refinement"
        )


@pytest.mark.parametrize("scheme", ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"])
def test_estimate_cfo_zero_on_clean_files_all_six_schemes(scheme):
    """Per the teammate's explicit ask: validate through the actual
    estimate() entry point, reported per scheme, so a fix covering 4 of 6
    modulation families is never again reported as if it covered all six
    -- that is exactly the shape of the mistake in this fix's own first
    round (426a780's "112/112" was 4 linear schemes only; the 56 FSK
    files were never in that count, and still failed with the false
    Rs/2 CFO). This test runs estimate() itself (constant_envelope=None,
    the real routing decision), not either estimator directly, so it
    would have caught the original miscount."""
    for f in _corpus_files(f"{scheme}_*dB_*.wav"):
        truth = json.loads(f.with_suffix(".json").read_text())
        if truth["snr_db"] < 10:
            continue
        r = ingest(f)
        result = estimate(r.iq, r.fs, classify=False)
        assert result.status == "ok"
        assert abs(result.cfo_hz) < 100, f"{f.name}: measured CFO {result.cfo_hz:.1f} Hz"


def test_cfo_true_peak_score_beats_false_alias():
    """The root-cause check, not just the symptom: on a clean file, the
    M matching the signal's own PSK order must win on SCORE (not just
    happen to be picked), because its true DC line is intrinsically
    stronger than any other order's symbol-rate artifact. This is what
    makes the fix robust rather than coincidental."""
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    cfo, order_m, score, hyps, aliases = estimate_cfo(r.iq, r.fs)
    assert order_m == 4
    assert abs(cfo) < 100


def test_cfo_alias_hypotheses_include_zero():
    """Per the teammate's fix request: 0 Hz must always be an available
    candidate in the full alias set, not just the top pick -- a safety
    net for S3/S4 even if some future edge case makes the peak search
    land elsewhere."""
    f = _corpus_files("8psk_10dB_*.wav")[0]
    r = ingest(f)
    _cfo, _m, _score, _hyps, aliases = estimate_cfo(r.iq, r.fs)
    assert any(abs(c) < 1.0 for c, _m, _s in aliases)


def test_cfo_alias_hypotheses_cover_every_alias_per_order():
    """The alias set must expose all `m` roots per order, not just the
    single closest-to-zero pick `hyps` keeps for backward compatibility.
    Total may be m+1 if none of the m roots landed near zero and the
    explicit 0Hz safety net had to be appended on top -- that's correct,
    not a bug (see test_cfo_alias_hypotheses_include_zero). Distinguish
    the m real roots from the safety net by score: every real root
    shares the SAME FFT-peak score (they're aliases of one measurement),
    while the safety net's score is always 0.0."""
    f = _corpus_files("8psk_10dB_*.wav")[0]
    r = ingest(f)
    _cfo, _m, _score, hyps, aliases = estimate_cfo(r.iq, r.fs, orders=(4,))
    real_roots = [a for a in aliases if a[2] > 0.0]
    assert len(real_roots) == 4, "all 4 roots for order 4 should be present, none collapsed away"


def test_cfo_fsk_order_matches_fsk_order_hint():
    """estimate_cfo_fsk and estimate_fsk_order share the same tone-peak
    detector (_fsk_tone_peaks) precisely so they can never disagree on
    how many tones are present -- check that shared assumption holds,
    not just that each function works in isolation."""
    for scheme, expected in [("2fsk", 2), ("4fsk", 4)]:
        f = _corpus_files(f"{scheme}_15dB_*.wav")[0]
        r = ingest(f)
        _cfo, order_m, _score, _hyps, _aliases = estimate_cfo_fsk(r.iq, r.fs)
        fsk_order, _s, _h = estimate_fsk_order(r.iq, r.fs)
        assert order_m == fsk_order == expected


def test_cfo_fsk_alias_hypotheses_include_zero():
    """Same defensive guarantee as the linear-modulation path
    (test_cfo_alias_hypotheses_include_zero): 0 Hz must always be an
    available candidate, even if the tone-centroid estimate itself lands
    away from zero on some future edge case."""
    f = _corpus_files("2fsk_15dB_*.wav")[0]
    r = ingest(f)
    _cfo, _m, _score, _hyps, aliases = estimate_cfo_fsk(r.iq, r.fs)
    assert any(abs(c) < 1.0 for c, _m, _s in aliases)


def test_estimate_routes_fsk_to_estimate_cfo_fsk():
    """The actual bug: estimate() used to call estimate_cfo unconditionally.
    Confirm the routing by constant_envelope now happens -- an FSK file's
    result.cfo_hz must come from the tone-centroid path (small residual),
    not the M-th-power path (which would report ~symbol_rate/2 here)."""
    f = _corpus_files("4fsk_15dB_*.wav")[0]
    truth = json.loads(f.with_suffix(".json").read_text())
    r = ingest(f)
    result = estimate(r.iq, r.fs, classify=False)
    assert result.constant_envelope is True
    false_alias_hz = r.fs / truth["sps"] / 2
    assert abs(result.cfo_hz) < 100
    assert abs(result.cfo_hz - false_alias_hz) > 1000, \
        "result.cfo_hz looks like it came from the M-th-power path, not estimate_cfo_fsk"


def test_estimate_result_carries_cfo_alias_hypotheses():
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    assert result.cfo_alias_hypotheses
    assert any(abs(c) < 1.0 for c, _m, _s in result.cfo_alias_hypotheses)


def test_result_hypotheses_are_ranked_descending():
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    rate_scores = [h[1] for h in result.symbol_rate_hypotheses]
    assert rate_scores == sorted(rate_scores, reverse=True)


def test_envelope_cv_always_populated_even_when_constant_envelope_given():
    """7 Sep, Nehal: constant_envelope < 0.25 is an SNR test wearing a
    modulation test's name -- his ask was that the raw statistic be
    exposed in the result, not just documented in a report, so any
    caller can apply its own policy instead of trusting constant_envelope
    blind. Must be populated even when the caller passes constant_envelope
    explicitly, since that path never computes it internally otherwise."""
    f = _corpus_files("qpsk_10dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs, constant_envelope=False)
    assert result.envelope_cv is not None
    assert result.envelope_cv > 0.0


@pytest.mark.parametrize("scheme,snr,expected", [
    ("2fsk", 20, 0.070), ("2fsk", 15, 0.124), ("2fsk", 13, 0.155),
    ("2fsk", 10, 0.215), ("2fsk", 8, 0.264), ("2fsk", 4, 0.376),
    ("4fsk", 20, 0.070), ("4fsk", 15, 0.124), ("4fsk", 13, 0.155),
    ("4fsk", 10, 0.215), ("4fsk", 8, 0.264), ("4fsk", 4, 0.377),
])
def test_envelope_cv_matches_nehals_independent_measurement(scheme, snr, expected):
    """Pins the table from Nehal's 7 Sep review -- 2fsk and 4fsk give the
    same envelope_cv to three decimal places at every SNR (his table's
    values, rounded means of the 7 reps per scheme/SNR cell), which is
    the whole proof this statistic carries no modulation information,
    only an SNR one (it tracks 1/sqrt(2*SNR_linear)). Checked against
    the first file in the cell, not the mean -- tolerance widened to
    0.002 to cover real inter-rep variance (measured range for 2fsk at
    4dB alone is 0.375-0.378), not because the statistic is imprecise."""
    f = _corpus_files(f"{scheme}_{snr}dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs)
    assert abs(result.envelope_cv - expected) < 0.002, (
        f"{f.name}: envelope_cv={result.envelope_cv:.3f}, expected {expected}"
    )


def test_a_classifier_exception_degrades_instead_of_failing_s2(monkeypatch):
    """9 Sep guard pass. estimate()'s classify block used to catch only
    FileNotFoundError (the model-not-trained-yet case) -- any OTHER
    exception from models.classify.classify (a corrupt classifier.txt, a
    feature-extraction edge case on adversarial input) fell through to
    estimate()'s own outer handler and reported status="failed" for the
    WHOLE result, discarding a rate/cfo estimate that had already been
    computed successfully. classify() failing is not a reason to also
    throw away demodulation parameters that never depended on it."""
    import models.classify

    def _boom(iq, fs, symbol_rate):
        raise RuntimeError("classifier blew up on this capture")

    monkeypatch.setattr(models.classify, "classify", _boom)

    f = _corpus_files("qpsk_20dB_*.wav")[0]
    r = ingest(f)
    result = estimate(r.iq, r.fs, classify=True)

    assert result.status == "ok"
    assert result.symbol_rate_hz is not None
    assert result.cfo_hz is not None
    assert result.modulation_hypotheses == []
    assert result.modulation_low_confidence is None
