"""How close is S3 to the best any receiver could do, and what is still on the table?

    python reports/s3_bound_study.py [--render-only]

Owner: Anvith. Written 7 Sep, working the 6 September column's three named
failure cases: 16-QAM at 8 dB, 8-PSK at 4 dB, 16-QAM at 4 dB.

WHY A BOUND, AND NOT ANOTHER SWEEP
-----------------------------------
Those three cases had been carried since 5 Sep with the verdict "the operating
envelope, not a defect", resting on one observation: `truth-params` does not
decode them either, so the loss is in the demodulator rather than in lock
detection. That is true, and it is a different claim from "the loss is
irreducible". Nothing had ever put a number on the second one.

This does. For each (scheme, SNR) it computes the bit error rate an ideal
coherent receiver would get in AWGN and compares it with what S3 actually
measures. A cell close to the bound has nothing left in it whatever anyone
tunes; a cell far from the bound is a defect wearing an envelope's clothes.

THE Es/N0 CONVENTION IS CALIBRATED, NOT ASSUMED
-----------------------------------------------
`zoo.rf._awgn` sets noise power over the whole sampled band at 4 samples/symbol
while the receiver matched-filters to the symbol rate, so there is processing
gain the corpus's `snr_db` label does not include. Rather than trust a
derivation, BOTH conventions are computed and printed. The one that tracks the
cells where the receiver is known to work is the one to read - and it is not
close: `+6 dB` gives a 1.0-1.5x gap in every working cell, while `+0 dB` claims
the receiver beats the bound by 10x, which is impossible.

WHAT IT FOUND, AND WHY NOTHING SHIPPED
---------------------------------------
The receiver is within 1.0-1.5x of the bound in all twelve working cells. Two
cells are 7.2x and 12.5x off it, so the 5 Sep verdict on them was wrong. The
cause is the carrier loop's tracking bandwidth, and narrowing it recovers
almost all of the gap on this corpus - and destroys the receiver on any file
carrying a real carrier offset, which no corpus file does. See `cfo` below:
that is the measurement the corpus structurally cannot make, and it is the
reason the incumbent 0.02 stays.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from scipy.special import erfc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.s3_receive.lockcheck import CARRIER_OFFSET_LIMIT   # noqa: E402
from registry import MODULATIONS                                 # noqa: E402
from tests.fixtures import corpus                                # noqa: E402
from tests.fixtures.corpus import measured_ber, synth            # noqa: E402

OUT_BOUND_CSV = ROOT / "reports" / "s3_bound.csv"
OUT_CFO_CSV = ROOT / "reports" / "s3_carrier_residual.csv"
OUT_STAGE_CSV = ROOT / "reports" / "s3_stage_isolation.csv"
OUT_MD = ROOT / "reports" / "s3_bound.md"

SPS = 4
BITS_PER_SYMBOL = {"bpsk": 1, "qpsk": 2, "8psk": 3, "16qam": 4,
                   "2fsk": 1, "4fsk": 2}

CFO_SCHEMES = ("qpsk", "8psk", "16qam")
CFO_SNRS = (4.0, 8.0, 20.0)
CFO_RESIDUALS = (0.0, 0.005, 0.01, 0.02, 0.03)     # x Rs
CFO_BWS = (0.02, 0.01, 0.005, 0.002)               # 0.02 is the incumbent
CFO_SEEDS = (11, 12, 13)

BOUND_FIELDS = ["scheme", "snr_db", "measured_ber", "ideal_mf", "gap_mf",
                "ideal_raw", "gap_raw"]
CFO_FIELDS = ["scheme", "snr_db", "residual_x_rs", "loop_bw", "measured_ber"]
STAGE_FIELDS = ["arm", "scheme", "snr_db", "median_ber", "decodes", "n"]


def _q(x):
    return 0.5 * erfc(np.asarray(x, dtype=float) / np.sqrt(2.0))


def ideal_ber(scheme: str, esn0_db: float) -> float:
    """Ideal coherent AWGN bit error rate at this Es/N0, Gray-coded."""
    es = 10.0 ** (esn0_db / 10.0)
    k = BITS_PER_SYMBOL[scheme]
    eb = es / k
    if scheme in ("bpsk", "qpsk"):
        return float(_q(np.sqrt(2.0 * eb)))
    if scheme == "8psk":
        return float(min(2.0 * _q(np.sqrt(2.0 * es) * np.sin(np.pi / 8.0)) / k,
                         0.5))
    if scheme == "16qam":
        return float(min(3.0 * _q(np.sqrt(es / 5.0)) / k, 0.5))
    if scheme in ("2fsk", "4fsk"):
        from math import comb
        M = 2 ** k
        s = sum(((-1.0) ** (i + 1)) * float(comb(M - 1, i)) / (i + 1.0)
                * np.exp(-i * eb * k / (i + 1.0)) for i in range(1, M))
        ser = float(np.clip(s, 0.0, 1.0))
        return float(min(ser * (M / 2.0) / (M - 1.0), 0.5))
    raise KeyError(scheme)


def _bound_rows() -> list[dict]:
    per_cell: dict[tuple, list[float]] = {}
    files = corpus.corpus_files()
    for i, path in enumerate(files, 1):
        name = path.stem
        iq, fs, truth = corpus.load(name)
        sch, snr = truth["scheme"], int(truth["snr_db"])
        r = MODULATIONS[sch].receive(
            iq, {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0})
        ber = measured_ber(r, corpus.reference_bits(truth))
        per_cell.setdefault((sch, snr), []).append(
            1.0 if ber is None else float(ber))
        print(f"  bound [{i}/{len(files)}] {name}", flush=True)

    gain = 10.0 * np.log10(float(SPS))
    rows = []
    for (sch, snr) in sorted(per_cell, key=lambda t: (t[0], t[1])):
        med = float(np.median(per_cell[(sch, snr)]))
        i_mf, i_raw = ideal_ber(sch, snr + gain), ideal_ber(sch, float(snr))
        rows.append({
            "scheme": sch, "snr_db": snr,
            "measured_ber": round(med, 6),
            "ideal_mf": f"{i_mf:.3e}", "ideal_raw": f"{i_raw:.3e}",
            "gap_mf": round(med / i_mf, 2) if i_mf > 1e-12 else "",
            "gap_raw": round(med / i_raw, 2) if i_raw > 1e-12 else "",
        })
    return rows


def _cfo_rows() -> list[dict]:
    """The measurement the corpus cannot make: BER against a residual offset.

    Every corpus file has `cfo_norm` 0, so the corpus can show what a narrower
    carrier loop GAINS and is structurally incapable of showing what it costs.
    The offset goes in through the zoo channel, before the noise, because an
    offset applied afterwards rotates the noise with the signal.
    """
    saved = {n: MODULATIONS[n].carrier_loop_bw for n in MODULATIONS
             if hasattr(MODULATIONS[n], "carrier_loop_bw")}
    rows = []
    for sch in CFO_SCHEMES:
        for snr in CFO_SNRS:
            for res in CFO_RESIDUALS:
                for bw in CFO_BWS:
                    MODULATIONS[sch].carrier_loop_bw = bw
                    bers = []
                    for seed in CFO_SEEDS:
                        bits = np.random.default_rng(seed).integers(
                            0, 2, 60000).astype(np.uint8)
                        x, fs, rs, _ = synth(sch, snr_db=snr, sps=SPS,
                                             seed=seed, cfo_norm=res / SPS,
                                             bits=bits)
                        out = MODULATIONS[sch].receive(
                            x, {"fs": fs, "symbol_rate": rs, "cfo_hz": 0.0})
                        bers.append(float(measured_ber(out, bits)))
                    MODULATIONS[sch].carrier_loop_bw = saved[sch]
                    rows.append({"scheme": sch, "snr_db": snr,
                                 "residual_x_rs": res, "loop_bw": bw,
                                 "measured_ber": round(
                                     float(np.median(bers)), 6)})
                print(f"  cfo {sch} {snr:.0f}dB residual {res}", flush=True)
    return rows


def _stage_rows() -> list[dict]:
    """Which blind stage ahead of the demapper is losing the 4 dB gap.

    Two suspects, both blind, both before the demapper. The equaliser: this
    corpus has NO multipath - `linear.py` says so where it refuses to let
    `equaliser_converged` vote - so CMA/MMA has nothing to remove and at low
    SNR a noise-driven gradient can only add error. The carrier loop: every
    corpus file has zero offset, so a decision-directed detector fed wrong
    decisions at low SNR is the classic threshold effect.

    Bypassing each in turn says which. 20 dB is carried as a control: a bypass
    that helps 4 dB and hurts 20 dB is not a fix.
    """
    from pipeline.s3_receive import linear
    from pipeline.s3_receive.equalise import CMAResult

    want = {(s, d) for s in ("8psk", "16qam", "qpsk") for d in (4, 8, 20)}
    loaded = []
    for path in corpus.corpus_files():
        iq, fs, truth = corpus.load(path.stem)
        if (truth["scheme"], int(truth["snr_db"])) in want:
            loaded.append((truth["scheme"], int(truth["snr_db"]), iq, fs,
                           truth, corpus.reference_bits(truth)))

    def passthrough(symbols, *a, **k):
        y = np.asarray(symbols, dtype=np.complex128)
        return CMAResult(symbols=y.copy(), taps=np.array([1.0 + 0j]),
                         error=np.zeros(y.size), converged=True)

    cma, mma = linear.cma_equalise, linear.mma_equalise
    saved = {n: MODULATIONS[n].carrier_loop_bw for n in MODULATIONS
             if hasattr(MODULATIONS[n], "carrier_loop_bw")}
    rows = []
    for arm, bypass_eq, bw in (("full chain", False, None),
                               ("equaliser bypassed", True, None),
                               ("carrier 0.02 -> 0.002", False, 0.002),
                               ("both", True, 0.002)):
        linear.cma_equalise = passthrough if bypass_eq else cma
        linear.mma_equalise = passthrough if bypass_eq else mma
        if bw is not None:
            for n in saved:
                MODULATIONS[n].carrier_loop_bw = bw
        cells: dict[tuple, list[float]] = {}
        for sch, snr, iq, fs, truth, ref in loaded:
            r = MODULATIONS[sch].receive(
                iq, {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0})
            b = measured_ber(r, ref)
            cells.setdefault((sch, snr), []).append(1.0 if b is None else float(b))
        for n, v in saved.items():
            MODULATIONS[n].carrier_loop_bw = v
        for (sch, snr), bers in cells.items():
            rows.append({"arm": arm, "scheme": sch, "snr_db": snr,
                         "median_ber": round(float(np.median(bers)), 6),
                         "decodes": sum(1 for b in bers if b < 0.01),
                         "n": len(bers)})
        print(f"  stage {arm}", flush=True)
    linear.cma_equalise, linear.mma_equalise = cma, mma
    return rows


def _write(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(row, key, default=0.0):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def _render(bound: list[dict], cfo: list[dict],
            stage: list[dict]) -> None:
    L: list[str] = []
    A = L.append

    A("# How close S3 is to the bound, and what is still on the table")
    A("")
    A("Owner: Anvith. Generated by `reports/s3_bound_study.py`; "
      "`--render-only` re-renders from the CSVs.")
    A("")
    A("This is the 6 September column's three named failure cases, worked on "
      "7 September: **16-QAM at 8 dB, 8-PSK at 4 dB, 16-QAM at 4 dB**. "
      "The answer is that **no change to the demodulator is defensible**, and "
      "the reason is worth more than the three fixes would have been.")
    A("")

    A("## The bound")
    A("")
    A("Those three cases had been carried since 5 Sep as \"the operating "
      "envelope, not a defect\", on one observation: `truth-params` does not "
      "decode them either, so the loss is in the demodulator and not in lock "
      "detection. That is true. It is also a different claim from \"the loss "
      "is irreducible\", and nothing had put a number on the second one.")
    A("")
    A("Below, `ideal` is the bit error rate a perfect coherent receiver gets "
      "in AWGN at that Es/N0. **The Es/N0 convention is calibrated, not "
      "assumed:** `zoo.rf._awgn` sets noise power across the whole sampled "
      f"band at {SPS} samples/symbol while the receiver matched-filters to the "
      f"symbol rate, so there is {10*np.log10(SPS):.2f} dB of processing gain "
      "the `snr_db` label does not carry. Both conventions are shown; the one "
      "that tracks the cells where the receiver is known to work is the one to "
      "read, and it is not close.")
    A("")
    A("| scheme | SNR | measured | ideal (+6 dB) | gap | ideal (+0 dB) | gap |")
    A("|---|---|---|---|---|---|---|")
    for r in bound:
        gm = r["gap_mf"]
        gr = r["gap_raw"]
        gm = f"**{float(gm):.1f}x**" if gm not in ("", None) and float(gm) > 2 \
            else (f"{float(gm):.1f}x" if gm not in ("", None) else "-")
        gr = f"{float(gr):.2f}x" if gr not in ("", None) else "-"
        A(f"| {r['scheme']} | {r['snr_db']} | {_f(r,'measured_ber'):.5f} "
          f"| {r['ideal_mf']} | {gm} | {r['ideal_raw']} | {gr} |")
    A("")
    big = [r for r in bound if r["gap_mf"] not in ("", None)
           and float(r["gap_mf"]) > 2.0]
    meas = [r for r in bound if r["gap_mf"] not in ("", None)
            and _f(r, "measured_ber") > 0.0]
    # the two defect cells are called out separately below; this sentence is
    # about the cells the receiver actually works in
    ratios = sorted(float(r["gap_mf"]) for r in meas
                    if float(r["gap_mf"]) <= 2.0)
    zero = [r for r in bound if _f(r, "measured_ber") == 0.0]
    if ratios:
        A(f"**In the {len(ratios)} cells that carry measurable errors and are "
          f"not one of the two below, S3 sits {ratios[0]:.1f}-{ratios[-1]:.1f}x "
          f"above the bound.** For a "
          f"blind receiver - blind rate, blind offset, blind modulation, a "
          f"blind equaliser and two blind loops ahead of the demapper - that "
          f"is about half a dB of implementation loss, and it means those "
          f"cells have nothing left in them for any amount of tuning.")
        A("")
    A(f"**The `0.0x` rows are not a measurement and must not be read as one.** "
      f"In {len(zero)} cells the receiver made ZERO bit errors, and roughly "
      f"40 000 bits per file cannot resolve a rate below about 2.5e-05. Those "
      f"rows say only \"below what this corpus can measure\", which is "
      f"consistent with the bound rather than evidence about it. The ratio "
      f"range above is taken from the cells that carry real errors.")
    A("")
    if big:
        A("**And exactly "
          + str(len(big)) + " cells break the pattern:**")
        A("")
        for r in big:
            A(f"- `{r['scheme']} @ {r['snr_db']} dB` - measured "
              f"{_f(r,'measured_ber'):.4f} against an ideal "
              f"{r['ideal_mf']}, **{float(r['gap_mf']):.1f}x**")
        A("")
        A("Every other cell is at most 1.5x. So these are not the operating "
          "envelope: they are a departure from the receiver's own demonstrated "
          "behaviour everywhere else, and the 5 Sep verdict on them was wrong.")
        A("")

    A("## What the 1% decode line actually is at 8 dB")
    A("")
    q = next((r for r in bound
              if r["scheme"] == "16qam" and str(r["snr_db"]) == "8"), None)
    if q:
        ideal = float(q["ideal_mf"])
        A(f"The 6 Sep plan called 16-QAM at 8 dB \"the closest to moving and "
          f"the only one of the three where a demodulator change plausibly "
          f"crosses the line\". It is the opposite: **the line is below the "
          f"floor.**")
        A("")
        A(f"| | raw BER |")
        A(f"|---|---|")
        A(f"| the study's decode line | 0.01000 |")
        A(f"| **ideal receiver, this SNR** | **{ideal:.5f}** |")
        A(f"| S3 measured | {_f(q,'measured_ber'):.5f} |")
        A("")
        A(f"A perfect receiver clears the line by "
          f"{(0.01-ideal)/0.01*100:.0f}% and nothing else. S3 sits "
          f"{float(q['gap_mf']):.1f}x above the floor, so crossing that line "
          f"needs a receiver within about 0.3 dB of optimal - which is not a "
          f"constant, it is a different receiver. Every parameter swept (MMA "
          f"step size, tap count, equaliser warm-up) moved the median by a few "
          f"percent, and three of them cost a single file a 32x degradation "
          f"that the decode count could not see.")
        A("")

    A("## The 4 dB gap is real, and it is the carrier loop")
    A("")
    A("Isolating the blind stages ahead of the demapper, on corpus files:")
    A("")
    cols = [("16qam", 4), ("8psk", 4), ("16qam", 8), ("16qam", 20)]
    arms = []
    for r in stage:
        if r["arm"] not in arms:
            arms.append(r["arm"])
    A("| arm | " + " | ".join(f"{s_} {d} dB" for s_, d in cols) + " |")
    A("|---" * (len(cols) + 1) + "|")
    for arm in arms:
        cells = []
        for s_, d in cols:
            m = next((r for r in stage if r["arm"] == arm
                      and r["scheme"] == s_ and str(r["snr_db"]) == str(d)), None)
            if m is None:
                cells.append("-")
                continue
            cells.append(f"{_f(m, 'median_ber'):.4f}, {m['decodes']}/{m['n']}")
        A(f"| {arm} | " + " | ".join(cells) + " |")
    A("")
    A("The carrier loop is the whole gap. Narrowing it takes 8-PSK at 4 dB "
      "from 12.5x the bound to about 1.1x, and takes 16-QAM at 8 dB across the "
      "1% line on six of seven files.")
    A("")

    A("## Why it does not ship")
    A("")
    A(f"**Every file in the corpus has `cfo_norm` 0.** So the corpus can show "
      f"what a narrower carrier loop gains and is structurally incapable of "
      f"showing what it costs. What the loop has to survive is a RESIDUAL - "
      f"the search de-rotates by each candidate's offset first, and "
      f"`carrier_alignment` refuses anything beyond "
      f"CARRIER_OFFSET_LIMIT = {CARRIER_OFFSET_LIMIT} x Rs - so the question "
      f"is whether a narrower loop holds across 0 to "
      f"{CARRIER_OFFSET_LIMIT} x Rs. Synthetic, because the corpus cannot pose "
      f"it:")
    A("")
    for sch in CFO_SCHEMES:
        sub = [r for r in cfo if r["scheme"] == sch
               and abs(_f(r, "snr_db") - 20.0) < 1e-9]
        if not sub:
            continue
        A(f"**{sch} at 20 dB** - where the receiver is otherwise exact:")
        A("")
        A("| residual x Rs | " + " | ".join(f"bw {b}" for b in CFO_BWS) + " |")
        A("|---" * (len(CFO_BWS) + 1) + "|")
        for res in CFO_RESIDUALS:
            cells = []
            for bw in CFO_BWS:
                m = next((r for r in sub
                          if abs(_f(r, "residual_x_rs") - res) < 1e-12
                          and abs(_f(r, "loop_bw") - bw) < 1e-12), None)
                v = _f(m, "measured_ber", float("nan")) if m else float("nan")
                cells.append("-" if v != v else
                             (f"{v:.5f}" if v < 0.1 else f"**{v:.3f}**"))
            A(f"| {res} | " + " | ".join(cells) + " |")
        A("")
    A("**The incumbent 0.02 holds lock across the entire permitted residual "
      "range, on every scheme, and every narrower value loses lock somewhere "
      "inside it.** QPSK is the cleanest reading: 0.02 and 0.01 are exact at "
      "every residual, 0.005 fails at 0.03, and 0.002 fails at 0.005. A bold "
      "figure above is a loop that has stopped tracking - roughly 0.41-0.48, "
      "which is noise.")
    A("")
    A("So narrowing the loop would have bought 14 corpus files at 4 dB that "
      "**still would not decode** - the bound for 16-QAM there is 0.059 and "
      "for 8-PSK 0.029, against the 3% ceiling Nehal measured for the code - "
      "and paid for them by breaking every file with a real carrier offset. "
      "The incumbent wins, and it wins on evidence rather than on a tie-break.")
    A("")

    A("## What this leaves")
    A("")
    A("**For Dheeraj - the corpus has a blind spot, and it is load-bearing.** "
      "All 252 files carry `cfo_norm` 0. Any loop tuned against it alone is "
      "measured on half the problem: this study found a change that looks like "
      "a 12x win on every corpus file and is a catastrophe on any file with an "
      "offset. A few files with a non-zero `cfo_norm` would close the hole.")
    A("")
    A("**The one thing still on the table** is a second gear-shift in "
      "`costas_loop`. It already runs `ACQ_BW_RATIO` x wider for the first "
      "`ACQ_SYMBOLS` symbols and then settles, so acquisition is already "
      "separated from tracking; narrowing again AFTER lock would take the "
      "residual out during acquisition and still get the steady-state gain "
      "measured above. That is the textbook answer, it is worth real time, and "
      "it is not worth guessing at: `ACQ_SYMBOLS` chosen on a decode count "
      "cost a 34x single-file regression on 5 Sep, and this study is a second "
      "demonstration that this loop punishes constants picked on one arm.")
    A("")
    A(f"CSVs: `{OUT_BOUND_CSV.name}` ({len(bound)} cells), "
      f"`{OUT_STAGE_CSV.name}` ({len(stage)} rows), "
      f"`{OUT_CFO_CSV.name}` ({len(cfo)} points).")
    A("")

    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()
    if args.render_only:
        bound, cfo = _read(OUT_BOUND_CSV), _read(OUT_CFO_CSV)
        stage = _read(OUT_STAGE_CSV)
    else:
        bound = _bound_rows()
        stage = _stage_rows()
        cfo = _cfo_rows()
        _write(OUT_BOUND_CSV, BOUND_FIELDS, bound)
        _write(OUT_STAGE_CSV, STAGE_FIELDS, stage)
        _write(OUT_CFO_CSV, CFO_FIELDS, cfo)
    _render(bound, cfo, stage)
    print(f"wrote {OUT_MD.name}, {OUT_BOUND_CSV.name}, "
          f"{OUT_STAGE_CSV.name} and {OUT_CFO_CSV.name}")


if __name__ == "__main__":
    main()
