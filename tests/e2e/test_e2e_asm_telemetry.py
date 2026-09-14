"""The framed-telemetry capture, through the REAL pipeline from its WAV. No stubs.

demo/signals/qpsk_20dB_asm_telemetry.wav carries CCSDS-style frames: the attached
sync marker 1ACFFC1D and a housekeeping body. The claim it supports is that S6
locks the marker and hands back frames - so this asserts the lock, the measured
frame length, and that the payload text is frame bodies rather than a byte run
with markers decoded as glyphs.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from contracts import StageStatus
from service.config import config
from service.orchestrator import load_plugins, orchestrate

REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNAL = REPO_ROOT / "demo" / "signals" / "qpsk_20dB_asm_telemetry.wav"


@unittest.skipUnless(SIGNAL.is_file(), "demo/signals/qpsk_20dB_asm_telemetry.wav not present")
class AsmTelemetryEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_plugins()
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig = config.artifact_dir
        object.__setattr__(config, "artifact_dir", Path(cls._tmp.name) / "artifacts")
        cls.report = orchestrate(str(uuid.uuid4()), SIGNAL,
                                 db_path=Path(cls._tmp.name) / "e2e.db")
        cls.stages = {s.stage: s for s in cls.report.stages}

    @classmethod
    def tearDownClass(cls):
        object.__setattr__(config, "artifact_dir", cls._orig)
        cls._tmp.cleanup()

    def test_all_seven_stages_ok(self):
        for name, stage in self.stages.items():
            self.assertEqual(stage.status, StageStatus.OK, f"{name}: {stage.reason}")

    def test_s6_locks_the_attached_sync_marker(self):
        v = self.stages["s6_frame"].values
        self.assertTrue(v["asm_lock"])
        self.assertGreaterEqual(v["asm_hits"], 2)
        self.assertEqual(v["asm_frame_bits"], 223 * 8)
        self.assertEqual(v["header_hex"], "1ACFFC1D")

    def test_payload_is_frame_bodies(self):
        lines = self.stages["s6_frame"].values["payload_text"].split("\n")
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("HK SEQ="))
        self.assertTrue(lines[1].startswith("HK SEQ="))
        self.assertNotEqual(lines[0][:12], lines[1][:12])     # the counter moves
        self.assertNotIn("�", "\n".join(lines[:-1]))


if __name__ == "__main__":
    unittest.main()
