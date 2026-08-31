"""Interleaver plug-ins for Stage 4.

Each family exposes the same three things, which is what lets the orchestrator
sweep the registry without ever naming a scheme:

    candidate_params(n_bits)  -> iterable of parameter dicts to try
    deinterleave(bits, **p)   -> bits
    rank_signature(**p)       -> the row length at which a rank collapse is
                                 expected if these parameters are right

Only the block family is implemented today. Diagonal and convolutional land on
1 Sep, pseudo-random (via Berlekamp-Massey) on 7 Sep.
"""

from __future__ import annotations

import numpy as np

from registry import register_interleaver

__all__ = ["block_interleave", "block_deinterleave", "block_permutation", "BlockInterleaver"]


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
    def candidate_params(n_bits: int, max_period: int = 512):
        """Every (depth, width) whose period we could still see in this stream.

        Bounded on purpose: the registry product is the sweep-explosion risk
        (#5 in the register), so every dimension has a cap from day one.
        """
        for period in range(8, min(max_period, n_bits // 4) + 1):
            for depth in range(2, period + 1):
                if period % depth == 0:
                    yield {"depth": depth, "width": period // depth}

    @staticmethod
    def deinterleave(bits, depth: int, width: int):
        return block_deinterleave(bits, depth, width)

    @staticmethod
    def rank_signature(depth: int, width: int) -> int:
        return depth * width


# One registration line - the whole point of the registry. The orchestrator
# iterates INTERLEAVERS and never names a scheme, so adding the diagonal and
# convolutional families on 1 Sep is a new class and one more line here.
register_interleaver(BlockInterleaver())
