"""S3 -> S4 across the zoo's RF corpus: 6 modulations x 6 SNRs, from WAV.

The strongest end-to-end evidence available today, because every part of it
was produced by a different person:

    Dheeraj's modulator and channel  ->  a WAV on disk
    Anvith's S3                      ->  soft LLRs, blind
    my S4                            ->  interleaver, code, generators

`reports/end_to_end.md` measured the same chain against MY fixture
(`tests/fixtures/rf_channel.py`). That is a self-consistency check: my fixture
and my recovery could agree with each other and both be wrong, which is the
lesson section 7 of the handoff exists to record. This file removes that
coupling on the transmit side.

Still synthetic - it is AWGN with pulse shaping, not an off-air capture. Note
the corpus sets cfo_norm=0, phase_rad=0 and timing_offset_sym=0, so these files
are EASIER than my fixture, which used 1e-4, 0.7 rad and 0.3 symbols.

Regenerate with `python reports/zoo_rf_study.py`.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s3_receive.linear      # noqa: F401,E402  (registers modulations)
import pipeline.s3_receive.fsk_plugin  # noqa: F401,E402
import pipeline.s4_recover.interleavers  # noqa: F401,E402
from pipeline.s4_recover.rotations import recover_over_rotations  # noqa: E402
from registry import MODULATIONS  # noqa: E402

CORPUS = ROOT / "zoo" / "corpus" / "rf"


def load_iq(wav: Path) -> np.ndarray:
    data, _sr = sf.read(str(wav), always_2d=True)
    return (data[:, 0] + 1j * data[:, 1]).astype(np.complex128)


def run_one(wav: Path) -> dict:
    j = json.loads(wav.with_suffix(".json").read_text())
    scheme, il, code = j["scheme"], j["interleaver"], j["code"]
    row = {"scheme": scheme, "snr_db": j["snr_db"], "seed": j["seed"],
           "s3_ok": 0, "period_ok": 0, "interleaver_ok": 0, "generators_ok": 0,
           "status": "-", "reason": "", "rotation": -1, "used_fallback": 0,
           "s3_est_ber": -1.0, "s3_est_ber_valid": -1, "s3_evm": -1.0,
           "seconds": 0.0}

    t0 = time.time()
    iq = load_iq(wav)
    plugin = MODULATIONS.get(scheme)
    if plugin is None:
        row["reason"] = "no plug-in registered for %s" % scheme
        row["seconds"] = round(time.time() - t0, 1)
        return row

    # fs and symbol rate come from the truth sidecar because S2 does not exist
    # yet. Everything after the matched filter is blind. When S2 lands these
    # two lines are what change, and these numbers must be re-measured.
    s3 = plugin.receive(iq, {"fs": j["fs"], "symbol_rate": j["fs"] / j["sps"]})
    if s3.llrs is None or np.asarray(s3.llrs).size == 0:
        row["reason"] = "S3: %s" % (getattr(s3, "reason", "") or "no LLRs")[:60]
        row["seconds"] = round(time.time() - t0, 1)
        return row
    row["s3_ok"] = 1
    # S3 reports its own estimated output BER. Recorded here because it turns
    # out to PREDICT this stage's outcome exactly - see the summary below.
    v = getattr(s3, "values", {}) or {}
    row["s3_est_ber"] = float(v.get("estimated_output_ber", -1.0))
    row["s3_est_ber_valid"] = int(bool(v.get("estimated_output_ber_valid", False)))
    row["s3_evm"] = float(v.get("evm_percent", -1.0))

    # Every rotation the receiver cannot resolve. Shortest span decides, and
    # the statistical fallback is kept OUT of the screening pass - see
    # pipeline/s4_recover/rotations.py for the measurement that motivates it.
    rotations = getattr(s3, "llrs_by_rotation", None) or [s3.llrs]
    choice = recover_over_rotations(
        rotations,
        estimated_output_ber=row["s3_est_ber"],
        estimated_ber_valid=bool(row["s3_est_ber_valid"]))

    if choice is None:
        row["status"] = "declined"
        row["reason"] = "no rotation produced a confident recovery"
        row["seconds"] = round(time.time() - t0, 1)
        return row

    res = choice.result
    row["rotation"] = choice.index
    row["used_fallback"] = int(choice.used_fallback)
    row["status"] = res.status
    row["period_ok"] = int(res.period == il["period"])
    row["interleaver_ok"] = int(
        res.interleaver is not None
        and res.interleaver.params.get("depth") == il["depth"]
        and res.interleaver.params.get("width") == il["width"])
    row["generators_ok"] = int(res.generators_octal == tuple(code["polys_octal"]))
    row["seconds"] = round(time.time() - t0, 1)
    return row


def main() -> None:
    files = sorted(CORPUS.glob("*.wav"))
    if not files:
        raise SystemExit("no RF corpus at %s" % CORPUS)
    print("%d RF files from the real zoo\n" % len(files))

    rows = []
    for f in files:
        r = run_one(f)
        rows.append(r)
        print("%-8s %3sdB  S3=%d period=%d interleaver=%d generators=%d  %-10s %-42s %5.1fs"
              % (r["scheme"], r["snr_db"], r["s3_ok"], r["period_ok"],
                 r["interleaver_ok"], r["generators_ok"], r["status"],
                 r["reason"][:42], r["seconds"]), flush=True)

    out = ROOT / "reports" / "zoo_rf.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote", out)

    print("\n%-8s %-7s %-9s %-11s %s" % ("scheme", "S3 ok", "period", "interleaver", "generators"))
    for scheme in sorted({r["scheme"] for r in rows}):
        sub = [r for r in rows if r["scheme"] == scheme]
        print("%-8s %d/%-5d %d/%-7d %d/%-9d %d/%d"
              % (scheme, sum(r["s3_ok"] for r in sub), len(sub),
                 sum(r["period_ok"] for r in sub), len(sub),
                 sum(r["interleaver_ok"] for r in sub), len(sub),
                 sum(r["generators_ok"] for r in sub), len(sub)))

    print("\n%-8s %-7s %-11s" % ("SNR", "S3 ok", "full recovery"))
    for snr in sorted({r["snr_db"] for r in rows}):
        sub = [r for r in rows if r["snr_db"] == snr]
        print("%-8s %d/%-5d %d/%d" % ("%d dB" % snr, sum(r["s3_ok"] for r in sub),
                                      len(sub),
                                      sum(r["interleaver_ok"] and r["generators_ok"]
                                          for r in sub), len(sub)))

    # Does S3's own quality number predict whether S4 will succeed? Compare
    # the two populations rather than testing against zero - the estimate is
    # never exactly 0.0, it is 1e-87, and an earlier version of this summary
    # said "== 0.0" and reported nothing because of it.
    print()
    print("--- S3 estimated output BER vs S4 outcome ---")
    ok3 = [r for r in rows if r["s3_ok"]]
    rec = [r["s3_est_ber"] for r in ok3
           if r["interleaver_ok"] and r["generators_ok"]]
    bad = [r["s3_est_ber"] for r in ok3
           if not (r["interleaver_ok"] and r["generators_ok"])]
    if rec and bad:
        print("  recovered (%2d): est_BER max %.3e" % (len(rec), max(rec)))
        print("  failed    (%2d): est_BER min %.3e" % (len(bad), min(bad)))
        if max(rec) < min(bad):
            print("  Separable ON THIS CORPUS: every recovery <= %.1e, every"
                  % max(rec))
            print("  failure >= %.1e. EVM does NOT separate them." % min(bad))
            print("  CAVEAT, and it is not small: this corpus sets cfo=0,")
            print("  phase=0, timing=0. Re-measured through a channel WITH")
            print("  those impairments the populations OVERLAP (recovered up to")
            print("  1.19e-5, failed from 1.08e-5). So this is a useful")
            print("  heuristic, NOT an oracle - which is why the pre-flight in")
            print("  rotations.py gates only the expensive pass and can never")
            print("  suppress a recovery. See PREFLIGHT_BER_LIMIT.")
        else:
            print("  NOT separable on this corpus - the populations overlap.")

    full = sum(r["interleaver_ok"] and r["generators_ok"] for r in rows)
    print("\nFULL RECOVERY (interleaver AND generators): %d of %d" % (full, len(rows)))
    wrong = [r for r in rows
             if r["status"] == "ok" and not (r["interleaver_ok"] and r["generators_ok"])]
    print("CONFIDENTLY WRONG ANSWERS: %d" % len(wrong))
    for r in wrong:
        print("   ", r)


if __name__ == "__main__":
    main()
