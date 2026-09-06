"""End-to-End (E2E) Pipeline and Failure Isolation Tests for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Validates the complete flow:
upload -> FastAPI /analyze -> JobRunner -> orchestrator -> S0->S6 -> SQLite -> artifacts -> /runs/{run_id}

Covers:
1. Successful .wav analysis flow
2. Successful .iq analysis flow
3. Invalid file type rejection
4. Missing run handling
5. S0 ingest failure and downstream abort
6. S2 local fixture fallback
7. Per-stage timeout enforcement
8. Downstream failure isolation
9. Artifact creation and retrieval
10. Artifact path traversal defense
11. Total pipeline timeout budget
12. Malformed / 0-byte / oversized input handling
13. Concurrent analysis job execution
14. Large signal arrays excluded from JSON (JSON purity)
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus
from service.config import AppConfig, config
from service.db import get_all_stage_results, get_run, initialize_database
from service.job_runner import JobRunner, job_runner
from service.main import TestClient, app
from service.orchestrator import (
    DEFAULT_STAGE_OVERRIDES,
    orchestrate,
    submit_analysis_job,
)


# =============================================================================
# Standard-Library File Synthesizers (Zero external numpy/soundfile dependencies)
# =============================================================================

def make_dummy_wav(path: Path | str, duration_sec: float = 0.05, fs: int = 200000) -> None:
    """Create a valid 2-channel 16-bit PCM RIFF WAV using standard library struct."""
    n_samples = max(100, int(duration_sec * fs))
    byte_count = n_samples * 2 * 2  # 2 channels, 2 bytes/sample (16-bit)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + byte_count,
        b"WAVE",
        b"fmt ",
        16,              # Subchunk1Size (16 for PCM)
        1,               # AudioFormat (1 = PCM)
        2,               # NumChannels = 2 (stereo I/Q)
        int(fs),         # SampleRate
        int(fs * 2 * 2), # ByteRate
        4,               # BlockAlign
        16,              # BitsPerSample
        b"data",
        byte_count,
    )
    samples = []
    for i in range(n_samples):
        val_i = int(12000 * (1 if (i % 8 < 4) else -1))
        val_q = int(12000 * (1 if ((i + 2) % 8 < 4) else -1))
        samples.append(struct.pack("<hh", val_i, val_q))

    with open(path, "wb") as f:
        f.write(header)
        f.write(b"".join(samples))


def make_dummy_raw_iq(path: Path | str, n_samples: int = 1000) -> None:
    """Create an interleaved raw float32 IQ file using standard library struct."""
    samples = []
    for i in range(n_samples):
        val_i = 0.707 if (i % 8 < 4) else -0.707
        val_q = 0.707 if ((i + 2) % 8 < 4) else -0.707
        samples.append(struct.pack("<ff", val_i, val_q))
    with open(path, "wb") as f:
        f.write(b"".join(samples))


# =============================================================================
# Deterministic Pipeline Stage Dummies
# =============================================================================

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
    def __init__(self, status="ok", snr_db=15.2, noise_floor_db=-62.4, occupied_bw_hz=50000.0, bursts=None):
        self.status = status
        self.fs = 200000.0
        self.snr_db = snr_db
        self.noise_floor_db = noise_floor_db
        self.occupied_bw_hz = occupied_bw_hz
        self.bursts = bursts or [(0, 100)]
        self.psd_freqs = [-50000.0, -25000.0, 0.0, 25000.0, 50000.0]
        self.psd_db = [-62.4, -45.0, -18.2, -45.0, -62.4]
        self.reason = None


class DummyS2Estimate:
    def __init__(self, symbol_rate=25000.0, fs=200000.0, cfo_hz=50.0, order_hint=4):
        self.symbol_rate = symbol_rate
        self.fs = fs
        self.cfo_hz = cfo_hz
        self.order_hint = order_hint
        self.symbol_rate_score = 9.5
        self.cfo_score = 8.0


class DummyS3Result:
    def __init__(self, status="ok", modulation="qpsk", evm=5.4):
        self.status = status
        self.confidence = 0.95
        self.values = {"modulation": modulation, "evm_percent": evm, "lock_status": "locked"}
        self.hypotheses = [{"value": modulation, "score": 0.95, "evidence": "4-quadrant constellation"}]
        self.reason = None
        self.llrs = [1.5, -2.0, 3.1, -1.8] * 100
        self.symbols = [1.0 + 1.0j, -1.0 + 1.0j, -1.0 - 1.0j, 1.0 - 1.0j] * 50

    def as_stage_result(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "values": self.values,
            "hypotheses": self.hypotheses,
            "reason": self.reason,
        }


class DummyRankProfile:
    def __init__(self, deficiency=None):
        self.deficiency = deficiency or {"8": 0, "16": 0, "48": 12, "96": 36}


class DummyS4Result:
    def __init__(self, status="ok"):
        self.status = status
        self.confidence = 0.99
        self.family = "block"
        self.depth = 8
        self.width = 12
        self.period = 96
        self.code = None
        self.hypotheses = [
            Hypothesis(value="block_8x12", score=0.99, evidence="Rank deficiency 36 at L=96")
        ]
        self.profile = DummyRankProfile()
        self.reason = None


class DummyS5Result:
    def __init__(self, status="ok"):
        self.status = status
        self.confidence = 1.0
        self.values = {"decoder": "viterbi_soft", "decoded_bits_count": 10000, "corrected_errors": 2}
        self.hypotheses = [Hypothesis(value="conv_k7_r12", score=1.0, evidence="Valid trellis")]
        self.bits = [0, 1] * 5000
        self.reason = None

    def __len__(self):
        return len(self.bits)


class DummyS6Result:
    def __init__(self, status="ok"):
        self.status = status
        self.confidence = 1.0
        self.text = "RAAYA_SIH26_TELEMETRY_PACKET_VALID_FRAME_001"
        self.printable_fraction = 0.98
        self.looks_like_text = True
        self.n_bytes = 44
        self.reason = None


def deterministic_s0_handler(file_path: Path | str, fs_hint: float | None = None) -> DummyS0Result:
    p = Path(file_path)
    if not p.exists():
        return DummyS0Result(status="failed", iq=None, reason="File not found")
    with open(p, "rb") as f:
        head = f.read(12)
    if p.suffix.lower() == ".wav":
        if head.startswith(b"RIFF") and len(head) >= 12 and b"WAVE" in head:
            return DummyS0Result(status="ok", fs=fs_hint or 200000.0, source_format="wav")
        return DummyS0Result(status="failed", iq=None, reason="Corrupt or invalid WAV header")
    elif p.suffix.lower() in (".iq", ".bin", ".raw"):
        if p.stat().st_size > 0:
            return DummyS0Result(status="ok", fs=fs_hint or 200000.0, source_format="raw_float32")
        return DummyS0Result(status="failed", iq=None, reason="Empty raw IQ file")
    return DummyS0Result(status="failed", iq=None, reason=f"Unsupported format {p.suffix}")


def get_deterministic_pipeline() -> dict[str, Any]:
    return {
        "s0_ingest": deterministic_s0_handler,
        "s1_detect": lambda *args, **kwargs: DummyS1Result(),
        "s2_estimate": lambda *args, **kwargs: DummyS2Estimate(),
        "s3_receive": lambda *args, **kwargs: DummyS3Result(),
        "s4_recover": lambda *args, **kwargs: DummyS4Result(),
        "s5_decode": lambda *args, **kwargs: DummyS5Result(),
        "s6_frame": lambda *args, **kwargs: DummyS6Result(),
    }


# =============================================================================
# E2E Test Suite
# =============================================================================

class TestE2EPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.orig_db_path = config.db_path
        self.orig_upload_dir = config.upload_dir
        self.orig_artifact_dir = config.artifact_dir
        self.orig_stage_timeout = config.stage_timeout_seconds
        self.orig_total_timeout = config.total_timeout_seconds

        test_db = self.tmp_path / "test_e2e.db"
        test_uploads = self.tmp_path / "uploads"
        test_artifacts = self.tmp_path / "artifacts"
        test_uploads.mkdir(parents=True, exist_ok=True)
        test_artifacts.mkdir(parents=True, exist_ok=True)

        object.__setattr__(config, "db_path", test_db)
        object.__setattr__(config, "upload_dir", test_uploads)
        object.__setattr__(config, "artifact_dir", test_artifacts)

        initialize_database(config.db_path)
        self.client = TestClient(app)

        # Set default stage overrides to deterministic handlers
        DEFAULT_STAGE_OVERRIDES.clear()
        DEFAULT_STAGE_OVERRIDES.update(get_deterministic_pipeline())

    def tearDown(self):
        DEFAULT_STAGE_OVERRIDES.clear()
        object.__setattr__(config, "db_path", self.orig_db_path)
        object.__setattr__(config, "upload_dir", self.orig_upload_dir)
        object.__setattr__(config, "artifact_dir", self.orig_artifact_dir)
        object.__setattr__(config, "stage_timeout_seconds", self.orig_stage_timeout)
        object.__setattr__(config, "total_timeout_seconds", self.orig_total_timeout)
        self.tmp_dir.cleanup()

    def _wait_for_job(self, run_id: str, timeout_sec: float = 6.0) -> dict[str, Any]:
        """Poll GET /runs/{run_id} until terminal state."""
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            resp = self.client.get(f"/runs/{run_id}")
            if resp.status_code == 200:
                data = resp.json()
                st = data.get("status", "").lower()
                verdict = data.get("envelope_verdict", "").lower()
                if st in ("completed", "failed") or verdict in ("in_envelope", "out_of_envelope", "failed"):
                    return data
            time.sleep(0.02)
        self.fail(f"Job {run_id} did not complete within {timeout_sec}s")

    # =========================================================================
    # 1. Successful .wav analysis flow
    # =========================================================================
    def test_e2e_successful_wav_analysis(self):
        wav_path = self.tmp_path / "input_signal.wav"
        make_dummy_wav(wav_path, duration_sec=0.04, fs=200000)

        with open(wav_path, "rb") as f:
            content = f.read()

        files = {"file": ("input_signal.wav", content, "audio/wav")}
        data = {"fs_hint": "200000.0", "mod_scheme_hint": "qpsk"}

        post_resp = self.client.post("/analyze", data=data, files=files)
        self.assertEqual(post_resp.status_code, 202)
        post_body = post_resp.json()
        run_id = post_body["run_id"]
        self.assertEqual(post_body.get("status"), "queued")

        report = self._wait_for_job(run_id)
        self.assertIn(report["status"], ("completed", "failed"))
        self.assertEqual(report["run_id"], run_id)
        self.assertIn("envelope_verdict", report)

        # Verify all 7 stages exist in report
        stages = report.get("stages", [])
        self.assertEqual(len(stages), 7)
        stage_names = [s["stage"] for s in stages]
        self.assertEqual(
            stage_names,
            ["s0_ingest", "s1_detect", "s2_estimate", "s3_receive", "s4_recover", "s5_decode", "s6_frame"],
        )

        # S0 must be OK for a valid WAV
        s0 = stages[0]
        self.assertEqual(s0["status"], "ok")
        self.assertIn(s0["values"].get("source_format"), ("wav", "audio/wav"))

        # Verify SQLite persistence
        db_run = get_run(run_id, db_path=config.db_path)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["run_id"], run_id)
        db_stages = get_all_stage_results(run_id, db_path=config.db_path)
        self.assertEqual(len(db_stages), 7)

    # =========================================================================
    # 2. Successful .iq analysis flow
    # =========================================================================
    def test_e2e_successful_iq_analysis(self):
        iq_path = self.tmp_path / "capture.iq"
        make_dummy_raw_iq(iq_path, n_samples=2000)

        with open(iq_path, "rb") as f:
            content = f.read()

        files = {"file": ("capture.iq", content, "application/octet-stream")}
        data = {"fs_hint": "200000.0"}

        post_resp = self.client.post("/analyze", data=data, files=files)
        self.assertEqual(post_resp.status_code, 202)
        run_id = post_resp.json()["run_id"]

        report = self._wait_for_job(run_id)
        self.assertEqual(report["run_id"], run_id)
        s0 = report["stages"][0]
        self.assertEqual(s0["stage"], "s0_ingest")
        self.assertEqual(s0["status"], "ok")
        self.assertIn("raw", s0["values"].get("source_format", ""))

    # =========================================================================
    # 3. Invalid file type rejection
    # =========================================================================
    def test_e2e_invalid_file_extension_rejection(self):
        files = {"file": ("document.pdf", b"%PDF-1.4...", "application/pdf")}
        resp = self.client.post("/analyze", files=files)
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("Unsupported file format", body.get("detail", ""))

        # Verify no files left in quarantine
        uploads = list(config.upload_dir.glob("*"))
        self.assertEqual(len(uploads), 0)

    # =========================================================================
    # 4. Missing run handling
    # =========================================================================
    def test_e2e_missing_run_handling(self):
        missing_id = "run_nonexistent_99999"
        r1 = self.client.get(f"/runs/{missing_id}")
        self.assertEqual(r1.status_code, 404)

        r2 = self.client.get(f"/runs/{missing_id}/stage/1")
        self.assertEqual(r2.status_code, 404)

        r3 = self.client.get(f"/runs/{missing_id}/artifacts/psd")
        self.assertEqual(r3.status_code, 404)

    # =========================================================================
    # 5. S0 ingest failure and downstream abort
    # =========================================================================
    def test_e2e_s0_ingest_failure_and_downstream_abort(self):
        corrupt_wav = b"RIFF" + b"\x00" * 30  # truncated invalid header
        files = {"file": ("corrupt.wav", corrupt_wav, "audio/wav")}

        post_resp = self.client.post("/analyze", files=files)
        self.assertEqual(post_resp.status_code, 202)
        run_id = post_resp.json()["run_id"]

        report = self._wait_for_job(run_id)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["envelope_verdict"], "failed")

        s0 = report["stages"][0]
        self.assertEqual(s0["status"], "failed")
        self.assertIsNotNone(s0.get("reason"))

        # Downstream stages should be aborted cleanly with explanation
        for downstream in report["stages"][1:]:
            self.assertEqual(downstream["status"], "failed")
            self.assertIn("Aborted due to upstream failure in S0 ingest", downstream.get("reason", ""))

    # =========================================================================
    # 6. S2 local fixture fallback
    # =========================================================================
    def test_e2e_s2_fallback_handling(self):
        wav_path = self.tmp_path / "fallback_signal.wav"
        make_dummy_wav(wav_path, duration_sec=0.03)
        with open(wav_path, "rb") as f:
            content = f.read()

        files = {"file": ("fallback_signal.wav", content, "audio/wav")}

        post_resp = self.client.post("/analyze", files=files)
        run_id = post_resp.json()["run_id"]

        report = self._wait_for_job(run_id)
        s2 = next(s for s in report["stages"] if s["stage"] == "s2_estimate")
        self.assertEqual(s2["status"], "ok")
        self.assertIn("symbol_rate", s2["values"])
        self.assertIn("cfo_hz", s2["values"])

    # =========================================================================
    # 7. Per-stage timeout enforcement
    # =========================================================================
    def test_e2e_stage_timeout_enforcement(self):
        def slow_s1(*args, **kwargs):
            time.sleep(0.15)
            return DummyS1Result()

        wav_path = self.tmp_path / "timeout_signal.wav"
        make_dummy_wav(wav_path, duration_sec=0.02)

        run_id = "run_e2e_timeout_s1"
        submit_analysis_job(
            run_id=run_id,
            file_path=wav_path,
            stage_timeout=0.05,  # 50ms stage timeout
            stage_overrides={"s1_detect": slow_s1},
            db_path=config.db_path,
        )

        report = self._wait_for_job(run_id)
        s1 = next(s for s in report["stages"] if s["stage"] == "s1_detect")
        self.assertEqual(s1["status"], "failed")
        self.assertIn("timeout", s1.get("reason", "").lower())

        # S2 should still execute (isolated failure)
        s2 = next(s for s in report["stages"] if s["stage"] == "s2_estimate")
        self.assertIn(s2["status"], ("ok", "failed"))

    # =========================================================================
    # 8. Downstream stage failure isolation
    # =========================================================================
    def test_e2e_downstream_failure_isolation(self):
        def crashing_s4(*args, **kwargs):
            raise RuntimeError("Corrupted GF(2) parity matrix in rank collapse")

        wav_path = self.tmp_path / "crash_s4.wav"
        make_dummy_wav(wav_path, duration_sec=0.02)

        run_id = "run_e2e_crash_s4"
        submit_analysis_job(
            run_id=run_id,
            file_path=wav_path,
            stage_overrides={"s4_recover": crashing_s4},
            db_path=config.db_path,
        )

        report = self._wait_for_job(run_id)
        s4 = next(s for s in report["stages"] if s["stage"] == "s4_recover")
        self.assertEqual(s4["status"], "failed")
        self.assertIn("Corrupted GF(2) parity matrix", s4.get("reason", ""))

        # Report was still assembled and saved without crashing the process
        self.assertEqual(report["run_id"], run_id)
        db_run = get_run(run_id, db_path=config.db_path)
        self.assertIsNotNone(db_run)

    # =========================================================================
    # 9. Artifact creation and retrieval
    # =========================================================================
    def test_e2e_artifact_creation_and_retrieval(self):
        wav_path = self.tmp_path / "artifacts_signal.wav"
        make_dummy_wav(wav_path, duration_sec=0.04)

        with open(wav_path, "rb") as f:
            content = f.read()

        files = {"file": ("artifacts_signal.wav", content, "audio/wav")}
        post_resp = self.client.post("/analyze", files=files)
        run_id = post_resp.json()["run_id"]

        report = self._wait_for_job(run_id)

        # Verify S1 created psd artifact
        psd_resp = self.client.get(f"/runs/{run_id}/artifacts/psd")
        self.assertEqual(psd_resp.status_code, 200)
        psd_data = psd_resp.json()
        self.assertIn("freqs", psd_data)
        self.assertIn("psd_db", psd_data)

        # Verify S3 created constellation artifact
        c_resp = self.client.get(f"/runs/{run_id}/artifacts/constellation")
        self.assertEqual(c_resp.status_code, 200)
        c_data = c_resp.json()
        self.assertIsInstance(c_data, list)
        self.assertGreater(len(c_data), 0)

        # Verify S4 created rank_profile artifact
        rp_resp = self.client.get(f"/runs/{run_id}/artifacts/rank_profile")
        self.assertEqual(rp_resp.status_code, 200)
        rp_data = rp_resp.json()
        self.assertIn("96", rp_data)

    # =========================================================================
    # 10. Artifact path traversal defense
    # =========================================================================
    def test_e2e_artifact_path_traversal_defense(self):
        run_id = "run_traversal_test"
        bad_paths = [
            "../etc/passwd",
            "..%2F..%2Fservice%2Fconfig.py",
            "/absolute/root/file",
            "....//malicious",
        ]
        for bp in bad_paths:
            resp = self.client.get(f"/runs/{run_id}/artifacts/{bp}")
            self.assertIn(resp.status_code, (400, 403, 404))

    # =========================================================================
    # 11. Total pipeline timeout budget
    # =========================================================================
    def test_e2e_total_pipeline_timeout(self):
        def slow_stage(*args, **kwargs):
            time.sleep(0.04)
            return DummyS1Result()

        wav_path = self.tmp_path / "total_timeout.wav"
        make_dummy_wav(wav_path, duration_sec=0.02)

        run_id = "run_e2e_total_budget"
        submit_analysis_job(
            run_id=run_id,
            file_path=wav_path,
            total_timeout=0.03,  # 30ms total budget
            stage_overrides={
                "s1_detect": slow_stage,
                "s2_estimate": slow_stage,
            },
            db_path=config.db_path,
        )

        report = self._wait_for_job(run_id)
        # Verify subsequent stages were flagged with total timeout exceeded
        timed_out_stages = [
            s for s in report["stages"]
            if s.get("reason") and "Total timeout of 0.03s exceeded" in s["reason"]
        ]
        self.assertGreater(len(timed_out_stages), 0)

    # =========================================================================
    # 12. Malformed, 0-byte, and oversized input handling
    # =========================================================================
    def test_e2e_malformed_and_oversized_input(self):
        # 0-byte file
        files = {"file": ("empty.wav", b"", "audio/wav")}
        r1 = self.client.post("/analyze", files=files)
        self.assertEqual(r1.status_code, 400)
        self.assertIn("empty", r1.json().get("detail", "").lower())

        # Exceeds max upload limit (temporarily set max to 500 bytes)
        orig_max = config.max_upload_size_bytes
        try:
            object.__setattr__(config, "max_upload_size_bytes", 500)
            oversized = b"RIFF" + b"\x00" * 1000
            files_over = {"file": ("large.wav", oversized, "audio/wav")}
            r2 = self.client.post("/analyze", files=files_over)
            self.assertEqual(r2.status_code, 413)
        finally:
            object.__setattr__(config, "max_upload_size_bytes", orig_max)

    # =========================================================================
    # 13. Concurrent analysis jobs
    # =========================================================================
    def test_e2e_concurrent_analysis_jobs(self):
        wav_path = self.tmp_path / "concurrent_signal.wav"
        make_dummy_wav(wav_path, duration_sec=0.02)
        with open(wav_path, "rb") as f:
            content = f.read()

        run_ids = []
        for i in range(4):
            files = {"file": (f"signal_{i}.wav", content, "audio/wav")}
            resp = self.client.post("/analyze", files=files)
            self.assertEqual(resp.status_code, 202)
            run_ids.append(resp.json()["run_id"])

        self.assertEqual(len(set(run_ids)), 4)

        # Await all 4 jobs
        reports = [self._wait_for_job(rid) for rid in run_ids]
        for rep in reports:
            self.assertIn(rep["status"], ("completed", "failed"))
            self.assertEqual(len(rep["stages"]), 7)

        # Verify all 4 are persisted in SQLite without concurrency errors
        for rid in run_ids:
            r = get_run(rid, db_path=config.db_path)
            self.assertIsNotNone(r)

    # =========================================================================
    # 14. Large signal arrays excluded from JSON (JSON purity)
    # =========================================================================
    def test_e2e_large_signal_arrays_excluded_from_json(self):
        wav_path = self.tmp_path / "json_purity.wav"
        make_dummy_wav(wav_path, duration_sec=0.04)
        with open(wav_path, "rb") as f:
            content = f.read()

        files = {"file": ("json_purity.wav", content, "audio/wav")}
        post_resp = self.client.post("/analyze", files=files)
        run_id = post_resp.json()["run_id"]

        report = self._wait_for_job(run_id)
        json_str = json.dumps(report)

        # Raw IQ arrays and symbol buffers must NEVER be serialized inside report
        self.assertNotIn("iq_samples", json_str)
        self.assertNotIn("raw_iq", json_str)

        # S0 values should only contain metadata, not sample buffers
        s0_vals = report["stages"][0]["values"]
        self.assertNotIn("iq", s0_vals)
        self.assertIn("sample_count", s0_vals)


if __name__ == "__main__":
    unittest.main()
