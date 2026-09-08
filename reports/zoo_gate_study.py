"""S4 against Dheeraj's real zoo - the standing job from docs/HANDOFF.md.

    "The moment Dheeraj's zoo lands, delete tests/fixtures/local_zoo.py, point
     the tests at the real corpus, and re-run the gates. Report any number
     that moves."

This is the "re-run the gates and report what moved" half. Nothing here reads
`tests/fixtures/local_zoo.py`; every stream and every parameter comes off disk
from `zoo/corpus/`, and the recovery is never shown the truth.

Regenerate with `python reports/zoo_gate_study.py`.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s4_recover.interleavers  # noqa: F401,E402  (registers families)
from pipeline.s4_recover.rank_collapse import blind_recover  # noqa: E402

CORPUS = ROOT / "zoo" / "corpus" / "bits_only"


def truth_for(npy: Path) -> dict:
    return json.loads(npy.with_suffix("").with_suffix(".json").read_text())


def run_one(npy: Path) -> dict:
    j = truth_for(npy)
    bits = np.load(npy)
    code, il = j.get("code"), j.get("interleaver")
    scr = j.get("scrambler")
    # The uncoded file marks itself {"family": "none"} rather than null.
    if code is not None and code.get("family") in (None, "none"):
        code = None

    t0 = time.time()
    res = blind_recover(bits)
    elapsed = time.time() - t0

    row = {
        "file": npy.name,
        "coded": int(code is not None),
        "scrambled": int(scr is not None),
        "ber": j.get("injected_ber", 0.0),
        "true_period": (il or {}).get("period") or 0,
        "true_depth": (il or {}).get("depth") or 0,
        "true_width": (il or {}).get("width") or 0,
        "status": res.status,
        "confidence": round(res.confidence, 2),
        "method": res.method,
        "got_period": res.period or 0,
        "got_depth": (res.interleaver.params.get("depth", 0)
                      if res.interleaver else 0),
        "got_width": (res.interleaver.params.get("width", 0)
                      if res.interleaver else 0),
        "seconds": round(elapsed, 1),
    }

    if code is None:
        # The false-positive case. Any `ok` here is the failure that matters.
        row["outcome"] = "FALSE POSITIVE" if res.status == "ok" else "declined"
        row["period_ok"] = row["interleaver_ok"] = row["generators_ok"] = 0
        return row

    want_g = tuple(code["polys_octal"])
    row["period_ok"] = int(res.period == row["true_period"])
    row["interleaver_ok"] = int(
        res.interleaver is not None
        and res.interleaver.params.get("depth") == row["true_depth"]
        and res.interleaver.params.get("width") == row["true_width"])
    row["generators_ok"] = int(res.generators_octal == want_g)

    if res.status == "ok" and not (row["interleaver_ok"] and row["generators_ok"]):
        row["outcome"] = "WRONG ANSWER, STATED ok"
    elif row["interleaver_ok"] and row["generators_ok"]:
        row["outcome"] = "full recovery"
    elif res.status == "ok":
        row["outcome"] = "partial, stated ok"
    else:
        row["outcome"] = "declined"
    return row


def main() -> None:
    files = sorted(CORPUS.glob("*.bits.npy"))
    if not files:
        raise SystemExit("no corpus at %s" % CORPUS)
    print("%d bits-only files from the real zoo\n" % len(files))

    rows = []
    for f in files:
        r = run_one(f)
        rows.append(r)
        print("%-44s ber=%-6s scr=%d %-16s %-22s %4.1fs"
              % (r["file"][:44], r["ber"], r["scrambled"], r["status"],
                 r["outcome"], r["seconds"]), flush=True)

    out = ROOT / "reports" / "zoo_gate.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote", out)

    coded = [r for r in rows if r["coded"]]
    clean = [r for r in coded if r["ber"] == 0.0 and not r["scrambled"]]
    noisy = [r for r in coded if r["ber"] > 0.0 and not r["scrambled"]]
    scrambled = [r for r in coded if r["scrambled"]]
    uncoded = [r for r in rows if not r["coded"]]

    def line(label, group, field="interleaver_ok"):
        if not group:
            return
        print("  %-34s %2d/%-3d" % (label, sum(r[field] for r in group), len(group)))

    print("\n--- clean, unscrambled (the 29 Aug / 1 Sep gate) ---")
    line("period recovered", clean, "period_ok")
    line("depth x width recovered", clean, "interleaver_ok")
    line("generators recovered", clean, "generators_ok")

    print("\n--- by injected BER, unscrambled ---")
    for ber in sorted({r["ber"] for r in noisy}):
        sub = [r for r in noisy if r["ber"] == ber]
        print("  BER %-8s full recovery %2d/%-3d   declined %2d   wrong-but-ok %d"
              % (ber, sum(r["interleaver_ok"] and r["generators_ok"] for r in sub),
                 len(sub), sum(r["outcome"] == "declined" for r in sub),
                 sum("WRONG" in r["outcome"] for r in sub)))

    print("\n--- scrambled (known open problem) ---")
    line("full recovery", scrambled, "interleaver_ok")
    print("  %-34s %2d/%-3d" % ("declined or downgraded",
                                sum(r["status"] != "ok" for r in scrambled),
                                len(scrambled)))

    print("\n--- uncoded random (risk #15) ---")
    for r in uncoded:
        print("  %-40s %s -> %s" % (r["file"], r["status"], r["outcome"]))

    wrong = [r for r in rows if "WRONG" in r["outcome"] or "FALSE" in r["outcome"]]
    print("\nCONFIDENTLY WRONG ANSWERS: %d" % len(wrong))
    for r in wrong:
        print("   ", r["file"], r)
    tot = sum(r["seconds"] for r in rows)
    print("total %.0f s, median %.1f s/file"
          % (tot, float(np.median([r["seconds"] for r in rows]))))


if __name__ == "__main__":
    main()
