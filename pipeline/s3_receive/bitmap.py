"""Symbol-to-bit labelling. A cross-stream contract, not an internal detail.

The zoo encodes bits onto symbols and S3 decodes symbols back to bits. If the
two disagree about which bit pattern sits on which constellation point, every
stage downstream still runs, every test inside each stream still passes, and
the payload comes out as noise. Nothing raises. So the mapping is written down
here, in one place, and both sides are expected to read it.

**The rule.** Constellation points are indexed by position - by increasing
angle for PSK, by (I, Q) level for QAM. The bit label of point `k` is the Gray
code of `k`, most significant bit first:

    label[k] = k XOR (k >> 1)

Gray labelling means the nearest wrong decision costs one bit rather than
several, which is worth roughly a decibel to any downstream decoder and costs
nothing to implement. For QAM the rule is applied to each axis independently,
which is what makes a square QAM constellation Gray at all.

**Bit order within a symbol is MSB first**, and symbols concatenate in
transmission order, so a QPSK stream reads b0 b1 b0 b1 ... That is the order
S4 and S5 expect, because it is the order the encoder emitted.

Dheeraj: when the zoo grows a modulator, import `bits_to_symbol_indices` from
here rather than writing the mapping a second time. Two implementations of one
convention is the bug this file exists to prevent.
"""
from __future__ import annotations

import numpy as np

__all__ = ["gray", "gray_inverse", "bits_per_symbol", "symbol_labels",
           "label_bit_matrix", "bits_to_symbol_indices",
           "symbol_indices_to_bits", "qam16_constellation"]


def gray(k: int | np.ndarray) -> int | np.ndarray:
    return k ^ (k >> 1)


def gray_inverse(g: np.ndarray) -> np.ndarray:
    """Undo the Gray code. Only a handful of bits, so the shift-and-xor ladder
    is clearer than anything cleverer."""
    g = np.asarray(g, dtype=np.int64)
    out = g.copy()
    shift = 1
    while shift < 64:
        out ^= out >> shift
        shift <<= 1
    return out


def bits_per_symbol(order: int) -> int:
    # 9 Sep, guard pass. The power-of-two check below could not see order 0:
    # `(0).bit_length() - 1` is -1, and `1 << -1` raises
    # `ValueError: negative shift count` from inside the check itself, one
    # line before the message that would have said what was wrong. Same class
    # as a check that cannot see - it did raise, but about the arithmetic
    # rather than about the input. Every valid order is unaffected, and an
    # invalid one still raises ValueError; only the message changes.
    if int(order) < 1:
        raise ValueError(f"constellation order {order} is not a power of two")
    b = int(order).bit_length() - 1
    if 1 << b != int(order):
        raise ValueError(f"constellation order {order} is not a power of two")
    return b


def symbol_labels(order: int) -> np.ndarray:
    """label[k] - the integer bit pattern carried by constellation point k.

    For QAM the axes are Gray-coded separately and then packed I-high, Q-low;
    applying a single Gray code to the raster index would not give a Gray
    constellation at all, which is the mistake worth guarding against.
    """
    if order == 16:
        axis = gray(np.arange(4))
        lab = np.empty(16, dtype=np.int64)
        for i in range(4):
            for q in range(4):
                lab[i * 4 + q] = (axis[i] << 2) | axis[q]
        return lab
    return gray(np.arange(order, dtype=np.int64))


def label_bit_matrix(order: int) -> np.ndarray:
    """(M, bits) uint8 matrix: row k is point k's label, MSB first."""
    b = bits_per_symbol(order)
    lab = symbol_labels(order)
    shifts = np.arange(b - 1, -1, -1)
    return ((lab[:, None] >> shifts[None, :]) & 1).astype(np.uint8)


def bits_to_symbol_indices(bits: np.ndarray, order: int) -> np.ndarray:
    """Pack a bitstream into constellation point indices, MSB first.

    Trailing bits that do not fill a whole symbol are dropped rather than
    zero-padded: padding invents data, and the caller can always see the
    length it got back.
    """
    b = bits_per_symbol(order)
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    n = (bits.size // b) * b
    packed = bits[:n].reshape(-1, b)
    weights = (1 << np.arange(b - 1, -1, -1)).astype(np.int64)
    values = packed.astype(np.int64) @ weights
    # value is the LABEL; the point index is its inverse Gray code
    if order == 16:
        lab = symbol_labels(16)
        lookup = np.empty(16, dtype=np.int64)
        lookup[lab] = np.arange(16)
        return lookup[values]
    return gray_inverse(values)


def symbol_indices_to_bits(idx: np.ndarray, order: int) -> np.ndarray:
    mat = label_bit_matrix(order)
    return mat[np.asarray(idx, dtype=np.int64)].ravel()


def qam16_constellation() -> np.ndarray:
    """Unit-power square 16-QAM, raster-ordered I-major to match symbol_labels."""
    levels = np.array([-3.0, -1.0, 1.0, 3.0])
    pts = np.array([complex(i, q) for i in levels for q in levels])
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))
