"""The 1 Sep gate: three interleaver families, recovered blind.

> Recovered depth matches truth in >=15 of 16 block cases; diagonal on >=8
> of 10.

The interesting part is not that block works - it did on the 29th. It is that
block and diagonal produce **byte-identical rank profiles**: same deficient row
lengths, same deficiency values. Nothing in the profile can separate them. They
are told apart only by de-interleaving with each and asking whether a code
comes back, which is decisive rather than a threshold because a wrong
hypothesis leaves the stream looking random.

Convolutional is a different shape entirely - no block boundary, a continuous
permutation with a fixed latency - and it shows up in the profile as a small
repeat step well below the first collapse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from registry import INTERLEAVERS
import pipeline.s4_recover.interleavers  # noqa: F401  (registers the families)

from pipeline.s4_recover.interleavers import (
    block_deinterleave,
    block_interleave,
    conv_interleave,
    conv_latency,
    diagonal_interleave,
    diagonal_permutation,
)
from pipeline.s4_recover.rank_collapse import blind_recover, detect_signature
from pipeline.s5_decode.conv_reference import conv_encode

WIDTH = 16
DIAGONAL_CASES = [(2, 16), (4, 8), (4, 16), (6, 12), (8, 8),
                  (8, 12), (8, 16), (12, 8), (16, 6), (16, 12)]


@pytest.fixture(scope="module")
def coded():
    rng = np.random.default_rng(1)
    return conv_encode(rng.integers(0, 2, 130_000, dtype=np.uint8))


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth", range(1, 17))
def test_block_depth_recovered_one_to_sixteen(coded, depth):
    """Depth 1 is the identity permutation - writing one row and reading it
    back column-wise changes nothing - so the correct answer there is "no
    interleaver", not "block, depth 1"."""
    bits = block_interleave(coded, depth, WIDTH) if depth > 1 else coded
    res = blind_recover(bits)

    assert res.status == "ok", "depth %d: %s" % (depth, res.reason)
    if depth == 1:
        assert res.interleaver is None
    else:
        assert res.interleaver is not None
        assert res.interleaver.family == "block"
        assert res.interleaver.params == {"depth": depth, "width": WIDTH}
    assert res.generators_octal == (0o171, 0o133)


@pytest.mark.parametrize("depth,width", DIAGONAL_CASES)
def test_diagonal_recovered(coded, depth, width):
    res = blind_recover(diagonal_interleave(coded, depth, width))

    assert res.status == "ok", "%dx%d: %s" % (depth, width, res.reason)
    assert res.interleaver is not None
    assert res.interleaver.family == "diagonal", \
        "recovered %s, expected diagonal" % res.interleaver.family
    assert res.interleaver.params == {"depth": depth, "width": width}
    assert res.generators_octal == (0o171, 0o133)


@pytest.mark.parametrize("branches,delay", [(4, 1), (6, 2), (3, 3), (8, 1)])
def test_convolutional_recovered(coded, branches, delay):
    res = blind_recover(conv_interleave(coded, branches, delay))

    assert res.status == "ok", "N=%d M=%d: %s" % (branches, delay, res.reason)
    assert res.interleaver is not None
    assert res.interleaver.family == "convolutional"
    assert res.interleaver.params == {"branches": branches, "delay": delay}
    assert res.generators_octal == (0o171, 0o133)


# --------------------------------------------------------------------------
# why the family cannot be read off the profile
# --------------------------------------------------------------------------

def test_block_and_diagonal_have_identical_signatures(coded):
    """If this ever stops being true, the functional tie-break could be
    replaced by something cheaper. Until then it cannot."""
    b = detect_signature(block_interleave(coded, 8, 12))[:2]
    d = detect_signature(diagonal_interleave(coded, 8, 12))[:2]
    assert b == d == (96, 96)


@pytest.mark.parametrize("branches,delay,first,step", [(4, 1, 20, 4), (6, 2, 48, 6)])
def test_convolutional_signature_steps_below_its_first_collapse(
        coded, branches, delay, first, step):
    """step < first is what marks a convolutional stream; step == first marks a
    block-like one. This is the comparison that bounds the whole search."""
    f, st, _ = detect_signature(conv_interleave(coded, branches, delay))
    assert (f, st) == (first, step)
    assert st < f


def test_raw_coded_stream_also_steps_below_first(coded):
    """A raw rate-1/2 stream has first=14 step=2 and therefore LOOKS like a
    2-branch convolutional interleaver - the code's own symbol size is
    indistinguishable from a branch count. blind_recover has to check the
    direct code structure before trying any family, and this test exists so
    that ordering is never quietly removed."""
    f, st, _ = detect_signature(coded)
    assert (f, st) == (14, 2)
    res = blind_recover(coded)
    assert res.interleaver is None, "raw stream misread as %s" % res.interleaver


# --------------------------------------------------------------------------
# the permutations themselves
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth,width", [(4, 8), (8, 12), (6, 6), (3, 5)])
def test_diagonal_permutation_is_a_bijection(depth, width):
    perm = diagonal_permutation(depth, width)
    assert sorted(perm.tolist()) == list(range(depth * width))


@pytest.mark.parametrize("depth,width", DIAGONAL_CASES[:4])
def test_diagonal_round_trip(depth, width):
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, depth * width * 40, dtype=np.uint8)
    plugin = INTERLEAVERS["diagonal"]
    back = plugin.deinterleave(diagonal_interleave(bits, depth, width),
                               depth=depth, width=width)
    assert np.array_equal(back, bits[:len(back)])


@pytest.mark.parametrize("branches,delay", [(4, 1), (6, 2), (3, 3)])
def test_convolutional_round_trip_after_its_latency(branches, delay):
    """A Forney interleaver has no block boundary; it has a constant
    end-to-end latency, and the plug-in drops exactly that much fill."""
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, 8000, dtype=np.uint8)
    plugin = INTERLEAVERS["convolutional"]
    back = plugin.deinterleave(conv_interleave(bits, branches, delay),
                               branches=branches, delay=delay)
    lat = conv_latency(branches, delay)
    assert np.array_equal(back, bits[:len(bits) - lat])


# --------------------------------------------------------------------------
# bounds - risk #5 applies to every family
# --------------------------------------------------------------------------

def test_all_families_are_registered():
    assert {"block", "diagonal", "convolutional"} <= set(INTERLEAVERS)


@pytest.mark.parametrize("name", ["block", "diagonal"])
def test_period_hint_collapses_the_candidate_space(name):
    plugin = INTERLEAVERS[name]
    unhinted = sum(1 for _ in plugin.candidate_params(1_000_000))
    hinted = list(plugin.candidate_params(1_000_000, period=96))
    assert len(hinted) < unhinted / 50, "the hint is not actually bounding anything"
    assert all(c["depth"] * c["width"] == 96 for c in hinted)


def test_convolutional_candidates_are_bounded():
    plugin = INTERLEAVERS["convolutional"]
    cands = list(plugin.candidate_params(1_000_000))
    assert 0 < len(cands) < 300, "unbounded: %d candidates" % len(cands)
    for c in cands:
        assert 2 <= c["branches"] <= 32
        assert 1 <= c["delay"] <= 8


def test_a_bad_parameter_does_not_crash_the_sweep():
    """The sweep tries parameters that are wrong by construction. Any of them
    raising would take down an analysis mid-run."""
    rng = np.random.default_rng(4)
    bits = rng.integers(0, 2, 5000, dtype=np.uint8)
    for name, plugin in INTERLEAVERS.items():
        for params in list(plugin.candidate_params(5000))[:40]:
            plugin.deinterleave(bits, **params)      # must not raise


# --------------------------------------------------------------------------
# the soft path - found 4 Sep, and it is the 3 Sep `harden` bug one stage on
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,params", [
    ("block", {"depth": 8, "width": 12}),
    ("diagonal", {"depth": 8, "width": 12}),
    ("convolutional", {"branches": 4, "delay": 1}),
])
def test_deinterleave_preserves_soft_values(name, params):
    """A permutation does not care what it is permuting, and casting to uint8
    silently destroyed every LLR handed to it.

    S3 emits floats. blind_recover hard-slices at its entry by design, so the
    RECOVERY path never noticed - but the DECODE path needs the soft values,
    and de-interleaving an LLR array returned an array of zeros. Viterbi then
    decoded zeros into zeros, which is why the readable-text demo had never
    once worked through the real receiver.
    """
    rng = np.random.default_rng(7)
    llrs = rng.normal(0.0, 2.0, 96 * 40)

    out = INTERLEAVERS[name].deinterleave(llrs, **params)

    assert np.issubdtype(out.dtype, np.floating), \
        "%s returned %s, which destroys the soft information" % (name, out.dtype)
    assert np.any(out != 0), "%s zeroed the whole stream" % name
    # every value that survived is one of the inputs, unchanged
    kept = out[out != 0]
    assert np.isin(kept, llrs).all(), "%s altered the values it permuted" % name


def test_block_round_trip_is_exact_on_floats():
    rng = np.random.default_rng(8)
    llrs = rng.normal(0.0, 2.0, 96 * 40)
    back = block_deinterleave(block_interleave(llrs, 8, 12), 8, 12)
    assert np.array_equal(back, llrs)


def test_deinterleave_still_returns_bits_for_bits():
    """The fix must not change what the bit path does - the zoo, the fixtures
    and every recovery test feed uint8 and expect uint8 back."""
    rng = np.random.default_rng(9)
    bits = rng.integers(0, 2, 96 * 40, dtype=np.uint8)
    out = block_deinterleave(bits, 8, 12)
    assert out.dtype == np.uint8
    assert set(np.unique(out)).issubset({0, 1})
