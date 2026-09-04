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
N_REPS = 7   # 6 schemes x 6 SNRs x 7 reps = 252 files, toward the 4 Sep 250-file target

# rep 0 keeps the original seed formula (2000+n) so the first 36 files this
# produces are byte-identical to what's already committed -- verified by
# hash before extending this function, not assumed. Other streams glob
# zoo/corpus/rf/*.wav rather than hardcoding filenames, but nothing about
# that guarantee should be risked by renumbering files that already exist.


def build() -> None:
    n = 0
    written = 0
    for rep in range(N_REPS):
        for sch in SCHEMES:
            for snr in SNR_SWEEP:
                seed = 2000 + n if rep == 0 else 2000 + rep * 1000 + n
                iq, truth = make_rf_file(scheme_name=sch, snr_db=snr, seed=seed)
                name = f"{sch}_{snr}dB_{seed}"
                write_wav_pair(iq, truth, OUT_DIR, name)
                n += 1
                written += 1
        n = 0   # reset per-rep counter so rep 0's seeds match the original exactly
    print(f"Wrote {written} files to {OUT_DIR}")


if __name__ == "__main__":
    build()