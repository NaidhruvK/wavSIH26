"""Tests for service/db.py.

Verifies SQLite database initialization, runs CRUD, stage results persistence,
multi-stage associations, and JSON round-trips.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from service.db import (
    create_run,
    get_all_stage_results,
    get_run,
    get_stage_result,
    initialize_database,
    record_stage_result,
    update_run,
)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_raaya.db"
        initialize_database(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_initialize_database(self):
        self.assertTrue(self.db_path.exists())
        # running initialize again should be idempotent
        initialize_database(self.db_path)

    def test_create_and_get_run(self):
        run = create_run(
            run_id="run-001",
            filename="capture.wav",
            file_size=1048576,
            sha256="abc123hash",
            status="queued",
            envelope_verdict="pending",
            db_path=self.db_path,
        )
        self.assertIsNotNone(run)
        self.assertEqual(run["run_id"], "run-001")
        self.assertEqual(run["filename"], "capture.wav")
        self.assertEqual(run["file_size"], 1048576)
        self.assertEqual(run["sha256"], "abc123hash")
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["envelope_verdict"], "pending")
        self.assertIsNotNone(run["created_at"])

        fetched = get_run("run-001", db_path=self.db_path)
        self.assertEqual(fetched, run)

    def test_get_nonexistent_run(self):
        self.assertIsNone(get_run("does-not-exist", db_path=self.db_path))

    def test_update_run(self):
        create_run(run_id="run-002", filename="test.wav", db_path=self.db_path)

        updated = update_run(
            run_id="run-002",
            status="running",
            started_at="2026-09-04T22:00:00Z",
            envelope_verdict="in_envelope",
            db_path=self.db_path,
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["started_at"], "2026-09-04T22:00:00Z")
        self.assertEqual(updated["envelope_verdict"], "in_envelope")

        # update completion with error/reason
        finished = update_run(
            run_id="run-002",
            status="completed",
            finished_at="2026-09-04T22:00:10Z",
            error=None,
            db_path=self.db_path,
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["finished_at"], "2026-09-04T22:00:10Z")

    def test_record_and_get_stage_result(self):
        create_run(run_id="run-003", filename="sig.wav", db_path=self.db_path)

        stage_res = record_stage_result(
            run_id="run-003",
            stage="s1_detect",
            status="ok",
            confidence=0.98,
            elapsed_ms=45.2,
            reason=None,
            values={"snr_db": 14.5, "occupied_bw_hz": 50000.0},
            hypotheses=[{"value": "qpsk", "score": 0.95}],
            artifacts={"psd_plot": "reports/psd.png"},
            db_path=self.db_path,
        )

        self.assertEqual(stage_res["run_id"], "run-003")
        self.assertEqual(stage_res["stage"], "s1_detect")
        self.assertEqual(stage_res["status"], "ok")
        self.assertEqual(stage_res["confidence"], 0.98)
        self.assertEqual(stage_res["elapsed_ms"], 45.2)

        # check JSON round-trip
        self.assertEqual(stage_res["values"], {"snr_db": 14.5, "occupied_bw_hz": 50000.0})
        self.assertEqual(stage_res["hypotheses"], [{"value": "qpsk", "score": 0.95}])
        self.assertEqual(stage_res["artifacts"], {"psd_plot": "reports/psd.png"})

        # query individually
        fetched = get_stage_result("run-003", "s1_detect", db_path=self.db_path)
        self.assertEqual(fetched, stage_res)

    def test_multiple_stages_associated_with_run(self):
        create_run(run_id="run-004", filename="multi.wav", db_path=self.db_path)

        record_stage_result(
            run_id="run-004",
            stage="s0_ingest",
            status="ok",
            confidence=1.0,
            values={"fs": 200000.0},
            db_path=self.db_path,
        )
        record_stage_result(
            run_id="run-004",
            stage="s1_detect",
            status="ok",
            confidence=0.95,
            values={"snr_db": 18.0},
            db_path=self.db_path,
        )
        record_stage_result(
            run_id="run-004",
            stage="s2_estimate",
            status="ok",
            confidence=0.92,
            values={"symbol_rate": 25000.0},
            db_path=self.db_path,
        )

        all_stages = get_all_stage_results("run-004", db_path=self.db_path)
        self.assertEqual(len(all_stages), 3)
        self.assertEqual([s["stage"] for s in all_stages], ["s0_ingest", "s1_detect", "s2_estimate"])

    def test_stage_result_update_on_conflict(self):
        create_run(run_id="run-005", filename="conflict.wav", db_path=self.db_path)

        record_stage_result(
            run_id="run-005",
            stage="s2_estimate",
            status="low_confidence",
            confidence=0.5,
            values={"symbol_rate": 20000.0},
            db_path=self.db_path,
        )

        # Update with better estimate
        updated = record_stage_result(
            run_id="run-005",
            stage="s2_estimate",
            status="ok",
            confidence=0.95,
            values={"symbol_rate": 25000.0},
            db_path=self.db_path,
        )
        self.assertEqual(updated["status"], "ok")
        self.assertEqual(updated["confidence"], 0.95)
        self.assertEqual(updated["values"]["symbol_rate"], 25000.0)

        # Still only one record for s2_estimate
        all_stages = get_all_stage_results("run-005", db_path=self.db_path)
        self.assertEqual(len(all_stages), 1)


if __name__ == "__main__":
    unittest.main()
