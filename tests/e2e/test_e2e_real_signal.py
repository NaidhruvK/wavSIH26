"""One end-to-end run of the REAL pipeline on a REAL signal. No stubs.

Why this file exists
--------------------
On 7 Sep the full suite was 791 green while `orchestrate()` could not decode a
single file: S5 raised "'CodeStructure' object is not subscriptable" on every
input where S4 succeeded, and KeyError 'n' on every input where it failed.
Underneath that it never applied the offset and de-interleaver S4 had just
recovered, so even with the types fixed it decoded a still-interleaved stream -
measured 0.2948 re-encode BER against 0.0005 for the same file done correctly.

It stayed invisible because every integration test replaced all seven stages
with dummies (`make_clean_overrides`, `get_deterministic_pipeline`), and not one
test in tests/service or tests/e2e referenced a corpus file. The wiring between
Naidhruv's orchestrator and Nehal's S4/S5 had therefore never executed under
test - only the machinery around it had.

So this test asserts the one thing all of those could not: that a real capture
goes in and real bits come out. It is deliberately a single file and a single
run - it is a smoke test for the seam, not a sweep. The sweeps live in
reports/*_study.py and tests/contract/.
"""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNAL = REPO_ROOT / "zoo" / "corpus" / "rf" / "qpsk_15dB_2010.wav"
TRUTH = SIGNAL.with_suffix(".json")

# The Command Center budgets 90 s per file end to end.
ENVELOPE_BUDGET_S = 90.0


@unittest.skipUnless(
    SIGNAL.is_file() and TRUTH.is_file(),
    f"corpus capture not present ({SIGNAL.relative_to(REPO_ROOT)}); "
    "zoo/corpus is excluded from the container image",
)
class TestEndToEndOnARealCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile

        from service.orchestrator import orchestrate

        cls.truth = json.loads(TRUTH.read_text())
        cls._tmp = tempfile.TemporaryDirectory()
        t0 = time.perf_counter()
        cls.report = orchestrate(
            run_id="e2e-real-signal",
            file_path=SIGNAL,
            db_path=Path(cls._tmp.name) / "e2e_real.db",
        )
        cls.elapsed_s = time.perf_counter() - t0
        cls.stages = {s.stage: s for s in cls.report.stages}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_stage_reports_ok(self):
        from contracts import StageStatus

        for name in ("s0_ingest", "s1_detect", "s2_estimate", "s3_receive",
                     "s4_recover", "s5_decode", "s6_frame"):
            with self.subTest(stage=name):
                stage = self.stages[name]
                self.assertEqual(
                    stage.status, StageStatus.OK,
                    f"{name} is {stage.status} - {stage.reason}")

    def test_the_run_fits_the_90_second_envelope(self):
        self.assertLess(self.elapsed_s, ENVELOPE_BUDGET_S,
                        f"{self.elapsed_s:.1f}s exceeds the {ENVELOPE_BUDGET_S}s budget")
        self.assertEqual(self.report.envelope_verdict, "in_envelope")

    def test_s4_recovers_the_interleaver_and_generators_in_the_truth_file(self):
        values = self.stages["s4_recover"].values
        self.assertEqual(values["period"], self.truth["interleaver"]["period"])
        # The truth file stores the generators in octal notation; S4 reports the
        # same integers it recovered blind.
        self.assertEqual(list(values["generators_octal"]),
                         list(self.truth["code"]["polys_octal"]))

    def test_s5_decode_is_consistent_with_what_arrived(self):
        """The check that distinguishes a decode from confident noise.

        Re-encoding the decoded bits must reproduce the received stream. The
        pre-fix orchestrator scored 0.2948 here; a correct chain scores ~0.0005
        on this capture, whose injected BER is 0.0.
        """
        values = self.stages["s5_decode"].values
        self.assertIsNotNone(values.get("reencode_ber"),
                             "S5 did not run its re-encode check")
        self.assertLess(values["reencode_ber"], 0.01)
        self.assertGreater(values["decoded_bits_count"], 0)

    def test_s5_reports_honestly_that_it_decoded_a_prefix(self):
        """A truncated decode must never look like a complete one."""
        values = self.stages["s5_decode"].values
        self.assertTrue(values["decoded_prefix"])
        self.assertLess(values["coded_bits_decoded"], values["coded_bits_available"])

    def test_s6_frames_the_decoded_bits(self):
        values = self.stages["s6_frame"].values
        self.assertGreater(values["n_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
