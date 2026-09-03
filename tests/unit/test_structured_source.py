"""A structured payload is not a code, and Stage 4 used to say it was.

Three separate paths could each return `status=ok` on nothing but repeating
ASCII, and all three were found on 3-4 September by pushing real text through
the real receiver rather than random bits through the zoo.

    the statistical fallback   claimed "period=4, rate 1/2 K=2" at 0.59
    the direct reading         claimed "rate 1/6 K=4" and "rate 1/16 K=2"
    nothing at the exit        no single place required a claim to be checkable

The first of those is the one that cost a demo. On the wrong QPSK rotations of
a text-payload stream it returned `ok` with span 4, and span 4 beats the true
span 14 under the shortest-span rotation rule - so the garbage rotation WON
and the text arm of reports/end_to_end.md read 0 of 18 at every SNR, including
16 dB with a bit-perfect demodulation.

The common thread is the one this module keeps relearning: **structure in the
SOURCE looks like structure from a CODE, and only a functional test can tell
them apart.** Deficiency alone cannot - not for the family (block and diagonal
are byte-identical, 1 Sep), not for the period, and not for the block
alignment (see test_the_offset_argmax_is_uninformative_on_a_structured_source).

The guards here are one-sided in the safe direction. Every one of them turns a
confident wrong answer into `low_confidence` with a reason. None of them turns
a correct answer into a refusal - test_random_and_text_arms_agree pins that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401  (registers the families)
from pipeline.s4_recover.rank_collapse import (
    MIN_CODE_MEMORY,
    CodeStructure,
    InterleaverHypothesis,
    RecoveryResult,
    _finalise,
    _residual_syndrome,
    blind_recover,
    detect_signature,
    iter_signatures,
    parity_check_at_span,
    rank_profile,
    recover_code_structure,
    reshape_rows,
    ROW_MARGIN,
)
from pipeline.s4_recover.gf2 import null_space_gf2, rank_gf2
from tests.fixtures.local_zoo import make_stream

DEPTH, WIDTH = 8, 12
PERIOD = DEPTH * WIDTH

# The message the demo actually carries. Its own period (151 characters) is
# LONGER than the interleaver's, which is why it recovers - see the short
# payloads below for what happens when that is not true.
MESSAGE = ("RAAYA SIH26147 -- this message went through a modulator, a noisy "
           "channel and a blind receiver. Nothing about the interleaver or the "
           "code was supplied. ")

# Payloads whose own period is SHORTER than the interleaver's. Each one used
# to produce a confident wrong answer; the number is the collapse its own
# structure creates, measured, well below the true period of 96.
SHORT_PAYLOADS = [
    ("HELLO WORLD", 44),
    ("RAAYA SIH ", 24),
    ("ABCDEFGHIJKLMNOP", 32),
]


@pytest.fixture(scope="module")
def text_stream():
    """The demo message through the real interleaver. Recovers, and must."""
    return make_stream(60_000, DEPTH, WIDTH, seed=1, payload_text=MESSAGE)


# --------------------------------------------------------------------------
# 1. the exit invariant - `ok` has to mean something
# --------------------------------------------------------------------------

def test_ok_requires_an_interleaver_generators_or_real_memory():
    """The bug in one line: nothing anywhere required a claim to be checkable.

    Each branch of blind_recover had its own guards and each was individually
    reasonable. There was no single place they all had to hold, so the path
    that skipped them shipped `ok`. _finalise is that place.
    """
    bare = RecoveryResult("ok", 0.62, period=4,
                          code=CodeStructure(n=4, memory=0, span=4))
    out = _finalise(bare)
    assert out.status == "low_confidence"
    assert out.confidence <= 0.35
    assert "source artefact" in out.reason
    assert out.summary()          # must never raise, whatever the status


def test_finalise_leaves_a_real_recovery_alone():
    """One-sided. The guard may downgrade a claim; it may never invent one."""
    real = RecoveryResult(
        "ok", 0.95, period=PERIOD,
        interleaver=InterleaverHypothesis("block", {"depth": 8, "width": 12}, 1.0),
        code=CodeStructure(n=2, memory=6, span=14),
        generators_octal=(0o171, 0o133))
    assert _finalise(real) is real
    assert real.status == "ok" and real.confidence == 0.95


def test_finalise_admits_a_rate_one_third_code_with_no_generators():
    """Only rate 1/2 unpacks to generators today, so a genuine rate-1/3
    recovery carries neither generators nor an interleaver. Memory is what
    makes it a real claim, and the bar is exactly K >= 3."""
    third = RecoveryResult("ok", 0.95, period=21,
                           code=CodeStructure(n=3, memory=6, span=21))
    assert _finalise(third).status == "ok"

    degenerate = RecoveryResult("ok", 0.95, period=6,
                                code=CodeStructure(n=3, memory=MIN_CODE_MEMORY - 1,
                                                   span=6))
    assert _finalise(degenerate).status == "low_confidence"


# --------------------------------------------------------------------------
# 2. the direct reading is held to the evidence the families always were
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,_first", SHORT_PAYLOADS)
def test_a_source_artefact_has_a_multidimensional_null_space(payload, _first):
    """This is the discriminator, and it is structural rather than a threshold.

    A convolutional code imposes exactly ONE constraint at its own span, so the
    null space there is one-dimensional and that vector is the parity check. A
    structured source imposes many at once - ASCII clears bit 7 of every byte,
    which is a constraint per byte - so its null space at the collapse it
    creates has several dimensions. Measured here: 4, 7 and 19 against the
    code's 1.
    """
    bits, _ = make_stream(60_000, DEPTH, WIDTH, seed=1, payload_text=payload)
    code = recover_code_structure(bits)
    M = reshape_rows(bits, code.span, 0, max_rows=code.span + ROW_MARGIN)
    assert null_space_gf2(M).shape[0] > 1, \
        "artefact at span %s has a unique check - the discriminator is wrong" % code.span
    assert parity_check_at_span(bits, code.span) is None


def test_a_real_code_has_a_one_dimensional_null_space_that_annihilates():
    bits, _ = make_stream(60_000, None, None, seed=12)
    code = recover_code_structure(bits)
    check = parity_check_at_span(bits, code.span)
    assert check is not None, "a genuine rate-1/2 K=7 code must have a unique check"
    assert _residual_syndrome(bits, check, code.n) == 0.0


def test_residual_syndrome_rejects_a_check_fitted_to_too_few_rows():
    """Zero for the true check because it holds on the WHOLE stream, not only
    on the rows the null space saw. That distinction is the whole test."""
    bits, _ = make_stream(60_000, None, None, seed=12)
    code = recover_code_structure(bits)
    check = parity_check_at_span(bits, code.span)
    assert _residual_syndrome(bits, check, code.n) == 0.0

    wrong = np.array(check, dtype=np.uint8).copy()
    wrong[0] ^= 1
    assert _residual_syndrome(bits, wrong, code.n) > 0.0
    assert _residual_syndrome(bits, None, code.n) == 1.0


# --------------------------------------------------------------------------
# 3. the whole chain, on the payloads that used to break it
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,expected_first", SHORT_PAYLOADS)
def test_a_short_repeating_payload_is_never_claimed_as_a_code(payload, expected_first):
    """The safety half, and it is the half that matters for a judge.

    These streams are NOT recovered - see the offset finding below for why -
    and that is an open limitation, stated. What must never happen again is
    the previous behaviour: `ok`, high confidence, a fabricated rate and
    constraint length read straight off the source's own periodicity.
    """
    bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=1, payload_text=payload)

    assert detect_signature(bits)[0] == expected_first, \
        "fixture drifted: the source no longer collapses before the interleaver"

    res = blind_recover(bits)
    assert res.status != "ok", "claimed %s on a structured source" % res.summary()
    assert res.interleaver is None
    assert res.generators_octal is None
    assert res.summary()


def test_the_demo_message_still_recovers_through_the_whole_chain(text_stream):
    """The other side of the same coin. Guards that refuse everything are easy;
    these have to leave the working case working."""
    bits, truth = text_stream
    res = blind_recover(bits)
    assert res.status == "ok", res.reason
    assert res.period == truth.period
    assert res.interleaver is not None
    assert res.interleaver.params == {"depth": truth.depth, "width": truth.width}
    assert res.generators_octal == tuple(truth.polys_octal)


@pytest.mark.parametrize("trim", [0, 5, 37, 59])
def test_the_demo_message_recovers_from_any_start_offset(trim):
    """A real capture never begins on a block boundary. The receiver's group
    delay alone guarantees it, which is why the 3 Sep study saw offset 90."""
    bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=2, payload_text=MESSAGE)
    res = blind_recover(bits[trim:])
    assert res.status == "ok", "trim %d: %s" % (trim, res.reason)
    assert res.interleaver.params == {"depth": truth.depth, "width": truth.width}
    assert res.generators_octal == tuple(truth.polys_octal)
    assert res.offset == (truth.period - trim) % truth.period


def test_random_and_text_arms_agree():
    """The two arms of reports/end_to_end.md differ only in payload. Before the
    fix they differed in outcome too - 15/18 against 0/18. They must not."""
    for payload in (None, MESSAGE):
        bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=3, payload_text=payload)
        res = blind_recover(bits)
        arm = "text" if payload else "random"
        assert res.status == "ok", "%s arm: %s" % (arm, res.reason)
        assert res.interleaver.params == {"depth": truth.depth, "width": truth.width}
        assert res.generators_octal == tuple(truth.polys_octal), arm


# --------------------------------------------------------------------------
# 4. the candidate walk
# --------------------------------------------------------------------------

def test_iter_signatures_yields_successive_collapses(text_stream):
    bits, _ = text_stream
    seen = [first for first, _step, _prof in iter_signatures(bits)]
    assert seen[0] == PERIOD
    assert seen == sorted(seen), "candidates must be offered cheapest first"
    assert len(set(seen)) == len(seen), "a candidate was offered twice"


@pytest.mark.parametrize("payload", ["AB", "ABC"])
def test_the_walk_recovers_a_code_the_source_collapsed_in_front_of(payload):
    """What the walk actually buys, on the case where it is decisive.

    A raw coded stream carrying a 2- or 3-character repeating payload
    collapses at L=8 and L=12 from the SOURCE, before the code's own span of
    14. Taking the smallest collapse gave a fabricated rate and constraint
    length; walking past it recovers the real generators.

    Note this needs BOTH halves of the fix. iter_signatures offers L=14 as a
    later candidate, and recover_code_structure(min_span=...) is what lets the
    direct reading actually be taken there - without it the candidate moves on
    and the code structure is still read at L=8 every time.
    """
    bits, truth = make_stream(60_000, None, None, seed=1, payload_text=payload)

    assert detect_signature(bits)[0] < 14, \
        "fixture drifted: the source no longer collapses before the code"

    res = blind_recover(bits)
    assert res.status == "ok", res.reason
    assert res.generators_octal == tuple(truth.polys_octal)
    assert res.code.memory == 6 and res.code.n == 2


def test_code_structure_can_be_read_from_a_given_span():
    """The `min_span` half, on its own. Reading from the smallest collapse
    gives the source's artefact; reading from 14 gives the code."""
    bits, _ = make_stream(60_000, None, None, seed=1, payload_text="AB")
    artefact = recover_code_structure(bits)
    real = recover_code_structure(bits, min_span=14)
    assert artefact.span < 14
    assert (real.n, real.memory, real.span) == (2, 6, 14)
    assert real.consistent


def test_detect_signature_still_returns_only_the_first_collapse():
    """The walk is new; detect_signature's contract is not. reports/ and the
    family tests both read (first, step) from it."""
    bits, _ = make_stream(60_000, DEPTH, WIDTH, seed=1)
    assert detect_signature(bits)[:2] == (PERIOD, PERIOD)

    bits, _ = make_stream(60_000, None, None, seed=1)
    assert detect_signature(bits)[:2] == (14, 2)


def test_uncoded_data_offers_no_candidates_at_all():
    """Risk #5 and risk #15 in one test. The walk must not make the judge's
    first input - uncoded random data - any more expensive than it was, and
    the reason it does not is that there is nothing to walk: no collapse
    anywhere means no candidates, not many candidates."""
    rng = np.random.default_rng(4)
    noise = rng.integers(0, 2, 80_000, dtype=np.uint8)
    cands = list(iter_signatures(noise))
    assert len(cands) == 1
    first, step, _prof = cands[0]
    assert first is None and step is None


def test_the_walk_is_bounded(text_stream):
    bits, _ = text_stream
    assert len(list(iter_signatures(bits, max_candidates=3))) <= 3


# --------------------------------------------------------------------------
# 5. the limitation, measured rather than asserted away
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,_first", SHORT_PAYLOADS[:1])
def test_the_offset_argmax_is_uninformative_on_a_structured_source(payload, _first):
    """Why the short payloads above are refused rather than recovered.

    The block boundary is chosen by argmax of deficiency over offsets, and on
    a structured source that argmax carries no signal: the TRUE offset sits
    within one of the maximum, and so do dozens of others. Measured on this
    fixture the true offset ranks 39th of 96 while being one deficiency below
    the best.

    So the alignment cannot be resolved by the curve, exactly as the FAMILY
    cannot (block and diagonal are byte-identical) and the PERIOD cannot. It
    needs the same treatment - try candidates functionally - but a functional
    test per offset is a family search per offset, which does not fit the 90 s
    budget. That is the open item, and this test exists to fail loudly if the
    situation ever improves on its own.
    """
    bits, _ = make_stream(60_000, DEPTH, WIDTH, seed=1, payload_text=payload)
    defs = [PERIOD - rank_gf2(reshape_rows(bits, PERIOD, off,
                                           max_rows=PERIOD + ROW_MARGIN))
            for off in range(PERIOD)]
    true_off = 0                       # this fixture is not trimmed
    order = sorted(range(PERIOD), key=lambda i: -defs[i])

    assert max(defs) - defs[true_off] <= 1, \
        "the true offset is no longer near-maximal; revisit the whole finding"
    assert order.index(true_off) > 10, \
        "the argmax now finds the true offset - a ranked-offset search is " \
        "worth implementing, see the docstring"


def test_the_same_stream_with_a_random_payload_aligns_on_the_argmax():
    """The control. Nothing is wrong with the argmax itself - it is exactly
    right when the source is unstructured, which is why this went unnoticed
    until a real message went through."""
    bits, _ = make_stream(60_000, DEPTH, WIDTH, seed=1)
    defs = [PERIOD - rank_gf2(reshape_rows(bits, PERIOD, off,
                                           max_rows=PERIOD + ROW_MARGIN))
            for off in range(PERIOD)]
    assert int(np.argmax(defs)) == 0
