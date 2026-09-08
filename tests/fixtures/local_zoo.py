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

__all__ = ["Truth", "make_stream", "lfsr_scramble", "inject_errors",
           "inject_burst_errors", "gilbert_elliott_mask", "random_case",
           "make_rs_stream",
           "CCSDS_SCRAMBLER"]

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
    payload_text: str | None = None
    mean_burst: float = 1.0
    start_trim: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# CCSDS 131.0-B pseudo-randomiser: h(x) = x^8 + x^7 + x^5 + x^3 + 1.
# Maximal length, period 255. This is the real one, and it is the default here
# because the alternative caused a real problem: the previous default 0o177
# (x^6+...+1, all six taps) has period **7**, not 63. It is not
# maximal-length at all, despite a comment in this file that claimed it was.
# A period-7 sequence is a far weaker scrambler than anything real, and
# validating the 7 Sep Berlekamp-Massey recovery against it would have proved
# almost nothing. Verified by measurement, not by reading the polynomial.
CCSDS_SCRAMBLER = 0o435


def lfsr_scramble(bits: np.ndarray, poly: int = CCSDS_SCRAMBLER,
                  seed_state: int = 0xFF) -> np.ndarray:
    """Additive (synchronous) scrambler: XOR the stream with an LFSR sequence.

    `poly` is the feedback polynomial in the usual octal form. Default is the
    CCSDS 131.0-B pseudo-randomiser, period 255.

    Check the period before trusting a polynomial - scrambling a run of zeros
    returns the raw sequence, so the period is one array comparison away. Not
    every plausible-looking polynomial is maximal-length.
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

    INDEPENDENT errors. Real demodulator errors are not - see
    `inject_burst_errors` below, which exists precisely because every ceiling
    measured against this function is an optimistic bound.
    """
    if ber <= 0:
        return bits.copy(), 0
    mask = rng.random(len(bits)) < ber
    out = bits.copy()
    out[mask] ^= 1
    return out, int(mask.sum())


def gilbert_elliott_mask(n: int, ber: float, mean_burst: float,
                         rng: np.random.Generator, p_bad: float = 0.5):
    """Error positions from a two-state Gilbert-Elliott channel.

    The standard model for a channel that loses runs of symbols rather than
    scattered ones, which is what a receiver actually produces: a carrier or
    timing loop slips, and everything is wrong until it re-locks.

        GOOD  error probability 0
        BAD   error probability p_bad (0.5 = the demodulator is guessing)

    Parameterised by the two numbers anyone actually cares about - the overall
    error rate and the mean burst length - rather than by transition
    probabilities. Given those:

        P(bad)  = ber / p_bad                 so the average rate comes out right
        p_ba    = 1 / mean_burst              so bursts last that long on average
        p_ab    = p_ba * P(bad) / (1 - P(bad))

    Setting mean_burst = 1 does NOT reduce to the independent case, because a
    burst still errs at p_bad rather than at 1. That is deliberate: the
    comparison that matters is same overall BER, different clustering.
    """
    if ber <= 0 or n <= 0:
        return np.zeros(n, dtype=bool)

    p_state_bad = min(ber / p_bad, 0.99)
    p_ba = min(1.0, 1.0 / max(mean_burst, 1.0))
    p_ab = min(1.0, p_ba * p_state_bad / max(1e-12, 1.0 - p_state_bad))

    # Simulate the chain in runs rather than bit by bit: a geometric dwell time
    # in each state. 200k bits one at a time in Python is seconds; this is
    # milliseconds and is exactly the same process.
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
    """Flip bits in correlated runs, at the same overall rate as `inject_errors`.

    This is the honest error model, and the whole point of having it before
    3 Sep is that it changes an unknown into an estimate. Rank collapse counts
    how many ROWS of the matrix are damaged, not how many bits - so clustering
    errors into fewer rows should, in principle, HELP at a fixed BER. Whether
    it does, and by how much, is a measurement, not an opinion.
    """
    if ber <= 0:
        return bits.copy(), 0
    mask = gilbert_elliott_mask(len(bits), ber, mean_burst, rng, p_bad)
    out = bits.copy()
    out[mask] ^= 1
    return out, int(mask.sum())


def make_stream(n_source_bits: int = 20000, depth: int | None = 8, width: int | None = 12,
                polys=POLY_171_133, K: int = 7, scramble: bool = False,
                scrambler_poly: int = CCSDS_SCRAMBLER, ber: float = 0.0, seed: int = 0,
                mean_burst: float = 1.0, payload_text: str | None = None):
    """Build one coded stream and its truth. Returns (bits, Truth).

    `mean_burst` selects the error model: 1.0 keeps the independent flips that
    every number before 1 Sep was measured against; anything larger uses the
    Gilbert-Elliott channel, which is what a real receiver produces.
    """
    rng = np.random.default_rng(seed)
    if payload_text is None:
        src = rng.integers(0, 2, n_source_bits, dtype=np.uint8)
    else:
        # Real text, repeated to length. Random source bits prove the maths but
        # demonstrate nothing: "20000 bits matched 20000 bits" is a claim a
        # viewer has to take on trust, whereas a message appearing on screen
        # from a file the system was told nothing about is self-evident.
        raw = payload_text.encode("utf-8")
        reps = max(1, n_source_bits // (8 * len(raw)) + 1)
        src = np.unpackbits(np.frombuffer(raw * reps, dtype=np.uint8))[:n_source_bits]
    bits = conv_encode(src, polys=polys, K=K)

    period = None
    if depth and width:
        period = depth * width
        bits = block_interleave(bits, depth, width)

    if scramble:
        bits = lfsr_scramble(bits, scrambler_poly)

    if mean_burst > 1.0:
        bits, n_flipped = inject_burst_errors(bits, ber, mean_burst, rng)
    else:
        bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_source_bits, polys_octal=tuple(polys), K=K,
        depth=depth, width=width, period=period,
        scrambler_poly=scrambler_poly if scramble else None,
        injected_ber=ber, n_flipped=n_flipped, seed=seed,
        payload_text=payload_text, mean_burst=mean_burst,
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


# ---------------------------------------------------------------------------
# Reed-Solomon streams (2 Sep). Block code over GF(256), so it needs its own
# generator - conv_encode has nothing to do with it.
# ---------------------------------------------------------------------------

def make_rs_stream(n_blocks: int = 12, n: int = 255, k: int = 223,
                   ber: float = 0.0, seed: int = 0, mean_burst: float = 1.0,
                   payload_text: str | None = None, offset_bytes: int = 0):
    """RS(n, k) encoded stream and its truth. Returns (bits, Truth).

    `offset_bytes` prepends junk so the first block boundary is NOT at bit
    zero. Recovering the alignment is part of the problem; a fixture that
    always starts aligned tests an easier one.
    """
    import reedsolo

    rng = np.random.default_rng(seed)
    rs = reedsolo.RSCodec(n - k)

    if payload_text is None:
        payload = rng.integers(0, 256, n_blocks * k, dtype=np.uint8).tobytes()
    else:
        raw = payload_text.encode("utf-8")
        reps = n_blocks * k // len(raw) + 1
        payload = (raw * reps)[: n_blocks * k]

    encoded = bytearray()
    for b in range(n_blocks):
        encoded.extend(rs.encode(payload[b * k:(b + 1) * k]))

    if offset_bytes:
        encoded = bytearray(rng.integers(0, 256, offset_bytes,
                                         dtype=np.uint8).tobytes()) + encoded

    bits = np.unpackbits(np.frombuffer(bytes(encoded), dtype=np.uint8))

    if ber > 0 and mean_burst > 1.0:
        bits, n_flipped = inject_burst_errors(bits, ber, mean_burst, rng)
    else:
        bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_blocks * k * 8, polys_octal=(n, k), K=0,
        depth=None, width=None, period=n * 8, scrambler_poly=None,
        injected_ber=ber, n_flipped=n_flipped, seed=seed,
        payload_text=payload_text, mean_burst=mean_burst,
        start_trim=offset_bytes * 8,
    )
    return bits, truth, payload


# ---------------------------------------------------------------------------
# The concatenated CCSDS profile (5 Sep). Not in Dheeraj's corpus - his zoo
# generates conv-only and RS-only streams, so this is one of the three cases
# local_zoo is deliberately retained for.
# ---------------------------------------------------------------------------

def make_ccsds_stream(n_blocks: int = 4, depth: int = 8, width: int = 12,
                      polys=POLY_171_133, K: int = 7, n: int = 255, k: int = 223,
                      scramble: bool = False,
                      scrambler_poly: int = CCSDS_SCRAMBLER,
                      ber: float = 0.0, seed: int = 0,
                      payload_text: str | None = None):
    """RS outer -> interleave -> convolutional inner -> scramble.

    The transmit order the Command Center's 5 September row specifies. Note
    this is NOT bit-for-bit CCSDS 131.0-B, which randomises BEFORE the
    convolutional encoder and attaches an unrandomised sync marker; the
    difference matters for interoperating with a real spacecraft downlink and
    does not matter for what today is testing, which is whether four coding
    layers can be peeled off in sequence without being told any of them. The
    deviation is stated here so nobody quotes this as standards-compliant.

    Returns (bits, Truth, payload_bytes). `payload_bytes` is the RS-layer
    input, which is what a successful end-to-end decode must reproduce.
    """
    import reedsolo

    rng = np.random.default_rng(seed)
    rs = reedsolo.RSCodec(n - k)

    if payload_text is None:
        payload = rng.integers(0, 256, n_blocks * k, dtype=np.uint8).tobytes()
    else:
        raw = payload_text.encode("utf-8")
        payload = (raw * (n_blocks * k // len(raw) + 1))[: n_blocks * k]

    # 1. Reed-Solomon, the OUTER code
    encoded = bytearray()
    for b in range(n_blocks):
        encoded.extend(rs.encode(payload[b * k:(b + 1) * k]))
    bits = np.unpackbits(np.frombuffer(bytes(encoded), dtype=np.uint8))

    # 2. interleave, which is why the outer code survives Viterbi's burst errors
    period = None
    if depth and width:
        period = depth * width
        bits = block_interleave(bits, depth, width)

    # 3. convolutional, the INNER code
    bits = conv_encode(bits, polys=polys, K=K)

    # 4. the randomiser, outermost
    if scramble:
        bits = lfsr_scramble(bits, scrambler_poly)

    bits, n_flipped = inject_errors(bits, ber, rng)

    truth = Truth(
        n_source_bits=n_blocks * k * 8, polys_octal=tuple(polys), K=K,
        depth=depth, width=width, period=period,
        scrambler_poly=scrambler_poly if scramble else None,
        injected_ber=ber, n_flipped=n_flipped, seed=seed,
        payload_text=payload_text,
    )
    truth.rs_n, truth.rs_k, truth.n_blocks = n, k, n_blocks
    return bits, truth, bytes(payload)
