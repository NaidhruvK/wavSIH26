"""Tests for service/mocks.py.

Verifies that mock data validates against the official contracts,
contains all S0-S6 stages, outputs deterministically, and includes hypotheses
and final payload details.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import unittest

from contracts import AnalysisReport, StageResult, StageStatus
from service.mocks import ALL_STAGES, make_mock_report, make_mock_stage_result


class TestMocks(unittest.TestCase):
    def test_mock_report_validates_as_analysis_report(self):
        report = make_mock_report(run_id="test-run-123")
        self.assertIsInstance(report, AnalysisReport)
        self.assertEqual(report.run_id, "test-run-123")
        self.assertEqual(report.envelope_verdict, "in_envelope")
        self.assertIn("filename", report.file_meta)
        self.assertEqual(len(report.stages), 7)
        self.assertIn("payload_text", report.final)
        self.assertTrue(len(report.final["payload_text"]) > 0)

    def test_all_stages_validate_as_stage_result(self):
        expected_stages = [
            "s0_ingest",
            "s1_detect",
            "s2_estimate",
            "s3_receive",
            "s4_recover",
            "s5_decode",
            "s6_frame",
        ]
        self.assertEqual(ALL_STAGES, expected_stages)

        for stage_name in expected_stages:
            stage_res = make_mock_stage_result(stage_name)
            self.assertIsInstance(stage_res, StageResult)
            self.assertEqual(stage_res.stage, stage_name)
            self.assertEqual(stage_res.status, StageStatus.OK)
            self.assertGreaterEqual(stage_res.confidence, 0.0)
            self.assertLessEqual(stage_res.confidence, 1.0)
            self.assertIsInstance(stage_res.values, dict)
            self.assertIsInstance(stage_res.hypotheses, list)
            self.assertIsInstance(stage_res.artifacts, dict)
            self.assertTrue(len(stage_res.hypotheses) > 0)

    def test_unknown_stage_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_mock_stage_result("s9_unknown")

    def test_deterministic_output(self):
        rep1 = make_mock_report("det-run").model_dump()
        rep2 = make_mock_report("det-run").model_dump()
        self.assertEqual(rep1, rep2)

        for stage in ALL_STAGES:
            s1 = make_mock_stage_result(stage).model_dump()
            s2 = make_mock_stage_result(stage).model_dump()
            self.assertEqual(s1, s2)

    def test_hypotheses_and_payload_present(self):
        report = make_mock_report("check-hyp")
        stage_map = {s.stage: s for s in report.stages}

        # S2 should hypothesize QPSK
        s2_hyp_values = [h.value for h in stage_map["s2_estimate"].hypotheses]
        self.assertIn("qpsk", s2_hyp_values)

        # S4 should hypothesize block interleaver
        s4_hyp_values = [h.value for h in stage_map["s4_recover"].hypotheses]
        self.assertIn("block_8x12", s4_hyp_values)

        # S6 should have payload
        self.assertTrue(report.final.get("looks_like_text"))
        self.assertGreaterEqual(report.final.get("printable_fraction", 0.0), 0.85)


if __name__ == "__main__":
    unittest.main()
