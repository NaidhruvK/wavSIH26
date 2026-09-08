"""Evaluation harness package for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides benchmarking, comparison against ground truth, and metric scoring
across S0 through S6 pipeline stages.
"""
from __future__ import annotations

from .harness import (
    evaluate_report,
    evaluate_run,
    load_truth_for_file,
)
from .metrics import (
    EvaluationResult,
    MetricResult,
    MetricStatus,
    StageEvaluation,
    eval_s0_ingest,
    eval_s1_detect,
    eval_s2_estimate,
    eval_s3_receive,
    eval_s4_recover,
    eval_s5_decode,
    eval_s6_frame,
)

__all__ = [
    "MetricStatus",
    "MetricResult",
    "StageEvaluation",
    "EvaluationResult",
    "evaluate_report",
    "evaluate_run",
    "load_truth_for_file",
    "eval_s0_ingest",
    "eval_s1_detect",
    "eval_s2_estimate",
    "eval_s3_receive",
    "eval_s4_recover",
    "eval_s5_decode",
    "eval_s6_frame",
]
