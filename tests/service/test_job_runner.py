"""Tests for service/job_runner.py.

Verifies background job submission, completion, failure capture,
job cancellation, per-stage timeout enforcement, and exception propagation.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import time
import unittest

from service.job_runner import (
    JobCancelledError,
    JobRunner,
    StageTimeoutError,
)


class TestJobRunner(unittest.TestCase):
    def setUp(self):
        # Dedicated runner with small timeouts for fast tests
        self.runner = JobRunner(max_workers=2, stage_timeout=0.2, total_timeout=1.0)

    def tearDown(self):
        self.runner.shutdown(wait=True, cancel_futures=True)

    def test_submit_and_complete_job(self):
        def sample_work(x: int, y: int) -> int:
            return x + y

        job = self.runner.submit_job("run-101", sample_work, 15, 27)
        self.assertEqual(job.run_id, "run-101")

        # Await completion
        res = job.future.result(timeout=1.0)
        self.assertEqual(res, 42)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result, 42)
        self.assertIsNone(job.error)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)
        self.assertTrue(job.is_done)

        # Retrieval check
        fetched = self.runner.get_job("run-101")
        self.assertIs(fetched, job)

    def test_job_failure_captured(self):
        def failing_task():
            raise ValueError("stage estimation corrupted")

        job = self.runner.submit_job("run-102", failing_task)
        with self.assertRaises(ValueError):
            job.future.result(timeout=1.0)

        self.assertEqual(job.status, "failed")
        self.assertIsInstance(job.error, ValueError)
        self.assertEqual(str(job.error), "stage estimation corrupted")
        self.assertTrue(job.is_done)

    def test_job_cancellation(self):
        # Block worker pool with a sleep task so next task stays queued
        def slow_task():
            time.sleep(0.3)

        job1 = self.runner.submit_job("run-slow-1", slow_task)
        job2 = self.runner.submit_job("run-slow-2", slow_task)
        # job3 will be queued
        job3 = self.runner.submit_job("run-cancel-me", slow_task)

        cancelled = self.runner.cancel_job("run-cancel-me")
        self.assertTrue(cancelled)
        self.assertTrue(job3.is_cancelled)
        self.assertTrue(self.runner.is_cancelled("run-cancel-me"))

    def test_stage_timeout_success(self):
        def fast_stage(data: str) -> str:
            return f"processed_{data}"

        result = self.runner.run_stage_with_timeout(fast_stage, "iq_samples", timeout=0.5)
        self.assertEqual(result, "processed_iq_samples")

    def test_stage_timeout_fires(self):
        def runaway_stage():
            # Exceeds configured 0.05s timeout
            time.sleep(0.3)
            return "should_not_reach"

        with self.assertRaises(StageTimeoutError) as ctx:
            self.runner.run_stage_with_timeout(runaway_stage, timeout=0.05)

        self.assertIn("exceeded timeout", str(ctx.exception))

    def test_stage_exception_propagates(self):
        def broken_stage():
            raise ZeroDivisionError("division in matched filter")

        with self.assertRaises(ZeroDivisionError):
            self.runner.run_stage_with_timeout(broken_stage, timeout=0.5)

    def test_stage_aborts_on_cancelled_run(self):
        job = self.runner.submit_job("run-cancelled-check", lambda: time.sleep(0.2))
        self.runner.cancel_job("run-cancelled-check")

        def normal_stage():
            return 123

        with self.assertRaises(JobCancelledError):
            self.runner.run_stage_with_timeout(
                normal_stage, run_id="run-cancelled-check", timeout=0.5
            )

    def test_get_nonexistent_job_returns_none(self):
        self.assertIsNone(self.runner.get_job("does-not-exist"))
        self.assertFalse(self.runner.cancel_job("does-not-exist"))
        self.assertFalse(self.runner.is_cancelled("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
