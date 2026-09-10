"""Does the pipeline recover THE BITS THAT WERE SENT?

Nothing else in this repo asks that question, and it is the one the whole
project exists to answer.

What the other checks actually establish, and where each stops short:

  ``run_demo.py``          - modulation name, and all seven stages self-report
                             ok. Until 10 Sep it printed "ALL EIGHT CORRECT"
                             on that alone.
  ``test_e2e_real_signal`` - S4's recovered period and generators equal the
                             truth JSON. Real, and still only the PARAMETERS.
  ``reencode_ber``         - re-encoding S5's output reproduces the stream that
                             arrived. Self-consistency: it proves the decode
                             agrees with the input under the recovered code,
                             not that either matches the transmitter.

A chain can pass all three and still hand back the wrong bits. The transmitter
is reproducible - ``zoo.rf.make_rf_file`` draws the payload from
``np.random.default_rng(seed)`` and the seed is in the filename - so the bits
that were sent can be regenerated exactly and compared against.

The decoded run is a CONTIGUOUS INTERIOR SLICE of the source: S3 starts at a
sample offset, S4 finds a bit offset into that, and S5 decodes a bounded prefix
of what remains. So the test locates the slice first and then demands
exactness over it, rather than assuming it starts at bit zero.

WARM-UP. A Viterbi decoder entering a trellis mid-codeword has no state
history, so its first few output bits are unreliable by construction. Measured
across all eight demo captures on 10 Sep, every residual error sits at bit
index 6 or lower, and three of the eight are exact from bit 0. This test allows
a transient inside WARMUP_BITS and requires EXACTNESS past it: one error at bit
400 is a real defect and fails, where one at bit 3 is the decoder starting up.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "zoo" / "corpus" / "rf"

# One per receiver family: a PSK capture, a non-coherent FSK capture, and a
# dense-constellation capture at the bottom of its measured envelope.
CAPTURES = ["qpsk_20dB_2011", "2fsk_20dB_2029", "16qam_15dB_2022"]

WARMUP_BITS = 16          # generous: the measured worst case is bit 6
PROBE_BITS = 48           # exact-match anchor used to locate the slice
PROBE_ANCHOR = 512        # taken from INSIDE the run, clear of the warm-up


def true_source_bits(seed: int, n_source_bits: int = 20_000) -> np.ndarray:
    """The payload the transmitter actually sent.

    Mirrors ``zoo.rf.make_rf_file``, which calls ``zoo.bits_only.make_stream``
    with the corpus seed; that function's first draw from
    ``np.random.default_rng(seed)`` is the source payload. Regenerated here
    rather than read from the truth JSON, which records the PARAMETERS of the
    transmission but not its payload.
    """
    return np.random.default_rng(seed).integers(0, 2, n_source_bits, dtype=np.uint8)


def locate(decoded: np.ndarray, source: np.ndarray) -> tuple[int | None, bool]:
    """Where does ``decoded`` sit inside ``source``? Returns (offset, inverted).

    A coherent receiver cannot resolve 0 from 180 degrees without a sync
    marker, so the whole stream may arrive inverted. Both polarities are tried,
    and which one matched is reported rather than hidden.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    anchor = PROBE_ANCHOR if decoded.size >= PROBE_ANCHOR + PROBE_BITS else 0
    if decoded.size < anchor + PROBE_BITS:
        return None, False
    windows = sliding_window_view(source, PROBE_BITS)
    for inverted in (False, True):
        stream = (1 - decoded) if inverted else decoded
        hits = np.flatnonzero(
            (windows == stream[anchor:anchor + PROBE_BITS]).all(axis=1))
        for hit in hits:
            offset = int(hit) - anchor
            if offset >= 0:
                return offset, inverted
    return None, False


def _captures_present() -> bool:
    return all((CORPUS / (name + ".wav")).is_file() for name in CAPTURES)


@unittest.skipUnless(_captures_present(),
                     "corpus captures not present under " + str(CORPUS))
class TestDecodedBitsMatchTheTransmitter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from pipeline.s6_frame.payload import extract_text
        from service.orchestrator import orchestrate

        cls.results = {}
        for name in CAPTURES:
            wav = CORPUS / (name + ".wav")
            captured = {}

            def grab(bits, _c=captured):
                # S6 is the last stage and is handed exactly what S5 decoded.
                _c["bits"] = np.asarray(bits, dtype=np.uint8).ravel().copy()
                return extract_text(bits)

            with tempfile.TemporaryDirectory() as td:
                report = orchestrate(
                    run_id="bits-truth-" + name,
                    file_path=wav,
                    db_path=Path(td) / "bits.db",
                    stage_overrides={"s6_frame": grab},
                )
            cls.results[name] = {
                "decoded": captured.get("bits"),
                "truth": json.loads(wav.with_suffix(".json").read_text()),
                "seed": int(name.rsplit("_", 1)[1]),
                "stages": {s.stage: s for s in report.stages},
            }

    def _located(self, record):
        source = true_source_bits(record["seed"])
        offset, inverted = locate(record["decoded"], source)
        return source, offset, inverted

    def test_s5_produced_bits_at_all(self):
        for name, record in self.results.items():
            with self.subTest(capture=name):
                self.assertIsNotNone(record["decoded"], "S5 returned no bits")
                self.assertGreater(record["decoded"].size, PROBE_ANCHOR + PROBE_BITS)

    def test_the_decoded_run_is_found_inside_the_transmitted_payload(self):
        """A wrong decode is aperiodic and matches nowhere: a 48-bit exact
        probe against a 20,000-bit payload has about a 7e-11 chance of a
        coincidental hit."""
        for name, record in self.results.items():
            with self.subTest(capture=name):
                _source, offset, _inverted = self._located(record)
                self.assertIsNotNone(
                    offset,
                    name + ": no 48-bit run of the decode appears anywhere in "
                    "the bits that were transmitted - the decode does not "
                    "correspond to the payload")

    def test_every_bit_past_decoder_warmup_is_exactly_right(self):
        """The headline claim, in the strictest form the data supports: bit for
        bit identical to what was sent, with no tolerance at all past the
        trellis warm-up."""
        for name, record in self.results.items():
            with self.subTest(capture=name):
                source, offset, inverted = self._located(record)
                self.assertIsNotNone(offset, "run not located")

                decoded = (1 - record["decoded"]) if inverted else record["decoded"]
                n = min(decoded.size, source.size - offset)
                self.assertGreater(n, 1000, "too little overlap to be meaningful")

                mismatches = np.flatnonzero(source[offset:offset + n] != decoded[:n])
                late = mismatches[mismatches >= WARMUP_BITS]
                self.assertEqual(
                    late.size, 0,
                    "%s: %d bit error(s) past the %d-bit warm-up, at indices %s "
                    "of %d compared - these are not decoder start-up and "
                    "indicate a real defect"
                    % (name, late.size, WARMUP_BITS, late[:10].tolist(), n))

    def test_the_warmup_transient_stays_small(self):
        """Guards the allowance itself. If warm-up ever grows, this fails rather
        than quietly widening the window the test above ignores."""
        for name, record in self.results.items():
            with self.subTest(capture=name):
                source, offset, inverted = self._located(record)
                self.assertIsNotNone(offset, "run not located")
                decoded = (1 - record["decoded"]) if inverted else record["decoded"]
                n = min(decoded.size, source.size - offset)

                early = np.flatnonzero(
                    source[offset:offset + WARMUP_BITS] != decoded[:WARMUP_BITS])
                self.assertLessEqual(
                    early.size, 8,
                    "%s: %d of the first %d bits are wrong - that is more than a "
                    "trellis starting up" % (name, early.size, WARMUP_BITS))

                total = np.flatnonzero(source[offset:offset + n] != decoded[:n]).size
                self.assertLess(
                    total / n, 1e-3,
                    "%s: overall source-bit BER %.2e over %d bits"
                    % (name, total / n, n))


if __name__ == "__main__":
    unittest.main()
