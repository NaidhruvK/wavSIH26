"""Statistical parity-check recovery and validation.

The dangerous failure of this module is not missing a check - it is confirming
one that is not there. Most of what follows is aimed at that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.gf2 import null_space_gf2
from pipeline.s4_recover.statistical import (
    int_to_taps,
    null_space_int,
    statistical_recover,
    syndrome_validate,
    taps_to_int,
    vote_for_check,
)
from pipeline.s5_decode.conv_reference import parity_check_taps
from tests.fixtures.local_zoo import make_stream

TRUE_CHECK = parity_check_taps()
TRUE_SPAN = len(TRUE_CHECK)


def _span_set(vectors, span):
    """Every vector in the span of `vectors`, as ints - so two different bases
    of the same subspace compare equal."""
    out = set()
    for mask in range(1, 1 << len(vectors)):
        acc = np.zeros(span, dtype=np.uint8)
        for i, v in enumerate(vectors):
            if mask >> i & 1:
                acc ^= v
        out.add(taps_to_int(acc))
    return out


# --------------------------------------------------------------------------
# the packed-int null space, against galois
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(15))
def test_null_space_int_matches_galois(seed):
    rng = np.random.default_rng(seed)
    span = int(rng.integers(3, 16))
    k = int(rng.integers(1, span + 1))
    M = rng.integers(0, 2, (k, span), dtype=np.uint8)

    mine = [int_to_taps(v, span) for v in null_space_int([taps_to_int(r) for r in M], span)]
    ref = list(null_space_gf2(M))
    assert len(mine) == len(ref)
    if mine:
        assert _span_set(mine, span) == _span_set(ref, span)
        for v in mine:
            assert np.all((M @ v) % 2 == 0)


def test_round_trip_taps_int():
    rng = np.random.default_rng(0)
    for _ in range(50):
        span = int(rng.integers(2, 40))
        taps = rng.integers(0, 2, span, dtype=np.uint8)
        assert np.array_equal(int_to_taps(taps_to_int(taps), span), taps)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def test_true_check_validates_with_full_bias_on_clean_data():
    bits, _ = make_stream(60_000, None, None, seed=1)
    val = syndrome_validate(bits, taps_to_int(TRUE_CHECK), TRUE_SPAN, stride=2, phase=0)
    assert val.passed
    assert val.bias == pytest.approx(1.0, abs=1e-9)
    assert val.implied_ber == pytest.approx(0.0, abs=1e-9)


def test_wrong_check_does_not_validate():
    """A random vector must sit at bias ~0 and fail. This is the false-positive
    guard for the statistical half of Stage 4."""
    bits, _ = make_stream(60_000, None, None, seed=2)
    rng = np.random.default_rng(9)
    for _ in range(25):
        cand = int(rng.integers(1, 1 << TRUE_SPAN))
        if cand == taps_to_int(TRUE_CHECK):
            continue
        val = syndrome_validate(bits, cand, TRUE_SPAN, stride=2, phase=0)
        assert not val.passed, "validated a random vector: %s" % val.describe()
        assert abs(val.bias) < 0.05


def test_no_check_validates_on_uncoded_data():
    rng = np.random.default_rng(11)
    noise = rng.integers(0, 2, 80_000, dtype=np.uint8)
    res = statistical_recover(noise, max_span=16, n_samples=400)
    assert res.status == "failed", "claimed %s on uncoded data" % res.describe()


def test_wrong_phase_halves_the_bias():
    """A check evaluated at stride 1 mixes satisfied and unsatisfied windows, so
    the bias is halved. This is the effect the stride search exists to avoid."""
    bits, _ = make_stream(60_000, None, None, seed=3)
    h = taps_to_int(TRUE_CHECK)
    aligned = syndrome_validate(bits, h, TRUE_SPAN, stride=2, phase=0)
    mixed = syndrome_validate(bits, h, TRUE_SPAN, stride=1, phase=0)
    assert aligned.bias == pytest.approx(1.0, abs=1e-9)
    assert mixed.bias == pytest.approx(0.5, abs=0.02)


def test_implied_ber_tracks_injected_ber():
    """The validator's own estimate of the channel is checkable, so check it."""
    for ber in (0.005, 0.01, 0.02, 0.04):
        bits, truth = make_stream(60_000, None, None, ber=ber, seed=4)
        val = syndrome_validate(bits, taps_to_int(TRUE_CHECK), TRUE_SPAN, 2, 0)
        assert val.passed
        assert val.implied_ber == pytest.approx(ber, abs=0.004), \
            "injected %.3f, inferred %.4f" % (ber, val.implied_ber)


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------

def test_voting_finds_the_true_check_on_clean_data():
    bits, _ = make_stream(60_000, None, None, seed=5)
    cand = vote_for_check(bits, TRUE_SPAN, stride=2, phase=0, n_samples=200)
    assert cand is not None
    assert cand.check == taps_to_int(TRUE_CHECK)
    # with span+6 rows drawn, nearly every clean draw is exactly determined
    assert cand.vote_fraction > 0.9, "yield dropped - check EXTRA_ROWS"


def test_voting_produces_no_consensus_on_noise():
    rng = np.random.default_rng(13)
    noise = rng.integers(0, 2, 100_000, dtype=np.uint8)
    cand = vote_for_check(noise, TRUE_SPAN, stride=2, phase=0, n_samples=500)
    # a random vector may top the tally, but it must not dominate it
    assert cand is None or cand.vote_fraction < 0.05


@pytest.mark.parametrize("ber", [0.0, 0.01, 0.03])
def test_tracking_recovers_the_check_under_noise(ber):
    bits, _ = make_stream(60_000, None, None, ber=ber, seed=6)
    res = statistical_recover(bits, spans=[TRUE_SPAN])
    assert res.status == "ok"
    assert np.array_equal(np.array(res.taps, dtype=np.uint8), TRUE_CHECK)


def test_blind_search_recovers_span_and_check_on_clean_data():
    bits, _ = make_stream(60_000, None, None, seed=7)
    res = statistical_recover(bits, max_span=20)
    assert res.status == "ok"
    assert res.validation.span == TRUE_SPAN
    assert res.validation.stride == 2
    assert np.array_equal(np.array(res.taps, dtype=np.uint8), TRUE_CHECK)


def test_search_is_bounded():
    """max_span must actually bound the work - risk #5 lives here too."""
    rng = np.random.default_rng(17)
    noise = rng.integers(0, 2, 60_000, dtype=np.uint8)
    res = statistical_recover(noise, max_span=8, n_samples=100)
    assert res.status == "failed"
    assert "span 8" in res.reason


def test_time_budget_bounds_the_worst_case():
    """The search is most expensive on inputs containing nothing, which is
    exactly what someone reaches for to make the system waste time (risk #5).
    A budget bounds it, and the result must say the search was cut short rather
    than claim a clean negative it did not earn."""
    import time as _time
    rng = np.random.default_rng(77)
    noise = rng.integers(0, 2, 200_000, dtype=np.uint8)

    t0 = _time.monotonic()
    res = statistical_recover(noise, max_span=40, time_budget_s=2.0)
    elapsed = _time.monotonic() - t0

    assert res.status == "failed"
    assert elapsed < 12.0, "budget did not bound the search: %.1fs" % elapsed
    assert "budget stopped the search" in res.reason


def test_budget_does_not_weaken_a_real_recovery():
    bits, _ = make_stream(60_000, None, None, ber=0.01, seed=8)
    res = statistical_recover(bits, spans=[TRUE_SPAN], time_budget_s=30.0)
    assert res.status == "ok"
    assert np.array_equal(np.array(res.taps, dtype=np.uint8), TRUE_CHECK)


def test_unbudgeted_negative_still_claims_its_full_range():
    rng = np.random.default_rng(78)
    res = statistical_recover(rng.integers(0, 2, 60_000, dtype=np.uint8),
                              max_span=10, n_samples=200)
    assert res.status == "failed"
    assert "budget" not in res.reason
    assert "span 10" in res.reason
