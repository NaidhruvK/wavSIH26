"""Blind recovery of pseudo-random (QPP) interleavers - measured, not asserted.

    python reports/pseudorandom_interleaver_study.py

Writes reports/pseudorandom_interleavers.csv and prints the tables that
reports/pseudorandom_interleavers.md quotes.

Every case goes through `blind_recover` with nothing but the interleaved coded
bits. Recovery is scored by comparing PERMUTATIONS, never coefficient pairs:
QPP coefficients alias (K=96 has 512 valid pairs and only 256 distinct
permutations), so a coefficient-comparing test reports correct recoveries as
failures. See `pseudorandom.qpp_candidates`.

Arms:
  lte        LTE TS 36.212 table triples at sizes the stream can support
  relprime   f2 = 0, the relative-prime / golden interleaver
  open       QPP pairs drawn at random from the valid set, off the LTE table
  keyed      an unstructured random permutation - must NOT be inverted, and
             must report the period
  regress    block / diagonal / convolutional / raw coded / uncoded random, to
             show the new family and the budget changes broke nothing
  cost       wall clock of one functional test (de-interleave + code search)
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s4_recover.interleavers as il  # noqa: E402  (registers families)
import pipeline.s4_recover.pseudorandom as pr  # noqa: E402
from pipeline.s4_recover.rank_collapse import (  # noqa: E402
    blind_recover, max_searchable_period, recover_code_structure)
from pipeline.s5_decode.conv_reference import conv_encode  # noqa: E402

N_SOURCE = 60_000                 # 120 000 coded bits
SEED = 1
LTE_SIZES = (40, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 240,
             256, 288)
RELPRIME = ((32, 5), (40, 7), (48, 11), (64, 9), (72, 25), (80, 13), (96, 25),
            (120, 49), (128, 37), (160, 59), (192, 71), (256, 101))
N_OPEN = 12
N_KEYED = 8


def _perm_ok(res, K, f1, f2) -> bool:
    if res.interleaver is None or res.interleaver.family != "qpp":
        return False
    g = res.interleaver.params
    return (g["period"] == K and np.array_equal(
        pr.qpp_permutation(g["period"], g["f1"], g["f2"]),
        pr.qpp_permutation(K, f1, f2)))


def _run(label, tx, check):
    t0 = time.monotonic()
    res = blind_recover(tx)
    el = time.monotonic() - t0
    return {"arm": label, "ok": bool(check(res)), "seconds": round(el, 2),
            "status": res.status, "period": res.period,
            "family": res.interleaver.family if res.interleaver else "",
            "params": res.interleaver.params if res.interleaver else "",
            "verdict": (res.interleaver_verdict or {}).get("verdict", ""),
            "K_code": (res.code.memory + 1) if res.code and res.code.memory is not None else ""}


def main() -> int:
    rng = np.random.default_rng(SEED)
    coded = conv_encode(rng.integers(0, 2, N_SOURCE, dtype=np.uint8))
    print("coded bits %d, max searchable period %d"
          % (coded.size, max_searchable_period(coded.size)))
    rows = []

    print("\n-- lte --")
    for K in LTE_SIZES:
        f1, f2 = pr.LTE_QPP[K]
        r = _run("lte", pr.qpp_interleave(coded, K, f1, f2),
                 lambda res, K=K, f1=f1, f2=f2: _perm_ok(res, K, f1, f2))
        r.update(K=K, f1=f1, f2=f2)
        rows.append(r)
        print("  K=%3d (%3d,%3d) %-4s %5.1fs" % (K, f1, f2, "ok" if r["ok"] else "MISS", r["seconds"]))

    print("\n-- relprime --")
    for K, f1 in RELPRIME:
        r = _run("relprime", pr.qpp_interleave(coded, K, f1, 0),
                 lambda res, K=K, f1=f1: _perm_ok(res, K, f1, 0))
        r.update(K=K, f1=f1, f2=0)
        rows.append(r)
        print("  K=%3d (%3d,  0) %-4s %5.1fs" % (K, f1, "ok" if r["ok"] else "MISS", r["seconds"]))

    print("\n-- open (random valid pairs, off the LTE table) --")
    orng = np.random.default_rng(99)
    done = 0
    while done < N_OPEN:
        K = int(orng.choice((48, 64, 96, 128, 160, 192)))
        units = pr.coprime_to(K)
        rad = pr.radical(K)
        f1 = int(orng.choice(units))
        f2 = int(orng.choice(np.arange(rad, K, rad)))
        if not pr.is_qpp_permutation(K, f1, f2) or pr.LTE_QPP.get(K) == (f1, f2):
            continue
        # where does this permutation sit in the capped candidate order?
        target = pr.qpp_permutation(K, f1, f2).tobytes()
        rank = None
        for i, c in enumerate(pr.qpp_candidates(K, max_candidates=10 ** 6)):
            if pr.qpp_permutation(K, c["f1"], c["f2"]).tobytes() == target:
                rank = i + 1
                break
        r = _run("open", pr.qpp_interleave(coded, K, f1, f2),
                 lambda res, K=K, f1=f1, f2=f2: _perm_ok(res, K, f1, f2))
        r.update(K=K, f1=f1, f2=f2, candidate_rank=rank)
        rows.append(r)
        done += 1
        print("  K=%3d (%3d,%3d) rank %4s/%d cap %-4s %5.1fs" % (
            K, f1, f2, rank, pr.QPP_MAX_CANDIDATES, "ok" if r["ok"] else "MISS", r["seconds"]))

    print("\n-- keyed (unstructured permutation, K=96) --")
    K = 96
    nb = coded.size // K
    for s in range(N_KEYED):
        perm = np.random.default_rng(1000 + s).permutation(K)
        tx = coded[:nb * K].reshape(nb, K)[:, perm].reshape(-1)
        r = _run("keyed", tx, lambda res: res.status != "ok" and res.interleaver is None)
        r.update(K=K)
        rows.append(r)
        print("  seed %d  not-inverted=%s period=%s verdict=%s %5.1fs"
              % (s, r["ok"], r["period"], r["verdict"], r["seconds"]))

    print("\n-- regress --")
    cases = [
        ("block 8x12", il.block_interleave(coded, 8, 12),
         lambda res: res.interleaver is not None and res.interleaver.family == "block"
         and res.interleaver.params == {"depth": 8, "width": 12}),
        ("diagonal 8x12", il.diagonal_interleave(coded, 8, 12),
         lambda res: res.interleaver is not None and res.interleaver.family == "diagonal"
         and res.interleaver.params == {"depth": 8, "width": 12}),
        ("convolutional 4x1", il.conv_interleave(coded, 4, 1),
         lambda res: res.interleaver is not None and res.interleaver.family == "convolutional"),
        ("raw coded", coded,
         lambda res: res.status == "ok" and res.interleaver is None
         and res.code is not None and res.code.memory == 6),
        ("uncoded random", rng.integers(0, 2, coded.size, dtype=np.uint8),
         lambda res: res.status != "ok"),
    ]
    for label, tx, check in cases:
        r = _run("regress", tx, check)
        r.update(case=label)
        rows.append(r)
        print("  %-18s %-4s %-14s %5.1fs" % (label, "ok" if r["ok"] else "FAIL", r["status"], r["seconds"]))

    print("\n-- cost of one functional test --")
    K, f1, f2 = 96, 11, 24
    tx = pr.qpp_interleave(coded, K, f1, f2)
    cands = list(pr.qpp_candidates(K))
    t0 = time.monotonic()
    for c in cands[:64]:
        de = pr.qpp_deinterleave(tx, **c)
        recover_code_structure(de)
    per = (time.monotonic() - t0) / 64
    print("  %.1f ms per candidate (K=96, %d bits); %d candidates = %.1f s"
          % (per * 1e3, tx.size, len(cands), per * len(cands)))
    rows.append({"arm": "cost", "ok": True, "seconds": round(per, 4), "K": 96})

    print("\n-- summary --")
    for arm in ("lte", "relprime", "open", "keyed", "regress"):
        a = [r for r in rows if r["arm"] == arm]
        t = [r["seconds"] for r in a]
        print("  %-9s %2d of %2d   worst %.1fs" % (arm, sum(r["ok"] for r in a), len(a), max(t)))

    out = ROOT / "reports" / "pseudorandom_interleavers.csv"
    keys = sorted({k for r in rows for k in r})
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\nwrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
