"""Does Stage 4 survive REAL errors? Measured, two days before it had to be.

    python reports/burst_channel_study.py

Writes reports/burst_channel.png, .csv, and the numbers for burst_channel.md.

Every ceiling measured before 1 Sep used independent bit flips, and every
report carrying those numbers called them "an optimistic bound" on the grounds
that real demodulator errors are bursty and correlated. That assumption was
never tested. It is wrong, and in the useful direction.

Rank collapse counts DAMAGED ROWS, not damaged bits. A row is spoiled by one
error just as thoroughly as by twenty. So packing the same number of errors
into fewer rows leaves more clean rows, and the collapse survives further.
Measured at 1% BER on 96-bit rows:

    independent      62.8% of rows damaged
    mean burst 5     28.1%
    mean burst 20    10.4%
    mean burst 100    3.7%

The channel is Gilbert-Elliott: a good state with no errors and a bad state
erring at 50%, parameterised by overall BER and mean burst length so that the
comparison is same error count, different clustering.

THE CAVEAT THAT MATTERS: this helps RECOVERY and hurts DECODING. Bursts are
exactly what a convolutional decoder cannot handle - which is why interleavers
exist in the first place. So S4 gets easier and S5 gets harder on the same
stream, and the honest envelope has to report both.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s4_recover.rank_collapse import blind_recover, detect_period
from pipeline.s4_recover.statistical import statistical_recover
from pipeline.s5_decode.conv_reference import parity_check_taps
from tests.fixtures.local_zoo import gilbert_elliott_mask, make_stream

BER_GRID = [0.0, 0.001, 0.002, 0.003, 0.005, 0.0075, 0.01, 0.02, 0.03, 0.05]
BURSTS = [1, 5, 20, 100]
SEEDS = 6
N_SOURCE = 60_000
DEPTH, WIDTH = 8, 12
TRUE_SPAN = 14
TRUE_CHECK = parity_check_taps()


def rows_damaged():
    """The mechanism, isolated from any recovery code."""
    rng = np.random.default_rng(0)
    n, L = 400_000, DEPTH * WIDTH
    out = []
    for ber in (0.001, 0.003, 0.01):
        for mb in BURSTS:
            mask = gilbert_elliott_mask(n, ber, mb, rng)
            rows = mask[: n // L * L].reshape(-1, L).any(axis=1)
            out.append({"ber": ber, "mean_burst": mb,
                        "bits_in_error": int(mask.sum()),
                        "rows_damaged_pct": round(float(rows.mean() * 100), 2)})
    return out


def run():
    rows = []
    for ber in BER_GRID:
        for mb in BURSTS:
            t0 = time.time()
            exact = stat = full = 0
            for s in range(SEEDS):
                bits, truth = make_stream(N_SOURCE, DEPTH, WIDTH, ber=ber,
                                          seed=900 + s, mean_burst=mb)
                period, _, _ = detect_period(bits)
                exact += (period == truth.period)

                raw, _ = make_stream(N_SOURCE, None, None, ber=ber,
                                     seed=950 + s, mean_burst=mb)
                r = statistical_recover(raw, spans=[TRUE_SPAN], seed=s)
                stat += (r.taps is not None and
                         np.array_equal(np.array(r.taps, dtype=np.uint8), TRUE_CHECK))

                res = blind_recover(bits)
                full += (res.status == "ok"
                         and res.interleaver is not None
                         and res.interleaver.params == {"depth": truth.depth,
                                                        "width": truth.width})
            rows.append({"ber": ber, "mean_burst": mb,
                         "exact_period": exact / SEEDS,
                         "stat_tracking": stat / SEEDS,
                         "full_pipeline": full / SEEDS})
            print("BER=%.4f burst=%-4d exact=%.2f stat=%.2f full=%.2f  [%.0fs]"
                  % (ber, mb, exact / SEEDS, stat / SEEDS, full / SEEDS,
                     time.time() - t0), flush=True)
    return rows


def ceiling(rows, key, mb):
    best = 0.0
    for r in [r for r in rows if r["mean_burst"] == mb]:
        if r[key] >= 0.99:
            best = max(best, r["ber"])
        else:
            break
    return best


def write_csv(rows, path):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", path)


def write_plot(rows, damage, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {1: "#9B3122", 5: "#87621A", 20: "#1E3B5C", 100: "#2A6247"}
    fig, (ax, ax2, ax3) = plt.subplots(
        3, 1, figsize=(9.5, 12), gridspec_kw={"height_ratios": [1.3, 1.1, 0.9]})

    # --- 1. the finding -------------------------------------------------
    for mb in BURSTS:
        sub = [r for r in rows if r["mean_burst"] == mb]
        label = "independent" if mb == 1 else "mean burst %d" % mb
        ax.plot([r["ber"] * 100 for r in sub], [r["exact_period"] * 100 for r in sub],
                marker="o", color=colours[mb], linewidth=2, markersize=5.5,
                label="%s  —  ceiling %.2f%%"
                      % (label, ceiling(rows, "exact_period", mb) * 100))
    ax.set_xscale("symlog", linthresh=0.15)
    ax.set_ylim(-5, 105)
    ax.set_ylabel("Interleaver period recovered (%)")
    ax.set_xlabel("Bit error rate (%)")
    ax.set_title("Realistic bursty errors make Stage 4 recovery EASIER, not harder"
                 "\nidentical error counts, clustered differently — the envelope "
                 "widens 16x, from 0.30% to 5.0% BER", fontsize=12)
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=9, loc="lower left", title="error model")

    # --- 2. the part that is NOT solved ---------------------------------
    for mb in BURSTS:
        sub = [r for r in rows if r["mean_burst"] == mb]
        ax2.plot([r["ber"] * 100 for r in sub], [r["full_pipeline"] * 100 for r in sub],
                 marker="s", color=colours[mb], linewidth=1.8, markersize=4.5,
                 label="independent" if mb == 1 else "mean burst %d" % mb)
    ax2.set_xscale("symlog", linthresh=0.15)
    ax2.set_ylim(-5, 105)
    ax2.set_ylabel("Interleaver PARAMETERS recovered (%)")
    ax2.set_xlabel("Bit error rate (%)")
    ax2.set_title("The honest counterweight: recovering the interleaver's depth x width"
                  "\nstill fails at any non-zero BER. Bursts help — 0% to 83% at 0.1% BER —"
                  "\nbut nothing reaches 100%. This is the open problem.", fontsize=11)
    ax2.grid(alpha=0.25, linestyle=":")
    ax2.legend(fontsize=8.5, loc="upper right")

    # --- 3. the mechanism ------------------------------------------------
    at1 = [d for d in damage if d["ber"] == 0.01]
    ax3.bar([str(d["mean_burst"]) for d in at1], [d["rows_damaged_pct"] for d in at1],
            color=[colours[d["mean_burst"]] for d in at1], width=0.6)
    for d in at1:
        ax3.text(str(d["mean_burst"]), d["rows_damaged_pct"] + 1.5,
                 "%.1f%%" % d["rows_damaged_pct"], ha="center", fontsize=9.5)
    ax3.set_xlabel("Mean burst length (1 = independent)")
    ax3.set_ylabel("96-bit rows damaged (%)")
    ax3.set_title("Why: at a fixed 1% BER, clustering the same errors spoils far "
                  "fewer rows", fontsize=11)
    ax3.grid(alpha=0.25, linestyle=":", axis="y")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    damage = rows_damaged()
    rows = run()
    write_csv(rows, ROOT / "reports" / "burst_channel.csv")
    write_csv(damage, ROOT / "reports" / "burst_row_damage.csv")
    write_plot(rows, damage, ROOT / "reports" / "burst_channel.png")

    print()
    print("CEILINGS (highest BER with 100% success)")
    print("%-14s %10s %10s %10s" % ("error model", "exact", "statistical", "full"))
    for mb in BURSTS:
        print("%-14s %9.2f%% %9.2f%% %9.2f%%"
              % ("independent" if mb == 1 else "burst %d" % mb,
                 ceiling(rows, "exact_period", mb) * 100,
                 ceiling(rows, "stat_tracking", mb) * 100,
                 ceiling(rows, "full_pipeline", mb) * 100))
