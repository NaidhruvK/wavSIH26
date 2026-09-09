"""8 Sep: S3 against input that is not a signal, through the path the service uses.

`test_s3_receive.py` has had an adversarial block since 4 Sep, and it covers
`MODULATIONS[name].receive(iq, params)` - a NAMED plug-in handed a symbol rate.
This file covers `receive_best(iq, params_from_s2(estimate(iq, fs), fs))`, which
is what `service/orchestrator.py` actually calls, and which has a search, a rate
rescue, a de-duplication grid and a deadline that the plug-in path does not.

The generators live in `reports/s3_adversarial_study.py` so that the study and
these tests cannot drift apart: a case defined twice is a case that will
eventually be two different cases. The full measurement over 8 seeds and both
paths is `reports/s3_adversarial.md`; this file pins the properties.

NOTHING HERE ASSERTS ON WALL-CLOCK TIME
---------------------------------------
The reflex on "it takes too long" or "it must answer quickly" is
`assert elapsed < N`. That is the instrument that produced the 7 Sep flake, and
it fails on a loaded machine while the code it guards is correct. Every
assertion here is on WORK or on a VERDICT - status, modulation, finiteness, a
rate ratio - which reads the same on Nehal's box and mine. `test_s3_receive.py`
already owns the one legitimate timing test (`test_wrong_symbol_rate_fails_fast`,
which guards a 257-second denial of service and asserts a 5 s bound with three
orders of magnitude of headroom); this file adds no more.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.s0_ingest import ingest                          # noqa: E402
from pipeline.s2_estimate import estimate                      # noqa: E402
from pipeline.s3_receive.search import (params_from_s2,        # noqa: E402
                                        receive_best)
from registry import MODULATIONS                               # noqa: E402


def _study():
    """The study module, imported by path.

    `reports/` is not a package and importing it as one would need an
    `__init__.py` in a directory full of scripts. Loading by path keeps the
    generators in exactly one place without changing how reports are laid out.
    """
    spec = importlib.util.spec_from_file_location(
        "_s3_adversarial_study", ROOT / "reports" / "s3_adversarial_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


STUDY = _study()
SEEDS = (0, 1)          # the study sweeps 8; two is enough to pin a property
VALID = STUDY.VALID


def _blind(case: str, seed: int):
    iq, declared_fs, ref = STUDY.CASES[case](STUDY._seed(case, seed))
    iq = np.asarray(iq, dtype=complex)
    s2 = estimate(iq, declared_fs)
    return receive_best(iq, params_from_s2(s2, declared_fs)), ref, declared_fs


# --- the definition of done -------------------------------------------------

@pytest.mark.parametrize("case", list(STUDY.CASES))
@pytest.mark.parametrize("seed", SEEDS)
def test_every_adversarial_input_returns_a_status_through_the_blind_search(case, seed):
    """The row's definition of done: a status, never a traceback.

    An exception is the one failure mode with no good explanation - a judge
    sees a stack trace instead of an answer, and nothing downstream can even
    report that the stage declined.
    """
    res, _ref, _fs = _blind(case, seed)
    assert res.status in VALID, f"{case}: status {res.status!r} is not a contract status"
    if res.status == "failed":
        assert res.reason, f"{case}: failed without a reason - house rule 3"


@pytest.mark.parametrize("case", list(STUDY.CASES))
@pytest.mark.parametrize("seed", SEEDS)
def test_llrs_handed_to_s4_are_always_finite(case, seed):
    """S4 consumes this array directly. A NaN in it is a defect two stages away."""
    res, _ref, _fs = _blind(case, seed)
    if res.llrs is None:
        return
    llrs = np.asarray(res.llrs)
    assert llrs.dtype == np.float64, f"{case}: LLR dtype {llrs.dtype}"
    assert np.all(np.isfinite(llrs)), f"{case}: non-finite LLRs"


# --- the false-positive direction, which is the gate item -------------------

@pytest.mark.parametrize("case", STUDY.ABSENCE)
@pytest.mark.parametrize("seed", SEEDS)
def test_an_empty_band_is_never_reported_as_a_confident_lock(case, seed):
    """No signal is present, so `ok` is a confident lie.

    S3's half of the 8 Sep gate item - the same question Nehal's column asks of
    S4 as "uncoded random data must not produce a false code detection".
    Everything downstream reads `status` before it reads anything else, so an
    `ok` here propagates as truth through the whole report.

    This is asserted on the ABSENCE cases only, and that distinction is load-
    bearing. A hard-clipped QPSK capture is adversarial and also genuinely
    QPSK - it SHOULD come back `ok` - so asserting "no adversarial input is
    ever ok" would forbid the receiver from being right. See
    `reports/s3_adversarial.md` §3.
    """
    res, _ref, _fs = _blind(case, seed)
    assert res.status != "ok", (
        f"{case} claims a confident lock on a band with no signal in it "
        f"(modulation={res.values.get('modulation')!r})")


@pytest.mark.parametrize("case", STUDY.ABSENCE)
def test_no_absence_case_survives_the_named_plug_in_path_either(case):
    """The same question of every plug-in handed an explicit, plausible rate.

    The blind search can refuse on the cheap screen before any plug-in runs, so
    passing the test above does not by itself say the plug-ins are safe - it can
    say the screen is. This asks each demodulator directly.
    """
    iq, declared_fs, _ref = STUDY.CASES[case](STUDY._seed(case, 0))
    iq = np.asarray(iq, dtype=complex)
    params = {"fs": declared_fs, "symbol_rate": declared_fs / 4.0}
    for name in MODULATIONS:
        res = MODULATIONS[name].receive(iq, params)
        assert res.status != "ok", f"{name} claims a lock on {case}"


# --- the finding, pinned ----------------------------------------------------

def test_a_mislabelled_sample_rate_scales_the_reported_symbol_rate():
    """A wrong `fs` is invisible to S3, and this pins exactly how it shows up.

    The samples are a clean 200 kHz QPSK capture; the header says 48 kHz. Every
    stage of S3 works on `fs / symbol_rate`, so the demodulation is CORRECT and
    the reported symbol rate is wrong by exactly the ratio of the lie. S3 cannot
    detect this - absolute time is not in the samples, it arrives only from the
    WAV header or the service's `fs_hint` field.

    Pinned rather than fixed, because there is nothing here to fix. The test
    exists so that a future change which alters this behaviour - in either
    direction - is visible rather than silent, and so the number in
    `reports/s3_adversarial.md` §4 has something keeping it honest.
    """
    res, _ref, declared_fs = _blind("wrong sample rate", 0)
    assert res.status == "ok"
    assert res.values["modulation"] == "qpsk"

    true_fs, true_rate = 200_000.0, 50_000.0
    expected = true_rate * (declared_fs / true_fs)
    reported = float(res.values["symbol_rate_used"])
    assert reported == pytest.approx(expected, rel=1e-3), (
        f"declared fs {declared_fs} should scale the reported rate to "
        f"{expected} Hz, got {reported}")
    # sps is a ratio, so it is untouched by the lie - which is the mechanism.
    assert float(res.values["sps_estimated"]) == pytest.approx(4.0, rel=1e-3)


def test_a_saturated_capture_still_decodes_and_should():
    """Clipping is damage, not absence, and QPSK survives it.

    QPSK is constant-modulus: clipping at a quarter of peak removes the RRC
    pulse shaping's overshoot and leaves the symbols. `ok` is the right answer
    and this asserts the receiver is right for the right reason - a low measured
    BER against the bits that were actually transmitted, scored by the repo's
    own `corpus.measured_ber` rather than a comparison written here.
    """
    from tests.fixtures import corpus

    res, ref, _fs = _blind("clipped (saturated)", 0)
    assert res.status == "ok"
    assert res.values["modulation"] == "qpsk"
    assert corpus.measured_ber(res, np.asarray(ref)) < 0.01


# --- the verify line: six files, six clean statuses -------------------------

def test_the_six_adversarial_files_ingest_and_return_clean_statuses():
    """The day's verify line, run against the files on disk rather than arrays.

    `reports/s3_adversarial/*.wav` are written by
    `python reports/s3_adversarial_study.py --write-files` and go through S0
    exactly like a corpus file, so this covers the header/ingest half that an
    in-memory array cannot: a WAV whose declared rate is a lie is still a
    perfectly valid WAV, and S0 reads the rate from the header.
    """
    d = ROOT / "reports" / "s3_adversarial"
    files = sorted(d.glob("*.wav"))
    assert len(files) == 6, f"expected six adversarial files in {d}, found {len(files)}"

    for path in files:
        s0 = ingest(path)
        assert s0.status == "ok", f"{path.name}: S0 said {s0.status} ({s0.reason})"
        assert s0.iq is not None and s0.fs
        s2 = estimate(s0.iq, s0.fs)
        res = receive_best(s0.iq, params_from_s2(s2, s0.fs))
        assert res.status in VALID, f"{path.name}: {res.status!r}"
        if res.status == "failed":
            assert res.reason, f"{path.name}: failed with no reason"
        # the absence files must not claim a lock, from disk as well as in memory
        if path.stem in ("pure_noise", "DC_only", "empty_band"):
            assert res.status != "ok", f"{path.name} claims a lock"


def test_the_committed_files_are_reproducible_from_the_study(tmp_path, monkeypatch):
    """Seed 0 of each case must regenerate the committed file BYTE FOR BYTE.

    The study seeds off `zlib.crc32(case)` rather than `hash(case)` precisely so
    this holds: Python salts string hashing per process, so a `hash()`-derived
    seed would have made every one of these files unreproducible while looking
    completely deterministic inside a single run.

    This compares SAMPLES, and the first two attempts at it were both wrong in
    opposite directions - worth recording, because the second looked stricter.

    The first checked only the header rate and the number of samples. That would
    have passed against a file whose every sample was wrong, and one of them was:
    `empty_band.wav` was written as PCM_16 and quantised onto two distinct
    values, which no shape check can see.

    The second compared raw file BYTES, which failed on all six at byte 60 while
    every sample was identical. libsndfile writes a `PEAK` chunk for float WAVs
    carrying a creation TIMESTAMP, so a float WAV is deliberately not
    byte-reproducible. Asserting byte-identity would have been a permanently red
    test guarding a property the format does not offer - and it is only the
    samples that anything downstream reads.
    """
    import soundfile as sf

    d = ROOT / "reports" / "s3_adversarial"
    monkeypatch.setattr(STUDY, "FILE_DIR", tmp_path)
    STUDY.write_files()

    for case in STUDY.THE_SIX:
        name = "_".join(case.replace(":", "").replace("(", "")
                        .replace(")", "").split())
        committed, fresh = d / f"{name}.wav", tmp_path / f"{name}.wav"
        assert committed.exists(), f"missing committed file {committed}"
        assert fresh.exists(), f"write_files did not produce {fresh}"
        a, rate_a = sf.read(str(committed))
        b, rate_b = sf.read(str(fresh))
        assert rate_a == rate_b, f"{name}.wav: rate {rate_a} vs {rate_b}"
        assert sf.info(str(committed)).subtype == sf.info(str(fresh)).subtype
        assert np.array_equal(a, b), (
            f"{name}.wav does not regenerate sample-for-sample from the study")


def test_the_empty_band_file_still_holds_an_empty_band():
    """The level survives the round trip to disk, which PCM_16 did not allow.

    `empty band` is thermal noise at 1e-6 — the case exists to ask whether any
    decision in the chain is made on an ABSOLUTE level rather than a ratio. One
    PCM_16 quantum is 3.05e-05, so at the corpus's own subtype this capture
    collapsed onto ±1 LSB: 2 distinct sample values across 240,000, a one-bit
    dither pattern rather than a quiet band. The array in memory was always
    right; the file was not, and a sample-count check could not see it.

    Pinned because the fix is a subtype argument that is easy to "tidy" back to
    match the corpus.
    """
    import soundfile as sf

    path = ROOT / "reports" / "s3_adversarial" / "empty_band.wav"
    info = sf.info(str(path))
    assert info.subtype == "FLOAT", (
        f"empty_band.wav is {info.subtype}; a fixed-point subtype cannot carry "
        "a 1e-6 signal and silently turns this case into a dither pattern")
    data, _ = sf.read(str(path))
    assert np.max(np.abs(data)) < 1e-4, "level was normalised away"
    assert len(np.unique(data)) > 1000, (
        f"only {len(np.unique(data))} distinct sample values — quantised flat")


# --- 9 Sep: the guard pass --------------------------------------------------
#
# The 9 Sep row is "read S3 end to end looking for anything that can throw,
# guards only". These pin what that read found. EVERY case below left the stage
# as a traceback on `origin/main` at `0cc87b3`, and the exception each one used
# to produce is named in its assertion message, so a revert that restores the
# old behaviour fails here rather than in front of a judge.
#
# Nothing here asserts on the clock - see this module's docstring. Every
# assertion is on a status, a reason or a sentinel, which read the same on any
# machine at any speed.

_CONTROL = "control: clean qpsk"
"""The study's own clean 20 dB QPSK capture. Named here so this section and
the study cannot drift into two different controls."""

_NO_KEY = object()
"""Sentinel: drop the key entirely rather than set it to something."""


def _valid_capture():
    """The known-answer control, as a capture and its S2-derived params.

    The clean case, not an adversarial one, on purpose: these tests are about a
    parameter that is wrong, over a signal that is right. If the capture were
    also degenerate a refusal would prove nothing, which is the mistake the
    8 Sep entry in day2day records against this very file.
    """
    iq, declared_fs, _ = STUDY.CASES[_CONTROL](STUDY._seed(_CONTROL, 0))
    iq = np.asarray(iq, dtype=complex)
    return iq, params_from_s2(estimate(iq, declared_fs), declared_fs)


def test_the_control_capture_still_demodulates():
    """The known-answer cell, first in the section rather than after it.

    Every test below asserts that something is REFUSED. A capture S3 cannot
    demodulate at all would make all of them pass while proving nothing - the
    exact failure the 8 Sep hand-rolled transmitter produced, where three of six
    adversarial cases could only ever have reported a refusal.
    """
    iq, params = _valid_capture()
    res = receive_best(iq, params)
    assert res.status == "ok", (
        f"the control capture came back {res.status!r} ({res.reason}); every "
        "refusal asserted below is meaningless until this line passes")


@pytest.mark.parametrize("fs_value", [
    pytest.param(0.0, id="zero"),
    pytest.param(_NO_KEY, id="absent-key"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(-200000.0, id="negative"),
    pytest.param("wide", id="unreadable-string"),
    pytest.param(None, id="none"),
])
def test_an_unusable_sample_rate_is_refused_rather_than_raising(fs_value):
    """A sample rate S3 cannot use ends the search with a status, not a stack.

    `receive_best` defaults `fs` to 0.0 when the mapping carries no `fs` key,
    and zero is not a small sample rate - it is no frequency axis at all. That
    default reached `np.fft.rfftfreq(n, d=1.0 / fs)`, where `1.0 / fs` is a
    plain Python division: measured on this capture, `0.0`, an absent key and
    `inf` all left the stage as **ZeroDivisionError**, while `"wide"` and
    `None` raised ValueError and TypeError coercing on the way in. `nan` and a
    negative rate did not raise and were worse in a quieter way - they returned
    `failed` saying "every candidate was refused by the cheap screen", which is
    a verdict over a field that could not be measured at all.

    Every modulation plug-in has refused exactly this by name since 4 Sep
    (`base.unusable_reason`). The search never reached one, because the
    screening pass runs first. This asserts it now gives the same answer.
    """
    iq, params = _valid_capture()
    if fs_value is _NO_KEY:
        params.pop("fs")
    else:
        params["fs"] = fs_value

    res = receive_best(iq, params)

    assert res.status == "failed"
    assert res.reason and "not a usable number" in res.reason, (
        f"reason was {res.reason!r}; an unusable sample rate must be named, "
        "not reported as a field the screen looked at and refused")
    assert res.values["envelope"] == "outside", (
        "an unusable sample rate is an input outside what S3 supports, which "
        "is the distinction `values['envelope']` carries for /envelope")


@pytest.mark.parametrize("fs_value", [0.0, -200000.0, float("nan"), float("inf")])
def test_the_cheap_spectral_checks_answer_on_an_unusable_sample_rate(fs_value):
    """The same guard sits in `lockcheck`, and it is not redundant.

    These four are exported and called directly - by `reports/` today, and by
    anything that wants the spectral evidence without paying for the chain. The
    search guard above cannot help those callers. Two different frames raised:
    `1.0 / fs` inside `_averaged_spectrum` for `0.0` and `inf`, and scipy's
    `welch`, which rejects a non-positive or NaN `fs` itself with
    "Sampling frequency fs=... must be positive!".

    Each now returns the value its own docstring already promises for "nothing
    measurable" - None for the line search, 0.0 for the offset - so no caller
    needs a new branch and no new sentinel enters the module.
    """
    from pipeline.s3_receive.lockcheck import (carrier_alignment, carrier_offset,
                                               signal_presence, strongest_line,
                                               symbol_rate_line)
    iq, _ = _valid_capture()

    for family in ("psk", "fsk"):
        assert strongest_line(iq, fs_value, family) is None
        assert symbol_rate_line(iq, fs_value, 50000.0, family) == 0.0
        assert signal_presence(iq, fs_value, 50000.0, family).failed, (
            "with no frequency axis there is no line to find, so the presence "
            "check must refuse rather than pass on absent evidence")
    assert carrier_offset(iq, fs_value) == 0.0
    assert carrier_alignment(iq, fs_value, 50000.0).verdict in ("pass", "fail",
                                                                "unknown")


class _S2ThatChangedType:
    """An S2 result whose fields are present and the wrong type.

    Not a shape this repo produces today - `S2Result` annotates `fs: float` and
    defaults every ranked list to `[]`. It is the shape `params_from_s2`
    promises in its own docstring to survive, and the shape 8 Sep's
    `order_hint` finding actually took: an attribute that IS there, so the
    `getattr` default beside it never fires.
    """
    fs = None
    symbol_rate_hz = "fifty thousand"
    cfo_hz = None
    symbol_rate_hypotheses = 7
    cfo_hypotheses = None
    modulation_hypotheses = None


def test_the_s2_adapter_survives_an_s2_whose_fields_changed_type():
    """`params_from_s2` declines to raise on the way to a value.

    Its docstring says everything is "a `getattr` with a default, so an S2 that
    grows a field gets used and an S2 that lacks one still works". That held for
    a field that went MISSING and not for one that changed TYPE: `float(None)`
    raised TypeError, and a ranked list arriving as a scalar raised
    `TypeError: 'int' object is not iterable` inside `list()`.

    The adapter does not invent a rate. It returns 0.0, which the test above
    asserts `receive_best` refuses by name - so an S2 that changed shape gives a
    clean refusal naming the sample rate, rather than a traceback from an
    adapter three frames from anything a reader would suspect.
    """
    params = params_from_s2(_S2ThatChangedType(), None)

    assert params["fs"] == 0.0
    assert params["symbol_rate_hypotheses"] == []
    assert params["cfo_hypotheses"] == []
    assert params["modulation_hypotheses"] == []

    iq, _ = _valid_capture()
    res = receive_best(iq, params)
    assert res.status == "failed"
    assert "not a usable number" in (res.reason or "")


def test_a_constellation_order_of_zero_says_what_is_wrong():
    """The power-of-two check could not see the one order that most needs it.

    `bits_per_symbol(0)` computed `(0).bit_length() - 1 == -1` and then raised
    `ValueError: negative shift count` from inside the check itself, one line
    before the message that would have said what was wrong. Same family as a
    check that cannot see: it did raise, but about its own arithmetic rather
    than about the input. Every valid order is untouched and an invalid one
    still raises ValueError; only what it says changed.
    """
    from pipeline.s3_receive.bitmap import bits_per_symbol

    assert bits_per_symbol(2) == 1 and bits_per_symbol(16) == 4
    for bad in (0, -4):
        with pytest.raises(ValueError, match="not a power of two"):
            bits_per_symbol(bad)
