"""Are S3's LLRs calibrated per-bit, or only on average?

7 September. Written as the premise check under the LDPC decode path
(`reports/s3_ldpc_design.md`), because that path is the first consumer in this
project that would care about the answer.

WHY THIS IS A DIFFERENT QUESTION FROM THE ONE ALREADY ANSWERED
--------------------------------------------------------------
`softmap.estimated_ber` already turns the stream into a predicted error rate,

    P(bit i is wrong) = 1 / (1 + exp(|llr_i|))          [calibrated LLRs]

and the 3 Sep contract pins the MEAN of that against the measured bit error
rate to within a factor of two. That is an aggregate statement, and every
consumer S3 has today is happy with an aggregate statement:

  * Viterbi (`s5_decode/conv_code.py`) maximises a path metric that is a SUM of
    LLRs. Scale every LLR by any positive constant and the arg-max is
    unchanged - the decoder is scale-invariant, so a uniformly over-confident
    demapper costs it nothing.
  * Reed-Solomon (`s5_decode/rs_code.py`) works on hard symbols. It sees only
    `llr < 0`.
  * S4's rank collapse hard-slices by construction: rank over GF(2) has no
    partially-dependent row.

Sum-product belief propagation does not have that invariance. A check node
combines its inputs through

    tanh(L_out / 2) = prod_j tanh(L_j / 2)

and `tanh` is neither linear nor scale-free, so the MAGNITUDES are load
bearing, not just the signs and the ordering. Over-confident inputs make BP
lock onto a wrong codeword and stop; under-confident inputs cost coding gain.
An LDPC path therefore asks S3 for something no existing consumer has asked
for, and nothing in the repo has measured it.

The aggregate can be right while the distribution is wrong - that is the whole
point. A demapper that is over-confident on its strong bits and under-confident
on its weak ones has a correct mean predicted BER and a useless reliability
curve. So this study bins by |LLR| and asks, inside each bin, whether the bits
really do go wrong at the promised rate.

THE KNOWN-ANSWER CHECK, INSIDE THE TABLE
----------------------------------------
Five times this week a study here measured something other than its title, and
what caught it every time was a cell whose answer was already known. The one
built into this study is the `agg_` pair of columns: aggregating this script's
own per-bit error labels must reproduce `corpus.measured_ber` and
`softmap.estimated_ber`, both computed by the repo's own functions on the same
result. If `agg_empirical` and `repo_measured_ber` disagree, the alignment or
the rotation choice is wrong and every calibration number below is noise. Look
at those two columns FIRST.

WHERE THIS STUDY HAS NO POWER, SAID OUT LOUD
--------------------------------------------
Predicted error rate at |LLR| = 8 is 3.4e-4 and at |LLR| = 16 it is 1.1e-7.
With ~40 000 bits per file a high-confidence bin contains no errors at all,
and zero errors out of 40 000 is consistent with the prediction and with a
prediction ten times smaller. Those bins are reported and explicitly NOT
scored: `verdict` reads `no-power`, never `pass`. A check that cannot see must
say so.

Run:
    ./.venv/Scripts/python.exe reports/s3_llr_calibration_study.py
    ./.venv/Scripts/python.exe reports/s3_llr_calibration_study.py --render-only
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s3_receive.softmap import estimated_ber, llr_to_bits  # noqa: E402
from registry import MODULATIONS  # noqa: E402
from tests.fixtures.corpus import (align, corpus_names, load,  # noqa: E402
                                   measured_ber, reference_bits)

CSV_PATH = ROOT / "reports" / "s3_llr_calibration.csv"
MD_PATH = ROOT / "reports" / "s3_llr_calibration.md"

# |LLR| bin edges. The top bin is open. Everything at or above 8 is reported
# and not scored - see the docstring.
BIN_EDGES = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, math.inf]

SCORABLE_MAX_EDGE = 8.0
"""A bin whose lower edge is at or above this is never given a verdict.

1/(1+exp(8)) = 3.4e-4, so the expected error count in such a bin is under 14
even if the bin held every bit of a 40 000-bit file. Observing zero of them
separates nothing.
"""

MIN_ERRORS_TO_SCORE = 20
"""Below this many observed errors a bin gets `no-power` rather than a verdict.

At 20 errors the relative standard error of a Poisson count is 1/sqrt(20) =
22%, so a ratio can be called outside [0.5, 2.0] and not outside [0.8, 1.25].
The band below is set accordingly.
"""

CALIBRATED_BAND = (0.5, 2.0)
"""empirical / predicted inside this reads `ok`.

The same factor of two the 3 Sep contract already applies to the aggregate,
kept deliberately rather than tightened: a per-bin claim cannot be stricter
than the aggregate claim it has to sit under, and 20 errors will not support
a tighter one anyway.
"""

# One file per (modulation, SNR). 20 dB is included knowing it carries no
# errors - it is there so the no-power rows are visible next to the scored
# ones rather than quietly filtered out of the study.
SNRS = [4, 8, 10, 15, 20]


def _pick_files() -> list[str]:
    """First seed of each (modulation, SNR) cell, in registry order."""
    names = corpus_names()
    out = []
    for mod in MODULATIONS:
        for snr in SNRS:
            match = sorted(n for n in names
                           if n.startswith(f"{mod}_{snr}dB_"))
            if match:
                out.append(match[0])
    return out


def _best_rotation(res, tx: np.ndarray):
    """The rotation `measured_ber` would have chosen, plus what it takes to
    compare bit by bit: the offset into `tx`, and whether the stream is
    inverted.

    Deliberately mirrors `corpus.measured_ber` rather than re-deriving it -
    the one function in this repo that already handles both the rotation
    ambiguity and the acquisition-prefix offset. Re-deriving it is how a
    previous study produced a table of 0.497 in every cell.
    """
    best = None
    for cand in getattr(res, "llrs_by_rotation", None) or []:
        bits = llr_to_bits(cand)
        e, off = align(bits, tx)
        # A fully inverted stream carries the same information; S4 recovers
        # from it identically. Score it as its own complement.
        inverted = (1.0 - e) < e
        score = min(e, 1.0 - e)
        if best is None or score < best[0]:
            best = (score, cand, off, inverted)
    return best


def _rows_for_file(name: str) -> list[dict]:
    iq, fs, truth = load(name)
    mod = truth["scheme"]
    tx = reference_bits(truth)
    params = {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0}

    res = MODULATIONS[mod].receive(iq, params)
    picked = _best_rotation(res, tx)
    if picked is None:
        return [{"file": name, "modulation": mod, "snr_db": truth["snr_db"],
                 "bin_lo": "", "bin_hi": "", "n_bits": 0, "n_errors": 0,
                 "empirical": "", "predicted": "", "ratio": "",
                 "verdict": "no-llrs", "agg_empirical": "",
                 "repo_measured_ber": "", "agg_predicted": "",
                 "repo_estimated_ber": "", "status": res.status}]

    _, llrs, off, inverted = picked
    llrs = np.asarray(llrs, dtype=np.float64)
    bits = llr_to_bits(llrs)
    if inverted:
        bits = 1 - bits

    # Exactly `align`'s own window, so `agg_empirical` below is the SAME
    # number `measured_ber` computed rather than a near-miss of it. The
    # known-answer check is only worth having if it can actually fail.
    n = int(min(bits.size, 20000, tx.size // 2))
    if n < 1000 or off < 0:
        return [{"file": name, "modulation": mod, "snr_db": truth["snr_db"],
                 "bin_lo": "", "bin_hi": "", "n_bits": n, "n_errors": 0,
                 "empirical": "", "predicted": "", "ratio": "",
                 "verdict": "no-alignment", "agg_empirical": "",
                 "repo_measured_ber": "", "agg_predicted": "",
                 "repo_estimated_ber": "", "status": res.status}]

    err = bits[:n] != tx[off:off + n]
    mag = np.abs(llrs[:n])
    pred = 1.0 / (1.0 + np.exp(np.clip(mag, 0.0, 700.0)))

    # The known-answer pair. These come from the repo's own functions on the
    # same result and must agree with this script's own aggregates.
    # `estimated_ber` over the SAME window and the SAME rotation. The first
    # draft compared this script's windowed mean against `estimated_ber` over
    # the whole array, which are two different populations - and the check
    # duly reported eight disagreements that were its own and not the
    # demapper's. A known-answer check that fires on its own mismatched
    # populations is worse than none: it teaches you to ignore it.
    agg = {
        "agg_empirical": round(float(err.mean()), 6),
        "repo_measured_ber": round(float(measured_ber(res, tx)), 6),
        "agg_predicted": round(float(pred.mean()), 6),
        "repo_estimated_ber": round(float(estimated_ber(llrs[:n])), 6),
        "status": res.status,
    }

    rows = []
    for lo, hi in zip(BIN_EDGES[:-1], BIN_EDGES[1:]):
        m = (mag >= lo) & (mag < hi)
        n_bits = int(m.sum())
        if not n_bits:
            continue
        n_err = int(err[m].sum())
        emp = n_err / n_bits
        prd = float(pred[m].mean())
        if lo >= SCORABLE_MAX_EDGE or n_err < MIN_ERRORS_TO_SCORE:
            verdict, ratio = "no-power", ""
        else:
            r = emp / prd if prd > 0 else math.inf
            ratio = round(r, 3)
            lo_b, hi_b = CALIBRATED_BAND
            verdict = ("ok" if lo_b <= r <= hi_b
                       else "over-confident" if r > hi_b
                       else "under-confident")
        rows.append({
            "file": name, "modulation": mod, "snr_db": truth["snr_db"],
            "bin_lo": lo, "bin_hi": hi, "n_bits": n_bits, "n_errors": n_err,
            "empirical": round(emp, 6), "predicted": round(prd, 6),
            "ratio": ratio, "verdict": verdict, **agg,
        })
    return rows


FIELDS = ["file", "modulation", "snr_db", "bin_lo", "bin_hi", "n_bits",
          "n_errors", "empirical", "predicted", "ratio", "verdict",
          "agg_empirical", "repo_measured_ber", "agg_predicted",
          "repo_estimated_ber", "status"]


def _write_csv(rows) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _load_csv() -> list[dict]:
    with CSV_PATH.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("bin_lo", "bin_hi", "empirical", "predicted", "ratio",
                  "agg_empirical", "repo_measured_ber", "agg_predicted",
                  "repo_estimated_ber", "snr_db"):
            r[k] = float(r[k]) if r[k] not in ("", "inf") else (
                math.inf if r[k] == "inf" else None)
        for k in ("n_bits", "n_errors"):
            r[k] = int(r[k])
    return rows


def _fmt_bin(lo, hi) -> str:
    return f"[{lo:g}, {hi:g})" if hi != math.inf else f"[{lo:g}, inf)"


def _write_markdown(rows) -> None:
    scored = [r for r in rows if r["verdict"] in
              ("ok", "over-confident", "under-confident")]
    files = sorted({r["file"] for r in rows})

    out = [
        "# Are S3's LLRs calibrated per-bit, or only on average?",
        "",
        "Owner: Anvith. Regenerate with "
        "`./.venv/Scripts/python.exe reports/s3_llr_calibration_study.py` "
        "(`--render-only` re-renders this file from the CSV).",
        "",
        "The premise check under `reports/s3_ldpc_design.md`. Sum-product "
        "belief propagation is the first consumer in this project whose answer "
        "depends on LLR MAGNITUDES rather than only on their signs and their "
        "sum, so it is the first one that needs this measured. Viterbi is "
        "scale-invariant, Reed-Solomon sees hard bits, and S4 hard-slices - "
        "none of them could have told us.",
        "",
        f"{len(files)} files, one per (modulation, SNR) cell, demodulated "
        "through the true symbol rate so the number is the demapper's and not "
        "the search's.",
        "",
        "## Read this table first",
        "",
        "The known-answer check. This script labels every bit right or wrong "
        "itself, from its own alignment and its own rotation choice. If that "
        "machinery is sound, aggregating it must reproduce the repo's own "
        "`corpus.measured_ber`, and its mean predicted error must reproduce "
        "`softmap.estimated_ber`. Where those disagree, nothing below the line "
        "means anything.",
        "",
        "| file | status | this study | `measured_ber` | this study pred | "
        "`estimated_ber` | agrees |",
        "|---|---|---|---|---|---|---|",
    ]
    agree_all = True
    for f in files:
        r = next(r for r in rows if r["file"] == f)
        a, b = r["agg_empirical"], r["repo_measured_ber"]
        c, d = r["agg_predicted"], r["repo_estimated_ber"]
        if a is None or b is None:
            continue
        ok = abs(a - b) < 1e-6 and abs(c - d) < 1e-6
        agree_all &= ok
        out.append(f"| `{f}` | {r['status']} | {a:.6f} | {b:.6f} | "
                   f"{c:.6f} | {d:.6f} | {'yes' if ok else '**NO**'} |")
    out += [
        "",
        ("Every row agrees, so the per-bin numbers below rest on the same "
         "labelling the rest of the project already trusts."
         if agree_all else
         "**At least one row disagrees. Stop - the alignment or the rotation "
         "choice in this script is wrong, and the calibration table below is "
         "measuring something other than what it says.**"),
        "",
        "## Calibration by |LLR| bin",
        "",
        "`predicted` is the mean of `1 / (1 + exp(|llr|))` over the bin - what "
        "the LLR promises. `empirical` is how often those bits were actually "
        "wrong. `ratio` above 1 means the demapper is over-confident: it "
        "promised more reliability than it delivered.",
        "",
        f"A bin is scored only when it holds at least {MIN_ERRORS_TO_SCORE} "
        f"errors and its lower edge is under {SCORABLE_MAX_EDGE:g}. Everything "
        "else reads `no-power` - not `ok`. Zero errors in a high-confidence "
        "bin is consistent with the prediction and with a prediction ten times "
        "smaller, and calling that a pass would be corroboration invented out "
        "of an absence.",
        "",
        "`status` is S3's own verdict on the file. It is in this table because "
        "the two verdicts behave completely differently and reading the rows "
        "without it is how the first draft of the summary below went wrong.",
        "",
        # The bin column is titled without the pipes of `|LLR|`: an unescaped
        # pipe inside a header cell splits it, and the header then carries two
        # more columns than the rows under it. It renders as a broken table in
        # every viewer and as nothing at all in some.
        "| modulation | SNR | status | LLR magnitude bin | bits | errors | "
        "empirical | predicted | ratio | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["bin_lo"] is None:
            continue
        ratio = f"{r['ratio']:.2f}" if r["ratio"] not in (None, "") else "-"
        out.append(
            f"| {r['modulation']} | {r['snr_db']:g} dB | {r['status']} | "
            f"{_fmt_bin(r['bin_lo'], r['bin_hi'])} | {r['n_bits']} | "
            f"{r['n_errors']} | {r['empirical']:.5f} | {r['predicted']:.5f} | "
            f"{ratio} | {r['verdict']} |")

    out += ["", "## What this means for the LDPC path", ""]
    if not scored:
        out += [
            "**No bin in this study had enough errors to score.** That is a "
            "result about the corpus, not about the demapper: at these SNRs "
            "the files that decode do so with almost no bit errors, and the "
            "files that do not decode return no usable LLRs at all. The LDPC "
            "design cannot take a calibration claim from this study, and "
            "should say so rather than assume one.",
        ]
        MD_PATH.write_text("\n".join(out), encoding="utf-8")
        return

    # SPLIT BY `status`, and this is the finding rather than a presentation
    # choice. A first draft of this section ranked by the median ratio per
    # modulation and printed "8psk ... calibrated" over a file whose worst bin
    # was 66x out - because it had pooled a result S3 STANDS BEHIND with one
    # S3 REFUSED. Those are not the same population and the question "can an
    # LDPC decoder trust these magnitudes" has a different answer for each.
    out += [
        "The split below is by S3's own `status`, and it is the result rather "
        "than a way of arranging it. Pooling the two answers the wrong "
        "question: a consumer chooses whether to decode AFTER reading "
        "`status`, so what matters is how the LLRs behave inside each verdict, "
        "not on average across both.",
        "",
    ]
    for want, title, note in (
        ("ok", "Files S3 returned `ok` on - what an LDPC decoder would be fed",
         "This is the population the design can rely on."),
        (None, "Files S3 refused (`low_confidence`) - the contrast",
         "These LLRs never reach a decoder unless somebody ignores `status`. "
         "The numbers show what happens if they do."),
    ):
        rs_all = [r for r in scored
                  if (r["status"] == "ok" if want else r["status"] != "ok")]
        if not rs_all:
            continue
        out += [f"### {title}", "", note, "",
                "| modulation | scored bins | median ratio | worst ratio | "
                "reading |", "|---|---|---|---|---|"]
        by_mod: dict[str, list[dict]] = {}
        for r in rs_all:
            by_mod.setdefault(r["modulation"], []).append(r)
        for mod, rs in by_mod.items():
            ratios = sorted(float(r["ratio"]) for r in rs)
            med = ratios[len(ratios) // 2]
            worst = max(ratios, key=lambda x: abs(math.log(x)) if x > 0
                        else math.inf)
            # Ranked on the WORST bin, not the median. A decoder meets every
            # bin, not the middle one, and a median that reads `ok` over a
            # 66x bin is the summary that hid this the first time.
            reading = ("calibrated" if CALIBRATED_BAND[0] <= worst <= CALIBRATED_BAND[1]
                       else "over-confident" if worst > CALIBRATED_BAND[1]
                       else "under-confident")
            out.append(f"| {mod} | {len(rs)} | {med:.2f} | {worst:.2f} | "
                       f"{reading} |")
        out.append("")
    out += ["See `reports/s3_ldpc_design.md` for what the design does with "
            "this.", ""]
    MD_PATH.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    if "--render-only" in sys.argv:
        _write_markdown(_load_csv())
        print(f"rendered {MD_PATH}")
        return 0

    names = _pick_files()
    if not names:
        print("no corpus files found under zoo/corpus/rf/", file=sys.stderr)
        return 1
    rows: list[dict] = []
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}", flush=True)
        rows.extend(_rows_for_file(name))
    _write_csv(rows)
    _write_markdown(rows)
    print(f"wrote {CSV_PATH} and {MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
