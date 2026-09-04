"""The rotation search: shortest span decides, and screening comes before cost.

Both rules were paid for with measurement rather than reasoning, so both are
pinned here.

Rule 1 (3 Sep, Anvith's, verified from the S4 side): rank rotations by shortest
constraint span. Confidence cannot choose - it is identical for every rotation
that returns a code.

Rule 2 (4 Sep, measured on zoo/corpus/rf): keep the statistical fallback OUT of
the screening pass. Most rotations are wrong BY CONSTRUCTION, and the fallback
spends 8 s of wall clock proving a negative, so running it per rotation pays
the most expensive path on the inputs least likely to reward it. Measured, per
file, with every status identical either way:

    8-PSK  8 dB  8 rotations   70.3 s -> 1.4 s
    QPSK  20 dB  4 rotations   18.1 s -> 1.2 s

and across the whole 36-file RF corpus, worst file 72.1 s -> 32.3 s, total
746 s -> 258 s, recovery unchanged at 26/36 with zero wrong answers.

That is the difference between fitting the 6 September 90-second core-lock
budget and not fitting it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401  (registers the families)
from pipeline.s4_recover.rotations import (
    ROTATION_BUDGET_S,
    recover_over_rotations,
)
from tests.fixtures.local_zoo import make_stream

DEPTH, WIDTH = 8, 12


def as_llr(bits) -> np.ndarray:
    """Bits -> LLRs in this project's convention: positive means bit 0."""
    return np.where(np.asarray(bits, dtype=np.uint8) == 0, 3.0, -3.0)


@pytest.fixture(scope="module")
def rotations():
    """One true stream plus three wrong ones, as S3 would offer them."""
    bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=7)
    rng = np.random.default_rng(7)
    true_llr = as_llr(bits)
    return {
        "truth": truth,
        "cands": [
            as_llr(rng.integers(0, 2, len(bits), dtype=np.uint8)),  # 0: garbage
            true_llr,                                              # 1: correct
            as_llr(1 - np.asarray(bits, dtype=np.uint8)),          # 2: inverted
            as_llr(rng.integers(0, 2, len(bits), dtype=np.uint8)),  # 3: garbage
        ],
    }


def test_the_correct_rotation_wins(rotations):
    choice = recover_over_rotations(rotations["cands"])
    truth = rotations["truth"]

    assert choice is not None
    assert choice.index in (1, 2), "picked rotation %d" % choice.index
    assert choice.result.status == "ok"
    assert choice.result.generators_octal == tuple(truth.polys_octal)
    assert choice.result.interleaver.params == {"depth": truth.depth,
                                                "width": truth.width}


def test_an_inverted_rotation_recovers_identical_parameters(rotations):
    """The rank test is blind to inversion, so 0 and 180 degrees give the same
    interleaver, code and generators. That is exactly why polarity has to be
    settled downstream by printability rather than here."""
    bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=8)
    upright = recover_over_rotations([as_llr(bits)])
    flipped = recover_over_rotations([as_llr(1 - np.asarray(bits, dtype=np.uint8))])

    assert upright is not None and flipped is not None
    assert upright.result.generators_octal == flipped.result.generators_octal
    assert upright.result.interleaver.params == flipped.result.interleaver.params
    assert upright.result.code.span == flipped.result.code.span


def test_screening_avoids_the_fallback_when_a_rotation_succeeds(rotations):
    """The saving that matters. If any rotation recovers on the cheap path, the
    expensive path must never run - not once, not on the losing rotations."""
    choice = recover_over_rotations(rotations["cands"])
    assert choice is not None
    assert choice.used_fallback is False


def test_a_successful_search_is_fast_even_with_many_rotations(rotations):
    """Four rotations, three of them wrong. Before the screening pass this cost
    8 s per wrong rotation; the bound here would have failed then."""
    t0 = time.time()
    recover_over_rotations(rotations["cands"])
    elapsed = time.time() - t0
    assert elapsed < 15.0, "%.0f s for 4 rotations" % elapsed


def test_no_rotation_recovers_returns_none_within_the_budget():
    """The risk #5 case: a file where nothing will be found, which is precisely
    what a judge's out-of-envelope input looks like. The fallback is allowed to
    try, but the whole search is bounded."""
    rng = np.random.default_rng(11)
    noise = [as_llr(rng.integers(0, 2, 80_000, dtype=np.uint8)) for _ in range(4)]

    t0 = time.time()
    choice = recover_over_rotations(noise)
    elapsed = time.time() - t0

    assert choice is None, "claimed a code on four noise rotations"
    assert elapsed < ROTATION_BUDGET_S + 20.0, "%.0f s, budget %.0f s" % (
        elapsed, ROTATION_BUDGET_S)


def test_the_fallback_can_be_switched_off_entirely():
    rng = np.random.default_rng(12)
    noise = [as_llr(rng.integers(0, 2, 80_000, dtype=np.uint8)) for _ in range(3)]

    t0 = time.time()
    assert recover_over_rotations(noise, statistical_fallback=False) is None
    assert time.time() - t0 < 10.0, "the cheap path should be seconds, not tens"


def test_empty_input_is_not_a_crash():
    assert recover_over_rotations([]) is None
