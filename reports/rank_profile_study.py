"""Generate the rank-collapse signature plot - the chart that carries S4.

Writes reports/rank_profile.png and reports/rank_profile.csv.

Three traces on one axis, which is the entire technical argument in one image:
uncoded random data is flat on zero at every row length; a raw coded stream
collapses on every even row length from 14 upward; an interleaved stream
collapses only at multiples of the interleaver period. Nothing about this
requires knowing the scheme in advance, which is the point.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s4_recover.rank_collapse import rank_profile
from tests.fixtures.local_zoo import make_stream

N_SOURCE = 200_000
DEPTH, WIDTH = 8, 12
PERIOD = DEPTH * WIDTH
L_MAX = 300


def build():
    coded, _ = make_stream(N_SOURCE, None, None, seed=21)
    inter, _ = make_stream(N_SOURCE, DEPTH, WIDTH, seed=21)
    rng = np.random.default_rng(21)
    noise = rng.integers(0, 2, len(coded), dtype=np.uint8)

    return {
        "coded": rank_profile(coded, 2, L_MAX).deficiency,
        "interleaved": rank_profile(inter, 2, L_MAX).deficiency,
        "uncoded": rank_profile(noise, 2, L_MAX).deficiency,
    }


def write_csv(profiles, path):
    keys = sorted(set().union(*(p.keys() for p in profiles.values())))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_length", "coded", "interleaved", "uncoded"])
        for L in keys:
            w.writerow([L] + [profiles[k].get(L, "") for k in
                              ("coded", "interleaved", "uncoded")])
    print("wrote", path)


def write_plot(profiles, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9.5, 8.4),
                                  gridspec_kw={"height_ratios": [1.15, 1]})

    # The raw coded sawtooth is dense and swamps everything if drawn solid, so
    # it sits in the background at low alpha. The headline is the interleaved
    # trace: isolated spikes at multiples of the period, against a random
    # stream that never leaves zero.
    prof_c = profiles["coded"]
    Ls_c = sorted(prof_c)
    ax.fill_between(Ls_c, [prof_c[L] for L in Ls_c], color="#87621A", alpha=0.16,
                    linewidth=0,
                    label="Rate 1/2 K=7, no interleaver (background) - every even L >= 14")

    prof_i = profiles["interleaved"]
    Ls_i = sorted(prof_i)
    ax.vlines(Ls_i, 0, [prof_i[L] for L in Ls_i], color="#1E3B5C", linewidth=2.4,
              label="Block interleaved 8x12 - collapses ONLY at multiples of 96")
    hits = [L for L in Ls_i if prof_i[L] > 0]
    ax.plot(hits, [prof_i[L] for L in hits], "o", color="#1E3B5C", markersize=6)

    prof_u = profiles["uncoded"]
    Ls_u = sorted(prof_u)
    ax.plot(Ls_u, [prof_u[L] for L in Ls_u], color="#9B3122", linewidth=2.0,
            label="Uncoded random data - flat zero at every L, nothing claimed")

    for L in hits:
        ax.annotate("L = %d\ndef = %d" % (L, prof_i[L]), xy=(L, prof_i[L]),
                    xytext=(L + 6, prof_i[L] + 14), fontsize=8.5, color="#1E3B5C")

    ax.set_xlabel("Row length L (bits)")
    ax.set_ylabel("Rank deficiency  L - rank(M)")
    ax.set_title("GF(2) rank collapse - the Stage 4 signature\n"
                 "nothing here was told the modulation, the code or the interleaver",
                 fontsize=12)
    ax.set_ylim(-6, max(prof_c.values()) * 1.12)
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=8.5, loc="upper left", framealpha=0.93)

    prof = profiles["coded"]
    Ls = [L for L in sorted(prof) if L <= 48]
    ax2.bar([L - 0.2 for L in Ls], [prof[L] for L in Ls], width=0.75,
            color=["#87621A" if L % 2 == 0 else "#D3D2CD" for L in Ls])
    ax2.plot(Ls, [max(0, L / 2 - 6) for L in Ls], color="#2A6247", linewidth=1.6,
             linestyle="--", label="predicted  L/2 - 6")
    ax2.set_xlabel("Row length L (bits)")
    ax2.set_ylabel("Deficiency")
    ax2.set_title("Zoomed: measured deficiency matches L/n - m exactly, which is "
                  "how n=2 and m=6 are read off", fontsize=10.5)
    ax2.grid(alpha=0.25, linestyle=":", axis="y")
    ax2.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    profiles = build()
    write_csv(profiles, ROOT / "reports" / "rank_profile.csv")
    write_plot(profiles, ROOT / "reports" / "rank_profile.png")

    inter = profiles["interleaved"]
    print("\ninterleaved stream, nonzero deficiency at L =",
          [L for L, d in sorted(inter.items()) if d > 0])
    print("uncoded stream, max deficiency =", max(profiles["uncoded"].values()))
