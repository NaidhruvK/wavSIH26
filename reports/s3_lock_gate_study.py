"""S3 against Dheeraj's real RF corpus, blind, with lock-failure detection.

4 Sep, extended 5 Sep. Owner: Anvith. Regenerate with:

    python reports/s3_lock_gate_study.py            # measure and render
    python reports/s3_lock_gate_study.py --render-only

Three arms over the same corpus files, so the difference between them is the
code and nothing else:

    truth-params    S3 handed the symbol rate the zoo used and no carrier
                    offset. The ceiling: what the receiver can do when its
                    inputs are right.
    s2-top          S3 handed S2's TOP hypothesis on every field, which is
                    what the stage did before 4 Sep. This is the arm that
                    produced `status ok` on a stream with a bit error rate of
                    0.485, and the arm Dheeraj's 5 Sep CFO fix moves most.
    search          `receive_best`: S2's ranked hypotheses, screened cheaply,
                    the survivors run, the best kept. What ships.

The corpus grew from 36 files to 252 on 5 Sep - seven seeds per (modulation,
SNR) cell instead of one - and this study picks that up with no edit, because
it globs the directory. Nothing here is per-file except the tables at the end.
Read every number in it as "on 252 files": a one-seed cell cannot tell a
receiver from a lucky noise draw, and several of the 4 Sep numbers this file
used to print were one-seed cells.

Every bit error rate here is measured against the bits the zoo actually
transmitted, regenerated from the seed in the truth JSON - see
`tests/fixtures/corpus.reference_bits`. Nothing in `pipeline/` can see them.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

import pipeline.s3_receive                                      # noqa: E402,F401
from pipeline.s2_estimate import estimate                       # noqa: E402
from pipeline.s3_receive.search import (params_from_s2,         # noqa: E402
                                        receive_best)
from registry import MODULATIONS                                # noqa: E402
from tests.fixtures.corpus import (corpus_names, load,          # noqa: E402
                                   measured_ber, reference_bits)

OUT_CSV = ROOT / "reports" / "s3_lock_gate.csv"
OUT_MD = ROOT / "reports" / "s3_lock_gate.md"

CONFIDENTLY_WRONG_LIMIT = 0.10
"""Raw bit error rate above which an `ok` with a valid estimate is a lie.

A decade above `DECODE_LIMIT` and five times under the 0.485 the pre-4-Sep
build was reporting as a clean lock, so no file sits close to it in either
direction and the count does not move if the number does.
"""

DECODE_LIMIT = 0.01
"""A file "decodes" when the best rotation's raw bit error rate is under this.

The 4 Sep gate is written in terms of the whole pipeline reaching exact bits,
which S4 and S5 finish. S3 cannot report that, so it reports the thing it is
responsible for: whether the LLRs it emitted are close enough that the rest of
the chain has something to work with. 1% is well inside the 3% ceiling Nehal
measured for the statistical recovery path and well outside the 0.0002 the
junction study reaches when everything works, so nothing sits near it.
"""


def _one_file(name: str) -> list[dict]:
    iq, fs, truth = load(name)
    tx = reference_bits(truth)
    true_mod = truth["scheme"]
    s2 = estimate(iq, fs)
    rows = []

    arms = {
        "truth-params": dict(
            params={"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0},
            mod=true_mod),
        "s2-top": dict(
            params={"fs": fs, "symbol_rate": s2.symbol_rate_hz,
                    "cfo_hz": s2.cfo_hz},
            mod=true_mod),
    }
    for arm, cfg in arms.items():
        t0 = time.perf_counter()
        res = MODULATIONS[cfg["mod"]].receive(iq, cfg["params"])
        secs = time.perf_counter() - t0
        rows.append(_row(name, truth, arm, res, tx, secs, cfg["mod"]))

    t0 = time.perf_counter()
    res = receive_best(iq, params_from_s2(s2, fs))
    secs = time.perf_counter() - t0
    rows.append(_row(name, truth, "search", res, tx, secs,
                     res.values.get("modulation", "")))
    return rows


def _row(name, truth, arm, res, tx, secs, chosen_mod) -> dict:
    v = res.values
    ber = measured_ber(res, tx) if getattr(res, "llrs_by_rotation", None) else 1.0
    valid = bool(v.get("estimated_output_ber_valid"))
    est = float(v.get("estimated_output_ber", 1.0))
    return {
        "file": name,
        "true_mod": truth["scheme"],
        "snr_db": truth["snr_db"],
        "arm": arm,
        "chosen_mod": chosen_mod,
        "mod_correct": chosen_mod == truth["scheme"],
        "status": res.status,
        "confidence": round(float(res.confidence), 4),
        "est_ber": round(est, 8),
        "est_ber_valid": valid,
        "measured_ber": round(float(ber), 6),
        "decodes": bool(ber < DECODE_LIMIT),
        # The one that matters: a stage claiming a good demodulation over a
        # stream that is in fact noise. Everything downstream reads `status`
        # and the validity flag before it reads anything else.
        #
        # Deliberately NOT "ok but did not decode". That definition flags
        # 16qam_8dB_2019 - estimate 0.0122, actual 0.0149, an estimate right to
        # within 22% - purely for landing on the wrong side of a 1% line. The
        # failure worth counting is an estimate that is wrong by orders, so the
        # bar is a decade above the decode line and nothing sits near it.
        "confidently_wrong": bool(res.status == "ok" and valid
                                  and ber >= CONFIDENTLY_WRONG_LIMIT),
        # What the pre-4-Sep rule would have said, computed from the same run:
        # `ok` came from the carrier lock metric alone. This is how the "before"
        # column is measured rather than remembered.
        "old_rule_ok": bool(
            (v.get("lock_checks") or {}).get("carrier_locked") == "pass"
            or (v.get("lock_checks") or {}).get("tone_margin") == "pass"),
        "lock_failures": "|".join(v.get("lock_failures", []) or []),
        "chain_runs": v.get("search_chain_runs", 1),
        "secs": round(secs, 3),
        "reason": (res.reason or "")[:120],
    }


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
            rows.extend(_one_file(name))
            print(f"[{i:>2}/{len(names)}] {name}", flush=True)
        _write_csv(rows)

    _write_markdown(rows)
    print(f"wrote {OUT_CSV.name} and {OUT_MD.name}")
    return 0


FIELDS = ["file", "true_mod", "snr_db", "arm", "chosen_mod", "mod_correct",
          "status", "confidence", "est_ber", "est_ber_valid", "measured_ber",
          "decodes", "confidently_wrong", "old_rule_ok", "lock_failures",
          "chain_runs", "secs", "reason"]


def _write_csv(rows) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _load_csv() -> list[dict]:
    with open(OUT_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("snr_db", "confidence", "est_ber", "measured_ber", "secs"):
            r[k] = float(r[k])
        for k in ("mod_correct", "est_ber_valid", "decodes",
                  "confidently_wrong", "old_rule_ok"):
            r[k] = r[k] in ("True", "true", "1")
        r["chain_runs"] = int(r["chain_runs"] or 1)
    return rows


def _arm(rows, arm):
    return [r for r in rows if r["arm"] == arm]


# The 5 Sep row states its targets by family and by SNR floor, not over the
# corpus as a whole: "16-QAM reliable at 13 dB; PSK and FSK at 10 dB", verified
# as "lock rate 90%+ at >=10 dB for PSK and FSK". Encoded here so the verdict
# is computed from the same rows as everything else rather than read off a
# table by eye.
TARGETS = [
    ("PSK", ("bpsk", "qpsk", "8psk"), 10.0),
    ("FSK", ("2fsk", "4fsk"), 10.0),
    ("16-QAM", ("16qam",), 13.0),
]
VERIFY_LOCK_RATE = 0.90


def _harness_tables(srch) -> list[str]:
    """One cell per (modulation, SNR), for both questions, and the verdict.

    `locks` and `decodes` answer different questions and either table alone
    can be read the wrong way round. `locks` is S3's own claim - `status: ok` -
    and it is trivially maximised by never vetoing anything, which is exactly
    the failure 4 Sep found: the pre-4-Sep build locked 19 of 36 files over a
    bit error rate of 0.485. So the count of `ok` runs whose real bit error
    rate is at or above CONFIDENTLY_WRONG_LIMIT sits in the same section, not
    a later one. A lock rate is only worth having beside the count of lies it
    permits.

    Cells are `hits/files`. With seven seeds per (modulation, SNR) cell the
    denominator is 7 on the full corpus and 1 on the original 36-file one, so
    the shape of this table also says which corpus produced it.
    """
    # Registry order, not alphabetical: every other table in this project
    # reads bpsk, qpsk, 8psk, 16qam, 2fsk, 4fsk, and a table that reads
    # 16qam-first for no reason costs the reader a second look every time.
    order = {name: i for i, name in enumerate(MODULATIONS)}
    mods = sorted({r["true_mod"] for r in srch},
                  key=lambda m: order.get(m, len(order)))
    snrs = sorted({r["snr_db"] for r in srch})
    hdr = "| modulation | " + " | ".join(f"{s:.0f} dB" for s in snrs) + " | all |"
    sep = "|---" * (len(snrs) + 2) + "|"

    def matrix(title, pred, note):
        out = ["", title, "", hdr, sep]
        for mod in mods:
            cells = []
            for s in snrs:
                cell = [r for r in srch
                        if r["true_mod"] == mod and r["snr_db"] == s]
                cells.append(f"{sum(1 for r in cell if pred(r))}/{len(cell)}"
                             if cell else "-")
            rs = [r for r in srch if r["true_mod"] == mod]
            cells.append(f"**{sum(1 for r in rs if pred(r))}/{len(rs)}**")
            out.append(f"| {mod} | " + " | ".join(cells) + " |")
        return out + ["", note]

    L = ["", "## Harness table, by modulation and SNR bin", ""]
    L += matrix(
        "### Decodes - best rotation under "
        f"{DECODE_LIMIT:.0%} raw bit error rate",
        lambda r: r["decodes"],
        "This is the one the day gate is written against. It is measured "
        "against the bits the zoo transmitted, so it is what S4 would get, "
        "not what S3 believes it got.")
    L += matrix(
        "### Locks - S3 returned `status: ok`",
        lambda r: r["status"] == "ok",
        "S3's own claim, made blind. Read it beside the row below it.")
    L += matrix(
        "### Confidently wrong - `ok`, estimate marked valid, real BER "
        f">= {CONFIDENTLY_WRONG_LIMIT:.0%}",
        lambda r: r["confidently_wrong"],
        "Every cell here should be 0. A non-zero cell is worse than a failed "
        "one: downstream reads `status` before it reads anything else, so "
        "this is a stage telling S4 to spend its budget on noise.")

    L += ["", "### Against the 5 Sep targets", "",
          "| family | SNR floor | files | locks | decodes | confidently wrong "
          "| verify |", "|---|---|---|---|---|---|---|"]
    for label, schemes, floor in TARGETS:
        rs = [r for r in srch
              if r["true_mod"] in schemes and r["snr_db"] >= floor]
        if not rs:
            continue
        n = len(rs)
        lk = sum(1 for r in rs if r["status"] == "ok")
        dc = sum(1 for r in rs if r["decodes"])
        cw = sum(1 for r in rs if r["confidently_wrong"])
        ok = (lk / n) >= VERIFY_LOCK_RATE and cw == 0
        L.append(f"| **{label}** | ≥{floor:.0f} dB | {n} | "
                 f"**{lk}/{n}** ({lk / n:.0%}) | {dc}/{n} ({dc / n:.0%}) | "
                 f"{cw} | {'**PASS**' if ok else '**FAIL**'} |")
    L += ["",
          f"`verify` is the 5 Sep row's line - lock rate at or above "
          f"{VERIFY_LOCK_RATE:.0%} above the family's floor - **and** zero "
          "confidently wrong, which the row does not say and which is the "
          "only reason the first number means anything."]
    return L


def _write_markdown(rows) -> None:
    arms = ["truth-params", "s2-top", "search"]
    n_files = len(_arm(rows, "search"))

    L = [
        "# S3 lock-failure detection and hypothesis retry - the 4 Sep gate", "",
        f"**Anvith.** Measured on Dheeraj's {n_files}-file RF corpus "
        "(`zoo/corpus/rf/`), blind. Regenerate with "
        "`python reports/s3_lock_gate_study.py`.", "",
        "Bit error rates are against the bits the zoo actually transmitted, "
        "regenerated from the seed in each truth JSON. `decodes` means the "
        f"best rotation came back under **{DECODE_LIMIT:.0%}** raw BER.", "",
        "## The three arms", "",
        "| arm | what S3 was told | decodes | mod correct | "
        "**confidently wrong** | *would have been, old rule* | median s |",
        "|---|---|---|---|---|---|---|",
    ]
    told = {
        "truth-params": "the true symbol rate, no carrier offset",
        "s2-top": "S2's top hypothesis on every field",
        "search": "S2's *ranked* hypotheses, searched",
    }
    for a in arms:
        rs = _arm(rows, a)
        if not rs:
            continue
        dec = sum(r["decodes"] for r in rs)
        cor = sum(r["mod_correct"] for r in rs)
        cw = sum(r["confidently_wrong"] for r in rs)
        old = sum(r["old_rule_ok"] and r["measured_ber"] >= CONFIDENTLY_WRONG_LIMIT
                  for r in rs)
        med = float(np.median([r["secs"] for r in rs]))
        L.append(f"| `{a}` | {told[a]} | **{dec}/{len(rs)}** | {cor}/{len(rs)} "
                 f"| **{cw}** | *{old}* | {med:.2f} |")

    s2t, srch = _arm(rows, "s2-top"), _arm(rows, "search")
    cw_before = sum(r["old_rule_ok"] and r["measured_ber"] >= CONFIDENTLY_WRONG_LIMIT
                    for r in s2t)
    dec_before = sum(r["decodes"] for r in s2t)
    dec_after = sum(r["decodes"] for r in srch)

    L += [
        "", "## The last column, and why it is the point", "",
        "Every arm above runs TODAY's code, so `confidently wrong` is what the "
        "build now reports. The italic column is what the *old* rule - `ok` "
        "from the carrier lock metric alone - would have said about the very "
        "same runs. It is computed from the per-check verdicts each run "
        "recorded, so it is measured rather than remembered.", "",
        f"On the `s2-top` arm the old rule still returns `ok` on "
        f"**{cw_before} of {n_files}** files it should not.", "",
        "The cause is one line in two stages meeting. `s2_estimate.estimate_cfo` "
        "raised the signal to the M-th power and took the strongest line; on a "
        "pulse-shaped stream that line is the **symbol rate**, not `M x cfo`, "
        "so the offset came back near `Rs / M`. De-rotating by `Rs / M` "
        "advances the constellation exactly one symmetry step per symbol, and "
        "S3's lock metric `|E[u^S]|` is invariant under precisely that "
        "rotation. Neither stage was checkable against the other, because the "
        "only number either produced said everything was fine.", "",
        "**That half is fixed.** Dheeraj landed it on 5 Sep "
        "(`426a780`, 'Fix S2 CFO estimator falling into the M-th power "
        "spectral-line trap') and it is the largest single move in this "
        "table. The `s2-top` arm - S3 reading S2's top hypothesis and nothing "
        "else, which is what the stage did before 4 Sep - went from **4 of 36 "
        "files decoding on 4 Sep** to "
        f"**{dec_before} of {n_files}** on the same code path today. Measured "
        "on the corpus this morning: every file still has a true offset of "
        "exactly zero, and S2 now reports a non-zero one on 93 of 252 rather "
        "than 33 of 36 - so the estimator is right far more often, and the "
        "hypothesis-search and alignment check below are what cover the "
        "remainder rather than papering over it.", "",
        "## What closed it", "",
        "Independent checks against different evidence, any one of which can "
        "veto a claim of lock (`pipeline/s3_receive/lockcheck.py`). Four are "
        "new today; the carrier lock metric is kept, because it is right about "
        "what it is right about:", "",
        "- **`signal_present`** - a cyclostationary line at the claimed symbol "
        "rate. Spectral, so it survives every carrier and timing error there "
        "is. Separates 'nothing is here' from 'I did not lock', which is what "
        "makes pure noise a `failed` with a reason rather than a shrug.",
        "- **`carrier_aligned`** - the spectrum is still centred after the "
        "carrier-offset hypothesis has been applied. This is the one that "
        "catches the failure above, and its measurement doubles as the "
        "correction the retry loop tries next.",
        "- **`output_usable`** - the receiver may not claim `ok` while its own "
        "estimated output error rate says the output is junk. Found by "
        "`8psk_8dB_2013`, where the 2-FSK plug-in returned `ok` at a mean tone "
        "margin of 0.319 while estimating its own output BER at 0.19.",
        "- **`alphabet_used`** (linear) - does the received cloud use the "
        "whole constellation this hypothesis claims? The only check that can "
        "refuse a constellation which CONTAINS the true one. QPSK's four "
        "points are four of 16-QAM's sixteen, so a QPSK capture read as 16-QAM "
        "locks perfectly and reports an estimated BER of 1.8e-21 against an "
        "actual 0.482. Measured: correct hypothesis >= 0.992 evenness, "
        "wrong-but-`ok` <= 0.670, across four schemes and 4-25 dB.",
        "- **`tone_alias`** (FSK) - the frequency twin of the rotation "
        "ambiguity. An offset of one tone spacing maps the tone bank onto "
        "itself and slips every symbol label by one: identical tones, "
        "identical margins, every other check passing, and a bit error rate of "
        "0.248 on `4fsk_13dB_2033`. Refused rather than guessed.",
        "- **`timing_converged`** - a verdict the Gardner loop was already "
        "computing, reported, and then not counted.", "",
        f"With them, `confidently wrong` on this corpus is "
        f"**{sum(r['confidently_wrong'] for r in srch)}**, and files decoding "
        f"went from **{dec_before}** to **{dec_after}** of {n_files}.", "",
        "## Per modulation, `search` arm", "",
        "| modulation | decodes | files | worst SNR that decodes |",
        "|---|---|---|---|",
    ]
    for mod in sorted({r["true_mod"] for r in srch}):
        rs = [r for r in srch if r["true_mod"] == mod]
        ok = [r for r in rs if r["decodes"]]
        worst = f"{min(r['snr_db'] for r in ok):.0f} dB" if ok else "-"
        L.append(f"| {mod} | {len(ok)} | {len(rs)} | {worst} |")

    L += _harness_tables(srch)

    mods_ok = sorted({r["true_mod"] for r in srch if r["decodes"]})
    dec_frac = dec_after / max(n_files, 1)
    hi = [r for r in srch if r["snr_db"] >= 10.0]
    hi_dec = sum(r["decodes"] for r in hi)
    hi_frac = hi_dec / max(len(hi), 1)
    hi_mods = sorted({r["true_mod"] for r in hi if r["decodes"]})
    L += [
        "", "## Against the 5 Sep day gate", "",
        "The gate is written for the whole pipeline - at least 65% of corpus "
        "files at 10 dB or better decoding to exact bits across 5 or more "
        "modulations, and Nehal's concatenated CCSDS chain recovering its "
        "payload text. S4 and S5 finish that; S3 owns the front of it and can "
        "report its own half:", "",
        f"- **{hi_frac:.0%}** of the files at 10 dB and above reach LLRs "
        f"under {DECODE_LIMIT:.0%} raw BER ({hi_dec}/{len(hi)}), across "
        f"**{len(hi_mods)} of 6** modulations.",
        f"- Over the whole corpus including 4 and 8 dB it is "
        f"**{dec_frac:.0%}** ({dec_after}/{n_files}), across "
        f"{len(mods_ok)} of 6.",
        "- No input in this study, or in the adversarial set in "
        "`tests/unit/test_s3_receive.py`, raised out of `receive()`.", "",
        "Quoting either number without the corpus size attached is how a "
        "24/24 becomes a claim about a receiver rather than about 36 files, "
        f"so: **{n_files} files**, seven seeds per (modulation, SNR) cell.", "",
        "### Reproducing the before-column", "",
        "This CSV is always the CURRENT build, so a before/after number needs "
        "the old build re-measured rather than remembered. The 5 Sep "
        "before-figures quoted in STATUS.md - `search` 203/252, `s2-top` "
        "177/252 - come from running this same script against commit "
        "`aed281b`, which is this branch's merge of `main` immediately before "
        "the 5 Sep receiver changes:", "",
        "```bash",
        "git worktree add /tmp/s3-baseline aed281b",
        "cd /tmp/s3-baseline && "
        "<repo>/.venv/Scripts/python.exe reports/s3_lock_gate_study.py",
        "```", "",
        "It takes about eight minutes and reproduces 203 exactly. Written "
        "down because the first version of the 5 Sep write-up quoted a "
        "before-number whose CSV had already been overwritten by the "
        "after-run, which makes it a memory rather than a measurement - and "
        "this project does not keep those.", "",
        "## Every file that did not decode, `search` arm", "",
        f"All {n_files} rows are in `{OUT_CSV.name}`; this table is the "
        "complement, because it is the list the next day's work is drawn "
        "from. Sorted by SNR descending: a miss at 20 dB is a defect, a miss "
        "at 4 dB may be the operating envelope, and they should not be read "
        "in the same breath.", "",
        "| file | true | chosen | status | est BER | valid | measured BER | "
        "runs | s | why not |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    misses = [r for r in srch if not r["decodes"]]
    for r in sorted(misses, key=lambda r: (-r["snr_db"], r["true_mod"])):
        mark = "" if r["decodes"] else " ⚠"
        L.append(
            f"| {r['file']} | {r['true_mod']} | {r['chosen_mod'] or '-'} | "
            f"`{r['status']}` | {r['est_ber']:.2e} | "
            f"{'yes' if r['est_ber_valid'] else 'no'} | "
            f"{r['measured_ber']:.5f}{mark} | {r['chain_runs']} | "
            f"{r['secs']:.2f} | {r['reason'] or ''} |")

    L += [
        "", "## Cost", "",
        "The search considers up to "
        f"{max((r['chain_runs'] for r in srch), default=0)} full receiver runs "
        "and rejects the rest with one FFT each. Median "
        f"{np.median([r['secs'] for r in srch]):.2f} s per file, worst "
        f"{max(r['secs'] for r in srch):.2f} s, against a 20 s budget and a "
        "90 s whole-pipeline window. The screen is what makes that true: "
        "without it the same candidate list is 6 modulations x 3 rates x 5 "
        "offsets of full chain runs.", "",
        "## Known gaps, stated - 5 Sep", "",
        "- **8-PSK and 16-QAM at 4 dB do not decode, on any arm.** That is "
        "the operating envelope and not a lock-detection failure: "
        "`truth-params` does not decode them either, at a median raw bit "
        "error rate of 0.23 and 0.31 with the true rate and no offset. "
        "Nothing in S3 recovers a stream the demodulator cannot demodulate, "
        "and the checks correctly refuse all of them.",
        "- **16-QAM at 8 dB lands just the wrong side of the decode line, "
        "and knows it.** Seven files, raw bit error rate 0.0117-0.0124 "
        "against the 1% this study calls decoding, with the receiver's own "
        "estimate at 0.0100-0.0109 - right to within 13%, `status: ok`, "
        "correctly. They are counted as misses here and they are not misses "
        "downstream: 1.2% is inside the 3% Nehal measured as the ceiling for "
        "statistical code recovery. The number to move is the demodulator's, "
        "not the threshold's, and moving the threshold to claim them would be "
        "changing the definition of the gate to pass it.",
        "- **FSK below 10 dB was the largest single gap, and most of it was "
        "not S3's.** S2's symbol rate is exact on 224 of 252 files. The 28 "
        "exceptions are every 2-FSK and 4-FSK file at 4 and 8 dB, wrong by up "
        "to 81% - and `fsk_order_hypotheses` comes back empty on exactly "
        "those 28, not on all files as this report said on 4 Sep. **Dheeraj** "
        "has this documented and quantified in `reports/s2_envelope.md` as a "
        "deliberate low-SNR-only gap; what that write-up could not know is "
        "what it costs downstream, which is the whole of it: handed the true "
        "rate, S3 decodes all 28 at a median raw bit error rate of 0.004. The "
        "receiver was never the problem on those files. S3 now rescues the "
        "rate for itself (`lockcheck.strongest_line`, "
        "`reports/s3_rate_rescue.md`), which closes the gap from this side "
        "without touching S2 - but fixing the envelope predicate at source is "
        "still worth more, because every stage downstream of S2 inherits the "
        "wrong rate and only this one now works around it.",
        "- **A correction to what this report said on 4 Sep about "
        "`2fsk_4dB_2024`.** It was written up as a presence-threshold near "
        "miss - line score 4.4 against a limit of 4.5 - with the conclusion "
        "that 4 dB needed a better statistic rather than a looser number. The "
        "statistic was fine. Measured today: the 4.4 was scored at 48 479 Hz, "
        "the rate S2 offered; at the true 50 000 Hz the same statistic on the "
        "same file scores **45.2**, which is five times the limit for "
        "declaring a line present. The threshold was never what stood in the "
        "way, the rate was, and a study of the threshold would have spent the "
        "day tuning a number that was already right.",
        "- **Choosing the modulation is still not S3's job.** Dheeraj's "
        "classifier has landed and `receive_best` reads its ranking through "
        "`params_from_s2`, taking the first clean lock instead of running "
        "every survivor - which is where the drop in median time comes from. "
        "Where the classifier is wrong the search still recovers, because an "
        "unranked modulation is tried last rather than not at all.",
    ]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
