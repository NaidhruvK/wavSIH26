"""Core evaluation harness for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Orchestrates comparison of pipeline AnalysisReport runs against reference truth,
supports corpus discovery, database run evaluation, and machine-readable JSON reports.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional

from contracts import AnalysisReport
from service.config import config
from service.db import get_all_stage_results, get_run

from .metrics import (
    EvaluationResult,
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

STAGE_EVALUATORS = {
    "s0_ingest": eval_s0_ingest,
    "s1_detect": eval_s1_detect,
    "s2_estimate": eval_s2_estimate,
    "s3_receive": eval_s3_receive,
    "s4_recover": eval_s4_recover,
    "s5_decode": eval_s5_decode,
    "s6_frame": eval_s6_frame,
}


def load_truth_for_file(file_path: Path | str) -> Optional[dict[str, Any]]:
    """Discover and parse ground-truth reference data for a given test file."""
    path = Path(file_path)

    # 1. Look for adjacent .json truth file (standard zoo corpus convention)
    adjacent_json = path.with_suffix(".json")
    if adjacent_json.is_file():
        try:
            with open(adjacent_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Look in zoo/corpus/rf/ for matching stem
    zoo_rf_json = config.repo_root / "zoo" / "corpus" / "rf" / f"{path.stem}.json"
    if zoo_rf_json.is_file():
        try:
            with open(zoo_rf_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 3. Look in reports/s3_envelope.csv for pre-calculated reference measurements
    envelope_csv = config.repo_root / "reports" / "s3_envelope.csv"
    if envelope_csv.is_file():
        try:
            with open(envelope_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("file") == path.stem or row.get("file") == path.name:
                        return {
                            "scheme": row.get("modulation"),
                            "snr_db": float(row.get("snr_db", 0)) if row.get("snr_db") else None,
                            "sps": int(row.get("sps", 4)) if row.get("sps") else 4,
                            "status": row.get("status", "ok"),
                            "evm_percent": float(row.get("evm_percent", 0)) if row.get("evm_percent") else None,
                            "injected_ber": float(row.get("measured_ber", 0)) if row.get("measured_ber") else 0.0,
                            "source": "reports/s3_envelope.csv",
                        }
        except Exception:
            pass

    return None


def evaluate_report(
    report: AnalysisReport | dict[str, Any],
    truth: Optional[dict[str, Any]] = None,
    target_file: Optional[str] = None,
) -> EvaluationResult:
    """Evaluate an AnalysisReport against expected ground-truth references."""
    if hasattr(report, "model_dump"):
        report_dict = report.model_dump()
    elif isinstance(report, dict):
        report_dict = report
    else:
        report_dict = dict(report)

    run_id = report_dict.get("run_id", "unknown_run")
    file_meta = report_dict.get("file_meta", {}) or {}
    resolved_file = target_file or file_meta.get("filename", "unknown_file")

    # If truth was not provided, attempt discovery
    resolved_truth = truth
    if resolved_truth is None and resolved_file:
        resolved_truth = load_truth_for_file(resolved_file)

    if resolved_truth is None:
        resolved_truth = {}

    # Extract stages from report
    raw_stages = report_dict.get("stages", [])
    stages_by_name: dict[str, Any] = {}
    for stg in raw_stages:
        stg_name = stg.stage if hasattr(stg, "stage") else (stg.get("stage") if isinstance(stg, dict) else None)
        if stg_name:
            stages_by_name[stg_name] = stg

    stages_eval: dict[str, StageEvaluation] = {}
    unavailable_metrics: list[str] = []

    for stage_name, evaluator in STAGE_EVALUATORS.items():
        if stage_name in stages_by_name:
            stg_eval = evaluator(stages_by_name[stage_name], resolved_truth)
        else:
            # Stage not run in report
            stg_eval = StageEvaluation(
                stage=stage_name,
                status="unavailable",
                score=0.0,
                metrics=[],
            )

        stages_eval[stage_name] = stg_eval
        for m in stg_eval.metrics:
            if m.status == MetricStatus.UNAVAILABLE:
                unavailable_metrics.append(f"{stage_name}.{m.name}")

    # Compute overall score and verdict
    evaluable_stages = [s for s in stages_eval.values() if s.status != "unavailable"]
    if not evaluable_stages:
        overall_verdict = "inconclusive"
        overall_score = 0.0
    else:
        stage_scores = [s.score for s in evaluable_stages]
        overall_score = sum(stage_scores) / len(stage_scores)

        has_any_fail = any(s.status == "fail" for s in evaluable_stages)
        if not has_any_fail and overall_score >= 0.99:
            overall_verdict = "pass"
        elif not has_any_fail or overall_score >= 0.70:
            overall_verdict = "partial"
        else:
            overall_verdict = "fail"

    return EvaluationResult(
        run_id=run_id,
        target_file=resolved_file,
        overall_verdict=overall_verdict,
        overall_score=overall_score,
        stages=stages_eval,
        unavailable_metrics=sorted(list(set(unavailable_metrics))),
    )


def evaluate_run(
    run_id: str,
    truth: Optional[dict[str, Any]] = None,
    db_path: Optional[Path | str] = None,
) -> EvaluationResult:
    """Evaluate an existing historical run from the SQLite database."""
    run_record = get_run(run_id, db_path=db_path)
    if run_record is None:
        raise ValueError(f"Run ID '{run_id}' not found in database")

    stages = get_all_stage_results(run_id, db_path=db_path)
    file_meta = {
        "filename": run_record.get("filename", ""),
        "size_bytes": run_record.get("file_size", 0),
        "sha256": run_record.get("sha256", ""),
    }

    report_dict = {
        "run_id": run_id,
        "file_meta": file_meta,
        "envelope_verdict": run_record.get("envelope_verdict", "pending"),
        "stages": stages,
        "final": {},
    }

    return evaluate_report(
        report=report_dict,
        truth=truth,
        target_file=file_meta["filename"],
    )
