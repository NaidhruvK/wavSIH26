"""GF(2) rank, checked against galois on matrices of known rank.

The sweep uses a packed-int Gaussian elimination because it has to evaluate a
few hundred candidate row lengths per file. That is exactly the kind of code
that is quietly wrong, so it does not get to be the only implementation: every
assertion here compares it against galois, which is the one we trust.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.gf2 import (
    rank_gf2,
    rank_gf2_galois,
    null_space_gf2,
    reshape_rows,
    rows_to_ints,
)


def build_known_rank(rows: int, cols: int, rank: int, rng) -> np.ndarray:
    """A @ B over GF(2) has rank <= `rank` by construction, and equals it a.s."""
    A = rng.integers(0, 2, (rows, rank), dtype=np.uint8)
    B = rng.integers(0, 2, (rank, cols), dtype=np.uint8)
    return (A @ B) % 2


@pytest.mark.parametrize("seed", range(12))
def test_fast_rank_matches_galois_on_constructed_matrices(seed):
    rng = np.random.default_rng(seed)
    cols = int(rng.integers(4, 40))
    rank = int(rng.integers(1, cols + 1))
    M = build_known_rank(3 * cols, cols, rank, rng)
    assert rank_gf2(M) == rank_gf2_galois(M)


@pytest.mark.parametrize("seed", range(8))
def test_fast_rank_matches_galois_on_random_matrices(seed):
    rng = np.random.default_rng(1000 + seed)
    M = rng.integers(0, 2, (60, int(rng.integers(4, 45))), dtype=np.uint8)
    assert rank_gf2(M) == rank_gf2_galois(M)


def test_identity_and_zero_matrices():
    I = np.eye(16, dtype=np.uint8)
    assert rank_gf2(I) == rank_gf2_galois(I) == 16
    Z = np.zeros((16, 16), dtype=np.uint8)
    assert rank_gf2(Z) == rank_gf2_galois(Z) == 0


def test_duplicated_rows_do_not_add_rank():
    rng = np.random.default_rng(7)
    M = rng.integers(0, 2, (10, 20), dtype=np.uint8)
    stacked = np.vstack([M, M, M])
    assert rank_gf2(stacked) == rank_gf2(M)


def test_max_rank_early_exit_is_not_a_wrong_answer():
    """Early exit may only fire once the rank is already maximal."""
    rng = np.random.default_rng(3)
    M = rng.integers(0, 2, (400, 24), dtype=np.uint8)
    assert rank_gf2(M) == rank_gf2(M, max_rank=None) == rank_gf2_galois(M)


def test_empty_matrix():
    assert rank_gf2(np.zeros((0, 8), dtype=np.uint8)) == 0
    assert rows_to_ints(np.zeros((0, 8), dtype=np.uint8)) == []


def test_null_space_vectors_really_are_in_the_null_space():
    rng = np.random.default_rng(5)
    M = build_known_rank(40, 20, 13, rng)
    ns = null_space_gf2(M)
    assert ns.shape[0] == 20 - rank_gf2(M)
    assert np.all((M @ ns.T) % 2 == 0)


def test_reshape_discards_partial_rows_and_honours_offset():
    bits = np.arange(100, dtype=np.uint8) % 2
    M = reshape_rows(bits, 7)
    assert M.shape == (14, 7)
    M2 = reshape_rows(bits, 7, offset=3)
    assert M2.shape == (13, 7)
    assert np.array_equal(M2[0], bits[3:10])


def test_reshape_rejects_nonsense_row_length():
    with pytest.raises(ValueError):
        reshape_rows(np.zeros(10, dtype=np.uint8), 0)
