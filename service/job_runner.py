"""Background job runner and per-stage timeout execution for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides ThreadPoolExecutor-based background job execution, cancellation tracking,
and per-stage timeout enforcement to prevent unbounded sweep DoS.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

from .config import config

T = TypeVar("T")


class StageTimeoutError(TimeoutError):
    """Raised when a single pipeline stage exceeds its configured execution timeout."""
    pass


class JobCancelledError(Exception):
    """Raised when an operation is rejected because the associated job was cancelled."""
    pass


@dataclass
class Job:
    """Represents a submitted background analysis task."""

    run_id: str
    future: Optional[Future[Any]] = None
    status: str = "queued"  # queued | running | completed | failed | cancelled
    cancel_requested: bool = False
    result: Any = None
    error: Optional[Exception] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def cancel(self) -> bool:
        """Attempt to cancel this job."""
        self.cancel_requested = True
        if self.future and not self.future.running():
            cancelled = self.future.cancel()
            if cancelled:
                self.status = "cancelled"
                self.finished_at = time.time()
                return True
        if self.status == "queued":
            self.status = "cancelled"
            self.finished_at = time.time()
            return True
        return False

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_requested or self.status == "cancelled"

    @property
    def is_done(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class JobRunner:
    """Manages thread pools for background jobs and stage-level timeout isolation."""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        stage_timeout: Optional[float] = None,
        total_timeout: Optional[float] = None,
    ) -> None:
        self.max_workers = max_workers or config.max_workers
        self.stage_timeout = (
            stage_timeout if stage_timeout is not None else config.stage_timeout_seconds
        )
        self.total_timeout = (
            total_timeout if total_timeout is not None else config.total_timeout_seconds
        )

        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

        # Worker pool for top-level analysis runs
        self._job_executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="raaya-job"
        )
        # Dedicated worker pool for isolated per-stage executions with timeouts
        self._stage_executor = ThreadPoolExecutor(
            max_workers=max(self.max_workers * 2, 4), thread_name_prefix="raaya-stage"
        )
        self._shutdown = False

    def submit_job(
        self, run_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Job:
        """Submit an analysis job to run in the background."""
        with self._lock:
            if self._shutdown:
                raise RuntimeError("JobRunner has been shut down")

            job = Job(run_id=run_id, status="queued")
            self._jobs[run_id] = job

            def _job_wrapper() -> Any:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.finished_at = time.time()
                    return None

                job.status = "running"
                job.started_at = time.time()
                try:
                    res = fn(*args, **kwargs)
                    if job.cancel_requested:
                        job.status = "cancelled"
                    else:
                        job.status = "completed"
                        job.result = res
                    return res
                except Exception as exc:
                    job.error = exc
                    if job.cancel_requested:
                        job.status = "cancelled"
                    else:
                        job.status = "failed"
                    raise
                finally:
                    job.finished_at = time.time()

            job.future = self._job_executor.submit(_job_wrapper)
            return job

    def get_job(self, run_id: str) -> Optional[Job]:
        """Retrieve tracking object for a given run_id."""
        with self._lock:
            return self._jobs.get(run_id)

    def cancel_job(self, run_id: str) -> bool:
        """Request cancellation of a job."""
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return False
            return job.cancel()

    def is_cancelled(self, run_id: str) -> bool:
        """Check whether cancellation was requested for run_id."""
        with self._lock:
            job = self._jobs.get(run_id)
            return job.is_cancelled if job else False

    def run_stage_with_timeout(
        self,
        fn: Callable[..., T],
        *args: Any,
        timeout: Optional[float] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """Execute a stage function with wall-clock timeout and cancellation checks."""
        if run_id and self.is_cancelled(run_id):
            raise JobCancelledError(f"Run {run_id} was cancelled before stage execution")

        timeout_sec = timeout if timeout is not None else self.stage_timeout

        future = self._stage_executor.submit(fn, *args, **kwargs)
        try:
            result = future.result(timeout=timeout_sec)
        except FutureTimeoutError as exc:
            future.cancel()
            raise StageTimeoutError(
                f"Stage execution exceeded timeout of {timeout_sec:.1f}s"
            ) from exc
        except Exception:
            raise

        if run_id and self.is_cancelled(run_id):
            raise JobCancelledError(f"Run {run_id} was cancelled during stage execution")

        return result

    def shutdown(self, wait: bool = True, cancel_futures: bool = True) -> None:
        """Shut down the background executors cleanly."""
        with self._lock:
            self._shutdown = True
            for job in self._jobs.values():
                job.cancel()

        self._job_executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        self._stage_executor.shutdown(wait=wait, cancel_futures=cancel_futures)


# Default singleton instance
job_runner = JobRunner()

# Convenience module-level wrappers
submit_job = job_runner.submit_job
get_job = job_runner.get_job
cancel_job = job_runner.cancel_job
run_stage_with_timeout = job_runner.run_stage_with_timeout
