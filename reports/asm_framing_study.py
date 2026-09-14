"""Does CCSDS-style ASM framing survive blind recovery, and does S6 find the ASM?

    python reports/asm_framing_study.py              # the four source arms
    python reports/asm_framing_study.py --geometry   # why the search is bit-level

Prints the tables reports/asm_framing.md quotes.

Four source arms, each through the same rate-1/2 K=7 code and 8x12 block
interleaver, at 12 start offsets (0, 8, ..., 88 coded bits trimmed):

  asm+random   frames of ASM 1ACFFC1D + 219 random bytes
  asm+text     frames of ASM + a housekeeping text record padded to 219 bytes
  random       no ASM, random bytes (control: the envelope the gate measures)
  text         no ASM, the demo message repeated (control: the known gap)

For each: does S4 recover the interleaver and code? If so, decode a prefix with
the recovered generators and ask S6 - both the shipped byte-aligned search and a
bit-level search - whether the ASM is there.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.s4_recover.interleavers  # noqa: E402,F401
from pipeline.s4_recover.interleavers import block_interleave  # noqa: E402
from pipeline.s4_recover.rank_collapse import blind_recover  # noqa: E402
from pipeline.s5_decode.conv_code import ConvCode  # noqa: E402
from pipeline.s5_decode.conv_reference import conv_encode  # noqa: E402
from pipeline.s6_frame import payload as s6  # noqa: E402
from registry import INTERLEAVERS  # noqa: E402

ASM = bytes.fromhex("1ACFFC1D")
FRAME_BYTES = 223                       # ASM + 219, a CCSDS-sized frame
N_SOURCE_BITS = 80_000
OFFSETS = list(range(0, 96, 8))
DECODE_CODED_BITS = 8_000               # 500 bytes of source: two frames


def source(arm: str, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    n_bytes = N_SOURCE_BITS // 8
    if arm == "random":
        return rng.integers(0, 256, n_bytes, dtype=np.uint8).tobytes()
    if arm == "text":
        msg = (b"RAAYA SIH26147 -- BLIND SIGNAL RECOVERY. This capture was "
               b"demodulated, de-interleaved and decoded with no prior knowledge. ")
        return (msg * (n_bytes // len(msg) + 1))[:n_bytes]
    frames = []
    k = 0
    while sum(len(f) for f in frames) < n_bytes:
        if arm == "asm+random":
            body = rng.integers(0, 256, FRAME_BYTES - 4, dtype=np.uint8).tobytes()
        else:
            rec = (b"HK SEQ=%05d BATT=7.%02dV TEMP=%+05.1fC MODE=NOMINAL RSSI=-%03d "
                   % (k, 30 + k % 40, 20.0 + (k % 9) * 0.7, 90 + k % 17))
            body = (rec * (FRAME_BYTES // len(rec) + 1))[:FRAME_BYTES - 4]
        frames.append(ASM + body)
        k += 1
    return b"".join(frames)[:n_bytes]


def run_case(arm: str, offset: int, seed: int) -> dict:
    src = np.unpackbits(np.frombuffer(source(arm, seed), dtype=np.uint8))
    coded = block_interleave(conv_encode(src), 8, 12)[offset:]
    t0 = time.monotonic()
    res = blind_recover(coded)
    out = {"arm": arm, "offset": offset, "s4": res.status, "s4_s": time.monotonic() - t0,
           "intl_ok": bool(res.interleaver is not None and res.interleaver.family == "block"
                           and res.interleaver.params == {"depth": 8, "width": 12}),
           "gens": tuple(res.generators_octal or ()), "asm_byte": None, "asm_bit": None}
    if not (res.status == "ok" and res.interleaver is not None and res.generators_octal):
        return out
    de = INTERLEAVERS[res.interleaver.family].deinterleave(coded[res.offset:], **res.interleaver.params)
    params = {"n": res.code.n, "memory": res.code.memory,
              "generators_octal": tuple(res.generators_octal), "span": res.code.span,
              "parity_taps": res.parity_taps or []}
    llrs = np.where(de[:DECODE_CODED_BITS] == 0, 4.0, -4.0)
    decoded = ConvCode().decode(llrs, params)
    # The byte column is the pre-14-Sep search, replicated here so the two can be
    # compared on the same decode; extract_text itself now uses the lock.
    out["asm_byte"] = s6.bits_to_bytes(decoded).find(s6.CCSDS_ASM) != -1
    lock = s6.find_asm(decoded)
    out["asm_bit"] = bool(lock is not None and lock.locked)
    return out


def geometry() -> int:
    """Why the search is bit-level: an interleaver whose block is not whole bytes.

    With 8x12 at rate 1/2 each block is 48 source bits, so the decode always
    starts on a byte boundary and a byte search happens to work. A 5x8 block is
    20 source bits, and it does not.
    """
    depth, width = 5, 8
    n_ok = n_byte = n_bit = 0
    for i, off in enumerate(range(0, 40, 4)):
        src = np.unpackbits(np.frombuffer(source("asm+text", 100 + i), dtype=np.uint8))
        coded = block_interleave(conv_encode(src), depth, width)[off:]
        r = blind_recover(coded)
        if not (r.status == "ok" and r.interleaver is not None and r.generators_octal):
            print("  offset %2d  S4 %s" % (off, r.status))
            continue
        de = INTERLEAVERS[r.interleaver.family].deinterleave(coded[r.offset:], **r.interleaver.params)
        dec = ConvCode().decode(np.where(de[:DECODE_CODED_BITS] == 0, 4.0, -4.0), {
            "n": r.code.n, "memory": r.code.memory, "generators_octal": tuple(r.generators_octal),
            "span": r.code.span, "parity_taps": r.parity_taps or []})
        byte = s6.bits_to_bytes(dec).find(s6.CCSDS_ASM) != -1
        lock = s6.find_asm(dec)
        bit = bool(lock and lock.locked)
        n_ok += 1
        n_byte += byte
        n_bit += bit
        print("  offset %2d  S4 ok  byte-search %-5s bit-lock %s" % (off, byte, bit))
    print("\n  5x8: S4 decodable %d/10, byte-search %d/%d, bit-lock %d/%d"
          % (n_ok, n_byte, n_ok, n_bit, n_ok))
    return 0


def main() -> int:
    if "--geometry" in sys.argv:
        return geometry()
    rows = []
    for arm in ("random", "text", "asm+random", "asm+text"):
        print("-- %s --" % arm)
        for i, off in enumerate(OFFSETS):
            r = run_case(arm, off, seed=100 + i)
            rows.append(r)
            print("  offset %2d  S4 %-15s intl=%-5s gens=%-12s asm(byte)=%-5s asm(bit)=%-5s %.1fs"
                  % (off, r["s4"], r["intl_ok"], r["gens"], r["asm_byte"], r["asm_bit"], r["s4_s"]))
    print("\n-- summary --")
    for arm in ("random", "text", "asm+random", "asm+text"):
        a = [r for r in rows if r["arm"] == arm]
        s4 = sum(r["intl_ok"] for r in a)
        byte = sum(bool(r["asm_byte"]) for r in a)
        bit = sum(bool(r["asm_bit"]) for r in a)
        print("  %-11s S4 correct %2d/12   ASM byte-search %2d/12   ASM bit-search %2d/12"
              % (arm, s4, byte, bit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
