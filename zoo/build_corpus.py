"""zoo/build_corpus.py

Generates the bits-only corpus per docs/zoo-bits-only-contract.md.

Run:  python -m zoo.build_corpus

Writes to zoo/corpus/bits_only/ -- one .npy + one .json per file. Once this
lands, delete tests/fixtures/local_zoo.py and re-run S4's gates against this
corpus instead. Two sources of ground truth must not coexist.
"""
from __future__ import annotations

from pathlib import Path

from zoo.bits_only import make_stream, make_uncoded_random, write_pair

OUT_DIR = Path(__file__).resolve().parent / "corpus" / "bits_only"

# Same-period pairs prove the FACTORISATION search works, not just the
# period search -- 8x12 and 16x6 both have period 96.
DEPTH_WIDTH = [(4, 8), (8, 12), (16, 6), (8, 16), (16, 8), (32, 4)]
BER_SWEEP = [0.0, 0.001, 0.002, 0.005, 0.01, 0.02]


def build() -> None:
    n = 0
    for scramble in (False, True):
        for (depth, width) in DEPTH_WIDTH:
            for ber in BER_SWEEP:
                seed = 1000 + n
                bits, truth = make_stream(
                    depth=depth, width=width, scramble=scramble,
                    ber=ber, seed=seed,
                )
                name = f"conv_d{depth}w{width}_ber{ber}_scr{int(scramble)}_{seed}"
                write_pair(bits, truth, OUT_DIR, name)
                n += 1

    bits, truth = make_uncoded_random(seed=999)
    write_pair(bits, truth, OUT_DIR, "uncoded_random_999")
    n += 1

    print(f"Wrote {n} files to {OUT_DIR}")


if __name__ == "__main__":
    build()