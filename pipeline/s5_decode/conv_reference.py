"""Reference rate-1/n convolutional encoder.

This is NOT the decoder. Decoding uses an established soft-input Viterbi
library - we do not write our own. This encoder exists for two reasons:

  1. It generates known-truth coded streams for the Stage 4 rank spike before
     Dheeraj's zoo lands.
  2. It is the round-trip partner that will prove the Viterbi decoder correct
     on 2 Sep: encode(bits) -> decode() must return `bits` exactly at 0% BER.

Default is the NASA/Voyager rate-1/2 K=7 code, generators (171, 133) octal.
Polynomials are given in the conventional octal form, MSB = the current input
bit. 0o171 = 0b1111001, 0o133 = 0b1011011.
"""

from __future__ import annotations

import numpy as np

__all__ = ["POLY_171_133", "poly_to_taps", "taps_to_poly", "conv_encode",
           "parity_check_taps"]

POLY_171_133 = (0o171, 0o133)


def poly_to_taps(poly: int, K: int) -> np.ndarray:
    """Octal generator -> length-K tap vector, taps[0] multiplying the newest bit.

    LSB-FIRST, and this is not a free choice. The standard reading of a
    generator written in octal is g(D) = g0 + g1*D + ... + g(K-1)*D^(K-1) with
    the octal's most significant bit carrying the HIGHEST power. So g0 - the
    coefficient multiplying the current input bit - is the octal's LSB.

    Verified against commpy's Trellis for (171, 133): with this ordering the
    two encoders agree bit for bit; with the reverse they do not. The reversed
    convention is self-consistent - encode and blind-recover round-trip
    perfectly inside our own code - so nothing here catches it. What catches it
    is comparing against an independent implementation, which is why that
    comparison is a test and not a one-off.

    Getting this backwards would have had S4 report the generators of a real
    CCSDS downlink reversed: 0o117 and 0o155 instead of 0o171 and 0o133.
    """
    return np.array([(poly >> i) & 1 for i in range(K)], dtype=np.uint8)


def taps_to_poly(taps) -> int:
    """Inverse of poly_to_taps. taps[0] (newest bit) is the octal's LSB."""
    return int(sum(int(t) << i for i, t in enumerate(taps)))


def conv_encode(bits: np.ndarray, polys=POLY_171_133, K: int = 7,
                flush: bool = True) -> np.ndarray:
    """Encode a bit vector. Output is interleaved across the n generators.

    For rate 1/2 the output is g0[0], g1[0], g0[1], g1[1], ... - which is what
    a real modulator would be handed, and therefore what Stage 4 has to
    recognise. `flush` appends K-1 zeros so the register returns to state 0.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    if flush:
        bits = np.concatenate([bits, np.zeros(K - 1, dtype=np.uint8)])

    streams = []
    for poly in polys:
        taps = poly_to_taps(poly, K)
        # np.convolve(a, t)[i] == sum_j a[i-j] t[j], i.e. taps[0] hits the
        # newest input bit - exactly the shift-register convention above.
        streams.append((np.convolve(bits, taps)[: len(bits)] % 2).astype(np.uint8))

    return np.stack(streams, axis=1).ravel()


def parity_check_taps(polys=POLY_171_133, K: int = 7) -> np.ndarray:
    """The dual of a rate-1/2 code, as a tap pattern on the interleaved stream.

    For G(D) = [g0(D) g1(D)] the parity check is H(D) = [g1(D) g0(D)], because
    c0*g1 + c1*g0 = u*g0*g1 + u*g1*g0 = 0 over GF(2).

    Carrying that onto the interleaved stream s (s[2t]=c0_t, s[2t+1]=c1_t) is
    where the bit order bites. The constraint is

        sum_i g1_i*s[2(t-i)] + sum_i g0_i*s[2(t-i)+1] = 0

    so inside a window of 2K bits starting at 2t-2K+2, even slot a carries
    g1_{K-1-a} and odd slot a carries g0_{K-1-a}: both tap vectors go in
    REVERSED. This is risk #10 in the register (octal vs binary, bit order),
    and getting it backwards produces a check that fails on ~50% of windows -
    i.e. looks exactly like noise rather than like a bug.

    The constraint holds only on EVEN offsets. Odd-offset windows straddle the
    n=2 phase and fail, which is itself the signal S4 uses to find n.
    """
    if len(polys) != 2:
        raise ValueError("parity_check_taps is only defined for rate 1/2")
    t0 = poly_to_taps(polys[0], K)
    t1 = poly_to_taps(polys[1], K)
    return np.stack([t1[::-1], t0[::-1]], axis=1).ravel()
