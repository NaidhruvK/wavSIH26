"""S3 against Dheeraj's real RF corpus, blind, with lock-failure detection.

4 Sep. Owner: Anvith. Regenerate with:

    python reports/s3_lock_gate_study.py            # measure and render
    python reports/s3_lock_gate_study.py --render-only

Three arms over the same 36 files, so the difference between them is the code
and nothing else:

    truth-params    S3 handed the symbol rate the zoo used and no carrier
                    offset. The ceiling: what the receiver can do when its
                    inputs are right.
    s2-top          S3 handed S2's TOP hypothesis on every field, which is
                    what it was doing until today. This is the arm that
                    produced `status ok` on a stream with a bit error rate of
                    0.485.
    search          `receive_best`: S2's ranked hypotheses, screened cheaply,
                    the survivors run, the best kept. Today's work.

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


def _write_markdown(rows) -> None:
    arms = ["truth-params", "s2-top", "search"]
    n_files = len(_arm(rows, "search"))

    L = [
        "# S3 lock-failure detection and hypothesis retry - the 4 Sep gate", "",
        "**Anvith.** Measured on Dheeraj's 36-file RF corpus "
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
        f"On the `s2-top` arm, which is what S3 did until this morning, the old "
        f"rule returns `ok` on **{cw_before} of {n_files}** files whose real bit "
        "error rate is around 0.485 - a coin flip, reported as a clean lock, "
        "with `estimated_output_ber` reading 0.000000 beside it.", "",
        "The cause is one line in two stages meeting. `s2_estimate.estimate_cfo` "
        "raises the signal to the M-th power and takes the strongest line; on a "
        "pulse-shaped stream that line is the **symbol rate**, not `M x cfo`, "
        "so the offset comes back near `Rs / M`. De-rotating by `Rs / M` "
        "advances the constellation exactly one symmetry step per symbol, and "
        "S3's lock metric `|E[u^S]|` is invariant under precisely that "
        "rotation. Neither stage was checkable against the other, because the "
        "only number either produced said everything was fine.", "",
        "**Dheeraj** - the S2 half is yours and it is worth fixing at source: "
        "the CFO search should exclude the symbol-rate line, or rank M-th "
        "power peaks by something other than height. The corpus makes it easy "
        "to check, because every file has a true offset of exactly zero and "
        "S2 reports a non-zero one on 33 of 36.", "",
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

    mods_ok = sorted({r["true_mod"] for r in srch if r["decodes"]})
    dec_frac = dec_after / max(n_files, 1)
    L += [
        "", "## Against the 4 Sep gate", "",
        "The gate is written for the whole pipeline (≥40% of the corpus to "
        "exact bits, ≥4 of 6 modulations, no unhandled exception). S3 owns "
        "the first two stages of that and can report its own half:", "",
        f"- **{dec_frac:.0%}** of the corpus reaches LLRs under "
        f"{DECODE_LIMIT:.0%} raw BER ({dec_after}/{n_files}).",
        f"- **{len(mods_ok)} of 6** modulations are represented among them: "
        f"{', '.join(mods_ok)}.",
        "- No input in this study, or in the adversarial set in "
        "`tests/unit/test_s3_receive.py`, raised out of `receive()`.", "",
        "## Every file, `search` arm", "",
        "| file | true | chosen | status | est BER | valid | measured BER | "
        "runs | s | why not |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(srch, key=lambda r: (r["true_mod"], r["snr_db"])):
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
        "## Known gaps, stated", "",
        "- **The 4 dB files mostly do not decode**, on any arm. That is the "
        "operating envelope, not a lock-detection failure - `truth-params` "
        "does not decode them either. 5 Sep is the day that moves.",
        "- **The four FSK misses split two ways, and the halves have "
        "different owners.** `2fsk_8dB_2025` (S2 offers 11987, 9345, 59987 Hz "
        "against a true 50000) and `4fsk_4dB_2030` (65634) fail because the "
        "true rate is not in the list; the retry loop can only search what it "
        "is given. **Dheeraj**: one predicate is behind both - `estimate()`'s "
        "envelope test reads these WAVs as non-constant-envelope, so FSK "
        "captures go to the LINEAR symbol-rate estimator, and "
        "`fsk_order_hypotheses` comes back empty on all 36 files for the same "
        "reason. That is worth more to this gate than anything left in S3.",
        "- **`2fsk_4dB_2024` is mine, and it is a near miss.** S2's rate is "
        "48479 against a true 50000, close enough to work, and the presence "
        "check scored it 4.4 against a limit of 4.5. The limit is set from the "
        "worst noise draw measured at the shortest record length, so lowering "
        "it to catch this file would spend the margin that keeps noise out. "
        "The right fix is a better statistic at 4 dB, not a looser threshold; "
        "5 Sep is the day for it.",
        "- **Choosing the modulation is not S3's job** and this does not make "
        "it so. With no ranking from S2, the search runs every survivor and "
        "picks on reported quality, which works on this corpus and is not a "
        "classifier. When Dheeraj's lands, pass it as `modulations=` and the "
        "search takes the first clean lock instead.",
    ]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
