"""models/build_holdout.py

Held-out evaluation set for the 3 Sep gate: SNRs the model has never
trained on. {2.5, 7.5, 12.5} dB test interpolation (between the training
grid's {0,5,10,15,20}); -3dB tests extrapolation below the whole training
range. Validating on the training SNR grid is explicitly the mistake that
makes a reported number meaningless (per the plan) -- this file exists so
that mistake isn't possible by construction: HOLDOUT_SNRS_DB and
build_dataset.TRAIN_SNRS_DB share no values.

Same generation path as build_dataset.py (in-memory via
zoo.rf.through_channel, independent bits+seed per window), smaller N since
this is for evaluation, not training.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from pathlib import Path

from models.build_dataset import SEED_BASE, build

HOLDOUT_SNRS_DB = [-3, 2.5, 7.5, 12.5]
OUT_CSV = Path(__file__).resolve().parent / "dataset_holdout.csv"

assert not (set(HOLDOUT_SNRS_DB) & {0, 5, 10, 15, 20}), \
    "holdout SNRs must not overlap the training grid"


def build_holdout(n_per_class_per_snr: int = 300,
                   seed_base: int = SEED_BASE + 1_000_000,
                   out_csv: Path = OUT_CSV) -> Path:
    return build(n_per_class_per_snr=n_per_class_per_snr, seed_base=seed_base,
                 out_csv=out_csv, snrs_db=HOLDOUT_SNRS_DB)


if __name__ == "__main__":
    build_holdout()
