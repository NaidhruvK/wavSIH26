"""tests/unit/test_s0_ingest.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pipeline.s0_ingest import ingest

CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "rf"


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