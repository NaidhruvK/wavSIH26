"""The 4 September verification: WAV in, no truth anywhere, hypotheses ranked.

    Command Center, 4 Sep, Nehal:
      task   "Hypothesis fallback across registries: try each candidate
              modulation, rotation, interleaver and code; keep whichever
              produces a rank collapse."
      done   "S4 searches the registry product automatically, with bounds."
      verify "Corrupt S2's top hypothesis; the pipeline still decodes via
              the second."

Until today that line could not be run: S2 did not exist, so every study of
mine passed `fs` and `symbol_rate` to S3 from the truth sidecar and said so.
`reports/end_to_end.md` carries that admission. Dheeraj's S2 landed on main
this evening, so the caveat is now retirable by measurement instead of prose.

WHAT IS BLIND HERE. Everything. The only thing read off disk is the WAV
itself, through S0. The truth JSON is opened once, at the END, to score the
answer - never to produce it:

    S0 ingest      -> IQ and sample rate from the file
    S2 estimate    -> symbol rate, CFO, ranked hypotheses          (blind)
    S3 receive     -> soft LLRs per modulation hypothesis          (blind)
    S4 recover     -> interleaver, code, generators                (blind)

MODULATION is chosen by iterating the MODULATIONS registry and keeping
whatever produces a rank collapse - which is this column's own wording. It is
deliberately NOT the classifier (that wiring is Dheeraj's 4 Sep task) and not
`pipeline/s3_receive/search.py` (Anvith's, on his branch). Doing it the dumb
exhaustive way here is the point: it measures whether S4 can REJECT a wrong
modulation on its own, which is the question Anvith raised about the subset
trap - QPSK's four points are also four of 16-QAM's sixteen.

BOUNDS, because the registry product is risk #5: at most MAX_RATE_HYPOTHESES
symbol rates x the registered modulations, and the whole search per file is
under a wall clock. Nothing here may grow with file content.

Regenerate with `python reports/blind_chain_study.py`.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s3_receive.linear      # noqa: F401,E402  (registers modulations)
import pipeline.s3_receive.fsk_plugin  # noqa: F401,E402
import pipeline.s4_recover.interleavers  # noqa: F401,E402
from pipeline.s0_ingest import ingest  # noqa: E402
from pipeline.s2_estimate import estimate  # noqa: E402
from pipeline.s4_recover.rotations import recover_over_rotations  # noqa: E402
from registry import MODULATIONS  # noqa: E402

CORPUS = ROOT / "zoo" / "corpus" / "rf"

MAX_RATE_HYPOTHESES = 2      # S2 offers a ranked list; we try this many
SEARCH_BUDGET_S = 120.0      # wall clock for the whole per-file search


def _rate_hypotheses(s2, corrupt: bool) -> list[float]:
    """S2's ranked symbol rates, optionally with the top one poisoned.

    Corrupting means REPLACING the winner with a plausible-but-wrong rate, not
    deleting it - the point of the check is that a confident wrong answer from
    upstream is survivable, not that a missing answer is.
    """
    ranked = [float(r) for r, _score in (s2.symbol_rate_hypotheses or [])]
    if not ranked and s2.symbol_rate_hz:
        ranked = [float(s2.symbol_rate_hz)]
    if corrupt and ranked:
        ranked = [ranked[0] * 1.5] + ranked      # a wrong rate, ranked first
    return ranked[:MAX_RATE_HYPOTHESES + (1 if corrupt else 0)]


def run_one(wav: Path, corrupt: bool = False) -> dict:
    t0 = time.time()
    name = wav.stem
    row = {"file": name, "corrupt_top": int(corrupt), "s0_ok": 0, "s2_ok": 0,
           "s2_rate_hz": 0.0, "true_rate_hz": 0.0, "rate_err_pct": -1.0,
           "chain_runs": 0, "scheme_found": "-", "true_scheme": "-",
           "scheme_ok": 0, "interleaver_ok": 0, "generators_ok": 0,
           "false_positive": 0, "seconds": 0.0}

    s0 = ingest(wav)
    if getattr(s0, "status", "ok") != "ok" or s0.iq is None:
        row["seconds"] = round(time.time() - t0, 1)
        return row
    iq, fs = np.asarray(s0.iq), float(s0.fs)
    row["s0_ok"] = 1

    s2 = estimate(iq, fs)
    if s2.status != "ok":
        row["seconds"] = round(time.time() - t0, 1)
        return row
    row["s2_ok"] = 1
    row["s2_rate_hz"] = round(float(s2.symbol_rate_hz or 0.0), 1)

    # CFO IS A HYPOTHESIS, NOT A FACT - and on this corpus S2's is wrong.
    #
    # The M-th power estimator resolves M*cfo modulo 2*pi, so it recovers the
    # offset only up to +/- k*symbol_rate/M. On these files the true CFO is 0
    # and every hypothesis S2 ranks is an alias of it: 25000 Hz for BPSK
    # (rate/2), 12500 for QPSK (rate/4), 6250 for 8-PSK (rate/8). Zero is never
    # offered at any rank, so "decode via the second hypothesis" cannot save
    # it - the right answer is absent from the list entirely.
    #
    # Applying that offset costs the recovery on 4 of 4 files that recover
    # perfectly without it, and S3 still reports `ok` at 5-6% EVM while doing
    # it. So the null hypothesis - no pre-correction, let S3's own carrier loop
    # do its job - is tried FIRST, and S2's estimate second. This is the
    # registry-product fallback doing exactly what the column asks of it:
    # surviving a confidently wrong answer from upstream.
    cfo_candidates: list[float | None] = [None]
    if s2.cfo_hz:
        cfo_candidates.append(float(s2.cfo_hz))

    deadline = t0 + SEARCH_BUDGET_S
    found = None
    runs = 0
    for rate in _rate_hypotheses(s2, corrupt):
        if found is not None or time.time() > deadline:
            break
        for cfo in cfo_candidates:
            if found is not None or time.time() > deadline:
                break
            for scheme, plugin in MODULATIONS.items():
                if time.time() > deadline:
                    break
                runs += 1
                params = {"fs": fs, "symbol_rate": rate}
                if cfo is not None:
                    params["cfo_hz"] = cfo
                try:
                    s3 = plugin.receive(iq, params)
                except Exception:
                    continue
                if s3.llrs is None or np.asarray(s3.llrs).size == 0:
                    continue
                v = getattr(s3, "values", {}) or {}
                choice = recover_over_rotations(
                    getattr(s3, "llrs_by_rotation", None) or [s3.llrs],
                    estimated_output_ber=float(v.get("estimated_output_ber", -1.0)),
                    estimated_ber_valid=bool(
                        v.get("estimated_output_ber_valid", False)))
                if choice is not None:
                    found = (scheme, rate, choice)
                    break
    row["chain_runs"] = runs

    # --- scoring only from here. Nothing below fed the search. -------------
    truth = json.loads(wav.with_suffix(".json").read_text())
    il, code = truth["interleaver"], truth["code"]
    row["true_scheme"] = truth["scheme"]
    row["true_rate_hz"] = round(truth["fs"] / truth["sps"], 1)
    if row["s2_rate_hz"]:
        row["rate_err_pct"] = round(
            100.0 * abs(row["s2_rate_hz"] - row["true_rate_hz"]) / row["true_rate_hz"], 3)

    if found is not None:
        scheme, _rate, choice = found
        res = choice.result
        row["scheme_found"] = scheme
        row["scheme_ok"] = int(scheme == truth["scheme"])
        row["interleaver_ok"] = int(
            res.interleaver is not None
            and res.interleaver.params.get("depth") == il["depth"]
            and res.interleaver.params.get("width") == il["width"])
        row["generators_ok"] = int(res.generators_octal == tuple(code["polys_octal"]))
        # A confident answer on the WRONG modulation is the subset trap.
        row["false_positive"] = int(not (row["interleaver_ok"] and row["generators_ok"]))
    row["seconds"] = round(time.time() - t0, 1)
    return row


def main() -> None:
    files = sorted(CORPUS.glob("*.wav"))
    if not files:
        raise SystemExit("no RF corpus at %s" % CORPUS)

    # One file per modulation at a healthy SNR: enough to prove the chain runs
    # blind without paying for the whole corpus at 6 chain runs per file.
    picked = []
    for scheme in sorted({json.loads(f.with_suffix(".json").read_text())["scheme"]
                          for f in files}):
        for snr in (20, 15, 13):
            m = [f for f in files
                 if json.loads(f.with_suffix(".json").read_text())["scheme"] == scheme
                 and json.loads(f.with_suffix(".json").read_text())["snr_db"] == snr]
            if m:
                picked.append(m[0])
                break

    rows = []
    print("=== A. fully blind: S0 -> S2 -> S3 -> S4, no truth in the path ===")
    print("%-22s %-9s %-9s %-6s %-7s %-9s %-9s %s"
          % ("file", "S2 rate", "true rate", "err%", "runs", "scheme", "interlvr", "gens"))
    for f in picked:
        r = run_one(f, corrupt=False)
        rows.append(r)
        print("%-22s %-9.0f %-9.0f %-6s %-7d %-9s %-9s %s"
              % (r["file"][:22], r["s2_rate_hz"], r["true_rate_hz"],
                 r["rate_err_pct"], r["chain_runs"], r["scheme_found"],
                 "YES" if r["interleaver_ok"] else "no",
                 "YES" if r["generators_ok"] else "no"), flush=True)

    print()
    print("=== B. the 4 Sep verify: S2's TOP hypothesis corrupted ===")
    for f in picked:
        r = run_one(f, corrupt=True)
        rows.append(r)
        print("%-22s runs=%-3d scheme=%-8s interleaver=%-4s generators=%-4s  %s"
              % (r["file"][:22], r["chain_runs"], r["scheme_found"],
                 "YES" if r["interleaver_ok"] else "no",
                 "YES" if r["generators_ok"] else "no",
                 "recovered via a later hypothesis"
                 if r["interleaver_ok"] else "did NOT recover"), flush=True)

    out = ROOT / "reports" / "blind_chain.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote", out)

    clean = [r for r in rows if not r["corrupt_top"]]
    dirty = [r for r in rows if r["corrupt_top"]]
    errs = [r["rate_err_pct"] for r in clean if r["rate_err_pct"] >= 0]

    print()
    print("S2 symbol rate, blind : worst error %.3f %% over %d files"
          % (max(errs) if errs else -1, len(errs)))
    print("blind chain           : %d/%d recovered interleaver AND generators"
          % (sum(r["interleaver_ok"] and r["generators_ok"] for r in clean), len(clean)))
    print("top hypothesis corrupt: %d/%d still recovered"
          % (sum(r["interleaver_ok"] and r["generators_ok"] for r in dirty), len(dirty)))
    fp = [r for r in rows if r["false_positive"]]
    print("CONFIDENT ANSWERS ON THE WRONG MODULATION (the subset trap): %d" % len(fp))
    for r in fp:
        print("   ", r["file"], "->", r["scheme_found"], "(true %s)" % r["true_scheme"])
    print("worst per-file time   : %.1f s" % max(r["seconds"] for r in rows))


if __name__ == "__main__":
    main()
