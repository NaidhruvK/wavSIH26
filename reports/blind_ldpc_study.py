"""Closed-set blind LDPC identification - measured, not asserted.

    python reports/blind_ldpc_study.py

Prints the tables reports/blind_ldpc.md quotes.

Arms:
  identify   every catalogue entry, codeword start shifted so the offset search
             has to find it; must return the exact code AND the exact offset
  cross      every true stream scored against every OTHER catalogue entry - the
             wrong-code null, worst case over the whole catalogue
  random     200 random streams against the weakest entry - the empirical null
  degenerate streams that satisfy every linear code (zeros) or look structured;
             must all be refused
  ber        identification under independent bit errors
  margin     winner z over runner-up z on real matches (ID_RUNNER_UP_RATIO)
  s5cost     each CODES plug-in's blind_recover wall clock on one stream - the
             figures S5_BLIND_SWEEP_BUDGET_S is set against
  decode     identification output fed straight to decode + syndrome
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s5_decode.conv_code  # noqa: E402,F401  (registers conv)
import pipeline.s5_decode.ldpc_code as L  # noqa: E402
import pipeline.s5_decode.rs_code  # noqa: E402,F401  (registers reed-solomon)
from pipeline.s5_decode.ldpc_catalogue import (build_reference_catalogue,  # noqa: E402
                                               codewords_from_h, load_catalogue)
from registry import CODES  # noqa: E402


def main() -> int:
    build_reference_catalogue()
    cat = load_catalogue()
    ldpc = CODES["ldpc"]
    print("catalogue: %d entries" % len(cat))

    print("\n-- identify (start shifted 37 bits) --")
    streams = {}
    n_ok = 0
    worst_t = 0.0
    margins = []
    for e in cat:
        stream, _ = codewords_from_h(e.h, L.MIN_ID_BLOCKS + 4, seed=3)
        streams[e.name] = stream
        shift = 37 % e.n
        padded = np.concatenate(
            [np.random.default_rng(9).integers(0, 2, shift, dtype=np.uint8), stream])
        t0 = time.monotonic()
        got = ldpc.blind_recover(padded)
        el = time.monotonic() - t0
        worst_t = max(worst_t, el)
        ok = got is not None and got["code_name"] == e.name and got["offset"] == shift
        n_ok += ok
        if got is not None and got.get("runner_up_z"):
            margins.append(got["z_score"] / got["runner_up_z"])
        print("  %-36s %-4s z=%6.1f runner-up=%s  %.2fs" % (
            e.name, "ok" if ok else "MISS", got["z_score"] if got else 0.0,
            ("%.1f" % got["runner_up_z"]) if got and got["runner_up_z"] is not None else "-", el))
    print("  %d of %d exact code and offset, worst %.2fs" % (n_ok, len(cat), worst_t))

    print("\n-- cross (true stream vs every other entry) --")
    worst = (-99.0, "", "")
    weakest = (99.0, "")
    for t in cat:
        off, d, nch = L._best_offset_by_syndrome(streams[t.name], t.h, L.MIN_ID_BLOCKS)
        z = L._syndrome_z(d, nch)
        if z < weakest[0]:
            weakest = (z, t.name)
        for o in cat:
            if o.name == t.name:
                continue
            off, d, nch = L._best_offset_by_syndrome(streams[t.name], o.h, L.MIN_ID_BLOCKS)
            if off is None:
                continue
            z = L._syndrome_z(d, nch)
            if z > worst[0]:
                worst = (z, t.name, o.name)
    print("  worst wrong-code z %+.2f (stream %s vs H %s)" % worst)
    print("  weakest true-code z %+.2f (%s)" % weakest)

    print("\n-- random (200 streams vs the smallest entry) --")
    small = min(cat, key=lambda e: e.n)
    rng = np.random.default_rng(2)
    zs = []
    for _ in range(200):
        b = rng.integers(0, 2, small.n * (L.MIN_ID_BLOCKS + 4), dtype=np.uint8)
        off, d, nch = L._best_offset_by_syndrome(b, small.h, L.MIN_ID_BLOCKS)
        zs.append(L._syndrome_z(d, nch))
    zs = np.array(zs)
    print("  mean %+.2f  p99 %+.2f  max %+.2f  over ID_Z_MIN=%.1f: %d of 200"
          % (zs.mean(), np.percentile(zs, 99), zs.max(), L.ID_Z_MIN, int((zs >= L.ID_Z_MIN).sum())))

    print("\n-- degenerate / structured inputs (must refuse) --")
    r2 = np.random.default_rng(11)
    nulls = {
        "uncoded random": r2.integers(0, 2, 20000, dtype=np.uint8),
        "all zeros": np.zeros(20000, dtype=np.uint8),
        "all ones": np.ones(20000, dtype=np.uint8),
        "alternating": np.tile([0, 1], 10000).astype(np.uint8),
        "period-8 pattern": np.tile([1, 0, 1, 1, 0, 0, 1, 0], 2500).astype(np.uint8),
        "biased P(1)=0.7": (r2.random(20000) < 0.7).astype(np.uint8),
        "ASCII text bits": np.unpackbits(np.frombuffer(
            (b"The quick brown fox jumps over the lazy dog. " * 60)[:2500], dtype=np.uint8)),
    }
    refused = 0
    for label, b in nulls.items():
        got = ldpc.blind_recover(b)
        refused += got is None
        print("  %-18s %s" % (label, "refused" if got is None else "MATCHED " + got["code_name"]))
    print("  %d of %d refused" % (refused, len(nulls)))

    print("\n-- ber (gallager-n96-963, 12 blocks) --")
    target = next(e for e in cat if e.name == "gallager-n96-r1_2-963")
    clean, _ = codewords_from_h(target.h, 12, seed=7)
    for eps in (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10):
        noisy = clean.copy()
        noisy[np.random.default_rng(13).random(noisy.size) < eps] ^= 1
        got = ldpc.blind_recover(noisy)
        print("  eps=%.3f  %s" % (eps, "refused" if got is None else "%s dens=%.3f z=%+.1f" % (
            got["code_name"], got["syndrome_density"], got["z_score"])))

    print("\n-- margin (winner z / runner-up z on real matches) --")
    if margins:
        print("  %.1fx .. %.1fx  (ID_RUNNER_UP_RATIO %.1f)" % (min(margins), max(margins), L.ID_RUNNER_UP_RATIO))

    print("\n-- s5cost (blind_recover per plug-in, 24 000-bit LDPC stream as soft LLRs) --")
    big, _ = codewords_from_h(target.h, 250, seed=31)
    llrs = np.where(big == 0, 6.0, -6.0)
    for name, plugin in CODES.items():
        t0 = time.monotonic()
        got = plugin.blind_recover(llrs)
        print("  %-14s %.2fs  %s" % (name, time.monotonic() - t0,
                                     "identified" if got is not None else "declined"))

    print("\n-- decode (identification output -> decode + syndrome) --")
    shift = 61
    padded = np.concatenate([np.random.default_rng(4).integers(0, 2, shift, dtype=np.uint8),
                             codewords_from_h(target.h, 12, seed=21)[0]])
    soft = np.where(padded == 0, 6.0, -6.0)
    got = ldpc.blind_recover(soft)
    syn = ldpc.syndrome(soft, got)
    out = ldpc.decode(soft, got)
    print("  %s offset %d (true %d); %d of %d blocks converged; %d bits out"
          % (got["code_name"], got["offset"], shift, syn["blocks_converged"], syn["blocks"], len(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
