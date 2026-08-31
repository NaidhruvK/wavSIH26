"""The S4 command line path.

This is the "if only 48 hours remain" floor from the plan - the one path that
must keep working when the API, the browser and Docker are all unavailable. It
had 0% test coverage until now, which is the wrong number for the thing you
fall back to when everything else is broken.

Exit codes are part of the contract, not an afterthought: 0 recovered,
1 nothing recovered, 2 the caller made a mistake. A demo script that pipes this
into anything needs them to be stable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.cli import load_bits, main
from tests.fixtures.local_zoo import make_stream

TRUTH_PERIOD = 96


@pytest.fixture(scope="module")
def streams(tmp_path_factory):
    d = tmp_path_factory.mktemp("s4cli")
    bits, truth = make_stream(80_000, 8, 12, seed=0)
    np.save(d / "stream.npy", bits)
    np.packbits(bits).tofile(d / "stream.bin")
    (d / "empty.bin").write_bytes(b"")
    (d / "tiny.bin").write_bytes(b"\x01\x02")
    return d, truth


def test_load_npy_and_raw_agree(streams):
    d, _ = streams
    from_npy = load_bits(d / "stream.npy")
    from_bin = load_bits(d / "stream.bin")
    assert from_npy.dtype == np.uint8
    assert set(np.unique(from_npy)) <= {0, 1}
    assert np.array_equal(from_npy, from_bin[:len(from_npy)])


def test_recovers_from_npy(streams, capsys):
    d, truth = streams
    assert main([str(d / "stream.npy")]) == 0
    out = capsys.readouterr().out
    assert "period=%d" % truth.period in out
    assert "0o171, 0o133" in out


def test_recovers_from_raw_binary(streams, capsys):
    d, truth = streams
    assert main([str(d / "stream.bin")]) == 0
    assert "period=%d" % truth.period in capsys.readouterr().out


def test_demo_mode_runs(capsys):
    assert main(["--demo", "--depth", "4", "--width", "16"]) == 0
    out = capsys.readouterr().out
    assert "period=64" in out


def test_missing_file_exits_two(tmp_path, capsys):
    assert main([str(tmp_path / "nope.npy")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_no_arguments_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_empty_and_tiny_files_report_rather_than_crash(streams, capsys):
    d, _ = streams
    for name in ("empty.bin", "tiny.bin"):
        assert main([str(d / name)]) == 1
        out = capsys.readouterr().out
        assert "no code structure detected" in out
        assert "need >=" in out


def test_uncoded_data_is_refused(tmp_path, capsys):
    rng = np.random.default_rng(0)
    np.save(tmp_path / "noise.npy", rng.integers(0, 2, 80_000, dtype=np.uint8))
    assert main([str(tmp_path / "noise.npy")]) == 1
    out = capsys.readouterr().out
    assert "no code structure detected" in out
    assert "no rank collapse" in out


def test_searchable_period_is_printed_before_any_verdict(streams, capsys):
    """A negative is only meaningful next to the range that was searched, so the
    range has to be on screen even when the run succeeds."""
    d, _ = streams
    main([str(d / "stream.npy")])
    out = capsys.readouterr().out
    assert "searchable period" in out
    assert out.index("searchable period") < out.index("exact rank collapse")


def test_statistical_flag_runs_on_the_deinterleaved_stream(streams, capsys):
    d, _ = streams
    assert main([str(d / "stream.npy"), "--statistical"]) == 0
    out = capsys.readouterr().out
    assert "de-interleaved stream" in out, "statistical search ran on the wrong stream"
    assert "span=14" in out
