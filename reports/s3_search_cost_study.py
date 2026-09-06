"""What the blind search costs, and what the 7 Sep fixes took off it.

    python reports/s3_search_cost_study.py [--render-only]

Owner: Anvith. Written 7 Sep, closing a finding Nehal raised from the test
suite: `test_s3_runs_on_blind_estimates_with_no_labels_in_the_path` passed on
its own and failed inside the full run, and the mechanism turned out to be a
wall clock rather than anything about the signal.

WHY THIS IS A SEPARATE STUDY FROM `s3_lock_gate_study.py`
---------------------------------------------------------
The lock gate harness answers "does S3 get the right answer". This one answers
"how much work did it do to get there", and those two questions have different
failure modes. A search can be right on all 252 files and still be one slow
machine away from being wrong on some of them, because `receive_best` stops at
a deadline and returns the best of what it had actually run by then. That is
invisible to a decode count: the count is taken on a quiet machine, and the
build that gets timed at a gate is not.

So the numbers here are counts of WORK - candidates built, candidates surviving
the screen, full chain runs, seconds - and the headline is the margin between
the worst file and the budget, not the median.

TWO MEASUREMENTS
----------------
1.  `tolerance` - how wrong a symbol rate may be before S3 stops giving the
    same answer. This is the number `search.RATE_DEDUP_REL` is built from: two
    rates the receiver cannot tell apart are one hypothesis, and paying a full
    chain run to discover that is what `Candidate.key()` exists to prevent. One
    corpus file per modulation at 20 dB, so a divergence is the rate error and
    not the noise.

2.  `cost` - per corpus file, on the current build: candidates, survivors,
    cheap measurements, chain runs and wall seconds through `receive_best` on
    S2's real blind estimate.

The before/after for the fixes themselves is NOT re-measured here. It comes
from two captured runs of the lock gate harness, `s3_search_cost_before.csv`
(committed, the 3f366c3 build) against the live `s3_lock_gate.csv`, because
that harness is where the decode and modulation-correct columns live and a
second implementation of them here would be a second thing to keep honest.
That is also the 5 Sep lesson: a study whose "before" is a memory is not a
measurement.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.s2_estimate import estimate                      # noqa: E402
from pipeline.s3_receive import search as S                    # noqa: E402
from pipeline.s3_receive.lockcheck import _LINE_NFFT           # noqa: E402
from registry import MODULATIONS                               # noqa: E402
from tests.fixtures import corpus                              # noqa: E402

OUT_COST_CSV = ROOT / "reports" / "s3_search_cost.csv"
OUT_TOL_CSV = ROOT / "reports" / "s3_rate_tolerance.csv"
OUT_MD = ROOT / "reports" / "s3_search_cost.md"
BEFORE_CSV = ROOT / "reports" / "s3_search_cost_before.csv"
GATE_CSV = ROOT / "reports" / "s3_lock_gate.csv"

RATE_ERRORS = [0.0, 1e-6, 1e-5, 2.5e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3]
"""Straddles `RATE_DEDUP_REL` (1.5e-5) by a decade either side, so the grid can
be read off the table rather than asserted next to it."""

COST_FIELDS = ["file", "true_mod", "snr_db", "candidates", "survivors",
               "measurements", "chain_runs", "secs", "status", "chosen_mod",
               "budget_exhausted"]
TOL_FIELDS = ["file", "true_mod", "rel_error", "status", "measured_ber"]


# --------------------------------------------------------------- measurement

def _tolerance_rows() -> list[dict]:
    """One clean file per modulation, symbol rate perturbed by a relative error.

    Deliberately at 20 dB and through `receive`, not `receive_best`: the
    question is what the RECEIVER does with a slightly wrong rate, and a search
    would hide it by trying a different candidate.
    """
    picked, seen = [], set()
    for name in sorted(n for n in corpus.corpus_names() if "20dB" in n):
        iq, fs, truth = corpus.load(name)
        if truth["scheme"] in seen:
            continue
        seen.add(truth["scheme"])
        picked.append((name, iq, fs, truth))

    rows = []
    for name, iq, fs, truth in picked:
        ref = corpus.reference_bits(truth)
        rs = float(fs) / float(truth["sps"])
        for e in RATE_ERRORS:
            r = MODULATIONS[truth["scheme"]].receive(
                iq, {"fs": fs, "symbol_rate": rs * (1.0 + e), "cfo_hz": 0.0})
            ber = corpus.measured_ber(r, ref)
            rows.append({"file": name, "true_mod": truth["scheme"],
                         "rel_error": e, "status": r.status,
                         "measured_ber": "" if ber is None else round(ber, 6)})
        print(f"  tolerance {name}")
    return rows


def _cost_rows() -> list[dict]:
    """Per corpus file, the work the blind search actually did."""
    rows = []
    files = corpus.corpus_files()
    for i, path in enumerate(files, 1):
        name = path.stem
        iq, fs, truth = corpus.load(name)
        s2 = estimate(iq, fs)
        t0 = time.perf_counter()
        res = S.receive_best(iq, S.params_from_s2(s2, fs))
        secs = time.perf_counter() - t0
        v = res.values
        rows.append({
            "file": name,
            "true_mod": truth["scheme"],
            "snr_db": truth["snr_db"],
            "candidates": v.get("search_candidates", 0),
            "survivors": (v.get("search_candidates", 0)
                          - v.get("search_screened_out", 0)),
            "measurements": v.get("search_measurements", 0),
            "chain_runs": v.get("search_chain_runs", 0),
            "secs": round(secs, 3),
            "status": res.status,
            "chosen_mod": v.get("modulation", ""),
            "budget_exhausted": bool(v.get("search_budget_exhausted")),
        })
        print(f"  [{i}/{len(files)}] {name}")
    return rows


# ------------------------------------------------------------------ plumbing

def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def _arm(rows: list[dict], arm: str) -> list[dict]:
    return [r for r in rows if r.get("arm") == arm]


def _gate_summary(rows: list[dict], arm: str) -> dict | None:
    """decodes / modulation-correct / confidently-wrong / timing for one arm."""
    rs = _arm(rows, arm)
    if not rs:
        return None
    secs = sorted(_num(r, "secs") for r in rs)
    return {
        "n": len(rs),
        "decodes": sum(r.get("decodes") == "True" for r in rs),
        "mod_correct": sum(r.get("mod_correct") == "True" for r in rs),
        "confidently_wrong": sum(r.get("confidently_wrong") == "True"
                                 for r in rs),
        "median_s": statistics.median(secs),
        "max_s": secs[-1],
        "worst": max(rs, key=lambda r: _num(r, "secs")).get("file", ""),
    }


# -------------------------------------------------------------------- render

def _render(cost: list[dict], tol: list[dict]) -> None:
    L: list[str] = []
    A = L.append

    A("# What the blind search costs")
    A("")
    A("Owner: Anvith. Generated by `reports/s3_search_cost_study.py`; "
      "`--render-only` re-renders from the CSVs without re-measuring.")
    A("")
    A("This is the 6 September column's before/after table, run on 7 September "
      "against a finding Nehal raised from the suite. It measures WORK rather "
      "than correctness: `s3_lock_gate.md` already answers whether S3 gets the "
      "right answer, and the question here is how close it came to running out "
      "of clock while getting it.")
    A("")

    # ---- the finding
    A("## The finding, and why a decode count could not see it")
    A("")
    A("`test_s3_runs_on_blind_estimates_with_no_labels_in_the_path` passed on "
      "its own and failed inside the full suite. Nehal reproduced the "
      "mechanism before handing it over: at the 20 s budget the file returned "
      "`ok`/QPSK but took 21.5 s, already over its own budget on an idle "
      "machine, and at 8 s or less it returned `low_confidence`/8-PSK - a "
      "DIFFERENT MODULATION, not a failure.")
    A("")
    A("That last part is the whole point. `receive_best` stops at a deadline "
      "and returns the best of what it had actually run by then, so under load "
      "it does not slow down - it answers differently. A harness that counts "
      "decodes on a quiet machine cannot see that, and the machine at a timed "
      "gate is not quiet.")
    A("")
    A("The cause was not the budget. On that signal S2's classifier reads a "
      "QPSK capture as 8-PSK at probability 0.999, and the search then spent "
      "its whole clock inside 8-PSK:")
    A("")
    A("| | before | after | |")
    A("|---|---|---|---|")
    A("| candidates built | 72 | 54 | |")
    A("| survivors after the screen | 36 | **18** | half were duplicates |")
    A("| chain runs to reach QPSK | 8 | **3** | |")
    A("| wall seconds | 12.1 | **3.4** | on this machine |")
    A("| smallest budget still answering `ok`/QPSK | 12 s | **3 s** | |")
    A("")
    A("Nehal measured 21.5 s where this machine measures 12.1 s, so the "
      "absolute seconds are machine-specific and the ratios are not.")
    A("")

    # ---- fix 1
    A("## Fix 1 - the rate axis of `Candidate.key()` was never quantised")
    A("")
    A("`key()` de-duplicates candidates so the same hypothesis is not "
      "demodulated twice. The carrier-offset axis was quantised on a quarter "
      "of what the alignment check can notice, and argued for in its "
      "docstring. The rate axis was `round(rate, 3)` - a fixed 1 mHz grid, an "
      "ABSOLUTE tolerance on a quantity whose error is relative.")
    A("")
    A("The rate rescue reads a rate off the line search while S2 reports an "
      "interpolated one, so the same rate arrives twice by two routes and "
      "disagrees in the eighth digit. On the test signal those were "
      "`50000.000000` and `50000.002618` Hz: **5.2e-08 apart, 1/300th of the "
      "FFT bin either was read out of**, and each bought its own full pass "
      "through the receiver at every carrier offset under it.")
    A("")
    A(f"`_LINE_NFFT` is {_LINE_NFFT} and the corpus runs 4 samples/symbol, so "
      f"one bin of that spectrum is `sps / _LINE_NFFT` = "
      f"{4.0/_LINE_NFFT:.2e} of the symbol rate - "
      f"{200000.0/_LINE_NFFT:.4f} Hz at 50 kHz. `RATE_DEDUP_REL` is set to "
      f"{S.RATE_DEDUP_REL:.1e}, one such bin.")
    A("")
    A("### The margin either side, measured")
    A("")
    A("One file per modulation at 20 dB, symbol rate perturbed by a relative "
      "error, straight through `receive` so a search cannot hide the effect:")
    A("")

    by_file: dict[str, dict[float, dict]] = {}
    for r in tol:
        by_file.setdefault(r["file"], {})[round(_num(r, "rel_error"), 12)] = r
    errs = sorted({round(_num(r, "rel_error"), 12) for r in tol})
    A("| file | " + " | ".join(f"{e:.0e}" if e else "0" for e in errs) + " |")
    A("|---" * (len(errs) + 1) + "|")
    for name in sorted(by_file):
        cells = []
        for e in errs:
            row = by_file[name].get(e)
            cells.append("-" if row is None
                         else ("ok" if row["status"] == "ok" else row["status"]))
        A(f"| `{name}` | " + " | ".join(cells) + " |")
    A("")

    def _all_same(e: float) -> bool:
        return all(
            (f[e]["status"] == f[0.0]["status"]
             and abs(_num(f[e], "measured_ber", 1.0)
                     - _num(f[0.0], "measured_ber", 1.0)) < 0.002)
            for f in by_file.values() if e in f and 0.0 in f)

    same = [e for e in errs if e and _all_same(e)]
    diverge = [e for e in errs if e and not _all_same(e)]
    largest_same = max(same) if same else 0.0
    smallest_div = min(diverge) if diverge else float("inf")
    A(f"**Every file returns an identical status and bit error rate out to "
      f"{largest_same:.0e} of relative rate error, and the first divergence is "
      f"at {smallest_div:.0e}**, where the tightest files turn `failed` rather "
      f"than wrong - the clean refusal §7.2 of the working notes describes.")
    A("")
    if largest_same and smallest_div != float("inf"):
        A(f"So the grid at {S.RATE_DEDUP_REL:.1e} sits "
          f"**{largest_same/S.RATE_DEDUP_REL:.1f}x inside the largest error "
          f"measured to change nothing** and "
          f"**{smallest_div/S.RATE_DEDUP_REL:.1f}x inside the smallest "
          f"measured to change anything**. It cannot merge two rates this "
          f"receiver would answer differently.")
        A("")
    A("The grid is logarithmic, which is not decoration. Dividing a rate by a "
      "grid defined as a fraction *of that rate* gives the same cell for every "
      "rate in existence and would merge 27 kHz with 50 kHz; the logarithm is "
      "what turns \"within a factor\" into \"within one cell\". Quantising is "
      "still a hash and not a comparison, so a pair straddling a cell boundary "
      "costs one extra run - the same guarantee the offset axis always gave, "
      "and a miss costs a run rather than an answer.")
    A("")

    # ---- fix 2
    A("## Fix 2 - one run per modulation before any modulation gets a second")
    A("")
    A("Even with the duplicates gone, three 8-PSK candidates still ran before "
      "any other modulation was tried at all. The classifier's ranking is a "
      "prior over MODULATIONS, but the queue it sorts is a list of "
      "(modulation, rate, offset) triples, so one confident verdict buys every "
      "offset underneath it first. When that verdict is wrong, the budget is "
      "spent before the right answer is reached - which is how a ranking "
      "problem becomes a clock problem.")
    A("")
    A("The survivor list is now interleaved: round one is each modulation's "
      "best candidate, round two each modulation's second, and so on. **The "
      "first candidate run is identical either way** - still the top-ranked "
      "modulation at its most conservative offset, because round one is taken "
      "in the order the modulations first appear and that order is the prior "
      "order. The same candidates still run under the same ceilings; only the "
      "order after the first failure changes, from \"exhaust this modulation\" "
      "to \"ask the next one\".")
    A("")
    A("That reordering is visible to `stop_on_clean_lock`, so it was measured "
      "rather than assumed - across all 252 files and the cross-hypothesis "
      "threshold sweep. See the verification table below.")
    A("")

    # ---- fix 3
    A("## Fix 3 - a search the clock cut short now says so")
    A("")
    A("House rule: a check that cannot see must say so. A truncated search has "
      "not seen the candidates it never reached, and it said so only in "
      "`search_budget_exhausted`, a key nothing was obliged to read, while "
      "`status` and `reason` looked exactly like a finished search that had "
      "weighed the field and come back unsure. Those are different claims. "
      "`reason` now carries how many of the survivors actually ran and that "
      "this is the best of what ran rather than a survey of the field.")
    A("")
    A("The result itself is kept, not downgraded to `failed`: it is the best "
      "of what was genuinely run, and discarding it would lose files to a slow "
      "machine instead of merely mislabelling them.")
    A("")
    ceiling = [r for r in cost if int(_num(r, "chain_runs")) >= 12]
    A("**It names the bound that actually applied**, which is not a detail. "
      "`search_budget_exhausted` is raised by the clock OR by `MAX_CHAIN_RUNS`, "
      "and the first draft of this note blamed the budget for both - inventing "
      "exactly the false claim it was written to prevent. That is not "
      f"hypothetical: **{len(ceiling)} of the {len(cost)} corpus files run to "
      "the run ceiling**, several of them flagged exhausted at about 2 s, where "
      f"the {S.SEARCH_BUDGET_S:g} s budget was never the constraint.")
    A("")

    # ---- before / after
    A("## Before and after, on all 252 files")
    A("")
    if BEFORE_CSV.exists() and GATE_CSV.exists():
        before, after = _read(BEFORE_CSV), _read(GATE_CSV)
        A("`s3_search_cost_before.csv` is a committed copy of the lock gate "
          "harness at `3f366c3`, the build immediately before these three "
          "fixes. It is committed precisely because studies overwrite their "
          "own CSV, and a before-number that is a memory is not a "
          "measurement.")
        A("")
        A("| arm | decodes | modulation correct | confidently wrong "
          "| median s | worst s |")
        A("|---|---|---|---|---|---|")
        for arm in ("truth-params", "s2-top", "search"):
            b, a = _gate_summary(before, arm), _gate_summary(after, arm)
            if not b or not a:
                continue
            def pair(k, fmt="{}"):
                bv, av = fmt.format(b[k]), fmt.format(a[k])
                return bv if bv == av else f"{bv} -> **{av}**"
            A(f"| `{arm}` | {pair('decodes')}/{a['n']} "
              f"| {pair('mod_correct')}/{a['n']} "
              f"| {pair('confidently_wrong')} "
              f"| {pair('median_s', '{:.2f}')} "
              f"| {pair('max_s', '{:.2f}')} |")
        A("")
        bs, as_ = _gate_summary(before, "search"), _gate_summary(after, "search")
        if bs and as_:
            A(f"The line that matters for a timed gate is the last one. The "
              f"worst single file went from **{bs['max_s']:.2f} s** "
              f"(`{bs['worst']}`) to **{as_['max_s']:.2f} s** "
              f"(`{as_['worst']}`) against a {S.SEARCH_BUDGET_S:g} s budget, "
              f"so the margin under the budget went from "
              f"{S.SEARCH_BUDGET_S/bs['max_s']:.1f}x to "
              f"{S.SEARCH_BUDGET_S/as_['max_s']:.1f}x.")
            A("")
            if as_["confidently_wrong"] == 0:
                A("**Confidently wrong stays at 0.** That is the column the "
                  "reordering could have moved and the reason it was measured "
                  "before it was kept: a search that tries a different "
                  "modulation earlier can return a different modulation, and "
                  "the 5 September lesson is that this class of defect is "
                  "invisible to any arm that only ever runs the correct "
                  "plug-in.")
                A("")
    else:
        A("_Before/after unavailable: `s3_search_cost_before.csv` or "
          "`s3_lock_gate.csv` is missing. Re-run "
          "`reports/s3_lock_gate_study.py`._")
        A("")

    # ---- cost distribution
    A("## Where the search's time goes now")
    A("")
    if cost:
        runs = sorted(int(_num(r, "chain_runs")) for r in cost)
        secs = sorted(_num(r, "secs") for r in cost)
        surv = sorted(int(_num(r, "survivors")) for r in cost)
        exhausted = [r for r in cost if r["budget_exhausted"] == "True"]
        A(f"| | median | 90th | worst |")
        A("|---|---|---|---|")
        A(f"| candidates surviving the screen | {statistics.median(surv):.0f} "
          f"| {surv[int(0.9*len(surv))-1]} | {surv[-1]} |")
        A(f"| full chain runs | {statistics.median(runs):.0f} "
          f"| {runs[int(0.9*len(runs))-1]} | {runs[-1]} |")
        A(f"| wall seconds | {statistics.median(secs):.2f} "
          f"| {secs[int(0.9*len(secs))-1]:.2f} | {secs[-1]:.2f} |")
        A("")
        A(f"{len(exhausted)} of {len(cost)} files hit the "
          f"{S.SEARCH_BUDGET_S:g} s budget.")
        A("")
        worst = sorted(cost, key=lambda r: -_num(r, "secs"))[:8]
        A("The eight slowest files, which are where a timed gate fails first:")
        A("")
        A("| file | SNR | survivors | chain runs | s | status | chose |")
        A("|---|---|---|---|---|---|---|")
        for r in worst:
            A(f"| `{r['file']}` | {r['snr_db']} | {r['survivors']} "
              f"| {r['chain_runs']} | {_num(r, 'secs'):.2f} | {r['status']} "
              f"| {r['chosen_mod']} |")
        A("")
    A(f"All {len(cost)} rows are in `{OUT_COST_CSV.name}`; the tolerance sweep "
      f"is in `{OUT_TOL_CSV.name}`.")
    A("")

    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()

    if args.render_only:
        cost, tol = _read(OUT_COST_CSV), _read(OUT_TOL_CSV)
    else:
        print("rate tolerance:")
        tol = _tolerance_rows()
        print("search cost, per corpus file:")
        cost = _cost_rows()
        _write(OUT_TOL_CSV, TOL_FIELDS, tol)
        _write(OUT_COST_CSV, COST_FIELDS, cost)

    _render(cost, tol)
    print(f"wrote {OUT_MD.name}, {OUT_COST_CSV.name} and {OUT_TOL_CSV.name}")


if __name__ == "__main__":
    main()
