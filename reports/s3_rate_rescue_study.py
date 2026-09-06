"""Does the rate rescue find the rate, and can it be fooled? 5 Sep. Anvith.

    python reports/s3_rate_rescue_study.py

`lockcheck.strongest_line` proposes a symbol rate when every rate S2 offered
has already been refused by the presence screen. Two questions decide whether
that is worth having, and they pull in opposite directions:

    1. On a real capture, is the rate it proposes the right one?
    2. On something that is not a signal, does the rate it proposes get
       refused? A rescue that resurrects noise is worse than no rescue: the
       search currently returns `failed` on noise with zero chain runs, and
       that property is load-bearing.

Both are measured here, on the same corpus and the same noise population the
`LINE_ABSENT_LIMIT` docstring in `lockcheck.py` was set from, so the numbers
sit in the same units as the threshold they are argued against.

This study runs no receiver chain. It is FFTs only, which is why it is cheap
enough to re-run on every corpus change.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

from pipeline.s3_receive.lockcheck import (LINE_ABSENT_LIMIT,   # noqa: E402
                                           LINE_PRESENT_LIMIT,
                                           signal_presence, strongest_line)
from tests.fixtures.corpus import corpus_names, load            # noqa: E402

OUT_CSV = ROOT / "reports" / "s3_rate_rescue.csv"
OUT_MD = ROOT / "reports" / "s3_rate_rescue.md"

FAMILY_OF = {"bpsk": "psk", "qpsk": "psk", "8psk": "psk", "16qam": "psk",
             "2fsk": "fsk", "4fsk": "fsk"}

NOISE_DRAWS = 64
NOISE_LENGTHS = [80_000, 200_000, 640_000]
"""Matched to the record lengths the corpus actually uses (79 796 to 638 764
samples), so the noise population is measured where the signal population
lives rather than at a length chosen to flatter it."""


def main() -> int:
    rows = []
    names = corpus_names()
    for i, name in enumerate(names, 1):
        iq, fs, truth = load(name)
        true_rate = fs / truth["sps"]
        # Both branches on every file: the rescue does not know the family
        # either, and the search asks whichever family the candidate came from.
        for family in ("psk", "fsk"):
            got = strongest_line(iq, fs, family)
            rate, score = (got if got is not None else (float("nan"), 0.0))
            rows.append({
                "kind": "corpus",
                "file": name,
                "true_mod": truth["scheme"],
                "true_family": FAMILY_OF[truth["scheme"]],
                "snr_db": float(truth["snr_db"]),
                "family_asked": family,
                "proposed_rate": round(float(rate), 2),
                "true_rate": round(float(true_rate), 2),
                "rel_error": (round(abs(rate - true_rate) / true_rate, 6)
                              if np.isfinite(rate) else ""),
                "score": round(float(score), 3),
                # The safety question, asked exactly as the search asks it: the
                # proposal goes back through the same screen as any other
                # candidate, so what matters is that verdict, not the score.
                "screen": (signal_presence(iq, fs, rate, family).verdict
                           if np.isfinite(rate) else "unknown"),
            })
        if i % 50 == 0 or i == len(names):
            print(f"[{i}/{len(names)}]", flush=True)

    rng = np.random.default_rng(20260905)
    for n in NOISE_LENGTHS:
        for d in range(NOISE_DRAWS):
            x = rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n)
            for family in ("psk", "fsk"):
                got = strongest_line(x, 200_000.0, family)
                rate, score = (got if got is not None
                               else (float("nan"), 0.0))
                rows.append({
                    "kind": f"noise-{n}",
                    "file": f"draw{d}",
                    "true_mod": "", "true_family": "", "snr_db": "",
                    "family_asked": family,
                    "proposed_rate": round(float(rate), 2),
                    "true_rate": "", "rel_error": "",
                    "score": round(float(score), 3),
                    "screen": (signal_presence(x, 200_000.0, rate,
                                               family).verdict
                               if np.isfinite(rate) else "unknown"),
                })
        print(f"noise {n}: done", flush=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    _write_markdown(rows)
    print(f"wrote {OUT_CSV.name} and {OUT_MD.name}")
    return 0


def _write_markdown(rows) -> None:
    corpus_rows = [r for r in rows if r["kind"] == "corpus"]
    noise_rows = [r for r in rows if r["kind"] != "corpus"]
    n_files = len({r["file"] for r in corpus_rows})

    # The case the rescue is actually used in: the family asked is the family
    # the file is. Asking the FSK branch about a PSK file is a question the
    # search only asks while it is still eliminating, and a wrong answer there
    # costs a screen rejection, not a wrong demodulation.
    matched = [r for r in corpus_rows
               if r["family_asked"] == r["true_family"]]
    exact = [r for r in matched if r["rel_error"] != ""
             and float(r["rel_error"]) < 0.01]

    L = [
        "# The rate rescue: what it finds, and what it refuses - 5 Sep", "",
        "**Anvith.** Regenerate with "
        "`python reports/s3_rate_rescue_study.py`. FFTs only, no receiver "
        "chain, so it is cheap to re-run when the corpus changes.", "",
        "## 1. On a real capture, does it find the right rate?", "",
        f"Asking each file's own family, over all {n_files} corpus files:", "",
        f"- **{len(exact)}/{len(matched)}** land within 1% of the true "
        "symbol rate.",
    ]
    errs = [float(r["rel_error"]) for r in matched if r["rel_error"] != ""]
    if errs:
        L.append(f"- Worst relative error {max(errs):.4%}, median "
                 f"{np.median(errs):.4%}.")
    scores = [r["score"] for r in matched]
    if scores:
        L.append(f"- Line score at the proposed rate: {min(scores):.1f} .. "
                 f"{max(scores):.1f}, against a `LINE_PRESENT_LIMIT` of "
                 f"{LINE_PRESENT_LIMIT}.")

    L += ["", "By modulation and SNR - `found/files`, within 1%:", "",
          "| modulation | " + " | ".join(
              f"{s:.0f} dB" for s in sorted(
                  {r["snr_db"] for r in matched})) + " |",
          "|---" * (len(sorted({r["snr_db"] for r in matched})) + 1) + "|"]
    snrs = sorted({r["snr_db"] for r in matched})
    for mod in sorted({r["true_mod"] for r in matched}):
        cells = []
        for s in snrs:
            c = [r for r in matched
                 if r["true_mod"] == mod and r["snr_db"] == s]
            ok = sum(1 for r in c
                     if r["rel_error"] != "" and float(r["rel_error"]) < 0.01)
            cells.append(f"{ok}/{len(c)}" if c else "-")
        L.append(f"| {mod} | " + " | ".join(cells) + " |")

    L += ["", "## 2. On noise, is the proposal refused?", "",
          "The rescue proposes the strongest line in the spectrum, and noise "
          "has a strongest line too. What stops it mattering is that the "
          "proposal re-enters the same presence screen as every other "
          "candidate. So the question is not what score noise reaches - it "
          "is what the screen says about the rate noise proposes.", "",
          "| population | draws | screen `fail` | `unknown` | `pass` | "
          "worst score |", "|---|---|---|---|---|---|"]
    for kind in sorted({r["kind"] for r in noise_rows}):
        rs = [r for r in noise_rows if r["kind"] == kind]
        f = sum(1 for r in rs if r["screen"] == "fail")
        u = sum(1 for r in rs if r["screen"] == "unknown")
        p = sum(1 for r in rs if r["screen"] == "pass")
        L.append(f"| `{kind}` | {len(rs)} | {f} | {u} | **{p}** | "
                 f"{max(r['score'] for r in rs):.2f} |")

    passes = sum(1 for r in noise_rows if r["screen"] == "pass")
    L += ["",
          f"`pass` is the column that matters and it reads **{passes}**. "
          f"`LINE_ABSENT_LIMIT` is {LINE_ABSENT_LIMIT} and "
          f"`LINE_PRESENT_LIMIT` is {LINE_PRESENT_LIMIT}; a proposal landing "
          "in the band between them comes back `unknown`, which does not "
          "veto, so those candidates do reach the chain and are refused by "
          "the checks downstream of it. That is the same path a marginal S2 "
          "rate already took before this existed, and "
          "`test_the_rate_rescue_does_not_let_noise_through` pins the outcome "
          "end to end rather than trusting this table.", ""]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
