"""zoo/build_rf_corpus.py

Generates the RF/IQ WAV corpus. Run: python -m zoo.build_rf_corpus

Once this lands, tests/fixtures/rf_channel.py can be deleted and Anvith's
S3 tests re-run against the real corpus.
"""
from __future__ import annotations

from pathlib import Path

from zoo.rf import make_rf_file, write_wav_pair

OUT_DIR = Path(__file__).resolve().parent / "corpus" / "rf"

SCHEMES = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]
SNR_SWEEP = [4, 8, 10, 13, 15, 20]


def build() -> None:
    n = 0
    for sch in SCHEMES:
        for snr in SNR_SWEEP:
            seed = 2000 + n
            iq, truth = make_rf_file(scheme_name=sch, snr_db=snr, seed=seed)
            name = f"{sch}_{snr}dB_{seed}"
            write_wav_pair(iq, truth, OUT_DIR, name)
            n += 1
    print(f"Wrote {n} files to {OUT_DIR}")


if __name__ == "__main__":
    build()