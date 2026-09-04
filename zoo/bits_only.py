"""zoo/bits_only.py

Bits-only corpus generator, per docs/zoo-bits-only-contract.md (Nehal -> Dheeraj).

Produces raw coded bitstreams -- convolutional encode -> interleave -> scramble
-> inject errors -- with a truth JSON sidecar per file, matching the schema
Nehal's S4 stream reads. This is the REAL replacement for
tests/fixtures/local_zoo.py: once files from here are on disk, delete that
fixture and re-run S4's gates against this corpus.

OWNERSHIP: Dheeraj. Reuses pipeline.s5_decode.conv_reference (encoder) and
pipeline.s4_recover.interleavers (block_interleave) rather than
re-implementing them -- one encoder, one interleaver, used by everyone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from pipeline.s5_decode.conv_reference import conv_encode, POLY_171_133
from pipeline.s4_recover.interleavers import block_interleave

__all__ = ["Truth", "make_stream", "make_uncoded_random", "lfsr_scramble",
           "inject_errors", "write_pair", "CCSDS_SCRAMBLER"]

# Real CCSDS 131.0-B pseudo-randomiser: h(x) = x^8+x^7+x^5+x^3+1, period 255.
# (Nehal's fixture originally had a period-7 polynomial mislabelled as
# maximal-length -- verified by measurement, not by reading it.)
CCSDS_SCRAMBLER = 0o435


@dataclass
class Truth:
    n_source_bits: int
    code: dict
    interleaver: dict | None
    scrambler: dict | None
    injected_ber: float
    n_flipped: int
    error_model: str
    start_offset: int
    pipeline_order: list
    seed: int

    def as_dict(self) -> dict:
        return asdict(self)


def lfsr_scramble(bits: np.ndarray, poly: int = CCSDS_SCRAMBLER,
                   seed_state: int = 0xFF) -> np.ndarray:
    """Additive scrambler: XOR the stream with an LFSR sequence."""
    deg = poly.bit_length() - 1
    state = seed_state & ((1 << deg) - 1) or 1
    taps = poly & ((1 << deg) - 1)
    out = np.empty(len(bits), dtype=np.uint8)
    for i in range(len(bits)):
        fb = bin(state & taps).count("1") & 1
        out[i] = bits[i] ^ (state & 1)
        state = (state >> 1) | (fb << (deg - 1))
    return out


def inject_errors(bits: np.ndarray, ber: float, rng: np.random.Generator):
    """Independent bit flips at rate `ber`. Seeded and reproducible."""
    if ber <= 0:
        return bits.copy(), 0
    mask = rng.random(len(bits)) < ber
    out = bits.copy()
    out[mask] ^= 1
    return out, int(mask.sum())


def bits_needed(period: int, row_margin: int = 64) -> int:
    """Coded bits required before a period is even searchable: L*(L+margin)."""
    return period * (period + row_margin)


def make_stream(
    n_source_bits: int = 80_000,
    depth: int | None = 8,
    width: int | None = 12,
    polys=POLY_171_133,
    K: int = 7,
    scramble: bool = False,
    scrambler_poly: int = CCSDS_SCRAMBLER,
    ber: float = 0.0,
    seed: int = 0,
    start_offset: int | None = None,
) -> tuple[np.ndarray, Truth]:
    """Build one coded bits-only stream and its truth, per the contract.

    Pipeline order: encode -> interleave -> scramble -> inject errors.
    n_source_bits defaults high enough to clear the >=150,000 coded-bit
    floor the contract sets (periods up to ~350 stay searchable).
    """
    rng = np.random.default_rng(seed)
    src = rng.integers(0, 2, n_source_bits, dtype=np.uint8)
    bits = conv_encode(src, polys=polys, K=K)

    interleaver_truth = None
    period = None
    if depth and width:
        period = depth * width
        bits = block_interleave(bits, depth, width)
        interleaver_truth = {"family": "block", "depth": depth,
                              "width": width, "period": period}

    scrambler_truth = None
    if scramble:
        bits = lfsr_scramble(bits, scrambler_poly)
        scrambler_truth = {"family": "lfsr", "poly_octal": scrambler_poly,
                            "seed_state": 0xFF}

    offset = 0
    if start_offset is None and period:
        # Deliberately not a block boundary -- "ideal, not required" in the
        # contract. Recovering alignment is part of the problem.
        offset = int(rng.integers(0, period))
    elif start_offset is not None:
        offset = start_offset
    if offset:
        bits = bits[offset:]

    bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_source_bits,
        code={"family": "conv", "rate": "1/2", "K": K,
              "polys_octal": list(polys), "poly_notation": "octal"},
        interleaver=interleaver_truth,
        scrambler=scrambler_truth,
        injected_ber=ber,
        n_flipped=n_flipped,
        error_model="independent",
        start_offset=offset,
        pipeline_order=["encode", "interleave", "scramble", "inject"],
        seed=seed,
    )
    return bits, truth


def make_uncoded_random(n_bits: int = 160_000, seed: int = 999
                         ) -> tuple[np.ndarray, Truth]:
    """The false-positive case (risk #15): random bits, no code at all.

    A judge will run exactly this file. It must be in the corpus, labelled,
    not improvised on demo day.
    """
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, n_bits, dtype=np.uint8)
    truth = Truth(
        n_source_bits=n_bits,
        code={"family": "none"},
        interleaver=None,
        scrambler=None,
        injected_ber=0.0,
        n_flipped=0,
        error_model="none",
        start_offset=0,
        pipeline_order=["random"],
        seed=seed,
    )
    return bits, truth


def write_pair(bits: np.ndarray, truth: Truth, out_dir: Path, name: str) -> None:
    """One .npy bits file + one .json truth sidecar, same stem."""
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / f"{name}.bits.npy", bits.astype(np.uint8))
    with open(out_dir / f"{name}.json", "w") as f:
        json.dump(truth.as_dict(), f, indent=2)