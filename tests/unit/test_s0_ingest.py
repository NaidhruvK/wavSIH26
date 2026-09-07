"""tests/unit/test_s0_ingest.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.s0_ingest import ingest, sniff_iq_layout, sniff_raw_format

CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "rf"
SNIFFER_CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "s0_sniffer"
KNOWN_GAP_CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "s0_sniffer_known_gaps"


def test_reads_own_zoo_wav():
    wav_files = list(CORPUS.glob("*.wav"))
    assert wav_files, "no RF corpus files found -- run python -m zoo.build_rf_corpus first"

    f = wav_files[0]
    result = ingest(f)
    assert result.status == "ok"
    assert result.source_format == "wav"
    assert result.iq is not None
    assert result.iq.size > 0
    assert result.fs == 200_000.0


def test_fs_matches_truth_json():
    wav_files = list(CORPUS.glob("*.wav"))
    f = wav_files[0]
    truth = json.loads((f.with_suffix(".json")).read_text())
    result = ingest(f)
    assert result.fs == truth["fs"]


def test_missing_file_fails_cleanly():
    result = ingest("zoo/corpus/rf/does_not_exist.wav")
    assert result.status == "failed"
    assert result.reason is not None


def test_raw_int16_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    iq_true = (rng.normal(0, 0.3, 5000) + 1j * rng.normal(0, 0.3, 5000))
    interleaved = np.empty(iq_true.size * 2, dtype=np.int16)
    interleaved[0::2] = (iq_true.real * 32767).astype(np.int16)
    interleaved[1::2] = (iq_true.imag * 32767).astype(np.int16)
    p = tmp_path / "test.iq"
    interleaved.tofile(p)

    result = ingest(p, fs_hint=48000.0)
    assert result.status == "ok"
    assert result.source_format == "raw_int16"
    assert result.iq.size == iq_true.size


def _sniffer_files() -> list[Path]:
    files = sorted(SNIFFER_CORPUS.glob("*.iq"))
    if not files:
        pytest.skip("no s0_sniffer corpus -- run python -m zoo.build_s0_sniffer_corpus first")
    return files


def _truth_for(f: Path) -> dict:
    return json.loads(f.with_suffix("").with_suffix(".sidecar.json").read_text())


# --------------------------------------------------------------------------
# 7 Sep: endianness and channel-layout detection, with evidence shown.
# --------------------------------------------------------------------------

def test_sniff_raw_format_detects_big_endian_int16(tmp_path):
    rng = np.random.default_rng(1)
    iq_true = rng.normal(0, 0.3, 4000) + 1j * rng.normal(0, 0.3, 4000)
    interleaved = np.empty(iq_true.size * 2, dtype=">i2")
    interleaved[0::2] = (iq_true.real * 32000).astype(">i2")
    interleaved[1::2] = (iq_true.imag * 32000).astype(">i2")
    p = tmp_path / "be.iq"
    interleaved.tofile(p)

    hyps = sniff_raw_format(p)
    assert hyps[0][0] == "int16_be"
    assert len(hyps) > 1, "runner-up hypotheses must be present, not just the winner"
    assert all(len(h) == 3 for h in hyps), "each hypothesis carries (label, score, evidence)"


def test_sniff_iq_layout_detects_interleaved_vs_planar():
    rng = np.random.default_rng(2)
    t = np.arange(4000)
    i_ch = np.sin(2 * np.pi * 0.01 * t)     # smooth, oversampled-looking
    q_ch = np.cos(2 * np.pi * 0.01 * t)

    interleaved = np.empty(8000)
    interleaved[0::2], interleaved[1::2] = i_ch, q_ch
    planar = np.concatenate([i_ch, q_ch])

    hyps_i = sniff_iq_layout(interleaved)
    hyps_p = sniff_iq_layout(planar)
    assert hyps_i[0][0] == "interleaved"
    assert hyps_p[0][0] == "planar"
    assert all(len(h) == 3 for h in hyps_i + hyps_p)


def test_ingest_result_carries_layout_and_hypotheses(tmp_path):
    rng = np.random.default_rng(3)
    iq_true = rng.normal(0, 0.3, 4000) + 1j * rng.normal(0, 0.3, 4000)
    interleaved = np.empty(iq_true.size * 2, dtype=np.int16)
    interleaved[0::2] = (iq_true.real * 32000).astype(np.int16)
    interleaved[1::2] = (iq_true.imag * 32000).astype(np.int16)
    p = tmp_path / "test.iq"
    interleaved.tofile(p)

    result = ingest(p)
    assert result.layout == "interleaved"
    assert result.layout_hypotheses
    assert result.hypotheses


# --------------------------------------------------------------------------
# The 7 Sep gate: 12 of 12 correct, with runner-up hypotheses and scores
# displayed. Corpus: zoo/build_s0_sniffer_corpus.py.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "f", sorted(SNIFFER_CORPUS.glob("*.iq")) if SNIFFER_CORPUS.exists() else [],
    ids=lambda f: f.stem,
)
def test_s0_sniffer_recovers_true_format(f):
    truth = _truth_for(f)
    result = ingest(f)

    assert result.status == "ok", f"{f.name}: {result.reason}"
    assert result.source_format == f"raw_{truth['dtype']}", (
        f"{f.name}: dtype top hypothesis {result.source_format}, "
        f"true raw_{truth['dtype']} -- full ranking: {result.hypotheses}"
    )
    assert result.layout == truth["layout"], (
        f"{f.name}: layout top hypothesis {result.layout}, true {truth['layout']} "
        f"-- full ranking: {result.layout_hypotheses}"
    )

    # runner-up hypotheses and scores displayed, per the gate's own wording --
    # not just checked for existence, but genuinely ranked with visible evidence.
    scores = [h[1] for h in result.hypotheses]
    assert scores == sorted(scores, reverse=True)
    assert all(isinstance(h[2], str) and h[2] for h in result.hypotheses), \
        "every dtype hypothesis must carry a non-empty evidence string"
    assert all(isinstance(h[2], str) and h[2] for h in result.layout_hypotheses), \
        "every layout hypothesis must carry a non-empty evidence string"


def test_s0_sniffer_corpus_is_twelve_files():
    """Guards the gate's own number -- if someone trims the corpus, the
    12/12 claim should stop being true rather than silently become 10/10."""
    assert len(_sniffer_files()) == 12


# --------------------------------------------------------------------------
# Known, measured, NOT chased limitations -- pinned the same way
# test_fsk_order_known_gap_at_low_snr pins its gap: a stated miss, not a
# hidden one. If any of these starts passing, tighten sniff_raw_format /
# sniff_iq_layout's discriminator and delete the corresponding assertion.
# --------------------------------------------------------------------------

def _known_gap_files() -> list[Path]:
    files = sorted(KNOWN_GAP_CORPUS.glob("*.iq"))
    if not files:
        pytest.skip("no known-gap corpus -- run python -m zoo.build_s0_sniffer_corpus first")
    return files


def test_known_gap_byte_order_plus_planar_layout_compounds():
    """sniff_raw_format's byte-order discriminator is reliable in an
    interleaved layout (see test_s0_sniffer_recovers_true_format's BE
    cases) but not when the layout is ALSO planar -- two independent
    ambiguities stacked on one file, see the module docstring."""
    files = {f.stem: f for f in _known_gap_files()}
    for name in ("float32_be_planar_qpsk", "int16_be_planar_8psk"):
        f = files[name]
        truth = _truth_for(f)
        result = ingest(f)
        recovered = (result.source_format == f"raw_{truth['dtype']}"
                     and result.layout == truth["layout"])
        assert not recovered, (
            f"{name} now recovers correctly -- byte-order-plus-planar "
            "compound ambiguity may be fixed; promote this file into "
            "the main s0_sniffer corpus and delete this test."
        )


def test_known_gap_4fsk_layout_detection():
    """sniff_iq_layout's autocorrelation discriminator is near-zero for
    4fsk even on the CORRECT split -- its tone spacing at this sps
    decorrelates adjacent same-channel samples regardless of alignment.
    See sniff_iq_layout's docstring for the measured numbers."""
    f = next(f for f in _known_gap_files() if "4fsk" in f.stem)
    truth = _truth_for(f)
    result = ingest(f)
    recovered = result.layout == truth["layout"]
    assert not recovered, (
        "4fsk layout detection now works -- if a sharper discriminator "
        "was found, promote this file into the main s0_sniffer corpus "
        "and delete this test."
    )