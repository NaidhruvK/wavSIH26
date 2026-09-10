"""Raaya SIH26147 - the demo gate, runnable in front of a judge.

Eight captures, blind, through the real seven-stage orchestrator. Nothing about
any file is supplied: the truth JSON beside each capture is read ONLY to score
the answer afterwards, never to produce it.

    python demo/run_demo.py            # one pass
    python demo/run_demo.py --twice    # the 9 Sep gate: correct, twice

Exit code is 0 only if every file passed every pass, so this is usable as a
gate and not just as a screen to look at.

WHY THESE EIGHT. The operating envelope was measured across all six modulations
and all six corpus SNRs (STATUS.md, 10 Sep). Every modulation completes all
seven stages at >= 15 dB; 16-QAM needs >= 15 dB and 8-PSK >= 13 dB. These eight
sit inside that envelope deliberately. A 16-QAM capture at 13 dB does NOT
complete - it fails honestly at S4 - and it is excluded for that reason rather
than because it looked bad.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIGNALS = HERE / "signals"
ENVELOPE_BUDGET_S = 90.0


def load_truth(wav: Path) -> dict:
    j = wav.with_suffix(".json")
    return json.loads(j.read_text()) if j.is_file() else {}


def truth_modulation(truth: dict, wav: Path) -> str:
    for key in ("modulation", "scheme", "mod"):
        v = truth.get(key)
        if isinstance(v, str):
            return v.lower()
    return wav.name.split("_")[0].lower()


def run_once(orchestrate, pass_no: int) -> bool:
    wavs = sorted(SIGNALS.glob("*.wav"))
    if not wavs:
        print("no captures in %s" % SIGNALS)
        return False

    print("=" * 78)
    print("PASS %d  -  %d captures, blind, through the real pipeline" % (pass_no, len(wavs)))
    print("=" * 78)
    print("%-26s %-8s %-8s %-7s %-8s %s"
          % ("capture", "truth", "found", "stages", "seconds", "verdict"))

    all_ok = True
    for wav in wavs:
        truth = load_truth(wav)
        want = truth_modulation(truth, wav)
        with tempfile.TemporaryDirectory() as td:
            t0 = time.perf_counter()
            try:
                report = orchestrate(run_id="demo-%d-%s" % (pass_no, wav.stem),
                                     file_path=wav, db_path=Path(td) / "demo.db")
            except Exception as exc:                       # never crash the demo
                print("%-26s %-8s %-8s %-7s %-8s CRASHED: %s"
                      % (wav.name[:26], want, "-", "-", "-", exc))
                all_ok = False
                continue
            elapsed = time.perf_counter() - t0

        stages = {s.stage: s for s in report.stages}
        n_ok = sum(1 for s in report.stages
                   if str(getattr(s.status, "value", s.status)) == "ok")
        s3 = stages.get("s3_receive")
        got = str((s3.values or {}).get("modulation", "?")).lower() if s3 else "?"

        ok = (got == want) and n_ok == len(report.stages) and elapsed < ENVELOPE_BUDGET_S
        all_ok &= ok
        print("%-26s %-8s %-8s %-7s %-8.1f %s"
              % (wav.name[:26], want, got, "%d/%d" % (n_ok, len(report.stages)),
                 elapsed, "OK" if ok else "*** FAIL ***"))
        if not ok:
            for s in report.stages:
                st = str(getattr(s.status, "value", s.status))
                if st != "ok":
                    print("      %-12s %-15s %s" % (s.stage, st, (s.reason or "")[:70]))

    print("-" * 78)
    print("PASS %d: %s" % (pass_no, "ALL EIGHT CORRECT" if all_ok else "FAILED"))
    print()
    return all_ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--twice", action="store_true",
                    help="run two consecutive passes, the 9 Sep gate condition")
    args = ap.parse_args(argv)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from service.orchestrator import orchestrate

    passes = 2 if args.twice else 1
    results = [run_once(orchestrate, i + 1) for i in range(passes)]

    print("=" * 78)
    if all(results):
        print("GATE PASS - %d of %d passes, every capture correct in all seven stages"
              % (len(results), passes))
        return 0
    print("GATE FAIL - %d of %d passes clean" % (sum(results), passes))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
