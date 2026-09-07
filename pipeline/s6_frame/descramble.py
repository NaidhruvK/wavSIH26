"""S6: blind recovery of an additive scrambler, and descrambling.

The problem. A CCSDS-style transmitter scrambles last, so the receiver sees
r = c XOR s where c is the coded stream and s is a pseudo-random LFSR
sequence. Viterbi cannot decode r, and s is never transmitted.

The method, in three steps, none of which needs a dictionary of known
polynomials:

1. THE SYNDROME IS THE SCRAMBLER, SEEN THROUGH THE CODE.
   The recovered parity check h annihilates any codeword, so

       h . r  =  h . (c XOR s)  =  h . c  XOR  h . s  =  h . s

   The scrambler is not observable, but a linear functional of it is. And a
   linear functional of an LFSR sequence obeys the SAME recurrence, so
   Berlekamp-Massey on the syndrome returns the scrambler's degree without
   ever seeing the scrambler.

2. THE PERIOD FALLS OUT OF A SHIFT TEST.
   s repeats with period P, so r[k] XOR r[k+P] = c[k] XOR c[k+P], and the sum
   of two codewords is a codeword. So the correct shift is the one whose
   difference has an exactly zero syndrome. One subtlety that cost a wrong
   answer first time: the shift must also be a multiple of n, or the two
   codewords are not phase-aligned and their sum is not a codeword. For a
   period-255 scrambler on a rate-1/2 code the answer is lcm(255, 2) = 510,
   not 255.

3. THE SEQUENCE ITSELF NEEDS BOTH FACTS.
   Solving h.s = h.r directly for a P-periodic s is under-determined - 510
   unknowns, rank 255, an ambiguity of 2^255 - because any s XOR codeword is
   also a solution. What removes it is that s is not an arbitrary periodic
   sequence: it lives in the degree-d subspace of LFSR sequences. Enumerating
   candidate polynomials of the recovered degree and matching each against the
   observed syndrome pins it down in a few thousand cheap comparisons.

Everything here is bounded by degree, which comes from step 1 rather than from
a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "berlekamp_massey",
    "lfsr_sequence",
    "ScramblerHypothesis",
    "find_scrambler_period",
    "recover_scrambler",
    "descramble",
    "additive_keystream",
    "descramble_known",
    "CCSDS_RANDOMISER",
    "STANDARD_RANDOMISERS",
]

# ---------------------------------------------------------------------------
# Known randomisers of the declared envelope.
#
# WHY A TABLE OF KNOWN POLYNOMIALS EXISTS ALONGSIDE THE BLIND SEARCH ABOVE,
# because it looks like a contradiction and is not. The blind method needs the
# code's parity check, and it gets it because the scrambler in this project's
# own ordering sits OUTSIDE the convolutional code, where a parity check can
# still be recovered from the self-difference. In the real CCSDS 131.0-B
# transmit order the randomiser sits INSIDE - between the interleaver and the
# convolutional encoder - so by the time Viterbi has run there is no local
# linear code left to take a syndrome against. RS(255,223) puts its constraints
# at 2040 bits, an order of magnitude past anything the sweep reaches.
#
# So for that layer the honest move is the one `rs_code.STANDARD_PROFILES`
# already makes for Reed-Solomon: try the PUBLISHED profiles of the declared
# envelope, and let a downstream decoder be the judge. A published constant
# from a blue book is not truth leaked from the corpus - nothing here reads a
# truth JSON, and a stream that is not one of these is declined, not guessed.
CCSDS_RANDOMISER = 0o651
"""The real CCSDS 131.0-B pseudo-randomiser: h(x) = x^8 + x^7 + x^5 + x^3 + 1.

    0o651 = 425 = 0x1A9 = 0b1_1010_1001   ->  bits 8,7,5,3,0

CHECKED AGAINST THE BLUE BOOK, NOT AGAINST OUR OWN CORPUS, and they disagree.
`zoo.bits_only.CCSDS_SCRAMBLER` is `0o435` under a docstring that names this
exact polynomial, but 0o435 = 285 = 0x11D = x^8 + x^4 + x^3 + x^2 + 1 - which
is the GF(256) field polynomial of Reed-Solomon, not the randomiser. No reading
reconciles them; the reciprocal of 0o435 is 0o561, still not 0o651.

It is a mislabel and not a malfunction: both polynomials are primitive of
degree 8, so both give a period-255 additive scrambler, the corpus is
self-consistent, and every recovery number measured against it stands. What it
would have broken is the only thing this table exists for - a REAL downlink.
A "known standard profiles" table whose standard entry is not the standard
declines the one stream it was written to catch.

So both are listed. The blue book's goes first because it is the one a real
capture will carry; ours follows so the corpus keeps working. The cost of the
extra hypothesis is one screened pass on the failure path.
"""

CORPUS_RANDOMISER = 0o435
"""What `zoo.bits_only` actually applies - x^8 + x^4 + x^3 + x^2 + 1. See above."""

STANDARD_RANDOMISERS = [
    ("ccsds-131.0-B", CCSDS_RANDOMISER, 0xFF),
    ("zoo-corpus-0o435", CORPUS_RANDOMISER, 0xFF),
]
"""(name, polynomial, initial state). Tried in order, after "no randomiser"."""

MAX_DEGREE = 12          # brute force is 2^(d-1) polynomials; 12 -> 2048
MAX_SHIFT = 4096         # cap on the period search
MATCH_BITS = 64          # syndrome bits compared per candidate
SYNDROME_SAMPLE = 20_000  # windows used for validation


def berlekamp_massey(seq) -> tuple[int, list[int]]:
    """Shortest LFSR generating `seq` over GF(2): (degree, connection taps)."""
    seq = [int(b) & 1 for b in seq]
    n = len(seq)
    c = [1] + [0] * n
    b = [1] + [0] * n
    L, m = 0, -1
    for i in range(n):
        d = seq[i]
        for j in range(1, L + 1):
            d ^= c[j] & seq[i - j]
        if d:
            t = c[:]
            shift = i - m
            for j in range(n - shift):
                if b[j]:
                    c[j + shift] ^= 1
            if 2 * L <= i:
                L, m, b = i + 1 - L, i, t
    return L, c[: L + 1]


def lfsr_sequence(taps: list[int], state: int, n: int, degree: int) -> np.ndarray:
    """Generate n bits from the recurrence s[k] = sum taps[j] s[k-j].

    `taps` is the connection polynomial as returned by berlekamp_massey, with
    taps[0] == 1 by construction.
    """
    out = np.zeros(n, dtype=np.uint8)
    hist = [(state >> i) & 1 for i in range(degree)]     # hist[0] is most recent
    tap_idx = [j for j in range(1, degree + 1) if j < len(taps) and taps[j]]
    for k in range(n):
        out[k] = hist[0]
        nxt = 0
        for j in tap_idx:
            nxt ^= hist[j - 1]
        hist = [nxt] + hist[:-1]
    return out


@dataclass
class ScramblerHypothesis:
    degree: int
    period: int | None
    taps: list[int]
    state: int
    syndrome_violations: float     # fraction, after descrambling
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.syndrome_violations == 0.0

    def describe(self) -> str:
        return ("scrambler degree %d, period %s, residual syndrome %.4f"
                % (self.degree, self.period, self.syndrome_violations))


def _syndrome(bits: np.ndarray, parity_taps: np.ndarray, stride: int, phase: int):
    windows = np.lib.stride_tricks.sliding_window_view(bits, len(parity_taps))
    windows = windows[phase::stride]
    return (windows @ parity_taps) % 2


def find_scrambler_period(bits: np.ndarray, parity_taps: np.ndarray,
                          stride: int = 2, phase: int = 0,
                          max_shift: int = MAX_SHIFT) -> int | None:
    """Smallest shift whose self-difference has an exactly zero syndrome.

    Only multiples of `stride` are tried: a shift that is not a whole number of
    code symbols leaves the two codewords out of phase, and their sum is not a
    codeword. Getting that wrong makes the true period look like a non-answer.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    limit = min(max_shift, len(bits) // 3)
    for shift in range(stride, limit + 1, stride):
        diff = bits[:-shift] ^ bits[shift:]
        if len(diff) < len(parity_taps) * 4:
            break
        if _syndrome(diff[:SYNDROME_SAMPLE], parity_taps, stride, phase).mean() == 0.0:
            return shift
    return None


def recover_scrambler(bits: np.ndarray, parity_taps, stride: int = 2,
                      phase: int = 0, max_degree: int = MAX_DEGREE
                      ) -> ScramblerHypothesis | None:
    """Recover an additive scrambler blind. None means no scrambling detected."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    h = np.asarray(parity_taps, dtype=np.uint8).ravel()

    syn = _syndrome(bits, h, stride, phase)
    if syn.size == 0:
        return None
    if syn.mean() == 0.0:
        return None                      # already clean - nothing to undo

    degree, _ = berlekamp_massey(syn[: 8 * max_degree].tolist())
    if degree == 0 or degree > max_degree:
        return ScramblerHypothesis(degree, None, [], 0, float(syn.mean()),
                                   "degree %d outside the searched range 1..%d"
                                   % (degree, max_degree))

    period = find_scrambler_period(bits, h, stride, phase)
    target = syn[:MATCH_BITS]
    n_needed = stride * MATCH_BITS + len(h) + degree

    # Enumerate connection polynomials of exactly this degree (taps[0] and
    # taps[degree] are 1 by definition), and for each, every non-zero state.
    # Bounded by 2^(2d-1); the degree came from Berlekamp-Massey, not a guess.
    for middle in range(1 << max(0, degree - 1)):
        taps = [1] + [(middle >> i) & 1 for i in range(degree - 1)] + [1]
        for state in range(1, 1 << degree):
            s = lfsr_sequence(taps, state, n_needed, degree)
            cand = _syndrome(s, h, stride, phase)[:MATCH_BITS]
            if cand.size == target.size and np.array_equal(cand, target):
                full = lfsr_sequence(taps, state, len(bits), degree)
                residual = _syndrome(bits ^ full, h, stride, phase).mean()
                if residual == 0.0:
                    return ScramblerHypothesis(degree, period, taps, state, 0.0)
    return ScramblerHypothesis(degree, period, [], 0, float(syn.mean()),
                               "degree %d recovered but no polynomial and state "
                               "reproduced the observed syndrome" % degree)


def descramble(bits: np.ndarray, hypothesis: ScramblerHypothesis) -> np.ndarray:
    """Undo the scrambler described by a recovered hypothesis."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    if not hypothesis or not hypothesis.taps:
        return bits.copy()
    seq = lfsr_sequence(hypothesis.taps, hypothesis.state, len(bits), hypothesis.degree)
    return (bits ^ seq).astype(np.uint8)


def additive_keystream(poly: int = CCSDS_RANDOMISER, seed_state: int = 0xFF,
                       n: int = 0) -> np.ndarray:
    """The XOR sequence of an additive scrambler, as 0/1 bits.

    Fibonacci LFSR shifted toward the LSB, output tapped at the LSB - the
    convention `zoo.bits_only.lfsr_scramble` uses to BUILD the corpus. Two
    implementations of one scrambler is the same class of bug as two
    implementations of one bit mapping, so this one is pinned against that one
    by tests/unit/test_ccsds_real_order.py rather than trusted for reading
    the same way.

    The sequence is periodic, so one period is generated and tiled. That is a
    speed decision - 255 steps instead of tens of thousands - but the period is
    MEASURED here by running until the state repeats, not assumed from the
    polynomial's degree. A polynomial that is not primitive has a shorter
    period, and assuming 2^d - 1 for one of those would silently emit the wrong
    keystream after the first cycle.
    """
    if n <= 0:
        return np.zeros(0, dtype=np.uint8)
    deg = poly.bit_length() - 1
    if deg <= 0:
        raise ValueError("polynomial must have degree >= 1")
    taps = poly & ((1 << deg) - 1)
    start = (seed_state & ((1 << deg) - 1)) or 1

    period_bits: list[int] = []
    state = start
    for _ in range(1 << deg):          # bounded: the state space itself
        period_bits.append(state & 1)
        fb = bin(state & taps).count("1") & 1
        state = (state >> 1) | (fb << (deg - 1))
        if state == start:
            break
    seq = np.array(period_bits, dtype=np.uint8)
    if len(seq) >= n:
        return seq[:n]
    return np.tile(seq, n // len(seq) + 1)[:n]


def descramble_known(bits: np.ndarray, poly: int = CCSDS_RANDOMISER,
                     seed_state: int = 0xFF) -> np.ndarray:
    """XOR out a known additive randomiser, starting at bit 0 of `bits`.

    PHASE 0 IS ASSUMED, and that is a real limit worth stating rather than
    discovering. The randomiser's period is 255 bits, which is coprime with
    both the 8-bit symbol and the rate-1/2 code, so a receiver whose stream
    does not begin on the randomiser's first bit gets a keystream in the wrong
    phase and nothing downstream decodes. That holds here because the
    convolutional encoder starts on the randomiser's bit 0, so Viterbi's output
    does too. A capture that starts mid-frame needs a phase search this
    function does not do - that is frame synchronisation, and it belongs with
    the sync-marker work, not here.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    return (bits ^ additive_keystream(poly, seed_state, len(bits))).astype(np.uint8)
