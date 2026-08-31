"""Stage 4 on its own, from a terminal. No API, no browser, no Docker.

    python -m pipeline.s4_recover.cli <bitstream>
    python -m pipeline.s4_recover.cli --demo

Accepts .npy (0/1 uint8 array), or any other file read as raw bytes and
unpacked MSB-first into bits.

This exists because of the "if only 48 hours remain" floor in the plan: the one
path that must survive everything is a single command that prints recovered
parameters to a terminal. Keeping it working from day one costs almost nothing
and means the S4 demo never depends on anyone else's stage being up.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s4_recover.rank_collapse import blind_recover, max_searchable_period
from pipeline.s4_recover.statistical import statistical_recover
from pipeline.s4_recover.interleavers import block_deinterleave


def load_bits(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        arr = np.load(path)
        return np.asarray(arr, dtype=np.uint8).ravel()
    raw = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    return np.unpackbits(raw)


def report(bits: np.ndarray, statistical: bool, quiet: bool = False) -> int:
    print("stream            : %d bits" % len(bits))
    print("searchable period : up to %d (limited by stream length)"
          % max_searchable_period(len(bits)))
    print()

    t0 = time.time()
    res = blind_recover(bits)
    elapsed = time.time() - t0

    print("--- exact rank collapse ---------------------------------------")
    print("status            : %s (confidence %.2f)" % (res.status, res.confidence))
    print("result            : %s" % res.summary())
    if res.reason:
        print("note              : %s" % res.reason)
    if res.code and res.code.n:
        print("code              : rate 1/%d, memory m=%d, constraint length K=%d"
              % (res.code.n, res.code.memory, res.code.memory + 1))
        print("constraint span   : %d bits" % res.code.span)
    if res.generators_octal:
        print("generators        : " + ", ".join("0o%o" % g for g in res.generators_octal))
    if res.parity_taps:
        print("parity check      : " + "".join(str(b) for b in res.parity_taps))
    if len(res.hypotheses) > 1:
        print("other hypotheses  :")
        for h in res.hypotheses[1:5]:
            print("    %-28s score %.2f  %s"
                  % ("%s%s" % (h.family, h.params), h.score, h.evidence))
    print("elapsed           : %.2f s" % elapsed)

    deinterleaved = None
    if res.status == "ok" and res.interleaver:
        deinterleaved = block_deinterleave(bits[res.offset:], **res.interleaver.params)
        print()
        print("de-interleaved    : %d bits ready for S5 (Viterbi)" % len(deinterleaved))

    if statistical:
        # Run the statistical search on the de-interleaved stream when we have
        # one. A code's parity check is short - 14 bits here - but interleaving
        # scatters its support across the whole block, so on the interleaved
        # stream there is no short check to find and the search correctly
        # reports nothing. That is a true answer to the wrong question.
        target = deinterleaved if deinterleaved is not None else bits
        where = "de-interleaved stream" if deinterleaved is not None else "raw stream"
        print()
        print("--- statistical parity check (%s) ---" % where)
        t0 = time.time()
        stat = statistical_recover(target, max_span=24)
        print("status            : %s" % stat.status)
        print("result            : %s" % stat.describe())
        if stat.validation and stat.validation.implied_ber is not None:
            print("inferred channel  : BER %.4f" % stat.validation.implied_ber)
        print("elapsed           : %.2f s" % (time.time() - t0))

    return 0 if res.status == "ok" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Blind interleaver and code recovery (Stage 4)")
    ap.add_argument("path", nargs="?", type=Path, help=".npy bit array, or a raw binary file")
    ap.add_argument("--demo", action="store_true",
                    help="run against a locally generated coded stream")
    ap.add_argument("--statistical", action="store_true",
                    help="also run the statistical parity-check search")
    ap.add_argument("--depth", type=int, default=8, help="demo interleaver depth")
    ap.add_argument("--width", type=int, default=12, help="demo interleaver width")
    ap.add_argument("--ber", type=float, default=0.0, help="demo injected bit error rate")
    args = ap.parse_args(argv)

    if args.demo:
        from tests.fixtures.local_zoo import make_stream
        bits, truth = make_stream(80_000, args.depth, args.width, ber=args.ber, seed=0)
        print("DEMO - generated locally, truth withheld from the recovery below")
        print("truth             : period=%d depth=%d width=%d G=(0o171, 0o133) BER=%.4f"
              % (truth.period, truth.depth, truth.width, truth.injected_ber))
        print()
        return report(bits, args.statistical)

    if args.path is None:
        ap.error("give a file, or --demo")
    if not args.path.exists():
        print("no such file: %s" % args.path, file=sys.stderr)
        return 2
    return report(load_bits(args.path), args.statistical)


if __name__ == "__main__":
    raise SystemExit(main())
