"""models/build_dataset.py

Generates the labelled training set for the 6-class modulation classifier
(2 Sep column): >=2000 windows per class, stratified across the SNR grid
{0,5,10,15,20} dB, features + label written to a single CSV -- not
thousands of individual corpus files, since a window is 4096 samples of
feature input, not a corpus artifact anyone inspects by hand.

Windows are synthesised directly via zoo.rf.through_channel at sps=8 (the
plan's fixed samples/symbol for classifier input), one fresh random bit
sequence and seed per window -- independent noise AND independent data
per window, not overlapping slices of a few long captures, so 2000
windows really are 2000 independent trials, not a smaller number of
distinct realizations replayed.

fs is nominal (200_000.0, matching the existing RF corpus's convention)
since through_channel has no absolute-time notion -- only sps matters for
the waveform itself; fs only sets the Hz scale S1/S2's frequency-domain
estimators report in.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np

from models.features import FEATURE_NAMES, extract_features
from zoo.rf import through_channel

SCHEMES = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]
TRAIN_SNRS_DB = [0, 5, 10, 15, 20]
SPS = 8
FS = 200_000.0
BETA = 0.35
WINDOW_LEN = 4096
N_SOURCE_BITS = 3000       # generous margin over the ~700 symbols needed
SEED_BASE = 10_000

OUT_CSV = Path(__file__).resolve().parent / "dataset_train.csv"


def make_window(scheme: str, snr_db: float, seed: int, rng: np.random.Generator
                 ) -> np.ndarray:
    bits = rng.integers(0, 2, size=N_SOURCE_BITS, dtype=np.uint8)
    phase = float(rng.uniform(-np.pi, np.pi))
    iq, _n_used = through_channel(
        bits, scheme, sps=SPS, beta=BETA, snr_db=snr_db,
        cfo_norm=0.0, phase_rad=phase, timing_offset_sym=0.0, seed=seed,
    )
    if iq.size < WINDOW_LEN + 256:
        raise ValueError(f"window too short for {scheme}: got {iq.size}, need >={WINDOW_LEN + 256}")
    start = (iq.size - WINDOW_LEN) // 2   # clear of RRC edge transients
    window = iq[start:start + WINDOW_LEN]
    power = np.sqrt(np.mean(np.abs(window) ** 2))
    return window / (power if power > 0 else 1.0)


def build(n_per_class_per_snr: int = 420, seed_base: int = SEED_BASE,
          out_csv: Path = OUT_CSV, snrs_db: list | None = None) -> Path:
    t0 = time.time()
    rows = []
    seed = seed_base
    for scheme in SCHEMES:
        for snr_db in (snrs_db if snrs_db is not None else TRAIN_SNRS_DB):
            rng = np.random.default_rng(seed)
            for _ in range(n_per_class_per_snr):
                seed += 1
                window = make_window(scheme, snr_db, seed, rng)
                fv = extract_features(window, FS)
                rows.append([scheme, snr_db, seed] + fv.values.tolist())

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "snr_db", "seed"] + FEATURE_NAMES)
        w.writerows(rows)

    elapsed = time.time() - t0
    print(f"{len(rows)} windows -> {out_csv} ({elapsed:.1f}s)")
    return out_csv


if __name__ == "__main__":
    build()
