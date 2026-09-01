"""What the rank profile says about each interleaver family - and what it can't.

    python reports/interleaver_families_study.py

Writes reports/interleaver_families.png and .csv.

The point of the figure is a negative result as much as a positive one. Block
and diagonal interleavers produce byte-identical profiles: same deficient row
lengths, same deficiency values. No amount of staring at the curve separates
them. That is why Stage 4 resolves the family functionally - de-interleave with
each candidate and ask whether the code comes back - rather than by pattern
matching on the profile.

Convolutional is the one family the profile does identify, because its
deficiency repeats every N bits (the branch count) starting well above N,
whereas a block-like interleaver first collapses exactly at its period.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s4_recover.interleavers import (
    block_interleave,
    conv_interleave,
    diagonal_interleave,
)
from pipeline.s4_recover.rank_collapse import rank_profile, detect_signature
from pipeline.s5_decode.conv_reference import conv_encode

N_SOURCE = 160_000
L_MAX = 220


def build():
    rng = np.random.default_rng(7)
    coded = conv_encode(rng.integers(0, 2, N_SOURCE, dtype=np.uint8))
    streams = {
        "block 8x12": block_interleave(coded, 8, 12),
        "diagonal 8x12": diagonal_interleave(coded, 8, 12),
        "convolutional N=4 M=1": conv_interleave(coded, 4, 1),
        "convolutional N=6 M=2": conv_interleave(coded, 6, 2),
        "uncoded random": rng.integers(0, 2, len(coded), dtype=np.uint8),
    }
    profiles, sigs = {}, {}
    for name, bits in streams.items():
        profiles[name] = rank_profile(bits, 2, L_MAX).deficiency
        first, step, _ = detect_signature(bits)
        sigs[name] = (first, step)
    return profiles, sigs


def write_csv(profiles, path):
    names = list(profiles)
    keys = sorted(set().union(*(p.keys() for p in profiles.values())))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_length"] + names)
        for L in keys:
            w.writerow([L] + [profiles[n].get(L, "") for n in names])
    print("wrote", path)


def write_plot(profiles, sigs, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(10, 8.6))

    # --- panel 1: block and diagonal are the same curve ------------------
    blk, dia = profiles["block 8x12"], profiles["diagonal 8x12"]
    Ls = sorted(blk)
    ax.vlines(Ls, 0, [blk[L] for L in Ls], color="#1E3B5C", linewidth=7,
              alpha=0.35, label="block 8x12")
    ax.vlines(Ls, 0, [dia.get(L, 0) for L in Ls], color="#9B3122", linewidth=2,
              label="diagonal 8x12 — exactly on top of it")
    unc = profiles["uncoded random"]
    ax.plot(sorted(unc), [unc[L] for L in sorted(unc)], color="#2A6247",
            linewidth=1.8, label="uncoded random — flat zero, nothing claimed")
    for L in [L for L in Ls if blk[L] > 0]:
        ax.annotate("L=%d\ndef=%d" % (L, blk[L]), xy=(L, blk[L]),
                    xytext=(L + 4, blk[L] + 4), fontsize=9, color="#1E3B5C")
    ax.set_title("The profile cannot name the family\n"
                 "block and diagonal give identical deficiencies at identical "
                 "row lengths", fontsize=12)
    ax.set_xlabel("Row length L (bits)")
    ax.set_ylabel("Rank deficiency  L − rank(M)")
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=9, loc="upper left")

    # --- panel 2: convolutional steps below its first collapse -----------
    for key, colour in [("convolutional N=4 M=1", "#57398C"),
                        ("convolutional N=6 M=2", "#87621A")]:
        prof = profiles[key]
        Ls2 = sorted(prof)
        first, step = sigs[key]
        ax2.plot(Ls2, [prof[L] for L in Ls2], color=colour, linewidth=1.7,
                 label="%s  →  first %d, step %d" % (key, first, step))
        ax2.axvline(first, color=colour, linestyle=":", linewidth=1.2, alpha=0.8)

    ax2.set_title("Convolutional is the one family the profile does identify: "
                  "step < first\n(a block-like interleaver has step == first, "
                  "its own period)", fontsize=11.5)
    ax2.set_xlabel("Row length L (bits)")
    ax2.set_ylabel("Rank deficiency")
    ax2.grid(alpha=0.25, linestyle=":")
    ax2.legend(fontsize=9, loc="upper left")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    profiles, sigs = build()
    write_csv(profiles, ROOT / "reports" / "interleaver_families.csv")
    write_plot(profiles, sigs, ROOT / "reports" / "interleaver_families.png")
    print()
    print("%-26s %8s %6s   %s" % ("stream", "first", "step", "verdict"))
    for name, (first, step) in sigs.items():
        if first is None:
            verdict = "no collapse — nothing claimed"
        elif step == first:
            verdict = "block-like, period %d" % first
        else:
            verdict = "convolutional, %d branches" % step
        print("%-26s %8s %6s   %s" % (name, first, step, verdict))
