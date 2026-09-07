"""The 6 September column: the REAL CCSDS 131.0-B transmit order, peeled blind.

Why this file exists alongside `test_ccsds_chain.py`, which already claims a
concatenated profile decodes end to end. That file measures the Command
Center's stated layer order:

    RS -> BIT-interleave -> convolutional -> scrambler on the channel

and the real standard's order is a different chain, not a relabelling of the
same one:

    RS -> BYTE-interleave (depth I) -> randomise -> convolutional

Two differences, and each one breaks a different assumption:

  * the randomiser sits INSIDE the convolutional code, so it survives Viterbi
    and is still on the decoded stream. `recover_scrambler` cannot help there:
    it needs a parity check to take a syndrome against, and after Viterbi the
    only code left is Reed-Solomon, whose binary-image constraints sit at
    L = 2040 - an order of magnitude past anything the rank sweep reaches.
  * the interleaver permutes SYMBOLS, not bits. The eight bits of an RS byte
    travel together and only the byte's position moves, so a bit-level
    de-interleaver of any (depth, width) cannot undo it.

MEASURED BEFORE THE FIX, on `zoo.ccsds.make_ccsds_stream` at depths 1 and 4:
`recover_ccsds` peeled the convolutional layer, recovered (0o171, 0o133)
exactly, ran Viterbi, and then returned `partial` with "no de-interleaving
produced a Reed-Solomon codeword". That was a true statement about a search
that could not have succeeded - the honest failure, but a failure.

The corpus files these tests mirror are Dheeraj's `zoo/corpus/ccsds/`, built to
the standard order at his end from a written request. The generator is his and
this receiver is mine, which is the property worth having: the interleaver and
the randomiser below are checked against HIS implementation, not against a
second copy of my own assumptions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401  (registers families)
import pipeline.s5_decode.conv_code      # noqa: F401  (registers conv)
import pipeline.s5_decode.rs_code        # noqa: F401  (registers RS)
from pipeline.s4_recover.interleavers import (
    CCSDS_DEPTHS, symbol_deinterleave, symbol_interleave)
from pipeline.s6_frame.ccsds import recover_ccsds
from pipeline.s6_frame.descramble import (
    CCSDS_RANDOMISER, CORPUS_RANDOMISER, STANDARD_RANDOMISERS,
    additive_keystream, descramble_known)
from registry import INTERLEAVERS
from zoo.bits_only import CCSDS_SCRAMBLER, lfsr_scramble
from zoo.ccsds import ccsds_interleave, make_ccsds_stream

MSG = ("RAAYA SIH26147 -- real CCSDS 131.0-B transmit order: Reed-Solomon "
       "outer, symbol interleaving, pseudo-randomiser, convolutional inner. ")


# --------------------------------------------------------------------------
# the two primitives, each pinned against an INDEPENDENT implementation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth", CCSDS_DEPTHS)
def test_symbol_interleaver_agrees_with_the_generators_own(depth):
    """Two implementations of one permutation, and they must agree exactly.

    `zoo.ccsds.ccsds_interleave` works on a list of byte codewords; the one
    under test works on a flat bit stream, because that is what a receiver
    holds. Agreeing bit for bit is the only thing that makes a recovery result
    mean anything - the same reason `conv_reference` is pinned against commpy
    rather than trusted for reading well.
    """
    rng = np.random.default_rng(3)
    n = 255
    codewords = [bytes(rng.integers(0, 256, n, dtype=np.uint8))
                 for _ in range(depth * 2)]
    reference = ccsds_interleave(codewords, depth)

    src_bits = np.unpackbits(np.frombuffer(b"".join(codewords), dtype=np.uint8))
    mine = symbol_interleave(src_bits, depth, n)

    assert np.packbits(mine).tobytes() == reference
    assert np.array_equal(symbol_deinterleave(mine, depth, n), src_bits)


@pytest.mark.parametrize("depth", (2, 4, 8))
def test_symbol_interleaving_spreads_a_burst_across_codewords(depth):
    """The property the standard is FOR, not just the permutation's algebra.

    A channel burst damages a run of consecutive TRANSMITTED bytes. If
    interleaving works, those land in `depth` different codewords, because
    RS(255,223) corrects 16 symbol errors in one codeword and nothing beyond
    that in the same one.
    """
    n = 255
    codewords = [bytes([i] * n) for i in range(depth)]   # codeword c is all c
    tx = np.frombuffer(ccsds_interleave(codewords, depth), dtype=np.uint8)
    burst = tx[10:10 + depth]                            # consecutive on the wire
    assert len(set(burst.tolist())) == depth             # ... all different codewords


def test_known_randomiser_matches_the_generators_lfsr():
    """The receiver's keystream against the one the corpus was built with.

    Same class of check as the interleaver above. An additive scrambler that is
    one bit out of phase, or shifted the other way, descrambles to noise and
    raises nothing at all.
    """
    assert CORPUS_RANDOMISER == CCSDS_SCRAMBLER

    rng = np.random.default_rng(7)
    bits = rng.integers(0, 2, 5000, dtype=np.uint8)
    scrambled = lfsr_scramble(bits, CCSDS_SCRAMBLER, 0xFF)

    assert np.array_equal(additive_keystream(CORPUS_RANDOMISER, 0xFF, len(bits)),
                          scrambled ^ bits)
    assert np.array_equal(descramble_known(scrambled, CORPUS_RANDOMISER), bits)


def test_the_blue_books_randomiser_is_in_the_table_and_is_not_the_corpus_one():
    """The corpus randomiser is MISLABELLED, and the table must not inherit it.

    `zoo.bits_only.CCSDS_SCRAMBLER` is 0o435 under a docstring naming
    h(x) = x^8 + x^7 + x^5 + x^3 + 1. It is not that polynomial:

        0o435 = 285 = 0x11D = x^8 + x^4 + x^3 + x^2 + 1   <- RS field polynomial
        0o651 = 425 = 0x1A9 = x^8 + x^7 + x^5 + x^3 + 1   <- CCSDS 131.0-B

    Not a malfunction - both are primitive of degree 8, so both give a
    period-255 additive scrambler and every number measured against the corpus
    stands. But a table of "known standard profiles" whose standard entry is
    not the standard would decline the one stream it exists to catch, so both
    are carried and this pins which is which.
    """
    def poly_bits(v):
        return {i for i in range(v.bit_length()) if (v >> i) & 1}

    assert poly_bits(CCSDS_RANDOMISER) == {8, 7, 5, 3, 0}
    assert poly_bits(CORPUS_RANDOMISER) == {8, 4, 3, 2, 0}
    assert CCSDS_RANDOMISER != CORPUS_RANDOMISER

    names = [n for n, _p, _s in STANDARD_RANDOMISERS]
    assert "ccsds-131.0-B" in names, "the blue book's own randomiser is not tried"
    polys = {p for _n, p, _s in STANDARD_RANDOMISERS}
    assert {CCSDS_RANDOMISER, CORPUS_RANDOMISER} <= polys

    # both must be genuinely period-255, or the keystream tiling is wrong
    for poly in (CCSDS_RANDOMISER, CORPUS_RANDOMISER):
        ks = additive_keystream(poly, 0xFF, 2000)
        period = next(p for p in range(1, 1000)
                      if np.array_equal(ks[:1000], ks[p:p + 1000]))
        assert period == 255, "0o%o has period %d, not 255" % (poly, period)


def test_the_randomiser_period_is_measured_not_assumed():
    """255, and read off the sequence rather than off the polynomial's degree.

    A non-primitive polynomial has a shorter period, and `additive_keystream`
    tiles one measured period rather than assuming 2^d - 1. A fixture in this
    repo has already carried a polynomial mislabelled as maximal-length once
    (period 7, not 63), which is why this is asserted and not read.
    """
    ks = additive_keystream(CCSDS_RANDOMISER, 0xFF, 2000)
    period = next(p for p in range(1, 1000)
                  if np.array_equal(ks[:1000], ks[p:p + 1000]))
    assert period == 255


def test_the_symbol_family_is_registered():
    """Reachable by name through the registry, like every other family."""
    assert "ccsds-symbol" in INTERLEAVERS
    plugin = INTERLEAVERS["ccsds-symbol"]
    depths = [p["depth"] for p in plugin.candidate_params(8 * 255 * 8 * 8)]
    assert depths == list(CCSDS_DEPTHS)
    # 0 means "the rank sweep will not find this one" - see the docstring.
    assert plugin.rank_signature(depth=4) == 0


# --------------------------------------------------------------------------
# the gate: four layers off a stream built to the real standard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("depth", (1, 4))
def test_the_real_transmit_order_peels_to_a_byte_exact_payload(depth):
    """The 6 Sep gate. Nothing about any of the four layers is supplied.

    depth 1 and depth 4 are both here on purpose. I=1 is a legal CCSDS profile
    meaning "no interleaving", and it is the arm that would pass by accident if
    the symbol de-interleaver were broken but the randomiser were right - so a
    depth that actually permutes has to be in the gate beside it.

    Cost is ~30 s each and it is almost all Viterbi (commpy is pure Python).
    Two depths, not six: `zoo`'s own round-trip test covers the generator at
    every depth, and what this file is for is the receiver.
    """
    bits, payload, meta = make_ccsds_stream(n_blocks=8, depth=depth,
                                            payload_text=MSG, seed=11)
    assert meta["pipeline_order"] == ["rs_encode", "byte_interleave",
                                      "randomise", "conv_encode"]

    res = recover_ccsds(bits)

    assert res.status == "ok", res.reason
    assert res.generators_octal == (0o171, 0o133)
    assert res.stages.get("derandomise") is True
    # the corpus is built with 0o435, not the blue book's 0o651 - see
    # test_the_blue_books_randomiser_is_in_the_table_and_is_not_the_corpus_one
    assert res.randomiser == "zoo-corpus-0o435"
    assert res.rs_params.n == 255 and res.rs_params.k == 223
    assert res.rs_params.errata_rate == 0.0

    if depth == 1:
        assert res.interleaver is None          # I=1 is the identity
    else:
        assert res.interleaver == {"family": "ccsds-symbol", "depth": depth,
                                   "n_bytes": 255}

    assert res.payload[:len(payload)] == payload


def test_uncoded_noise_is_not_claimed_as_a_real_order_profile():
    """The false-positive guard, restated for the paths added today.

    Two more hypotheses were added to the search - a known randomiser and a
    symbol interleaver - and every widening of a search is a new way to find
    something that is not there. RS(255,223) accepting a block requires every
    one of four blocks to decode with zero corrections, so this should be
    impossible rather than merely unlikely; it is asserted because "should be"
    is not a measurement.
    """
    rng = np.random.default_rng(99)
    noise = rng.integers(0, 2, 40_000, dtype=np.uint8)
    res = recover_ccsds(noise)
    assert res.status != "ok"
    assert res.payload == b""
