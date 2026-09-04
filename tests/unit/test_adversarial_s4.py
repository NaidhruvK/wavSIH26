"""The 8 September gate, brought forward to the 4th because it was failing.

> Adversarial inputs to S4: all-zeros, all-ones, uncoded random, wrong rate,
> truncated stream. Reports "no code structure detected" rather than
> hallucinating one. Uncoded random data must NOT produce a false code
> detection. The false-positive test that matters most.

Every stream in this file is NOT convolutionally coded. Any `status == "ok"`
here is a false positive, and a false positive is the one failure that cannot
be spotted by looking at the screen - it is risk #15, and it is what a judge
reaches for first.

WHAT THIS FOUND, 4 September. Run against the code as it stood that morning,
six of these twelve returned `ok`:

    all ones                     ok 0.70  "block(depth=...)"
    alternating 0101             ok 0.70  "G=(0o1, 0o1)" + an interleaver
    period-8 pattern             ok 0.70  "block(depth=...)"
    uncoded ASCII short-repeat   ok 0.70  a convolutional interleaver
    uncoded ASCII, interleaved   ok 0.70  "block(depth=...)"
    biased 70/30                 ok 0.63  "rate 1/1 K=4, inferred BER 0.3015"

None of them was a regression - all six predate 3 September. They survived
because every existing false-positive test used UNIFORM random data, which
this module has always handled correctly. Uniform random is the one input a
rank test finds easy. Degenerate and merely PATTERNED streams are the hard
case and nothing was testing them.

The last one is the most instructive. 0.3015 is 1 - 0.7 to three decimals: the
syndrome test was measuring the source's own bias and reporting it back as the
channel's error rate. A biased i.i.d. stream makes EVERY parity check biased.

Three guards closed them, all structural rather than tuned:

    code_signature_holds()   a rate-1/n code constrains its stream ONLY at
                             multiples of n. Degenerate streams are deficient
                             everywhere, including odd lengths. Documented in
                             rank_collapse.py since 29 Aug; never enforced.
    MIN_CODE_MEMORY          applied on the INTERLEAVER path too, which never
                             had it - `_finalise` treats "an interleaver was
                             identified" as sufficient, so a hypothesis backed
                             by a memory-0 "code" walked through the exit.
    n >= 2, implied BER      a rate-1/1 code has no redundancy to recover, and
                             an implied error rate outside the method's own
                             measured 3% ceiling is not a code seen through
                             noise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401  (registers the families)
from pipeline.s4_recover.interleavers import block_interleave, diagonal_interleave
from pipeline.s4_recover.rank_collapse import (
    InterleaverHypothesis,
    RecoveryResult,
    blind_recover,
    code_signature_holds,
)
from pipeline.s5_decode.conv_reference import conv_encode
from tests.fixtures.local_zoo import make_stream

N = 120_000

ASCII_LONG = ("RAAYA SIH26147 telemetry frame header repeats every frame and "
              "this is plain uncoded ASCII with no error correcting code in it. ")
ASCII_SHORT = "HELLO WORLD"


def _ascii_bits(text: str, n: int = N) -> np.ndarray:
    raw = (text * (n // (8 * len(text)) + 2)).encode()
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n]


def _cases():
    rng = np.random.default_rng(20260904)
    uncoded_ascii = _ascii_bits(ASCII_LONG)
    short_ascii = _ascii_bits(ASCII_SHORT)
    return {
        "uniform random": rng.integers(0, 2, N, dtype=np.uint8),
        "all zeros": np.zeros(N, dtype=np.uint8),
        "all ones": np.ones(N, dtype=np.uint8),
        "alternating 0101": np.tile([0, 1], N // 2).astype(np.uint8),
        "period-8 pattern": np.tile([1, 0, 1, 1, 0, 0, 0, 1], N // 8).astype(np.uint8),
        "uncoded ASCII": uncoded_ascii,
        "uncoded ASCII short-repeat": short_ascii,
        "uncoded ASCII interleaved": block_interleave(uncoded_ascii, 8, 12),
        "uncoded ASCII diagonal": diagonal_interleave(short_ascii, 8, 12),
        "biased 70/30": (rng.random(N) < 0.7).astype(np.uint8),
        "LLR noise (float)": rng.normal(0.0, 1.5, N),
    }


CASES = _cases()


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_uncoded_stream_is_ever_claimed_as_a_code(name):
    """The gate. `low_confidence` and `failed` are both fine answers here -
    the stream really does have structure in several of these cases. What is
    not fine is `ok`, which is the word the UI renders as a recovery."""
    res = blind_recover(CASES[name])

    assert res.status != "ok", "claimed %s on %s" % (res.summary(), name)
    assert res.generators_octal is None, \
        "%s: stated generators %s" % (name, res.generators_octal)
    assert res.interleaver is None, \
        "%s: stated an interleaver %s" % (name, res.interleaver)
    assert res.summary()          # must never raise, whatever the status


@pytest.mark.parametrize("name", sorted(CASES))
def test_adversarial_input_stays_within_the_time_budget(name):
    """Risk #5. These are exactly the inputs a sweep runs longest on, because
    there is no answer to find and every candidate must be eliminated."""
    import time

    t0 = time.time()
    blind_recover(CASES[name])
    elapsed = time.time() - t0

    assert elapsed < 45.0, "%s took %.0f s" % (name, elapsed)


# --------------------------------------------------------------------------
# the structural discriminator, on its own
# --------------------------------------------------------------------------

def test_code_signature_holds_for_a_real_code():
    bits, _ = make_stream(60_000, None, None, seed=1)
    assert code_signature_holds(bits, 2, 14)


@pytest.mark.parametrize("stream,label", [
    (np.ones(N, dtype=np.uint8), "all ones"),
    (np.tile([0, 1], N // 2).astype(np.uint8), "alternating"),
    (np.tile([1, 0, 1, 1, 0, 0, 0, 1], N // 8).astype(np.uint8), "period-8"),
])
def test_code_signature_rejects_degenerate_streams(stream, label):
    """A rate-1/2 code is full rank at every ODD row length. These are not."""
    assert not code_signature_holds(stream, 2, 14), label


def test_code_signature_only_looks_below_the_span():
    """The bound is load-bearing, not cosmetic. A structured SOURCE also adds
    odd-length deficiency, but at and above its own period - a 2-character
    payload first collapses at L=31 against a code span of 14. Checking the
    whole profile would reject the streams the candidate walk exists to
    recover, and `test_the_walk_recovers_a_code_the_source_collapsed_in_front
    _of` would fail."""
    bits, truth = make_stream(60_000, None, None, seed=1, payload_text="AB")
    assert code_signature_holds(bits, 2, 14), \
        "the guard reaches above the span and would reject a real recovery"

    res = blind_recover(bits)
    assert res.status == "ok"
    assert res.generators_octal == tuple(truth.polys_octal)


def test_rate_one_third_is_not_rejected_by_the_signature_check():
    """n=3 constrains only multiples of 3; the check must use n, not assume 2."""
    rng = np.random.default_rng(2)
    src = rng.integers(0, 2, 30_000, dtype=np.uint8)
    coded = conv_encode(src, polys=(0o171, 0o133, 0o165), K=7)
    assert code_signature_holds(coded, 3, 21)


# --------------------------------------------------------------------------
# summary() promises never to raise, and it did
# --------------------------------------------------------------------------

def test_summary_survives_a_convolutional_interleaver():
    """`summary()` formatted p["depth"] and p["width"], which every family has
    EXCEPT convolutional. A convolutional hypothesis raised KeyError inside the
    one method whose docstring promises it never raises - and it is called from
    the UI on every result, including the failures it exists to explain.

    No test caught it because no test had ever printed a convolutional
    hypothesis. An adversarial input did, on the first run."""
    res = RecoveryResult(
        "ok", 0.7, period=20,
        interleaver=InterleaverHypothesis("convolutional",
                                          {"branches": 4, "delay": 1}, 1.0))
    text = res.summary()
    assert "convolutional" in text and "branches=4" in text
