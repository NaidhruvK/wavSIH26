"""Interleaver plug-ins for Stage 4.

Each family exposes the same three things, which is what lets the orchestrator
sweep the registry without ever naming a scheme:

    candidate_params(n_bits)  -> iterable of parameter dicts to try
    deinterleave(bits, **p)   -> bits
    rank_signature(**p)       -> the row length at which a rank collapse is
                                 expected if these parameters are right

Three families are implemented: block, diagonal (helical) and convolutional
(Forney). Pseudo-random via Berlekamp-Massey lands 7 Sep.

WHAT THE RANK PROFILE CAN AND CANNOT TELL YOU, measured 1 Sep:

    block 8x12        deficient at L = 96, 192, 288    step 96, first 96
    diagonal 8x12     deficient at L = 96, 192         step 96, first 96
    convolutional     deficient at L = 20, 24, 28...   step 4,  first 20
      N=4 M=1

Block and diagonal are INDISTINGUISHABLE by rank profile - identical positions
and identical deficiency values. Only de-interleaving with each and asking
whether the code comes back can separate them, which is why every family gets
tried functionally rather than guessed at.

Convolutional is different and usefully so: its deficiency repeats every N
bits (the branch count) starting well above N, whereas a block-like
interleaver first collapses exactly at its period. So `step < first` means
convolutional and `step == first` means block-like. That comparison costs
nothing and it bounds the search before it starts.
"""

from __future__ import annotations

import numpy as np

from registry import register_interleaver

__all__ = [
    "block_permutation", "block_interleave", "block_deinterleave", "BlockInterleaver",
    "diagonal_permutation", "diagonal_interleave", "diagonal_deinterleave",
    "DiagonalInterleaver",
    "conv_interleave", "conv_deinterleave", "ConvolutionalInterleaver",
    "MAX_PERIOD", "MAX_BRANCHES", "MAX_DELAY",
]

MAX_PERIOD = 512     # largest block/diagonal period considered
MAX_BRANCHES = 32    # largest convolutional branch count
MAX_DELAY = 8        # largest convolutional delay increment


def block_permutation(depth: int, width: int) -> np.ndarray:
    """Output index -> input index, for one block of depth*width bits.

    Written row-wise into a depth x width array, read out column-wise. Input
    index k lands at (row=k//width, col=k%width); output index p reads
    (col=p//depth, row=p%depth). So p carries input (p % depth)*width + p//depth.
    """
    p = np.arange(depth * width)
    return (p % depth) * width + (p // depth)


def block_interleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    """Block-interleave, discarding any trailing partial block."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=np.uint8)
    blocks = bits[: n_blocks * period].reshape(n_blocks, depth, width)
    return blocks.transpose(0, 2, 1).reshape(-1).astype(np.uint8)


def block_deinterleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=np.uint8)
    blocks = bits[: n_blocks * period].reshape(n_blocks, width, depth)
    return blocks.transpose(0, 2, 1).reshape(-1).astype(np.uint8)


class BlockInterleaver:
    name = "block"
    detail = "block interleaver, depth x width, recovered by rank signature"

    @staticmethod
    def candidate_params(n_bits: int, period: int | None = None,
                         max_period: int = MAX_PERIOD):
        """Every (depth, width) whose period we could still see in this stream.

        Pass `period` when the rank profile already gave it - then only its
        factorisations are offered, which is a dozen candidates instead of tens
        of thousands. Bounded either way: the registry product is the
        sweep-explosion risk (#5), so every dimension has a cap from day one.
        """
        periods = ([period] if period else
                   range(8, min(max_period, max(8, n_bits // 4)) + 1))
        for per in periods:
            if per < 2 or per > max_period:
                continue
            for depth in range(1, per + 1):
                if per % depth == 0:
                    yield {"depth": depth, "width": per // depth}

    @staticmethod
    def deinterleave(bits, depth: int, width: int):
        return block_deinterleave(bits, depth, width)

    @staticmethod
    def rank_signature(depth: int, width: int) -> int:
        return depth * width


# ---------------------------------------------------------------------------
# diagonal (helical)
# ---------------------------------------------------------------------------

def diagonal_permutation(depth: int, width: int) -> np.ndarray:
    """Output index -> input index for one depth*width block, read diagonally.

    Written row-wise as for a block interleaver, but read along diagonals: the
    s-th diagonal takes one element from every row, stepping the column by the
    row index. Output p = s*depth + i reads (row=i, col=(i+s) mod width).

    The modular column wrap is what makes it a bijection - each row contributes
    every column exactly once across the width diagonals.
    """
    perm = np.empty(depth * width, dtype=np.int64)
    for s in range(width):
        for i in range(depth):
            perm[s * depth + i] = i * width + ((i + s) % width)
    return perm


def diagonal_interleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=np.uint8)
    perm = diagonal_permutation(depth, width)
    blocks = bits[: n_blocks * period].reshape(n_blocks, period)
    return blocks[:, perm].reshape(-1).astype(np.uint8)


def diagonal_deinterleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=np.uint8)
    inverse = np.argsort(diagonal_permutation(depth, width))
    blocks = bits[: n_blocks * period].reshape(n_blocks, period)
    return blocks[:, inverse].reshape(-1).astype(np.uint8)


class DiagonalInterleaver:
    name = "diagonal"
    detail = "helical/diagonal read of a depth x width block"

    @staticmethod
    def candidate_params(n_bits: int, period: int | None = None,
                         max_period: int = MAX_PERIOD):
        """Same parameter space as block - the rank profile cannot tell them
        apart, so both families get offered the same periods and the functional
        test decides."""
        periods = ([period] if period else
                   range(8, min(max_period, max(8, n_bits // 4)) + 1))
        for per in periods:
            if per > max_period:
                continue
            for depth in range(2, per + 1):
                if per % depth == 0:
                    yield {"depth": depth, "width": per // depth}

    @staticmethod
    def deinterleave(bits, depth: int, width: int):
        return diagonal_deinterleave(bits, depth, width)

    @staticmethod
    def rank_signature(depth: int, width: int) -> int:
        return depth * width


# ---------------------------------------------------------------------------
# convolutional (Forney)
# ---------------------------------------------------------------------------

def conv_interleave(bits: np.ndarray, branches: int, delay: int) -> np.ndarray:
    """Forney convolutional interleaver: `branches` lines, line j delayed by
    j*delay symbols.

    Input is fed round-robin, so line j is visited once every `branches` ticks
    and therefore holds its symbols for j*delay*branches ticks. Unlike block
    and diagonal this has no block boundary at all - it is a continuous
    permutation with a fixed end-to-end latency of (branches-1)*delay*branches.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    k = np.arange(len(bits))
    src = k - (k % branches) * delay * branches
    out = np.zeros(len(bits), dtype=np.uint8)
    ok = src >= 0
    out[ok] = bits[src[ok]]
    return out


def conv_deinterleave(bits: np.ndarray, branches: int, delay: int) -> np.ndarray:
    """The mirror: line j carries the complementary delay (branches-1-j)*delay.

    The result is offset by the constant end-to-end latency, so the first
    (branches-1)*delay*branches bits are fill and must be discarded before the
    stream means anything.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    k = np.arange(len(bits))
    src = k - (branches - 1 - (k % branches)) * delay * branches
    out = np.zeros(len(bits), dtype=np.uint8)
    ok = src >= 0
    out[ok] = bits[src[ok]]
    return out


def conv_latency(branches: int, delay: int) -> int:
    return (branches - 1) * delay * branches


class ConvolutionalInterleaver:
    name = "convolutional"
    detail = "Forney convolutional interleaver, branches x delay"

    @staticmethod
    def candidate_params(n_bits: int, branches: int | None = None,
                         max_branches: int = MAX_BRANCHES,
                         max_delay: int = MAX_DELAY):
        """`branches` comes free from the profile: the deficiency of a
        convolutionally interleaved stream repeats every `branches` bits, so
        the step between deficient row lengths IS the branch count. Given that,
        only the delay is actually unknown, and it is swept over a small
        bounded range."""
        branch_list = ([branches] if branches else range(2, max_branches + 1))
        for n in branch_list:
            if n < 2 or n > max_branches:
                continue
            for m in range(1, max_delay + 1):
                if conv_latency(n, m) * 4 < n_bits:
                    yield {"branches": n, "delay": m}

    @staticmethod
    def deinterleave(bits, branches: int, delay: int):
        out = conv_deinterleave(bits, branches, delay)
        # drop the fill produced by the constant end-to-end latency
        return out[conv_latency(branches, delay):]

    @staticmethod
    def rank_signature(branches: int, delay: int) -> int:
        """The repeat period of the deficiency, which is the branch count -
        NOT the first row length at which a collapse appears."""
        return branches


# One registration line per family - the whole point of the registry. The
# orchestrator iterates INTERLEAVERS and never names a scheme.
register_interleaver(BlockInterleaver())
register_interleaver(DiagonalInterleaver())
register_interleaver(ConvolutionalInterleaver())
