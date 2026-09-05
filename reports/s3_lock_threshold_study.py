"""The carrier lock threshold, per scheme rather than per family. 5 Sep. Anvith.

    python reports/s3_lock_threshold_study.py               # measure and render
    python reports/s3_lock_threshold_study.py --render-only

WHAT THIS IS FOR

`linear._LOCK_THRESHOLD` is keyed by family - `{"psk": 0.60, "qam": 0.55}` -
and the 252-file corpus says that is one key too coarse. Every 8-PSK file at
8 dB demodulates to a bit error rate of 0.0025-0.0034, which is a working
receiver by any definition this project uses, and every one of them is
reported `low_confidence` because its carrier lock metric reads 0.49-0.52
against the 0.60 that BPSK and QPSK share with it.

That is a false negative in the strict sense: the stage refusing to claim a
demodulation it in fact performed. It costs nothing in this study's decode
count and it costs S4 the whole file, because S4 reads `status` first.

WHY THE FAMILY KEY CANNOT WORK, WHICH IS THE PART WORTH READING

The metric is `|E[u^S]|` with S the constellation's rotational symmetry - 2 for
BPSK, 4 for QPSK, 8 for 8-PSK. Raising a noisy symbol to the S-th power raises
its phase error to the S-th power too, so at a FIXED symbol-error rate the
metric falls as S rises. The three PSK schemes therefore cannot share a number
for the same structural reason `_LOCK_THRESHOLD` already splits PSK from QAM,
one level finer. This study measures that rather than asserting it.

HOW THE THRESHOLD IS CHOSEN, AND WHAT IT IS ALLOWED TO SEE

Every corpus file is run through every linear plug-in at the true symbol rate
with no carrier offset, which gives two populations per scheme:

    admit   the hypothesis is correct AND the run decoded. A threshold that
            refuses one of these is a false negative and costs a real file.
    refuse  a GENUINE failure - wrong hypothesis, or the correct one over a
            stream it demodulated at `GENUINE_FAILURE_BER` or worse. A
            threshold that admits one is a false positive, and those are the
            failures this project counts hardest, because downstream reads
            `status` before it reads anything else.

Runs between the decode line and a genuine failure are in NEITHER, and that
exclusion is the one judgement in this study - see `GENUINE_FAILURE_BER`,
which names the seven files it applies to and what happens to them.

`carrier_locked` is not the only check, so admitting a run is not the same as
the composite verdict returning `ok`. The counts below are recomputed from the
OTHER checks' recorded verdicts at each candidate threshold - a run counts as
admitted only when carrier lock clears the threshold and nothing else vetoed -
so what is being swept is the stage's actual answer and not one check's.

The chosen value is the midpoint of the widest gap between the two
populations, in log terms, which puts the same relative margin either side
rather than favouring whichever population happens to be tighter.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

from pipeline.s3_receive.linear import (_LOCK_THRESHOLD,        # noqa: E402
                                        _LOCK_THRESHOLD_BY_FAMILY,
                                        LinearDemod)
from tests.fixtures.corpus import (corpus_names, load,          # noqa: E402
                                   measured_ber, reference_bits)

OUT_CSV = ROOT / "reports" / "s3_lock_threshold.csv"
OUT_MD = ROOT / "reports" / "s3_lock_threshold.md"

SCHEMES = ["bpsk", "qpsk", "8psk", "16qam"]
DECODE_LIMIT = 0.01
"""Same number as the other two S3 studies, deliberately."""

GENUINE_FAILURE_BER = 0.02
"""A run has to be THIS wrong to count in the `refuse` population.

Between `DECODE_LIMIT` and here is a near-miss band, and on this corpus it
holds exactly one thing: the seven 16-QAM files at 8 dB, which demodulate at
1.17-1.24% raw bit error rate while the receiver estimates its own output at
1.00-1.09%. Calling those lock failures would set a lock threshold from where
a decode line happens to fall through a continuum rather than from anything
the carrier loop did, and it makes 16-QAM unseparable: its worst decoding file
reads 0.784 and its best non-decoding one 0.788. They are reported as their own
row rather than dropped silently, and at every threshold this study chooses
they pass - which is right, since 1.2% is well inside the 3% Nehal measured as
the ceiling for statistical code recovery.
"""

PREVIOUS = {"bpsk": 0.60, "qpsk": 0.60, "8psk": 0.60, "16qam": 0.55}
"""What these were before 5 Sep, written down rather than imported.

`_LOCK_THRESHOLD` is what this study SETS, so reading the before-column out of
it means the comparison quietly becomes "0.30 against 0.30" the moment the
change lands, and the report stops saying what it did. The old values are two
lines of the same file's history and they belong in the report that moved
them.
"""

GRID = [round(x, 3) for x in np.arange(0.05, 0.96, 0.01)]


def _run(name: str) -> list[dict]:
    iq, fs, truth = load(name)
    tx = reference_bits(truth)
    rate = fs / truth["sps"]
    out = []
    for hyp in SCHEMES:
        res = LinearDemod(hyp).receive(
            iq, {"fs": fs, "symbol_rate": rate, "cfo_hz": 0.0})
        v = res.values
        ber = (measured_ber(res, tx)
               if getattr(res, "llrs_by_rotation", None) else 1.0)
        checks = v.get("lock_checks") or {}
        lock = (v.get("lock_metrics") or {}).get("carrier_locked")
        out.append({
            "file": name,
            "true_mod": truth["scheme"],
            "snr_db": float(truth["snr_db"]),
            "hypothesis": hyp,
            "correct": hyp == truth["scheme"],
            "carrier_lock": ("" if lock is None else round(float(lock), 4)),
            "measured_ber": round(float(ber), 6),
            "decodes": bool(ber < DECODE_LIMIT),
            "status": res.status,
            # Every check EXCEPT the one being swept. A run is admitted at a
            # candidate threshold only if none of these failed, so the sweep
            # reports the stage's verdict rather than one check's opinion.
            "other_failed": "|".join(
                n for n, verdict in checks.items()
                if verdict == "fail" and n != "carrier_locked"),
        })
    return out


def _populations(rows, scheme: str) -> tuple[list[float], list[float]]:
    """(admit, refuse) carrier-lock values for one hypothesis scheme.

    TWO EXCLUSIONS, both of which change the answer, so both are stated.

    Runs with no carrier lock value at all are excluded: the chain gave up
    before the carrier loop, so this threshold never saw them and moving it
    cannot change their outcome.

    Runs that another check already vetoed are excluded too, and this one is
    the correction that matters. The first version of this study compared the
    raw populations and reported that qpsk, 8psk and 16qam all overlapped, so
    no threshold separated them - which is true of the statistic and false of
    the stage. A 16-QAM capture read as QPSK reaches a carrier lock of 0.990
    and is refused by `alphabet_used` on the same run; it can never be
    admitted whatever this threshold says, so counting it as something this
    threshold has to exclude sets the number from a case that is already
    closed. What this threshold is responsible for is the runs nothing else
    catches. Those are the populations below.
    """
    admit, refuse = [], []
    for r in rows:
        if (r["hypothesis"] != scheme or r["carrier_lock"] == ""
                or r["other_failed"]):
            continue
        if r["correct"] and r["decodes"]:
            admit.append(float(r["carrier_lock"]))
        elif r["measured_ber"] >= GENUINE_FAILURE_BER:
            refuse.append(float(r["carrier_lock"]))
    return admit, refuse


def _near_miss(rows, scheme: str) -> list[dict]:
    """Runs between the decode line and a genuine failure - in neither
    population, and named here so the exclusion is visible."""
    return [r for r in rows
            if r["hypothesis"] == scheme and r["carrier_lock"] != ""
            and not r["other_failed"] and not (r["correct"] and r["decodes"])
            and r["measured_ber"] < GENUINE_FAILURE_BER]


def _choose(admit, refuse) -> tuple[float | None, str]:
    """Midpoint of the gap between the two populations, in log terms.

    Geometric rather than arithmetic so the same relative margin sits either
    side, instead of favouring whichever population happens to be tighter.

    Returns None when they overlap, because there is then no threshold on this
    statistic that separates them and the honest answer is to say so rather
    than pick the least-bad cut and call it measured.
    """
    if not admit or not refuse:
        return None, "one population is empty"
    lo, hi = min(admit), max(refuse)
    if lo <= hi:
        return None, (f"populations overlap: worst admit {lo:.3f} is at or "
                      f"below best refuse {hi:.3f}")
    return float(np.sqrt(lo * hi)), (
        f"admit >= {lo:.3f}, refuse <= {hi:.3f}, ratio {lo / max(hi, 1e-9):.2f}x")


def _counts(rows, scheme: str, thr: float) -> tuple[int, int, int, int]:
    """(admitted_good, missed_good, admitted_bad, refused_bad) at `thr`.

    `bad` here is a GENUINE failure, the same population `_populations` uses.
    The near-miss band is in neither count; `_near_miss` reports it separately
    rather than letting seven files at 1.2% bit error rate read as seven
    false positives in a table about lock detection.
    """
    ag = mg = ab = rb = 0
    for r in rows:
        if r["hypothesis"] != scheme or r["carrier_lock"] == "":
            continue
        passes = float(r["carrier_lock"]) >= thr and not r["other_failed"]
        if r["correct"] and r["decodes"]:
            ag, mg = (ag + 1, mg) if passes else (ag, mg + 1)
        elif r["measured_ber"] >= GENUINE_FAILURE_BER:
            ab, rb = (ab + 1, rb) if passes else (ab, rb + 1)
    return ag, mg, ab, rb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()

    if args.render_only:
        rows = _load_csv()
    else:
        rows = []
        names = corpus_names()
        for i, name in enumerate(names, 1):
            rows.extend(_run(name))
            if i % 25 == 0 or i == len(names):
                print(f"[{i}/{len(names)}]", flush=True)
        _write_csv(rows)

    _write_markdown(rows)
    print(f"wrote {OUT_CSV.name} and {OUT_MD.name}")
    return 0


FIELDS = ["file", "true_mod", "snr_db", "hypothesis", "correct",
          "carrier_lock", "measured_ber", "decodes", "status", "other_failed"]


def _write_csv(rows) -> None:
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _load_csv() -> list[dict]:
    with open(OUT_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["snr_db"] = float(r["snr_db"])
        r["measured_ber"] = float(r["measured_ber"])
        for k in ("correct", "decodes"):
            r[k] = r[k] in ("True", "true", "1")
    return rows


def _write_markdown(rows) -> None:
    n_files = len({r["file"] for r in rows})
    L = [
        "# The carrier lock threshold, per scheme - 5 Sep", "",
        "**Anvith.** Regenerate with "
        "`python reports/s3_lock_threshold_study.py`. Every one of the "
        f"{n_files} corpus files run through all {len(SCHEMES)} linear "
        "plug-ins at the true symbol rate with no carrier offset, which is "
        f"{n_files * len(SCHEMES)} runs and two populations per scheme.", "",
        "`admit` is a run whose hypothesis was correct **and** which decoded "
        f"under {DECODE_LIMIT:.0%} raw bit error rate - refusing one of those "
        "is a false negative and costs S4 a working file. `refuse` is "
        "everything else. A run counts as admitted only when its carrier lock "
        "clears the threshold **and** no other check vetoed, so these are the "
        "stage's verdicts and not one check's.", "",
        "## The two populations", "",
        "| scheme | incumbent | admit: min / median | refuse: max / median | "
        "gap | chosen |", "|---|---|---|---|---|---|",
    ]
    chosen: dict[str, float | None] = {}
    notes: dict[str, str] = {}
    for s in SCHEMES:
        admit, refuse = _populations(rows, s)
        thr, why = _choose(admit, refuse)
        chosen[s], notes[s] = thr, why
        inc = PREVIOUS[s]
        am = f"{min(admit):.3f} / {np.median(admit):.3f}" if admit else "-"
        rm = f"{max(refuse):.3f} / {np.median(refuse):.3f}" if refuse else "-"
        gap = (f"{min(admit) / max(max(refuse), 1e-9):.2f}x"
               if admit and refuse and min(admit) > max(refuse) else "**overlap**")
        L.append(f"| {s} | {inc:.2f} | {am} | {rm} | {gap} | "
                 + (f"**{thr:.2f}**" if thr is not None else "*none*") + " |")

    L += ["", "## What the change costs and buys", "",
          "`before` is the value this study replaced, written down in "
          "`PREVIOUS` so the comparison survives the change landing. Counts "
          "are runs whose hypothesis was correct and which decoded "
          "(`admitted`), the same minus those this threshold refused "
          "(`missed`), and genuine failures it let through (`wrong`).", "",
          "| scheme | before | after | at before | at after | "
          "false negatives recovered | false positives added |",
          "|---|---|---|---|---|---|---|"]
    for s in SCHEMES:
        inc = PREVIOUS[s]
        ag0, mg0, ab0, _ = _counts(rows, s, inc)
        if chosen[s] is None:
            L.append(f"| {s} | {inc:.2f} | *none* | {ag0} admitted, {mg0} "
                     f"missed, {ab0} wrong | - | - | - |")
            continue
        ag1, mg1, ab1, _ = _counts(rows, s, chosen[s])
        L.append(f"| {s} | {inc:.2f} | **{chosen[s]:.2f}** | "
                 f"{ag0} admitted, {mg0} missed, {ab0} wrong | "
                 f"{ag1} admitted, {mg1} missed, {ab1} wrong | "
                 f"**{ag1 - ag0}** | {ab1 - ab0} |")

    L += ["", "## Per scheme", ""]
    for s in SCHEMES:
        admit, refuse = _populations(rows, s)
        skipped = sum(1 for r in rows
                      if r["hypothesis"] == s and r["carrier_lock"] == "")
        near = _near_miss(rows, s)
        L += [f"### {s}", "",
              f"- {len(admit)} admit, {len(refuse)} refuse, {skipped} runs "
              "gave up before the carrier loop and are in neither.",
              f"- {notes[s]}", ""]
        if near:
            lo = min(float(r["carrier_lock"]) for r in near)
            hi = max(float(r["carrier_lock"]) for r in near)
            bl = min(r["measured_ber"] for r in near)
            bh = max(r["measured_ber"] for r in near)
            verdict = ("all pass" if chosen[s] is not None and lo >= chosen[s]
                       else "NOT all pass - check this")
            L += [f"- **{len(near)} near-miss runs excluded from both**: "
                  f"carrier lock {lo:.3f}..{hi:.3f} at "
                  f"{bl:.4f}..{bh:.4f} raw BER, between the "
                  f"{DECODE_LIMIT:.0%} decode line and the "
                  f"{GENUINE_FAILURE_BER:.0%} genuine-failure line. At the "
                  f"chosen threshold they {verdict}.", ""]
        if admit:
            by_snr = {}
            for r in rows:
                if (r["hypothesis"] == s and r["correct"]
                        and r["carrier_lock"] != ""):
                    by_snr.setdefault(r["snr_db"], []).append(
                        float(r["carrier_lock"]))
            L += ["| SNR | carrier lock, correct hypothesis (min .. max) |",
                  "|---|---|"]
            for snr in sorted(by_snr):
                v = by_snr[snr]
                L.append(f"| {snr:.0f} dB | {min(v):.3f} .. {max(v):.3f} |")
            L.append("")

    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
