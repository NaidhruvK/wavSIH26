"""Closed-set blind LDPC identification.

What reports/blind_ldpc.md claims, asserted:

  - each catalogue code is identified with its exact codeword offset
  - streams every linear code accepts (zeros, periodic) are refused
  - a stream whose code is not in the catalogue is refused
  - two RELATED catalogue entries that both fit do not produce a confident pick
  - the identification output is directly decodable
  - open-set recovery of an unknown H is still not attempted
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s5_decode.ldpc_code as L  # noqa: E402
from pipeline.s5_decode.ldpc_catalogue import (CatalogueEntry,  # noqa: E402
                                               build_reference_catalogue,
                                               codewords_from_h, load_catalogue,
                                               regular_ldpc, write_alist)
from registry import CODES  # noqa: E402


@pytest.fixture(scope="module")
def ldpc():
    return CODES["ldpc"]


@pytest.fixture(scope="module")
def catalogue():
    build_reference_catalogue()
    return load_catalogue()


def _shifted(h, blocks, shift, seed=3):
    stream, _ = codewords_from_h(h, blocks, seed=seed)
    pad = np.random.default_rng(9).integers(0, 2, shift, dtype=np.uint8)
    return np.concatenate([pad, stream])


def test_catalogue_has_the_reference_entries(catalogue):
    names = {e.name for e in catalogue}
    assert {"reference-n48-r1_2-regular36-seed0",
            "reference-n96-r1_2-regular36-seed0",
            "reference-n192-r1_2-regular36-seed0"} <= names


def test_alist_round_trip(tmp_path):
    h = regular_ldpc(96, seed=5)
    path = write_alist(h, tmp_path / "x.alist")
    assert np.array_equal(L.read_alist(path), h)


def test_codewords_have_zero_syndrome():
    h = regular_ldpc(96, seed=0)
    words, _ = codewords_from_h(h, 8, seed=1)
    assert not ((h @ words.reshape(8, 96).T) % 2).any()


def test_every_catalogue_code_is_identified_with_its_offset(ldpc, catalogue):
    for e in catalogue:
        shift = 37 % e.n
        got = ldpc.blind_recover(_shifted(e.h, L.MIN_ID_BLOCKS + 4, shift))
        assert got is not None, e.name
        assert got["code_name"] == e.name
        assert got["offset"] == shift
        assert got["syndrome_density"] == 0.0


@pytest.mark.parametrize("label,bits", [
    ("zeros", np.zeros(20_000, dtype=np.uint8)),
    ("ones", np.ones(20_000, dtype=np.uint8)),
    ("alternating", np.tile([0, 1], 10_000).astype(np.uint8)),
    ("period-8", np.tile([1, 0, 1, 1, 0, 0, 1, 0], 2_500).astype(np.uint8)),
    ("random", np.random.default_rng(11).integers(0, 2, 20_000, dtype=np.uint8)),
    ("biased", (np.random.default_rng(12).random(20_000) < 0.7).astype(np.uint8)),
])
def test_streams_that_are_not_catalogue_codewords_are_refused(ldpc, label, bits):
    assert ldpc.blind_recover(bits) is None


def test_a_code_outside_the_catalogue_is_refused(ldpc, catalogue):
    foreign = regular_ldpc(96, seed=12345)          # not in the directory
    assert ldpc.blind_recover(_shifted(foreign, 12, 5)) is None


def test_related_entries_that_both_fit_are_refused_not_guessed(ldpc):
    """A catalogue holding H and a subset of H's rows: both annihilate the
    stream, so the threshold passes both. Only ID_RUNNER_UP_RATIO says 'not
    sure which' - sqrt(24*6)=12 against sqrt(48*6)=17 is 1.41x, under 2.0."""
    h = regular_ldpc(96, seed=0)
    cat = [CatalogueEntry("full", h, "test"), CatalogueEntry("half", h[:24], "test")]
    assert ldpc.blind_recover(_shifted(h, 10, 0), catalogue=cat) is None


def test_a_single_entry_catalogue_needs_only_the_threshold(ldpc):
    h = regular_ldpc(96, seed=0)
    got = ldpc.blind_recover(_shifted(h, 10, 11), catalogue=[CatalogueEntry("only", h, "test")])
    assert got is not None and got["offset"] == 11 and got["runner_up_z"] is None


def test_too_few_blocks_are_not_scored(ldpc):
    h = regular_ldpc(96, seed=0)
    short = _shifted(h, L.MIN_ID_BLOCKS - 2, 0)
    assert ldpc.blind_recover(short, catalogue=[CatalogueEntry("only", h, "test")]) is None


@pytest.mark.parametrize("eps", [0.01, 0.02])
def test_identification_survives_channel_errors(ldpc, catalogue, eps):
    target = next(e for e in catalogue if e.name == "reference-n96-r1_2-regular36-seed0")
    stream, _ = codewords_from_h(target.h, 12, seed=7)
    stream[np.random.default_rng(13).random(stream.size) < eps] ^= 1
    got = ldpc.blind_recover(stream)
    assert got is not None and got["code_name"] == target.name


def test_identification_output_decodes(ldpc, catalogue):
    target = next(e for e in catalogue if e.name == "reference-n96-r1_2-regular36-seed0")
    soft = np.where(_shifted(target.h, 12, 61, seed=21) == 0, 6.0, -6.0)
    got = ldpc.blind_recover(soft)
    assert got["offset"] == 61
    syn = ldpc.syndrome(soft, got)
    assert syn["blocks"] == 12 and syn["blocks_converged"] == 12
    assert len(ldpc.decode(soft, got)) > 0


def test_decode_without_a_matrix_still_refuses():
    """Open-set recovery of an unknown H is still out of scope."""
    with pytest.raises(ValueError, match="no parity-check matrix"):
        L.parity_check_from_params({})
