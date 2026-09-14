"""What an LDPC decoder needs from S3, pinned. Owner: Anvith.

7 September, day-clock blocks C and E. Design and the measurements behind it:
`reports/s3_ldpc_design.md`. The plug-in is `pipeline/s5_decode/ldpc_code.py`,
beside `conv_code.py` and `rs_code.py` where a CODES plug-in belongs. It spent
an afternoon in `pipeline/s3_receive/` first, because that folder is Nehal's
and a file in someone else's directory is a request at the sync and not an
edit; it moved once that was agreed.

Three things are pinned here. The first two are properties of S3's output that
an LDPC decode path depends on and that nothing before it has needed - Viterbi,
Reed-Solomon and S4 are indifferent to both:

  1. `llr_start_bit` - where the emitted stream begins inside the transmitted
     one. Viterbi, Reed-Solomon and S4 are all indifferent to this (S4's
     per-file label JSON has carried `start_offset` since 29 August), so it
     was never reported until today. A block code decoded against a supplied
     parity-check matrix is not indifferent: a codeword has a first bit.

  2. The LLR magnitudes are worth what they claim. Viterbi maximises a SUM of
     LLRs and is invariant to scaling them; sum-product belief propagation
     combines them through `tanh` and is not. So BP is the first consumer in
     this project whose answer depends on the magnitudes being right.

The third is block E itself: a codeword built from a supplied H, pushed through
the zoo's channel and S3, decoding back to the source bits at an SNR where the
raw stream does NOT - plus the alignment window, the sign convention, and
`blind_recover` refusing to guess.

The corpus tests here are skipped when `zoo/corpus/rf/` is absent, like the
rest of the S3 corpus tests. The block E tests build their own signal and do
not need it.
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

# Code plug-ins register on EXPLICIT import - by design, so that nothing pays
# for a decoder it never asks for, and so `pipeline/s5_decode/__init__.py` can
# stay empty. This is the ONE line in the test suite that knows where the file
# lives; everything below reaches it through `CODES`.
import pipeline.s5_decode.ldpc_code  # noqa: E402,F401  (registers LDPCCode)
from tests.fixtures.corpus import synth  # noqa: E402

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

# --- 3. the supplied H, and the decode path built on it ---------------------
#
# Block C and block E of the 7 Sep row. The plug-in is
# `pipeline/s5_decode/ldpc_code.py`, beside `conv_code.py` and `rs_code.py`.
# Every test below reaches it by NAME through `CODES["ldpc"]` and never by
# import, which is the same rule the registry tests follow: adding, moving or
# replacing a code plug-in stays one file and one registration line.


def supplied_h(k: int = 8, m: int = 4, seed: int = 11):
    """A tiny systematic parity-check matrix and its generator.

    H = [P | I_m] and G = [I_k | P^T] over GF(2), so `H @ (u @ G) == 0` for
    every information vector `u`. Systematic and tiny on purpose: this
    fixture's job is to be obviously a valid H, not to be a good code. The
    code that actually has to correct errors is `ira_code` below.
    """
    rng = np.random.default_rng(seed)
    n = k + m
    p = rng.integers(0, 2, size=(m, k), dtype=np.uint8)
    h = np.concatenate([p, np.eye(m, dtype=np.uint8)], axis=1)
    g = np.concatenate([np.eye(k, dtype=np.uint8), p.T], axis=1)
    assert h.shape == (m, n) and g.shape == (k, n)
    return h, g


def ira_code(k: int = 256, m: int = 256, col_weight: int = 3, seed: int = 11):
    """A rate-1/2 LDPC code that actually corrects errors, and its encoder.

    `H = [P | T]` with `T` lower bidiagonal - the IRA / DVB-S2 staircase. Two
    reasons for that shape rather than `[P | I]`:

      * **Encoding needs no Gaussian elimination.** `T p = P u` unrolls to
        `p_i = s_i XOR p_{i-1}`, a cumulative XOR, so this file carries no
        GF(2) solver whose own bugs could be mistaken for decoder bugs.
      * **`[P | I]` gives every parity bit a column weight of one.** A
        degree-1 variable node contributes nothing back to the graph, and a
        code built that way decodes far worse for a reason that has nothing to
        do with the decoder under test. The staircase makes them degree 2.

    Measured on this code (reports/s3_ldpc_design.md): a 6.5% raw bit error
    rate over AWGN goes to exactly zero.
    """
    rng = np.random.default_rng(seed)
    p = np.zeros((m, k), dtype=np.uint8)
    for c in range(k):
        p[rng.choice(m, size=col_weight, replace=False), c] = 1
    t = np.eye(m, dtype=np.uint8)
    t[np.arange(1, m), np.arange(0, m - 1)] = 1
    return np.concatenate([p, t], axis=1), p


def ira_encode(u: np.ndarray, p: np.ndarray) -> np.ndarray:
    """`[u | cumulative XOR of P u]` - the systematic codeword for `ira_code`."""
    s = (p @ np.asarray(u, dtype=np.uint8)) % 2
    return np.concatenate([np.asarray(u, dtype=np.uint8),
                           np.bitwise_xor.accumulate(s.astype(np.uint8))])


def _ldpc_stream(snr_db: float, n_words: int = 12, seed: int = 7):
    """Codewords -> the zoo's channel -> S3 -> (llrs, values, raw BER, ...).

    One helper because every end-to-end test below needs the same six steps and
    a copy of them in each is six places for the alignment to drift.
    """
    h, p = ira_code()
    m, n = h.shape
    k = n - m
    rng = np.random.default_rng(seed)
    words = [rng.integers(0, 2, k).astype(np.uint8) for _ in range(n_words)]
    tx_info = np.concatenate(words)
    tx = np.concatenate([ira_encode(u, p) for u in words])

    x, fs, rs, _ = synth("qpsk", bits=tx, snr_db=snr_db, sps=4,
                         cfo_norm=0.0008, timing_offset_sym=0.31, seed=5)
    res = MODULATIONS["qpsk"].receive(x, {"fs": fs, "symbol_rate": rs})
    picked = _best_rotation(res, tx)
    assert picked is not None, f"S3 emitted no LLRs at {snr_db} dB: {res.reason}"
    raw_ber, llrs, _, inverted = picked
    if inverted:
        # A rotation that flips every bit carries the same information and S4
        # recovers from it identically, but a decoder handed it decodes the
        # complement. Resolving it is S4's job, not this file's; here it is
        # simply undone so the test is about the decoder.
        llrs = -llrs
    return h, k, n, tx_info, res, llrs, raw_ber


def _aligned_params(res, n: int, **extra) -> dict:
    """The offset window an LDPC decoder gets from `llr_start_bit`.

    `llr_start_bit` is a LOWER bound - never an over-estimate - so the first
    codeword boundary computed from it lands at or after the real one, and the
    search runs backwards from there by the tolerance. See
    `LDPCCode._pick_offset`.
    """
    start = int(res.values["llr_start_bit"])
    tol = int(res.values["llr_start_bit_tolerance"])
    first = -(-start // n) * n              # round `start` up to a multiple of n
    return {"offset": first - start - tol, "search_offsets": tol,
            "first_codeword": first, **extra}


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


def test_the_ira_fixture_encodes_to_its_own_parity_check_matrix():
    """The same check for the code that has to do real work.

    The staircase encoder is a recursion rather than a matrix product, so it
    is exactly the kind of thing that can be subtly wrong and still produce
    plausible-looking bits.
    """
    h, p = ira_code()
    rng = np.random.default_rng(4)
    for _ in range(5):
        u = rng.integers(0, 2, p.shape[1]).astype(np.uint8)
        c = ira_encode(u, p)
        assert c.size == h.shape[1]
        assert not ((h @ c) % 2).any(), "IRA encoder does not satisfy its H"
        assert np.array_equal(c[:u.size], u), "the code is not systematic"


def test_the_ldpc_plugin_is_registered_by_name():
    """Reached through `CODES`, never by import - the rule that keeps adding a
    code to one file and one registration line. `test_registry_contract`
    already proves the registry works; this proves this plug-in is in it."""
    assert "ldpc" in CODES, \
        f"registered codes are {sorted(CODES)} - ldpc_code.py did not register"
    assert CODES["ldpc"].name == "ldpc"


def test_blind_recovery_of_h_returns_none_rather_than_a_guess():
    """The one behaviour the Command Center specifies by exclusion.

    OPEN-SET blind LDPC parity-check recovery is on its *do not build, ever,
    this sprint* list on research grounds. A `blind_recover` that returned a
    plausible-looking H it had not recovered would be the confidently-wrong
    answer this whole project is built to avoid.

    Since 13 Sep `blind_recover` does return parameters - but only for a
    closed-set catalogue match (tests/unit/test_ldpc_blind.py). None of these
    streams is a catalogue codeword stream, so `None` is still the only
    correct output: a degenerate stream, Gaussian noise, and a ramp too short
    to score.
    """
    rng = np.random.default_rng(9)
    for stream in (np.zeros(4096), rng.normal(0, 4, 4096), np.arange(64.0)):
        assert CODES["ldpc"].blind_recover(stream) is None


def test_a_parity_check_matrix_must_be_supplied_exactly_once():
    """None, and more than one, are both errors rather than defaults.

    Two H's that disagree would decode to a wrong answer with nothing to
    report it, and picking "the first one found" is how that happens quietly.
    """
    ldpc = CODES["ldpc"]
    llrs = np.zeros(64)
    with pytest.raises(ValueError, match="no parity-check matrix"):
        ldpc.decode(llrs, {})
    h, _ = supplied_h()
    with pytest.raises(ValueError, match="supplied 2 ways"):
        ldpc.decode(llrs, {"H": h, "H_rows": [[0, 1]]})


def test_the_three_ways_of_supplying_h_agree():
    """Dense, sparse rows and a MacKay alist describe the same matrix.

    The alist is here because it is the format published matrices ship in, and
    a parser that is never exercised is a parser that is wrong.
    """
    from pipeline.s5_decode.ldpc_code import parity_check_from_params

    h, _ = supplied_h()
    m, n = h.shape
    rows = [list(np.flatnonzero(r)) for r in h]
    cols = [list(np.flatnonzero(c) + 1) for c in h.T]      # alist is 1-based
    max_col = max(len(c) for c in cols)
    max_row = max(len(r) for r in rows)
    alist = "\n".join(
        [f"{n} {m}", f"{max_col} {max_row}",
         " ".join(str(len(c)) for c in cols),
         " ".join(str(len(r)) for r in rows)]
        + [" ".join(str(i) for i in c + [0] * (max_col - len(c))) for c in cols]
        + [" ".join(str(i + 1) for i in r) for r in rows])

    from_dense = parity_check_from_params({"H": h})
    from_rows = parity_check_from_params({"H_rows": rows, "n": n})
    from_alist = parity_check_from_params({"H_alist": alist})
    assert np.array_equal(from_dense, h)
    assert np.array_equal(from_rows, h), "sparse rows disagree with dense"
    assert np.array_equal(from_alist, h), "alist disagrees with dense"


@pytest.mark.parametrize("algorithm", ["min-sum", "sum-product"])
def test_the_decoder_corrects_errors_it_is_given(algorithm):
    """Over a plain AWGN channel, with no receiver in the way.

    Isolated from S3 on purpose. If this and the end-to-end test below fail
    together, the fault is here; if only the end-to-end one fails, it is in the
    junction. Two tests that can only fail together would not separate them.

    5% of bits wrong going in, zero coming out, on both algorithms.
    """
    h, p = ira_code()
    m, n = h.shape
    k = n - m
    rng = np.random.default_rng(3)
    words = [rng.integers(0, 2, k).astype(np.uint8) for _ in range(4)]
    tx = np.concatenate([ira_encode(u, p) for u in words])

    sigma = 0.605                     # about a 5% raw bit error rate on BPSK
    y = (1.0 - 2.0 * tx.astype(float)) + sigma * rng.standard_normal(tx.size)
    llrs = 2.0 * y / sigma ** 2       # log P(0)/P(1), the project convention

    raw = float(((llrs < 0).astype(np.uint8) != tx).mean())
    assert 0.02 < raw < 0.10, (
        f"raw error rate {raw:.3f} is outside the band this test is about - "
        f"too clean proves nothing, too noisy is a different experiment")

    out = CODES["ldpc"].decode(llrs, {"H": h, "algorithm": algorithm})
    want = np.concatenate(words)
    assert np.array_equal(out[:want.size], want[:out.size]), (
        f"{algorithm}: {int((out[:want.size] != want[:out.size]).sum())} of "
        f"{want.size} source bits wrong after decoding a {raw:.1%} raw stream")


def test_the_syndrome_report_says_when_the_decoder_did_not_converge():
    """House rule: a check that cannot see must say so.

    `syndrome` is the one check in the plug-in that needs no reference bits, so
    it is the one a blind receiver can run on its own output - which makes it
    worth proving that it reports failure rather than only success.
    """
    h, p = ira_code()
    k = h.shape[1] - h.shape[0]
    rng = np.random.default_rng(5)
    tx = ira_encode(rng.integers(0, 2, k).astype(np.uint8), p)

    clean = np.where(tx == 0, 6.0, -6.0)
    good = CODES["ldpc"].syndrome(clean, {"H": h})
    assert good["blocks_converged"] == good["blocks"] == 1
    assert good["syndrome_weights"] == [0]

    noise = rng.normal(0.0, 1.0, tx.size)
    bad = CODES["ldpc"].syndrome(noise, {"H": h})
    assert bad["blocks_converged"] == 0, \
        "pure noise converged to a codeword - the syndrome is not being checked"
    assert bad["syndrome_weights"][0] > 0


def test_validate_catches_a_decoder_that_locked_onto_nothing():
    """Weak by design and the same shape as `ConvCode.validate` - it catches
    the degenerate cases and claims nothing more."""
    ldpc = CODES["ldpc"]
    assert ldpc.validate(np.array([], dtype=np.uint8))["ok"] is False
    assert ldpc.validate(np.zeros(1000, dtype=np.uint8))["ok"] is False
    assert ldpc.validate(np.ones(1000, dtype=np.uint8))["ok"] is False
    mixed = np.random.default_rng(1).integers(0, 2, 1000).astype(np.uint8)
    assert ldpc.validate(mixed)["ok"] is True


# --- block E: the four things "LDPC decodes with the supplied H" must show ---

_E2E_SNR_DB = 2.0
"""The SNR the end-to-end test runs at.

Chosen so the raw stream is NOT already correct: measured over this code and
this channel, S3 returns `ok` with a raw bit error rate of 0.0091, and the
decode has to remove those errors rather than inherit a clean stream. At 5 dB
and above the raw stream is already exact and the test would demonstrate only
that the plumbing runs.

The other end, measured: the decode still clears a 6.0% raw rate at -1 dB,
where S3 has dropped to `low_confidence`, and at -2 dB S3 returns `failed`
with no LLRs at all. So on this code the binding limit is the receiver rather
than the decoder.
"""


def test_the_supplied_h_decodes_a_stream_the_raw_bits_get_wrong():
    """Block E, criterion 1 - and the only one that makes the block worth
    having. A decode that succeeds where the raw stream was already exact has
    demonstrated that the plumbing runs and nothing else.
    """
    h, k, n, tx_info, res, llrs, raw_ber = _ldpc_stream(_E2E_SNR_DB)
    assert res.status == "ok", res.reason
    assert raw_ber > 0.0, (
        f"the raw stream at {_E2E_SNR_DB} dB is already exact, so this test "
        f"cannot show the code correcting anything - lower the SNR")

    params = _aligned_params(res, n, H=h)
    first = params.pop("first_codeword")
    out = CODES["ldpc"].decode(llrs, params)
    want = tx_info[(first // n) * k:][:out.size]
    n_cmp = min(out.size, want.size)
    assert n_cmp >= k, "fewer than one full codeword survived the prefix"
    wrong = int((out[:n_cmp] != want[:n_cmp]).sum())
    assert wrong == 0, (
        f"{wrong} of {n_cmp} source bits wrong after LDPC decoding a stream "
        f"whose raw bit error rate was {raw_ber:.4f}")


def test_the_decoder_finds_its_alignment_inside_the_promised_window():
    """Block E, criterion 2.

    S3 cannot report an exact start - `llr_start_bit` carries a one-symbol
    tolerance - so the decoder searches. What makes that search short rather
    than the length of the stream is the DIRECTION: the reported value is
    never an over-estimate, so the boundary computed from it lands at or after
    the real one and the search runs backwards by the tolerance. This asserts
    the window is both sufficient and small.
    """
    h, k, n, _, res, llrs, _ = _ldpc_stream(_E2E_SNR_DB)
    params = _aligned_params(res, n, H=h)
    params.pop("first_codeword")
    tol = int(res.values["llr_start_bit_tolerance"])
    assert params["search_offsets"] == tol <= 4, \
        "the search window should be one symbol, at most four bits"

    rep = CODES["ldpc"].syndrome(llrs, params)
    assert rep["blocks_converged"] == rep["blocks"] > 0, (
        f"only {rep['blocks_converged']} of {rep['blocks']} blocks reached a "
        f"zero syndrome from offset {rep['offset']}; the window "
        f"[{params['offset']}, {params['offset'] + tol}] did not contain the "
        f"codeword boundary")
    assert params["offset"] <= rep["offset"] <= params["offset"] + tol


def test_a_negated_stream_does_not_decode():
    """Block E, criterion 3, and the reason it is a separate test.

    Project LLRs are `log(P(0)/P(1))` and textbook belief propagation is
    written in the same convention, so this plug-in needs no negation where
    `conv_code.py` needs one for commpy. "It happens to match" is true until
    somebody swaps a library, and getting it backwards decodes to noise
    without raising anything. A test that passed either way would be testing
    that the code runs.
    """
    h, k, n, tx_info, res, llrs, _ = _ldpc_stream(_E2E_SNR_DB)
    params = _aligned_params(res, n, H=h)
    first = params.pop("first_codeword")

    rep = CODES["ldpc"].syndrome(-llrs, params)
    assert rep["blocks_converged"] == 0, (
        f"{rep['blocks_converged']} of {rep['blocks']} blocks converged on a "
        f"NEGATED stream. The sign convention is not wired to anything.")

    out = CODES["ldpc"].decode(-llrs, params)
    want = tx_info[(first // n) * k:][:out.size]
    n_cmp = min(out.size, want.size)
    ber = float((out[:n_cmp] != want[:n_cmp]).mean())
    assert ber > 0.3, \
        f"negating every LLR left the output {1 - ber:.1%} correct"
