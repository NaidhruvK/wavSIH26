"""The realistic error model, and what it does to Stage 4.

Every ceiling measured before 1 Sep used independent bit flips, and every
report carrying those numbers called them "an optimistic bound" because real
demodulator errors are bursty. That assumption was never tested. It is wrong,
and in the useful direction:

  rank collapse counts DAMAGED ROWS, not damaged bits. A row is ruined by one
  error as thoroughly as by twenty. Clustering the same errors into fewer rows
  leaves more clean rows, so the collapse survives further.

These tests pin the mechanism, so that if someone later "fixes" the channel
model or the row-selection logic, the reason the numbers look the way they do
does not quietly evaporate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.gf2 import rank_gf2, reshape_rows
from pipeline.s4_recover.interleavers import block_interleave
from pipeline.s4_recover.rank_collapse import detect_period
from pipeline.s5_decode.conv_reference import conv_encode
from tests.fixtures.local_zoo import (
    CCSDS_SCRAMBLER,
    gilbert_elliott_mask,
    lfsr_scramble,
    make_stream,
)

ROW = 96


@pytest.fixture(scope="module")
def interleaved():
    rng = np.random.default_rng(0)
    return block_interleave(conv_encode(rng.integers(0, 2, 150_000, dtype=np.uint8)), 8, 12)


def _deficiency(bits, L):
    return L - rank_gf2(reshape_rows(bits, L, 0, max_rows=L + 64))


# --------------------------------------------------------------------------
# the channel does what it says
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ber", [0.002, 0.01, 0.03])
@pytest.mark.parametrize("mean_burst", [1, 5, 20])
def test_channel_delivers_the_requested_error_rate(ber, mean_burst):
    """Clustering must not change the overall rate - otherwise the comparison
    is measuring two different channels, not two different arrangements of the
    same one."""
    rng = np.random.default_rng(0)
    # long bursts at a low rate mean few bursts, so the realised rate is
    # noisier - sample enough that the tolerance can stay meaningful
    mask = gilbert_elliott_mask(1_000_000, ber, mean_burst, rng)
    assert mask.mean() == pytest.approx(ber, rel=0.2)


def test_clustering_reduces_damaged_rows_at_fixed_ber():
    """The whole mechanism in one assertion."""
    rng = np.random.default_rng(0)
    n, ber = 400_000, 0.01
    damaged = {}
    for mb in (1, 5, 20, 100):
        mask = gilbert_elliott_mask(n, ber, mb, rng)
        rows = mask[: n // ROW * ROW].reshape(-1, ROW).any(axis=1)
        damaged[mb] = rows.mean()

    assert damaged[1] > damaged[5] > damaged[20] > damaged[100]
    assert damaged[100] < damaged[1] / 5, \
        "clustering barely helped: %r" % damaged


def test_zero_ber_produces_no_errors():
    rng = np.random.default_rng(0)
    assert not gilbert_elliott_mask(10_000, 0.0, 20, rng).any()


# --------------------------------------------------------------------------
# and therefore recovery survives further
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mean_burst,ber", [(5, 0.0075), (20, 0.02), (100, 0.05)])
def test_recovery_survives_bursts_that_kill_independent_errors(mean_burst, ber):
    """Each of these rates defeats the exact test outright with independent
    errors, and is comfortably recovered when the same errors are clustered.

    The rates are chosen where the separation is clean rather than marginal.
    Independent errors do not fail sharply at a threshold - measured 4/6 at
    0.5% and 0/6 at 0.75% - so a test built on the marginal point would be
    flaky in a way that says nothing about the code.
    """
    for seed in range(3):
        indep, truth = make_stream(60_000, 8, 12, ber=ber, seed=900 + seed,
                                   mean_burst=1)
        assert detect_period(indep)[0] != truth.period, \
            "fixture no longer discriminating: independent errors still work at %.4f" % ber

        bursty, truth = make_stream(60_000, 8, 12, ber=ber, seed=900 + seed,
                                    mean_burst=mean_burst)
        assert detect_period(bursty)[0] == truth.period, \
            "burst %d at BER %.4f should recover" % (mean_burst, ber)


# --------------------------------------------------------------------------
# scrambling does not hide the code - this is what makes CCSDS tractable
# --------------------------------------------------------------------------

def test_default_scrambler_is_actually_maximal_length():
    """0o177 was the default until 1 Sep and has period SEVEN, not 63, despite
    a comment claiming it was maximal-length. Validating blind scrambler
    recovery against a period-7 sequence would have proved nearly nothing."""
    seq = lfsr_scramble(np.zeros(3000, dtype=np.uint8))
    degree = CCSDS_SCRAMBLER.bit_length() - 1
    period = next(p for p in range(1, 1200)
                  if np.array_equal(seq[:1000], seq[p:p + 1000]))
    assert period == 2 ** degree - 1 == 255
    assert seq.mean() == pytest.approx(0.5, abs=0.05)


def test_rank_collapse_survives_scrambling(interleaved):
    """Scrambling is an AFFINE map - XOR with a fixed sequence - not a linear
    one, so in principle it could destroy the collapse entirely. It does not.
    The deficiency shrinks but stays large, and stays at multiples of the
    period, which means CCSDS can be unwound without descrambling first."""
    scrambled = lfsr_scramble(interleaved)
    for L in (96, 192, 288):
        clean, scr = _deficiency(interleaved, L), _deficiency(scrambled, L)
        assert scr > 0, "collapse destroyed at L=%d" % L
        assert scr > clean * 0.6, "collapse gutted at L=%d: %d -> %d" % (L, clean, scr)
    # and nothing appears where it should not
    assert _deficiency(scrambled, 100) == 0


@pytest.mark.parametrize("poly", [0o45, 0o177, 0o211, 0o435, 0o1021])
def test_scrambling_costs_about_its_own_degree(interleaved, poly):
    """The deficiency lost to scrambling is the degree of the LFSR - the
    scrambler sequence satisfies its own linear recurrence, so it only adds
    that many dimensions to the row space.

    "About", not "exactly": measured exact for 17 of 18 (polynomial, row
    length) pairs, with one case losing less where the sequence period
    interacts with the row length. Treated as an indicator, not a law.
    """
    degree = poly.bit_length() - 1
    scrambled = lfsr_scramble(interleaved, poly)
    for L in (96, 192):
        drop = _deficiency(interleaved, L) - _deficiency(scrambled, L)
        assert 0 < drop <= degree, \
            "L=%d: dropped %d, degree is %d" % (L, drop, degree)
