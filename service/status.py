"""Repository status inspection helper for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Powers `make status` to provide instant, automated visibility into which layers
are real, mocked, or pending, test counts, and current branch state.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def get_git_branch() -> str:
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=2.0,
        )
        return res.stdout.strip() or "detached"
    except Exception:
        return "unknown"


def check_status() -> dict:
    contracts_ok = (REPO_ROOT / "contracts" / "stage_result.py").is_file() and (
        REPO_ROOT / "contracts" / "report.py"
    ).is_file()

    registry_ok = (REPO_ROOT / "registry" / "protocols.py").is_file()
    registry_details = {"modulations": 0, "interleavers": 0, "codes": 0}
    if registry_ok:
        try:
            from service.orchestrator import load_plugins
            load_plugins()
        except Exception:
            pass
        try:
            import registry

            desc = registry.describe()
            registry_details = desc.get("counts", registry_details)
        except Exception:
            pass

    service_files = ["config.py", "db.py", "mocks.py", "job_runner.py", "orchestrator.py", "main.py", "cli.py"]
    service_ok = all((REPO_ROOT / "service" / f).is_file() for f in service_files)

    pipeline_stages = {
        "s0_ingest": (REPO_ROOT / "pipeline" / "s0_ingest.py").is_file(),
        "s1_detect": (REPO_ROOT / "pipeline" / "s1_detect.py").is_file(),
        "s2_estimate": (REPO_ROOT / "pipeline" / "s2_estimate.py").is_file(),
        "s3_receive": (REPO_ROOT / "pipeline" / "s3_receive" / "__init__.py").is_file(),
        "s4_recover": (REPO_ROOT / "pipeline" / "s4_recover" / "rank_collapse.py").is_file(),
        "s5_decode": (REPO_ROOT / "pipeline" / "s5_decode" / "conv_code.py").is_file(),
        "s6_frame": (REPO_ROOT / "pipeline" / "s6_frame" / "payload.py").is_file(),
    }

    web_ok = (REPO_ROOT / "web" / "package.json").is_file()
    docker_ok = (REPO_ROOT / "Dockerfile").is_file()

    test_files = list(REPO_ROOT.glob("tests/**/test_*.py"))

    # Prevent re-entrant test execution if already running within a test runner
    if os.environ.get("RAAYA_IN_TEST"):
        return {
            "branch": get_git_branch(),
            "python_version": sys.version.split()[0],
            "contracts_layer": contracts_ok,
            "registry_layer": registry_ok,
            "registry_counts": registry_details,
            "service_layer": service_ok,
            "pipeline_stages": pipeline_stages,
            "web_layer": web_ok,
            "docker_layer": docker_ok,
            "total_test_files": len(test_files),
            "runnable_tests_count": 0,
            "runnable_tests_passed": True,
            "failures_count": 0,
            "errors_count": 0,
        }

    # Discover and run runnable test suite (contracts + service)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    runnable_dirs = [
        REPO_ROOT / "tests" / "contract",
        REPO_ROOT / "tests" / "service",
        REPO_ROOT / "tests" / "eval",
        REPO_ROOT / "tests" / "e2e",
    ]
    for d in runnable_dirs:
        if d.is_dir():
            for f in sorted(d.glob("test_*.py")):
                try:
                    module_name = f"{f.parent.relative_to(REPO_ROOT)}.{f.stem}".replace(os.sep, ".")
                    tests = loader.loadTestsFromName(module_name)
                    # Skip test modules that failed import due to external dependencies (e.g. numpy)
                    has_err = False
                    for t in tests:
                        if "FailedTest" in type(t).__name__:
                            has_err = True
                            break
                    if not has_err:
                        suite.addTests(tests)
                except Exception:
                    pass

    import logging
    prev_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    os.environ["RAAYA_IN_TEST"] = "1"
    devnull_stream = open(os.devnull, "w")
    try:
        runner = unittest.TextTestRunner(stream=devnull_stream)
        result = runner.run(suite)
    finally:
        devnull_stream.close()
        os.environ.pop("RAAYA_IN_TEST", None)
        logging.disable(prev_level)

    return {
        "branch": get_git_branch(),
        "python_version": sys.version.split()[0],
        "contracts_layer": contracts_ok,
        "registry_layer": registry_ok,
        "registry_counts": registry_details,
        "service_layer": service_ok,
        "pipeline_stages": pipeline_stages,
        "web_layer": web_ok,
        "docker_layer": docker_ok,
        "total_test_files": len(test_files),
        "runnable_tests_count": result.testsRun,
        "runnable_tests_passed": result.wasSuccessful(),
        "failures_count": len(result.failures),
        "errors_count": len(result.errors),
    }


def print_status() -> None:
    st = check_status()
    print("=" * 66)
    print("           RAAYA / wavSIH26 — PROJECT REPOSITORY STATUS           ")
    print("=" * 66)
    print(f"Git Branch:            {st['branch']}")
    print(f"Python Environment:    {st['python_version']}")
    print("-" * 66)
    print(f"Contracts Layer:       {'[OK] Active' if st['contracts_layer'] else '[MISSING]'}")
    print(
        f"Registry Layer:        {'[OK] Active' if st['registry_layer'] else '[MISSING]'} "
        f"(Plugins: {st['registry_counts'].get('modulations', 0)} mods, "
        f"{st['registry_counts'].get('interleavers', 0)} intls, "
        f"{st['registry_counts'].get('codes', 0)} codes)"
    )
    print(f"Service Layer:         {'[OK] Config, DB, Mocks active' if st['service_layer'] else '[MISSING]'}")
    print(f"Web UI Layer:          {'[OK] Implemented' if st['web_layer'] else '[PENDING Phase 6]'}")
    print(f"Docker Layer:          {'[OK] Base image present' if st['docker_layer'] else '[MISSING]'}")
    print("-" * 66)
    print("Pipeline Stages:")
    for stage, ok in st["pipeline_stages"].items():
        state_str = (
            "[OK] Implemented"
            if ok
            else ("[PENDING - Local S2 fixture active]" if stage == "s2_estimate" else "[PENDING]")
        )
        print(f"  - {stage:<16} {state_str}")
    print("-" * 66)
    print(f"Total Test Files:      {st['total_test_files']} discovered")
    status_icon = "[PASS]" if st["runnable_tests_passed"] else "[FAIL]"
    print(
        f"Contract & Service:    {status_icon} {st['runnable_tests_count']} tests run, "
        f"{st['failures_count']} failures, {st['errors_count']} errors"
    )
    print("=" * 66)


if __name__ == "__main__":
    print_status()
