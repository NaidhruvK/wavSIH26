"""Decoded BER vs channel BER, for both registered code plug-ins.

    python reports/code_ber_study.py

The second half of the 2 Sep gate ("exact match on 20 streams per code; BER
curve plotted"). Both codes are driven through their own blind recovery first,
so the curves measure the whole path - recover parameters, then decode - not a
decoder handed the answer.

The two codes fail in completely different ways and the chart is worth having
for that alone:

  convolutional   degrades smoothly. Viterbi always returns something, and the
                  output error rate climbs gradually as the channel worsens.
  Reed-Solomon    is a cliff. Below t = (n-k)/2 symbol errors per block it
                  corrects everything exactly; above it the decoder refuses
                  and the block is dropped rather than guessed at.

That cliff is a feature, not a limitation: an RS block either comes back right
or does not come back. It never comes back plausible and wrong.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s4_recover.interleavers  # noqa: F401
import pipeline.s5_decode.conv_code  # noqa: F401
import pipeline.s5_decode.rs_code  # noqa: F401
from registry import CODES
from tests.fixtures.local_zoo import make_rs_stream, make_stream

CONV_BERS = [0.0, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]
RS_BERS = [0.0, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.0075, 0.01]
SEEDS = 5


def conv_curve():
    rows = []
    for ber in CONV_BERS:
        out, recovered = [], 0
        for s in range(SEEDS):
            bits, truth = make_stream(9_000, None, None, ber=ber, seed=4000 + s)
            params = CODES["conv"].blind_recover(bits)
            if params is None:
                continue
            recovered += 1
            dec = CODES["conv"].decode(bits, params)
            src = np.random.default_rng(4000 + s).integers(0, 2, 9_000, dtype=np.uint8)
            n = min(len(dec), len(src))
            out.append(float((dec[:n] != src[:n]).mean()))
        rows.append({"channel_ber": ber,
                     "recovered_fraction": recovered / SEEDS,
                     "decoded_ber": float(np.mean(out)) if out else float("nan")})
        print("conv  BER=%.4f  recovered=%.2f  decoded_BER=%.5f"
              % (ber, rows[-1]["recovered_fraction"], rows[-1]["decoded_ber"]), flush=True)
    return rows


def rs_curve():
    rows = []
    for ber in RS_BERS:
        out, recovered = [], 0
        for s in range(SEEDS):
            bits, truth, payload = make_rs_stream(8, ber=ber, seed=5000 + s)
            params = CODES["reed-solomon"].blind_recover(bits)
            if params is None:
                out.append(0.5)          # nothing recovered = no payload at all
                continue
            recovered += 1
            dec = CODES["reed-solomon"].decode(bits, params)
            got = np.packbits(dec).tobytes()
            ref = payload[:len(got)]
            if not ref:
                out.append(0.5)
                continue
            a = np.unpackbits(np.frombuffer(got[:len(ref)], dtype=np.uint8))
            b = np.unpackbits(np.frombuffer(ref, dtype=np.uint8))
            out.append(float((a != b).mean()))
        rows.append({"channel_ber": ber,
                     "recovered_fraction": recovered / SEEDS,
                     "decoded_ber": float(np.mean(out)) if out else float("nan")})
        print("rs    BER=%.4f  recovered=%.2f  decoded_BER=%.5f"
              % (ber, rows[-1]["recovered_fraction"], rows[-1]["decoded_ber"]), flush=True)
    return rows


def write_csv(conv, rs, path):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "channel_ber", "recovered_fraction", "decoded_ber"])
        for r in conv:
            w.writerow(["conv", r["channel_ber"], r["recovered_fraction"], r["decoded_ber"]])
        for r in rs:
            w.writerow(["reed-solomon", r["channel_ber"], r["recovered_fraction"], r["decoded_ber"]])
    print("wrote", path)


def write_plot(conv, rs, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5.8))
    ax.plot([r["channel_ber"] * 100 for r in conv],
            [max(r["decoded_ber"], 1e-6) * 100 for r in conv],
            marker="o", color="#1E3B5C", linewidth=2, label="convolutional 1/2 K=7 — graceful")
    ax.plot([r["channel_ber"] * 100 for r in rs],
            [max(r["decoded_ber"], 1e-6) * 100 for r in rs],
            marker="s", color="#9B3122", linewidth=2, label="Reed-Solomon (255,223) — cliff")
    lim = max(CONV_BERS) * 100
    ax.plot([0, lim], [0, lim], color="#71777F", linestyle="--", linewidth=1,
            label="uncoded (y = x)")
    ax.set_yscale("log")
    ax.set_xlabel("Channel bit error rate (%)")
    ax.set_ylabel("Decoded bit error rate (%), log scale")
    ax.set_title("Decoded BER after BLIND parameter recovery, both registered codes\n"
                 "each stream is recovered before it is decoded — no parameter is supplied",
                 fontsize=11.5)
    ax.grid(alpha=0.25, linestyle=":", which="both")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("wrote", path)


if __name__ == "__main__":
    conv, rs = conv_curve(), rs_curve()
    write_csv(conv, rs, ROOT / "reports" / "code_ber.csv")
    write_plot(conv, rs, ROOT / "reports" / "code_ber.png")
