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

DTYPE IS PRESERVED, AND THAT IS NOT A DETAIL (found 4 Sep)
----------------------------------------------------------
Every function here used to begin `np.asarray(bits, dtype=np.uint8)`. A
permutation does not care what it is permuting, so that cast bought nothing -
and it silently destroyed every LLR handed to it. An LLR of -0.4 truncates to
0; a negative one wraps. De-interleaving a real receiver's soft output
returned an array of zeros, and the Viterbi decoder downstream dutifully
decoded zeros into zeros.

This is the same bug as the 3 Sep `harden` finding one stage further along.
That one was blind_recover assuming hard bits at its entry; this one is the
de-interleavers assuming them at their entry, and it went unnoticed because
every test until 4 Sep de-interleaved zoo BITS. The recovery path hard-slices
by design, so nothing upstream complained - it was only the DECODE path, which
needs the soft values, that quietly produced nothing.

It is why the readable-text demo had never once worked through the real
receiver: reports/end_to_end.md could recover the interleaver, the code and
both generators from a real capture and still print no message.

tests/contract/test_llr_contract.py already carried the rule - "an integer
dtype destroys the soft information" - and asserted it of S3's output. It was
never asserted of anything that consumes that output.
"""


from __future__ import annotations

import numpy as np

from registry import register_interleaver

__all__ = [
    "block_permutation", "block_interleave", "block_deinterleave", "BlockInterleaver",
    "diagonal_permutation", "diagonal_interleave", "diagonal_deinterleave",
    "DiagonalInterleaver",
    "conv_interleave", "conv_deinterleave", "ConvolutionalInterleaver",
    "symbol_interleave", "symbol_deinterleave", "CCSDSSymbolInterleaver",
    "MAX_PERIOD", "MAX_BRANCHES", "MAX_DELAY", "CCSDS_DEPTHS", "RS_SYMBOL_BITS",
]

MAX_PERIOD = 512     # largest block/diagonal period considered
MAX_BRANCHES = 32    # largest convolutional branch count
MAX_DELAY = 8        # largest convolutional delay increment

# CCSDS 131.0-B fixes the symbol interleaver's depth to I in {1,2,3,4,5,8}.
# It is a closed set in the standard, not a range we chose, so the search is
# six candidates rather than a grid - which is why this family is the cheap
# one to try first (see pipeline/s6_frame/ccsds.py).
CCSDS_DEPTHS = (1, 2, 3, 4, 5, 8)
RS_SYMBOL_BITS = 8   # an RS symbol over GF(2^8) is one byte


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
    bits = np.asarray(bits).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=bits.dtype)
    blocks = bits[: n_blocks * period].reshape(n_blocks, depth, width)
    return blocks.transpose(0, 2, 1).reshape(-1)


def block_deinterleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    bits = np.asarray(bits).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=bits.dtype)
    blocks = bits[: n_blocks * period].reshape(n_blocks, width, depth)
    return blocks.transpose(0, 2, 1).reshape(-1)


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
            # Depth 1 is the IDENTITY permutation - writing one row and
            # reading it back column-wise changes nothing - so offering it as
            # a candidate lets an un-interleaved stream come back as
            # "block(depth=1)". That is not a wrong permutation, it is the
            # direct reading wearing a hat, and on 4 Sep it carried a
            # scrambler composite around the K<=9 guard that only the direct
            # branch applied. "No interleaver" is the honest way to say this,
            # and blind_recover already has a route for it.
            for depth in range(2, per + 1):
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
    bits = np.asarray(bits).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=bits.dtype)
    perm = diagonal_permutation(depth, width)
    blocks = bits[: n_blocks * period].reshape(n_blocks, period)
    return blocks[:, perm].reshape(-1)


def diagonal_deinterleave(bits: np.ndarray, depth: int, width: int) -> np.ndarray:
    bits = np.asarray(bits).ravel()
    period = depth * width
    n_blocks = len(bits) // period
    if n_blocks == 0:
        return np.zeros(0, dtype=bits.dtype)
    inverse = np.argsort(diagonal_permutation(depth, width))
    blocks = bits[: n_blocks * period].reshape(n_blocks, period)
    return blocks[:, inverse].reshape(-1)


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
    bits = np.asarray(bits).ravel()
    k = np.arange(len(bits))
    src = k - (k % branches) * delay * branches
    out = np.zeros(len(bits), dtype=bits.dtype)
    ok = src >= 0
    out[ok] = bits[src[ok]]
    return out


def conv_deinterleave(bits: np.ndarray, branches: int, delay: int) -> np.ndarray:
    """The mirror: line j carries the complementary delay (branches-1-j)*delay.

    The result is offset by the constant end-to-end latency, so the first
    (branches-1)*delay*branches bits are fill and must be discarded before the
    stream means anything.
    """
    bits = np.asarray(bits).ravel()
    k = np.arange(len(bits))
    src = k - (branches - 1 - (k % branches)) * delay * branches
    out = np.zeros(len(bits), dtype=bits.dtype)
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


# ---------------------------------------------------------------------------
# CCSDS symbol (byte) interleaver
# ---------------------------------------------------------------------------

def symbol_interleave(bits: np.ndarray, depth: int, n_bytes: int = 255) -> np.ndarray:
    """CCSDS 131.0-B symbol interleaving, expressed on a bit stream.

    THIS IS NOT THE BLOCK INTERLEAVER WITH DIFFERENT NUMBERS, and the
    difference is the whole reason this family exists. `block_interleave`
    permutes individual BITS. CCSDS permutes SYMBOLS - bytes of a Reed-Solomon
    codeword - so the eight bits of a symbol always travel together and only
    their position moves. Take `depth` consecutive n-byte codewords as a
    (depth x n) matrix and transmit it column-wise: byte 0 of every codeword,
    then byte 1 of every codeword, and so on.

    Why the standard does it that way: a channel burst damages a run of
    CONSECUTIVE transmitted bytes, and column-wise transmission puts those
    consecutive bytes in `depth` DIFFERENT codewords. RS(255,223) corrects 16
    symbol errors per codeword, so spreading a 16*depth-byte burst over depth
    codewords is the difference between correctable and not.

    Trailing bytes that do not fill a whole depth x n group are dropped, the
    same convention every other family here uses.
    """
    data = _to_bytes(bits)
    group = depth * n_bytes
    n_groups = len(data) // group
    if n_groups == 0:
        return np.zeros(0, dtype=np.uint8)
    mat = data[: n_groups * group].reshape(n_groups, depth, n_bytes)
    return np.unpackbits(np.ascontiguousarray(mat.transpose(0, 2, 1)).ravel())


def symbol_deinterleave(bits: np.ndarray, depth: int, n_bytes: int = 255) -> np.ndarray:
    """Inverse of `symbol_interleave`: read the (n x depth) matrix back out.

    A receiver does not know `depth`, which is what makes this searchable
    rather than given - but CCSDS_DEPTHS has six members, so the search is six
    candidates and the Reed-Solomon decoder settles it (pipeline/s6_frame/
    ccsds.py). Note the rank test cannot help here at all: a permutation
    preserves rank over GF(2), and RS puts its binary-image constraints at
    L = 2040 anyway, far past MAX_PERIOD.
    """
    data = _to_bytes(bits)
    group = depth * n_bytes
    n_groups = len(data) // group
    if n_groups == 0:
        return np.zeros(0, dtype=np.uint8)
    mat = data[: n_groups * group].reshape(n_groups, n_bytes, depth)
    return np.unpackbits(np.ascontiguousarray(mat.transpose(0, 2, 1)).ravel())


def _to_bytes(bits: np.ndarray) -> np.ndarray:
    """Bit stream -> byte array, dropping a trailing partial byte.

    Packing a partial byte would zero-pad it on the right and invent a symbol
    that was never transmitted, which RS would then decline - a confusing way
    to fail. Dropping it is the same convention as the row/block trims above.
    """
    arr = np.asarray(bits, dtype=np.uint8).ravel()
    arr = arr[: len(arr) // RS_SYMBOL_BITS * RS_SYMBOL_BITS]
    return np.packbits(arr) if arr.size else np.zeros(0, dtype=np.uint8)


class CCSDSSymbolInterleaver:
    name = "ccsds-symbol"
    detail = ("CCSDS 131.0-B symbol (byte) interleaver, depth I in 1..8, "
              "settled by the Reed-Solomon decoder rather than by rank")

    @staticmethod
    def candidate_params(n_bits: int, n_bytes: int = 255, **_):
        """The standard's own depths, largest group first excluded by length.

        Depth 1 IS offered here, unlike the block family, and that is not an
        oversight: CCSDS I=1 is a legal profile meaning "no interleaving", and
        a receiver that cannot report it has to call a real I=1 downlink
        "no interleaver found" instead of "interleaved at depth 1".
        """
        for depth in CCSDS_DEPTHS:
            if n_bits >= depth * n_bytes * RS_SYMBOL_BITS:
                yield {"depth": depth, "n_bytes": n_bytes}

    @staticmethod
    def deinterleave(bits, depth: int, n_bytes: int = 255):
        return symbol_deinterleave(bits, depth, n_bytes)

    @staticmethod
    def rank_signature(depth: int, n_bytes: int = 255) -> int:
        """There is no rank signature, and returning a number here would be a
        lie the orchestrator would act on. A permutation preserves rank over
        GF(2) and RS's constraints sit at 2040 bits, so no row length in the
        searched range collapses. 0 means "the sweep will not find this - use
        the functional test", and `blind_recover` treats it that way."""
        return 0


# One registration line per family - the whole point of the registry. The
# orchestrator iterates INTERLEAVERS and never names a scheme.
register_interleaver(BlockInterleaver())
register_interleaver(DiagonalInterleaver())
register_interleaver(ConvolutionalInterleaver())
register_interleaver(CCSDSSymbolInterleaver())
