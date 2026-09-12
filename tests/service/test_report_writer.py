"""Tests for service/report_writer.py.

Covers the two files a run now leaves on disk - report.json and report.md -
their content, and the promise that a report which cannot be written never
fails an analysis that already succeeded.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus
from service.report_writer import (
    MD_PAYLOAD_CHARS,
    MD_STAGE_VALUE_CHARS,
    report_to_dict,
    report_to_markdown,
    save_report,
)


def make_report(**kw) -> AnalysisReport:
    defaults = dict(
        run_id="run-1",
        file_meta={"filename": "qpsk_20dB_2011.wav", "size_bytes": 1280044,
                   "sha256": "abc123"},
        envelope_verdict="in_envelope",
        stages=[
            StageResult(stage="s0_ingest", status=StageStatus.OK, confidence=1.0,
                        values={"fs": 200000.0}, elapsed_ms=12.0),
            StageResult(stage="s4_recover", status=StageStatus.OK, confidence=0.95,
                        values={"period": 96, "depth": 8, "width": 12},
                        hypotheses=[Hypothesis(value="block(8,12)", score=0.95),
                                    Hypothesis(value="block(12,8)", score=0.41,
                                               evidence="lower rank deficiency")],
                        artifacts={"rank_profile_plot": "reports/artifacts/run-1/rank_profile.json"},
                        elapsed_ms=4630.0),
        ],
        final={"payload_text": "RAAYA SIH26147", "printable_fraction": 1.0,
               "looks_like_text": True, "bits_count": 11994, "entropy": 4.2},
    )
    defaults.update(kw)
    return AnalysisReport(**defaults)


class TestSaveReport(unittest.TestCase):
    def test_both_files_land_in_the_run_directory(self):
        with tempfile.TemporaryDirectory() as td:
            written = save_report("run-1", make_report(), artifact_dir=td)

            self.assertEqual(set(written), {"report_json", "report_md"})
            run_dir = Path(td) / "run-1"
            self.assertTrue((run_dir / "report.json").is_file())
            self.assertTrue((run_dir / "report.md").is_file())

    def test_json_round_trips_and_keeps_every_field(self):
        with tempfile.TemporaryDirectory() as td:
            save_report("run-1", make_report(), artifact_dir=td)
            data = json.loads((Path(td) / "run-1" / "report.json").read_text(encoding="utf-8"))

            self.assertEqual(data["run_id"], "run-1")
            self.assertEqual(data["envelope_verdict"], "in_envelope")
            self.assertEqual(data["file_meta"]["sha256"], "abc123")
            self.assertEqual(len(data["stages"]), 2)
            self.assertEqual(data["stages"][1]["values"]["period"], 96)
            self.assertEqual(data["final"]["bits_count"], 11994)
            self.assertIn("generated_at", data)

    def test_stage_status_is_written_as_a_string_not_an_enum_repr(self):
        # StageStatus is a str Enum; a naive dump can still write
        # "StageStatus.OK", which no other reader would understand.
        with tempfile.TemporaryDirectory() as td:
            save_report("run-1", make_report(), artifact_dir=td)
            raw = (Path(td) / "run-1" / "report.json").read_text(encoding="utf-8")

            self.assertIn('"ok"', raw)
            self.assertNotIn("StageStatus", raw)

    def test_a_non_finite_value_does_not_produce_invalid_json(self):
        # json.dump writes bare NaN by default, which is valid to Python and to
        # nothing else. The writer converts it before it reaches the file.
        rep = make_report(final={"payload_text": "", "printable_fraction": float("nan"),
                                 "looks_like_text": False, "bits_count": 0,
                                 "entropy": float("inf")})
        with tempfile.TemporaryDirectory() as td:
            written = save_report("run-1", rep, artifact_dir=td)
            self.assertIn("report_json", written)

            raw = (Path(td) / "run-1" / "report.json").read_text(encoding="utf-8")
            self.assertNotIn("NaN", raw)
            self.assertNotIn("Infinity", raw)
            data = json.loads(raw)
            self.assertIsNone(data["final"]["printable_fraction"])

    def test_an_unwritable_directory_returns_empty_and_does_not_raise(self):
        with unittest.mock.patch("service.report_writer.Path.mkdir",
                                 side_effect=OSError("read-only")):
            written = save_report("run-1", make_report(), artifact_dir="/nowhere")
        self.assertEqual(written, {})


class TestMarkdown(unittest.TestCase):
    def render(self, rep) -> str:
        return report_to_markdown(report_to_dict(rep))

    def test_it_leads_with_the_capture_verdict_and_stage_count(self):
        md = self.render(make_report())

        self.assertIn("# Raaya analysis - qpsk_20dB_2011.wav", md)
        self.assertIn("`in_envelope`", md)
        self.assertIn("**Stages ok** 2/2", md)

    def test_recovered_values_and_ranked_hypotheses_are_both_shown(self):
        md = self.render(make_report())

        self.assertIn("**period**: 96", md)
        self.assertIn("block(12,8)", md)
        self.assertIn("lower rank deficiency", md)

    def test_status_renders_as_ok_not_as_a_python_enum_repr(self):
        # StageStatus subclasses str, so json.dump writes "ok" while str() on the
        # member writes "StageStatus.OK". The JSON test alone did not catch this.
        md = self.render(make_report())

        self.assertNotIn("StageStatus", md)
        self.assertIn("| `s0_ingest` | ok |", md.replace(" | 1 | 12 ms |", " |"))

    def test_generator_polynomials_read_as_octal(self):
        # The stage carries them as ints. 0o171 printed with str() is 121,
        # which matches nothing else in this project or any reference table.
        rep = make_report(stages=[
            StageResult(stage="s4_recover", status=StageStatus.OK, confidence=0.95,
                        values={"generators_octal": [121, 91], "K": 7})])
        md = self.render(rep)

        self.assertIn("0o171, 0o133", md)
        self.assertNotIn("121, 91", md)

    def test_a_long_stage_value_is_trimmed_and_points_at_the_json(self):
        # S6 reports the message under both `text` and `payload_text`; dumped
        # raw, the stage section prints it twice before Payload prints it again.
        rep = make_report(stages=[
            StageResult(stage="s6_frame", status=StageStatus.OK, confidence=1.0,
                        values={"text": "B" * 900, "payload_text": "B" * 900})])
        md = self.render(rep)

        self.assertNotIn("B" * (MD_STAGE_VALUE_CHARS + 1), md)
        self.assertIn("(900 characters, in full in report.json)", md)

    def test_recovered_text_is_quoted(self):
        md = self.render(make_report())

        self.assertIn("```text", md)
        self.assertIn("RAAYA SIH26147", md)

    def test_a_long_payload_is_truncated_and_says_so(self):
        rep = make_report(final={"payload_text": "A" * 5000, "printable_fraction": 1.0,
                                 "looks_like_text": True, "bits_count": 40000})
        md = self.render(rep)

        self.assertIn("A" * MD_PAYLOAD_CHARS, md)
        self.assertNotIn("A" * (MD_PAYLOAD_CHARS + 1), md)
        self.assertIn("of 5000 characters", md)

    def test_a_binary_payload_reads_as_a_correct_answer_not_a_failure(self):
        rep = make_report(final={"payload_text": "", "printable_fraction": 0.38,
                                 "looks_like_text": False, "bits_count": 11994})
        md = self.render(rep)

        self.assertIn("correct answer", md)
        self.assertIn("38", md)

    def test_a_refused_capture_records_the_reason_in_the_file(self):
        # The whole point of writing on the early-return paths: the reason a
        # capture was declined is the thing worth keeping.
        rep = make_report(
            envelope_verdict="out_of_envelope",
            stages=[StageResult(stage="s4_recover", status=StageStatus.FAILED,
                                confidence=0.0,
                                reason="no rank collapse at any period from 8 to 369")],
            final={})
        md = self.render(rep)

        self.assertIn("`out_of_envelope`", md)
        self.assertIn("no rank collapse at any period from 8 to 369", md)
        self.assertIn("**Stages ok** 0/1", md)


if __name__ == "__main__":
    unittest.main()
