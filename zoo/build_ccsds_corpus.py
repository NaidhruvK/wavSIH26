"""zoo/build_ccsds_corpus.py

Generates the real-standard-order concatenated CCSDS corpus. Run:
    python -m zoo.build_ccsds_corpus

5 Sep, requested by a teammate verifying S4-S6 concatenated recovery: the
zoo corpus had conv-only and RS-only streams but no concatenated profile,
so their chain was tested only against tests/fixtures/local_zoo's
bit-level-interleaved, wrong-order stand-in (that file's own docstring
already states the deviation). zoo/ccsds.py implements the real order --
RS outer -> BYTE-level interleave (depth I) -> randomise -> convolutional
inner -- verified by a clean-channel round trip in
tests/unit/test_ccsds.py before any of these files existed.

Writes to zoo/corpus/ccsds/, NOT zoo/corpus/rf/: every existing corpus-
wide test globs zoo/corpus/rf/*dB_*.wav and regenerates ground truth via
zoo.bits_only.make_stream's single-code schema (this project's own
reports/envelope_study.py included) -- a concatenated file dropped in
there would silently corrupt every one of those, without any of them
having been wrong to assume what they assumed about that directory.

One file per (scheme, SNR, depth) combination -- schemes and SNRs chosen
to span the declared envelope without an hour of runtime for something
nobody sweeps the way the main RF corpus is swept; interleave depths
{1, 4, 8} span "no interleaving" through the deepest value the real
standard specifies, to give S4-S6 something to search over.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from pathlib import Path

from zoo.ccsds import make_ccsds_rf_file, write_ccsds_wav_pair

OUT_DIR = Path(__file__).resolve().parent / "corpus" / "ccsds"

PAYLOAD_TEXT = (
    "RAAYA SIH26147 CCSDS TEST PAYLOAD. Reed-Solomon outer code, byte-level "
    "interleaving at the real CCSDS symbol depth, the pseudo-randomiser "
    "applied before the convolutional inner code -- the real 131.0-B "
    "transmit order, not a bit-level stand-in. If you can read this "
    "sentence after decoding, every layer of the concatenated chain came "
    "off in the right order."
)

CASES = [
    # (scheme, sps, snr_db, depth, seed)
    ("qpsk", 4, 20.0, 1, 9001),
    ("qpsk", 4, 20.0, 4, 9002),
    ("qpsk", 4, 15.0, 4, 9003),
    ("qpsk", 4, 10.0, 4, 9004),
    ("8psk", 4, 20.0, 4, 9005),
    ("16qam", 4, 20.0, 4, 9006),
    ("bpsk", 4, 15.0, 8, 9007),
    ("qpsk", 4, 20.0, 8, 9008),
]


def build() -> None:
    n = 0
    for scheme, sps, snr_db, depth, seed in CASES:
        iq, payload, truth = make_ccsds_rf_file(
            scheme_name=scheme, n_blocks=32, depth=depth, sps=sps,
            snr_db=snr_db, payload_text=PAYLOAD_TEXT, seed=seed,
        )
        name = f"ccsds_{scheme}_{int(snr_db)}dB_depth{depth}_{seed}"
        write_ccsds_wav_pair(iq, payload, truth, OUT_DIR, name)
        n += 1
        print(f"{name}: {iq.size} IQ samples, {truth.payload_n_bytes} payload bytes, "
              f"depth={depth}, rs={truth.rs}")
    print(f"wrote {n} files to {OUT_DIR}")


if __name__ == "__main__":
    build()
