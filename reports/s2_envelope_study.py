"""reports/s2_envelope_study.py

5 Sep -- envelope-vs-SNR study, the mechanism behind the still-open
2fsk/4fsk 0% live-classification gap below 10dB (see s2_coverage.md).

Two envelope statistics are in play, both var(|x|)-based but with
different thresholds because they gate different decisions:

  - models.features.envelope_variance (var/mean**2, threshold 0.05):
    gates whether the IF-histogram peak-finder runs at all when
    extracting classifier features, vs. reporting peak_count=1
    unconditionally. TRIED removing this gate this session (theory:
    envelope_variance is already its own feature, so the classifier
    could learn the cutoff contextually) -- MEASURED to regress real,
    currently-passing behaviour (test_if_hist_peak_count_matches_scheme
    started failing at 15dB, baseline macro-F1 dropped below its
    regression floor, a previously-solid 4fsk-at-15dB classification
    flipped wrong) and REVERTED. See "Why both gates stay fixed" below --
    same root cause as the second statistic.

  - pipeline.s2_estimate's own std(|x|)/mean(|x|) < 0.25 check: decides
    which symbol-rate estimator (constant-envelope-only vs general) S2
    uses on the raw capture, upstream of everything else including which
    `rate` gets handed to the classifier's resampler. Not touched this
    session either, for the same measured reason.

Run: python -m reports.s2_envelope_study
Writes reports/s2_envelope.{csv,md,png}.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pipeline.s0_ingest import ingest
from models.features import envelope_variance

CORPUS = Path(__file__).resolve().parents[1] / "zoo" / "corpus" / "rf"
OUT_CSV = Path(__file__).resolve().parent / "s2_envelope.csv"
OUT_MD = Path(__file__).resolve().parent / "s2_envelope.md"
OUT_PNG = Path(__file__).resolve().parent / "s2_envelope.png"
SCHEMES = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]
COLORS = {"bpsk": "tab:blue", "qpsk": "tab:orange", "8psk": "tab:green",
          "16qam": "tab:red", "2fsk": "tab:purple", "4fsk": "tab:brown"}


def _std_over_mean(iq: np.ndarray) -> float:
    a = np.abs(iq)
    return float(np.std(a) / (np.mean(a) + 1e-30))


def run() -> None:
    rows = []
    ev_by = defaultdict(list)     # var/mean**2 (features.py metric)
    sm_by = defaultdict(list)     # std/mean (s2_estimate.py metric)

    for f in sorted(CORPUS.glob("*.wav")):
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        ev = envelope_variance(r.iq)
        sm = _std_over_mean(r.iq)
        rows.append([f.name, truth["scheme"], truth["snr_db"], ev, sm])
        ev_by[(truth["scheme"], truth["snr_db"])].append(ev)
        sm_by[(truth["scheme"], truth["snr_db"])].append(sm)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "scheme", "snr_db", "envelope_variance", "std_over_mean"])
        w.writerows(rows)

    snrs = sorted({snr for (_s, snr) in ev_by})

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for sch in SCHEMES:
        ev_means = [np.mean(ev_by[(sch, s)]) for s in snrs]
        sm_means = [np.mean(sm_by[(sch, s)]) for s in snrs]
        axes[0].plot(snrs, ev_means, marker="o", label=sch, color=COLORS[sch])
        axes[1].plot(snrs, sm_means, marker="o", label=sch, color=COLORS[sch])

    axes[0].axhline(0.05, color="black", linestyle="--", linewidth=1,
                     label="0.05 (features.py gate, kept -- see report)")
    axes[0].set_title("var(|x|)/mean(|x|)^2 -- models.features.envelope_variance")
    axes[0].set_xlabel("SNR (dB)")
    axes[0].set_ylabel("envelope_variance")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].axhline(0.25, color="black", linestyle="--", linewidth=1,
                     label="0.25 (s2_estimate.py estimator-select gate)")
    axes[1].set_title("std(|x|)/mean(|x|) -- pipeline.s2_estimate constant_envelope check")
    axes[1].set_xlabel("SNR (dB)")
    axes[1].set_ylabel("std/mean")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.suptitle("S2 envelope statistics vs SNR, all 6 schemes -- 5 Sep")
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=130)
    plt.close(fig)

    fsk_max_4db = max(np.mean(sm_by[("2fsk", 4)]), np.mean(sm_by[("4fsk", 4)]))
    psk_min_20db = min(np.mean(sm_by[(s, 20)]) for s in ["bpsk", "qpsk", "8psk", "16qam"])

    lines = [
        "# S2 envelope statistics vs SNR -- 5 Sep\n",
        f"![envelope chart]({OUT_PNG.name})\n",
        "Both panels plot the same underlying quantity (envelope spread "
        "relative to its mean) computed two different ways in this "
        "codebase, against SNR, averaged per scheme over all corpus reps. "
        "Left: `models.features.envelope_variance` (var/mean^2), gates "
        "the IF-histogram peak-finder in the classifier feature "
        "extractor. Right: the raw `std/mean` ratio "
        "`pipeline.s2_estimate.estimate()` computes on the full capture "
        "to pick which symbol-rate estimator to run.\n",
        "## Why the 0-8dB gap exists\n",
        "Both statistics are dominated by additive-noise-induced envelope "
        "spread at low SNR: for a genuinely constant-envelope signal "
        "(2fsk/4fsk, unshaped CPFSK), that spread is close to the *entire* "
        "signal, so it falls steeply and predictably with SNR. For "
        "RRC-shaped PSK/QAM, pulse-shaping itself contributes most of the "
        "spread, so the SNR-dependent term is a smaller fraction of a much "
        "higher floor. Both fixed thresholds (0.05 and 0.25) were "
        "implicitly calibrated at the point where the two curves are "
        "cleanly separated, which is >=10dB -- matching every other gate "
        "in this project.\n",
        "## Why both gates stay fixed (not adaptive, not removed)\n",
        f"Measured on this corpus: FSK's noisiest in-scheme case (2fsk/4fsk "
        f"at 4dB) reaches std/mean={fsk_max_4db:.3f}, while clean PSK/QAM's "
        f"best case (any of bpsk/qpsk/8psk/16qam at 20dB) sits as low as "
        f"{psk_min_20db:.3f} -- **FSK-at-4dB is numerically closer to "
        "constant-envelope than clean-20dB-PSK/QAM is**, by this single "
        "scalar metric. No fixed threshold on this statistic can classify "
        "both correctly, in either direction: raising it enough to catch "
        "low-SNR FSK necessarily starts misclassifying clean high-SNR "
        "PSK/QAM, which today works perfectly (see s2_coverage.md); "
        "removing it entirely (tried on the `models.features` copy of "
        "this gate, see module docstring) is the same trade in the limit "
        "-- measured to regress a deterministic 15dB test and a "
        "previously-solid 4fsk classification. An SNR-adaptive threshold "
        "was considered and rejected too: pipeline.s1_detect.estimate_snr "
        "is itself off by 8-23dB specifically for 4fsk (see its own "
        "docstring), so adaptively thresholding the exact class most "
        "affected on a broken SNR estimate would trade one gap for a "
        "worse one, one day before CORE LOCK. Left as a known, "
        "quantified, low-SNR-only gap -- consistent with every gate in "
        "this project being anchored at >=10dB.\n",
        "## What was tried this session\n",
        "Removed `models.features.if_histogram_features`'s "
        "`envelope_variance(x) >= 0.05` gate (which clamps `peak_count` "
        "to 1 rather than running the peak-finder) on the theory that "
        "envelope_variance is already its own feature, so the trained "
        "classifier could learn the right cutoff contextually instead of "
        "a fixed one. Ungated, real corpus windows at 8dB peak-count "
        "separably (2fsk~2, 4fsk~5, PSK/QAM~1) and the retrained holdout "
        "macro-F1 barely moved (0.720->0.722 overall). But re-running the "
        "full targeted test suite caught what the aggregate holdout "
        "number hid: `test_if_hist_peak_count_matches_scheme` started "
        "failing at 15dB for qpsk/8psk/16qam (spurious peaks, exactly "
        "what the original gate's docstring warned about), "
        "`test_baseline_macro_f1_on_training_set` dropped below its "
        "regression floor, and a previously-solid 4fsk-at-15dB "
        "classification flipped to 2fsk. Reverted; models/features.py's "
        "docstring documents the attempt and the measured reason it "
        "didn't survive testing, same as the 4fsk overfitting "
        "misdiagnosis correction in classifier_eval.md -- a disproven "
        "hypothesis, kept visible rather than silently dropped.\n",
    ]
    OUT_MD.write_text("\n".join(lines))
    print(f"{len(rows)} files -> {OUT_CSV}, {OUT_MD}, {OUT_PNG}")


if __name__ == "__main__":
    run()
