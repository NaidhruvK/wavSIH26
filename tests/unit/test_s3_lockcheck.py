"""Lock-failure detection and the bounded hypothesis retry. Owner: Anvith.

4 Sep, Blocks B, C and D. Every test here pins something that was measured
rather than assumed, and the docstring says which - the numbers in
`lockcheck.py`'s constants came from those measurements and a test that does
not say what it is defending gets deleted by whoever is tidying up on 8 Sep.

The corpus tests are marked `slow` and skipped when `zoo/corpus/rf/` is absent,
so this file still runs on a clone that has not pulled the WAVs.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s3_receive  # noqa: E402,F401  (registers the plug-ins)
from pipeline.s2_estimate import estimate  # noqa: E402
from pipeline.s3_receive.lockcheck import (FAIL, LINE_ABSENT_LIMIT,  # noqa: E402
                                           LINE_PRESENT_LIMIT, PASS, UNKNOWN,
                                           Check, LockReport, carrier_offset,
                                           carrier_alignment, signal_presence,
                                           symbol_rate_line)
from pipeline.s3_receive.result import REQUIRED_VALUES  # noqa: E402
from pipeline.s3_receive.search import (params_from_s2,  # noqa: E402
                                        receive_best)
from registry import MODULATIONS  # noqa: E402
from tests.fixtures import corpus  # noqa: E402
from tests.fixtures.corpus import synth  # noqa: E402

FS = 200_000.0
RS = 50_000.0
ALL_SIX = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]

has_corpus = pytest.mark.skipif(
    not corpus.corpus_files(),
    reason="zoo/corpus/rf/ is not present in this clone")


def noise(n: int = 200000, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n)


# --- the statistics -------------------------------------------------------

@pytest.mark.parametrize("name,fam", [("qpsk", "psk"), ("16qam", "qam"),
                                      ("2fsk", "fsk"), ("4fsk", "fsk")])
def test_symbol_rate_line_finds_the_rate_it_was_sent_at(name, fam):
    x = synth(name, n_bits=120000, snr_db=15.0)[0]
    right = symbol_rate_line(x, FS, RS, fam)
    assert right >= LINE_PRESENT_LIMIT, f"{name}: line only {right:.1f}"
    for wrong in (0.61 * RS, 1.31 * RS, 2.0 * RS):
        assert symbol_rate_line(x, FS, wrong, fam) < LINE_ABSENT_LIMIT, \
            f"{name}: found a line at {wrong:.0f} Hz that is not there"


def test_symbol_rate_line_uses_the_whole_record_not_the_first_fft():
    """The truncation bug. `np.fft.rfft(y, n)` CROPS y to n samples when n is
    smaller - it does not transform all of it - so a long record contributed
    its first 262 144 samples and nothing else, silently.

    Pinned by measuring the thing that regression would break: the noise
    ceiling has to keep falling as the record grows, because that is the
    variance reduction segment averaging buys. With the truncation back, the
    two numbers below are equal to within noise.
    """
    short = max(symbol_rate_line(noise(120000, s), FS, RS, "linear")
                for s in range(6))
    long = max(symbol_rate_line(noise(1_920_000, s), FS, RS, "linear")
               for s in range(6))
    assert long < short * 0.8, (
        f"noise ceiling {long:.2f} on a 1.9M-sample record against "
        f"{short:.2f} on a 120k one - the long record is being truncated")


def test_carrier_offset_reads_zero_on_a_centred_signal_and_finds_a_shift():
    x = synth("qpsk", n_bits=120000, snr_db=20.0)[0]
    assert abs(carrier_offset(x, FS)) < 0.03 * RS

    shift = 0.06 * FS
    moved = x * np.exp(2j * np.pi * (shift / FS) * np.arange(x.size))
    assert abs(carrier_offset(moved, FS) - shift) < 0.05 * abs(shift)


def test_carrier_offset_uses_symmetry_not_a_centroid():
    """CPFSK is the case that separates the two estimators.

    Its spectral sidelobes never reach the noise floor inside the captured
    band, so a power-weighted centroid is dragged toward the middle by a
    pedestal that a correlation ignores. Measured on a 4-FSK file shifted by a
    known 25 kHz: the centroid reads 10.6 kHz, the symmetry estimator 24.95.

    Only the MAGNITUDE is asserted here, and the next test says why.
    """
    x = synth("4fsk", n_bits=120000, snr_db=20.0, sps=4)[0]
    shift = 25_000.0
    moved = x * np.exp(2j * np.pi * (shift / FS) * np.arange(x.size))
    got = carrier_offset(moved, FS)
    assert abs(abs(got) - shift) < 0.1 * shift, \
        f"read {got:.0f} Hz for a {shift:.0f} Hz shift"
    # and the alignment check, which is what actually gates anything, fires
    assert carrier_alignment(moved, FS, RS).verdict == FAIL


def test_carrier_offset_cannot_sign_a_shift_that_wraps_the_band():
    """A stated limitation, pinned so nobody trusts the sign further than it
    goes.

    4-FSK at 4 samples/symbol puts tones at +/-25 and +/-75 kHz in a 200 kHz
    band. Shift that by +25 kHz and the outermost tone wraps to the other edge,
    leaving a tone set that genuinely IS symmetric about -25 kHz. The spectrum
    has two equally good centres and no measurement on it can choose.

    This is why `search.receive_best` treats the measured residual as one more
    candidate to be scored rather than as a correction to apply, and why
    `cfo = 0` is always in the candidate list: when the sign comes back wrong,
    the zero candidate is what recovers the file.
    """
    x = synth("4fsk", n_bits=120000, snr_db=20.0, sps=4)[0]
    moved = x * np.exp(2j * np.pi * (25_000.0 / FS) * np.arange(x.size))
    got = carrier_offset(moved, FS)
    assert got < 0, (
        "the sign came back positive - if the estimator has been made "
        "wrap-aware, that is an improvement, and this test should record the "
        "new behaviour rather than be deleted")


# --- the checks themselves ------------------------------------------------

def test_presence_is_three_valued_and_the_middle_value_is_reachable():
    """One threshold could not answer both "is this noise" and "is this a
    signal". 2-FSK at 1.5 dB over 8 samples/symbol scores about 5.5: above
    every noise draw measured, below what would settle it. The honest verdict
    is neither, and the chain carries on."""
    assert signal_presence(noise(), FS, RS, "linear").verdict == FAIL
    strong = synth("qpsk", n_bits=120000, snr_db=15.0)[0]
    assert signal_presence(strong, FS, RS, "psk").verdict == PASS

    weak = synth("2fsk", n_bits=240000, snr_db=1.5, sps=8)[0]
    c = signal_presence(weak, FS, 25_000.0, "fsk")
    assert c.verdict == UNKNOWN, (
        f"2-FSK at 1.5 dB scored {c.value:.1f}, verdict {c.verdict}")


def test_presence_abstains_rather_than_passing_when_it_cannot_see():
    """A check with no evidence must not return `pass`. A silent pass looks
    like corroboration and is worse than having no check."""
    for bad in (0.0, -1.0, float("nan")):
        assert signal_presence(noise(), FS, bad, "linear").verdict == UNKNOWN
        assert carrier_alignment(noise(), FS, bad).verdict == UNKNOWN


def test_a_report_of_only_unknowns_does_not_claim_a_failure():
    r = LockReport()
    r.add(Check("a", UNKNOWN, "no evidence"))
    assert r.locked and r.reason is None and r.failures == []


def test_lock_report_reason_names_every_failing_check():
    r = LockReport()
    r.add(Check("a", FAIL, "a said no")).add(Check("b", PASS, "b said yes"))
    r.add(Check("c", FAIL, "c said no"))
    assert not r.locked
    assert "a said no" in r.reason and "c said no" in r.reason
    assert r.as_values()["lock_failures"] == ["a", "c"]


# --- the failure this whole day exists for --------------------------------

@pytest.mark.parametrize("name", ["bpsk", "qpsk", "8psk", "16qam"])
def test_a_symmetry_step_per_symbol_is_not_reported_as_a_lock(name):
    """THE regression of 4 September. Do not delete this.

    De-rotating by `Rs / S` advances the constellation exactly one symmetry
    step per symbol, and the S-th power lock metric is invariant under that by
    construction - `(u e^{j2pi/S})^S == u^S`. So the receiver used to report
    `status: ok`, `confidence: 0.985` and `estimated_output_ber: 0.000000` over
    a stream whose real bit error rate was 0.485. It is the exact offset S2
    hands over, on 33 of the 36 corpus files, because its M-th power search
    locks onto the symbol-rate line.

    What must hold: not `ok`, and the estimate must be marked invalid. Whether
    LLRs come out at all is not the point - believing them is.
    """
    sch = MODULATIONS[name]
    symmetry = getattr(sch, "scheme", None)
    s = symmetry.symmetry if symmetry is not None else 2
    x = synth(name, n_bits=120000, snr_db=20.0)[0]

    clean = sch.receive(x, {"fs": FS, "symbol_rate": RS, "cfo_hz": 0.0})
    assert clean.status == "ok", f"{name} does not lock even clean: {clean.reason}"

    bad = sch.receive(x, {"fs": FS, "symbol_rate": RS, "cfo_hz": RS / s})
    assert bad.status != "ok", (
        f"{name} claims a lock at a carrier offset of Rs/{s}, which advances "
        "the constellation one symmetry step per symbol")
    assert bad.values["estimated_output_ber_valid"] is False
    assert "carrier_aligned" in bad.values["lock_failures"]


def test_a_receiver_may_not_claim_ok_while_estimating_its_output_is_junk():
    """Self-consistency, and it was missing.

    The 2-FSK plug-in over an 8-PSK capture (`8psk_8dB_2013`) found two tones
    at a mean margin of 0.319 - over its own 0.15 threshold - and returned
    `ok` while estimating its output bit error rate at 0.19. The real rate was
    0.48. Every check it had was about the INPUT; none asked whether the output
    it had just produced was worth anything.
    """
    from pipeline.s3_receive.lockcheck import OUTPUT_BER_LIMIT, output_usable

    assert output_usable(0.19).verdict == FAIL
    assert output_usable(0.012).verdict == PASS
    assert output_usable(float("nan")).verdict == UNKNOWN
    # and it can never veto a stream S4 could still have recovered from: Nehal
    # measured the statistical path's ceiling at 3% raw
    assert OUTPUT_BER_LIMIT > 0.03


def test_a_whole_tone_spacing_of_offset_is_refused_not_guessed():
    """The FSK twin of the rotation ambiguity, found on `4fsk_13dB_2033`.

    An offset of one tone spacing maps the tone bank onto itself and slips
    every symbol label by one - identical tones, identical margins, every
    check passing, and a bit error rate of 0.248. S3 cannot resolve it, so it
    refuses the hypothesis instead of picking one of M readings.
    """
    from pipeline.s3_receive.lockcheck import tone_alias

    spacing = 50_000.0
    assert tone_alias(-49_951.0, spacing).verdict == FAIL     # the measured case
    assert tone_alias(2 * spacing, spacing).verdict == FAIL
    assert tone_alias(97.7, spacing).verdict == PASS          # small, fine
    assert tone_alias(0.4 * spacing, spacing).verdict == PASS  # not a whole one
    assert tone_alias(1000.0, 0.0).verdict == UNKNOWN         # nothing to judge


def test_search_prefers_the_hypothesis_that_needs_less_correcting():
    """Occam, as a tie-break, and it is load-bearing.

    `4fsk_13dB_2033` produced an identical estimate under a 0 Hz offset and
    under a -49 951 Hz one. The large offset won on tone margin - a meaningless
    difference - and decoded at 0.248. Two candidates the receiver cannot tell
    apart are separated by which makes the bigger claim about the input.
    """
    x = synth("4fsk", n_bits=120000, snr_db=15.0, sps=4)[0]
    params = {"fs": FS, "symbol_rate": RS,
              "cfo_hypotheses": [(-RS, 4, 90.0), (0.0, 2, 10.0)]}
    res = receive_best(x, params, modulations=["4fsk"])
    assert abs(res.values.get("cfo_hz_used", 0.0)) < 0.15 * RS, \
        f"took a {res.values.get('cfo_hz_used')} Hz correction over a 0 Hz one"


# --- Nehal's ask: the guaranteed keys -------------------------------------

ADVERSARIAL = {
    "pure noise": lambda n: noise(n),
    "DC only": lambda n: np.full(n, 1.0 + 0j),
    "all zeros": lambda n: np.zeros(n, dtype=complex),
    "clipped square": lambda n: np.sign(
        np.random.default_rng(1).normal(0, 1, n)).astype(complex),
    "single impulse": lambda n: np.eye(1, n, 0, dtype=complex).ravel(),
    "two tones": lambda n: (np.exp(2j * np.pi * 0.01 * np.arange(n))
                            + np.exp(2j * np.pi * 0.13 * np.arange(n))),
    "one sample": lambda n: np.ones(1, dtype=complex),
}


@pytest.mark.parametrize("case", list(ADVERSARIAL))
@pytest.mark.parametrize("mod", ALL_SIX)
def test_estimated_ber_is_a_primary_key(case, mod):
    """Nehal, 4 Sep: `estimated_output_ber` pinned as a primary key.

    It used to exist only on the success path, so a defensive short-circuit
    reading `values["estimated_output_ber"]` raised `KeyError` on exactly the
    inputs it was written to catch. Every key in `REQUIRED_VALUES` is now
    present on every path of every plug-in, and this is what says so.
    """
    x = ADVERSARIAL[case](120000)
    res = MODULATIONS[mod].receive(x, {"fs": FS, "symbol_rate": RS})
    for key in REQUIRED_VALUES:
        assert key in res.values, f"{mod}/{case}: {key} missing from values"
    ber = res.values["estimated_output_ber"]
    assert isinstance(ber, float) and 0.0 <= ber <= 1.0
    assert isinstance(res.values["estimated_output_ber_valid"], bool)
    assert res.values["envelope"] in ("inside", "outside")
    # and the dict form a caller logs or sends over a socket carries them too
    assert "estimated_output_ber" in res.as_stage_result()["values"]


@pytest.mark.parametrize("mod", ALL_SIX)
def test_pure_noise_is_a_failure_with_a_reason_not_a_shrug(mod):
    """The 4 Sep verify row, for all six rather than three.

    `low_confidence` would already be safe - nothing downstream would trust
    it - but it is the wrong answer, because it invites another hypothesis
    when there is nothing here to have a hypothesis about. `failed` with the
    measured line score in the reason ends the search and says why.
    """
    res = MODULATIONS[mod].receive(noise(), {"fs": FS, "symbol_rate": RS})
    assert res.status == "failed", f"{mod} returned {res.status} on pure noise"
    assert res.reason and "symbol-rate line" in res.reason
    assert res.values["estimated_output_ber_valid"] is False


@pytest.mark.parametrize("mod", ALL_SIX)
def test_giving_up_on_noise_is_fast(mod):
    """Clean give-up has to be cheap or it is not a give-up.

    The screen is one FFT. Running the whole chain on noise first and then
    reporting `low_confidence` costs 0.2-1.0 s per plug-in, which the 4 Sep
    hypothesis loop multiplies by the size of the registry product.
    """
    t0 = time.perf_counter()
    res = MODULATIONS[mod].receive(noise(), {"fs": FS, "symbol_rate": RS})
    elapsed = time.perf_counter() - t0
    assert res.status == "failed"
    assert elapsed < 0.20, f"{mod} took {elapsed*1e3:.0f} ms to give up"


@pytest.mark.parametrize("mod", ALL_SIX)
@pytest.mark.parametrize("params", [
    {"fs": FS, "symbol_rate": float("nan")},
    {"fs": float("nan"), "symbol_rate": RS},
    {"fs": FS, "symbol_rate": RS, "cfo_hz": float("nan")},
    {"fs": FS, "symbol_rate": -5.0},
    {"fs": FS, "symbol_rate": RS, "beta": float("nan")},
])
def test_a_non_finite_estimate_is_explained_not_raised(mod, params):
    """`estimate_symbol_rate` returns NaN when it finds no in-band peak, so
    this is a value S2 really produces and really hands over.

    It used to reach `rrc_taps` and come back as
    `ValueError: cannot convert float NaN to integer`. Nothing crashed - the
    catch-all in `receive()` held - and the reason string was the exception
    text, which tells a reader nothing about their signal.

    NaN walks through every guard written as an inequality, because `nan <= 0`,
    `nan < 2.0` and `nan > x` are all False. It has to be excluded by name.
    """
    x = synth("qpsk", n_bits=60000)[0]
    res = MODULATIONS[mod].receive(x, params)
    assert res.status == "failed"
    assert res.values["envelope"] == "outside"
    assert res.reason and "Error" not in res.reason, \
        f"reason is exception text, not an explanation: {res.reason}"


def test_envelope_marks_an_input_outside_what_s3_supports():
    """`failed` covers two different things and a caller needs them apart: an
    input beyond the declared envelope, and a fair input with nothing in it.
    Naidhruv's /envelope endpoint reads this."""
    x = synth("qpsk", n_bits=8000)[0]
    outside = MODULATIONS["qpsk"].receive(x, {"fs": 1.0, "symbol_rate": 0.8})
    assert outside.status == "failed"
    assert outside.values["envelope"] == "outside"

    inside = MODULATIONS["qpsk"].receive(noise(), {"fs": FS, "symbol_rate": RS})
    assert inside.status == "failed"
    assert inside.values["envelope"] == "inside"


# --- the hypothesis retry -------------------------------------------------

def test_search_recovers_from_a_wrong_top_hypothesis():
    """Block C. S2's top carrier offset is wrong; the second is not, and the
    loop is what reads it."""
    x = synth("qpsk", n_bits=120000, snr_db=18.0)[0]
    params = {
        "fs": FS,
        "symbol_rate": RS,
        "symbol_rate_hypotheses": [(RS, 90.0)],
        # top is the failure mode this day is about; zero is added by the
        # search itself and is the one that works
        "cfo_hypotheses": [(RS / 4.0, 4, 70.0), (13_000.0, 8, 20.0)],
    }
    single = MODULATIONS["qpsk"].receive(
        x, {"fs": FS, "symbol_rate": RS, "cfo_hz": RS / 4.0})
    assert single.status != "ok"

    best = receive_best(x, params)
    assert best.status == "ok", best.reason
    assert best.values["modulation"] == "qpsk"
    assert abs(best.values["cfo_hz_used"]) < 0.03 * RS


def test_search_is_bounded_on_an_input_that_matches_nothing():
    """Risk #5 through the front door. 6 modulations x 3 rates x 5 offsets of
    full chain runs is over a minute inside a 90-second pipeline budget; the
    cheap screen is what stops it being one."""
    params = {
        "fs": FS, "symbol_rate": RS,
        "symbol_rate_hypotheses": [(RS, 9.0), (0.6 * RS, 8.0), (1.7 * RS, 7.0)],
        "cfo_hypotheses": [(3000.0, 4, 5.0), (-7000.0, 8, 4.0), (900.0, 2, 3.0)],
    }
    t0 = time.perf_counter()
    res = receive_best(noise(), params)
    elapsed = time.perf_counter() - t0
    assert res.status == "failed"
    assert elapsed < 8.0, f"searching noise took {elapsed:.1f} s"
    assert res.values["search_chain_runs"] == 0, \
        "the screen let a full demodulation of pure noise through"


def test_search_records_why_each_candidate_was_refused():
    """"S3 chose 8-PSK" is not something anyone can check. The rejections are
    the part of the answer that can be argued with, so they are kept."""
    res = receive_best(noise(), {"fs": FS, "symbol_rate": RS})
    trail = [h for h in res.hypotheses if isinstance(h.value, dict)
             and "modulation" in h.value]
    assert trail, "the search returned no audit trail"
    assert all(h.evidence for h in trail)
    summary = res.hypotheses[-1].value
    assert summary["chain_runs"] == 0 and summary["screened"] >= len(trail) - 1


def test_search_never_names_a_scheme():
    """The registry is the list. Adding a modulation must be a registration
    line, not an edit here - `grep` run as code so it is checked every run."""
    src = (Path(__file__).resolve().parents[2] / "pipeline" / "s3_receive"
           / "search.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])
    for scheme in ("bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"):
        assert f'"{scheme}"' not in code and f"'{scheme}'" not in code, \
            f"search.py names {scheme} in code rather than iterating MODULATIONS"


# --- against the real corpus ----------------------------------------------

@has_corpus
@pytest.mark.parametrize("name", ["qpsk_20dB_2011", "bpsk_20dB_2005",
                                  "8psk_20dB_2017", "16qam_20dB_2023",
                                  "2fsk_20dB_2029", "4fsk_20dB_2035"])
def test_corpus_file_decodes_through_the_blind_search(name):
    """End to end on Dheeraj's real corpus, from S2's blind estimates only.

    This replaces the old `rf_channel.py` fixture arm. It is the tightest
    statement S3 can make on its own: real WAV in, real S2 estimates in, bits
    out that match what the zoo transmitted.
    """
    iq, fs, truth = corpus.load(name)
    tx = corpus.reference_bits(truth)
    s2 = estimate(iq, fs)

    res = receive_best(iq, params_from_s2(s2, fs))
    assert res.status == "ok", res.reason
    assert res.values["modulation"] == truth["scheme"], \
        f"chose {res.values['modulation']} for a {truth['scheme']} file"
    ber = corpus.measured_ber(res, tx)
    assert ber < 0.01, f"{name}: raw BER {ber:.4f} on the best rotation"


@has_corpus
def test_the_corpus_regenerates_exactly():
    """Everything above rests on this: the transmitted bits can be rebuilt from
    the seed in the truth JSON, so a bit error rate is measured against what was
    actually sent rather than against a re-derivation that might share an error
    with the receiver."""
    from zoo.rf import through_channel

    iq, fs, truth = corpus.load("qpsk_20dB_2011")
    tx = corpus.reference_bits(truth)
    regen, n_used = through_channel(
        tx, truth["scheme"], truth["sps"], truth["beta"], truth["snr_db"],
        truth["cfo_norm"], truth["phase_rad"], truth["timing_offset_sym"],
        truth["seed"])
    assert n_used == truth["n_bits_used"]
    n = min(regen.size, iq.size)
    scale = np.vdot(iq[:n], regen[:n]) / np.vdot(iq[:n], iq[:n])
    err = (np.mean(np.abs(regen[:n] - scale * iq[:n]) ** 2)
           / np.mean(np.abs(regen[:n]) ** 2))
    assert err < 1e-6, f"relative mismatch {err:.2e} - the corpus moved"
