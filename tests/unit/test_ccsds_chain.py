"""The 5 September gate: the concatenated CCSDS profile, peeled off blind.

    Command Center, 5 Sep, Nehal:
      task   "Concatenated CCSDS chain: RS outer -> interleaver ->
              convolutional inner -> scrambler, recovered and decoded in
              sequence."
      done   "Full concatenated profile decodes end to end."
      verify "Known payload text appears correctly from a CCSDS-profile file."

Four coding layers, none supplied. This is the artefact that answers the whole
problem statement in one file.

TWO THINGS TODAY OVERTURNED, both of them mine:

1. The interleaver is INVISIBLE to the rank test in this ordering. Every
   earlier study here interleaved the convolutional CODEWORD, whose parity
   constraints are local (span 14), so permuting them moved the collapse to
   the interleaver period. CCSDS interleaves the RS codeword instead, and a
   permutation preserves rank over GF(2). I measured a collapse at 96 on one
   file and reported the interleaver was visible; it was the ASCII payload's
   own structure, and it moved when I changed the message. With a random
   payload there is no deficiency anywhere.

2. The scrambler's chicken-and-egg is breakable. `recover_scrambler` needs the
   code's parity check and the scrambler hides the code, so neither goes
   first - but r[n] XOR r[n+P] cancels an additive scrambler at any shift P
   that is a multiple of both its period and the symbol size, leaving the XOR
   of two codewords, which is a codeword. Searching P with the RANK test needs
   no parity check, and the code recovered from the difference unlocks the
   rest.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401  (registers families)
import pipeline.s5_decode.conv_code      # noqa: F401  (registers conv)
import pipeline.s5_decode.rs_code        # noqa: F401  (registers RS)
from pipeline.s4_recover.interleavers import block_deinterleave
from pipeline.s4_recover.rank_collapse import blind_recover, rank_profile
from pipeline.s5_decode.conv_reference import parity_check_taps
from pipeline.s6_frame.ccsds import (
    _interleaver_candidates,
    _rs_screen,
    find_scrambler_period_blind,
    recover_ccsds,
)
from tests.fixtures.local_zoo import CCSDS_SCRAMBLER, lfsr_scramble, make_ccsds_stream

MSG = ("RAAYA SIH26147 -- concatenated CCSDS profile: Reed-Solomon outer, "
       "block interleaver, convolutional inner, and a randomiser on top. ")
DEPTH, WIDTH = 8, 12


@pytest.fixture(scope="module")
def clean():
    return make_ccsds_stream(40, DEPTH, WIDTH, scramble=False, seed=1,
                             payload_text=MSG)


@pytest.fixture(scope="module")
def scrambled():
    return make_ccsds_stream(40, DEPTH, WIDTH, scramble=True, seed=1,
                             payload_text=MSG)


# --------------------------------------------------------------------------
# the fixture itself, before anything is asked to recover from it
# --------------------------------------------------------------------------

def test_the_generator_inverts_with_known_parameters(scrambled):
    """Prove the transmit chain before testing the receive chain. A fixture
    that is wrong makes every recovery number meaningless, and that lesson
    cost this project a day when the zoo's scrambler period was mislabelled."""
    bits, truth, _payload = scrambled
    unscrambled = lfsr_scramble(bits, CCSDS_SCRAMBLER)      # XOR is its own inverse
    h = parity_check_taps()
    win = np.lib.stride_tricks.sliding_window_view(unscrambled, len(h))[::2]
    assert float(((win @ h) % 2).mean()) == 0.0, \
        "the inner convolutional layer does not check out - fixture is wrong"


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def test_concatenated_profile_decodes_end_to_end(clean):
    bits, truth, payload = clean
    res = recover_ccsds(bits)

    assert res.status == "ok", res.summary()
    assert res.generators_octal == tuple(truth.polys_octal)
    assert res.interleaver == {"family": "block", "depth": DEPTH, "width": WIDTH}
    assert res.rs_params is not None and res.rs_params.n == 255 and res.rs_params.k == 223
    assert res.payload[:200] == payload[:200], "decoded payload is not the transmitted one"
    assert "RAAYA SIH26147" in res.text
    assert res.printable_fraction > 0.99


def test_concatenated_profile_decodes_through_a_scrambler(scrambled):
    """The verify line, with all four layers present."""
    bits, truth, payload = scrambled
    res = recover_ccsds(bits)

    assert res.status == "ok", res.summary()
    assert res.stages.get("descramble"), "the scrambler was never peeled"
    assert res.generators_octal == tuple(truth.polys_octal)
    assert res.interleaver == {"family": "block", "depth": DEPTH, "width": WIDTH}
    assert res.payload[:200] == payload[:200]
    assert "RAAYA SIH26147" in res.text


# --------------------------------------------------------------------------
# the two findings, pinned so they cannot be quietly un-learned
# --------------------------------------------------------------------------

def test_the_interleaver_is_invisible_to_the_rank_test_here():
    """A permutation preserves rank over GF(2). With a RANDOM payload there is
    no deficiency at any searchable row length, so no rank-curve-driven search
    could ever find this interleaver. If this test starts failing, something
    about the chain changed and `_interleaver_candidates` should be revisited -
    it does not read the curve for exactly this reason."""
    bits, truth, _payload = make_ccsds_stream(40, DEPTH, WIDTH, scramble=False,
                                              seed=2, payload_text=None)
    res = blind_recover(bits)
    assert res.status == "ok" and res.generators_octal == tuple(truth.polys_octal)

    from registry import CODES
    decoded = np.asarray(CODES["conv"].decode(bits[:48_000], {
        "n": res.code.n, "memory": res.code.memory,
        "generators_octal": res.generators_octal,
        "span": res.code.span, "parity_taps": res.parity_taps}), dtype=np.uint8)

    prof = rank_profile(decoded, 8, 200)
    assert prof.nonzero() == [], \
        "the decoded stream is now rank deficient at %s - the structural " \
        "claim in _interleaver_candidates needs re-checking" % prof.nonzero()


def test_the_convolutional_layer_is_read_directly_with_no_interleaver(clean):
    """On the channel stream the interleaver is genuinely not there - it is one
    layer further in. `interleaver=none` is the CORRECT answer at this point,
    not a miss."""
    bits, truth, _payload = clean
    res = blind_recover(bits)
    assert res.status == "ok"
    assert res.interleaver is None
    assert res.code.span == 14
    assert res.generators_octal == tuple(truth.polys_octal)


def test_self_difference_finds_the_scrambler_without_a_parity_check(scrambled):
    """The chicken-and-egg breaker. No parity check is passed in."""
    bits, truth, _payload = scrambled
    shift, res = find_scrambler_period_blind(bits)

    assert shift is not None, "no self-difference shift exposed the code"
    assert res.generators_octal == tuple(truth.polys_octal)
    assert shift % 2 == 0, "a shift that is not a whole number of symbols " \
                           "cannot cancel to a codeword"


# --------------------------------------------------------------------------
# the search is bounded and the oracle does not fire on noise
# --------------------------------------------------------------------------

def test_the_rs_screen_rejects_wrong_de_interleavings(clean):
    """The screen must be a cheap NO, never a cheap yes. One hit on the whole
    grid, and it is the true one."""
    bits, truth, _payload = clean
    res = blind_recover(bits)
    from registry import CODES
    decoded = np.asarray(CODES["conv"].decode(bits[:48_000], {
        "n": res.code.n, "memory": res.code.memory,
        "generators_octal": res.generators_octal,
        "span": res.code.span, "parity_taps": res.parity_taps}), dtype=np.uint8)

    hits = [(d, w) for d, w in _interleaver_candidates(decoded)
            if _rs_screen(block_deinterleave(decoded, d, w))]
    assert hits == [(DEPTH, WIDTH)], "screen hits were %s" % hits


def test_the_scrambler_screen_actually_screens(scrambled):
    """The guard that was missing, and its absence cost a 53x slowdown.

    `b431082` moved SCREEN_ROW_LEN from 14 to 60 - correctly, because 14 is the
    span of rate-1/2 K=7 and nothing else, so the screen rejected every other
    code in the envelope. Nothing tested the OTHER half of the screen's job.
    With the test still written as "deficiency > 0", L=60 admitted **255 of 255
    shifts**, every one paid for a full `blind_recover`, and this search went
    from about a second to 268 s - on its own, past the 90 s core-lock budget
    for the entire seven-stage analysis. Every test still passed. Only the
    clock knew.

    The reason a bare threshold cannot work here is structural: the sum of two
    codewords is a codeword at EVERY shift that is a whole number of symbols -
    that is the premise the method rests on - so the code's own deficiency is
    present at every shift, and only its SIZE separates the true one. Measured:
    254 wrong shifts at deficiency 16, the true shift at 24, no overlap.

    So this asserts the property, not the implementation: the search must
    return the right answer AND must not pay for the whole space to do it.
    The bound is deliberately loose - it is there to catch a 50x regression on
    a busy machine, not to measure performance.
    """
    bits, truth, _payload = scrambled

    t0 = time.time()
    shift, res = find_scrambler_period_blind(bits)
    elapsed = time.time() - t0

    assert shift == 510, "expected lcm(255, 2); got %s" % shift
    assert res.generators_octal == tuple(truth.polys_octal)
    assert elapsed < 60.0, (
        "the self-difference search took %.0f s. It searches 255 shifts and "
        "only a handful should ever reach `blind_recover` - check that the "
        "deficiency screen still separates the true shift from the floor "
        "rather than admitting everything." % elapsed)


def test_uncoded_noise_is_not_claimed_as_a_ccsds_profile():
    """Risk #15 applied to the whole chain. Four layers of claim is four times
    the damage if any of it is invented."""
    rng = np.random.default_rng(5)
    noise = rng.integers(0, 2, 120_000, dtype=np.uint8)

    res = recover_ccsds(noise)

    assert res.status != "ok", "claimed a CCSDS profile in noise: %s" % res.summary()
    assert not res.payload
    assert res.summary()
