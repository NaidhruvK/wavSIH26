"""tests/unit/test_bits_only.py"""
from __future__ import annotations

import numpy as np
import pytest

from zoo.bits_only import (CCSDS_SCRAMBLER, DEPTH_WIDTH_POOL, MAX_POOL_PERIOD,
                            bits_needed, gilbert_elliott_mask,
                            inject_burst_errors, lfsr_scramble, make_rs_stream,
                            make_stream, random_case)


def test_ccsds_scrambler_is_the_real_ccsds_polynomial():
    """7 Sep, caught by Nehal: this constant used to be 0o435 (0x11D, the
    GF(256) field polynomial reedsolo/Reed-Solomon use), not the CCSDS
    131.0-B randomiser its own name and comment describe. h(x) =
    x^8+x^7+x^5+x^3+1 has taps at bits 7,5,3,0 below the implicit x^8 --
    0o651 = 0b1_1010_1001, which is exactly that."""
    assert CCSDS_SCRAMBLER == 0o651
    assert CCSDS_SCRAMBLER == 0x1A9
    deg = CCSDS_SCRAMBLER.bit_length() - 1
    assert deg == 8
    taps = CCSDS_SCRAMBLER & ((1 << deg) - 1)
    assert taps == (1 << 7) | (1 << 5) | (1 << 3) | (1 << 0)


def test_ccsds_scrambler_is_maximal_length():
    """Primitive polynomial of degree 8 -> period EXACTLY 255, same
    requirement the old (wrong) constant also happened to satisfy -- the
    mislabel was never a working-vs-broken question, only a standards-
    compliance one. XORing zeros with the LFSR exposes its raw output
    sequence directly, so this is a period check on that sequence: it must
    repeat at lag 255 (maximal length for a degree-8 poly) and not repeat
    at any smaller divisor of 255 (a real but shorter period, meaning the
    polynomial was primitive of a lower degree in disguise)."""
    seq = lfsr_scramble(np.zeros(1020, dtype=np.uint8), CCSDS_SCRAMBLER)
    assert np.array_equal(seq[:255], seq[255:510])
    assert np.array_equal(seq[:255], seq[510:765])
    for divisor in (1, 3, 5, 15, 17, 51, 85):   # every proper divisor of 255
        assert not np.array_equal(seq[:-divisor], seq[divisor:]), divisor


def test_payload_text_round_trips_through_conv_only():
    """No RS/interleave layer here, just conv_encode -- a much simpler
    check than tests/unit/test_ccsds.py's full-chain one, isolating that
    make_stream's own payload_text repeat-to-length logic is correct."""
    from pipeline.s5_decode.conv_code import ConvCode

    text = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG. "
    bits, truth = make_stream(n_source_bits=4000, depth=None, width=None,
                               payload_text=text, seed=3)
    assert truth.payload_text == text

    params = {"n": 2, "memory": 6, "generators_octal": (0o171, 0o133)}
    decoded = ConvCode().decode(bits, params)
    recovered = np.packbits(decoded[:len(text) * 8]).tobytes()
    assert recovered.startswith(text.encode("utf-8"))


def test_mean_burst_default_matches_independent_model():
    bits, truth = make_stream(n_source_bits=2000, depth=None, width=None,
                               ber=0.01, seed=1)
    assert truth.error_model == "independent"
    assert truth.mean_burst == 1.0


def test_mean_burst_above_one_uses_gilbert_elliott():
    bits, truth = make_stream(n_source_bits=2000, depth=None, width=None,
                               ber=0.05, mean_burst=20.0, seed=1)
    assert truth.error_model == "gilbert-elliott"
    assert truth.mean_burst == 20.0
    assert truth.n_flipped > 0


def test_gilbert_elliott_mask_hits_target_ber_on_average():
    """Not exact per-call (it's a stochastic process), but the overall rate
    across many bits should land close to the requested BER -- the whole
    point of parameterising by (ber, mean_burst) rather than raw transition
    probabilities."""
    rng = np.random.default_rng(0)
    mask = gilbert_elliott_mask(200_000, ber=0.02, mean_burst=10.0, rng=rng)
    measured = mask.mean()
    assert abs(measured - 0.02) < 0.005, f"measured {measured}"


def test_gilbert_elliott_errors_cluster_more_than_independent():
    """The entire reason this model exists: mean_burst > 1 should produce
    longer runs of consecutive errors than mean_burst = 1 at the same BER.

    Not a 1:1 scaling with mean_burst -- p_ba = 1/mean_burst governs the BAD
    STATE's dwell time, but only p_bad=0.5 of those bits actually flip, so
    a run of consecutive ERRORS is shorter than a bad-state dwell. Measured
    at mean_burst=1 (which is deliberately NOT the independent case -- see
    gilbert_elliott_mask's docstring): mean run length ~1.0, since p_ba=1
    means every bad-state dwell is exactly 1 bit long. At mean_burst=20:
    measured ~1.9, a real and repeatable ~2x, not the 3x an earlier,
    unverified version of this test assumed."""
    rng = np.random.default_rng(0)
    mask = gilbert_elliott_mask(200_000, ber=0.02, mean_burst=1.0, rng=rng)
    mask_bursty = gilbert_elliott_mask(200_000, ber=0.02, mean_burst=20.0,
                                        rng=np.random.default_rng(0))

    def mean_run_length(m):
        d = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        return float((ends - starts).mean()) if starts.size else 0.0

    assert mean_run_length(mask_bursty) > mean_run_length(mask) * 1.5


def test_inject_burst_errors_zero_ber_is_noop():
    bits = np.zeros(500, dtype=np.uint8)
    out, n = inject_burst_errors(bits, 0.0, 20.0, np.random.default_rng(0))
    assert n == 0
    assert np.array_equal(out, bits)


# ---------------------------------------------------------------------------
# 7 Sep: random_case and make_rs_stream, ported from
# tests/fixtures/local_zoo.py at Nehal's request -- the last two functions
# blocking that fixture's deletion.
# ---------------------------------------------------------------------------

def test_random_case_is_reproducible_from_seed_alone():
    bits_a, truth_a = random_case(seed=7)
    bits_b, truth_b = random_case(seed=7)
    assert np.array_equal(bits_a, bits_b)
    assert truth_a.as_dict() == truth_b.as_dict()


def test_random_case_draws_depth_width_from_the_pool():
    _bits, truth = random_case(seed=3)
    assert truth.interleaver is not None
    dw = (truth.interleaver["depth"], truth.interleaver["width"])
    assert dw in DEPTH_WIDTH_POOL
    assert truth.interleaver["period"] == dw[0] * dw[1]


def test_random_case_default_length_covers_the_hardest_pool_entry():
    """The bit count must be long enough that even MAX_POOL_PERIOD (the
    hardest case the pool can draw) is searchable -- too short and a
    rank-collapse sweep can't reach the period at all, which looks like
    "no code detected" rather than what it actually is."""
    _bits, truth = random_case(seed=11)
    assert truth.n_source_bits * 2 >= bits_needed(MAX_POOL_PERIOD)


def test_random_case_offset_is_zero_when_disabled():
    _bits, truth = random_case(seed=4, random_offset=False)
    assert truth.start_offset == 0


def test_random_case_offset_is_usually_nonzero_when_enabled():
    """Not deterministically nonzero for any single seed (0 is a valid draw
    from the range), so checked over several seeds -- at least most should
    land away from the block boundary, which is the entire point (a fixture
    that always starts at offset 0 tests an easier problem than the real
    one)."""
    offsets = [random_case(seed=s)[1].start_offset for s in range(10)]
    assert sum(o != 0 for o in offsets) >= 7


def test_bits_needed_scales_with_period_squared_ish():
    assert bits_needed(100) > bits_needed(50)
    assert bits_needed(32, row_margin=64) == 32 * (32 + 64)


def test_make_rs_stream_round_trips_through_reedsolo():
    import reedsolo

    bits, truth, payload = make_rs_stream(n_blocks=4, seed=9)
    assert truth.code == {"family": "rs", "n": 255, "k": 223}
    assert bits.size == 4 * 255 * 8

    rs = reedsolo.RSCodec(255 - 223)
    encoded = np.packbits(bits).tobytes()
    recovered = bytearray()
    for b in range(4):
        block = encoded[b * 255:(b + 1) * 255]
        dec, _, _ = rs.decode(block)
        recovered.extend(dec)
    assert bytes(recovered) == payload


def test_make_rs_stream_payload_text_repeats_to_length():
    text = "PAYLOAD "
    _bits, truth, payload = make_rs_stream(n_blocks=2, seed=1, payload_text=text)
    assert truth.payload_text == text
    assert payload.startswith(text.encode("utf-8"))


def test_make_rs_stream_offset_bytes_prepends_junk():
    bits0, truth0, _ = make_rs_stream(n_blocks=2, seed=2, offset_bytes=0)
    bits5, truth5, _ = make_rs_stream(n_blocks=2, seed=2, offset_bytes=5)
    assert truth5.start_offset == 5 * 8
    assert bits5.size == bits0.size + 5 * 8


def test_make_rs_stream_injects_errors_at_requested_ber():
    bits, truth, _payload = make_rs_stream(n_blocks=8, seed=6, ber=0.02)
    measured = truth.n_flipped / bits.size   # bits.size = n_blocks*n*8, not n_source_bits (n_blocks*k*8)
    assert abs(measured - 0.02) < 0.01
