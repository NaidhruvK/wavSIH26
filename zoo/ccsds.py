"""zoo/ccsds.py

The real concatenated CCSDS 131.0-B profile: RS(255,223) outer code, then
BYTE/symbol-level interleaving across `depth` consecutive RS codewords
(depth I in {1,2,3,4,5,8} per the standard), then the pseudo-randomiser,
then the rate-1/2 K=7 convolutional code as the INNER code -- in that
order, which is the real standard's order and is randomise-BEFORE-inner-
code, not the bit-level-interleaved / different-order stand-in this
project has been testing against so far (tests/fixtures/local_zoo.py's
own make_ccsds_stream, whose docstring already states its own deviation:
bit-level interleaving instead of byte-level, and interleave-before-
convolutional instead of scramble-before-convolutional).

5 Sep, requested by a teammate verifying S4-S6 concatenated recovery:
"real CCSDS interleaves symbols (bytes, depth I in 1..8) and randomises
before the convolutional encoder... a corpus file built to the real
standard would be more valuable than a copy of my fixture." This is that
file, generated the same way as every other zoo/ corpus (a WAV + truth
JSON via zoo/rf.py's channel/write path), not a bits-only fixture.

Deliberately written to zoo/corpus/ccsds/, NOT zoo/corpus/rf/: every
existing consumer globs zoo/corpus/rf/*dB_*.wav and assumes
zoo.bits_only.make_stream's single-code truth schema (used by, among
others, this project's own reports/envelope_study.py to regenerate exact
source bits from a seed) -- dropping a differently-coded, differently-
structured file into that directory would silently corrupt every one of
those without any of them being wrong to have assumed what they assumed.

OWNERSHIP: Dheeraj. Reuses pipeline.s5_decode.conv_reference (the same
convolutional encoder everyone else uses), zoo.bits_only's randomiser
(same CCSDS_SCRAMBLER polynomial), and zoo.rf's channel/WAV-writing path
-- one encoder, one scrambler, one channel model, used by everyone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import soundfile as sf

from pipeline.s5_decode.conv_reference import conv_encode, POLY_171_133
from zoo.bits_only import CCSDS_SCRAMBLER, lfsr_scramble
from zoo.rf import _awgn, _frac_delay, modulate_bits

__all__ = ["CCSDSTruth", "rs_encode_blocks", "ccsds_interleave",
           "ccsds_deinterleave", "make_ccsds_stream", "make_ccsds_rf_file",
           "write_ccsds_wav_pair"]

RS_N, RS_K = 255, 223   # CCSDS 131.0-B's own profile -- the one the problem
                        # statement names, and pipeline/s5_decode/rs_code.py's
                        # first (most-likely) STANDARD_PROFILES entry.


@dataclass
class CCSDSTruth:
    scheme: str
    fs: float
    sps: int
    beta: float
    snr_db: float
    cfo_norm: float
    phase_rad: float
    timing_offset_sym: float
    seed: int
    n_bits_used: int
    payload_n_bytes: int
    rs: dict
    interleave_depth: int
    scrambler: dict
    code: dict
    pipeline_order: list

    def as_dict(self) -> dict:
        return asdict(self)


def rs_encode_blocks(payload: bytes, n: int = RS_N, k: int = RS_K) -> list[bytes]:
    """Payload bytes -> a list of n-byte RS codewords, k bytes of payload each.

    Payload is padded with zero bytes to a whole number of k-byte blocks --
    padding is data, not a protocol detail, so byte length before padding
    is recorded in the truth (payload_n_bytes) and callers trim after
    decode rather than this function guessing where real data ends.
    """
    import reedsolo
    rs = reedsolo.RSCodec(n - k)
    padded = payload + b"\x00" * (-len(payload) % k)
    return [bytes(rs.encode(padded[i:i + k])) for i in range(0, len(padded), k)]


def ccsds_interleave(codewords: list[bytes], depth: int) -> bytes:
    """Real CCSDS symbol interleaving: byte 0 of every codeword in the
    depth-I block, then byte 1 of every codeword, ... -- a transpose of the
    (depth x n) codeword matrix, flattened row-major (== the original
    matrix flattened column-major). Spreads a channel burst, which damages
    a run of CONSECUTIVE transmitted bytes, across up to `depth` different
    codewords instead of concentrating it in one -- the entire point of
    interleaving a burst-error channel ahead of a block code.

    len(codewords) must be a multiple of `depth`; interleaving is applied
    per depth-I group, groups concatenated in order (matches how a real
    downlink frames consecutive interleave blocks back to back).
    """
    n = len(codewords[0])
    assert all(len(c) == n for c in codewords), "all codewords must be the same length"
    assert len(codewords) % depth == 0, "codeword count must be a multiple of depth"
    out = bytearray()
    for g in range(0, len(codewords), depth):
        mat = np.frombuffer(b"".join(codewords[g:g + depth]), dtype=np.uint8)
        mat = mat.reshape(depth, n)
        out.extend(mat.T.tobytes())   # transpose, row-major flatten
    return bytes(out)


def ccsds_deinterleave(data: bytes, depth: int, n: int = RS_N) -> list[bytes]:
    """Inverse of ccsds_interleave. Used by the round-trip self-test below;
    a real blind receiver has to find `depth` by search, which is Nehal's
    problem (S4-S6), not implemented here."""
    assert len(data) % (depth * n) == 0, "data length must be a whole number of depth-I blocks"
    codewords: list[bytes] = []
    for g in range(0, len(data), depth * n):
        block = np.frombuffer(data[g:g + depth * n], dtype=np.uint8).reshape(n, depth).T
        codewords.extend(bytes(row) for row in block)
    return codewords


def make_ccsds_stream(
    n_blocks: int = 8,
    depth: int = 4,
    payload: bytes | None = None,
    payload_text: str | None = None,
    polys=POLY_171_133,
    K: int = 7,
    scrambler_poly: int = CCSDS_SCRAMBLER,
    seed: int = 0,
) -> tuple[np.ndarray, bytes, dict]:
    """RS outer -> byte-interleave (depth I) -> randomise -> convolutional
    inner, the real CCSDS 131.0-B transmit order (see module docstring for
    exactly how this differs from tests/fixtures/local_zoo.make_ccsds_stream,
    which interleaves bits and applies the randomiser after the
    convolutional code instead of before it).

    Returns (coded_bits, payload_bytes, meta) -- payload_bytes is the
    RS-layer input a correct end-to-end decode must reproduce (after
    stripping any zero-padding meta['payload_n_bytes'] records).
    """
    rng = np.random.default_rng(seed)
    n_blocks = (n_blocks // depth) * depth or depth   # round up to a multiple of depth

    if payload_text is not None:
        raw = payload_text.encode("utf-8")
        need = n_blocks * RS_K
        payload = (raw * (need // len(raw) + 1))[:need]
    elif payload is None:
        payload = rng.integers(0, 256, n_blocks * RS_K, dtype=np.uint8).tobytes()
    payload_n_bytes = len(payload)

    codewords = rs_encode_blocks(payload, RS_N, RS_K)          # 1. RS outer
    interleaved = ccsds_interleave(codewords, depth)            # 2. byte interleave
    bits = np.unpackbits(np.frombuffer(interleaved, dtype=np.uint8))
    bits = lfsr_scramble(bits, scrambler_poly)                  # 3. randomiser
    bits = conv_encode(bits, polys=polys, K=K)                  # 4. convolutional inner

    meta = dict(payload_n_bytes=payload_n_bytes, rs={"n": RS_N, "k": RS_K},
                interleave_depth=depth, n_codewords=len(codewords),
                scrambler={"family": "lfsr", "poly_octal": scrambler_poly, "seed_state": 0xFF},
                code={"family": "conv", "rate": "1/2", "K": K,
                      "polys_octal": list(polys), "poly_notation": "octal"},
                pipeline_order=["rs_encode", "byte_interleave", "randomise", "conv_encode"])
    return bits, payload[:payload_n_bytes], meta


def make_ccsds_rf_file(
    scheme_name: str = "qpsk", n_blocks: int = 8, depth: int = 4,
    fs: float = 200_000.0, sps: int = 4, beta: float = 0.35,
    snr_db: float = 15.0, cfo_norm: float = 0.0, phase_rad: float = 0.0,
    timing_offset_sym: float = 0.0, payload_text: str | None = None,
    seed: int = 0,
) -> tuple[np.ndarray, bytes, CCSDSTruth]:
    """Coded CCSDS bits -> full RF waveform ready to write as WAV, with
    truth -- same shape as zoo.rf.make_rf_file, extended with the RS/
    interleave-depth metadata a single-code truth JSON has no field for."""
    bits, payload, meta = make_ccsds_stream(
        n_blocks=n_blocks, depth=depth, payload_text=payload_text, seed=seed,
    )
    rng = np.random.default_rng(seed)
    x, n_used = modulate_bits(bits, scheme_name, sps, beta)
    if timing_offset_sym:
        x = _frac_delay(x, timing_offset_sym * sps)
    if cfo_norm or phase_rad:
        n = np.arange(x.size)
        x = x * np.exp(1j * (2 * np.pi * cfo_norm * n + phase_rad))
    iq = _awgn(x, snr_db, rng)

    truth = CCSDSTruth(
        scheme=scheme_name, fs=fs, sps=sps, beta=beta, snr_db=snr_db,
        cfo_norm=cfo_norm, phase_rad=phase_rad,
        timing_offset_sym=timing_offset_sym, seed=seed, n_bits_used=n_used,
        payload_n_bytes=meta["payload_n_bytes"], rs=meta["rs"],
        interleave_depth=meta["interleave_depth"], scrambler=meta["scrambler"],
        code=meta["code"], pipeline_order=meta["pipeline_order"],
    )
    return iq, payload, truth


def write_ccsds_wav_pair(iq: np.ndarray, payload: bytes, truth: CCSDSTruth,
                          out_dir: Path, name: str) -> None:
    """2-channel WAV (I, Q) + truth JSON + the raw payload bytes, so a
    successful decode can be checked with a byte comparison, not just a
    truth-field comparison."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stereo = np.stack([iq.real, iq.imag], axis=-1).astype(np.float32)
    peak = np.max(np.abs(stereo)) or 1.0
    stereo = stereo / peak * 0.9
    sf.write(str(out_dir / f"{name}.wav"), stereo, int(truth.fs))
    with open(out_dir / f"{name}.json", "w") as f:
        json.dump(truth.as_dict(), f, indent=2)
    (out_dir / f"{name}.payload.bin").write_bytes(payload)
