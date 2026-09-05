"""reports/s2_coverage_study.py

Per-scheme coverage matrix for live S2 classification (4 Sep column, item
D) -- top-1 classifier accuracy per scheme x SNR bin, over the full RF
corpus, run through pipeline.s2_estimate.estimate() exactly as S3 would
call it (S2's own symbol-rate estimate feeds the classifier, not truth).

Run: python -m reports.s2_coverage_study
Writes reports/s2_coverage.{csv,md}.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from pipeline.s0_ingest import ingest
from pipeline.s2_estimate import estimate

CORPUS = Path(__file__).resolve().parents[1] / "zoo" / "corpus" / "rf"
OUT_CSV = Path(__file__).resolve().parent / "s2_coverage.csv"
OUT_MD = Path(__file__).resolve().parent / "s2_coverage.md"
SCHEMES = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]


def run() -> None:
    t0 = time.time()
    rows = []
    by_scheme_snr = defaultdict(lambda: [0, 0])
    by_scheme = defaultdict(lambda: [0, 0])

    for f in sorted(CORPUS.glob("*.wav")):
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        result = estimate(r.iq, r.fs)
        top1 = result.modulation_hypotheses[0][0] if result.modulation_hypotheses else None
        top1_prob = result.modulation_hypotheses[0][1] if result.modulation_hypotheses else None
        correct = int(top1 == truth["scheme"])
        rows.append([f.name, truth["scheme"], truth["snr_db"], top1, top1_prob, correct])
        by_scheme_snr[(truth["scheme"], truth["snr_db"])][0] += correct
        by_scheme_snr[(truth["scheme"], truth["snr_db"])][1] += 1
        by_scheme[truth["scheme"]][0] += correct
        by_scheme[truth["scheme"]][1] += 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "true_scheme", "snr_db", "pred_scheme", "pred_prob", "correct"])
        w.writerows(rows)

    snrs = sorted({snr for (_s, snr) in by_scheme_snr})
    lines = [
        "# S2 live-classification coverage matrix -- 4 Sep\n",
        f"pipeline.s2_estimate.estimate() run against all {len(rows)} files in "
        "zoo/corpus/rf/, classifier fed S2's own estimated symbol rate (not "
        "truth). Top-1 accuracy per scheme x SNR.\n",
        "| scheme \\ SNR(dB) | " + " | ".join(str(s) for s in snrs) + " | overall |",
        "|---" * (len(snrs) + 2) + "|",
    ]
    for sch in SCHEMES:
        cells = []
        for snr in snrs:
            c, t = by_scheme_snr[(sch, snr)]
            cells.append(f"{c}/{t}" if t else "-")
        c, t = by_scheme[sch]
        lines.append(f"| {sch} | " + " | ".join(cells) + f" | {c}/{t} ({c/t:.0%}) |")

    lines.append(
        "\n## Reading this table\n\n"
        "bpsk/16qam are perfect; qpsk/8psk solid from 8dB up (both real "
        "improvements from the regularisation fix in "
        "reports/classifier_eval.md's \"Reading the 10dB+ number\" section "
        "-- an overfitting bug, not a missing feature: the model scored "
        "100% on its own training rows for the exact cases it was failing "
        "on in holdout, traced to per-(scheme,SNR)-cell training clusters "
        "as tight as std=0.013 on some features). 2fsk is perfect >=10dB "
        "and 0% below it -- the envelope-variance gate documented in "
        "models/features.py, a *different*, still-open, low-SNR-only gap. "
        "4fsk went from 17% to 52% after the same fix (perfect at 10-15dB, "
        "up from wrong everywhere except exactly 10dB) but is not fully "
        "resolved: 6 of 7 files are wrong at 20dB, though no longer "
        "confidently wrong -- probabilities run 0.4-0.8 for the incorrect "
        "top pick, with 4fsk consistently the #2 hypothesis at 14-42%, so "
        "the ranked-hypothesis design (not just top-1) still carries the "
        "right answer for S3/S4's rank test to recover. This 20dB slice "
        "was never covered by the holdout evaluation (holdout SNRs are "
        "{-3,2.5,7.5,12.5}dB) -- a live-corpus-only finding, not something "
        "the regularisation search was tuned against."
    )
    OUT_MD.write_text("\n".join(lines))
    print(f"{len(rows)} files, {time.time()-t0:.1f}s -> {OUT_CSV}, {OUT_MD}")


if __name__ == "__main__":
    run()
