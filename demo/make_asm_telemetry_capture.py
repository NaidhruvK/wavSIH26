"""Build the RF capture that carries FRAMED telemetry, for S6's ASM lock.

    python demo/make_asm_telemetry_capture.py            # write the capture
    python demo/make_asm_telemetry_capture.py --sweep    # measure all 12 offsets

Writes demo/signals/qpsk_20dB_asm_telemetry.{wav,json}, byte-identical every run.

WHAT IT CARRIES
---------------
Frames of 223 bytes: the CCSDS attached sync marker 1ACFFC1D, then a 219-byte
body of housekeeping records ("HK SEQ=00007 BATT=7.37V TEMP=+24.9C MODE=NOMINAL
RSSI=-097"). The sequence counter and readings change every frame. Then the
same chain as the text capture: rate-1/2 K=7 convolutional code, 8x12 block
interleaver, QPSK, RRC, 20 dB AWGN, WAV.

WHY THIS ONE IS NOT THE TEXT CAPTURE'S 1-IN-12
---------------------------------------------
qpsk_20dB_textpayload decodes at 1 of 12 generator offsets, because its source is
one message repeated EXACTLY, and that exact long periodicity puts spurious rank
collapses ahead of the interleaver's. reports/asm_framing_study.py measured the
bits-domain arms at 12 offsets each:

    random bytes                         S4 correct 12/12
    one message repeated exactly          S4 correct  1/12
    ASM + random bytes                   S4 correct 12/12
    ASM + housekeeping varying per frame S4 correct 12/12

`--sweep` repeats that through the REAL orchestrator from a WAV, which is what
the start offset below is chosen against - see reports/asm_framing.md for the
table it printed.

WHAT IT DOES NOT PROVE
----------------------
S6 synchronises on a KNOWN marker. It does not discover an unknown frame header,
and a telemetry format whose frames repeat exactly would hit the same gap the
text capture does. Synthetic, like every capture in demo/signals.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.s4_recover.interleavers import block_interleave          # noqa: E402
from pipeline.s5_decode.conv_reference import conv_encode, POLY_171_133  # noqa: E402
from zoo.rf import RFTruth, through_channel, write_wav_pair            # noqa: E402

ASM = bytes.fromhex("1ACFFC1D")
FRAME_BYTES = 223
SCHEME = "qpsk"
SNR_DB = 20.0
FS = 200_000.0
SPS = 4
BETA = 0.35
DEPTH, WIDTH = 8, 12
N_FRAMES = 12                  # 2676 bytes -> 21 408 source bits, 42 816 coded
SEED = 26147
START_OFFSET = 37              # an arbitrary non-boundary offset; see --sweep
NAME = "qpsk_20dB_asm_telemetry"


def frames() -> bytes:
    out = []
    for k in range(N_FRAMES):
        rec = (b"HK SEQ=%05d BATT=7.%02dV TEMP=%+05.1fC MODE=NOMINAL RSSI=-%03d "
               % (k, 30 + (k * 7) % 40, 20.0 + (k % 9) * 0.7, 90 + (k * 5) % 17))
        body = (rec * (FRAME_BYTES // len(rec) + 1))[:FRAME_BYTES - 4]
        out.append(ASM + body)
    return b"".join(out)


def build(start_offset: int):
    src = np.unpackbits(np.frombuffer(frames(), dtype=np.uint8))
    coded = block_interleave(conv_encode(src), DEPTH, WIDTH)[start_offset:]
    iq, n_used = through_channel(coded, SCHEME, SPS, BETA, SNR_DB,
                                 cfo_norm=0.0, phase_rad=0.0,
                                 timing_offset_sym=0.0, seed=SEED)
    truth = RFTruth(
        scheme=SCHEME, fs=FS, sps=SPS, beta=BETA, snr_db=SNR_DB,
        cfo_norm=0.0, phase_rad=0.0, timing_offset_sym=0.0, seed=SEED,
        n_bits_used=n_used,
        code={"family": "conv", "rate": "1/2", "K": 7,
              "polys_octal": list(POLY_171_133), "poly_notation": "octal"},
        interleaver={"family": "block", "depth": DEPTH, "width": WIDTH,
                     "period": DEPTH * WIDTH},
        scrambler=None, injected_ber=0.0, error_model="independent",
    )
    return iq, truth


def write(out_dir: Path, name: str, start_offset: int) -> Path:
    iq, truth = build(start_offset)
    write_wav_pair(iq, truth, out_dir, name)
    meta = out_dir / f"{name}.json"
    d = json.loads(meta.read_text())
    d.update({"start_offset": start_offset, "framing": {
        "asm_hex": ASM.hex().upper(), "frame_bytes": FRAME_BYTES, "n_frames": N_FRAMES}})
    meta.write_text(json.dumps(d, indent=2))
    return out_dir / f"{name}.wav"


def sweep() -> int:
    from service.orchestrator import load_plugins, orchestrate
    from service.config import config
    load_plugins()
    ok = 0
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        object.__setattr__(config, "artifact_dir", tmp / "artifacts")
        for off in range(0, 96, 8):
            wav = write(tmp, f"sweep_{off}", off)
            t0 = time.monotonic()
            rep = orchestrate(str(uuid.uuid4()), wav, db_path=tmp / "sweep.db")
            st = {s.stage: s for s in rep.stages}
            s4, s6 = st["s4_recover"], st["s6_frame"]
            v6 = s6.values
            full = all(s.status.value == "ok" for s in rep.stages)
            locked = bool(v6.get("asm_lock"))
            ok += full and locked
            print("offset %2d  stages ok %d/7  S4 %-14s %-24s ASM lock %-5s hits %-2s frame %s bits  %.1fs"
                  % (off, sum(s.status.value == "ok" for s in rep.stages), s4.status.value,
                     str(s4.values.get("interleaver_params")), locked, v6.get("asm_hits"),
                     v6.get("asm_frame_bits"), time.monotonic() - t0))
    print("\n%d of 12 offsets: all seven stages ok AND ASM lock" % ok)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    if ap.parse_args().sweep:
        return sweep()
    wav = write(HERE / "signals", NAME, START_OFFSET)
    print("wrote %s (%.0f kB), start_offset=%d, %d frames"
          % (wav, wav.stat().st_size / 1024, START_OFFSET, N_FRAMES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
