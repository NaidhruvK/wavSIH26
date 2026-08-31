"""TEMPORARY local stand-in for Dheeraj's bits-only zoo.

DEATH DATE: whenever zoo/ lands with its bits-only mode. Delete this file then
and point the tests at the real corpus - do not let two sources of ground truth
coexist, because the moment they disagree nobody will know which one is right.

It exists only so S4 can be built and gated tonight without waiting on the zoo.
It generates exactly what the real zoo's bits-only mode is specified to give:
coded, interleaved, optionally scrambled bitstreams with a configurable
injected bit-error rate, and a truth dict beside every stream.

Everything here is seeded. A trial that fails must be reproducible from its
seed alone.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s5_decode.conv_reference import conv_encode, POLY_171_133
from pipeline.s4_recover.interleavers import block_interleave

__all__ = ["Truth", "make_stream", "lfsr_scramble", "inject_errors", "random_case"]

# Factorisations worth drawing from: period >= 32 so the collapse is
# unambiguous, and both dimensions > 1 so it is a real interleaver.
DEPTH_WIDTH_POOL = [
    (4, 8), (4, 16), (8, 8), (8, 12), (8, 16), (6, 16),
    (12, 8), (16, 6), (16, 8), (16, 12), (32, 4), (10, 12),
]


@dataclass
class Truth:
    n_source_bits: int
    polys_octal: tuple[int, int]
    K: int
    depth: int | None
    width: int | None
    period: int | None
    scrambler_poly: int | None
    injected_ber: float
    n_flipped: int
    seed: int
    start_trim: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def lfsr_scramble(bits: np.ndarray, poly: int = 0o177, seed_state: int = 0x7F) -> np.ndarray:
    """Additive (synchronous) scrambler: XOR the stream with an LFSR sequence.

    poly is the feedback polynomial in the usual octal form. The default is the
    degree-6 maximal-length polynomial used in several CCSDS profiles.
    """
    deg = poly.bit_length() - 1
    state = seed_state & ((1 << deg) - 1)
    if state == 0:
        state = 1
    taps = poly & ((1 << deg) - 1)
    out = np.empty(len(bits), dtype=np.uint8)
    for i in range(len(bits)):
        fb = bin(state & taps).count("1") & 1
        out[i] = bits[i] ^ (state & 1)
        state = (state >> 1) | (fb << (deg - 1))
    return out


def inject_errors(bits: np.ndarray, ber: float, rng: np.random.Generator):
    """Flip bits independently at rate `ber`.

    NOTE the limitation, and keep saying it out loud: these errors are
    INDEPENDENT. Real demodulator errors are bursty and correlated. Any BER
    ceiling measured against this generator is an optimistic bound, and the
    3 Sep junction is where that gets corrected against real LLRs.
    """
    if ber <= 0:
        return bits.copy(), 0
    mask = rng.random(len(bits)) < ber
    out = bits.copy()
    out[mask] ^= 1
    return out, int(mask.sum())


def make_stream(n_source_bits: int = 20000, depth: int | None = 8, width: int | None = 12,
                polys=POLY_171_133, K: int = 7, scramble: bool = False,
                scrambler_poly: int = 0o177, ber: float = 0.0, seed: int = 0):
    """Build one coded stream and its truth. Returns (bits, Truth)."""
    rng = np.random.default_rng(seed)
    src = rng.integers(0, 2, n_source_bits, dtype=np.uint8)
    bits = conv_encode(src, polys=polys, K=K)

    period = None
    if depth and width:
        period = depth * width
        bits = block_interleave(bits, depth, width)

    if scramble:
        bits = lfsr_scramble(bits, scrambler_poly)

    bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_source_bits, polys_octal=tuple(polys), K=K,
        depth=depth, width=width, period=period,
        scrambler_poly=scrambler_poly if scramble else None,
        injected_ber=ber, n_flipped=n_flipped, seed=seed,
    )
    return bits, truth


MAX_POOL_PERIOD = max(d * w for d, w in DEPTH_WIDTH_POOL)


def bits_needed(period: int, row_margin: int = 64) -> int:
    """Coded bits required before a period is even searchable: L*(L+margin)."""
    return period * (period + row_margin)


def random_case(seed: int, n_source_bits: int | None = None, ber: float = 0.0,
                random_offset: bool = True):
    """One randomly parameterised trial - what the 10-trial gate draws from.

    The stream is trimmed by a random amount so the first bit is NOT a block
    boundary. Recovering the alignment is part of the problem; a fixture that
    always starts at offset 0 is testing an easier problem than the real one.

    Length is derived from the pool, not guessed: too short and the sweep
    cannot reach the period, which shows up as a false "no code detected".
    """
    rng = np.random.default_rng(seed)
    depth, width = DEPTH_WIDTH_POOL[int(rng.integers(0, len(DEPTH_WIDTH_POOL)))]
    if n_source_bits is None:
        # coded stream is 2x source, and we want ~1.6x the bare minimum
        n_source_bits = int(bits_needed(MAX_POOL_PERIOD) * 1.6 / 2)
    bits, truth = make_stream(n_source_bits=n_source_bits, depth=depth, width=width,
                              ber=ber, seed=seed)
    if random_offset:
        trim = int(rng.integers(0, depth * width))
        bits = bits[trim:]
        truth.start_trim = trim
    return bits, truth
