"""What an LDPC decoder needs from S3, pinned. Owner: Anvith.

7 September, day-clock block C. The plug-in itself is not written - a
`CodePlugin` belongs in `pipeline/s5_decode/`, which is Nehal's, and a file in
someone else's directory is a request at the sync rather than an edit. The
design, the measurements behind it and the request are in
`reports/s3_ldpc_design.md`.

What IS written is this file: the two properties of S3's output that an LDPC
decode path depends on and that nothing before it has needed, each asserted
rather than described.

  1. `llr_start_bit` - where the emitted stream begins inside the transmitted
     one. Viterbi, Reed-Solomon and S4 are all indifferent to this (S4's
     per-file label JSON has carried `start_offset` since 29 August), so it
     was never reported until today. A block code decoded against a supplied
     parity-check matrix is not indifferent: a codeword has a first bit.

  2. The LLR magnitudes are worth what they claim. Viterbi maximises a SUM of
     LLRs and is invariant to scaling them; sum-product belief propagation
     combines them through `tanh` and is not. So BP is the first consumer in
     this project whose answer depends on the magnitudes being right.

The corpus tests here are skipped when `zoo/corpus/rf/` is absent, like the
rest of the S3 corpus tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.s3_receive  # noqa: E402,F401  (registers the plug-ins)
from pipeline.s3_receive.softmap import llr_to_bits  # noqa: E402
from registry import CODES, MODULATIONS  # noqa: E402
from tests.fixtures import corpus  # noqa: E402

try:
    # Code plug-ins register on EXPLICIT import - `pipeline/s5_decode/__init__.py`
    # is empty by design - so without this the acceptance test below would skip
    # forever even after the file landed, and "it wakes up the moment the
    # plug-in is registered" would be a claim this file quietly failed to keep.
    import pipeline.s5_decode.ldpc_code  # noqa: E402,F401
except ModuleNotFoundError as exc:
    # ONLY the plug-in being absent is a skip. If the file exists and something
    # it imports does not, that is a broken plug-in and it must be loud - an
    # except-and-pass here would turn it into a silent permanent skip, which is
    # the "check that cannot see and does not say so" failure this repo names
    # as a house rule.
    if exc.name != "pipeline.s5_decode.ldpc_code":
        raise

has_corpus = pytest.mark.skipif(
    not corpus.corpus_files(),
    reason="zoo/corpus/rf/ is not present in this clone")


def _best_rotation(res, tx):
    """The rotation, offset and inversion `corpus.measured_ber` would pick.

    Mirrors that function rather than re-deriving the comparison. A previous
    study in this repo scored its own bit errors instead of calling it, forgot
    the alignment offset, and produced a table of 0.497 in every cell.
    """
    best = None
    for cand in getattr(res, "llrs_by_rotation", None) or []:
        e, off = corpus.align(llr_to_bits(cand), tx)
        score = min(e, 1.0 - e)
        if best is None or score < best[0]:
            best = (score, np.asarray(cand, dtype=np.float64), off,
                    (1.0 - e) < e)
    return best


# --- 1. where the stream starts ---------------------------------------------

# One file per modulation at two SNRs. 8 dB is in the list because that is
# where `carrier_settled_at` is non-zero and actually varies - 3328 on the
# 16-QAM file against 0 on BPSK - so the reported value has to track something
# rather than happen to match a constant. 4 dB is deliberately NOT here: 8-PSK
# and 16-QAM at 4 dB come back at a bit error rate near 0.42, where `align`
# itself is barely working, and a test whose instrument is unreliable on the
# input is not evidence about the thing it names.
_START_BIT_FILES = [
    "bpsk_8dB_2001", "bpsk_20dB_2005",
    "qpsk_8dB_2007", "qpsk_20dB_2011",
    "8psk_8dB_2013", "8psk_20dB_2017",
    "16qam_8dB_2019", "16qam_20dB_2023",
    "2fsk_8dB_2025", "2fsk_20dB_2029",
    "4fsk_8dB_2031", "4fsk_20dB_2035",
]


@has_corpus
@pytest.mark.parametrize("name", _START_BIT_FILES)
def test_reported_llr_start_bit_matches_the_measured_offset(name):
    """`llr_start_bit` lands where the stream actually starts, within its own
    stated tolerance.

    Until 7 Sep `values` was short by a constant 507 symbols - 507 bits on
    BPSK and 2028 on 16-QAM - because three of the terms are quantities the
    stage knows and a consumer cannot see: Gardner's two-symbol interpolator
    head start, the 500-symbol settling trim, and the equaliser's centre tap.

    The tolerance is one symbol and is not slack that could be tightened: the
    residue is a discarded half-symbol, because Gardner's first output sits at
    sample `2 + 2*period` - symbol 2.5 at 4 samples per symbol - and the floor
    division that turns it into a symbol count throws the 0.5 away. Claiming
    the value was exact would have been the more useful statement and the false
    one.

    **The bound is `0 <= err <= tol`, and the lower half carries its own
    weight.** A consumer searches FORWARD from `llr_start_bit`, so a reported
    value that OVERSHOT would put the true start behind the search window where
    no amount of searching finds it. Measured non-negative on all 36 cells.

    Measured across all 36 (modulation, SNR) cells in
    `reports/s3_ldpc_design.md`: 36 of 36 inside tolerance. These twelve are
    the subset where `carrier_settled_at` is non-zero and varies.
    """
    iq, fs, truth = corpus.load(name)
    tx = corpus.reference_bits(truth)
    res = MODULATIONS[truth["scheme"]].receive(
        iq, {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0})

    picked = _best_rotation(res, tx)
    assert picked is not None, f"{name}: no LLRs to locate ({res.reason})"
    ber, _, true_off, _ = picked
    assert ber < 0.1, (
        f"{name}: bit error rate {ber:.3f} - `align` cannot be trusted to "
        f"find the offset on a stream this wrong, so this file cannot say "
        f"anything about `llr_start_bit` either way")

    reported = res.values["llr_start_bit"]
    tol = res.values["llr_start_bit_tolerance"]
    err = true_off - reported
    assert 0 <= err <= tol, (
        f"{name}: stream really starts at bit {true_off}, S3 reports "
        f"{reported} +{tol}. Error {err:+d} bits is outside that window, so a "
        f"decoder searching forward from the reported value would never find "
        f"the codeword boundary.")


# --- 2. are the magnitudes worth what they claim ----------------------------

_MIN_ERRORS = 20
"""Fewest observed errors a |LLR| bin needs before it is scored at all.

At 20 the relative standard error of a Poisson count is 22%, which supports a
verdict against a factor-of-two band and nothing tighter.
"""

_CALIBRATION_LIMIT = 2.0
"""Largest empirical/promised error ratio a bin may show on an `ok` file.

The same factor of two the 3 Sep contract already applies to
`estimated_ber`'s aggregate - a per-bin claim cannot be stricter than the
aggregate claim it sits under. Measured worst across the whole `ok` population
in `reports/s3_llr_calibration.md` is **1.62** (2-FSK at 4 dB), so the margin
is 1.23x. 16-QAM reads 1.25 and 4-FSK 1.41.
"""

# The only corpus files that produce a scorable bin on an `ok` result. Every
# other cell decodes with too few bit errors to measure a reliability curve:
# 19 818 of 19 955 BPSK bits at 4 dB sit in the |LLR| >= 16 bin with zero
# errors, and zero errors out of twenty thousand is consistent with the
# promise and with a promise ten times smaller. Those cells are unmeasured,
# not passing, and they are left out rather than counted as evidence.
_CALIBRATED_FILES = ["16qam_8dB_2019", "2fsk_4dB_2024", "4fsk_4dB_2030"]


def _bin_ratios(res, tx, edges=(0.0, 0.5, 1.0, 2.0, 4.0, 8.0)):
    """(lo, hi, n_errors, empirical/promised) per |LLR| bin."""
    picked = _best_rotation(res, tx)
    if picked is None:
        return []
    _, llrs, off, inverted = picked
    bits = llr_to_bits(llrs)
    if inverted:
        bits = 1 - bits
    n = int(min(bits.size, 20000, tx.size // 2))
    err = bits[:n] != tx[off:off + n]
    mag = np.abs(llrs[:n])
    promised = 1.0 / (1.0 + np.exp(np.clip(mag, 0.0, 700.0)))

    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (mag >= lo) & (mag < hi)
        if not m.any():
            continue
        n_err = int(err[m].sum())
        p = float(promised[m].mean())
        out.append((lo, hi, n_err, (err[m].mean() / p) if p > 0 else np.inf))
    return out


@has_corpus
def test_the_llrs_s3_stands_behind_are_calibrated_per_bin():
    """Not just on average - per bin, which is what belief propagation reads.

    `estimated_ber` already pins the MEAN of `1/(1+exp(|llr|))` against the
    measured error rate. A demapper can pass that while being over-confident
    on its strong bits and under-confident on its weak ones, which is a
    correct mean and a useless reliability curve. Sum-product combines
    magnitudes through `tanh` and consumes the curve, not the mean.

    NOT parametrized, and that is the point. These files sit close to the
    scoring floor - 2-FSK at 4 dB carries 27 errors in its best bin against a
    minimum of 20 - so a change that IMPROVES the demapper can take one of them
    below it. Per file that would be a red build for a good change, which is a
    false alarm; across the set it is the property becoming untestable, which
    is a real one. So an unscorable file is skipped with its reason recorded
    and the run fails only when NOTHING is left to measure.
    """
    checked, unscorable = [], []
    for name in _CALIBRATED_FILES:
        iq, fs, truth = corpus.load(name)
        tx = corpus.reference_bits(truth)
        res = MODULATIONS[truth["scheme"]].receive(
            iq, {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0})
        if res.status != "ok":
            unscorable.append(f"{name}: status {res.status} ({res.reason})")
            continue
        scored = [(lo, hi, r) for lo, hi, n_err, r in _bin_ratios(res, tx)
                  if n_err >= _MIN_ERRORS]
        if not scored:
            unscorable.append(f"{name}: no bin reached {_MIN_ERRORS} errors")
            continue
        for lo, hi, ratio in scored:
            checked.append((name, lo, hi, ratio))
            assert ratio <= _CALIBRATION_LIMIT, (
                f"{name}: bits with |LLR| in [{lo:g}, {hi:g}) went wrong "
                f"{ratio:.2f}x more often than their LLR promised. "
                f"Over-confident input is what makes belief propagation settle "
                f"on a wrong codeword - see reports/s3_ldpc_design.md")

    assert checked, (
        f"no corpus file could be scored at all, so this test measured "
        f"nothing and passing would be corroboration invented out of an "
        f"absence. Reasons: {unscorable}. Re-pick `_CALIBRATED_FILES` against "
        f"reports/s3_llr_calibration.md rather than relaxing the bound.")


@has_corpus
def test_the_streams_with_over_confident_llrs_are_the_ones_s3_refuses():
    """The gate an LDPC decoder has to respect, and why it is not a nicety.

    On these files the demapper emits magnitudes of 4 to 8 - promising about
    0.4% error - over bits that are wrong 29% and 39% of the time: 66x and 82x
    over-confident. Fed to sum-product that is not a degraded decode, it is a
    decoder arguing itself into a wrong codeword with confidence.

    S3 refuses both. **This test pins the IMPLICATION, not either half**: if a
    stream's strong LLRs are badly over-confident then `status` is not `ok`.
    The design rule it justifies - decode only `status == "ok"` - is worth
    nothing if the refusal ever stops covering the over-confidence.

    Same shape as the test above and for the same reason: a file that stopped
    being badly calibrated has made the implication vacuous rather than false,
    so it is skipped with its reason recorded. The run fails only if no file
    is left to test the implication on.
    """
    checked, vacuous = [], []
    for name in ("8psk_4dB_2012", "16qam_4dB_2018"):
        iq, fs, truth = corpus.load(name)
        tx = corpus.reference_bits(truth)
        res = MODULATIONS[truth["scheme"]].receive(
            iq, {"fs": fs, "symbol_rate": fs / truth["sps"], "cfo_hz": 0.0})

        high = [r for lo, hi, n_err, r in _bin_ratios(res, tx)
                if lo >= 4.0 and n_err >= _MIN_ERRORS]
        if not high:
            vacuous.append(f"{name}: no high-|LLR| bin carried enough errors")
            continue
        if max(high) <= 10.0:
            vacuous.append(f"{name}: worst high-|LLR| bin only "
                           f"{max(high):.1f}x over-confident")
            continue
        checked.append(name)
        assert res.status != "ok", (
            f"{name}: S3 returned ok on a stream whose strong LLRs are "
            f"{max(high):.0f}x over-confident. An LDPC decoder gating on "
            f"status would now be handed exactly the input that breaks it.")

    assert checked, (
        f"no file was still over-confident enough to test the implication on, "
        f"so this test asserted nothing. Reasons: {vacuous}. Re-pick against "
        f"reports/s3_llr_calibration.md.")


# --- 3. the supplied H, and the plug-in that does not exist yet -------------

def supplied_h(k: int = 8, m: int = 4, seed: int = 11):
    """A small systematic parity-check matrix and its generator.

    H = [P | I_m] and G = [I_k | P^T] over GF(2), so `H @ (u @ G) == 0` for
    every information vector `u`. Systematic and tiny on purpose: the fixture's
    job is to be obviously a valid H, not to be a good code.

    This is the `supplied` in "with a supplied parity-check matrix" - the
    day-clock row asks for a decode path given H, and blind recovery of H is
    stated as out of scope in `reports/envelope.md`.
    """
    rng = np.random.default_rng(seed)
    n = k + m
    p = rng.integers(0, 2, size=(m, k), dtype=np.uint8)
    h = np.concatenate([p, np.eye(m, dtype=np.uint8)], axis=1)
    g = np.concatenate([np.eye(k, dtype=np.uint8), p.T], axis=1)
    assert h.shape == (m, n) and g.shape == (k, n)
    return h, g


def test_the_supplied_h_fixture_is_a_valid_parity_check_matrix():
    """Every codeword this fixture produces satisfies its own H.

    Written before anything that consumes it. A decoder tested against an H
    and a G that do not agree fails for a reason that has nothing to do with
    the decoder, and that is a day nobody gets back.
    """
    h, g = supplied_h()
    rng = np.random.default_rng(3)
    for _ in range(20):
        u = rng.integers(0, 2, size=g.shape[0], dtype=np.uint8)
        c = (u @ g) % 2
        assert not ((h @ c) % 2).any(), "H @ c != 0 - the fixture is wrong"
    # And it must be able to fail: flip one bit and the syndrome must light up.
    c = (rng.integers(0, 2, size=g.shape[0], dtype=np.uint8) @ g) % 2
    c[0] ^= 1
    assert ((h @ c) % 2).any(), \
        "a corrupted codeword passed the syndrome - H is degenerate"


@pytest.mark.skipif(
    "ldpc" not in CODES,
    reason="no LDPC plug-in is registered. Block E of the 7 Sep row is OPEN, "
           "not done: pipeline/s5_decode/ is Nehal's and the file is a request "
           "at the sync. Spec and acceptance criteria in "
           "reports/s3_ldpc_design.md; this test wakes up the moment "
           "register_code() runs for it.")
def test_the_supplied_h_decodes_through_the_registry():
    """Block E's acceptance criterion, written as an assertion so that landing
    the plug-in is what closes the block rather than somebody saying it is.

    Reached by name through `CODES`, never by import - the same rule the rest
    of the registry tests follow, so that adding a code stays one file and one
    registration line.
    """
    h, g = supplied_h()
    plugin = CODES["ldpc"]
    assert plugin.blind_recover(np.zeros(64)) is None, \
        "blind recovery of H is out of scope; it must return None, not a guess"

    rng = np.random.default_rng(5)
    u = rng.integers(0, 2, size=g.shape[0], dtype=np.uint8)
    c = (u @ g) % 2
    # Project convention: positive LLR means bit 0.
    llrs = np.where(c == 0, 4.0, -4.0)
    out = np.asarray(plugin.decode(llrs, {"H": h, "max_iter": 50}))
    assert np.array_equal(out[:u.size], u), \
        "clean LLRs did not decode to the information bits"
    flipped = np.asarray(plugin.decode(-llrs, {"H": h, "max_iter": 50}))
    assert not np.array_equal(flipped[:u.size], u), \
        "negating every LLR changed nothing - the sign convention is not wired"
