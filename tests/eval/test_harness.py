"""Tests for eval/harness.py evaluation orchestrator and corpus discovery.

OWNED BY: Naidhruv.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contracts import AnalysisReport, StageResult, StageStatus
from eval.harness import evaluate_report, evaluate_run, load_truth_for_file
from eval.metrics import EvaluationResult
from service.config import config
from service.db import create_run, initialize_database, record_stage_result


class TestEvalHarness(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.db_path = self.tmp_path / "test_eval.db"
        initialize_database(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_evaluate_report_all_pass(self):
        truth = {
            "source_format": "wav",
            "fs": 200000.0,
            "snr_db": 15.0,
            "scheme": "qpsk",
            "sps": 4,
            "status": "ok",
            "evm_percent": 5.0,
            "interleaver": {"family": "block", "period": 96, "depth": 8, "width": 12},
            "code": {"polys_octal": [121, 91]},
            "n_source_bits": 10000,
            "injected_ber": 0.0,
            "payload_text": "CONFIRMED",
        }

        stages = [
            StageResult(
                stage="s0_ingest",
                status=StageStatus.OK,
                confidence=1.0,
                values={"source_format": "wav", "sample_rate": 200000.0},
            ),
            StageResult(
                stage="s1_detect",
                status=StageStatus.OK,
                confidence=0.9,
                values={"snr_db": 15.2},
            ),
            StageResult(
                stage="s2_estimate",
                status=StageStatus.OK,
                confidence=0.92,
                values={"symbol_rate": 50000.0, "cfo_hz": 10.0, "modulation": "qpsk"},
            ),
            StageResult(
                stage="s3_receive",
                status=StageStatus.OK,
                confidence=0.95,
                values={"modulation": "qpsk", "evm_percent": 5.2},
            ),
            StageResult(
                stage="s4_recover",
                status=StageStatus.OK,
                confidence=0.98,
                values={"period": 96, "family": "block", "generators_octal": [121, 91]},
            ),
            StageResult(
                stage="s5_decode",
                status=StageStatus.OK,
                confidence=0.99,
                values={"decoded_bits_count": 10000, "inferred_ber": 0.0},
            ),
            StageResult(
                stage="s6_frame",
                status=StageStatus.OK,
                confidence=1.0,
                values={"printable_fraction": 0.99, "looks_like_text": True, "text": "CONFIRMED"},
            ),
        ]

        report = AnalysisReport(
            run_id="run_eval_01",
            file_meta={"filename": "test_signal.wav"},
            envelope_verdict="in_envelope",
            stages=stages,
        )

        res = evaluate_report(report, truth=truth)
        self.assertIsInstance(res, EvaluationResult)
        self.assertEqual(res.overall_verdict, "pass")
        self.assertEqual(res.overall_score, 1.0)
        self.assertEqual(len(res.stages), 7)
        for s in res.stages.values():
            self.assertEqual(s.status, "pass")

    def test_evaluate_report_with_failures(self):
        truth = {
            "source_format": "wav",
            "fs": 200000.0,
            "snr_db": 25.0,
            "scheme": "8psk",
        }
        # S1 has wrong SNR, S2 has wrong modulation
        stages = [
            StageResult(
                stage="s0_ingest",
                status=StageStatus.OK,
                confidence=1.0,
                values={"source_format": "wav", "sample_rate": 200000.0},
            ),
            StageResult(
                stage="s1_detect",
                status=StageStatus.OK,
                confidence=0.8,
                values={"snr_db": 5.0},  # Error 20 dB > tolerance
            ),
            StageResult(
                stage="s2_estimate",
                status=StageStatus.OK,
                confidence=0.8,
                values={"symbol_rate": 10000.0, "cfo_hz": 0.0, "modulation": "2fsk"},
            ),
        ]

        report = AnalysisReport(
            run_id="run_eval_fail",
            file_meta={"filename": "bad_signal.wav"},
            stages=stages,
        )

        res = evaluate_report(report, truth=truth)
        self.assertIn(res.overall_verdict, ("fail", "partial"))
        self.assertEqual(res.stages["s1_detect"].status, "fail")
        self.assertEqual(res.stages["s2_estimate"].status, "fail")

    def test_load_truth_for_file_rf_corpus(self):
        # Look for existing sample in zoo/corpus/rf
        rf_dir = config.repo_root / "zoo" / "corpus" / "rf"
        wav_files = list(rf_dir.glob("*.wav"))
        if wav_files:
            sample_wav = wav_files[0]
            truth = load_truth_for_file(sample_wav)
            self.assertIsNotNone(truth)
            self.assertIn("scheme", truth)
            self.assertIn("fs", truth)

    def test_load_truth_for_file_s3_envelope_csv(self):
        # file named 'bpsk_20dB_sps4' exists in reports/s3_envelope.csv
        truth = load_truth_for_file("bpsk_20dB_sps4.wav")
        self.assertIsNotNone(truth)
        self.assertEqual(truth.get("scheme"), "bpsk")
        self.assertEqual(truth.get("snr_db"), 20.0)

    def test_evaluate_run_database(self):
        run_id = "run_db_eval_01"
        create_run(
            run_id=run_id,
            filename="bpsk_20dB_sps4.wav",
            file_size=2048,
            sha256="sha",
            status="completed",
            envelope_verdict="in_envelope",
            db_path=self.db_path,
        )
        record_stage_result(
            run_id=run_id,
            stage="s0_ingest",
            status="ok",
            confidence=1.0,
            values={"source_format": "wav", "sample_rate": 200000.0},
            db_path=self.db_path,
        )
        record_stage_result(
            run_id=run_id,
            stage="s1_detect",
            status="ok",
            confidence=0.9,
            values={"snr_db": 19.8},
            db_path=self.db_path,
        )

        res = evaluate_run(run_id=run_id, db_path=self.db_path)
        self.assertIsInstance(res, EvaluationResult)
        self.assertEqual(res.run_id, run_id)
        self.assertEqual(res.stages["s0_ingest"].status, "pass")
        self.assertEqual(res.stages["s1_detect"].status, "pass")

    def test_cli_main_entry(self):
        from eval.__main__ import main

        # Test CLI default demonstration mode
        with patch.object(sys, "argv", ["eval"]), patch("sys.stdout", io.StringIO()):
            ret = main()
            self.assertIn(ret, (0, 1))

        # Test CLI --json mode
        with patch.object(sys, "argv", ["eval", "--json"]):
            captured_stdout = io.StringIO()
            with patch("sys.stdout", captured_stdout):
                ret = main()
                self.assertIn(ret, (0, 1))
                output = captured_stdout.getvalue()
                parsed = json.loads(output)
                self.assertIn("overall_score", parsed)
                self.assertIn("stages", parsed)


if __name__ == "__main__":
    unittest.main()
