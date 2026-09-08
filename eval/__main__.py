"""CLI entrypoint for wavSIH26 evaluation harness.

Usage:
    python -m eval --run-id <run_id>
    python -m eval --report <path_to_report.json>
    python -m eval --file <path_to_signal.wav> [--truth <path_to_truth.json>]
    python -m eval --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from service.config import config
from service.orchestrator import orchestrate

from .harness import evaluate_report, evaluate_run, load_truth_for_file


def format_summary_table(res: Any) -> str:
    lines = [
        "=" * 70,
        "             RAAYA / wavSIH26 — PIPELINE EVALUATION REPORT",
        "=" * 70,
        f"Run ID:            {res.run_id}",
        f"Target File:       {res.target_file}",
        f"Evaluated At:      {res.evaluated_at}",
        f"Overall Score:     {res.overall_score * 100:.1f} %",
        f"Overall Verdict:   [{res.overall_verdict.upper()}]",
        "-" * 70,
        f"{'Stage':<15} {'Status':<12} {'Score':<10} {'Metrics (Pass/Total)'}",
        "-" * 70,
    ]

    for stage_name, s_eval in res.stages.items():
        evaluable = [m for m in s_eval.metrics if m.status != "unavailable"]
        passed = [m for m in evaluable if m.status == "pass"]
        metric_str = f"{len(passed)}/{len(evaluable)}" if evaluable else "No ref data"
        status_str = f"[{s_eval.status.upper()}]"
        score_str = f"{s_eval.score * 100:.0f} %" if evaluable else "N/A"
        lines.append(f"{stage_name:<15} {status_str:<12} {score_str:<10} {metric_str}")

    lines.append("-" * 70)
    if res.unavailable_metrics:
        lines.append(f"Unavailable metrics ({len(res.unavailable_metrics)}):")
        for u in res.unavailable_metrics[:10]:
            lines.append(f"  - {u}")
        if len(res.unavailable_metrics) > 10:
            lines.append(f"  - ... and {len(res.unavailable_metrics) - 10} more")
    else:
        lines.append("All reference metrics evaluated.")
    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Raaya automated evaluation harness for S0-S6 pipeline runs."
    )
    parser.add_argument("--run-id", type=str, help="Evaluate existing run from database by run_id")
    parser.add_argument("--report", type=str, help="Evaluate an existing AnalysisReport JSON file")
    parser.add_argument("--file", type=str, help="Run pipeline on input file and evaluate against truth")
    parser.add_argument("--truth", type=str, help="Explicit ground-truth JSON path")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON to stdout")
    parser.add_argument("--db-path", type=str, help="Path to SQLite database")

    args = parser.parse_args()

    truth = None
    if args.truth:
        truth_path = Path(args.truth)
        if not truth_path.is_file():
            sys.stderr.write(f"Error: Truth file not found: {args.truth}\n")
            return 1
        with open(truth_path, "r", encoding="utf-8") as f:
            truth = json.load(f)

    result = None

    if args.run_id:
        try:
            result = evaluate_run(args.run_id, truth=truth, db_path=args.db_path)
        except Exception as exc:
            sys.stderr.write(f"Error evaluating run '{args.run_id}': {exc}\n")
            return 1

    elif args.report:
        report_path = Path(args.report)
        if not report_path.is_file():
            sys.stderr.write(f"Error: Report file not found: {args.report}\n")
            return 1
        with open(report_path, "r", encoding="utf-8") as f:
            rep_data = json.load(f)
        result = evaluate_report(rep_data, truth=truth, target_file=report_path.name)

    elif args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            sys.stderr.write(f"Error: Input file not found: {args.file}\n")
            return 1
        # Run orchestrator
        run_id = f"eval_{file_path.stem}"
        report = orchestrate(run_id=run_id, file_path=file_path, db_path=args.db_path)
        result = evaluate_report(report, truth=truth, target_file=file_path.name)

    else:
        # Default demonstration evaluation against an existing corpus sample if present
        zoo_rf = config.repo_root / "zoo" / "corpus" / "rf"
        sample_json = next(zoo_rf.glob("*.json"), None) if zoo_rf.is_dir() else None
        if sample_json:
            with open(sample_json, "r", encoding="utf-8") as f:
                truth_sample = json.load(f)
            # Create a mock report matching this sample for evaluation demo
            from service.mocks import make_mock_report
            rep = make_mock_report()
            result = evaluate_report(rep, truth=truth_sample, target_file=sample_json.stem)
        else:
            parser.print_help()
            return 0

    if args.json:
        print(result.to_json(indent=2))
    else:
        print(format_summary_table(result))

    return 0 if result.overall_verdict in ("pass", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
