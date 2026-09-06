"""Service layer for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides centralized configuration, SQLite persistence, job orchestration, and mock data.
"""
from __future__ import annotations

from .config import AppConfig, config
from .db import (
    create_run,
    get_all_stage_results,
    get_run,
    get_stage_result,
    initialize_database,
    record_stage_result,
    update_run,
)
from .job_runner import (
    Job,
    JobCancelledError,
    JobRunner,
    StageTimeoutError,
    cancel_job,
    get_job,
    job_runner,
    run_stage_with_timeout,
    submit_job,
)
from .mocks import make_mock_report, make_mock_stage_result

__all__ = [
    "AppConfig",
    "config",
    "initialize_database",
    "create_run",
    "update_run",
    "get_run",
    "record_stage_result",
    "get_stage_result",
    "get_all_stage_results",
    "Job",
    "JobRunner",
    "job_runner",
    "StageTimeoutError",
    "JobCancelledError",
    "submit_job",
    "get_job",
    "cancel_job",
    "run_stage_with_timeout",
    "make_mock_report",
    "make_mock_stage_result",
]
