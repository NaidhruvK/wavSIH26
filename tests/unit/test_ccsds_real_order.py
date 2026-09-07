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
    CCSDS_RANDOMISER, LEGACY_ZOO_RANDOMISER, STANDARD_RANDOMISERS,
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
    assert CCSDS_RANDOMISER == CCSDS_SCRAMBLER, (
        "the generator and the blue book have diverged again - 9b4c524 made "
        "zoo.bits_only.CCSDS_SCRAMBLER 0o651, and this table must follow it")

    rng = np.random.default_rng(7)
    bits = rng.integers(0, 2, 5000, dtype=np.uint8)
    scrambled = lfsr_scramble(bits, CCSDS_SCRAMBLER, 0xFF)

    assert np.array_equal(additive_keystream(CCSDS_RANDOMISER, 0xFF, len(bits)),
                          scrambled ^ bits)
    assert np.array_equal(descramble_known(scrambled, CCSDS_RANDOMISER), bits)


def test_the_blue_book_randomiser_is_the_generators_and_the_legacy_one_is_kept():
    """The 6 Sep mislabel, now fixed on the generator side - pinned both ways.

    On 6 Sep `zoo.bits_only.CCSDS_SCRAMBLER` was 0o435 under a docstring naming
    h(x) = x^8 + x^7 + x^5 + x^3 + 1, which is a different polynomial:

        0o435 = 285 = 0x11D = x^8 + x^4 + x^3 + x^2 + 1   <- RS field polynomial
        0o651 = 425 = 0x1A9 = x^8 + x^7 + x^5 + x^3 + 1   <- CCSDS 131.0-B

    `9b4c524` corrected the CONSTANT rather than the comment, so the generator
    now emits the blue book's randomiser and the corpus was regenerated. This
    asserts the agreement rather than assuming it - the same class of check that
    caught the disagreement in the first place.

    0o435 stays in the table, demoted: it is NOT a standard, it is the RS field
    polynomial, and it is carried only so a pre-`9b4c524` capture still
    descrambles. Both must be genuinely period-255 or the keystream tiling is
    wrong, which is the property that made the original mislabel harmless.
    """
    def poly_bits(v):
        return {i for i in range(v.bit_length()) if (v >> i) & 1}

    assert poly_bits(CCSDS_RANDOMISER) == {8, 7, 5, 3, 0}
    assert poly_bits(LEGACY_ZOO_RANDOMISER) == {8, 4, 3, 2, 0}
    assert CCSDS_RANDOMISER != LEGACY_ZOO_RANDOMISER

    # the generator now carries the blue book's, which is the 9b4c524 fix
    assert CCSDS_SCRAMBLER == CCSDS_RANDOMISER

    names = [n for n, _p, _s in STANDARD_RANDOMISERS]
    assert "ccsds-131.0-B" in names, "the blue book's own randomiser is not tried"
    polys = {p for _n, p, _s in STANDARD_RANDOMISERS}
    assert {CCSDS_RANDOMISER, LEGACY_ZOO_RANDOMISER} <= polys

    # both must be genuinely period-255, or the keystream tiling is wrong
    for poly in (CCSDS_RANDOMISER, LEGACY_ZOO_RANDOMISER):
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
def test_the_ccsds_randomiser_is_invisible_to_the_reed_solomon_decoder():
    """WHY THE RANDOMISER IS SETTLED ON THE PAYLOAD. Structural, not chance.

    The CCSDS 131.0-B randomiser is an LFSR of period 255 BITS. An RS(255,223)
    block is 255 bytes = 2040 bits = exactly 8 whole periods, so every codeword
    in the stream is XORed with the SAME 255-byte pattern K.

    And K is itself an exact RS codeword - it decodes with ZERO errata, which
    is what this test pins. Reed-Solomon is linear over GF(256), so for any
    codeword C:

        C + K  is a codeword, exactly, with no errors to correct.

    So "RS decoded every block at errata_rate 0.0" carries NO information about
    whether the randomiser was removed. It is not a weak signal or a rare
    coincidence - the transformation maps the code onto itself. The same is
    true in reverse: applying the randomiser to an UN-randomised stream also
    yields codewords, so the ambiguity cannot be fixed by reordering the
    hypotheses either. Only the payload can tell the two apart.

    `0o435` did not have this property, which is the only reason the 6 September
    gate passed: the chain was being judged by a randomiser that happened to
    break the code. `9b4c524` corrected the constant to the real one and the
    property arrived with it - the chain then accepted the no-randomiser
    hypothesis at errata_rate 0.0 and returned a payload XORed with a fixed
    pattern, while reporting status=ok. `_resolve_randomiser` is the fix.
    """
    import reedsolo

    for poly, expect_codeword in ((CCSDS_RANDOMISER, True),
                                  (LEGACY_ZOO_RANDOMISER, False)):
        ks = additive_keystream(poly, 0xFF, 255 * 8)      # 255 bytes
        K = np.packbits(np.asarray(ks, dtype=np.uint8)).tobytes()
        assert len(K) == 255

        try:
            _dec, _full, errata = reedsolo.RSCodec(32).decode(bytearray(K))
            is_codeword, n_errata = True, len(errata)
        except reedsolo.ReedSolomonError:
            is_codeword, n_errata = False, None

        assert is_codeword is expect_codeword, (
            "0o%o: RS(255,223) codeword = %s, expected %s"
            % (poly, is_codeword, expect_codeword))
        if expect_codeword:
            assert n_errata == 0, (
                "0o%o's keystream needed %d corrections; the invisibility "
                "argument depends on it being an EXACT codeword" % (poly, n_errata))


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
    assert res.randomiser == "ccsds-131.0-B"
    # RS accepted the no-randomiser hypothesis too, at errata_rate 0.0 - the
    # payload is what separated them. Assert that, or a regression to
    # first-accept would pass this test again on garbage.
    assert res.randomiser_ambiguous is False
    assert "payload layer" in res.randomiser_note
    assert res.rs_params.n == 255 and res.rs_params.k == 223
    assert res.rs_params.errata_rate == 0.0

    if depth == 1:
        assert res.interleaver is None          # I=1 is the identity
    else:
        assert res.interleaver == {"family": "ccsds-symbol", "depth": depth,
                                   "n_bytes": 255}

    assert res.payload[:len(payload)] == payload


def test_a_random_payload_is_declined_rather_than_guessed():
    """The other half of `_resolve_randomiser`, and the reason it uses entropy.

    On a payload that was random to begin with, removing the randomiser exposes
    no structure - both hypotheses decode to something incompressible, both are
    valid RS codewords, and NOTHING can separate them. That is not a gap in the
    discriminator, it is a true statement about the stream.

    So the chain must decline. A confident answer here would be a coin flip
    reported as a measurement, which is precisely the failure that made this
    function necessary. `partial` with the candidates named is the honest
    result, and it is what an orchestrator can act on.

    This is also why the measure is entropy rather than the printable fraction
    used elsewhere: printability would have answered "neither is text" and said
    nothing about which is right.
    """
    bits, _payload, _meta = make_ccsds_stream(n_blocks=8, depth=1,
                                              payload_text=None, seed=11)
    res = recover_ccsds(bits)

    assert res.status == "partial"
    assert res.randomiser_ambiguous is True
    assert res.randomiser is None, "declined, so no randomiser may be claimed"
    assert "cannot separate them" in res.reason
    # and it must say so because the margin was small, not for some other reason
    assert "margin" in res.reason


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
