"""Tests for contracts/stage_result.py and contracts/report.py.

Verifies Pydantic model contracts, field validation, and serialization.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import unittest

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus


class TestStageContract(unittest.TestCase):
    def test_stage_status_values(self):
        self.assertEqual(StageStatus.OK.value, "ok")
        self.assertEqual(StageStatus.LOW_CONFIDENCE.value, "low_confidence")
        self.assertEqual(StageStatus.FAILED.value, "failed")
        self.assertEqual(StageStatus.OUT_OF_ENVELOPE.value, "out_of_envelope")

    def test_hypothesis_creation(self):
        h = Hypothesis(value="qpsk", score=0.95, evidence="spectral peak")
        self.assertEqual(h.value, "qpsk")
        self.assertEqual(h.score, 0.95)
        self.assertEqual(h.evidence, "spectral peak")

        # default evidence
        h2 = Hypothesis(value=123, score=0.5)
        self.assertEqual(h2.evidence, "")

    def test_stage_result_defaults(self):
        res = StageResult(stage="s0_ingest", status=StageStatus.OK, confidence=0.99)
        self.assertEqual(res.stage, "s0_ingest")
        self.assertEqual(res.status, StageStatus.OK)
        self.assertEqual(res.confidence, 0.99)
        self.assertEqual(res.values, {})
        self.assertEqual(res.hypotheses, [])
        self.assertEqual(res.artifacts, {})
        self.assertEqual(res.elapsed_ms, 0.0)
        self.assertIsNone(res.reason)

        d = res.model_dump()
        self.assertEqual(d["stage"], "s0_ingest")
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["confidence"], 0.99)
        self.assertEqual(d["values"], {})
        self.assertEqual(d["hypotheses"], [])
        self.assertEqual(d["artifacts"], {})
        self.assertEqual(d["elapsed_ms"], 0.0)
        self.assertIsNone(d["reason"])

    def test_stage_result_mutable_defaults_isolation(self):
        res1 = StageResult(stage="s1", status=StageStatus.OK, confidence=1.0)
        res2 = StageResult(stage="s2", status=StageStatus.OK, confidence=1.0)

        res1.values["snr"] = 15.0
        res1.hypotheses.append(Hypothesis(value="a", score=1.0))
        res1.artifacts["plot"] = "p.png"

        self.assertEqual(res2.values, {})
        self.assertEqual(res2.hypotheses, [])
        self.assertEqual(res2.artifacts, {})

    def test_stage_result_confidence_bounds(self):
        with self.assertRaises((ValueError, Exception)):
            StageResult(stage="s1", status=StageStatus.OK, confidence=1.5)

        with self.assertRaises((ValueError, Exception)):
            StageResult(stage="s1", status=StageStatus.OK, confidence=-0.1)

    def test_analysis_report_structure(self):
        stage0 = StageResult(
            stage="s0_ingest",
            status=StageStatus.OK,
            confidence=1.0,
            values={"fs": 200000.0, "format": "wav"},
        )
        stage1 = StageResult(
            stage="s1_detect",
            status=StageStatus.OK,
            confidence=0.95,
            values={"snr_db": 12.5},
            hypotheses=[Hypothesis(value="burst", score=0.9)],
        )

        report = AnalysisReport(
            run_id="run-42",
            file_meta={"filename": "test.wav", "size_bytes": 1024},
            envelope_verdict="in_envelope",
            stages=[stage0, stage1],
            final={"payload_text": "HELLO"},
        )

        d = report.model_dump()
        self.assertEqual(d["run_id"], "run-42")
        self.assertEqual(d["file_meta"]["filename"], "test.wav")
        self.assertEqual(d["envelope_verdict"], "in_envelope")
        self.assertEqual(len(d["stages"]), 2)
        self.assertEqual(d["stages"][0]["stage"], "s0_ingest")
        self.assertEqual(d["stages"][1]["stage"], "s1_detect")
        self.assertEqual(d["final"]["payload_text"], "HELLO")


if __name__ == "__main__":
    unittest.main()
