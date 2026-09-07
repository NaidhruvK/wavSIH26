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
           "inject_errors", "gilbert_elliott_mask", "inject_burst_errors",
           "write_pair", "CCSDS_SCRAMBLER"]

# Real CCSDS 131.0-B pseudo-randomiser: h(x) = x^8+x^7+x^5+x^3+1, period 255.
# (Nehal's fixture originally had a period-7 polynomial mislabelled as
# maximal-length -- verified by measurement, not by reading it.)
#
# 7 Sep, caught by Nehal building a STANDARD_RANDOMISERS table against this
# constant: 0o435 = 0x11D = x^8+x^4+x^3+x^2+1, the GF(256) field polynomial
# used everywhere else in this project for Reed-Solomon (reedsolo's default,
# and the one pipeline/s5_decode/rs_code.py relies on) -- an easy constant to
# reach for while writing an RS-and-randomiser generator, and NOT the CCSDS
# randomiser the comment above (and this constant's own name) describes.
# 0o651 = 0x1A9 = x^8+x^7+x^5+x^3+1 is the polynomial that comment is
# actually describing. Both are primitive of degree 8 (period 255 either
# way), so nothing was broken -- the corpus was always a valid, self-
# consistent additive scrambler between this generator and any receiver
# checking against this same constant -- but the earlier 0o435 was a
# mislabel, not a working choice with a wrong comment.
CCSDS_SCRAMBLER = 0o651


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
    payload_text: str | None = None
    mean_burst: float = 1.0

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


def gilbert_elliott_mask(n: int, ber: float, mean_burst: float,
                          rng: np.random.Generator, p_bad: float = 0.5) -> np.ndarray:
    """Error positions from a two-state Gilbert-Elliott channel.

    7 Sep, ported from tests/fixtures/local_zoo.py so zoo/ can produce the
    bursty (correlated) error model a real receiver actually makes, not just
    independent flips -- one of the two remaining reasons that fixture was
    still load-bearing (12 test files, 7 report studies) after
    zoo/build_rf_corpus.py replaced everything else it used to do.

    The standard model for a channel that loses runs of symbols rather than
    scattered ones: a carrier or timing loop slips, and everything is wrong
    until it re-locks.

        GOOD  error probability 0
        BAD   error probability p_bad (0.5 = the demodulator is guessing)

    Parameterised by the two numbers anyone actually cares about -- the
    overall error rate and the mean burst length -- rather than by
    transition probabilities directly. Given those:

        P(bad)  = ber / p_bad                 so the average rate comes out right
        p_ba    = 1 / mean_burst              so bursts last that long on average
        p_ab    = p_ba * P(bad) / (1 - P(bad))

    Setting mean_burst = 1 does NOT reduce to the independent case, because a
    burst still errs at p_bad rather than at 1. That is deliberate: the
    comparison that matters is the same overall BER, differently clustered.
    """
    if ber <= 0 or n <= 0:
        return np.zeros(n, dtype=bool)

    p_state_bad = min(ber / p_bad, 0.99)
    p_ba = min(1.0, 1.0 / max(mean_burst, 1.0))
    p_ab = min(1.0, p_ba * p_state_bad / max(1e-12, 1.0 - p_state_bad))

    # Simulate the chain in runs rather than bit by bit: a geometric dwell
    # time in each state. 200k bits one at a time in Python is seconds; this
    # is milliseconds and is exactly the same process.
    mask = np.zeros(n, dtype=bool)
    pos, bad = 0, False
    while pos < n:
        p_leave = p_ba if bad else p_ab
        dwell = 1 if p_leave >= 1.0 else int(rng.geometric(max(p_leave, 1e-9)))
        end = min(n, pos + dwell)
        if bad:
            span = end - pos
            mask[pos:end] = rng.random(span) < p_bad
        pos, bad = end, not bad
    return mask


def inject_burst_errors(bits: np.ndarray, ber: float, mean_burst: float,
                         rng: np.random.Generator, p_bad: float = 0.5):
    """Flip bits in correlated runs, at the same overall rate as
    `inject_errors`. See reports/burst_channel.md for why this matters:
    rank collapse counts damaged ROWS, not damaged bits, so clustering the
    same errors into fewer rows can HELP recovery rather than hurt it."""
    if ber <= 0:
        return bits.copy(), 0
    mask = gilbert_elliott_mask(len(bits), ber, mean_burst, rng, p_bad)
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
    mean_burst: float = 1.0,
    payload_text: str | None = None,
) -> tuple[np.ndarray, Truth]:
    """Build one coded bits-only stream and its truth, per the contract.

    Pipeline order: encode -> interleave -> scramble -> inject errors.
    n_source_bits defaults high enough to clear the >=150,000 coded-bit
    floor the contract sets (periods up to ~350 stay searchable).

    `payload_text`, `mean_burst`: 7 Sep, added at Nehal's request -- the
    last two things tests/fixtures/local_zoo.make_stream could do that this
    function couldn't, and the reason that fixture (12 test files, 7 report
    studies, plus pipeline/s4_recover/cli.py) was still load-bearing.
    `payload_text` repeats real text to fill n_source_bits (a message
    appearing on screen after decode is self-evident in a way "20000 bits
    matched 20000 bits" is not); `mean_burst` > 1.0 switches error injection
    from independent flips to a Gilbert-Elliott bursty channel (see
    inject_burst_errors) at the same overall BER, matching what a real
    demodulator that slips and re-locks actually produces.
    """
    rng = np.random.default_rng(seed)
    if payload_text is None:
        src = rng.integers(0, 2, n_source_bits, dtype=np.uint8)
    else:
        # Real text, repeated to length -- same reasoning and construction
        # as tests/fixtures/local_zoo.make_stream's version, so callers
        # switching from that fixture to this function see identical bits.
        raw = payload_text.encode("utf-8")
        reps = max(1, n_source_bits // (8 * len(raw)) + 1)
        src = np.unpackbits(np.frombuffer(raw * reps, dtype=np.uint8))[:n_source_bits]
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

    if mean_burst > 1.0:
        bits, n_flipped = inject_burst_errors(bits, ber, mean_burst, rng)
    else:
        bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_source_bits,
        code={"family": "conv", "rate": "1/2", "K": K,
              "polys_octal": list(polys), "poly_notation": "octal"},
        interleaver=interleaver_truth,
        scrambler=scrambler_truth,
        injected_ber=ber,
        n_flipped=n_flipped,
        error_model="independent" if mean_burst <= 1.0 else "gilbert-elliott",
        start_offset=offset,
        pipeline_order=["encode", "interleave", "scramble", "inject"],
        seed=seed,
        payload_text=payload_text,
        mean_burst=mean_burst,
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