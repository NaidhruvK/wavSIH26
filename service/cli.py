"""Command-Line Interface (CLI) for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides CLI subcommands to:
1. `run`: Launch the unified FastAPI web service and Command Center UI with uvicorn.
2. `status`: Check and print current repository, pipeline, contracts, and test status.
3. `analyze <file>`: Execute offline end-to-end signal analysis directly on a WAV or IQ file.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

from service.config import config
from service.orchestrator import orchestrate
from service.status import print_status

logger = logging.getLogger("raaya.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m service.cli",
        description="Raaya (wavSIH26) Command Line Interface",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Start the Raaya REST API and UI service")
    run_parser.add_argument(
        "--host",
        type=str,
        default=config.host,
        help=f"Bind host address (default: {config.host})",
    )
    run_parser.add_argument(
        "--port",
        type=int,
        default=config.port,
        help=f"Bind port number (default: {config.port})",
    )
    run_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn hot reloading for development",
    )

    # Subcommand: status
    subparsers.add_parser("status", help="Display repository implementation and testing status")

    # Subcommand: analyze
    analyze_parser = subparsers.add_parser(
        "analyze", help="Execute offline S0-S6 analysis pipeline on a WAV or IQ file"
    )
    analyze_parser.add_argument("file", type=str, help="Path to input .wav or .iq file")
    analyze_parser.add_argument(
        "--fs",
        type=float,
        default=None,
        help="Sampling rate hint in Hz (optional)",
    )
    analyze_parser.add_argument(
        "--mod",
        type=str,
        default=None,
        help="Modulation scheme hint (e.g. bpsk, qpsk) (optional)",
    )
    analyze_parser.add_argument(
        "--json",
        action="store_true",
        help="Output full AnalysisReport as JSON",
    )

    return parser


def handle_run(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "Error: 'uvicorn' is not installed in the current environment.\n"
            "Install it via: pip install uvicorn\n"
        )
        return 1

    print(f"Starting Raaya Intelligence Service on http://{args.host}:{args.port}")
    uvicorn.run("service.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def handle_status(args: argparse.Namespace) -> int:
    print_status()
    return 0


def handle_analyze(args: argparse.Namespace) -> int:
    target_path = Path(args.file)
    if not target_path.is_file():
        sys.stderr.write(f"Error: Target file '{args.file}' does not exist or is not a file.\n")
        return 1

    run_id = f"cli_{uuid.uuid4().hex[:8]}"
    report = orchestrate(
        run_id=run_id,
        file_path=target_path,
        fs_hint=args.fs,
        mod_scheme_hint=args.mod,
    )

    report_dict = report.model_dump() if hasattr(report, "model_dump") else dict(report)

    if args.json:
        print(json.dumps(report_dict, indent=2))
    else:
        file_meta = report.file_meta if isinstance(report.file_meta, dict) else {}
        filename = file_meta.get("filename", target_path.name)
        size_bytes = file_meta.get("size_bytes", target_path.stat().st_size if target_path.exists() else 0)

        print("=" * 66)
        print("           RAAYA / wavSIH26 — OFFLINE SIGNAL ANALYSIS            ")
        print("=" * 66)
        print(f"Run ID:            {report.run_id}")
        print(f"File:              {filename} ({size_bytes} bytes)")
        print(f"Verdict:           {report.envelope_verdict}")
        print("-" * 66)
        print("Stages:")
        for stage in report.stages:
            status_tag = f"[{stage.status.value.upper()}]"
            details = []
            if stage.values:
                if "snr_db" in stage.values:
                    details.append(f"SNR: {stage.values['snr_db']:.1f} dB")
                if "modulation" in stage.values:
                    details.append(f"Mod: {stage.values['modulation']}")
                if "symbol_rate" in stage.values and stage.values["symbol_rate"]:
                    details.append(f"SymRate: {stage.values['symbol_rate']:.0f}")
                if "sample_rate" in stage.values and stage.values["sample_rate"]:
                    details.append(f"Fs: {stage.values['sample_rate']:.0f} Hz")
                if "evm_percent" in stage.values and stage.values["evm_percent"]:
                    details.append(f"EVM: {stage.values['evm_percent']:.1f}%")
                if "inferred_ber" in stage.values:
                    details.append(f"BER: {stage.values['inferred_ber']:.4f}")
                if "n_bytes" in stage.values:
                    details.append(f"{stage.values['n_bytes']} bytes")
            detail_str = f" - {', '.join(details)}" if details else ""
            if stage.reason:
                detail_str += f" ({stage.reason})"
            print(f"  - {stage.stage:<16} {status_tag:<6} (conf: {stage.confidence:.2f}, {stage.elapsed_ms:.1f}ms){detail_str}")
        print("-" * 66)
        final_dict = report.final if isinstance(report.final, dict) else {}
        payload_text = final_dict.get("payload_text", "")
        if payload_text:
            print(f"Final Decoded Payload:\n  {payload_text}")
        else:
            print("Final Decoded Payload: [None / Demodulation Only]")
        print("=" * 66)

    return 0 if report.envelope_verdict != "failed" else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "run":
        return handle_run(args)
    elif args.command == "status":
        return handle_status(args)
    elif args.command == "analyze":
        return handle_analyze(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
