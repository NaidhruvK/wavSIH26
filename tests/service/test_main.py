"""Tests for service/main.py FastAPI REST API service.

OWNED BY: Naidhruv.
Verifies all REST endpoints:
- GET /health
- GET /registry
- GET /envelope
- POST /analyze (file upload validation, storage, background job submission, HTTP 202)
- GET /runs/{run_id} (retrieval of full AnalysisReport, handling 404 for missing run)
- GET /runs/{run_id}/stage/{stage_num} (retrieval by index 0-6 and name, handling 400/404)
- GET /runs/{run_id}/artifacts/{artifact_name} (artifact delivery, path traversal defense)
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contracts import StageStatus
from service.config import config
from service.db import (
    create_run,
    get_run,
    initialize_database,
    record_stage_result,
    update_run,
)
from service.job_runner import JobRunner
from service.main import TestClient, app


class TestRestAPI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.orig_db_path = config.db_path
        self.orig_upload_dir = config.upload_dir
        self.orig_artifact_dir = config.artifact_dir

        # Isolate database and storage directories for testing
        test_db = self.tmp_path / "test_api.db"
        test_uploads = self.tmp_path / "uploads"
        test_artifacts = self.tmp_path / "artifacts"
        test_uploads.mkdir(parents=True, exist_ok=True)
        test_artifacts.mkdir(parents=True, exist_ok=True)

        object.__setattr__(config, "db_path", test_db)
        object.__setattr__(config, "upload_dir", test_uploads)
        object.__setattr__(config, "artifact_dir", test_artifacts)

        initialize_database(config.db_path)
        self.client = TestClient(app)

    def tearDown(self):
        object.__setattr__(config, "db_path", self.orig_db_path)
        object.__setattr__(config, "upload_dir", self.orig_upload_dir)
        object.__setattr__(config, "artifact_dir", self.orig_artifact_dir)
        try:
            self.tmp_dir.cleanup()
        except OSError:
            pass

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "raaya")
        self.assertIn("timestamp", data)

    def test_registry_endpoint(self):
        resp = self.client.get("/registry")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("counts", data)
        self.assertIn("modulations", data)
        self.assertIn("interleavers", data)
        self.assertIn("codes", data)
        self.assertIsInstance(data["counts"], dict)
        if "errors" not in data:
            # Fully loaded DSP environment.
            #
            # This asserted modulations=6, interleavers=3, codes=2. Those are
            # not invariants - they are a snapshot. interleavers went to 4 when
            # the CCSDS symbol interleaver landed and codes to 3 when the LDPC
            # plug-in did, so the test broke on exactly the event the registry
            # exists to make cheap: adding a scheme in one file and one line.
            # Assert what the API actually promises instead - that every
            # plug-in the pipeline registers is visible through the endpoint,
            # and that the advertised counts match the advertised lists.
            for family in ("modulations", "interleavers", "codes"):
                self.assertEqual(data["counts"][family], len(data[family]),
                                 f"counts[{family}] disagrees with the {family} list")

            names = {f: {e["name"] for e in data[f]}
                     for f in ("modulations", "interleavers", "codes")}
            self.assertLessEqual({"bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"},
                                 names["modulations"])
            self.assertLessEqual({"block", "diagonal", "convolutional"},
                                 names["interleavers"])
            self.assertLessEqual({"conv", "reed-solomon"}, names["codes"])
        else:
            # Lightweight host environment: errors should be surfaced and non-empty
            self.assertIsInstance(data["errors"], dict)
            self.assertGreater(len(data["errors"]), 0)

    def test_registry_dynamic_plugin_registration(self):
        from registry import MODULATIONS, register_modulation

        class MockMod:
            name = "custom_test_mod"
            def demodulate(self, samples, params):
                return []
            def classify_features(self, iq):
                return {}
            def theoretical_cumulants(self):
                return {}

        register_modulation(MockMod())
        try:
            resp = self.client.get("/registry")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            mod_names = [m["name"] for m in data["modulations"]]
            self.assertIn("custom_test_mod", mod_names)
        finally:
            MODULATIONS.pop("custom_test_mod", None)

    def test_envelope_endpoint(self):
        resp = self.client.get("/envelope")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("system"), "Raaya / wavSIH26")
        self.assertIn("stages", data)
        self.assertIn("s0_ingest", data["stages"])
        self.assertIn("s3_receive", data["stages"])
        self.assertIn("s4_recover", data["stages"])
        self.assertIn("timeouts", data)

    def test_analyze_submission_wav(self):
        content = b"RIFF" + b"\x00" * 200
        files = {"file": ("signal_test.wav", content, "audio/wav")}
        data = {"fs_hint": "200000.0"}

        resp = self.client.post("/analyze", data=data, files=files)
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertIn("run_id", body)
        self.assertEqual(body.get("status"), "queued")
        self.assertEqual(body.get("filename"), "signal_test.wav")
        self.assertGreater(body.get("size_bytes", 0), 0)

        # Check that file was safely quarantined in upload_dir
        saved_files = list(config.upload_dir.glob(f"{body['run_id']}_signal_test.wav"))
        self.assertEqual(len(saved_files), 1)
        self.assertEqual(saved_files[0].read_bytes(), content)

    def test_analyze_submission_iq(self):
        content = b"\x01\x02\x03\x04" * 100
        files = {"file": ("raw_stream.iq", content, "application/octet-stream")}

        resp = self.client.post("/analyze", files=files)
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertIn("run_id", body)
        self.assertEqual(body.get("status"), "queued")

    def test_analyze_invalid_extension(self):
        files = {"file": ("malicious.exe", b"MZ...", "application/x-msdownload")}
        resp = self.client.post("/analyze", files=files)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported file format", resp.json().get("detail", ""))

    def test_analyze_empty_file(self):
        files = {"file": ("empty.wav", b"", "audio/wav")}
        resp = self.client.post("/analyze", files=files)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.json().get("detail", "").lower())

    def test_get_run_report_success(self):
        run_id = "run_test_get_01"
        create_run(
            run_id=run_id,
            filename="capture.wav",
            file_size=4096,
            sha256="abc123sha",
            status="completed",
            envelope_verdict="in_envelope",
        )
        record_stage_result(
            run_id=run_id,
            stage="s0_ingest",
            status="ok",
            confidence=1.0,
            elapsed_ms=12.5,
            values={"sample_rate": 200000.0},
        )
        record_stage_result(
            run_id=run_id,
            stage="s6_frame",
            status="ok",
            confidence=0.98,
            elapsed_ms=5.0,
            values={"text": "MISSION LOCK", "printable_fraction": 0.99, "n_bytes": 12},
        )

        resp = self.client.get(f"/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("run_id"), run_id)
        self.assertEqual(data.get("envelope_verdict"), "in_envelope")
        self.assertEqual(len(data.get("stages", [])), 2)
        self.assertEqual(data["final"].get("payload_text"), "MISSION LOCK")
        self.assertEqual(data["file_meta"].get("filename"), "capture.wav")

    def test_get_run_missing(self):
        resp = self.client.get("/runs/non_existent_run_999")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json().get("detail", "").lower())

    def test_get_stage_result_by_number_and_name(self):
        run_id = "run_test_stage_01"
        create_run(run_id=run_id, filename="telemetry.wav", file_size=1024, sha256="sha1")
        record_stage_result(
            run_id=run_id,
            stage="s1_detect",
            status="ok",
            confidence=0.88,
            elapsed_ms=45.0,
            values={"snr_db": 14.5, "occupied_bw_hz": 48000.0},
        )

        # Query by index '1'
        resp1 = self.client.get(f"/runs/{run_id}/stage/1")
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1.get("stage"), "s1_detect")
        self.assertEqual(data1["values"].get("snr_db"), 14.5)

        # Query by name 's1_detect'
        resp2 = self.client.get(f"/runs/{run_id}/stage/s1_detect")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2.get("stage"), "s1_detect")

        # Query by short name 's1'
        resp3 = self.client.get(f"/runs/{run_id}/stage/s1")
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.json().get("stage"), "s1_detect")

    def test_get_stage_result_invalid_and_missing(self):
        run_id = "run_test_stage_02"
        create_run(run_id=run_id, filename="telemetry.wav", file_size=1024, sha256="sha2")

        # Invalid stage number '99'
        resp_inv = self.client.get(f"/runs/{run_id}/stage/99")
        self.assertEqual(resp_inv.status_code, 400)

        # Valid stage identifier but not completed/recorded yet
        resp_miss = self.client.get(f"/runs/{run_id}/stage/3")
        self.assertEqual(resp_miss.status_code, 404)

        # Missing run entirely
        resp_no_run = self.client.get("/runs/unknown_run_xyz/stage/0")
        self.assertEqual(resp_no_run.status_code, 404)

    def test_get_artifact_delivery_and_safety(self):
        run_id = "run_test_art_01"
        run_art_dir = config.artifact_dir / run_id
        run_art_dir.mkdir(parents=True, exist_ok=True)

        artifact_file = run_art_dir / "s1_psd_plot.json"
        artifact_data = {"freqs": [-50000, 0, 50000], "psd_db": [-60.0, -10.0, -60.0]}
        artifact_file.write_text(json.dumps(artifact_data), encoding="utf-8")

        # 1. Successful artifact retrieval with or without .json suffix
        resp1 = self.client.get(f"/runs/{run_id}/artifacts/s1_psd_plot")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json(), artifact_data)

        resp2 = self.client.get(f"/runs/{run_id}/artifacts/s1_psd_plot.json")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json(), artifact_data)

        # 2. Missing artifact
        resp_missing = self.client.get(f"/runs/{run_id}/artifacts/s3_constellation")
        self.assertEqual(resp_missing.status_code, 404)

        # 3. Path traversal defense
        resp_traversal = self.client.get(f"/runs/{run_id}/artifacts/..%2F..%2Fetc%2Fpasswd")
        self.assertIn(resp_traversal.status_code, (400, 403, 404))

        resp_traversal2 = self.client.get(f"/runs/{run_id}/artifacts/../../etc/passwd")
        self.assertIn(resp_traversal2.status_code, (400, 403, 404))

    def test_cors_configuration(self):
        cors_found = False
        if hasattr(app, "user_middleware"):
            for m in app.user_middleware:
                if "CORS" in getattr(m.cls, "__name__", ""):
                    cors_found = True
                    # starlette renamed Middleware.options -> .kwargs; keep both
                    # so this asserts the policy rather than the library version.
                    opts = getattr(m, "kwargs", None)
                    if opts is None:
                        opts = getattr(m, "options", {})
                    self.assertFalse(opts.get("allow_credentials", False))
        elif hasattr(app, "middlewares"):
            for cls, opts in app.middlewares:
                if cls is None or "CORS" in getattr(cls, "__name__", ""):
                    cors_found = True
                    self.assertFalse(opts.get("allow_credentials", False))
        self.assertTrue(cors_found)

    def test_static_files_served_at_root(self):
        dist_index = Path(__file__).resolve().parents[2] / "web" / "dist" / "index.html"
        if dist_index.is_file():
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
