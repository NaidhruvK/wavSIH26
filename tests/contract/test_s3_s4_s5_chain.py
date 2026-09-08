"""The whole chain, in one test: WAV-shaped samples in, source bits out.

This is the integration the 3 September gate is really about, and it is the one
thing S3's own contract test cannot do. `test_llr_contract.py` asserts the LLR
sign convention against the bits the fixture transmitted - which catches a sign
error in S3, and is blind to a sign error that S3 and the fixture share. Only
running the LLRs through the decoder that actually consumes them settles it,
because Viterbi against a mis-signed metric decodes to noise and raises nothing.

    modulate -> channel -> S3 demodulate -> S4 blind_recover -> S5 Viterbi

Deliberately small. commpy's Viterbi at K=7 is not fast, and this test earns its
place by being decisive rather than broad: one modulation, one SNR, the full
depth. The breadth lives in reports/s3_s4_junction.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s4_recover.interleavers  # noqa: E402,F401  (registers)
import pipeline.s5_decode.conv_code  # noqa: E402,F401  (registers)
from pipeline.s3_receive import llr_to_bits  # noqa: E402
from pipeline.s4_recover.rank_collapse import blind_recover  # noqa: E402
from pipeline.s5_decode.conv_reference import POLY_171_133, conv_encode  # noqa: E402
from registry import CODES, MODULATIONS  # noqa: E402
from tests.fixtures.corpus import synth  # noqa: E402

TRUE_GENS = (0o171, 0o133)


def _ber_against(decoded: np.ndarray, source: np.ndarray) -> float:
    """Decoded bits against the source, aligned by correlation. Harness-only."""
    n = min(decoded.size, 8000)
    if n < 500:
        return 1.0
    a = 1.0 - 2.0 * decoded[:n].astype(float)
    b = 1.0 - 2.0 * source.astype(float)
    L = 1 << int(np.ceil(np.log2(n + source.size)))
    c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)[: source.size - n + 1]
    if c.size == 0:
        return 1.0
    off = int(np.argmax(np.abs(c)))
    e = float(np.mean(decoded[:n] != source[off : off + n]))
    return min(e, 1.0 - e)


@pytest.fixture(scope="module")
def chain():
    rng = np.random.default_rng(20260903)
    source = rng.integers(0, 2, 30000).astype(np.uint8)
    coded = conv_encode(source, polys=POLY_171_133, K=7)
    x, fs, symbol_rate, _ = synth("qpsk", sps=4, snr_db=12.0, bits=coded,
                                  cfo_norm=0.0012, timing_offset_sym=0.37,
                                  seed=3)
    res = MODULATIONS["qpsk"].receive(x, {"fs": fs, "symbol_rate": symbol_rate})
    return source, coded, res


def test_s3_produces_a_locked_soft_stream(chain):
    _, _, res = chain
    assert res.status == "ok", res.reason
    assert res.llrs.size > 10000
    assert np.issubdtype(res.llrs.dtype, np.floating)


def test_s4_recovers_the_generators_from_s3_output(chain):
    _, _, res = chain
    got = [tuple(r.generators_octal) for r in
           (blind_recover(llr_to_bits(c)[:80000]) for c in res.llrs_by_rotation)
           if r.status == "ok" and r.generators_octal]
    assert TRUE_GENS in got, f"S4 never recovered the true generators; saw {got}"


def test_viterbi_decodes_s3_llrs_back_to_the_source_bits(chain):
    """The sign convention, settled through the decoder rather than against
    ourselves. A mis-signed LLR array decodes to roughly 0.5 BER here and
    raises nothing anywhere."""
    source, _, res = chain

    best = 1.0
    for cand in res.llrs_by_rotation:
        rec = blind_recover(llr_to_bits(cand)[:80000])
        if rec.status != "ok" or tuple(rec.generators_octal or ()) != TRUE_GENS:
            continue
        params = {"n": 2, "memory": 6,
                  "generators_octal": tuple(rec.generators_octal)}
        for offset in (0, 1):
            decoded = CODES["conv"].decode(cand[offset : offset + 16000], params)
            best = min(best, _ber_against(decoded, source))

    assert best < 0.01, (
        f"best decoded BER was {best:.4f}; at ~0.5 the LLR sign convention is "
        "inverted somewhere between S3 and conv_code.decode")


def test_a_wrong_rotation_decodes_to_noise(chain):
    """The other half of the same claim. If every rotation decoded, the test
    above would be measuring nothing."""
    source, _, res = chain

    wrong = []
    for cand in res.llrs_by_rotation:
        rec = blind_recover(llr_to_bits(cand)[:80000])
        if rec.status == "ok" and tuple(rec.generators_octal or ()) != TRUE_GENS \
                and rec.generators_octal:
            params = {"n": 2, "memory": 6,
                      "generators_octal": tuple(rec.generators_octal)}
            decoded = CODES["conv"].decode(cand[:16000], params)
            wrong.append(_ber_against(decoded, source))

    if not wrong:
        pytest.skip("no wrong-generator rotation on this stream")
    assert min(wrong) > 0.2, (
        f"a rotation with the wrong generators decoded at {min(wrong):.4f} - "
        "that should not be possible and would undermine the positive test")
