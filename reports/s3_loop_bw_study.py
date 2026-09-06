"""Carrier and timing loop bandwidth, swept per modulation. 5 Sep. Anvith.

    python reports/s3_loop_bw_study.py               # measure and render
    python reports/s3_loop_bw_study.py --render-only

Both loops ran at one global bandwidth for every linear scheme until today:
`costas_loop(loop_bw=0.02)` and `gardner_sync(loop_bw=0.004)`. The 5 Sep row
asks for them per modulation. This is the measurement that sets them, and it
drives the real `LinearDemod` chain through its constructor rather than a copy
of the loops, so what is measured is what ships.

WHY THERE ARE TWO ARMS, WHICH IS THE WHOLE METHOD

A loop bandwidth is a trade and a sweep that exercises only one side of it will
report a straight line. Run every file at its true symbol rate with no carrier
offset and the loops have nothing to acquire; the only thing bandwidth can do
is admit detector noise, so the narrowest setting wins every cell and the study
"proves" a number that would fall over on the first real capture.

So each sweep has a `clean` arm and an arm carrying the impairment the loop
exists to remove:

    carrier   clean    true rate, zero offset
              offset   a residual carrier offset of CARRIER_RESIDUAL x Rs,
                       left UNCORRECTED. Sized from `lockcheck`: the alignment
                       check passes any hypothesis whose residual is under
                       CARRIER_OFFSET_LIMIT = 0.03 Rs, so this is an error the
                       pipeline really does hand the Costas loop, not a
                       worst case invented for the chart.

    timing    clean    the record as captured
              phase    the record started half a symbol late, which is
                       precisely what the Gardner loop exists to remove.

THE TIMING ARM WAS WRONG THE FIRST TIME AND THE CORRECTION IS THE INTERESTING
PART. It began as a symbol-rate error of 1%, on the reasoning that
`gardner_sync` accepts up to max_rate_dev = 5% so the loop should track it out.
Every cell of that sweep came back 0/28 - all four schemes, all five
bandwidths, both a wide loop and a narrow one - which is not a measurement of
anything. The cause: a rate error never reaches the timing loop. `signal_presence`
looks for the cyclostationary line at the rate it was GIVEN, on a 2^18-point
spectrum whose bins are 0.76 Hz apart at fs = 200 kHz, so a claimed rate 0.05%
away from the true one is about 33 bins off the line and reads the noise floor.
The chain gives up before the matched filter. Measured directly, on
qpsk_20dB_2011 and 16qam_20dB_2023: 0.01% rate error decodes at BER 0.00000,
0.05% returns `failed`, and so does everything above it.

That is the right behaviour - it is a clean refusal, not a wrong answer, and no
rate error in this range produces a confident lie - but it means the symbol
rate has to be right to about a part in ten thousand, and it makes the rate
S2 hands over binary rather than approximate. It is also why the rate rescue
in `search.py` matters as much as it does: a rate that is 3% wrong is not
slightly worse, it is nothing at all.

A half-symbol start offset is the impairment the timing loop can actually see.
At 4 samples per symbol it is an exact 2-sample slice of the record, so it
needs no resampling and introduces no error of its own.

THE INCUMBENT WINS TIES. A bandwidth replaces the one in `linear.py` only if
it decodes strictly more files across the two arms; equal counts keep the old
value. Without that rule the sweep "recommends" a change wherever the grid is
flat - BPSK decodes 28/28 in every cell of both arms, so any tie-break picks
one for reasons that are a prior rather than a measurement, and a working
number gets moved on no evidence. The report says explicitly where the sweep
had no discriminating power.

WHAT THIS SWEEP CANNOT SEE, AND IT COST A REAL DEFECT. Every run here uses the
CORRECT plug-in for the file. So it measures how well a hypothesis that is
already right performs, and it is blind to how well a hypothesis that is WRONG
performs - which is the thing `lockcheck.alphabet_used` exists to refuse. On
5 Sep this sweep recommended 8-PSK's carrier bandwidth go 0.02 -> 0.04 on a
clean-identical, impaired-better, monotone reading. That change was shipped and
then reverted, because a wider loop also smears a WRONG constellation into
looking right: a QPSK capture through the 8-PSK plug-in went from alphabet
entropy 0.691 (refused) to 0.947 (accepted), and the stage returned `status:
ok` over a stream 48.4% wrong. See `REVERTED` below and
`linear._CARRIER_LOOP_BW`. A recommendation from this file is evidence about
the correct-hypothesis path only, and has to be checked against the
cross-hypothesis study before it is taken.

FSK IS ABSENT ON PURPOSE. `FSKDemod` is a non-coherent tone bank: no Costas
loop, no Gardner loop, nothing here to tune. Its 5 Sep work is the low-SNR
presence statistic, which is a different study.

The sweeps are run one after the other, carrier first, and the timing sweep
uses the carrier bandwidth the first sweep chose. That is coordinate descent,
not a joint optimum, and with two knobs and a monotone-ish response it is the
right cost - but it is worth saying rather than implying a grid search.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

from pipeline.s3_receive.linear import (_CARRIER_LOOP_BW,       # noqa: E402
                                        _TIMING_LOOP_BW,
                                        LinearDemod)
from tests.fixtures.corpus import (corpus_names, load,          # noqa: E402
                                   measured_ber, reference_bits)

OUT_CSV = ROOT / "reports" / "s3_loop_bw.csv"
OUT_MD = ROOT / "reports" / "s3_loop_bw.md"

SCHEMES = ["bpsk", "qpsk", "8psk", "16qam"]

SNR_POINTS = [4.0, 8.0, 10.0, 13.0]
"""Where a loop bandwidth can still change the answer.

15 and 20 dB are excluded from the sweep, not from the confirmation: every
linear file at those levels decodes at every bandwidth tried in a first pass,
so including them adds a third of the runtime to move no cell. The chosen
values are confirmed over the whole corpus by `s3_lock_gate_study.py`, which
is the study that has to hold.
"""

CARRIER_BWS = [0.005, 0.01, 0.02, 0.04, 0.08]
TIMING_BWS = [0.001, 0.002, 0.004, 0.008, 0.016]
"""Two per decade either side of the incumbent (0.02 and 0.004), which are
themselves grid points, so "no change" is a result the sweep can return rather
than a gap between the points it tried."""

CARRIER_RESIDUAL = 0.02
"""Residual carrier offset for the impaired arm, as a fraction of the symbol
rate. Under `lockcheck.CARRIER_OFFSET_LIMIT` (0.03), so it is an offset that
passes the alignment check and reaches the loop, and under `costas_loop`'s
own pull-in range (max_freq 0.25 rad/symbol = 0.04 Rs), so a loop that fails
to remove it failed for want of bandwidth rather than headroom."""

TIMING_OFFSET_SAMPLES = 2
"""Start offset for the impaired timing arm, in samples.

The corpus is 4 samples per symbol throughout, so 2 samples is exactly half a
symbol - the worst case for a timing recovery loop, and the one it exists for.
Slicing rather than resampling means the impairment is exact: the samples are
the ones the zoo wrote, starting two later."""

DECODE_LIMIT = 0.01
"""Same definition as `s3_lock_gate_study.DECODE_LIMIT`, and deliberately the
same number: two studies of one receiver that disagree about what counts as
working are two studies nobody can put side by side."""

REVERTED = {
    ("carrier", "8psk"): (
        0.04,
        "Shipped 5 Sep and reverted the same evening. This sweep still "
        "recommends it and this sweep is still wrong, for a reason it cannot "
        "measure: it only ever runs the correct plug-in. A QPSK capture "
        "through the 8-PSK plug-in reads alphabet entropy 0.691 at 0.02 "
        "(refused) and 0.947 at 0.04 (accepted), so at 0.04 `qpsk_8dB_2007` "
        "comes back `status: ok`, self-estimating 0.0035, over a stream that "
        "is 48.4% wrong. One file gained on the impaired arm is not worth "
        "blinding the subset-trap check. See `linear._CARRIER_LOOP_BW`."),
    ("carrier", "16qam"): (
        0.04,
        "It reaches 13/28 on the impaired arm against 9/28, and "
        "costs `16qam_10dB_4020` on the clean arm - raw BER 0.0029 -> 0.0299. "
        "That is a 10 dB file, and >=10 dB is the region the day gate is "
        "written on, so a measured corpus file is not traded for an injected "
        "scenario. The acquisition gear-shift recovers most of the same gap "
        "(1/28 -> 9/28) without costing anything."),
    ("timing", "16qam"): (
        0.002,
        "The clean-arm grid reads 12/14/13/14/13 with median BER "
        "0.020/0.009/0.015/0.009/0.019 - non-monotone across a 16x range. A "
        "response that alternates is not an optimum at 0.002, it is a "
        "response with no reliable signal in it, and the +1 sits inside that "
        "scatter. Picking the best cell of an alternating sequence fits this "
        "corpus rather than tuning a loop."),
}
"""Values this sweep recommends that were measured, tried and rejected.

Kept as data rather than deleted from the grid, because a study that quietly
stops reporting an option it once recommended is a study whose reader cannot
tell the difference between "never considered" and "considered and refused".
"""


def _files() -> list[tuple[str, str, float]]:
    """(name, scheme, snr) for every corpus file this sweep uses."""
    out = []
    for name in corpus_names():
        _, _, truth = load(name)
        if truth["scheme"] in SCHEMES and float(truth["snr_db"]) in SNR_POINTS:
            out.append((name, truth["scheme"], float(truth["snr_db"])))
    return out


def _run_one(name: str, scheme: str, arm: str,
             carrier_bw: float, timing_bw: float) -> dict:
    iq, fs, truth = load(name)
    tx = reference_bits(truth)
    rate = fs / truth["sps"]

    if arm == "offset":
        # Left uncorrected: the receiver is told the offset is zero, so the
        # Costas loop is the only thing that can remove it. Applying it here
        # and also declaring it would measure nothing.
        iq = iq * np.exp(2j * np.pi * (CARRIER_RESIDUAL * rate / fs)
                         * np.arange(iq.size))
        claimed_rate = rate
    elif arm == "phase":
        iq = iq[TIMING_OFFSET_SAMPLES:]
        claimed_rate = rate
    else:
        claimed_rate = rate

    plug = LinearDemod(scheme, carrier_loop_bw=carrier_bw,
                       timing_loop_bw=timing_bw)
    t0 = time.perf_counter()
    res = plug.receive(iq, {"fs": fs, "symbol_rate": claimed_rate,
                            "cfo_hz": 0.0})
    secs = time.perf_counter() - t0

    ber = measured_ber(res, tx) if getattr(res, "llrs_by_rotation", None) else 1.0
    return {
        "scheme": scheme,
        "file": name,
        "snr_db": float(truth["snr_db"]),
        "arm": arm,
        "carrier_bw": carrier_bw,
        "timing_bw": timing_bw,
        "status": res.status,
        "measured_ber": round(float(ber), 6),
        "decodes": bool(ber < DECODE_LIMIT),
        "secs": round(secs, 3),
    }


def _sweep(files, knob: str, grid, fixed: dict, incumbent: dict,
           rows: list) -> dict[str, float]:
    """One knob over its grid, per scheme, and the value each scheme picks.

    `fixed` is the OTHER knob's bandwidth, held constant while this one moves.
    `incumbent` is THIS knob's current value in `linear.py`, which is what a
    candidate has to beat. They are separate arguments because conflating them
    is a silent bug rather than a loud one: `_pick` would be handed a value
    that appears in no row, `total()` of it would return 0, and every scheme
    would "improve" on nothing at all - which is precisely the tie-breaking
    this rule exists to prevent.
    """
    arms = ["clean", "offset"] if knob == "carrier" else ["clean", "phase"]
    total = len(files) * len(grid) * len(arms)
    done = 0
    for bw in grid:
        for arm in arms:
            for name, scheme, _ in files:
                c = bw if knob == "carrier" else fixed[scheme]
                t = bw if knob == "timing" else fixed[scheme]
                rows.append(dict(_run_one(name, scheme, arm, c, t), knob=knob))
                done += 1
            print(f"  {knob} bw={bw} {arm}: {done}/{total}", flush=True)
    return {s: _pick(rows, knob, s, grid, incumbent[s]) for s in SCHEMES}


def _pick(rows, knob: str, scheme: str, grid, incumbent: float) -> float:
    """The rule, stated once and applied to every scheme identically.

    Rank on total decodes across both arms, because that is the quantity the
    day gate is written in - and require a STRICT improvement over the value
    already in `linear.py` before moving it.

    The strictness is the whole rule. A sweep ranked on decodes alone has ties
    wherever the grid is flat, and any tie-break then returns a
    recommendation: rank by median bit error rate and a rounding difference
    decides, rank by narrower-is-better and every flat row moves toward the
    edge of the grid. BPSK decodes 28/28 in all ten of its cells. There is
    nothing in that to choose from, and the honest output is "no change", not
    the smallest number in the list.
    """
    def total(bw) -> int:
        return sum(r["decodes"] for r in rows
                   if r["knob"] == knob and r["scheme"] == scheme
                   and r[f"{knob}_bw"] == bw)

    best, best_n = incumbent, total(incumbent)
    for bw in grid:
        if total(bw) > best_n:
            best, best_n = bw, total(bw)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()

    if args.render_only:
        rows = _load_csv()
    else:
        files = _files()
        print(f"{len(files)} files, {len(SCHEMES)} schemes", flush=True)
        rows: list[dict] = []
        carrier = _sweep(files, "carrier", CARRIER_BWS,
                         fixed=dict(_TIMING_LOOP_BW),
                         incumbent=dict(_CARRIER_LOOP_BW), rows=rows)
        print(f"carrier picks: {carrier}", flush=True)
        timing = _sweep(files, "timing", TIMING_BWS,
                        fixed=carrier, incumbent=dict(_TIMING_LOOP_BW),
                        rows=rows)
        print(f"timing picks: {timing}", flush=True)
        _write_csv(rows)

    _write_markdown(rows)
    print(f"wrote {OUT_CSV.name} and {OUT_MD.name}")
    return 0


FIELDS = ["knob", "scheme", "file", "snr_db", "arm", "carrier_bw", "timing_bw",
          "status", "measured_ber", "decodes", "secs"]


def _write_csv(rows) -> None:
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _load_csv() -> list[dict]:
    with open(OUT_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("snr_db", "carrier_bw", "timing_bw", "measured_ber", "secs"):
            r[k] = float(r[k])
        r["decodes"] = r["decodes"] in ("True", "true", "1")
    return rows


def _write_markdown(rows) -> None:
    L = [
        "# Loop bandwidths, per modulation - 5 Sep", "",
        "**Anvith.** Regenerate with `python reports/s3_loop_bw_study.py`. "
        "Both loops ran at one global bandwidth for every linear scheme until "
        "today; this is the sweep that replaces them, or declines to.", "",
        "**The grid below measures a SINGLE-SPEED carrier loop, which is what "
        "`costas_loop` was when the sweep ran.** Its most useful result was "
        "not a bandwidth: it was that 16-QAM handed a residual offset of "
        "0.02 x Rs - one `lockcheck.CARRIER_OFFSET_LIMIT` explicitly permits - "
        "decoded **1 of 28** files at every bandwidth that did not also cost "
        "clean files. That is an acquisition problem, not a tracking one, and "
        "`gardner_sync` had already solved the same problem years of "
        "convention earlier by gear-shifting. `costas_loop` now does too "
        "(`carrier.ACQ_SYMBOLS`, 4x for 100 symbols, both measured, and "
        "the 100 chosen on a per-file regression check rather than a decode "
        "count - see that constant), "
        "and with it the same 16-QAM cell reads **9/28 on the impaired arm "
        "with the clean arm unchanged at 14/28**. Re-running this study now "
        "would measure the gear-shifted loop; the tables below are kept as "
        "the single-speed measurement that motivated it, which is the honest "
        "before-column and the one the next sweep should be read against.", "",
        "Confirmed across all four schemes after the change, same two arms, "
        "single-speed count in brackets:", "",
        "| scheme | bw | clean | offset |", "|---|---|---|---|",
        "| bpsk | 0.02 | 28/28 (28) | 28/28 (28) |",
        "| qpsk | 0.02 | 28/28 (28) | 28/28 (28) |",
        "| **8psk** | **0.02** | 21/28 (21) | 20/28 (18) |",
        "| **16qam** | **0.02** | **14/28** (14) | **9/28** (1) |",
        "| 16qam | 0.04 | 13/28 (13) | 13/28 (11) |", "",
        f"Each cell is `decodes/files` over {len(SNR_POINTS)} SNR points "
        f"({', '.join(f'{s:.0f}' for s in SNR_POINTS)} dB) x 7 seeds. The "
        "incumbent value is **bold**; the value this study chooses is marked "
        "`<-`. FSK is not here: its plug-in is a non-coherent tone bank with "
        "neither loop in it.", "",
    ]

    for knob, grid, incumbent, arms in (
            ("carrier", CARRIER_BWS, _CARRIER_LOOP_BW, ["clean", "offset"]),
            ("timing", TIMING_BWS, _TIMING_LOOP_BW, ["clean", "phase"])):
        krows = [r for r in rows if r["knob"] == knob]
        if not krows:
            continue
        picks = {s: _pick(rows, knob, s, grid, incumbent[s]) for s in SCHEMES}
        impaired = arms[1]
        L += [
            f"## The {knob} loop", "",
            f"Impaired arm: `{impaired}` - "
            + (f"a residual carrier offset of {CARRIER_RESIDUAL:.2f} x Rs, "
               "left for the loop to remove."
               if knob == "carrier" else
               f"the record started {TIMING_OFFSET_SAMPLES} samples late - "
               "half a symbol at this corpus's 4 samples per symbol - left "
               "for the loop to find."), "",
            "| scheme | arm | " + " | ".join(f"{g:g}" for g in grid)
            + " | picked |",
            "|---" * (len(grid) + 3) + "|",
        ]
        for scheme in SCHEMES:
            for arm in arms:
                cells = []
                for bw in grid:
                    rs = [r for r in krows if r["scheme"] == scheme
                          and r["arm"] == arm and r[f"{knob}_bw"] == bw]
                    dec = sum(r["decodes"] for r in rs)
                    cell = f"{dec}/{len(rs)}" if rs else "-"
                    if abs(bw - incumbent.get(scheme, -1)) < 1e-12:
                        cell = f"**{cell}**"
                    if abs(bw - (picks[scheme] or -1)) < 1e-12:
                        cell = f"{cell} `<-`"
                    cells.append(cell)
                tail = (f"**{picks[scheme]:g}**" if arm == arms[0] else "")
                L.append(f"| {scheme} | {arm} | " + " | ".join(cells)
                         + f" | {tail} |")
        L += ["", "Changes this sweep asks for:", ""]
        overridden = set()
        for scheme in SCHEMES:
            note = REVERTED.get((knob, scheme))
            if note and picks[scheme] is not None and abs(picks[scheme] - note[0]) < 1e-12:
                overridden.add(scheme)
                L += [f"- **{scheme}: {note[0]:g} — recommended here, NOT "
                      f"TAKEN.** {note[1]}", ""]
        changed = [s for s in SCHEMES
                   if s not in overridden and picks[s] is not None
                   and abs(picks[s] - incumbent.get(s, -1)) > 1e-12]
        if changed:
            for s in changed:
                L.append(f"- **{s}**: {incumbent[s]:g} -> {picks[s]:g}")
        elif overridden:
            L.append("- none beyond the override(s) above. Every other "
                     "scheme's incumbent value survived the sweep, which is a "
                     "result and not a null one.")
        else:
            L.append("- none. Every scheme's incumbent value survived the "
                     "sweep, which is a result and not a null one: the "
                     "global number was already the right one for each of "
                     "them, and now that is measured rather than assumed.")
        L.append("")

    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
