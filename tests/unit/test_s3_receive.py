"""Unit tests for Stage 3. Owner: Anvith.

Each test builds its own short signal rather than reading a corpus, so the suite
runs in seconds and does not depend on a fixture that is due to be deleted the
day Dheeraj's zoo lands.

Several of these exist because the bug they pin was found the hard way, and the
docstring says which - a test whose reason for existing is written down does not
get deleted by whoever is tidying up on 8 September.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s3_receive import (bits_to_symbol_indices, cma_equalise,  # noqa: E402
                                 cumulants, dispersion_constants,
                                 estimate_rolloff, estimated_ber, evm_percent,
                                 gardner_sync, label_bit_matrix, llr_to_bits,
                                 lock_metric, magnitude_dispersion,
                                 matched_filter, max_log_llr, mma_equalise,
                                 phase_rotation_candidates, rrc_taps, scheme,
                                 symbol_indices_to_bits)
from pipeline.s3_receive.carrier import carrier_settle_index, costas_loop  # noqa: E402
from registry import MODULATIONS  # noqa: E402
from tests.fixtures.rf_channel import ChannelSpec, through_channel  # noqa: E402

SPS = 4
BETA = 0.35
LINEAR = ["bpsk", "qpsk", "8psk", "16qam"]


def make(name: str, n_bits: int = 60000, snr_db: float = 25.0, **kw) -> np.ndarray:
    bits = np.random.default_rng(kw.pop("seed", 7)).integers(
        0, 2, n_bits).astype(np.uint8)
    spec = ChannelSpec(scheme=name, sps=kw.pop("sps", SPS), snr_db=snr_db, **kw)
    return through_channel(bits, spec)[0]


# --- filters ---------------------------------------------------------------

def test_rrc_is_unit_energy_and_symmetric():
    h = rrc_taps(BETA, SPS, span=10)
    assert h.size % 2 == 1
    assert np.isclose(np.sum(h**2), 1.0)
    assert np.allclose(h, h[::-1])


def test_rrc_rejects_out_of_range_beta():
    for bad in (0.0, 1.5):
        with pytest.raises(ValueError):
            rrc_taps(bad, SPS)


def test_matched_filter_preserves_length_and_alignment():
    x = make("qpsk", 8000)
    y = matched_filter(x, BETA, SPS)
    assert y.size == x.size
    c = np.abs(np.correlate(y[100:1100], x[100:1100], mode="same"))
    assert int(np.argmax(c)) == c.size // 2


@pytest.mark.parametrize("beta", [0.15, 0.2, 0.35, 0.5, 0.7])
def test_rolloff_estimated_blind(beta):
    """Blind roll-off from a joint amplitude-and-shape fit to the raised cosine.

    Two earlier estimators are described in `filters.estimate_rolloff`; both
    were biased and one of them shipped with a 0.15 tolerance written around
    its error. This one is accurate to about 0.01 from 0.15 to 0.70, so the
    tolerance is 0.03 and it means something again.
    """
    x = make("qpsk", 120000, snr_db=20.0, beta=beta)
    est = estimate_rolloff(x, fs=1.0, symbol_rate=1.0 / SPS)
    assert abs(est - beta) < 0.03, f"estimated {est:.3f} for a true {beta}"


def test_estimated_ber_is_flagged_invalid_when_not_locked():
    """The number is optimistic when the receiver has not locked, so it travels
    with a flag saying whether to believe it. 8-PSK below its threshold is the
    case that showed this: 0.003 reported against 0.035 actual."""
    ok = MODULATIONS["qpsk"].receive(
        make("qpsk", 120000, snr_db=20.0), {"fs": 200000.0, "symbol_rate": 50000.0})
    assert ok.status == "ok"
    assert ok.values["estimated_output_ber_valid"] is True

    poor = MODULATIONS["8psk"].receive(
        make("8psk", 120000, snr_db=4.0), {"fs": 200000.0, "symbol_rate": 50000.0})
    if poor.status == "ok":
        pytest.skip("8-PSK still locked at 4 dB on this build")
    assert poor.values["estimated_output_ber_valid"] is False


# --- bit mapping (a cross-stream contract) ---------------------------------

@pytest.mark.parametrize("order", [2, 4, 8, 16])
def test_bit_mapping_round_trips(order):
    b = np.random.default_rng(0).integers(0, 2, 4000).astype(np.uint8)
    back = symbol_indices_to_bits(bits_to_symbol_indices(b, order), order)
    n = min(b.size, back.size)
    assert np.array_equal(b[:n], back[:n])


@pytest.mark.parametrize("name", LINEAR)
def test_constellation_labelling_is_gray(name):
    """Adjacent points must differ in exactly one bit. For QAM this only holds
    if each AXIS is Gray-coded separately - a single Gray code over the raster
    index gives a labelling that looks plausible and is not Gray at all."""
    sch = scheme(name)
    pts, mat = sch.points, label_bit_matrix(sch.order)
    for i in range(sch.order):
        d = np.abs(pts - pts[i])
        d[i] = np.inf
        for j in np.flatnonzero(d <= d.min() + 1e-9):
            diff = int(np.sum(mat[i] ^ mat[j]))
            assert diff == 1, f"{name}: points {i},{j} differ in {diff} bits"


# --- timing ----------------------------------------------------------------

def test_gardner_requires_two_samples_per_symbol():
    with pytest.raises(ValueError):
        gardner_sync(make("qpsk", 4000), sps=1.5)


def test_gardner_converges_from_a_fractional_offset():
    x = make("qpsk", 60000, timing_offset_sym=0.4)
    r = gardner_sync(matched_filter(x, BETA, SPS), SPS)
    assert r.locked and r.converged_at is not None and r.converged_at < 2000


def test_gardner_locks_on_the_open_eye_not_the_zero_crossing():
    """The sign-convention regression. Both points are equilibria of the
    detector; only one has an open eye, and a mis-signed loop settles just as
    cleanly onto the wrong one."""
    x = make("qpsk", 60000, timing_offset_sym=0.4)
    y = matched_filter(x, BETA, SPS)
    loop = magnitude_dispersion(gardner_sync(y, SPS).symbols[-2000:])
    best = min(magnitude_dispersion(y[off::SPS][200:]) for off in range(SPS))
    assert loop < best + 0.02


@pytest.mark.parametrize("sps", [4, 8])
def test_gardner_tracks_the_same_rate_at_4_and_8_sps(sps):
    """Loop gain is relative to sps. Expressed in absolute samples it halves at
    8 sps, which showed up as a 0.13 % rate bias and a constellation that
    decayed over a long record while looking clean at the start."""
    x = make("qpsk", 60000, sps=sps, timing_offset_sym=0.3)
    r = gardner_sync(matched_filter(x, BETA, sps), sps)
    assert abs(float(np.mean(r.sps_track)) - sps) < 0.01 * sps


# --- carrier ---------------------------------------------------------------

@pytest.mark.parametrize("name", LINEAR)
def test_costas_locks_and_recovers_the_offset(name):
    cfo = 0.002
    sch = scheme(name)
    x = make(name, 120000, snr_db=28.0, cfo_norm=cfo)
    r = gardner_sync(matched_filter(x, BETA, SPS), SPS)
    eq = (mma_equalise(r.symbols[500:], sch.points) if sch.family == "qam"
          else cma_equalise(r.symbols[500:]))
    c = costas_loop(eq.symbols[1200:], sch,
                    lock_threshold=0.55 if sch.family == "qam" else 0.60)
    assert c.locked, f"{name} lock {c.lock:.3f}"
    assert abs(c.freq[-1] - 2 * np.pi * cfo * SPS) < 0.02


def test_lock_metric_separates_locked_from_spinning():
    sch = scheme("qpsk")
    rng = np.random.default_rng(1)
    clean = sch.points[rng.integers(0, 4, 4000)]
    spinning = clean * np.exp(2j * np.pi * 0.13 * np.arange(clean.size))
    assert lock_metric(clean, sch) > 0.98
    assert lock_metric(spinning, sch) < 0.10


def test_qam_lock_metric_uses_the_outer_ring():
    """The plain fourth-power metric moved only between 0.24 and 0.33 across
    10-20 dB on 16-QAM, and 0.24 was a stream decoding at 49 % BER. Keeping the
    top quartile by magnitude - the corner points, which sit at exact multiples
    of 45 degrees - restores the separation."""
    sch = scheme("16qam")
    rng = np.random.default_rng(2)
    clean = sch.points[rng.integers(0, 16, 8000)]
    spinning = clean * np.exp(2j * np.pi * 0.07 * np.arange(clean.size))
    assert lock_metric(clean, sch) > 0.9
    assert lock_metric(spinning, sch) < 0.2


def test_rotation_candidates_match_the_symmetry_not_the_order():
    """16-QAM has sixteen points and only four rotational ambiguities. Emitting
    sixteen would hand S4 twelve hypotheses that cannot be right."""
    rng = np.random.default_rng(3)
    for name, expected in (("qpsk", 4), ("8psk", 8), ("16qam", 4), ("bpsk", 2)):
        sch = scheme(name)
        s = sch.points[rng.integers(0, sch.order, 400)]
        assert len(phase_rotation_candidates(s, sch)) == expected


def test_carrier_settle_index_finds_the_acquisition_prefix():
    sch = scheme("qpsk")
    rng = np.random.default_rng(4)
    sym = sch.points[rng.integers(0, 4, 6000)]
    spun = sym.copy()
    spun[:1500] *= np.exp(2j * np.pi * 0.05 * np.arange(1500))
    assert carrier_settle_index(spun, sch, 0.6) >= 1024


# --- equalisers ------------------------------------------------------------

def test_cma_reduces_modulus_error_on_a_multipath_channel():
    x = make("qpsk", 80000, snr_db=30.0)
    r = gardner_sync(matched_filter(x, BETA, SPS), SPS)
    sym = r.symbols[500:]
    echoed = np.convolve(sym, np.array([1.0, 0.0, 0.35 + 0.15j]), mode="same")
    before = magnitude_dispersion(echoed[-2000:])
    after = magnitude_dispersion(cma_equalise(echoed).symbols[-2000:])
    assert after < before


def test_dispersion_constants_differ_for_qam():
    """R2 is the same for every PSK because they share one modulus; QAM does
    not, which is the whole reason MMA exists."""
    r2_psk, _ = dispersion_constants(scheme("qpsk").points)
    r2_qam, r2a_qam = dispersion_constants(scheme("16qam").points)
    assert np.isclose(r2_psk, 1.0)
    assert not np.isclose(r2_qam, r2a_qam)


def test_mma_beats_cma_on_qam():
    """CMA drives QAM towards a single modulus it does not have, so it settles
    on a constellation that is not the transmitted one - confidently, and
    without raising."""
    sch = scheme("16qam")
    rng = np.random.default_rng(5)
    sym = sch.points[rng.integers(0, 16, 20000)]
    echoed = np.convolve(sym, np.array([1.0, 0.0, 0.25 + 0.1j]), mode="same")
    mma = mma_equalise(echoed, sch.points).symbols[-4000:]
    cma = cma_equalise(echoed).symbols[-4000:]
    assert evm_percent(mma, sch) < evm_percent(cma, sch)


# --- soft demapping --------------------------------------------------------

@pytest.mark.parametrize("name", LINEAR)
def test_max_log_llr_sign_matches_the_convention(name):
    """Positive LLR means bit 0. Checked on the noiseless constellation, where
    the answer is not a matter of degree."""
    sch = scheme(name)
    llrs = max_log_llr(sch.points, sch.points, sigma2=0.01)
    assert np.array_equal(llr_to_bits(llrs), label_bit_matrix(sch.order).ravel())


def test_llr_magnitude_grows_as_noise_falls():
    sch = scheme("qpsk")
    rng = np.random.default_rng(6)
    s = sch.points[rng.integers(0, 4, 4000)]
    quiet = np.mean(np.abs(max_log_llr(s, sch.points, sigma2=0.01)))
    noisy = np.mean(np.abs(max_log_llr(s, sch.points, sigma2=0.30)))
    assert quiet > noisy


def test_estimated_ber_is_monotone_in_confidence():
    assert estimated_ber(np.full(1000, 8.0)) < estimated_ber(np.full(1000, 1.0))
    assert 0.4 < estimated_ber(np.zeros(1000)) <= 0.5


def test_noncoherent_llr_rejects_wrong_shape():
    from pipeline.s3_receive import noncoherent_llr
    with pytest.raises(ValueError):
        noncoherent_llr(np.zeros((10, 3)), order=2)


# --- cumulants -------------------------------------------------------------

@pytest.mark.parametrize("name", LINEAR)
def test_theoretical_cumulants_match_a_noiseless_measurement(name):
    sch = scheme(name)
    theory = MODULATIONS[name].theoretical_cumulants()
    drawn = sch.points[np.random.default_rng(5).integers(0, sch.order, 60000)]
    meas = cumulants(drawn)
    assert np.isclose(abs(theory["C21"]), 1.0, atol=1e-9)
    for key in ("C40", "C42"):
        assert abs(theory[key] - meas[key]) < 0.08


# --- plug-ins --------------------------------------------------------------

def test_registry_carries_six_modulations():
    assert {"bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"} <= set(MODULATIONS)


def test_plugin_reports_failure_instead_of_raising():
    r = MODULATIONS["qpsk"].receive(np.zeros(10, dtype=complex),
                                    {"fs": 1.0, "symbol_rate": 0.25})
    assert r.status == "failed" and r.reason


def test_plugin_rejects_an_impossible_symbol_rate():
    r = MODULATIONS["qpsk"].receive(make("qpsk", 20000),
                                    {"fs": 1.0, "symbol_rate": 0.8})
    assert r.status == "failed" and "samples/symbol" in r.reason


def test_missing_s2_estimate_is_a_clean_failure_not_a_crash():
    r = MODULATIONS["qpsk"].receive(make("qpsk", 8000), {"fs": 1.0})
    assert r.status == "failed" and "symbol_rate" in r.reason


def test_s3_runs_on_blind_estimates_with_no_labels_in_the_path():
    """The 1 September gate, kept alive after the port.

    Every other test here hands S3 the symbol rate the fixture used, which is a
    label. This one estimates it from the signal - squared-magnitude spectrum
    for the rate, M-th power line search for the offset - and checks the chain
    still locks. Without it, "the receiver stopped reading the answers" would be
    a claim resting on a test that no longer exercised it.
    """
    from tests.fixtures.local_s2 import estimate_blind

    fs = 200000.0
    bits = np.random.default_rng(9).integers(0, 2, 120000).astype(np.uint8)
    spec = ChannelSpec(scheme="qpsk", sps=4, snr_db=16.0, fs=fs,
                       cfo_norm=0.0015, timing_offset_sym=0.42, seed=11)
    x, _ = through_channel(bits, spec)

    s2 = estimate_blind(x, fs)
    assert abs(s2.symbol_rate - spec.symbol_rate) / spec.symbol_rate < 0.01

    r = MODULATIONS["qpsk"].receive(x, s2.as_params())   # blind params only
    assert r.status == "ok" and r.llrs.size > 1000


def test_no_label_lookup_anywhere_in_the_stage():
    """`grep -ri truth pipeline/s3_receive/` returns nothing. Run as code so it
    is checked on every run rather than typed at a standup."""
    root = Path(__file__).resolve().parents[2] / "pipeline" / "s3_receive"
    hits = [f"{p.name}:{i}" for p in sorted(root.glob("*.py"))
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "truth" in line.lower()]
    assert hits == [], f"label references in S3: {hits}"


def test_stage_result_dict_form_drops_bulk_arrays():
    """The report travels over a socket and into SQLite. A 200 000-element
    float array inside it is one that cannot be logged or cached."""
    r = MODULATIONS["qpsk"].receive(
        make("qpsk", 120000), {"fs": 200000.0, "symbol_rate": 50000.0})
    d = r.as_stage_result()
    assert not any(isinstance(v, np.ndarray) for v in d["values"].values())
    assert d["status"] in ("ok", "low_confidence")


# --- degenerate and adversarial input ---------------------------------------
#
# The 4 Sep row is "clean give-up: return low_confidence, never garbage" and the
# 8 Sep row is the adversarial set. These are the cheap half of both, written
# early because every one of them is an input a judge can produce in five
# seconds, and because "it raised an exception" is the one failure mode with no
# good explanation.

ADVERSARIAL = {
    "pure noise": lambda rng, n: (rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n)),
    "DC only": lambda rng, n: np.full(n, 1.0 + 0j),
    "all zeros": lambda rng, n: np.zeros(n, dtype=complex),
    "clipped square": lambda rng, n: np.sign(rng.normal(0, 1, n)).astype(complex),
    "single impulse": lambda rng, n: np.eye(1, n, 0, dtype=complex).ravel(),
    "two overlapping tones": lambda rng, n: (
        np.exp(2j * np.pi * 0.01 * np.arange(n))
        + np.exp(2j * np.pi * 0.13 * np.arange(n))),
}


@pytest.mark.parametrize("case", list(ADVERSARIAL))
@pytest.mark.parametrize("mod", ["qpsk", "16qam", "2fsk"])
def test_adversarial_input_returns_a_status_never_an_exception(case, mod):
    rng = np.random.default_rng(99)
    x = ADVERSARIAL[case](rng, 120000)
    res = MODULATIONS[mod].receive(x, {"fs": 200000.0, "symbol_rate": 50000.0})
    assert res.status in ("ok", "low_confidence", "failed", "out_of_envelope")
    if res.status == "failed":
        assert res.reason, f"{mod}/{case}: failed without a reason"
    # whatever it decides, the LLR array must still be usable by S4
    out = MODULATIONS[mod].demodulate(x, {"fs": 200000.0, "symbol_rate": 50000.0})
    assert isinstance(out, np.ndarray) and out.dtype == np.float64
    assert np.all(np.isfinite(out))


@pytest.mark.parametrize("mod", ["qpsk", "16qam", "2fsk", "4fsk"])
def test_wrong_symbol_rate_fails_fast(mod):
    """S2 will be wrong sometimes, and the 4 Sep hypothesis loop will try rates
    that do not fit on purpose. Both must come back as a status, QUICKLY.

    The timing assertion is the point. Before the cap in `rrc_taps` and the
    length check in `_run`, a symbol rate of 1 Hz against 200 kHz asked for a
    two-million-tap matched filter: this test took **257 seconds per
    modulation** and returned the correct status at the end of it. A stage that
    answers correctly after four minutes has not answered - it has become the
    denial of service that risk #5 describes, reachable from a single wrong
    number in an upstream estimate."""
    import time as _time

    x = make("qpsk", 60000, snr_db=20.0)
    for rate in (1.0, 3.0, 199999.0):
        t0 = _time.perf_counter()
        res = MODULATIONS[mod].receive(x, {"fs": 200000.0, "symbol_rate": rate})
        elapsed = _time.perf_counter() - t0
        assert res.status in ("ok", "low_confidence", "failed")
        assert elapsed < 5.0, (
            f"{mod} took {elapsed:.1f}s to reject {rate} Hz")


def test_rrc_taps_refuses_an_implausible_rate():
    from pipeline.s3_receive.filters import MAX_TAPS

    with pytest.raises(ValueError, match="cap"):
        rrc_taps(0.35, sps=MAX_TAPS, span=10)


def test_pure_noise_is_not_reported_as_a_confident_lock():
    """The false-positive direction. Noise must not come back as `ok`, because
    everything downstream reads that flag before it reads anything else."""
    rng = np.random.default_rng(7)
    x = rng.normal(0, 1, 200000) + 1j * rng.normal(0, 1, 200000)
    for mod in ("qpsk", "8psk", "16qam"):
        res = MODULATIONS[mod].receive(x, {"fs": 200000.0, "symbol_rate": 50000.0})
        assert res.status != "ok", f"{mod} claims a lock on pure noise"


# --- the plotting harness ---------------------------------------------------

def test_plot_harness_writes_every_chart(tmp_path):
    """plots.py had no coverage at all: it is only called from a report script,
    so a break in it would surface as a failed report at the worst moment
    rather than as a red test."""
    from pipeline.s3_receive.plots import (chain_summary, cma_trace,
                                           constellation_plot, eye_diagram,
                                           timing_trace)

    sch = scheme("qpsk")
    x = make("qpsk", 60000, snr_db=20.0, timing_offset_sym=0.3)
    y = matched_filter(x, BETA, SPS)
    g = gardner_sync(y, SPS)

    made = [
        eye_diagram(y, SPS, tmp_path / "eye.png",
                    align_sample=float(np.median(g.positions[500:] % SPS))),
        constellation_plot(g.symbols, tmp_path / "const.png",
                           reference=sch.points),
        timing_trace(g.error, tmp_path / "timing.png",
                     converged_at=g.converged_at,
                     reference_error=np.zeros(g.error.size)),
        cma_trace(cma_equalise(g.symbols[500:]).error, tmp_path / "cma.png"),
        chain_summary([{"modulation": "qpsk", "snr_db": 20.0,
                        "evm_percent": 5.0, "carrier_lock": 0.98}],
                      tmp_path / "summary.png"),
    ]
    for path in made:
        assert Path(path).exists() and Path(path).stat().st_size > 1000


def test_eye_diagram_refuses_a_record_too_short_to_draw():
    from pipeline.s3_receive.plots import eye_diagram
    with pytest.raises(ValueError):
        eye_diagram(np.zeros(20, dtype=complex), SPS, "unused.png")
