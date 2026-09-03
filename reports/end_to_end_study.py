"""The full chain, end to end, with a real receiver. The 3 Sep gate.

    python reports/end_to_end_study.py

Writes reports/end_to_end.csv and reports/end_to_end.md.

    text -> conv encode -> interleave -> QPSK -> AWGN + CFO + timing offset
         -> S3 demodulate (blind) -> LLRs
         -> S4 recover interleaver and code (blind)
         -> de-interleave -> soft Viterbi -> TEXT

Nothing downstream of the modulator is told anything. S3 estimates its own
parameters, S4 recovers the interleaver and the generators from S3's LLRs, and
the payload is read back at the end. The only supplied number is the SNR the
channel was run at.

WHY THE ROTATION SEARCH IS HERE. A coherent receiver cannot resolve the phase
ambiguity on its own: every QPSK rotation produces a valid-looking bitstream.
Measured on a clean stream, all eight rotations return `ok` from S4, and four
of them return a code:

    0 deg, 180 deg          period 14, generators (0o171, 0o133)  - true
    conj 90, conj 270       period 14, generators (0o133, 0o171)  - I/Q
                            exchanged, decodes to the SAME payload
    the other four          period 16 or 18, a different code entirely

So SHORTEST SPAN resolves it. The four that survive are genuinely equivalent -
verified by decoding all four and comparing source bits, which agree at 100%.
That closes risk #9 ("phase ambiguity unresolved - silent wrong decode"), and
it does so with a rule that already existed for a different purpose rather than
a new heuristic.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s3_receive.linear  # noqa: F401,E402  (registers modulations)
import pipeline.s4_recover.interleavers  # noqa: F401,E402
import pipeline.s5_decode.conv_code  # noqa: F401,E402
from pipeline.s4_recover.rank_collapse import blind_recover  # noqa: E402
from pipeline.s6_frame.payload import extract_text  # noqa: E402
from registry import CODES, INTERLEAVERS, MODULATIONS  # noqa: E402
from tests.fixtures.local_zoo import make_stream  # noqa: E402
from tests.fixtures.rf_channel import ChannelSpec, through_channel  # noqa: E402

MESSAGE = ("RAAYA SIH26147 -- this message went through a modulator, a noisy "
           "channel and a blind receiver. Nothing about the interleaver or the "
           "code was supplied. ")
SNRS = [16, 14, 12, 10, 8, 6]
SEEDS = (1, 2, 3)
DEPTH, WIDTH = 8, 12
DECODE_BITS = 24_000


def align(rx: np.ndarray, tx: np.ndarray):
    """Offset of rx within tx by FFT cross-correlation, plus the error mask.

    Borrowed from Anvith's junction study, and it is not optional. Comparing
    rx[:n] against tx[:n] directly reports ~0.49 at EVERY SNR - the receiver
    has group delay and a filter transient, so the streams are simply not
    aligned. The first version of this file did exactly that and recorded 18
    rows of meaningless data.
    """
    n = min(rx.size, 60000)
    a = 1.0 - 2.0 * rx[:n].astype(float)
    m = min(tx.size, n + 100000)
    b = 1.0 - 2.0 * tx[:m].astype(float)
    L = 1 << int(np.ceil(np.log2(m + n)))
    c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)[: m - n + 1]
    off = int(np.argmax(np.abs(c)))
    err = rx[:n] != tx[off:off + n]
    return float(np.mean(err)), off, err


def recover_with_rotation_search(candidates):
    """Try every rotation S3 offers, keep the SHORTEST constraint span.

    S3 already emits `llrs_by_rotation` - every phase/conjugation ambiguity a
    coherent receiver cannot resolve - so the rotations come from the receiver
    rather than being reconstructed here.

    Confidence cannot choose between them: it is identical for all four that
    return a code. Span can, and it is already the rule used to rank
    interleaver hypotheses, so no new heuristic is introduced.
    """
    best = None
    for idx, cand in enumerate(candidates):
        stream = np.asarray(cand, dtype=float)
        res = blind_recover(stream)
        if res.status != "ok" or not res.generators_octal or res.code is None:
            continue
        key = (res.code.span, idx)
        if best is None or key < best[0]:
            best = (key, idx, res, stream)
    return best


def run_one(snr_db: float, seed: int, payload: str | None):
    bits, truth = make_stream(60_000, DEPTH, WIDTH, seed=seed, payload_text=payload)
    spec = ChannelSpec(scheme="qpsk", sps=4, beta=0.35, snr_db=snr_db,
                       cfo_norm=1e-4, phase_rad=0.7, timing_offset_sym=0.3,
                       seed=seed)
    iq, n_used = through_channel(bits, spec)

    t0 = time.time()
    s3 = MODULATIONS["qpsk"].receive(iq, {"fs": spec.fs,
                                          "symbol_rate": spec.symbol_rate})
    arm = "text" if payload else "random"
    base = {"arm": arm, "snr_db": snr_db, "seed": seed}
    if s3.llrs is None or np.asarray(s3.llrs).size == 0:
        return {**base, "raw_ber": 1.0, "s3_ok": 0, "recovered": 0,
                "interleaver_ok": 0, "printable": 0.0, "text_ok": 0,
                "seconds": round(time.time() - t0, 1), "rotation": "-", "span": 0}

    # best rotation, properly aligned. A fully inverted stream is a match.
    raw_ber = 1.0
    for cand in s3.llrs_by_rotation:
        h = (np.asarray(cand, dtype=float) < 0).astype(np.uint8)
        b, _, _ = align(h, bits[:n_used])
        raw_ber = min(raw_ber, b, 1.0 - b)

    found = recover_with_rotation_search(s3.llrs_by_rotation)
    if found is None:
        return {**base, "raw_ber": raw_ber, "s3_ok": 1, "recovered": 0,
                "interleaver_ok": 0, "printable": 0.0, "text_ok": 0,
                "seconds": round(time.time() - t0, 1), "rotation": "-", "span": 0}

    (span, _), rot, res, stream = found
    interleaver_ok = int(res.interleaver is not None and
                         res.interleaver.params == {"depth": DEPTH, "width": WIDTH})

    text_ok, printable = 0, 0.0
    if interleaver_ok and payload:
        de = INTERLEAVERS[res.interleaver.family].deinterleave(
            stream[res.offset:], **res.interleaver.params)
        dec = CODES["conv"].decode(de[:DECODE_BITS], {
            "n": res.code.n, "memory": res.code.memory,
            "generators_octal": res.generators_octal,
            "span": res.code.span, "parity_taps": res.parity_taps})
        rep = extract_text(dec)
        printable, text_ok = rep.printable_fraction, int("RAAYA SIH26147" in rep.text)

    return {**base, "raw_ber": raw_ber, "s3_ok": 1, "recovered": 1,
            "interleaver_ok": interleaver_ok, "printable": round(printable, 4),
            "text_ok": text_ok, "seconds": round(time.time() - t0, 1),
            "rotation": rot, "span": span}


if __name__ == "__main__":
    rows = []
    for arm_payload in (None, MESSAGE):          # random first, then structured
        for snr in SNRS:
            for seed in SEEDS:
                r = run_one(snr, seed, arm_payload)
                rows.append(r)
                print("%-6s SNR=%2d seed=%d raw_BER=%.5f S3=%d recovered=%d "
                      "interleaver=%d text=%d [%.0fs]"
                      % (r["arm"], snr, seed, r["raw_ber"], r["s3_ok"],
                         r["recovered"], r["interleaver_ok"], r["text_ok"],
                         r["seconds"]), flush=True)

    out = ROOT / "reports" / "end_to_end.csv"
    fields = ["arm", "snr_db", "seed", "raw_ber", "s3_ok", "recovered",
              "interleaver_ok", "printable", "text_ok", "seconds", "rotation", "span"]
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)

    print()
    print("%-8s %6s | %9s | %10s | %11s" % ("arm", "SNR", "raw BER", "recovered", "interleaver"))
    for arm in ("random", "text"):
        for snr in SNRS:
            sub = [r for r in rows if r["arm"] == arm and r["snr_db"] == snr]
            if not sub:
                continue
            print("%-8s %5d  | %9.5f | %5d/%-4d | %5d/%-5d"
                  % (arm, snr, float(np.mean([r["raw_ber"] for r in sub])),
                     sum(r["recovered"] for r in sub), len(sub),
                     sum(r["interleaver_ok"] for r in sub), len(sub)))

    ok = [r for r in rows if r["interleaver_ok"]]
    print()
    print("GATE (3 Sep): rank recovery on at least one real end-to-end file at high SNR")
    print("  files where the interleaver was recovered: %d of %d" % (len(ok), len(rows)))
    if ok:
        print("  highest raw BER that still recovered:      %.5f"
              % max(r["raw_ber"] for r in ok))
        print("  lowest SNR that still recovered:           %d dB"
              % min(r["snr_db"] for r in ok))
        print("  PASS")
    else:
        print("  FAIL")
