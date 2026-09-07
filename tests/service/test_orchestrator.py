"""Tests for service/orchestrator.py.

Verifies end-to-end S0->S6 pipeline execution, native return type adaptation,
failure isolation, per-stage and total timeout enforcement, S2 fallback,
artifact handling, and asynchronous job submission.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

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
    def __init__(self, status="ok", snr_db=15.0, noise_floor_db=-60.0, occupied_bw_hz=50000.0, bursts=None):
        self.status = status
        self.fs = 200000.0
        self.snr_db = snr_db
        self.noise_floor_db = noise_floor_db
        self.occupied_bw_hz = occupied_bw_hz
        self.bursts = bursts or [(0, 100)]
        self.psd_freqs = [-50000.0, 0.0, 50000.0]
        self.psd_db = [-60.0, -20.0, -60.0]
        self.reason = None


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
    def __init__(self, status="ok", llrs=None):
        self.status = status
        self.confidence = 0.95
        self.values = {"modulation": "qpsk", "evm_percent": 5.2}
        self.hypotheses = [{"value": "qpsk", "score": 0.95, "evidence": "tight clusters"}]
        self.reason = None
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

        # S2 (local_s2 fallback with symbol_rate)
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

    def test_s2_fallback_detection(self):
        class MockLocalS2:
            @staticmethod
            def estimate_blind(iq, fs):
                return DummyS2Estimate()

        with unittest.mock.patch.dict("sys.modules", {"tests.fixtures.local_s2": MockLocalS2}):
            estimator = get_s2_estimate()
            self.assertIsNotNone(estimator)
            self.assertTrue(callable(estimator))
            est = estimator(None, 200000.0)
            self.assertEqual(est.symbol_rate, 25000.0)

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

    def test_orchestrator_dispatches_to_registered_plugins(self):
        """Verify orchestrator dynamically routes to plugins registered in MODULATIONS and CODES."""
        from registry import CODES, MODULATIONS, register_code, register_modulation

        class CustomMod:
            name = "custom_test_scheme"
            called = False
            def demodulate(self, samples, params):
                CustomMod.called = True
                return [1.0, -1.0, 1.0, -1.0]
            def classify_features(self, iq):
                return {}
            def theoretical_cumulants(self):
                return {}

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
        register_modulation(CustomMod(), replace=True)
        register_code(CustomConvCode(), replace=True)

        try:
            overrides = make_clean_overrides()
            # Remove s3_receive and s5_decode from overrides so orchestrator falls back to registry
            overrides.pop("s3_receive", None)
            overrides.pop("s5_decode", None)
            # S2 suggests custom_test_scheme
            overrides["s2_estimate"] = lambda iq, fs: DummyS2Estimate()
            s2_orig = overrides["s2_estimate"]
            def s2_with_hyp(iq, fs):
                res = s2_orig(iq, fs)
                return res
            # S0/S1/S2/S4/S6 present
            report = orchestrate(
                run_id="run-plugin-dispatch",
                file_path=self.test_file,
                mod_scheme_hint="custom_test_scheme",
                runner=self.runner,
                stage_overrides=overrides,
                db_path=self.db_path,
            )
            self.assertTrue(CustomMod.called, "S3 did not dispatch to registered modulation plugin")
            self.assertTrue(CustomConvCode.called, "S5 did not dispatch to registered code plugin")
            s3_stage = next(s for s in report.stages if s.stage == "s3_receive")
            s5_stage = next(s for s in report.stages if s.stage == "s5_decode")
            self.assertEqual(s3_stage.status, StageStatus.OK)
            self.assertEqual(s5_stage.status, StageStatus.OK)
        finally:
            MODULATIONS.pop("custom_test_scheme", None)
            if orig_conv is not None:
                CODES["conv"] = orig_conv
            else:
                CODES.pop("conv", None)


if __name__ == "__main__":
    unittest.main()
