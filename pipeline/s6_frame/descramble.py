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
]

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
