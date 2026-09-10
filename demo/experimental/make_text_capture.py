"""Build an RF capture that carries a READABLE message, for the UI demo.

Why this exists
---------------
All eight corpus captures in demo/signals carry RANDOM payload bits. They prove
the chain end to end, but the UI's payload panel then shows ~39% printable -
correct, and completely unmoving to watch. The one place a decoded MESSAGE
appears today is the CLI (`--demo --text`), which operates on bits and never
touches a waveform.

So this makes the same thing the CLI demonstrates, but as a real RF capture:
text -> convolutional encode -> block interleave -> QPSK -> RRC -> AWGN -> WAV.
Uploading it in the browser ends with the sentence on screen, recovered blind.

It composes zoo's PUBLIC functions and does not modify zoo/ - `make_rf_file`
simply does not expose `payload_text`, though `make_stream` beneath it does.

    python demo/make_text_capture.py

START OFFSET IS PINNED TO 0, AND THAT IS NOT A DEFAULT
------------------------------------------------------
`zoo.bits_only.make_stream` defaults to a RANDOM start offset. A repeating text
payload at a non-zero offset defeats the rank collapse: measured 1 of 10 offsets
against 10 of 10 for an unstructured payload, because ASCII is rank-deficient
before the code touches it (bit 7 is clear in every byte) and its own
periodicity collapses before the interleaver's. Leaving the offset random would
make this capture work about one time in ten - which is exactly the kind of
thing that works while you build it and fails in front of a judge.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from zoo.bits_only import make_stream                    # noqa: E402
from zoo.rf import RFTruth, through_channel, write_wav_pair   # noqa: E402

MESSAGE = (
    "RAAYA SIH26147 -- BLIND SIGNAL RECOVERY. This capture was demodulated, "
    "de-interleaved and decoded with no prior knowledge: the modulation, the "
    "interleaver depth and width, the code rate and both generator polynomials "
    "were all recovered from the waveform alone. "
)

SCHEME = "qpsk"
SNR_DB = 20.0
FS = 200_000.0
SPS = 4
BETA = 0.35
DEPTH, WIDTH = 8, 12
N_SOURCE_BITS = 20_000        # -> 40 000 coded bits, same order as the corpus
SEED = 26147
NAME = "qpsk_20dB_textpayload"


def main() -> int:
    coded_bits, bits_truth = make_stream(
        n_source_bits=N_SOURCE_BITS, depth=DEPTH, width=WIDTH,
        ber=0.0, seed=SEED, mean_burst=1.0, scramble=False,
        start_offset=0,                       # pinned - see module docstring
        payload_text=MESSAGE,
    )
    iq, n_used = through_channel(
        coded_bits, SCHEME, SPS, BETA, SNR_DB,
        cfo_norm=0.0, phase_rad=0.0, timing_offset_sym=0.0, seed=SEED,
    )
    truth = RFTruth(
        scheme=SCHEME, fs=FS, sps=SPS, beta=BETA, snr_db=SNR_DB,
        cfo_norm=0.0, phase_rad=0.0, timing_offset_sym=0.0, seed=SEED,
        n_bits_used=n_used, code=bits_truth.code,
        interleaver=bits_truth.interleaver, scrambler=bits_truth.scrambler,
        injected_ber=0.0, error_model="independent",
    )
    out = HERE / "signals"
    write_wav_pair(iq, truth, out, NAME)
    wav = out / f"{NAME}.wav"
    print("wrote %s (%.0f kB)" % (wav, wav.stat().st_size / 1024))
    print("  scheme=%s snr=%.0f dB  interleaver=%s  code=%s"
          % (SCHEME, SNR_DB, truth.interleaver, truth.code))
    print("  payload: %s..." % MESSAGE[:60])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
