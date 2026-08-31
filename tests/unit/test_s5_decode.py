"""S5 dependencies, pinned against independent implementations.

Two of these tests exist because of bugs they already caught on 29 Aug, and
both bugs were invisible from inside our own code:

  - our encoder used the reversed generator bit order. Encode and blind-recover
    round-tripped perfectly against each other, so every S4 test passed. Only
    comparing against commpy showed it. On a real CCSDS downlink S4 would have
    reported 0o117 / 0o155 instead of 0o171 / 0o133.
  - commpy's 'unquantized' decoder wants soft values in the 2b-1 sense
    (bit 0 -> -1, bit 1 -> +1). Feeding it raw 0/1, or the opposite sign,
    decodes to noise while raising nothing.

Neither is a crash. Both are silently wrong answers, which is the failure class
that actually loses a demo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s5_decode.conv_reference import (
    POLY_171_133,
    conv_encode,
    parity_check_taps,
    poly_to_taps,
    taps_to_poly,
)

commpy_cc = pytest.importorskip("commpy.channelcoding")
Trellis = commpy_cc.Trellis
TB_DEPTH = 35          # ~5*(m+1) for m=6


def trellis():
    return Trellis(np.array([6]), np.array([[0o171, 0o133]]))


# --------------------------------------------------------------------------
# the convention, pinned
# --------------------------------------------------------------------------

def test_our_encoder_matches_commpy_bit_for_bit():
    """The cross-implementation check. If this fails, our generator bit order
    has drifted and every recovered polynomial we report is wrong."""
    rng = np.random.default_rng(3)
    for n in (50, 500, 5000):
        bits = rng.integers(0, 2, n)
        ref = np.asarray(commpy_cc.conv_encode(bits.astype(int), trellis()),
                         dtype=np.uint8)
        ours = conv_encode(bits.astype(np.uint8))
        assert len(ours) <= len(ref)
        assert np.array_equal(ref[:len(ours)], ours), "n=%d: encoders disagree" % n


def test_poly_taps_round_trip_is_lsb_first():
    for poly in (0o171, 0o133, 0o5, 0o177):
        taps = poly_to_taps(poly, 7)
        assert taps[0] == (poly & 1), "taps[0] must be the octal LSB"
        assert taps_to_poly(taps) == poly


def test_parity_check_annihilates_the_coded_stream():
    rng = np.random.default_rng(4)
    coded = conv_encode(rng.integers(0, 2, 60_000, dtype=np.uint8))
    h = parity_check_taps()
    windows = np.lib.stride_tricks.sliding_window_view(coded, len(h))
    syndrome = (windows @ h) % 2
    assert syndrome[0::2].sum() == 0, "check fails on even-aligned windows"
    # and it must NOT hold on the odd phase - that asymmetry is how n is found
    assert syndrome[1::2].mean() == pytest.approx(0.5, abs=0.05)


# --------------------------------------------------------------------------
# the decoder we will actually use on 2 Sep
# --------------------------------------------------------------------------

def test_hard_decision_viterbi_round_trips_exactly():
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 1500).astype(int)
    t = trellis()
    enc = commpy_cc.conv_encode(bits, t)
    dec = commpy_cc.viterbi_decode(enc, t, tb_depth=TB_DEPTH, decoding_type="hard")
    assert np.array_equal(dec[:len(bits)], bits)


def test_soft_decision_convention_is_two_b_minus_one():
    """S5 must be soft-input. Getting the sign convention wrong decodes to
    noise silently, so the convention is pinned here rather than remembered."""
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 1500).astype(int)
    t = trellis()
    enc = np.asarray(commpy_cc.conv_encode(bits, t))

    correct = commpy_cc.viterbi_decode(2.0 * enc - 1.0, t, tb_depth=TB_DEPTH,
                                       decoding_type="unquantized")
    assert np.array_equal(correct[:len(bits)], bits)

    inverted = commpy_cc.viterbi_decode(1.0 - 2.0 * enc, t, tb_depth=TB_DEPTH,
                                        decoding_type="unquantized")
    assert not np.array_equal(inverted[:len(bits)], bits), \
        "both signs decode correctly - the convention test is not testing anything"


def test_soft_decision_beats_hard_under_noise():
    """The reason the LLR contract exists at all. If this ever stops being
    true, Anvith's soft outputs are being thrown away somewhere."""
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, 4_000).astype(int)
    t = trellis()
    enc = np.asarray(commpy_cc.conv_encode(bits, t))

    sigma = np.sqrt(10 ** (0 / 10) / 2)          # Es/N0 = 0 dB
    rx = (2.0 * enc - 1.0) + rng.normal(0, sigma, len(enc))

    hard = commpy_cc.viterbi_decode((rx > 0).astype(int), t, tb_depth=TB_DEPTH,
                                    decoding_type="hard")
    soft = commpy_cc.viterbi_decode(rx, t, tb_depth=TB_DEPTH,
                                    decoding_type="unquantized")

    ber_hard = (hard[:len(bits)] != bits).mean()
    ber_soft = (soft[:len(bits)] != bits).mean()
    assert ber_soft < ber_hard / 5, "soft %.5f vs hard %.5f" % (ber_soft, ber_hard)


def test_reed_solomon_round_trips_and_corrects():
    reedsolo = pytest.importorskip("reedsolo")
    rs = reedsolo.RSCodec(32)                     # 32 parity symbols -> 16 correctable
    payload = bytes(range(64))
    encoded = bytearray(rs.encode(payload))
    for i in (0, 5, 17, 40, 70):                  # 5 corruptions, well inside t=16
        encoded[i] ^= 0xFF
    assert bytes(rs.decode(bytes(encoded))[0]) == payload
