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


def check_recovery(truth: dict, s4_values: dict) -> list[str]:
    """Compare what S4 blindly recovered against the truth JSON. Returns a list
    of mismatch descriptions -- empty means every recovered parameter is right.

    THIS IS THE CLAIM THE GATE PRINTS. Until 10 Sep the gate scored a capture
    on the modulation name plus "all seven stages said ok", and nothing
    anywhere compared the recovered interleaver or code against the truth
    sitting in the JSON beside the capture. A run that identified the
    modulation, reported ok at every stage, and recovered the WRONG
    interleaver would have printed ALL EIGHT CORRECT. The stage statuses are
    self-assessment; this is the part that is scored against an answer.
    """
    problems: list[str] = []

    want_int = truth.get("interleaver") or {}
    if want_int:
        got_family = s4_values.get("interleaver_family")
        got_params = s4_values.get("interleaver_params") or {}
        if got_family != want_int.get("family"):
            problems.append("interleaver family %s, truth %s"
                            % (got_family, want_int.get("family")))
        for key in ("depth", "width"):
            if key in want_int and got_params.get(key) != want_int[key]:
                problems.append("interleaver %s %s, truth %s"
                                % (key, got_params.get(key), want_int[key]))
        if "period" in want_int and s4_values.get("period") != want_int["period"]:
            problems.append("period %s, truth %s"
                            % (s4_values.get("period"), want_int["period"]))

    want_code = truth.get("code") or {}
    if want_code:
        if "rate" in want_code and s4_values.get("code_rate") != want_code["rate"]:
            problems.append("rate %s, truth %s"
                            % (s4_values.get("code_rate"), want_code["rate"]))
        if "K" in want_code and s4_values.get("K") != want_code["K"]:
            problems.append("K %s, truth %s" % (s4_values.get("K"), want_code["K"]))
        want_polys = want_code.get("polys_octal")
        if want_polys:
            got_polys = list(s4_values.get("generators_octal") or [])
            if got_polys != list(want_polys):
                problems.append("generators %s, truth %s" % (got_polys, list(want_polys)))

    return problems


def run_once(orchestrate, pass_no: int) -> bool:
    wavs = sorted(SIGNALS.glob("*.wav"))
    if not wavs:
        print("no captures in %s" % SIGNALS)
        return False

    print("=" * 78)
    print("PASS %d  -  %d captures, blind, through the real pipeline" % (pass_no, len(wavs)))
    print("=" * 78)
    print("%-24s %-7s %-7s %-7s %-9s %-7s %s"
          % ("capture", "truth", "found", "stages", "params", "seconds", "verdict"))

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
                print("%-24s %-7s %-7s %-7s %-9s %-7s CRASHED: %s"
                      % (wav.name[:24], want, "-", "-", "-", "-", exc))
                all_ok = False
                continue
            elapsed = time.perf_counter() - t0

        stages = {s.stage: s for s in report.stages}
        n_ok = sum(1 for s in report.stages
                   if str(getattr(s.status, "value", s.status)) == "ok")
        s3 = stages.get("s3_receive")
        got = str((s3.values or {}).get("modulation", "?")).lower() if s3 else "?"

        s4 = stages.get("s4_recover")
        problems = check_recovery(truth, (s4.values or {}) if s4 else {})

        ok = (got == want and not problems
              and n_ok == len(report.stages) and elapsed < ENVELOPE_BUDGET_S)
        all_ok &= ok
        print("%-24s %-7s %-7s %-7s %-9s %-7.1f %s"
              % (wav.name[:24], want, got, "%d/%d" % (n_ok, len(report.stages)),
                 "MATCH" if not problems else "MISMATCH",
                 elapsed, "OK" if ok else "*** FAIL ***"))
        if not ok:
            for s in report.stages:
                st = str(getattr(s.status, "value", s.status))
                if st != "ok":
                    print("      %-12s %-15s %s" % (s.stage, st, (s.reason or "")[:70]))
            for problem in problems:
                print("      %-12s %s" % ("s4_recover", problem))

    print("-" * 78)
    print("PASS %d: %s" % (pass_no,
                           "ALL %d CORRECT - every recovered parameter matches truth"
                           % len(wavs) if all_ok else "FAILED"))
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
        print("GATE PASS - %d of %d passes. Every capture: modulation identified," 
              " interleaver and code recovered EQUAL TO TRUTH, seven of seven"
              " stages ok, inside the %.0f s envelope."
              % (len(results), passes, ENVELOPE_BUDGET_S))
        return 0
    print("GATE FAIL - %d of %d passes clean" % (sum(results), passes))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
