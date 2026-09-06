"""tests/unit/test_ccsds.py"""
from __future__ import annotations

import numpy as np
import pytest
import reedsolo

from pipeline.s5_decode.conv_code import ConvCode
from zoo.bits_only import lfsr_scramble
from zoo.ccsds import (RS_K, RS_N, ccsds_deinterleave, ccsds_interleave,
                        make_ccsds_rf_file, make_ccsds_stream, rs_encode_blocks)


def test_interleave_deinterleave_round_trip():
    """The transpose must be exactly invertible -- this is the one piece of
    real, un-tested math in this module (everything else is composition of
    already-tested pieces)."""
    rng = np.random.default_rng(0)
    codewords = [bytes(rng.integers(0, 256, RS_N, dtype=np.uint8)) for _ in range(12)]
    interleaved = ccsds_interleave(codewords, depth=4)
    back = ccsds_deinterleave(interleaved, depth=4, n=RS_N)
    assert back == codewords


def test_interleave_spreads_a_contiguous_burst_across_codewords():
    """The entire point of interleaving: a contiguous run of corrupted
    TRANSMITTED bytes must land in different codewords, not concentrate in
    one -- this is what makes an outer RS code robust to burst channels."""
    rng = np.random.default_rng(1)
    depth = 4
    codewords = [bytes(rng.integers(0, 256, RS_N, dtype=np.uint8)) for _ in range(depth)]
    interleaved = bytearray(ccsds_interleave(codewords, depth))
    burst_len = depth * 3   # a burst spanning 3 interleaved "rows"
    for i in range(burst_len):
        interleaved[i] ^= 0xFF
    damaged = ccsds_deinterleave(bytes(interleaved), depth, RS_N)
    per_codeword_damage = [
        sum(1 for a, b in zip(orig, dmg) if a != b)
        for orig, dmg in zip(codewords, damaged)
    ]
    assert all(d <= 3 for d in per_codeword_damage), per_codeword_damage
    assert sum(1 for d in per_codeword_damage if d > 0) == depth


def test_rs_round_trip():
    payload = b"the quick brown fox jumps over the lazy dog" * 20
    codewords = rs_encode_blocks(payload, RS_N, RS_K)
    rs = reedsolo.RSCodec(RS_N - RS_K)
    recovered = bytearray()
    for c in codewords:
        dec, _, _ = rs.decode(c)
        recovered.extend(dec)
    padded = payload + b"\x00" * (-len(payload) % RS_K)
    assert bytes(recovered) == padded


@pytest.mark.parametrize("depth", [1, 4, 8])
def test_make_ccsds_stream_full_chain_round_trip(depth):
    """RS -> byte-interleave -> randomise -> conv, then undo every layer in
    reverse over a clean (noiseless) channel, and recover the exact
    payload. This is the real-standard-order chain a teammate asked for --
    verified correct here BEFORE any WAV file gets built on top of it,
    same discipline as every other estimator fix this session."""
    text = "HELLO CCSDS WORLD, this is a test payload for the concatenated chain."
    bits, payload, meta = make_ccsds_stream(n_blocks=8, depth=depth, payload_text=text, seed=1)

    params = {"n": 2, "memory": meta["code"]["K"] - 1,
              "generators_octal": tuple(meta["code"]["polys_octal"])}
    decoded = ConvCode().decode(bits, params)
    descrambled = lfsr_scramble(decoded, meta["scrambler"]["poly_octal"])
    n_bytes = (descrambled.size // 8) * 8
    interleaved_bytes = np.packbits(descrambled[:n_bytes]).tobytes()
    codewords = ccsds_deinterleave(interleaved_bytes, depth, meta["rs"]["n"])

    rs = reedsolo.RSCodec(meta["rs"]["n"] - meta["rs"]["k"])
    recovered = bytearray()
    for c in codewords:
        dec, _, _ = rs.decode(bytes(c))
        recovered.extend(dec)
    recovered = bytes(recovered)[:meta["payload_n_bytes"]]
    assert recovered[:len(payload)] == payload


def test_make_ccsds_stream_pipeline_order_matches_real_ccsds():
    """Per the teammate's exact ask: RS outer -> interleave -> randomise ->
    convolutional inner, randomising BEFORE the inner code -- not
    tests/fixtures/local_zoo.make_ccsds_stream's order, which that file's
    own docstring already states randomises AFTER (outermost)."""
    _bits, _payload, meta = make_ccsds_stream(n_blocks=4, depth=1, seed=0)
    assert meta["pipeline_order"] == [
        "rs_encode", "byte_interleave", "randomise", "conv_encode",
    ]


def test_make_ccsds_rf_file_produces_iq_and_truth():
    iq, payload, truth = make_ccsds_rf_file(
        scheme_name="qpsk", n_blocks=8, depth=4, snr_db=20.0, seed=5,
        payload_text="short test payload",
    )
    assert iq.size > 0
    assert np.iscomplexobj(iq)
    assert truth.rs == {"n": RS_N, "k": RS_K}
    assert truth.interleave_depth == 4
    assert truth.payload_n_bytes == len(payload)
