"""Tests for service/cli.py command-line interface.

OWNED BY: Naidhruv.
Verifies:
1. Argument parser configuration for subcommands: run, status, analyze
2. `status` subcommand execution
3. `run` subcommand uvicorn invocation with custom host, port, and reload flags
4. `run` subcommand error handling when uvicorn is missing
5. `analyze` subcommand on valid WAV input (summary text and JSON output)
6. `analyze` subcommand error handling for missing files
"""
from __future__ import annotations

import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from service.cli import build_parser, handle_analyze, handle_run, handle_status, main
from service.config import AppConfig, config


def make_dummy_wav(path: Path | str, duration_sec: float = 0.05, fs: int = 200000) -> None:
    """Create a minimal valid 2-channel 16-bit PCM RIFF WAV using standard library struct."""
    n_samples = max(100, int(duration_sec * fs))
    byte_count = n_samples * 2 * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + byte_count,
        b"WAVE",
        b"fmt ",
        16,
        1,
        2,
        fs,
        fs * 4,
        4,
        16,
        b"data",
        byte_count,
    )
    raw_data = b"\x00\x00\x10\x00" * n_samples
    Path(path).write_bytes(header + raw_data)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        # Isolated config paths
        self.orig_db = config.db_path
        self.orig_upload = config.upload_dir
        self.orig_artifact = config.artifact_dir

        object.__setattr__(config, "db_path", self.tmp_path / "test_cli.db")
        object.__setattr__(config, "upload_dir", self.tmp_path / "uploads")
        object.__setattr__(config, "artifact_dir", self.tmp_path / "artifacts")
        config.ensure_directories()

    def tearDown(self):
        object.__setattr__(config, "db_path", self.orig_db)
        object.__setattr__(config, "upload_dir", self.orig_upload)
        object.__setattr__(config, "artifact_dir", self.orig_artifact)
        self.tmp_dir.cleanup()

    def test_build_parser_subcommands(self):
        parser = build_parser()

        # Parse run command
        args_run = parser.parse_args(["run", "--host", "127.0.0.1", "--port", "9000", "--reload"])
        self.assertEqual(args_run.command, "run")
        self.assertEqual(args_run.host, "127.0.0.1")
        self.assertEqual(args_run.port, 9000)
        self.assertTrue(args_run.reload)

        # Parse status command
        args_status = parser.parse_args(["status"])
        self.assertEqual(args_status.command, "status")

        # Parse analyze command
        args_analyze = parser.parse_args(["analyze", "sample.wav", "--fs", "100000", "--mod", "bpsk", "--json"])
        self.assertEqual(args_analyze.command, "analyze")
        self.assertEqual(args_analyze.file, "sample.wav")
        self.assertEqual(args_analyze.fs, 100000.0)
        self.assertEqual(args_analyze.mod, "bpsk")
        self.assertTrue(args_analyze.json)

    def test_status_command(self):
        captured_out = io.StringIO()
        with patch("sys.stdout", captured_out):
            ret = main(["status"])
        self.assertEqual(ret, 0)
        output = captured_out.getvalue()
        self.assertIn("RAAYA / wavSIH26", output)
        self.assertIn("Contracts Layer", output)

    @patch.dict("sys.modules", {"uvicorn": MagicMock()})
    def test_run_command_success(self):
        import uvicorn
        uvicorn.run = MagicMock()

        with patch("sys.stdout", io.StringIO()):
            ret = main(["run", "--host", "0.0.0.0", "--port", "8080"])
        self.assertEqual(ret, 0)
        uvicorn.run.assert_called_once_with("service.main:app", host="0.0.0.0", port=8080, reload=False)

    def test_run_command_missing_uvicorn(self):
        with patch.dict("sys.modules", {"uvicorn": None}):
            captured_err = io.StringIO()
            with patch("sys.stderr", captured_err):
                ret = handle_run(build_parser().parse_args(["run"]))
            self.assertEqual(ret, 1)
            self.assertIn("uvicorn", captured_err.getvalue().lower())

    def test_analyze_command_missing_file(self):
        captured_err = io.StringIO()
        with patch("sys.stderr", captured_err):
            ret = main(["analyze", str(self.tmp_path / "nonexistent.wav")])
        self.assertEqual(ret, 1)
        self.assertIn("does not exist", captured_err.getvalue())

    def test_analyze_command_summary_text(self):
        wav_file = self.tmp_path / "valid_signal.wav"
        make_dummy_wav(wav_file, duration_sec=0.02, fs=100000)

        captured_out = io.StringIO()
        with patch("sys.stdout", captured_out):
            ret = main(["analyze", str(wav_file)])
        self.assertIn(ret, (0, 1))
        output = captured_out.getvalue()
        self.assertIn("RAAYA / wavSIH26 — OFFLINE SIGNAL ANALYSIS", output)
        self.assertIn("Run ID:", output)
        self.assertIn("Stages:", output)

    def test_analyze_command_json_output(self):
        wav_file = self.tmp_path / "valid_signal_json.wav"
        make_dummy_wav(wav_file, duration_sec=0.02, fs=100000)

        captured_out = io.StringIO()
        with patch("sys.stdout", captured_out):
            ret = main(["analyze", str(wav_file), "--json"])
        self.assertIn(ret, (0, 1))
        output = captured_out.getvalue()
        data = json.loads(output)
        self.assertIn("run_id", data)
        self.assertIn("stages", data)
        self.assertIn("envelope_verdict", data)


if __name__ == "__main__":
    unittest.main()
