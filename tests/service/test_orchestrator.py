"""Tests for service/orchestrator.py.

Verifies end-to-end S0->S6 pipeline execution, native return type adaptation,
failure isolation, per-stage and total timeout enforcement, S2 fallback,
artifact handling, and asynchronous job submission.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import dataclasses
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

from contracts import AnalysisReport, StageResult, StageStatus
from service.config import AppConfig, config
from service.db import get_all_stage_results, get_run, initialize_database
from service.job_runner import JobRunner
from service.orchestrator import (
    adapt_s0,
    adapt_s1,
    adapt_s2,
    adapt_s3,
    adapt_s4,
    adapt_s5,
    adapt_s6,
    get_plugin_load_errors,
    get_s2_estimate,
    get_s3_receive,
    load_plugins,
    orchestrate,
    submit_analysis_job,
)


class DummyS0Result:
    def __init__(self, status="ok", iq=None, fs=200000.0, source_format="wav", hypotheses=None, reason=None):
        self.status = status
        self.iq = iq if iq is not None else [1.0 + 0.5j] * 1000
        self.fs = fs
        self.source_format = source_format
        self.hypotheses = hypotheses or [("wav", 1.0)]
        self.reason = reason
        self.file_path = "test.wav"


class DummyS1Result:
    def __init__(self, status="ok", snr_db=15.0, noise_floor_db=-60.0, occupied_bw_hz=50000.0, bursts=None, reason=None):
        self.status = status
        self.fs = 200000.0
        self.snr_db = snr_db
        self.noise_floor_db = noise_floor_db
        self.occupied_bw_hz = occupied_bw_hz
        self.bursts = bursts or [(0, 100)]
        self.psd_freqs = [-50000.0, 0.0, 50000.0]
        self.psd_db = [-60.0, -20.0, -60.0]
        self.reason = reason


class DummyS2Estimate:
    def __init__(self, symbol_rate=25000.0, fs=200000.0, cfo_hz=50.0, order_hint=4):
        self.symbol_rate = symbol_rate
        self.fs = fs
        self.cfo_hz = cfo_hz
        self.order_hint = order_hint
        self.symbol_rate_score = 9.5
        self.cfo_score = 8.0


class RealS2EstimateResult:
    """Simulates Dheeraj's S2 stage result exposing symbol_rate_hz."""
    def __init__(self, symbol_rate_hz=32000.0, fs=200000.0, cfo_hz=75.0, order_hint=4):
        self.symbol_rate_hz = symbol_rate_hz
        self.fs = fs
        self.cfo_hz = cfo_hz
        self.order_hint = order_hint
        self.symbol_rate_score = 9.8
        self.cfo_score = 8.5


class DummyS3Result:
    def __init__(self, status="ok", llrs=None, values=None, reason=None, confidence=0.95):
        self.status = status
        self.confidence = confidence
        self.values = values if values is not None else {"modulation": "qpsk", "evm_percent": 5.2}
        self.hypotheses = [{"value": "qpsk", "score": 0.95, "evidence": "tight clusters"}]
        self.reason = reason
        self.llrs = llrs if llrs is not None else [1.5, -2.0, 3.1, -1.8] * 100
        self.symbols = [1.0 + 1.0j, -1.0 + 1.0j, -1.0 - 1.0j, 1.0 - 1.0j] * 20

    def as_stage_result(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "values": self.values,
            "hypotheses": self.hypotheses,
            "reason": self.reason,
        }


class DummyRecoveryResult:
    def __init__(self, status="ok"):
        self.status = status
        self.confidence = 0.99
        self.period = 96
        self.offset = 0
        self.generators_octal = (0o171, 0o133)
        self.method = "exact"
        self.inferred_ber = None
        self.reason = ""
        self.interleaver = type("Intl", (), {"family": "block", "params": {"depth": 8, "width": 12}})()
        self.code = type("Code", (), {"n": 2, "memory": 6})()
        self.hypotheses = [
            type("Hyp", (), {"family": "block", "params": {"depth": 8, "width": 12}, "score": 0.99, "evidence": "collapse"})()
        ]
        self.profile = type("Prof", (), {"deficiency": {96: 36}})()


class DummyPayloadReport:
    def __init__(self):
        self.n_bytes = 40
        self.printable_fraction = 0.95
        self.text = "RAAYA TELEMETRY LOCK CONFIRMED"
        self.looks_like_text = True

    def preview(self, width=100):
        return self.text[:width]


def make_clean_overrides() -> dict[str, Any]:
    return {
        "s0_ingest": lambda p, fs_hint=None: DummyS0Result(),
        "s1_detect": lambda iq, fs: DummyS1Result(),
        "s2_estimate": lambda iq, fs: DummyS2Estimate(),
        "s3_receive": lambda iq, params: DummyS3Result(),
        "s4_recover": lambda bits: DummyRecoveryResult(),
        "s5_decode": lambda llrs, params: [0, 1, 0, 1] * 200,
        "s6_frame": lambda bits: DummyPayloadReport(),
    }


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.db_path = self.tmp_path / "test_orch.db"
        initialize_database(self.db_path)

        # Create dummy file to analyze
        self.test_file = self.tmp_path / "signal.wav"
        self.test_file.write_bytes(b"RIFF" + b"\x00" * 1000)

        self.orig_artifact_dir = config.artifact_dir
        object.__setattr__(config, "artifact_dir", self.tmp_path / "artifacts")
        config.artifact_dir.mkdir(parents=True, exist_ok=True)

        self.runner = JobRunner(max_workers=2, stage_timeout=1.0, total_timeout=5.0)

    def tearDown(self):
        object.__setattr__(config, "artifact_dir", self.orig_artifact_dir)
        self.runner.shutdown(wait=True, cancel_futures=True)
        self.tmp_dir.cleanup()

    def test_normal_s0_to_s6_orchestration(self):
        overrides = make_clean_overrides()
        report = orchestrate(
            run_id="run-norm-01",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertIsInstance(report, AnalysisReport)
        self.assertEqual(report.run_id, "run-norm-01")
        self.assertEqual(report.envelope_verdict, "in_envelope")
        self.assertEqual(len(report.stages), 7)

        expected_stages = [
            "s0_ingest",
            "s1_detect",
            "s2_estimate",
            "s3_receive",
            "s4_recover",
            "s5_decode",
            "s6_frame",
        ]
        actual_stages = [s.stage for s in report.stages]
        self.assertEqual(actual_stages, expected_stages)

        for s in report.stages:
            self.assertEqual(s.status, StageStatus.OK)
            self.assertGreaterEqual(s.confidence, 0.0)
            self.assertLessEqual(s.confidence, 1.0)

        self.assertEqual(report.final["payload_text"], "RAAYA TELEMETRY LOCK CONFIRMED")
        self.assertEqual(report.final["printable_fraction"], 0.95)

        # Verify DB persistence
        run_record = get_run("run-norm-01", db_path=self.db_path)
        self.assertIsNotNone(run_record)
        self.assertEqual(run_record["status"], "completed")
        stage_records = get_all_stage_results("run-norm-01", db_path=self.db_path)
        self.assertEqual(len(stage_records), 7)

    def test_stage_result_adaptation(self):
        # S0
        s0 = adapt_s0(DummyS0Result(), 10.0)
        self.assertEqual(s0.stage, "s0_ingest")
        self.assertEqual(s0.status, StageStatus.OK)
        self.assertEqual(s0.values["source_format"], "wav")

        # S1
        s1 = adapt_s1(DummyS1Result(), 15.0, "run-adapt")
        self.assertEqual(s1.stage, "s1_detect")
        self.assertEqual(s1.values["snr_db"], 15.0)

        # S2 (symbol_rate fallback compatibility)
        s2 = adapt_s2(DummyS2Estimate(), 20.0)
        self.assertEqual(s2.stage, "s2_estimate")
        self.assertEqual(s2.values["symbol_rate"], 25000.0)
        self.assertEqual(s2.values["symbol_rate_hz"], 25000.0)

        # S2 (Dheeraj's real S2 result with symbol_rate_hz)
        s2_real = adapt_s2(RealS2EstimateResult(symbol_rate_hz=32000.0, fs=200000.0), 20.0)
        self.assertEqual(s2_real.stage, "s2_estimate")
        self.assertEqual(s2_real.status, StageStatus.OK)
        self.assertEqual(s2_real.values["symbol_rate"], 32000.0)
        self.assertEqual(s2_real.values["symbol_rate_hz"], 32000.0)
        self.assertEqual(s2_real.values["sps"], 200000.0 / 32000.0)

        # S3
        s3 = adapt_s3(DummyS3Result(), 25.0, "run-adapt")
        self.assertEqual(s3.stage, "s3_receive")
        self.assertEqual(s3.values["modulation"], "qpsk")

        # S4
        s4 = adapt_s4(DummyRecoveryResult(), 30.0, "run-adapt")
        self.assertEqual(s4.stage, "s4_recover")
        self.assertEqual(s4.values["period"], 96)

        # S5
        s5 = adapt_s5([0, 1] * 50, 35.0)
        self.assertEqual(s5.stage, "s5_decode")
        self.assertEqual(s5.values["decoded_bits_count"], 100)

        # S6
        s6 = adapt_s6(DummyPayloadReport(), 40.0)
        self.assertEqual(s6.stage, "s6_frame")
        self.assertEqual(s6.values["n_bytes"], 40)
        self.assertTrue(s6.values["looks_like_text"])
        self.assertEqual(s6.values["payload_text"], "RAAYA TELEMETRY LOCK CONFIRMED")
        self.assertEqual(s6.values["entropy"], 0.0)
        self.assertFalse(s6.values["has_header"])
        self.assertEqual(s6.values["header_hex"], "")
        self.assertEqual(s6.values["header_entropy"], 0.0)
        self.assertEqual(s6.values["payload_entropy"], 0.0)

    def test_adapt_s6_with_framing_and_entropy(self):
        """adapt_s6 forwards all six S6 framing and entropy fields to StageResult.values."""
        class FramedReport:
            n_bytes = 48
            printable_fraction = 0.98
            text = "\x1a\xcf\xfc\x1dTELEMETRY_PAYLOAD_VALID_2026"
            looks_like_text = True
            inverted = False
            entropy = 3.82
            has_header = True
            header_hex = "1ACFFC1D"
            header_entropy = 2.0
            payload_entropy = 3.65
            payload_text = "TELEMETRY_PAYLOAD_VALID_2026"

        s6 = adapt_s6(FramedReport(), 42.0)
        self.assertEqual(s6.stage, "s6_frame")
        self.assertEqual(s6.status, StageStatus.OK)
        self.assertEqual(s6.values["n_bytes"], 48)
        self.assertAlmostEqual(s6.values["printable_fraction"], 0.98)
        self.assertTrue(s6.values["looks_like_text"])
        self.assertEqual(s6.values["text"], "\x1a\xcf\xfc\x1dTELEMETRY_PAYLOAD_VALID_2026")
        self.assertAlmostEqual(s6.values["entropy"], 3.82)
        self.assertTrue(s6.values["has_header"])
        self.assertEqual(s6.values["header_hex"], "1ACFFC1D")
        self.assertAlmostEqual(s6.values["header_entropy"], 2.0)
        self.assertAlmostEqual(s6.values["payload_entropy"], 3.65)
        self.assertEqual(s6.values["payload_text"], "TELEMETRY_PAYLOAD_VALID_2026")

        # Verify no raw byte arrays are present
        for k, v in s6.values.items():
            self.assertNotIsInstance(v, (bytes, bytearray), f"Raw byte array found in values[{k}]")

    def test_orchestration_final_exposes_s6_framing_and_entropy(self):
        """AnalysisReport.final and S6 StageResult expose framing and entropy information."""
        class FramedPayloadReport:
            n_bytes = 36
            printable_fraction = 1.0
            text = "\x1a\xcf\xfc\x1dVALID_FRAMED_STREAM"
            looks_like_text = True
            inverted = False
            entropy = 3.4
            has_header = True
            header_hex = "1ACFFC1D"
            header_entropy = 2.0
            payload_entropy = 3.1
            payload_text = "VALID_FRAMED_STREAM"

        overrides = make_clean_overrides()
        overrides["s6_frame"] = lambda bits: FramedPayloadReport()

        report = orchestrate(
            run_id="run-s6-framing-01",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertIsInstance(report, AnalysisReport)
        self.assertEqual(report.envelope_verdict, "in_envelope")

        # Check final payload
        self.assertEqual(report.final["payload_text"], "VALID_FRAMED_STREAM")
        self.assertEqual(report.final["printable_fraction"], 1.0)
        self.assertTrue(report.final["looks_like_text"])
        self.assertAlmostEqual(report.final["entropy"], 3.4)
        self.assertTrue(report.final["has_header"])
        self.assertEqual(report.final["header_hex"], "1ACFFC1D")
        self.assertAlmostEqual(report.final["header_entropy"], 2.0)
        self.assertAlmostEqual(report.final["payload_entropy"], 3.1)

        # Check S6 stage values
        s6_stage = next(s for s in report.stages if s.stage == "s6_frame")
        self.assertEqual(s6_stage.values["header_hex"], "1ACFFC1D")
        self.assertTrue(s6_stage.values["has_header"])
        self.assertEqual(s6_stage.values["payload_text"], "VALID_FRAMED_STREAM")
        self.assertAlmostEqual(s6_stage.values["payload_entropy"], 3.1)

    def test_stage_failure_isolation(self):
        overrides = make_clean_overrides()

        # Inject failure in S2
        def failing_s2(iq, fs):
            raise RuntimeError("Corrupted cyclostationary spectrum")

        overrides["s2_estimate"] = failing_s2

        report = orchestrate(
            run_id="run-fail-s2",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        stage_map = {s.stage: s for s in report.stages}
        self.assertEqual(stage_map["s0_ingest"].status, StageStatus.OK)
        self.assertEqual(stage_map["s1_detect"].status, StageStatus.OK)
        self.assertEqual(stage_map["s2_estimate"].status, StageStatus.FAILED)
        self.assertIn("Corrupted cyclostationary spectrum", stage_map["s2_estimate"].reason)
        self.assertEqual(report.envelope_verdict, "failed")

    def test_s0_failure_aborts_downstream(self):
        overrides = make_clean_overrides()
        overrides["s0_ingest"] = lambda p, fs_hint=None: DummyS0Result(status="failed", iq=None, reason="corrupt WAV header")

        report = orchestrate(
            run_id="run-fail-s0",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertEqual(report.envelope_verdict, "failed")
        self.assertEqual(len(report.stages), 7)
        self.assertEqual(report.stages[0].status, StageStatus.FAILED)
        for downstream in report.stages[1:]:
            self.assertEqual(downstream.status, StageStatus.FAILED)
            self.assertIn("Aborted", downstream.reason)

    def test_stage_timeout_handling(self):
        overrides = make_clean_overrides()

        def slow_stage(iq, fs):
            time.sleep(0.3)
            return DummyS1Result()

        overrides["s1_detect"] = slow_stage

        report = orchestrate(
            run_id="run-timeout-s1",
            file_path=self.test_file,
            stage_timeout=0.05,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        stage_map = {s.stage: s for s in report.stages}
        self.assertEqual(stage_map["s1_detect"].status, StageStatus.FAILED)
        self.assertIn("exceeded timeout", stage_map["s1_detect"].reason)

    def test_get_s2_estimate_does_not_import_local_s2(self):
        """Verify get_s2_estimate does not import tests.fixtures.local_s2 and resolves pipeline.s2_estimate."""
        mock_local_s2 = unittest.mock.MagicMock()
        with unittest.mock.patch.dict("sys.modules", {"pipeline.s2_estimate": None, "tests.fixtures.local_s2": mock_local_s2}):
            estimator = get_s2_estimate()
            self.assertIsNone(estimator)
            mock_local_s2.assert_not_called()

        # When pipeline.s2_estimate is available
        class MockPipelineS2:
            @staticmethod
            def estimate(iq, fs):
                return DummyS2Estimate()

        with unittest.mock.patch.dict("sys.modules", {"pipeline.s2_estimate": MockPipelineS2}):
            estimator = get_s2_estimate()
            self.assertIsNotNone(estimator)
            self.assertEqual(estimator(None, 200000.0).symbol_rate, 25000.0)

    def test_s2_resolves_to_the_real_pipeline_stage(self):
        """S2 must resolve to pipeline/s2_estimate.py and nothing else.

        This replaces test_s2_fallback_detection, which asserted
        `est.symbol_rate == 25000.0` against a tests/fixtures/local_s2 fallback
        that could never be reached (the primary has existed since 1 Sep) and
        whose field the real S2Result does not even have - it publishes
        symbol_rate_hz. The fallback is gone; this pins that it stays gone,
        because a service silently running a test fixture is worse than one
        that fails.
        """
        try:
            import numpy
            import scipy
        except ImportError:
            self.skipTest("numpy/scipy not installed in host environment")

        estimator = get_s2_estimate()
        self.assertIsNotNone(estimator)
        self.assertTrue(callable(estimator))
        self.assertEqual(estimator.__module__, "pipeline.s2_estimate")

        from pipeline.s2_estimate import S2Result
        field_names = {f.name for f in dataclasses.fields(S2Result)}
        self.assertIn("symbol_rate_hz", field_names)
        self.assertNotIn("symbol_rate", field_names)

    def test_artifact_handling(self):
        overrides = make_clean_overrides()
        report = orchestrate(
            run_id="run-art-01",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        stage_map = {s.stage: s for s in report.stages}
        # S1 should have saved psd plot artifact
        self.assertIn("psd_plot", stage_map["s1_detect"].artifacts)
        # S3 should have saved constellation plot artifact
        self.assertIn("constellation_plot", stage_map["s3_receive"].artifacts)
        # S4 should have saved rank profile artifact
        self.assertIn("rank_profile_plot", stage_map["s4_recover"].artifacts)

    def test_total_timeout_protection(self):
        overrides = make_clean_overrides()

        def delayed_stage(*args, **kwargs):
            time.sleep(0.04)
            return DummyS0Result()

        overrides["s0_ingest"] = lambda p, fs_hint=None: delayed_stage()

        report = orchestrate(
            run_id="run-total-timeout",
            file_path=self.test_file,
            stage_timeout=1.0,
            total_timeout=0.03,  # total timeout triggers during/after S0
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        # Downstream stages should record total timeout
        downstream_reasons = [s.reason for s in report.stages[1:] if s.reason]
        self.assertTrue(any("Total timeout" in r for r in downstream_reasons))

    def test_submit_analysis_job_async(self):
        overrides = make_clean_overrides()
        job = submit_analysis_job(
            run_id="run-async-01",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertEqual(job.run_id, "run-async-01")
        report = job.future.result(timeout=2.0)
        self.assertIsInstance(report, AnalysisReport)
        self.assertEqual(job.status, "completed")
        self.assertEqual(report.envelope_verdict, "in_envelope")

    def test_s2_symbol_rate_hz_integration(self):
        """Verify pipeline execution when S2 returns a result exposing symbol_rate_hz."""
        overrides = make_clean_overrides()
        captured_s2_params = {}

        overrides["s2_estimate"] = lambda iq, fs: RealS2EstimateResult(
            symbol_rate_hz=40000.0, fs=200000.0, cfo_hz=25.0
        )

        def s3_spy(iq, s2_params):
            captured_s2_params.update(s2_params)
            return DummyS3Result()

        overrides["s3_receive"] = s3_spy

        report = orchestrate(
            run_id="run-s2-rate-hz",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertEqual(report.envelope_verdict, "in_envelope")
        s2_stage = next(s for s in report.stages if s.stage == "s2_estimate")
        self.assertEqual(s2_stage.status, StageStatus.OK)
        self.assertEqual(s2_stage.values["symbol_rate"], 40000.0)
        self.assertEqual(s2_stage.values["symbol_rate_hz"], 40000.0)
        self.assertEqual(s2_stage.values["sps"], 5.0)
        self.assertEqual(captured_s2_params.get("symbol_rate"), 40000.0)

    def test_load_plugins_and_error_tracking(self):
        """Verify load_plugins returns errors dict and get_plugin_load_errors is consistent."""
        errors = load_plugins(force=True)
        self.assertIsInstance(errors, dict)
        tracked_errors = get_plugin_load_errors()
        self.assertEqual(errors, tracked_errors)

    def test_required_plugin_modules_covers_every_registering_module(self):
        """Every module that registers a plug-in on import must be in the loader.

        REQUIRED_PLUGIN_MODULES is a hand-maintained tuple, and on 7 Sep it
        silently went stale: the LDPC plug-in moved into pipeline/s5_decode/
        three and a half hours after the tuple was written, so the service came
        up with CODES = {conv, reed-solomon} and the LDPC decode path was dead
        through the API while its own unit tests stayed green. Nothing pointed
        at it, because a missing plug-in looks exactly like a scheme nobody
        tried. Derive the truth from the source instead of trusting the tuple.
        """
        import re

        from service.orchestrator import REQUIRED_PLUGIN_MODULES

        pipeline_root = Path(__file__).resolve().parents[2] / "pipeline"
        registering = set()
        pattern = re.compile(r"^register_(modulation|interleaver|code)\s*\(",
                             re.MULTILINE)
        for path in pipeline_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                rel = path.relative_to(pipeline_root.parent).with_suffix("")
                registering.add(".".join(rel.parts))

        self.assertTrue(registering, "found no registering modules - check the scan")
        covered = set(REQUIRED_PLUGIN_MODULES)
        missing = {
            m for m in registering
            # A module is covered either directly or by its package, whose
            # __init__ imports it (pipeline.s3_receive registers this way).
            if m not in covered and not any(m.startswith(c + ".") for c in covered)
        }
        self.assertEqual(
            missing, set(),
            "these modules register a plug-in on import but the service never "
            f"imports them, so their schemes are invisible to the API: {sorted(missing)}")

    def test_plugin_error_visibility_in_stage_results(self):
        """Verify that S3 and S5 include plugin load failures in reason when stage fails."""
        mock_errors = {"pipeline.s3_receive": "ModuleNotFoundError: No module named 'numpy'"}
        with unittest.mock.patch("service.orchestrator.get_plugin_load_errors", return_value=mock_errors):
            s3_res = adapt_s3(None, 5.0, "run-err-vis")
            self.assertEqual(s3_res.status, StageStatus.FAILED)
            self.assertIn("plugin load failures", s3_res.reason)
            self.assertIn("pipeline.s3_receive", s3_res.reason)
            self.assertIn("numpy", s3_res.reason)

            s5_res = adapt_s5(None, 5.0)
            self.assertEqual(s5_res.status, StageStatus.FAILED)
            self.assertIn("plugin load failures", s5_res.reason)
            self.assertIn("pipeline.s3_receive", s5_res.reason)

    def test_orchestrator_dispatches_to_s3_receive_best(self):
        """Verify S3 dispatch invokes receive_best when no override is supplied, and respects overrides."""
        mock_receive_best = unittest.mock.MagicMock(return_value=DummyS3Result())

        with unittest.mock.patch("service.orchestrator.get_s3_receive", return_value=mock_receive_best):
            overrides = make_clean_overrides()
            overrides.pop("s3_receive", None)
            overrides["s2_estimate"] = lambda iq, fs: DummyS2Estimate(symbol_rate=25000.0, cfo_hz=42.0)

            report = orchestrate(
                run_id="run-s3-receive-best",
                file_path=self.test_file,
                runner=self.runner,
                stage_overrides=overrides,
                db_path=self.db_path,
            )

            mock_receive_best.assert_called_once()
            call_args, call_kwargs = mock_receive_best.call_args
            self.assertEqual(len(call_args), 2)
            self.assertIsNotNone(call_args[0])
            self.assertEqual(call_args[1]["symbol_rate"], 25000.0)
            self.assertEqual(call_args[1]["cfo_hz"], 42.0)
            self.assertNotIn("modulation_hypotheses", call_args[1])
            self.assertNotIn("modulations", call_kwargs)

            s3_stage = next(s for s in report.stages if s.stage == "s3_receive")
            self.assertEqual(s3_stage.status, StageStatus.OK)

        # Verify mod_scheme_hint is forwarded as modulation_hypotheses prior without restricting modulations
        with unittest.mock.patch("service.orchestrator.get_s3_receive", return_value=mock_receive_best):
            mock_receive_best.reset_mock()
            overrides = make_clean_overrides()
            overrides.pop("s3_receive", None)
            report = orchestrate(
                run_id="run-s3-mod-hint",
                file_path=self.test_file,
                mod_scheme_hint="QPSK",
                runner=self.runner,
                stage_overrides=overrides,
                db_path=self.db_path,
            )
            mock_receive_best.assert_called_once()
            call_args, call_kwargs = mock_receive_best.call_args
            self.assertEqual(len(call_args), 2)
            self.assertEqual(call_args[1]["modulation_hypotheses"], [("qpsk", 1.0)])
            self.assertNotIn("modulations", call_kwargs)

        # Verify stage_overrides['s3_receive'] takes precedence over get_s3_receive
        custom_s3_called = False
        def custom_s3(iq, params):
            nonlocal custom_s3_called
            custom_s3_called = True
            return DummyS3Result()

        with unittest.mock.patch("service.orchestrator.get_s3_receive", return_value=mock_receive_best):
            mock_receive_best.reset_mock()
            overrides = make_clean_overrides()
            overrides["s3_receive"] = custom_s3
            report = orchestrate(
                run_id="run-s3-override",
                file_path=self.test_file,
                runner=self.runner,
                stage_overrides=overrides,
                db_path=self.db_path,
            )
            self.assertTrue(custom_s3_called)
            mock_receive_best.assert_not_called()

    def test_orchestrator_dispatches_to_registered_codes(self):
        """Verify orchestrator dynamically routes to code plugins registered in CODES."""
        from registry import CODES, register_code


        class CustomConvCode:
            name = "conv"
            called = False
            def blind_recover(self, llrs):
                return {}
            def decode(self, llrs, code_params):
                CustomConvCode.called = True
                return [0, 1, 0, 1]
            def validate(self, bits):
                return {"valid": True}

        orig_conv = CODES.get("conv")
        register_code(CustomConvCode(), replace=True)

        try:
            overrides = make_clean_overrides()
            overrides.pop("s5_decode", None)
            s4_mock = DummyRecoveryResult()
            s4_mock.interleaver = None
            overrides["s4_recover"] = lambda bits: s4_mock
            report = orchestrate(
                run_id="run-code-dispatch",
                file_path=self.test_file,
                runner=self.runner,
                stage_overrides=overrides,
                db_path=self.db_path,
            )
            self.assertTrue(CustomConvCode.called, "S5 did not dispatch to registered code plugin")
            s5_stage = next(s for s in report.stages if s.stage == "s5_decode")
            self.assertEqual(s5_stage.status, StageStatus.OK)
        finally:
            if orig_conv is not None:
                CODES["conv"] = orig_conv
            else:
                CODES.pop("conv", None)

    def test_get_s3_receive(self):
        """Verify get_s3_receive resolves receive_best or returns None if unavailable."""
        mock_receive_best = unittest.mock.MagicMock()
        mock_module = unittest.mock.MagicMock(receive_best=mock_receive_best)
        with unittest.mock.patch.dict("sys.modules", {"pipeline.s3_receive": mock_module}):
            fn = get_s3_receive()
            self.assertEqual(fn, mock_receive_best)

        with unittest.mock.patch.dict("sys.modules", {"pipeline.s3_receive": None}):
            fn = get_s3_receive()
            self.assertIsNone(fn)

    def test_adapt_s3_envelope_outside_becomes_out_of_envelope(self):
        """Verify adapt_s3 maps values['envelope'] == 'outside' to StageStatus.OUT_OF_ENVELOPE."""
        s3_outside = DummyS3Result(
            status="failed",
            values={"envelope": "outside", "modulation": "qpsk"},
            reason="S2 reports 1.25 samples/symbol; S3 needs at least 2",
        )
        res = adapt_s3(s3_outside, 10.0, "run-s3-outside")
        self.assertEqual(res.status, StageStatus.OUT_OF_ENVELOPE)
        self.assertEqual(res.confidence, 0.0)
        self.assertEqual(res.values["envelope"], "outside")
        self.assertIn("at least 2", res.reason)

        # Inside envelope with failed status remains StageStatus.FAILED
        s3_inside_failed = DummyS3Result(
            status="failed",
            values={"envelope": "inside", "modulation": "qpsk"},
            reason="Demodulation lock failed",
        )
        res_failed = adapt_s3(s3_inside_failed, 10.0, "run-s3-inside-fail")
        self.assertEqual(res_failed.status, StageStatus.FAILED)

    def test_adapt_s1_low_snr_out_of_envelope(self):
        """Verify adapt_s1 marks SNR below -5.0 dB as OUT_OF_ENVELOPE."""
        s1_low = DummyS1Result(status="ok", snr_db=-8.5)
        res = adapt_s1(s1_low, 10.0, "run-s1-low")
        self.assertEqual(res.status, StageStatus.OUT_OF_ENVELOPE)
        self.assertEqual(res.confidence, 0.0)
        self.assertIn("-8.5 dB", res.reason)
        self.assertIn("-5.0 dB", res.reason)

        # Normal SNR >= -5.0 dB remains StageStatus.OK
        s1_ok = DummyS1Result(status="ok", snr_db=12.0)
        res_ok = adapt_s1(s1_ok, 10.0, "run-s1-ok")
        self.assertEqual(res_ok.status, StageStatus.OK)
        self.assertGreater(res_ok.confidence, 0.0)

        # S1 failure without SNR remains StageStatus.FAILED
        s1_fail = DummyS1Result(status="failed", snr_db=None, reason="empty IQ array")
        res_fail = adapt_s1(s1_fail, 10.0, "run-s1-fail")
        self.assertEqual(res_fail.status, StageStatus.FAILED)
        self.assertEqual(res_fail.reason, "empty IQ array")

    def test_adapt_s2_invalid_or_out_of_envelope_sps(self):
        """Verify adapt_s2 marks invalid rate or SPS outside [2.5, 40.0] as OUT_OF_ENVELOPE."""
        # Non-positive rate
        s2_zero = DummyS2Estimate(symbol_rate=0.0)
        res_zero = adapt_s2(s2_zero, 10.0)
        self.assertEqual(res_zero.status, StageStatus.OUT_OF_ENVELOPE)
        self.assertEqual(res_zero.confidence, 0.0)

        # SPS below 2.5 (e.g. symbol_rate = 100000.0, fs = 200000.0 -> sps = 2.0 < 2.5)
        s2_low_sps = DummyS2Estimate(symbol_rate=100000.0, fs=200000.0)
        res_low_sps = adapt_s2(s2_low_sps, 10.0)
        self.assertEqual(res_low_sps.status, StageStatus.OUT_OF_ENVELOPE)
        self.assertEqual(res_low_sps.confidence, 0.0)
        self.assertIn("outside declared operating envelope", res_low_sps.reason)

        # SPS above 40.0 (e.g. symbol_rate = 4000.0, fs = 200000.0 -> sps = 50.0 > 40.0)
        s2_high_sps = DummyS2Estimate(symbol_rate=4000.0, fs=200000.0)
        res_high_sps = adapt_s2(s2_high_sps, 10.0)
        self.assertEqual(res_high_sps.status, StageStatus.OUT_OF_ENVELOPE)
        self.assertEqual(res_high_sps.confidence, 0.0)
        self.assertIn("outside declared operating envelope", res_high_sps.reason)

        # Valid SPS
        s2_valid = DummyS2Estimate(symbol_rate=25000.0, fs=200000.0)
        res_valid = adapt_s2(s2_valid, 10.0)
        self.assertEqual(res_valid.status, StageStatus.OK)
        self.assertGreater(res_valid.confidence, 0.0)

    def test_orchestrator_refuses_downstream_on_s1_out_of_envelope(self):
        """Verify S1 OUT_OF_ENVELOPE stops downstream stages and sets report.envelope_verdict."""
        overrides = make_clean_overrides()
        overrides["s1_detect"] = lambda iq, fs: DummyS1Result(status="ok", snr_db=-10.0)

        s2_called = False
        def mock_s2(iq, fs):
            nonlocal s2_called
            s2_called = True
            return DummyS2Estimate()

        overrides["s2_estimate"] = mock_s2

        report = orchestrate(
            run_id="run-refuse-s1",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertFalse(s2_called, "S2 was executed despite S1 being out of envelope")
        self.assertEqual(report.envelope_verdict, "out_of_envelope")
        self.assertEqual(len(report.stages), 7)
        self.assertEqual(report.stages[0].status, StageStatus.OK)
        self.assertEqual(report.stages[1].status, StageStatus.OUT_OF_ENVELOPE)
        for downstream in report.stages[2:]:
            self.assertEqual(downstream.status, StageStatus.OUT_OF_ENVELOPE)
            self.assertIn("Refused: input out of operating envelope", downstream.reason)

        run_rec = get_run("run-refuse-s1", db_path=self.db_path)
        self.assertEqual(run_rec["envelope_verdict"], "out_of_envelope")
        self.assertEqual(run_rec["status"], "completed")

    def test_orchestrator_refuses_downstream_on_s2_out_of_envelope(self):
        """Verify S2 OUT_OF_ENVELOPE stops downstream stages and sets report.envelope_verdict."""
        overrides = make_clean_overrides()
        overrides["s2_estimate"] = lambda iq, fs: DummyS2Estimate(symbol_rate=2000.0, fs=200000.0)  # sps = 100.0

        s3_called = False
        def mock_s3(iq, params):
            nonlocal s3_called
            s3_called = True
            return DummyS3Result()

        overrides["s3_receive"] = mock_s3

        report = orchestrate(
            run_id="run-refuse-s2",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertFalse(s3_called, "S3 was executed despite S2 being out of envelope")
        self.assertEqual(report.envelope_verdict, "out_of_envelope")
        self.assertEqual(len(report.stages), 7)
        self.assertEqual(report.stages[0].status, StageStatus.OK)
        self.assertEqual(report.stages[1].status, StageStatus.OK)
        self.assertEqual(report.stages[2].status, StageStatus.OUT_OF_ENVELOPE)
        for downstream in report.stages[3:]:
            self.assertEqual(downstream.status, StageStatus.OUT_OF_ENVELOPE)
            self.assertIn("Refused: input out of operating envelope", downstream.reason)

        run_rec = get_run("run-refuse-s2", db_path=self.db_path)
        self.assertEqual(run_rec["envelope_verdict"], "out_of_envelope")
        self.assertEqual(run_rec["status"], "completed")

    def test_orchestrator_refuses_downstream_on_s3_out_of_envelope(self):
        """Verify S3 OUT_OF_ENVELOPE stops downstream stages and sets report.envelope_verdict."""
        overrides = make_clean_overrides()
        overrides["s3_receive"] = lambda iq, params: DummyS3Result(
            status="failed",
            values={"envelope": "outside", "modulation": "qpsk"},
            reason="record too short to settle the timing loop",
        )

        s4_called = False
        def mock_s4(bits):
            nonlocal s4_called
            s4_called = True
            return DummyRecoveryResult()

        overrides["s4_recover"] = mock_s4

        report = orchestrate(
            run_id="run-refuse-s3",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        self.assertFalse(s4_called, "S4 was executed despite S3 being out of envelope")
        self.assertEqual(report.envelope_verdict, "out_of_envelope")
        self.assertEqual(len(report.stages), 7)
        self.assertEqual(report.stages[0].status, StageStatus.OK)
        self.assertEqual(report.stages[1].status, StageStatus.OK)
        self.assertEqual(report.stages[2].status, StageStatus.OK)
        self.assertEqual(report.stages[3].status, StageStatus.OUT_OF_ENVELOPE)
        for downstream in report.stages[4:]:
            self.assertEqual(downstream.status, StageStatus.OUT_OF_ENVELOPE)
            self.assertIn("Refused: input out of operating envelope", downstream.reason)

        run_rec = get_run("run-refuse-s3", db_path=self.db_path)
        self.assertEqual(run_rec["envelope_verdict"], "out_of_envelope")
        self.assertEqual(run_rec["status"], "completed")


    def test_s5_declines_a_deinterleaver_that_destroys_soft_values(self):
        """A family that cannot carry LLRs must stop S5, not be applied to them.

        `ccsds-symbol` works in the Reed-Solomon BYTE domain: `_to_bytes` packs
        bits, so it returns uint8. That is correct where it belongs - after
        Viterbi, in s6_frame/ccsds.py - and destructive at this seam. Measured
        on 4096 float LLRs: 2107 negative in, 0 out, every value collapsed to
        {0, 1}. conv_code.decode then sees dtype uint8 and silently takes its
        HARD path, so without the guard S5 returns a confident decode of noise
        rather than raising - the same false-green class as the adapters.

        Reachable because depth 1 is the IDENTITY permutation, so the family
        clears the functional gate on exactly the streams the direct reading
        clears, and rank_collapse's shortest-span tie-break excludes it only
        while `direct` is non-None.
        """
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed in host environment")

        from pipeline.s4_recover.interleavers import symbol_deinterleave

        # State the premise, so this test explains itself if it ever fails.
        soft = np.linspace(-3.0, 3.0, 4096)
        self.assertEqual(soft.dtype.kind, "f")
        self.assertNotEqual(
            np.asarray(symbol_deinterleave(soft, depth=1, n_bytes=255)).dtype.kind,
            "f",
            "premise broken: symbol_deinterleave now preserves soft values, so "
            "re-examine whether this guard is still the right shape")

        s4 = DummyRecoveryResult()
        s4.interleaver = type("Intl", (), {
            "family": "ccsds-symbol",
            "params": {"depth": 1, "n_bytes": 255}})()

        overrides = make_clean_overrides()
        overrides.pop("s5_decode", None)      # exercise the real S5 path
        overrides["s3_receive"] = lambda iq, params: DummyS3Result(
            llrs=list(np.linspace(-3.0, 3.0, 4096)))
        overrides["s4_recover"] = lambda bits: s4

        report = orchestrate(
            run_id="run-s5-symbol-domain",
            file_path=self.test_file,
            runner=self.runner,
            stage_overrides=overrides,
            db_path=self.db_path,
        )

        s5 = next(s for s in report.stages if s.stage == "s5_decode")
        self.assertNotEqual(
            s5.status, StageStatus.OK,
            "S5 reported ok after de-interleaving with a family that destroyed "
            "the soft information - that is a confident decode of noise")
        self.assertIn("soft", (s5.reason or "").lower())


if __name__ == "__main__":
    unittest.main()
