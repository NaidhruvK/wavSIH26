"""Pseudo-random (QPP) interleaver recovery, and the honest refusal beside it.

The claims under test are the ones reports/pseudorandom_interleavers.md makes:

  - LTE-table, relative-prime and arbitrary QPP interleavers are inverted blind
  - recovery is judged as a PERMUTATION, because coefficient pairs alias
  - an unstructured permutation is NOT inverted, its period IS reported, and
    the report does not call a period "interleaving"
  - the families that existed before still come back as themselves
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers as il  # noqa: E402  (registers families)
import pipeline.s4_recover.pseudorandom as pr  # noqa: E402
from pipeline.s4_recover.rank_collapse import blind_recover  # noqa: E402
from pipeline.s5_decode.conv_reference import conv_encode  # noqa: E402
from registry import INTERLEAVERS  # noqa: E402


@pytest.fixture(scope="module")
def coded():
    return conv_encode(np.random.default_rng(1).integers(0, 2, 60_000, dtype=np.uint8))


def _same_permutation(res, K, f1, f2) -> bool:
    if res.interleaver is None or res.interleaver.family != "qpp":
        return False
    return np.array_equal(pr.qpp_permutation(**res.interleaver.params),
                          pr.qpp_permutation(K, f1, f2))


# --------------------------------------------------------------------------
# the permutation itself
# --------------------------------------------------------------------------

def test_registered():
    assert "qpp" in INTERLEAVERS


def test_every_lte_table_entry_is_a_bijection():
    assert len(pr.LTE_QPP) == 60
    assert pr.LTE_QPP_REJECTED == {}


@pytest.mark.parametrize("K,f1,f2", [(40, 3, 10), (96, 11, 24), (128, 23, 66), (512, 31, 64)])
def test_round_trip_is_bit_exact(K, f1, f2):
    bits = np.random.default_rng(K).integers(0, 2, K * 20, dtype=np.uint8)
    assert np.array_equal(pr.qpp_deinterleave(pr.qpp_interleave(bits, K, f1, f2), K, f1, f2), bits)


def test_soft_values_survive_deinterleaving():
    """The 4 Sep rule: a permutation must not cast LLRs to integers."""
    llrs = np.random.default_rng(0).normal(0, 3, 96 * 10)
    out = pr.qpp_deinterleave(llrs, 96, 11, 24)
    assert out.dtype.kind == "f"
    assert np.allclose(np.sort(out), np.sort(llrs))


def test_non_bijective_coefficients_are_refused():
    assert not pr.is_qpp_permutation(96, 2, 0)          # f1 shares a factor with K
    with pytest.raises(ValueError):
        pr.qpp_permutation(96, 2, 0)


def test_coefficients_alias_and_candidates_are_deduplicated():
    """(f1 + K/2, f2 + K/2) is the same map for even K - the finding that made a
    coefficient-comparing test report correct recoveries as wrong."""
    assert np.array_equal(pr.qpp_permutation(96, 37, 48), pr.qpp_permutation(96, 85, 0))
    perms = {pr.qpp_permutation(96, c["f1"], c["f2"]).tobytes()
             for c in pr.qpp_candidates(96, max_candidates=10 ** 6)}
    n = sum(1 for _ in pr.qpp_candidates(96, max_candidates=10 ** 6))
    assert n == len(perms) == 256


def test_lte_triple_is_offered_first():
    assert next(pr.qpp_candidates(96)) == {"period": 96, "f1": 11, "f2": 24}


def test_no_candidates_without_a_period():
    assert list(pr.QPPInterleaver.candidate_params(120_000)) == []


def test_key_space_bits():
    assert pr.permutation_key_space_bits(96) == pytest.approx(498.3, abs=0.1)


# --------------------------------------------------------------------------
# the prefilter may only ever reject wrong answers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("K,f1,f2", [(40, 3, 10), (96, 11, 24), (128, 45, 60),
                                     (192, 187, 180), (256, 15, 32)])
def test_prefilter_passes_the_true_permutation(coded, K, f1, f2):
    assert pr.qpp_prefilter(pr.qpp_interleave(coded, K, f1, f2), K, f1, f2)


def test_prefilter_passes_true_permutation_for_a_short_code():
    """K=3 (generators 5, 7) - span 6, well inside PREFILTER_ROW_LEN."""
    from commpy.channelcoding import Trellis, conv_encode as cc_encode
    trellis = Trellis(np.array([2]), np.array([[5, 7]]))
    bits = np.random.default_rng(4).integers(0, 2, 20_000)
    short = np.asarray(cc_encode(bits, trellis), dtype=np.uint8)
    assert pr.qpp_prefilter(pr.qpp_interleave(short, 96, 11, 24), 96, 11, 24)


def test_prefilter_rejects_nearly_every_wrong_permutation(coded):
    K, f1, f2 = 128, 15, 32
    tx = pr.qpp_interleave(coded, K, f1, f2)
    passed = sum(pr.qpp_prefilter(tx, **c) for c in pr.qpp_candidates(K))
    assert 1 <= passed <= 4          # measured 1-2 of 2048


def test_prefilter_does_not_filter_a_stream_too_short_to_screen():
    assert pr.qpp_prefilter(np.zeros(500, dtype=np.uint8), 96, 11, 24) is True


# --------------------------------------------------------------------------
# blind recovery end to end through blind_recover
# --------------------------------------------------------------------------

@pytest.mark.parametrize("K,f1,f2", [
    (96, 11, 24),       # LTE table
    (64, 9, 0),         # relative prime
    (128, 23, 66),      # off-table; rank 778 in the candidate order, missed at cap 288
    (192, 133, 72),     # off-table; rank 451, missed at cap 288
])
def test_qpp_interleaver_is_inverted_blind(coded, K, f1, f2):
    res = blind_recover(pr.qpp_interleave(coded, K, f1, f2))
    assert res.status == "ok"
    assert _same_permutation(res, K, f1, f2)
    assert res.code.n == 2 and res.code.memory == 6


def test_unstructured_permutation_is_characterised_not_inverted(coded):
    K = 96
    perm = np.random.default_rng(1000).permutation(K)
    nb = coded.size // K
    tx = coded[:nb * K].reshape(nb, K)[:, perm].reshape(-1)
    res = blind_recover(tx)
    assert res.status != "ok"
    assert res.interleaver is None
    v = res.interleaver_verdict
    assert v is not None and v["verdict"] == "period-only"
    assert v["period"] == 96 and v["permutation_recovered"] is False
    assert v["key_space_bits"] == pytest.approx(498.3, abs=0.1)
    # a period is not proof of an interleaver - a length-K block code collapses
    # at the same row length (found against an LDPC downlink, 13 Sep)
    assert "interleaving is present" not in res.reason
    assert "block code" in res.reason


@pytest.mark.parametrize("label,fn,params,family", [
    ("block", il.block_interleave, {"depth": 8, "width": 12}, "block"),
    ("diagonal", il.diagonal_interleave, {"depth": 8, "width": 12}, "diagonal"),
])
def test_existing_families_are_not_captured_by_qpp(coded, label, fn, params, family):
    res = blind_recover(fn(coded, **params))
    assert res.status == "ok"
    assert res.interleaver.family == family and res.interleaver.params == params
