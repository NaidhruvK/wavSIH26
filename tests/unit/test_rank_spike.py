"""The 29 Aug Stage 4 gate, as a test.

PASS = the rank spike returns the correct codeword length 10/10 on clean data.

If this fails, the project premise is wrong and we need to know tonight, not on
7 September. Nothing else in S4-S6 is worth building until it is green.

The trials also assert the interleaver factorisation, the recovered generator
polynomials, and the block alignment - all of which come out of the same sweep,
so there is no reason to check less than all of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.rank_collapse import (
    blind_recover,
    detect_period,
    rank_profile,
    recover_code_structure,
    max_searchable_period,
)
from pipeline.s5_decode.conv_reference import conv_encode, parity_check_taps
from tests.fixtures.local_zoo import random_case, make_stream

TRIALS = 10

# Deliberately NOT a module constant compared against itself. The 31 Aug spec
# says "recovered polynomials equal THE ZOO'S CONFIGURED generators", and the
# difference is the whole point: asserting a hardcoded (171, 133) would pass
# even if recovery were hardwired to return it. Every assertion below reads
# truth.polys_octal from the stream that was actually generated, and
# test_registry.py drives the same recovery with K = 3, 5, 7 and 9.


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(TRIALS))
def test_rank_spike_recovers_parameters(seed):
    """One trial of the gate. Ten of these must pass, and they must pass on
    randomly parameterised streams with a random start offset - recovering the
    block alignment is part of the problem, not a given."""
    bits, truth = random_case(seed)
    res = blind_recover(bits)

    assert res.status == "ok", f"seed {seed}: {res.reason}"
    assert res.period == truth.period, f"seed {seed}: period {res.period} != {truth.period}"

    assert res.interleaver is not None, f"seed {seed}: no interleaver hypothesis"
    assert res.interleaver.params == {"depth": truth.depth, "width": truth.width}, \
        f"seed {seed}: got {res.interleaver.params}"

    assert res.generators_octal == tuple(truth.polys_octal), \
        f"seed {seed}: recovered {res.generators_octal}, zoo configured {truth.polys_octal}"
    assert res.code.n == 2 and res.code.memory == truth.K - 1

    # the stream was trimmed by truth.start_trim, so the recovered offset must
    # put us back on a block boundary
    assert (truth.start_trim + res.offset) % truth.period == 0, \
        f"seed {seed}: trim {truth.start_trim} + offset {res.offset} not a multiple of period"


def test_rank_spike_ten_of_ten():
    """The gate as a single number, so a failing night is unambiguous."""
    passed = 0
    failures = []
    for seed in range(TRIALS):
        bits, truth = random_case(seed)
        res = blind_recover(bits)
        if (res.status == "ok" and res.period == truth.period
                and res.interleaver is not None
                and res.interleaver.params == {"depth": truth.depth, "width": truth.width}
                and res.generators_octal == tuple(truth.polys_octal)):
            passed += 1
        else:
            failures.append((seed, res.summary()))
    assert passed == TRIALS, f"{passed}/{TRIALS}; failures: {failures}"


# --------------------------------------------------------------------------
# the negative that matters most
# --------------------------------------------------------------------------

def test_uncoded_random_data_is_not_claimed_as_a_code():
    """Risk #15. A judge will feed the system random data and see what it says.

    Claiming a code where none exists is worse than finding nothing, because it
    is the one failure that cannot be distinguished from success by looking at
    the screen."""
    rng = np.random.default_rng(20260829)
    for trial in range(3):
        # 80k is well past MIN_BITS and still searches to a period of ~250.
        # Every uncoded stream drives the statistical fallback through its
        # entire span range before returning nothing, so this test pays the
        # worst case three times - which is enough.
        noise = rng.integers(0, 2, 80_000, dtype=np.uint8)
        res = blind_recover(noise)
        assert res.status == "failed", \
            f"trial {trial}: claimed {res.summary()} on uncoded random data"
        assert res.period is None


def test_all_zeros_and_all_ones_do_not_crash():
    for bits in (np.zeros(100_000, dtype=np.uint8), np.ones(100_000, dtype=np.uint8)):
        res = blind_recover(bits)
        assert res.status in {"ok", "low_confidence", "failed"}


def test_short_stream_refuses_rather_than_guessing():
    rng = np.random.default_rng(1)
    res = blind_recover(rng.integers(0, 2, 500, dtype=np.uint8))
    assert res.status == "failed"
    assert "need" in res.reason


def test_data_limited_negative_states_its_range():
    """A stream too short to reach its own period is allowed to report "no
    code" - but only bounded. It must say how far it looked and that the stream
    length is what stopped it, otherwise "no code" reads as "no code at any
    period", which is a claim we did not earn."""
    bits, truth = make_stream(n_source_bits=6000, depth=16, width=12, seed=5)
    assert max_searchable_period(len(bits)) < truth.period, "fixture no longer data-limited"
    res = blind_recover(bits)
    assert res.status == "failed"
    assert res.data_limited is True
    assert res.searched_to < truth.period
    assert "cannot be ruled out" in res.reason
    assert res.summary()  # must not raise


def test_negative_on_random_data_reports_the_range_it_searched():
    rng = np.random.default_rng(4242)
    res = blind_recover(rng.integers(0, 2, 200_000, dtype=np.uint8))
    assert res.status == "failed"
    assert res.searched_to > 200
    assert str(res.searched_to) in res.reason


# --------------------------------------------------------------------------
# the structure the method rests on
# --------------------------------------------------------------------------

def test_raw_convolutional_signature():
    """deficiency = L/2 - 6 on even L >= 14, zero on odd L. If this ever stops
    holding, the sweep is measuring something other than the code."""
    bits, _ = make_stream(n_source_bits=60_000, depth=None, width=None, seed=11)
    prof = rank_profile(bits, 2, 48)
    for L, d in prof.deficiency.items():
        expected = max(0, L // 2 - 6) if L % 2 == 0 else 0
        assert d == expected, f"L={L}: deficiency {d}, expected {expected}"


def test_no_interleaver_case_is_recognised():
    bits, truth = make_stream(n_source_bits=60_000, depth=None, width=None, seed=12)
    res = blind_recover(bits)
    assert res.status == "ok"
    assert res.interleaver is None
    assert res.generators_octal == tuple(truth.polys_octal)


def test_recovered_parity_check_annihilates_the_stream():
    """The recovered check is only real if it actually holds on the data."""
    bits, _ = make_stream(n_source_bits=60_000, depth=None, width=None, seed=13)
    res = blind_recover(bits)
    h = np.array(res.parity_taps, dtype=np.uint8)
    windows = np.lib.stride_tricks.sliding_window_view(bits, len(h))
    syndrome = (windows @ h) % 2
    assert syndrome[0::2].sum() == 0, "recovered check does not hold on even-aligned windows"


def test_reference_parity_taps_match_recovered():
    bits, _ = make_stream(n_source_bits=60_000, depth=None, width=None, seed=14)
    res = blind_recover(bits)
    assert np.array_equal(np.array(res.parity_taps, dtype=np.uint8), parity_check_taps())


def test_code_structure_reads_n_and_memory():
    bits, _ = make_stream(n_source_bits=60_000, depth=None, width=None, seed=15)
    code = recover_code_structure(bits)
    assert (code.n, code.memory, code.span, code.consistent) == (2, 6, 14, True)


# --------------------------------------------------------------------------
# the statistical fallback inside blind_recover
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ber", [0.0005, 0.002, 0.01, 0.03])
def test_fallback_recovers_where_the_exact_test_cannot(ber):
    """The exact rank test dies at ~0.3% BER. Without the fallback wired in,
    blind_recover inherits that ceiling even though the statistical method
    reaches 3% - the capability would exist and the pipeline would not have
    it. These are the error rates where only the fallback can succeed."""
    bits, truth = make_stream(60_000, None, None, ber=ber, seed=3)

    res = blind_recover(bits)

    assert res.status == "ok", "BER %.4f: %s" % (ber, res.reason)
    assert res.method == "statistical"
    assert res.generators_octal == tuple(truth.polys_octal)
    assert res.inferred_ber == pytest.approx(ber, abs=0.004)


def test_exact_path_is_still_preferred_when_it_works():
    """The fallback must not shadow the exact test on clean data - the exact
    result carries the interleaver and the alignment, which the statistical
    path does not."""
    bits, _ = make_stream(60_000, None, None, seed=3)
    res = blind_recover(bits)
    assert res.status == "ok"
    assert res.method == "exact"
    assert res.inferred_ber is None


def test_fallback_can_be_switched_off():
    bits, _ = make_stream(60_000, None, None, ber=0.01, seed=3)
    res = blind_recover(bits, statistical_fallback=False)
    assert res.status in {"low_confidence", "failed"}
    assert res.method == "exact"


def test_fallback_does_not_manufacture_a_code_from_noise():
    """The fallback widens what we can recover. It must not widen what we are
    willing to claim - risk #15 applies to both paths equally."""
    rng = np.random.default_rng(31082026)
    for _ in range(2):
        noise = rng.integers(0, 2, 80_000, dtype=np.uint8)
        res = blind_recover(noise)
        assert res.status == "failed", "claimed %s on noise" % res.summary()
        assert res.generators_octal is None


def test_fallback_gives_up_beyond_its_own_ceiling():
    bits, _ = make_stream(60_000, None, None, ber=0.08, seed=3)
    res = blind_recover(bits)
    assert res.status in {"failed", "low_confidence"}
    assert res.generators_octal is None
