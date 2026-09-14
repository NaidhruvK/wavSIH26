"""What the samples say about the sampling rate: aliasing and fractional bandwidth.

    python reports/sampling_rate_study.py

Prints the table reports/sampling_rate.md quotes.

It began as the calibration run for an edge-power aliasing detector and became
the evidence for NOT shipping one: the edge-power populations of correctly and
under-sampled captures overlap completely (see the summary it prints).

Correctly sampled captures are RF-zoo waveforms at several sps and roll-offs.
Aliased captures are the same waveforms decimated WITHOUT an anti-alias filter,
which is what an under-sampled capture physically is. The final arm relabels a
capture's fs by 2x and shows every dimensionless number is unchanged - the
demonstration that the declared fs itself is not observable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.s1_detect import (check_sampling_rate, compute_psd,  # noqa: E402
                                estimate_noise_floor)
from zoo.rf import through_channel  # noqa: E402

FS = 200_000.0


def capture(scheme, sps, beta, snr, cfo=0.0, seed=0, n_bits=40_000):
    bits = np.random.default_rng(seed).integers(0, 2, n_bits, dtype=np.uint8)
    iq, _ = through_channel(bits, scheme, sps, beta, snr, cfo, 0.0, 0.0, seed)
    return iq


def _edge_power(iq, fs, edge_fraction=0.05):
    """The rejected statistic, kept here so the negative result is reproducible."""
    freqs, psd_db = compute_psd(iq, fs)
    lin = 10 ** (psd_db / 10.0)
    ex = np.clip(lin - 10 ** (estimate_noise_floor(psd_db) / 10.0), 0.0, None)
    tot = ex.sum()
    if tot <= 0:
        return 0.0
    return float(ex[np.abs(freqs / fs) > 0.5 - edge_fraction].sum() / tot)


def main() -> int:
    good, bad = [], []
    print("%-44s occ     ovs    edge(rejected)" % "case")

    def row(label, iq, fs, bucket):
        r = check_sampling_rate(iq, fs)
        e = _edge_power(iq, fs)
        bucket.append(e)
        print("%-44s %-7s %-6s %.5f" % (label, r["occupied_fraction"], r["oversampling"], e))

    print("-- correctly sampled --")
    for scheme in ("bpsk", "qpsk", "8psk", "16qam"):
        for sps, beta in ((2, 0.35), (4, 0.35), (8, 0.35), (4, 0.2), (4, 0.5)):
            for snr in (5.0, 20.0):
                row("%s sps=%d beta=%.2f snr=%.0f" % (scheme, sps, beta, snr),
                    capture(scheme, sps, beta, snr), FS, good)
    for cfo in (0.1, 0.2):
        row("qpsk sps=4 cfo=%.1f*fs" % cfo, capture("qpsk", 4, 0.35, 20.0, cfo=cfo), FS, good)

    print("-- under-sampled (decimated without anti-alias filter) --")
    for scheme in ("bpsk", "qpsk", "16qam"):
        for sps, dec in ((8, 6), (8, 7), (4, 3), (8, 5)):
            row("%s sps=%d decimated %d -> eff sps %.2f" % (scheme, sps, dec, sps / dec),
                capture(scheme, sps, 0.35, 20.0)[::dec], FS / dec, bad)

    print("-- fs relabel: same samples, fs doubled --")
    iq = capture("qpsk", 4, 0.35, 20.0)
    a, b = check_sampling_rate(iq, FS), check_sampling_rate(iq, 2 * FS)
    print("  fs=%.0f  %s" % (FS, a))
    print("  fs=%.0f  %s" % (2 * FS, b))
    print("  every field identical: %s" % (a == b))

    print("\n-- summary: the rejected edge-power statistic --")
    print("  correctly sampled (%d): %.5f .. %.5f" % (len(good), min(good), max(good)))
    print("  under-sampled     (%d): %.5f .. %.5f" % (len(bad), min(bad), max(bad)))
    overlap = min(bad) <= max(good)
    print("  populations overlap: %s -> no threshold separates them" % overlap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
