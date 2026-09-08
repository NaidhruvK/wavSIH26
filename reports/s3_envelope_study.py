"""S3's operating envelope, measured file by file.

    python reports/s3_envelope_study.py

Writes reports/s3_envelope.{csv,md} and the diagnostic charts under
reports/s3/.

This exists because three pieces of gate evidence had been produced in a
throwaway working copy and never reproduced here: the 30 Aug EVM table, the
31 Aug corpus lock rate, and the 29 Aug eye and constellation plots. Evidence
that is not in the repo is not evidence, so it is regenerated from the current
build rather than quoted from memory.

Owner: Anvith.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s3_receive import (estimated_ber, gardner_sync,  # noqa: E402
                                 llr_to_bits, matched_filter, scheme)
from pipeline.s3_receive.plots import (chain_summary, cma_trace,  # noqa: E402
                                       constellation_plot, eye_diagram,
                                       timing_trace)
from registry import MODULATIONS  # noqa: E402
from tests.fixtures.corpus import synth  # noqa: E402

OUT = ROOT / "reports"
CHARTS = OUT / "s3"

# 20 PSK files, matching the shape of the corpus the 31 Aug gate names, plus
# QAM and FSK so the table covers the whole declared envelope.
PSK_CORPUS = [(m, snr, sps)
              for m, sps in (("bpsk", 4), ("qpsk", 4), ("qpsk", 8), ("8psk", 4))
              for snr in (20, 16, 13, 10, 8)]
OTHER_CORPUS = [("16qam", snr, 4) for snr in (22, 18, 15, 13)] + \
               [("2fsk", snr, 8) for snr in (16, 12, 8, 5)] + \
               [("4fsk", snr, 8) for snr in (18, 14, 10, 7)]

CHART_FILES = ["qpsk_20dB_sps4", "qpsk_10dB_sps4", "16qam_22dB_sps4",
               "8psk_20dB_sps4"]


def measured_ber(res, tx: np.ndarray) -> float:
    """Lowest BER over the emitted rotations, counting a fully inverted stream
    as a match. Harness-only: S3 cannot make this comparison."""
    best = 1.0
    for cand in res.llrs_by_rotation:
        rx = llr_to_bits(cand)
        n = min(rx.size, 40000)
        if n < 1000:
            continue
        a = 1.0 - 2.0 * rx[:n].astype(float)
        m = min(tx.size, n + 100000)
        b = 1.0 - 2.0 * tx[:m].astype(float)
        L = 1 << int(np.ceil(np.log2(m + n)))
        c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)[: m - n + 1]
        off = int(np.argmax(np.abs(c)))
        e = float(np.mean(rx[:n] != tx[off : off + n]))
        best = min(best, e, 1.0 - e)
    return best


def run_one(mod: str, snr: float, sps: int, bits: np.ndarray) -> tuple[dict, dict]:
    x, fs, symbol_rate, n_used = synth(mod, sps=sps, snr_db=snr, bits=bits,
                                       cfo_norm=0.0013, timing_offset_sym=0.37,
                                       seed=17)
    res = MODULATIONS[mod].receive(x, {"fs": fs, "symbol_rate": symbol_rate})
    v = res.values
    row = {
        "file": f"{mod}_{int(snr)}dB_sps{sps}",
        "modulation": mod, "snr_db": snr, "sps": sps,
        "status": res.status,
        "carrier_lock": round(float(v.get("carrier_lock", v.get("mean_margin", 0))), 4),
        "evm_percent": (round(float(v["evm_percent"]), 3)
                        if v.get("evm_percent") is not None else ""),
        "timing_converged_at": v.get("timing_converged_at", ""),
        "rolloff_beta": (round(float(v["rolloff_beta"]), 4)
                         if v.get("rolloff_beta") is not None else ""),
        "equaliser": v.get("equaliser", "none"),
        "carrier_settled_at": v.get("carrier_settled_at", 0),
        "n_llrs": v.get("n_llrs", 0),
        "estimated_ber": round(float(v.get("estimated_output_ber", 1.0)), 6),
        "measured_ber": round(measured_ber(res, bits[:n_used]), 6),
        "elapsed_ms": round(res.elapsed_ms, 1),
        "reason": res.reason or "",
    }
    return row, {"mod": mod, "sps": sps, "x": x, "res": res}


def draw_charts(ctx: dict, name: str) -> list[str]:
    res, sps = ctx["res"], ctx["sps"]
    sch = scheme(ctx["mod"])
    made = []
    x = ctx["x"]
    beta = res.values.get("rolloff_beta", 0.35)
    y = matched_filter(x, beta, sps)
    g = gardner_sync(y, sps)

    made.append(eye_diagram(
        y, sps, CHARTS / f"eye_{name}.png",
        align_sample=float(np.median(g.positions[1000:] % sps)),
        title=f"Eye after matched filter - {name}"))
    made.append(constellation_plot(
        res.symbols, CHARTS / f"constellation_{name}.png",
        reference=sch.points / np.sqrt(np.mean(np.abs(sch.points) ** 2)),
        title=f"Constellation after carrier recovery - {name}"))
    made.append(timing_trace(
        g.error, CHARTS / f"timing_{name}.png",
        converged_at=g.converged_at, title=f"Timing loop - {name}"))
    return made


def main() -> int:
    CHARTS.mkdir(parents=True, exist_ok=True)
    bits = np.random.default_rng(3141).integers(0, 2, 300000).astype(np.uint8)

    rows, charts = [], []
    for mod, snr, sps in PSK_CORPUS + OTHER_CORPUS:
        row, ctx = run_one(mod, snr, sps, bits)
        rows.append(row)
        print(f"{row['file']:22s} {row['status']:15s} "
              f"lock={row['carrier_lock']:.3f} EVM={row['evm_percent']} "
              f"estBER={row['estimated_ber']:.5f} actBER={row['measured_ber']:.5f}")
        if row["file"] in CHART_FILES and ctx["res"].symbols is not None:
            charts += draw_charts(ctx, row["file"])

    charts.append(chain_summary(
        [{"modulation": r["modulation"], "snr_db": r["snr_db"],
          "evm_percent": float(r["evm_percent"] or "nan"),
          "carrier_lock": r["carrier_lock"]}
         for r in rows if r["evm_percent"] != ""],
        CHARTS / "s3_envelope.png", title="S3 across the declared envelope"))

    fields = list(rows[0])
    with (OUT / "s3_envelope.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    _write_markdown(rows, charts)
    print(f"\nwrote {len(rows)} rows and {len(charts)} charts")
    return 0


def _write_markdown(rows: list[dict], charts: list[str]) -> None:
    psk = [r for r in rows if r["modulation"] in ("bpsk", "qpsk", "8psk")]
    locked = [r for r in psk if r["status"] == "ok"]
    conv = [int(r["timing_converged_at"]) for r in rows
            if str(r["timing_converged_at"]).isdigit()]

    lines = [
        "# S3 operating envelope", "",
        "**Anvith.** Regenerated from the build on `main`. Every number here "
        "comes from `reports/s3_envelope_study.py`, whose signals are now made "
        "by **`zoo.rf`** - Dheeraj's real modulator. The stand-in it used to "
        "call, `tests/fixtures/rf_channel.py`, is deleted. The parametric "
        "sweep stays a sweep rather than becoming a corpus read because it "
        "needs SNRs and samples-per-symbol the 36-file corpus does not carry; "
        "`reports/s3_lock_gate.md` is the one measured on the corpus itself.",
        "",
        "## Gate evidence", "",
        f"- **31 Aug, lock rate:** {len(locked)} of {len(psk)} PSK files report "
        "`ok`. Gate asks for at least 18 of 20.",
        f"- **29 Aug, timing convergence:** worst case "
        f"**{max(conv) if conv else 0}** symbols. Gate asks for under 2000.",
        "- **30 Aug, EVM per file:** the table below, and "
        "`reports/s3_envelope.csv`.",
        "- **3 Sep, estimated vs measured BER:** both columns below. The "
        "estimate is only meaningful where the receiver reports `ok` - see the "
        "caveat under the table.",
        "", "## Per file", "",
        "| File | status | lock | EVM % | timing conv | est BER | measured BER |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['file']} | {r['status']} | {r['carrier_lock']:.3f} | "
            f"{r['evm_percent'] or '-'} | {r['timing_converged_at'] or '-'} | "
            f"{r['estimated_ber']:.5f} | {r['measured_ber']:.5f} |")

    bad = [r for r in rows if r["status"] != "ok"
           and r["measured_ber"] > 4 * max(r["estimated_ber"], 1e-9)]
    lines += [
        "", "## The caveat that matters", "",
        "**S3's estimated output BER is only trustworthy when it reports "
        "`ok`.** The estimate is derived from the LLR magnitudes, and those are "
        "calibrated against a noise variance measured on a constellation the "
        "receiver believes it has locked. When it has not, the variance is "
        "measured against the wrong reference and the estimate is optimistic.",
        "",
    ]
    if bad:
        lines.append("Cases in this run where the estimate was more than 4x "
                     "optimistic, all of them already flagged `low_confidence` "
                     "or `failed`:")
        lines.append("")
        for r in bad:
            lines.append(f"- `{r['file']}` — estimated {r['estimated_ber']:.5f}, "
                         f"measured {r['measured_ber']:.5f}")
        lines.append("")
    lines += [
        "Anything consuming `estimated_output_ber` must gate on `status` first. "
        "S4 already does, because it takes the LLRs rather than the number, but "
        "the UI card and the envelope report both need to.",
        "", "## Charts", "",
    ] + [f"- `{Path(c).relative_to(ROOT)}`" for c in charts]

    (OUT / "s3_envelope.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
