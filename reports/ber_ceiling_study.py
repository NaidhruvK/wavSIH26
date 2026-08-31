"""Measure where Stage 4 breaks, and write the number down.

Produces reports/ber_ceiling.csv, reports/ber_ceiling.png and the numbers that
go into reports/ber_ceiling.md. Run it with:

    python reports/ber_ceiling_study.py

Four curves, because they fail at very different places and the difference is
the whole argument for having two methods:

  exact_period    exact rank test finds the interleaver period (depth 8 x
                  width 12, P=96) on an interleaved stream
  exact_code      exact rank test reads n and m off a raw coded stream
  stat_tracking   statistical method recovers the parity check when the span is
                  already known from a clean file
  stat_blind      statistical method recovers span and check from nothing

READ THE CAVEAT BEFORE QUOTING ANY OF THESE. The errors here are INDEPENDENT,
injected by the local zoo. Real demodulator errors are bursty and correlated,
so every ceiling below is an optimistic bound. The honest version of these
numbers gets measured on 3 Sep against real LLRs out of S3, and that is the
number that goes in the envelope report.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s4_recover.rank_collapse import detect_period, recover_code_structure
from pipeline.s4_recover.statistical import statistical_recover
from pipeline.s5_decode.conv_reference import parity_check_taps
from tests.fixtures.local_zoo import make_stream

BER_GRID = [0.0, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.0075,
            0.01, 0.02, 0.03, 0.05, 0.07, 0.10]
SEEDS_EXACT = 8
SEEDS_STAT = 5
N_SOURCE = 60_000
DEPTH, WIDTH = 8, 12
PERIOD = DEPTH * WIDTH
TRUE_SPAN = 14
TRUE_CHECK = parity_check_taps()


def run() -> list[dict]:
    rows = []
    for ber in BER_GRID:
        t0 = time.time()
        rec = {"ber": ber}

        # --- exact rank test, interleaved stream: does it find the period? ---
        hits = 0
        for s in range(SEEDS_EXACT):
            bits, truth = make_stream(N_SOURCE, DEPTH, WIDTH, ber=ber, seed=400 + s)
            period, _, _ = detect_period(bits)
            hits += (period == truth.period)
        rec["exact_period"] = hits / SEEDS_EXACT

        # --- exact rank test, raw coded stream: does it read n and m? --------
        hits = 0
        for s in range(SEEDS_EXACT):
            bits, _ = make_stream(N_SOURCE, None, None, ber=ber, seed=500 + s)
            code = recover_code_structure(bits)
            hits += (code.n == 2 and code.memory == 6 and code.consistent)
        rec["exact_code"] = hits / SEEDS_EXACT

        # --- statistical, span already known ---------------------------------
        hits, bers = 0, []
        for s in range(SEEDS_STAT):
            bits, _ = make_stream(N_SOURCE, None, None, ber=ber, seed=600 + s)
            res = statistical_recover(bits, spans=[TRUE_SPAN], seed=s)
            ok = res.taps is not None and np.array_equal(
                np.array(res.taps, dtype=np.uint8), TRUE_CHECK)
            hits += ok
            if ok and res.validation.implied_ber is not None:
                bers.append(res.validation.implied_ber)
        rec["stat_tracking"] = hits / SEEDS_STAT
        rec["implied_ber"] = float(np.mean(bers)) if bers else float("nan")

        # --- statistical, fully blind ----------------------------------------
        hits = 0
        for s in range(SEEDS_STAT):
            bits, _ = make_stream(N_SOURCE, None, None, ber=ber, seed=700 + s)
            res = statistical_recover(bits, max_span=20, seed=s)
            hits += (res.taps is not None and len(res.taps) == TRUE_SPAN
                     and np.array_equal(np.array(res.taps, dtype=np.uint8), TRUE_CHECK))
        rec["stat_blind"] = hits / SEEDS_STAT

        rec["seconds"] = round(time.time() - t0, 1)
        rows.append(rec)
        print("BER=%.4f  exact_period=%.2f  exact_code=%.2f  stat_tracking=%.2f  "
              "stat_blind=%.2f  implied_ber=%.4f  [%.0fs]"
              % (ber, rec["exact_period"], rec["exact_code"], rec["stat_tracking"],
                 rec["stat_blind"], rec["implied_ber"], rec["seconds"]), flush=True)
    return rows


def ceiling(rows: list[dict], key: str, threshold: float = 0.99) -> float:
    """Highest BER at which the method still succeeded on every trial."""
    best = 0.0
    for r in rows:
        if r[key] >= threshold:
            best = max(best, r["ber"])
        else:
            break
    return best


# Wall-clock timing is deliberately NOT written into the metrics CSV. The 8 Sep
# gate is "regenerate from a clean checkout, numbers identical", and that has to
# mean a byte comparison. One nondeterministic column makes that impossible and
# forces a human to eyeball a diff instead - which is how a real change slips
# through. Timing goes in its own file.
METRIC_FIELDS = ["ber", "exact_period", "exact_code", "stat_tracking",
                 "implied_ber", "stat_blind"]


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=METRIC_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    timing = path.with_name(path.stem + "_timing.csv")
    with timing.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ber", "seconds"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_plot(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ber = [r["ber"] * 100 for r in rows]
    series = [
        ("exact_period", "Exact rank - interleaver period (P=96)", "#9B3122", "o"),
        ("exact_code", "Exact rank - code structure (n, m)", "#87621A", "s"),
        ("stat_blind", "Statistical - blind (span unknown)", "#1E3B5C", "^"),
        ("stat_tracking", "Statistical - tracking (span known)", "#2A6247", "D"),
    ]

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 8.2),
                                  gridspec_kw={"height_ratios": [2.1, 1]})
    for key, label, colour, marker in series:
        ax.plot(ber, [r[key] * 100 for r in rows], marker=marker, color=colour,
                label=label, linewidth=1.9, markersize=5.5)
    ax.set_ylabel("Recovery success rate (%)")
    ax.set_title("Stage 4 operating envelope - recovery vs injected BER\n"
                 "rate 1/2 K=7 (171,133), 60k source bits, independent bit errors",
                 fontsize=11.5)
    ax.set_xscale("symlog", linthresh=0.1)
    ax.set_ylim(-5, 105)
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=9, loc="lower left")
    ax.axhline(100, color="#71777F", linewidth=0.7, linestyle="--")

    ok = [r for r in rows if not np.isnan(r["implied_ber"]) and r["stat_tracking"] > 0]
    ax2.plot([r["ber"] * 100 for r in ok], [r["implied_ber"] * 100 for r in ok],
             marker="o", color="#2A6247", linewidth=1.9, markersize=5.5,
             label="BER inferred from syndrome bias")
    lim = max([r["ber"] * 100 for r in ok] + [1])
    ax2.plot([0, lim], [0, lim], color="#71777F", linestyle="--", linewidth=1,
             label="truth (y = x)")
    ax2.set_xlabel("Injected bit error rate (%)")
    ax2.set_ylabel("Inferred BER (%)")
    ax2.set_title("The validator also measures the channel it is working in",
                  fontsize=10.5)
    ax2.grid(alpha=0.25, linestyle=":")
    ax2.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    rows = run()
    reports = ROOT / "reports"
    write_csv(rows, reports / "ber_ceiling.csv")
    write_plot(rows, reports / "ber_ceiling.png")
    print()
    print("CEILINGS (highest BER with 100% success)")
    for key in ("exact_period", "exact_code", "stat_blind", "stat_tracking"):
        print("  %-14s %.4f  (%.2f%%)" % (key, ceiling(rows, key), ceiling(rows, key) * 100))
