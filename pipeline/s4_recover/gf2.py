"""GF(2) linear algebra for Stage 4.

Two implementations of rank, deliberately:

`rank_gf2` packs each row into a Python int and runs Gaussian elimination with
XOR. It is the one the sweep calls, because the sweep evaluates a few hundred
candidate row lengths per file and needs to be fast.

`rank_gf2_galois` is the reference. It goes through `galois` and
`np.linalg.matrix_rank`, is far slower, and exists so that
tests/unit/test_gf2.py can assert the fast path agrees with it on random
matrices of known rank. Never optimise the reference.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "rows_to_ints",
    "rank_gf2",
    "rank_gf2_galois",
    "null_space_gf2",
    "reshape_rows",
]


def reshape_rows(bits: np.ndarray, row_len: int, offset: int = 0,
                 max_rows: int | None = None) -> np.ndarray:
    """Chop a bitstream into non-overlapping rows of `row_len` bits.

    Trailing bits that do not fill a whole row are discarded. `offset` slides
    the start of the first row, which is how we search for the alignment of an
    interleaver block boundary we do not know.
    """
    if row_len <= 0:
        raise ValueError("row_len must be positive")
    tail = bits[offset:]
    n_rows = len(tail) // row_len
    if max_rows is not None:
        n_rows = min(n_rows, max_rows)
    if n_rows == 0:
        return np.zeros((0, row_len), dtype=np.uint8)
    return tail[: n_rows * row_len].reshape(n_rows, row_len).astype(np.uint8)


def rows_to_ints(matrix: np.ndarray) -> list[int]:
    """Pack each row of a 0/1 matrix into a Python int, column 0 in the MSB.

    np.packbits zero-pads the final byte on the right, which multiplies every
    row by the same power of two. Rank is unchanged by that, so we do not
    bother to shift it back out.
    """
    if matrix.size == 0:
        return []
    packed = np.packbits(np.ascontiguousarray(matrix, dtype=np.uint8), axis=1)
    return [int.from_bytes(row.tobytes(), "big") for row in packed]


def rank_gf2(matrix, max_rank: int | None = None) -> int:
    """Rank over GF(2) by packed-int Gaussian elimination.

    Accepts either a 0/1 array or an already-packed list of ints. `max_rank`
    lets the caller stop early: on unstructured data the rank hits the column
    count after roughly `n_cols` rows, and there is no reason to grind through
    the rest of the matrix to learn that.
    """
    if isinstance(matrix, np.ndarray):
        if matrix.size == 0:
            return 0
        if max_rank is None:
            max_rank = matrix.shape[1]
        rows = rows_to_ints(matrix)
    else:
        rows = list(matrix)
        if max_rank is None:
            max_rank = max((r.bit_length() for r in rows), default=0)

    pivots: dict[int, int] = {}
    rank = 0
    for cur in rows:
        while cur:
            bit = cur.bit_length() - 1
            pivot = pivots.get(bit)
            if pivot is None:
                pivots[bit] = cur
                rank += 1
                break
            cur ^= pivot
        if rank >= max_rank:
            break
    return rank


def rank_gf2_galois(matrix: np.ndarray) -> int:
    """Reference rank via galois. Slow on purpose - this is what we trust."""
    import galois

    gf2 = galois.GF(2)
    if matrix.size == 0:
        return 0
    return int(np.linalg.matrix_rank(gf2(np.asarray(matrix, dtype=np.uint8))))


def null_space_gf2(matrix: np.ndarray) -> np.ndarray:
    """Basis of {h : matrix @ h = 0} over GF(2), as a (k, n_cols) uint8 array.

    This is where the recovered parity checks come from: every vector in here
    is a linear constraint the encoder imposed on the stream, and the shortest
    of them is the code's parity-check polynomial.
    """
    import galois

    gf2 = galois.GF(2)
    if matrix.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    basis = gf2(np.asarray(matrix, dtype=np.uint8)).null_space()
    return np.asarray(basis, dtype=np.uint8)
