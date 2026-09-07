"""S6: blind descrambling, and getting a readable payload out the far end.

The chain this pins: coded bits in, nothing supplied, readable text out.
Recovered parameters are a claim a viewer has to trust; a message appearing
from a file the system was told nothing about is not.

Two of these tests exist because using REAL data broke things that random data
never would have:

  - a structured payload (ASCII has bit 7 clear in every byte) is
    rank-deficient before the code touches it, so the consistency test had to
    become one-sided. The first stream carrying an actual message failed.
  - relaxing that test let a scrambled stream read back as a confident,
    completely wrong code. That is the one failure mode this project has
    otherwise never had, so it gets a test of its own.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from registry import CODES
import pipeline.s4_recover.interleavers  # noqa: F401
import pipeline.s5_decode.conv_code  # noqa: F401

from pipeline.s4_recover.rank_collapse import blind_recover, recover_code_structure
from pipeline.s5_decode.conv_reference import parity_check_taps
from pipeline.s6_frame.descramble import (
    berlekamp_massey,
    descramble,
    find_scrambler_period,
    recover_scrambler,
)
from pipeline.s6_frame.payload import (
    CCSDS_ASM,
    CCSDS_ASM_INV,
    bits_to_bytes,
    calculate_byte_entropy,
    extract_text,
    PayloadReport,
)
from tests.fixtures.local_zoo import CCSDS_SCRAMBLER, lfsr_scramble, make_stream

MSG = ("RAAYA SIH26147 -- blind recovery of modulation, interleaver and code. "
       "Nothing about this file was supplied in advance. ")


@pytest.fixture(scope="module")
def coded():
    rng = np.random.default_rng(0)
    from pipeline.s5_decode.conv_reference import conv_encode
    return conv_encode(rng.integers(0, 2, 40_000, dtype=np.uint8))


# --------------------------------------------------------------------------
# Berlekamp-Massey and blind scrambler recovery
# --------------------------------------------------------------------------

def test_berlekamp_massey_finds_the_degree_of_a_raw_sequence():
    seq = lfsr_scramble(np.zeros(600, dtype=np.uint8))
    degree, _ = berlekamp_massey(seq.tolist())
    assert degree == CCSDS_SCRAMBLER.bit_length() - 1 == 8


def test_syndrome_of_a_scrambled_stream_carries_the_scrambler(coded):
    """h.r = h.(c XOR s) = h.s, because h annihilates any codeword. The
    scrambler is not observable but a linear functional of it is, and that
    functional obeys the same recurrence."""
    scrambled = lfsr_scramble(coded)
    h = parity_check_taps()
    windows = np.lib.stride_tricks.sliding_window_view(scrambled, len(h))[0::2]
    syndrome = (windows @ h) % 2
    assert syndrome.mean() > 0.1, "syndrome vanished - the trick relies on it"
    degree, _ = berlekamp_massey(syndrome[:200].tolist())
    assert degree == 8


def test_period_search_needs_a_multiple_of_the_symbol_size(coded):
    """The shift must be a multiple of BOTH the scrambler period and n, or the
    two codewords are out of phase and their sum is not a codeword. For a
    period-255 scrambler on a rate-1/2 code the answer is 510, not 255."""
    scrambled = lfsr_scramble(coded)
    period = find_scrambler_period(scrambled, parity_check_taps())
    assert period == 510 == np.lcm(255, 2)


@pytest.mark.parametrize("poly", [0o45, 0o211, CCSDS_SCRAMBLER])
def test_scrambler_recovered_blind_and_removed_exactly(coded, poly):
    """No dictionary of known polynomials - the degree comes from
    Berlekamp-Massey and bounds an exhaustive search from there."""
    scrambled = lfsr_scramble(coded, poly)
    hyp = recover_scrambler(scrambled, parity_check_taps())

    assert hyp is not None and hyp.ok, "not recovered: %s" % (hyp and hyp.reason)
    assert hyp.degree == poly.bit_length() - 1
    assert np.array_equal(descramble(scrambled, hyp), coded[:len(scrambled)])


def test_unscrambled_stream_reports_no_scrambler(coded):
    assert recover_scrambler(coded, parity_check_taps()) is None


# --------------------------------------------------------------------------
# the payload
# --------------------------------------------------------------------------

def test_printable_fraction_separates_text_from_noise():
    rng = np.random.default_rng(0)
    noise = extract_text(rng.integers(0, 2, 8000, dtype=np.uint8))
    assert not noise.looks_like_text
    assert noise.printable_fraction < 0.55

    src = np.unpackbits(np.frombuffer(MSG.encode() * 40, dtype=np.uint8))
    real = extract_text(src)
    assert real.looks_like_text
    assert real.printable_fraction > 0.99
    assert MSG.strip() in real.text


def test_bits_to_bytes_is_msb_first():
    bits = np.array([0, 1, 0, 0, 0, 0, 0, 1], dtype=np.uint8)   # 0x41 = 'A'
    assert bits_to_bytes(bits) == b"A"


# --------------------------------------------------------------------------
# structured payloads, which is what broke the consistency test
# --------------------------------------------------------------------------

def test_a_text_payload_is_still_recognised_as_a_code():
    """ASCII has bit 7 clear in every byte, so the source is rank-deficient
    before encoding and the measured deficiency EXCEEDS the code's own
    prediction. Demanding equality rejected every real payload."""
    bits, truth = make_stream(60_000, None, None, seed=1, payload_text=MSG)
    code = recover_code_structure(bits)
    assert code.consistent
    assert (code.n, code.memory, code.span) == (2, 6, 14)


def test_the_noise_direction_is_still_rejected():
    """Errors REDUCE deficiency and slide the span upward, overstating memory.
    The relaxation must not have opened that door."""
    for ber in (0.0005, 0.001):
        code = recover_code_structure(make_stream(60_000, None, None,
                                                  ber=ber, seed=3)[0])
        assert not code.consistent, "BER %.4f accepted; K would read %s" % (
            ber, code.memory + 1 if code.memory is not None else "?")


def test_scrambled_stream_is_not_reported_as_a_confident_code():
    """A scrambled stream yields the code-XOR-scrambler composite, which is a
    valid linear description of what arrived and annihilates it exactly - no
    residual test can reject it. It is simply not the transmitter's code, so
    it must never be stated as one."""
    bits, _ = make_stream(20_000, None, None, seed=1, scramble=True, payload_text=MSG)
    res = blind_recover(bits)
    if res.status == "ok" and res.generators_octal:
        assert res.generators_octal == (0o171, 0o133), \
            "stated a wrong code with confidence: %s" % res.summary()


# --------------------------------------------------------------------------
# the whole chain
# --------------------------------------------------------------------------

def test_end_to_end_coded_interleaved_stream_yields_readable_text():
    """The demo, as an assertion. Nothing below is told anything about the
    stream: the interleaver, its parameters, the code and its generators are
    all recovered before a single bit is decoded."""
    bits, truth = make_stream(30_000, 8, 12, seed=1, payload_text=MSG)

    res = blind_recover(bits)
    assert res.status == "ok"
    assert res.interleaver.params == {"depth": 8, "width": 12}
    assert res.generators_octal == tuple(truth.polys_octal)

    from registry import INTERLEAVERS
    de = INTERLEAVERS[res.interleaver.family].deinterleave(
        bits[res.offset:], **res.interleaver.params)
    decoded = CODES["conv"].decode(de[:24_000], {
        "n": res.code.n, "memory": res.code.memory,
        "generators_octal": res.generators_octal,
        "span": res.code.span, "parity_taps": res.parity_taps})

    report = extract_text(decoded)
    assert report.looks_like_text, "printable %.2f" % report.printable_fraction
    assert "RAAYA SIH26147" in report.text


# --------------------------------------------------------------------------
# polarity - risk #9, arriving exactly as the register predicted
# --------------------------------------------------------------------------

def test_inverted_text_is_read_the_right_way_up():
    """A coherent receiver cannot tell 0 degrees from 180, so half the
    rotations S3 offers carry the whole stream inverted. Both recover the same
    parameters - the rank test is blind to inversion - and both decode without
    complaint. One gives the message, the other its complement.

    Measured 4 Sep on a real capture: rotation 2 read printable 1.000 and
    rotation 0 read 0.001, same file, same recovered parameters. The study
    picked by rotation index and got the inverted one, which is why the text
    column read 0 while the interleaver column read 3/3.
    """
    src = np.unpackbits(np.frombuffer(MSG.encode(), dtype=np.uint8))

    upright = extract_text(src)
    flipped = extract_text(1 - src)

    assert upright.looks_like_text and not upright.inverted
    assert flipped.looks_like_text, "printable %.3f" % flipped.printable_fraction
    assert flipped.inverted
    assert MSG[:20] in flipped.text
    assert flipped.text == upright.text


def test_polarity_resolution_can_be_switched_off():
    """The old behaviour stays reachable, because resolving polarity by
    printability only works when the payload IS text."""
    src = np.unpackbits(np.frombuffer(MSG.encode(), dtype=np.uint8))
    raw = extract_text(1 - src, resolve_polarity=False)
    assert not raw.looks_like_text
    assert not raw.inverted


def test_polarity_resolution_does_not_rescue_noise():
    """Inverting random bits gives more random bits. Taking the better of two
    coin flips must not push noise over the line - risk #15 applies here too."""
    rng = np.random.default_rng(11)
    for _ in range(3):
        noise = extract_text(rng.integers(0, 2, 8000, dtype=np.uint8))
        assert not noise.looks_like_text
        assert noise.printable_fraction < 0.55


# --------------------------------------------------------------------------
# Byte entropy tests
# --------------------------------------------------------------------------

class TestByteEntropy(unittest.TestCase):
    """Focused unit tests for Shannon byte entropy calculation and S6 integration."""

    def test_empty_bytes_zero_entropy(self):
        """Empty input yields 0.0 entropy."""
        self.assertEqual(calculate_byte_entropy(b""), 0.0)
        self.assertEqual(calculate_byte_entropy(bytearray()), 0.0)

    def test_repeated_byte_zero_entropy(self):
        """Identical/single-value byte streams have zero uncertainty (0.0 bits/byte)."""
        self.assertEqual(calculate_byte_entropy(b"A"), 0.0)
        self.assertEqual(calculate_byte_entropy(b"A" * 100), 0.0)
        self.assertEqual(calculate_byte_entropy(b"\x00" * 50), 0.0)
        self.assertEqual(calculate_byte_entropy(b"\xff" * 256), 0.0)

    def test_two_equally_frequent_bytes_one_bit_per_byte(self):
        """Two equally probable byte values yield exactly 1.0 bit/byte."""
        self.assertAlmostEqual(calculate_byte_entropy(b"AB" * 50), 1.0, places=7)
        self.assertAlmostEqual(calculate_byte_entropy(b"A" * 25 + b"B" * 25), 1.0, places=7)
        self.assertAlmostEqual(calculate_byte_entropy(b"\x00" * 30 + b"\xff" * 30), 1.0, places=7)

    def test_known_multi_value_distribution(self):
        """Verify known distributions: 4 symbols (2 bits), 8 symbols (3 bits), uniform 256 (8 bits), biased."""
        # 4 equally frequent bytes -> log2(4) = 2.0 bits/byte
        self.assertAlmostEqual(calculate_byte_entropy(b"ABCD" * 25), 2.0, places=7)

        # 8 equally frequent bytes -> log2(8) = 3.0 bits/byte
        self.assertAlmostEqual(calculate_byte_entropy(b"ABCDEFGH" * 10), 3.0, places=7)

        # 256 uniformly distributed bytes -> log2(256) = 8.0 bits/byte
        data_256 = bytes(range(256))
        self.assertAlmostEqual(calculate_byte_entropy(data_256), 8.0, places=7)

        # Biased distribution: 75% 'A', 25% 'B'
        # H = -(0.75 * log2(0.75) + 0.25 * log2(0.25))
        expected_biased = -(0.75 * math.log2(0.75) + 0.25 * math.log2(0.25))
        data_biased = b"A" * 75 + b"B" * 25
        self.assertAlmostEqual(calculate_byte_entropy(data_biased), expected_biased, places=7)

    def test_normal_extract_text_works_and_exposes_entropy(self):
        """extract_text() still decodes text correctly and exposes entropy in PayloadReport."""
        text_bytes = b"Hello, World! Telemetry payload stream for SIH2026."
        bits = []
        for byte in text_bytes:
            for shift in range(7, -1, -1):
                bits.append((byte >> shift) & 1)

        rep = extract_text(bits)
        self.assertEqual(rep.text, "Hello, World! Telemetry payload stream for SIH2026.")
        self.assertEqual(rep.n_bytes, len(text_bytes))
        self.assertTrue(rep.looks_like_text)
        self.assertAlmostEqual(rep.printable_fraction, 1.0, places=5)
        self.assertFalse(rep.inverted)

        # Entropy field is populated and matches direct calculation
        expected_entropy = calculate_byte_entropy(text_bytes)
        self.assertAlmostEqual(rep.entropy, expected_entropy, places=7)
        self.assertGreater(rep.entropy, 0.0)
        self.assertLess(rep.entropy, 8.0)

    def test_extract_text_empty_input(self):
        """Empty bit stream yields a clean empty report with 0.0 entropy and default header fields."""
        rep = extract_text([])
        self.assertEqual(rep.n_bytes, 0)
        self.assertEqual(rep.entropy, 0.0)
        self.assertEqual(rep.text, "")
        self.assertFalse(rep.looks_like_text)
        self.assertFalse(rep.inverted)
        self.assertFalse(rep.has_header)
        self.assertEqual(rep.header_hex, "")
        self.assertEqual(rep.header_entropy, 0.0)
        self.assertEqual(rep.payload_entropy, 0.0)
        self.assertEqual(rep.payload_text, "")

    def test_asm_ascii_payload_split(self):
        """CCSDS_ASM followed by ASCII payload splits cleanly."""
        payload = b"Hello, SIH2026 ground station!"
        data = CCSDS_ASM + payload
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        rep = extract_text(bits)

        self.assertTrue(rep.has_header)
        self.assertEqual(rep.header_hex, "1ACFFC1D")
        self.assertEqual(rep.payload_text, "Hello, SIH2026 ground station!")
        self.assertAlmostEqual(rep.header_entropy, calculate_byte_entropy(CCSDS_ASM), places=7)
        self.assertAlmostEqual(rep.header_entropy, 2.0, places=7)
        self.assertAlmostEqual(rep.payload_entropy, calculate_byte_entropy(payload), places=7)
        self.assertEqual(rep.n_bytes, len(data))
        self.assertEqual(rep.text, (CCSDS_ASM + payload).decode("utf-8", errors="replace"))
        self.assertAlmostEqual(rep.entropy, calculate_byte_entropy(data), places=7)

    def test_asm_after_arbitrary_leading_bytes(self):
        """CCSDS_ASM after arbitrary leading bytes splits at the ASM marker."""
        preamble = b"\x00\x01\x02\x03\x55\xaa"
        payload = b"Telemetry payload after sync marker"
        data = preamble + CCSDS_ASM + payload
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        rep = extract_text(bits)

        self.assertTrue(rep.has_header)
        self.assertEqual(rep.header_hex, "1ACFFC1D")
        self.assertEqual(rep.payload_text, "Telemetry payload after sync marker")
        self.assertAlmostEqual(rep.header_entropy, 2.0, places=7)
        self.assertAlmostEqual(rep.payload_entropy, calculate_byte_entropy(payload), places=7)
        self.assertEqual(rep.n_bytes, len(data))

    def test_no_asm_entire_stream_is_payload(self):
        """Stream without ASM sets has_header=False, header_hex="", payload_text == text."""
        payload = b"Direct ASCII text without any CCSDS sync marker."
        bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))
        rep = extract_text(bits)

        self.assertFalse(rep.has_header)
        self.assertEqual(rep.header_hex, "")
        self.assertEqual(rep.header_entropy, 0.0)
        self.assertEqual(rep.payload_text, rep.text)
        self.assertAlmostEqual(rep.payload_entropy, rep.entropy, places=7)
        self.assertAlmostEqual(rep.payload_entropy, calculate_byte_entropy(payload), places=7)

    def test_inverted_stream_and_inverted_asm(self):
        """Inverted stream polarity resolution and inverted ASM detection."""
        # Case A: Inverted text payload with resolve_polarity=True (default).
        # Printability check flips stream to upright, restoring CCSDS_ASM.
        payload = b"Inverted text payload to test polarity flip and ASM."
        data = CCSDS_ASM + payload
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        inv_bits = 1 - bits

        rep_resolved = extract_text(inv_bits, resolve_polarity=True)
        self.assertTrue(rep_resolved.inverted)
        self.assertTrue(rep_resolved.has_header)
        self.assertEqual(rep_resolved.header_hex, "1ACFFC1D")
        self.assertEqual(rep_resolved.payload_text, payload.decode("utf-8"))
        self.assertAlmostEqual(rep_resolved.header_entropy, 2.0, places=7)
        self.assertAlmostEqual(rep_resolved.payload_entropy, calculate_byte_entropy(payload), places=7)

        # Case B: Stream containing raw inverted ASM (CCSDS_ASM_INV = b"\xe5\x30\x03\xe2")
        # when resolve_polarity=False.
        inv_data = CCSDS_ASM_INV + payload
        inv_bits_raw = np.unpackbits(np.frombuffer(inv_data, dtype=np.uint8))
        rep_inv_asm = extract_text(inv_bits_raw, resolve_polarity=False)
        self.assertFalse(rep_inv_asm.inverted)
        self.assertTrue(rep_inv_asm.has_header)
        self.assertEqual(rep_inv_asm.header_hex, "E53003E2")
        self.assertEqual(rep_inv_asm.payload_text, payload.decode("utf-8"))
        self.assertAlmostEqual(rep_inv_asm.header_entropy, 2.0, places=7)
        self.assertAlmostEqual(rep_inv_asm.payload_entropy, calculate_byte_entropy(payload), places=7)

    def test_payload_entropy_isolated_to_payload_bytes_only(self):
        """Payload entropy is computed strictly over payload bytes without marker contamination."""
        # Single repeated byte has 0 entropy, but CCSDS_ASM has entropy 2.0 (4 distinct bytes).
        raw_payload = b"A" * 50
        data = CCSDS_ASM + raw_payload
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        rep = extract_text(bits)

        self.assertTrue(rep.has_header)
        self.assertEqual(rep.header_hex, "1ACFFC1D")
        self.assertAlmostEqual(rep.header_entropy, 2.0, places=7)
        self.assertAlmostEqual(rep.payload_entropy, 0.0, places=7)
        self.assertEqual(rep.payload_text, "A" * 50)
        # Total stream entropy is > 0 due to the ASM bytes present
        self.assertGreater(rep.entropy, 0.0)


if __name__ == "__main__":
    unittest.main()
