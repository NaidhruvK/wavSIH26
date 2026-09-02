"""The 2 Sep gate: Reed-Solomon registered, exact match on 20 streams per code.

> Decoded bits equal source at 0% injected BER, for both code plug-ins.
> Exact match on 20 streams per code; BER curve plotted.

Both codes are driven through their own blind recovery first, so these assert
the whole path - recover parameters, then decode - rather than a decoder handed
the answer.

RS deliberately does NOT use rank collapse. RS(255,223) has a binary image of
dimension 1784 inside 2040, so the deficiency is real but only appears at a row
length of 2040 bits, needing ~4.3 million bits before the sweep could reach it
against a MAX_PERIOD of 512. The decoder is its own detector instead: on the
right parameters every block decodes with zero corrections, on the wrong ones
it fails outright.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: F401
import pipeline.s5_decode.conv_code  # noqa: F401
import pipeline.s5_decode.rs_code  # noqa: F401
from registry import CODES, describe
from pipeline.s5_decode.rs_code import STANDARD_PROFILES, ReedSolomonCode
from tests.fixtures.local_zoo import make_rs_stream, make_stream

TRIALS = 20


def _rs():
    return CODES["reed-solomon"]


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------

def test_reed_solomon_is_registered_alongside_conv():
    counts = describe()["counts"]
    assert counts["codes"] >= 2
    assert {"conv", "reed-solomon"} <= set(CODES)


def test_plugin_satisfies_the_codes_protocol():
    p = ReedSolomonCode()
    for method in ("blind_recover", "decode", "validate"):
        assert callable(getattr(p, method))


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def test_rs_exact_on_twenty_streams():
    """20/20 exact, each with a DIFFERENT byte alignment - recovering the block
    boundary is part of the problem, not a given."""
    exact = 0
    failures = []
    for s in range(TRIALS):
        bits, truth, payload = make_rs_stream(6, seed=3000 + s, offset_bytes=s * 3)
        params = _rs().blind_recover(bits)
        if params is None:
            failures.append((s, "no recovery"))
            continue
        got = np.packbits(_rs().decode(bits, params)).tobytes()
        if got[:len(payload)] == payload and (params.n, params.k) == (255, 223):
            exact += 1
        else:
            failures.append((s, "n=%d k=%d off=%d" % (params.n, params.k, params.offset)))
    assert exact == TRIALS, "%d/%d; %s" % (exact, TRIALS, failures[:3])


@pytest.mark.parametrize("offset_bytes", [0, 1, 7, 100, 254])
def test_block_alignment_is_recovered(offset_bytes):
    bits, truth, payload = make_rs_stream(6, seed=11, offset_bytes=offset_bytes)
    params = _rs().blind_recover(bits)
    assert params is not None
    assert params.offset == offset_bytes
    assert params.errata_rate == 0.0


def test_conv_exact_on_twenty_streams():
    """The other half of the same gate. 9000 source bits, because
    ConvCode.blind_recover refuses below MIN_BITS=8192 and a shorter fixture
    fails for the wrong reason."""
    exact = 0
    for s in range(TRIALS):
        bits, truth = make_stream(9_000, None, None, seed=2000 + s)
        params = CODES["conv"].blind_recover(bits)
        if params is None or tuple(params.generators_octal) != tuple(truth.polys_octal):
            continue
        dec = CODES["conv"].decode(bits, params)
        src = np.random.default_rng(2000 + s).integers(0, 2, 9_000, dtype=np.uint8)
        n = min(len(dec), len(src))
        exact += bool(np.array_equal(dec[:n], src[:n]))
    assert exact == TRIALS, "%d/%d" % (exact, TRIALS)


# --------------------------------------------------------------------------
# it must refuse things that are not RS
# --------------------------------------------------------------------------

def test_random_data_is_not_claimed_as_reed_solomon():
    rng = np.random.default_rng(7)
    for _ in range(3):
        assert _rs().blind_recover(rng.integers(0, 2, 300_000, dtype=np.uint8)) is None


def test_a_convolutional_stream_is_not_claimed_as_reed_solomon():
    """Two codes in the registry means each must decline the other's streams,
    or the orchestrator's first matching plug-in wins by import order."""
    bits, _ = make_stream(40_000, None, None, seed=5)
    assert _rs().blind_recover(bits) is None


def test_short_stream_is_declined():
    assert _rs().blind_recover(np.zeros(2_000, dtype=np.uint8)) is None


# --------------------------------------------------------------------------
# behaviour under errors - the cliff
# --------------------------------------------------------------------------

def test_errors_within_the_correction_limit_are_fixed_exactly():
    """t = (n-k)/2 = 16 symbols per 255-byte block. Well inside it, the payload
    comes back bit-exact."""
    bits, truth, payload = make_rs_stream(6, ber=0.0005, seed=21)
    params = _rs().blind_recover(bits)
    assert params is not None
    got = np.packbits(_rs().decode(bits, params)).tobytes()
    assert got[:len(payload)] == payload


def test_beyond_the_limit_it_declines_rather_than_inventing():
    """An RS block either comes back right or does not come back. It must never
    come back plausible and wrong."""
    bits, truth, payload = make_rs_stream(6, ber=0.05, seed=22)
    params = _rs().blind_recover(bits)
    if params is not None:
        got = np.packbits(_rs().decode(bits, params)).tobytes()
        assert got == b"" or got[:len(payload)] == payload, \
            "returned corrupted data instead of declining"


def test_correction_load_reports_how_hard_the_decoder_worked():
    bits, _, _ = make_rs_stream(6, seed=23)
    params = _rs().blind_recover(bits)
    load = _rs().correction_load(bits, params)
    assert load["blocks"] >= 4
    assert load["errata_rate"] == 0.0


def test_standard_profiles_are_bounded():
    """Risk #5 - the search is a dictionary, and it must stay small and
    honest about being one."""
    assert 0 < len(STANDARD_PROFILES) <= 8
    assert (255, 223) == STANDARD_PROFILES[0], "CCSDS profile should be tried first"
    for n, k in STANDARD_PROFILES:
        assert 0 < k < n <= 255
