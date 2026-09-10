"""tests/unit/test_s1_detect.py"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.s0_ingest import ingest
from pipeline.s1_detect import (
    compute_psd,
    compute_spectrogram,
    detect,
    detect_bursts,
    estimate_occupied_bw,
    estimate_snr,
)

CORPUS = Path(__file__).resolve().parents[2] / "zoo" / "corpus" / "rf"


def _corpus_files(prefix: str) -> list[Path]:
    files = sorted(CORPUS.glob(f"{prefix}_*dB_*.wav"))
    if not files:
        pytest.skip(f"no {prefix} files in {CORPUS} -- run python -m zoo.build_rf_corpus")
    return files


@pytest.mark.parametrize("prefix", ["bpsk", "qpsk", "8psk", "16qam"])
def test_snr_accurate_for_psk_qam(prefix):
    """The 4 Sep gate: SNR estimate within 1.5 dB of truth. Measured as total
    signal power / total noise power over the full capture, matching how the
    zoo defines truth snr_db in zoo/rf.py's _awgn -- not a peak-PSD-bin-vs-
    floor ratio, which overstates SNR by the processing gain fs/occupied_bw
    (was +7 dB at 8 sps before this was fixed)."""
    for f in _corpus_files(prefix):
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        snr_db, _ = estimate_snr(r.iq, r.fs)
        diff = snr_db - truth["snr_db"]
        assert abs(diff) < 1.5, f"{f.name}: truth={truth['snr_db']} measured={snr_db:.1f} diff={diff:+.1f}"


def test_snr_accurate_for_2fsk_at_every_snr():
    """2fsk now holds to the same 1.5 dB bar at EVERY corpus SNR.

    This used to skip everything above 15 dB, where the percentile-floor
    estimator ran 2 dB low. The moment estimator carries it: measured within
    0.01 dB of truth across the whole sweep.
    """
    for f in _corpus_files("2fsk"):
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        snr_db, _ = estimate_snr(r.iq, r.fs)
        diff = snr_db - truth["snr_db"]
        assert abs(diff) < 1.5, f"{f.name}: truth={truth['snr_db']} measured={snr_db:.1f} diff={diff:+.1f}"


def test_snr_accurate_for_4fsk():
    """WAS A STRICT XFAIL until 10 Sep, and the gap it recorded was worse than
    a wrong number on a stage card.

    Every 4fsk capture in the corpus, true SNR 4 to 20 dB, measured between
    -3.16 and -4.58 dB: the estimate carried no information about the true SNR
    at all, and `adapt_s1` refuses anything below -5.0 dB and marks every
    downstream stage out_of_envelope. The worst cell sat 0.42 dB from refusing
    a capture the pipeline decodes to the exact transmitted bits.

    estimate_snr now takes the larger of the spectral and moment estimates.
    """
    for f in _corpus_files("4fsk"):
        truth = json.loads(f.with_suffix(".json").read_text())
        r = ingest(f)
        snr_db, _ = estimate_snr(r.iq, r.fs)
        diff = snr_db - truth["snr_db"]
        assert abs(diff) < 1.5, f"{f.name}: truth={truth['snr_db']} measured={snr_db:.1f} diff={diff:+.1f}"


def test_no_capture_is_pushed_below_the_refusal_gate():
    """The consequence test, stated in the units that matter.

    adapt_s1 refuses below -5.0 dB. No corpus capture -- every one of which is
    a real signal at 4 dB or better -- may be estimated anywhere near it.
    """
    for prefix in ("bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"):
        for f in _corpus_files(prefix):
            truth = json.loads(f.with_suffix(".json").read_text())
            r = ingest(f)
            snr_db, _ = estimate_snr(r.iq, r.fs)
            assert snr_db > 0.0, (
                f"{f.name}: truth={truth['snr_db']} dB estimated {snr_db:.2f} dB, "
                "which is heading for the -5.0 dB envelope refusal")


def test_moment_estimator_never_overstates_snr():
    """The property that makes taking the max of the two estimators sound.

    S_hat = S*sqrt(2 - ka) with ka >= 1 for every signal, so the moment
    estimator can only understate. Checked against truth on every corpus file
    rather than argued: if this direction ever inverts, the max is unsafe and
    the combination in estimate_snr has to be revisited.
    """
    from pipeline.s1_detect import estimate_snr_moment
    for prefix in ("bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"):
        for f in _corpus_files(prefix):
            truth = json.loads(f.with_suffix(".json").read_text())
            r = ingest(f)
            moment_db, _norm_m4 = estimate_snr_moment(r.iq)
            if moment_db is None:
                continue
            assert moment_db < truth["snr_db"] + 0.5, (
                f"{f.name}: moment estimator returned {moment_db:.2f} dB against "
                f"truth {truth['snr_db']} dB -- it is supposed to understate")


def test_moment_estimator_is_exact_on_a_synthetic_constant_modulus_signal():
    """Ground truth built here, not read from a corpus: a unit-modulus signal
    with a known amount of circular Gaussian noise added."""
    from pipeline.s1_detect import estimate_snr_moment
    rng = np.random.default_rng(20260910)
    n = 200_000
    phase = rng.uniform(-np.pi, np.pi, n)
    signal = np.exp(1j * phase)                      # |s| = 1 exactly, so ka = 1
    for true_snr_db in (0.0, 5.0, 10.0, 20.0, 30.0):
        npow = 10 ** (-true_snr_db / 10.0)
        noise = (rng.normal(0, np.sqrt(npow / 2), n)
                 + 1j * rng.normal(0, np.sqrt(npow / 2), n))
        est, _ = estimate_snr_moment(signal + noise)
        assert est is not None
        assert abs(est - true_snr_db) < 0.3, (
            f"true {true_snr_db} dB, moment estimate {est:.2f} dB")


def test_moment_estimator_declines_on_pure_noise():
    """Pure circular Gaussian noise has ka_eff = 2 exactly, so 2*M2^2 - M4
    collapses to zero and there is no constant-modulus decomposition. Returning
    None is the honest answer; a number here would be invented."""
    from pipeline.s1_detect import estimate_snr_moment
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, 100_000) + 1j * rng.normal(0, 1, 100_000)
    est, norm_m4 = estimate_snr_moment(noise)
    assert est is None
    assert abs(norm_m4 - 2.0) < 0.05


def test_compute_psd_shape_and_symmetry():
    rng = np.random.default_rng(0)
    iq = rng.normal(size=4096) + 1j * rng.normal(size=4096)
    freqs, psd_db = compute_psd(iq, fs=200_000.0)
    assert freqs.shape == psd_db.shape
    assert np.all(np.diff(freqs) > 0), "fftshift should leave freqs monotonic"
    assert np.isfinite(psd_db).all()


@pytest.mark.parametrize("prefix", ["bpsk", "qpsk", "8psk", "16qam"])
def test_occupied_bw_is_a_reasonable_fraction_of_fs(prefix):
    """Regression guard for the noise-floor-subtraction fix: the naive
    cumulative-power method reported 89-99% of fs for every modulation
    including PSK (clearly wrong for an RRC-shaped signal at sps=4,
    beta=0.35, whose theoretical occupied fraction is ~34%). Bounded
    loosely (15-55%) rather than pinned tight, since this is a 99%-power
    threshold on a real (not brick-wall) filter, not an exact match to
    the theoretical (1+beta)/sps figure."""
    f = _corpus_files(prefix)[len(_corpus_files(prefix)) // 2]
    r = ingest(f)
    bw = estimate_occupied_bw(r.iq, r.fs)
    frac = bw / r.fs
    assert 0.15 < frac < 0.55, f"{f.name}: occupied_bw/fs={frac:.2f}, expected ~0.34"


def test_compute_spectrogram_shape():
    f = _corpus_files("qpsk")[0]
    r = ingest(f)
    freqs, times, spec_db = compute_spectrogram(r.iq, r.fs)
    assert spec_db.shape == (freqs.size, times.size)
    assert np.isfinite(spec_db).all()
    assert np.all(np.diff(freqs) > 0)
    assert np.all(np.diff(times) > 0)


def test_compute_spectrogram_locates_signal_in_time():
    """A short capture is one nonstop burst, so every time slice should show
    power well above a pure-noise slice would -- this is a weak sanity check
    (no on/off corpus exists yet to test burst localisation in time), just
    confirming the array carries real structure, not a constant."""
    f = _corpus_files("qpsk")[0]
    r = ingest(f)
    freqs, times, spec_db = compute_spectrogram(r.iq, r.fs)
    assert spec_db.max() - np.median(spec_db) > 3.0


def test_compute_spectrogram_short_input_does_not_crash():
    rng = np.random.default_rng(1)
    iq = rng.normal(size=50) + 1j * rng.normal(size=50)
    freqs, times, spec_db = compute_spectrogram(iq, fs=200_000.0)
    assert spec_db.size > 0


def test_detect_ok_result_carries_spectrogram():
    f = _corpus_files("qpsk")[0]
    r = ingest(f)
    result = detect(r.iq, r.fs)
    assert result.spec_freqs is not None
    assert result.spec_times is not None
    assert result.spec_db is not None
    assert result.spec_db.shape == (result.spec_freqs.size, result.spec_times.size)


def test_detect_fails_cleanly_on_empty_input():
    result = detect(np.array([]), fs=200_000.0)
    assert result.status == "failed"
    assert result.reason is not None
    assert result.snr_db is None


def test_detect_ok_on_real_capture():
    f = _corpus_files("qpsk")[0]
    r = ingest(f)
    result = detect(r.iq, r.fs)
    assert result.status == "ok"
    assert result.snr_db is not None
    assert result.occupied_bw_hz is not None and result.occupied_bw_hz > 0
    assert result.psd_freqs is not None and result.psd_db is not None


def test_detect_bursts_no_crash_on_continuous_signal():
    """The RF corpus has no on/off gaps -- every file is one continuous
    transmission, so there's no ground truth to check burst boundaries
    against yet. This only pins that the detector doesn't crash or hang on
    real data; burst-boundary accuracy is untested."""
    f = _corpus_files("qpsk")[0]
    r = ingest(f)
    bursts = detect_bursts(r.iq, r.fs)
    assert isinstance(bursts, list)
    for start, end in bursts:
        assert 0 <= start < end <= len(r.iq)


def test_detect_bursts_short_input_returns_empty():
    assert detect_bursts(np.zeros(10, dtype=complex), fs=200_000.0) == []
