"""LDPCCode - belief propagation against a SUPPLIED parity-check matrix.

7 September, day-clock block C. Design, and the two measurements it rests on:
`reports/s3_ldpc_design.md`.

WHO WROTE THIS AND WHY IT IS IN THIS DIRECTORY
----------------------------------------------
NEHAL - this is your folder and this file is not yours. Written by the S3
owner because the LDPC decode path is on his row of the 7 September day clock,
and landed here with agreement rather than dropped in: a `CODES` plug-in
belongs beside `conv_code.py` and `rs_code.py`, not inside the receiver stage.
It spent an afternoon in `pipeline/s3_receive/` for exactly that reason - a
file in someone else's directory is a request at the sync and never an edit,
which is what has kept four people on one pipeline at near-zero merge
conflicts all week.

It was written to be easy to take over, and those properties are worth keeping:

  * it imports NOTHING from `pipeline.s3_receive` - only numpy and the registry,
  * it touches no existing file: `pipeline/s5_decode/__init__.py` is empty and
    stays empty, because code plug-ins register on EXPLICIT import,
  * every test reaches it by name through `CODES["ldpc"]`, never by import,
    so moving or replacing it costs one line.

Rewrite it, rename it or throw it away - nothing outside its own tests depends
on its internals.

WHY AN LDPC DECODER IS THE FIRST THING HERE THAT CARES ABOUT LLR MAGNITUDES
---------------------------------------------------------------------------
Every other consumer of S3's soft output is indifferent to the SCALE of an
LLR. Viterbi maximises a sum of them, so multiplying every value by a positive
constant leaves the arg-max unchanged. Reed-Solomon sees only `llr < 0`. S4's
rank collapse hard-slices by construction.

Sum-product belief propagation is not indifferent: a check node combines its
inputs through `tanh(L/2)`, which is neither linear nor scale-free. That is
why `reports/s3_llr_calibration.md` exists and why it had to be measured
before this file could be written. What it found:

    files S3 returns `ok` on      worst per-bin ratio 1.62x   usable
    files S3 refuses              worst per-bin ratio 81.7x   not usable

Hence two decisions that are measurements rather than preferences:

  1. **The default algorithm is normalised min-sum, not sum-product.** The
     min-sum check update is positively homogeneous - scale every input by one
     positive constant and the hard decisions do not move - so it is immune to
     the scale half of a calibration error. It is NOT immune to a shape error,
     and saying otherwise would be the overclaim; what makes it safe here is
     that the measured shape error inside the `ok` population is small.
  2. **A caller should decode `status == "ok"` streams only.** On a refused
     stream this demodulator emits magnitudes of 4 to 8 - promising about 0.4%
     error - over bits that are wrong 29% and 39% of the time. Those are the
     inputs that make BP settle on a wrong codeword and stop. This file cannot
     enforce that, because it never sees an `S3Result`; the caller must.

OPEN-SET RECOVERY OF H IS OUT OF SCOPE; CLOSED-SET IDENTIFICATION IS NOT
-----------------------------------------------------------------------
The Command Center puts "blind LDPC parity-check recovery" on the *Do not
build, ever, this sprint* list, on research grounds: recovering an unknown H
from a noisy stream has no reliable published method at the error rates a real
receiver produces. That still holds, and nothing here attempts it - returning a
plausible-looking H that was not recovered is the confidently-wrong failure
this repo has been bitten by repeatedly.

Until 13 Sep `blind_recover` therefore returned `None` unconditionally, which
also refused a different and tractable problem: deciding WHICH known code, out
of a finite catalogue, a stream uses. It now does that, by syndrome density on
the hard decisions, and returns None when no catalogue entry clears the
threshold and the runner-up margin. The method, the thresholds and their
measured populations are in `ldpc_catalogue.py` and reports/blind_ldpc.md.

THE SIGN CONVENTION IS THE SAME AS THE PROJECT'S, WHICH IS WHY IT IS PINNED
---------------------------------------------------------------------------
Project LLRs are `log(P(bit == 0) / P(bit == 1))`, so positive means bit 0 and
the hard decision is `llr < 0`. Textbook BP is written in exactly that
convention, so - unlike `conv_code.py`, which has to negate for commpy - there
is no conversion here. "It happens to match" is true until somebody swaps a
library, and getting it backwards decodes to noise and raises nothing, so
`test_a_negated_stream_does_not_decode` asserts it rather than trusting it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from registry import register_code

__all__ = ["LDPCCode", "parity_check_from_params", "read_alist"]

MAX_ITER = 50
"""Default iteration cap.

Belief propagation on the codes this project is likely to be handed converges
in well under 20 iterations when it converges at all, and a run that has not
found a codeword by 50 is not going to. The cap is a bound on wasted work
rather than a tuned parameter, and the decoder stops the moment the syndrome
is zero regardless.
"""

MIN_SUM_NORMALISATION = 0.75
"""Scale applied to the min-sum check-node output.

Min-sum overestimates the magnitude of a check message, because it keeps only
the smallest incoming magnitude and ignores how the rest would have attenuated
it. Multiplying by a constant under 1 corrects most of that bias; 0.7-0.8 is
the range the literature settles on and 0.75 is its middle. It is NOT tuned on
this project's corpus - there is no corpus of LDPC-coded captures here to tune
it on, and a constant chosen on one arm is exactly what §10 of the working
notes records being punished for twice. Stated as an inherited default, and
overridable with `params["normalisation"]`.
"""

_LLR_CLIP = 40.0
"""Messages are clipped to this magnitude.

1/(1+exp(40)) is 4e-18, so nothing is lost by refusing to represent a bit as
more certain than that, and it keeps `exp` and `tanh` away from the ends of
their range where the arithmetic stops being informative. `softmap` clips its
emitted LLRs at 200 for a different reason - to keep the array finite - and
this is deliberately tighter because these values are fed back through
`arctanh`.
"""


def llr_to_bits(llrs) -> np.ndarray:
    """Hard decision under the project convention: positive LLR means bit 0.

    Accepts an already-hard 0/1 array too, matching `conv_code.llr_to_bits` so
    both sides of the junction slice a stream identically. The tolerance is a
    convenience and not a licence: a hard stream carries no soft information,
    and belief propagation on hard input is a much weaker decoder.
    """
    arr = np.asarray(llrs)
    if arr.dtype == np.uint8 or (arr.dtype.kind in "iu"
                                 and np.isin(arr, (0, 1)).all()):
        return arr.astype(np.uint8).ravel()
    return (arr.ravel() < 0).astype(np.uint8)


MIN_ID_BLOCKS = 6
"""Codeword blocks the identifier insists on before it will name a code.

The z statistic is sqrt(N)*(1-2*p_hat) over N = m*blocks checks, so fewer blocks
means a smaller N and a noisier estimate of p_hat. Six is where the WEAKEST
catalogue entry (n=48, m=24, so N=144) still separates decisively. A capture too
short for an entry is SKIPPED rather than scored on what it has: scoring it would
let the shortest code in the catalogue win every short capture on nothing but
having fitted.
"""

ID_Z_MIN = 8.0
"""How far below coin-flipping the failed-check rate must sit.

Under the wrong-code null each check fails independently with probability 1/2,
so the failure count is Binomial(N, 1/2) and z is standard normal - on which
reading 8 sigma is a one-sided p of 6e-16.

THAT READING IS WRONG AND QUOTING IT WOULD BE THE OVERCLAIM. The offset search
returns the MINIMUM density over all n alignments, so the reported z is a
maximum of n correlated draws, not one draw. The null is therefore shifted
upward by an order statistic and the nominal tail probability does not apply.
Measured instead of assumed - 200 random streams against the catalogue's
weakest entry (n=48, N=144 checks, so 48 offsets each):

    mean z  +2.24     p99  +3.50     max  +3.67     over threshold  0 of 200

So the empirical null tops out near +3.7 where the nominal model says +0. That is
the number this threshold is set against, and it is why the threshold is not
3 sigma.

The other side of the gap, measured over the whole shipped catalogue at
MIN_ID_BLOCKS blocks:

    weakest true code   n=48    z = +12.0
    strongest           n=1440  z = +65.7
    worst WRONG-code z anywhere in the catalogue, after the 13 Sep
      construction fix in ldpc_catalogue.regular_ldpc      z = +3.0

8.0 sits between +3.7 and +12.0. It is deliberately NOT tuned to the middle: the
true-code side scales as sqrt(N) and only grows with capture length, while the
null side is bounded by the order statistic, so the safe place for the threshold
is nearer the null. `ID_RUNNER_UP_RATIO` is what actually protects against a
catalogue containing two RELATED codes, which is the case a fixed threshold
cannot see - see its docstring for the +7.54 that found it.
"""

ID_RUNNER_UP_RATIO = 2.0
"""The winner's z must beat the runner-up's by this factor.

A threshold alone answers "does this code fit?". It cannot answer "is this THE
code?", and those come apart the moment the catalogue holds two related
matrices - which a catalogue grown by adding block lengths of one construction
certainly will, and which the standards do too, since one 802.16e base matrix
generates every rate.

Found by measurement rather than foresight. Before the construction fix in
`ldpc_catalogue.regular_ldpc`, the reference entries all shared an identity
block row, so a genuine n=192 codeword stream scored

    z = +24.0  against its own H          <- correct
    z =  +7.54 against the WRONG n=96 H   <- 0.46 below a threshold of 8.0

The construction no longer nests, which removes THAT instance. This ratio
removes the class: a wrong entry that genuinely fits half the stream's checks
scores at most ~sqrt(N/2) against the true entry's sqrt(N), a factor of 1.41, so
2.0 rejects it while leaving real matches - which beat their runner-up by 6.3x
to 24.2x across the shipped catalogue (reports/blind_ldpc_study.py) -
untouched. tests/unit/test_ldpc_blind.py builds the related-entry case (H and
half of H's rows) and asserts it is refused.

A single-entry catalogue has no runner-up and the ratio does not apply. That is
correct and not a hole: with one candidate there is no "which", only "does it
fit", and ID_Z_MIN is the whole of that question.
"""

ID_DENSITY_MAX = 0.25
"""Ceiling on the observed failed-check fraction, applied WITH z, not instead.

z grows as sqrt(N), so a long enough capture makes an arbitrarily feeble bias
look arbitrarily significant - the same trap `STAT_FALLBACK_MAX_IMPLIED_BER`
guards in rank_collapse, where a source with P(1)=0.7 made every parity check
"significant" and got reported as a code. A real match is near zero: the true
code's density is (1-(1-2*eps)^w)/2, which is 0.057 at 1% BER with row weight 6
and 0.22 at the 5% BER where BP has no chance anyway. So 0.25 admits every error
rate this decoder could act on and excludes every faint correlation.
"""

_ID_SCREEN_ROWS = 48
"""H rows used in the offset screen before the full check.

The screen is a matmul over every offset, so its cost is n_offsets * blocks * n
* rows. Using all 720 rows of the n=1440 entry is 1440*6*1440*720 = 9e9 MACs;
48 rows is 6e8, and 48 rows over 6 blocks is still 288 independent checks -
enough that the true offset's screen score is unmistakable. The full matrix then
decides among the few offsets the screen kept, so a screen that ranks imperfectly
costs nothing as long as it ranks the true offset into the top few.
"""

_ID_SCREEN_KEEP = 4
"""Offsets carried from the screen into the full-H check.

One would be enough if the screen were exact. It is not - it sees a subset of the
rows - so the true offset can be ranked second or third by a subset that happens
to be satisfied by a near miss. Measured across the catalogue the true offset
lands at screen rank 1 every time, so 4 is three ranks of margin rather than a
tuned value.
"""


def _degenerate_reason(bits):
    """Why this stream must not be identified at all, or None.

    Reads the BITS. Every linear code contains the zero word, so an all-zero
    stream satisfies every check of every H at every offset and ties the whole
    catalogue at a perfect score - a false positive no margin test between
    candidates can reject, because the candidates do not disagree. The same
    holds weakly for any near-constant or exactly periodic stream.

    This is the LDPC twin of `rank_collapse.exact_repetition_period`, and it is
    here - at the entry to identification - for the reason that file records: a
    guard that lives inside one branch is not a guarantee.
    """
    arr = np.asarray(bits, dtype=np.uint8).ravel()
    if arr.size < 8:
        return "only %d bits" % arr.size
    ones = float(arr.mean())
    if ones < 0.02 or ones > 0.98:
        return ("stream is %.1f%% ones - near-constant, and the zero word is a "
                "codeword of every linear code, so it would match the entire "
                "catalogue at once" % (100.0 * ones))
    # Exact periodicity, bounded. A stream that repeats carries no information
    # and any code found in it is an artifact of the repetition.
    for period in range(1, min(512, arr.size // 4) + 1):
        if np.array_equal(arr[:arr.size - period], arr[period:]):
            return ("stream repeats exactly every %d bits, so it carries no "
                    "information" % period)
    return None


def _syndrome_z(density, n_checks):
    """Standard deviations below coin-flipping. See ID_Z_MIN.

    Under the wrong-code null each check fails with probability 1/2 independ-
    ently, so the failure count is Binomial(n_checks, 1/2), mean 0.5*n and sd
    0.5*sqrt(n). z = (0.5 - density) / (0.5/sqrt(n)) = sqrt(n)*(1 - 2*density).
    """
    if n_checks <= 0:
        return 0.0
    return float(np.sqrt(n_checks) * (1.0 - 2.0 * float(density)))


def _syndrome_density(blocks, h):
    """Fraction of parity checks these blocks fail.

    float32 matmul then mod 2, rather than an integer matmul: numpy's integer
    matmul is not BLAS-backed and is far slower here, and every partial sum is
    bounded by the maximum row weight of H (15 in the shipped catalogue) so it
    is exactly representable. A row weight past 2^24 would break that, and no
    LDPC code has one.
    """
    blocks = np.asarray(blocks)
    if blocks.size == 0:
        return 1.0
    syn = (blocks.astype(np.float32) @ h.T.astype(np.float32)).astype(np.int64) & 1
    return float(syn.mean())


def _best_offset_by_syndrome(bits, h, min_blocks):
    """(offset, density, n_checks) for the codeword alignment that fits best.

    Two passes, because one would be either wrong or slow. The screen scores
    every one of the n possible offsets against a subset of H's rows in a single
    matmul; the full matrix then re-scores only `_ID_SCREEN_KEEP` of them. See
    `_ID_SCREEN_ROWS` for the cost arithmetic.

    Only offsets in [0, n) are considered, and that is exhaustive rather than a
    bound: codeword boundaries repeat every n bits, so offset n is offset 0 one
    block later and carries no new hypothesis.
    """
    m, n = h.shape
    if bits.size // n < min_blocks:
        return None, 1.0, 0
    blocks = min(bits.size // n, min_blocks)

    # Every offset's block set, built once. Offset o needs bits[o : o+blocks*n],
    # so the last offset needs (n-1) + blocks*n bits; a capture that cannot
    # supply that gets one fewer block rather than a truncated final row.
    need = (n - 1) + blocks * n
    if bits.size < need:
        blocks = (bits.size - (n - 1)) // n
        if blocks < 1:
            return None, 1.0, 0
        need = (n - 1) + blocks * n
    window = bits[:need]
    idx = np.arange(blocks * n)[None, :] + np.arange(n)[:, None]
    stacked = window[idx].reshape(n * blocks, n)          # (offset*block, n)

    rows = min(_ID_SCREEN_ROWS, m)
    h_screen = h[:rows]
    syn = (stacked.astype(np.float32) @ h_screen.T.astype(np.float32)
           ).astype(np.int64) & 1
    per_offset = syn.reshape(n, blocks * rows).mean(axis=1)
    keep = np.argsort(per_offset)[:_ID_SCREEN_KEEP]

    best_off, best_density = None, 1.0
    for off in keep:
        off = int(off)
        b = stacked[off * blocks:(off + 1) * blocks]
        d = _syndrome_density(b, h)
        if best_off is None or d < best_density:
            best_off, best_density = off, d
    return best_off, best_density, blocks * m


def read_alist(source) -> np.ndarray:
    """MacKay alist -> dense parity-check matrix.

    The interchange format most published matrices ship in. Layout:

        n m                      columns, rows
        max_col_weight max_row_weight
        <n column weights>
        <m row weights>
        <n lines: 1-based row indices of the ones in that column, zero padded>
        <m lines: 1-based column indices of the ones in that row>

    Only the column section is read; the row section is redundant with it, and
    a file where the two disagree is a broken file rather than a choice to be
    made. `source` is a path or the text itself.
    """
    text = source
    if isinstance(source, (str, Path)):
        p = Path(source)
        if p.suffix or p.exists():
            text = p.read_text(encoding="utf-8")
    lines = [ln.split() for ln in str(text).splitlines() if ln.strip()]
    if len(lines) < 4:
        raise ValueError("alist too short to carry a header")
    n, m = int(lines[0][0]), int(lines[0][1])
    if len(lines) < 4 + n:
        raise ValueError(
            f"alist header says {n} columns but the file carries "
            f"{len(lines) - 4} column lines")

    h = np.zeros((m, n), dtype=np.uint8)
    for col, entries in enumerate(lines[4:4 + n]):
        for e in entries:
            r = int(e)
            if r:                      # zero is the padding value, not a row
                h[r - 1, col] = 1
    return h


def parity_check_from_params(params: dict) -> np.ndarray:
    """The supplied H, from exactly one of the three accepted forms.

    Exactly one - not "the first one found". An H supplied twice by two routes
    is a caller bug, and if the two disagree then silently preferring one
    produces a decode that is wrong for a reason nothing reports. Raising here
    costs a caller one line and saves the failure that has no explanation.
    """
    given = [k for k in ("H", "H_rows", "H_alist") if params.get(k) is not None]
    if not given:
        raise ValueError(
            "no parity-check matrix supplied: pass exactly one of H (dense), "
            "H_rows (column indices per row) or H_alist (a MacKay alist path "
            "or its text). Recovering H from the stream is out of scope - see "
            "reports/s3_ldpc_design.md")
    if len(given) > 1:
        raise ValueError(
            f"parity-check matrix supplied {len(given)} ways at once: {given}. "
            "Pass exactly one; two that disagree would decode to a wrong "
            "answer with nothing to report it.")

    key = given[0]
    if key == "H":
        h = np.asarray(params["H"], dtype=np.uint8)
        if h.ndim != 2:
            raise ValueError(f"H must be 2-D, got shape {h.shape}")
    elif key == "H_rows":
        rows = list(params["H_rows"])
        width = params.get("n")
        if width is None:
            width = 1 + max((max(r) for r in rows if len(r)), default=-1)
        h = np.zeros((len(rows), int(width)), dtype=np.uint8)
        for i, cols in enumerate(rows):
            h[i, np.asarray(list(cols), dtype=int)] = 1
    else:
        h = read_alist(params["H_alist"])

    if not np.isin(h, (0, 1)).all():
        raise ValueError("H must be binary")
    if h.shape[0] >= h.shape[1]:
        raise ValueError(
            f"H is {h.shape[0]}x{h.shape[1]}: at least as many checks as "
            "bits leaves no information to carry")
    return h


def _check_update(e: np.ndarray, mask: np.ndarray, algorithm: str,
                  alpha: float) -> np.ndarray:
    """Check-node messages from variable-node messages, excluding self.

    Both branches compute the excluding-self combination without dividing by
    the term being excluded, which is the classic way this goes wrong: a single
    zero-magnitude message makes the row product zero and the division
    undefined for every edge in that row.
    """
    if algorithm == "min-sum":
        # sign(0) is 0 and would zero the whole row product, so a zero message
        # is treated as positive - it carries no sign information either way.
        sgn = np.where(mask, np.where(e >= 0.0, 1.0, -1.0), 1.0)
        row_sign = np.prod(sgn, axis=1, keepdims=True)
        excl_sign = row_sign * sgn          # dividing by +-1 IS multiplying

        mag = np.where(mask, np.abs(e), np.inf)
        j_min = np.argmin(mag, axis=1)
        rows = np.arange(mag.shape[0])
        min1 = mag[rows, j_min]
        second = mag.copy()
        second[rows, j_min] = np.inf
        min2 = np.min(second, axis=1)
        # every edge gets the row minimum, except the edge that IS the minimum,
        # which gets the runner-up
        is_min = np.zeros(mask.shape, dtype=bool)
        is_min[rows, j_min] = True
        excl_mag = np.where(is_min, min2[:, None], min1[:, None])
        excl_mag = np.where(np.isfinite(excl_mag), excl_mag, 0.0)
        out = alpha * excl_sign * excl_mag
    else:
        # sum-product, decomposed into sign and log-magnitude so the
        # excluding-self product is a subtraction and never a division
        t = np.where(mask, np.tanh(np.clip(e, -_LLR_CLIP, _LLR_CLIP) / 2.0), 1.0)
        sgn = np.where(t >= 0.0, 1.0, -1.0)
        mag = np.clip(np.abs(t), 1e-12, 1.0 - 1e-12)
        log_mag = np.log(mag)
        excl_log = np.sum(np.where(mask, log_mag, 0.0), axis=1, keepdims=True)
        excl_log = excl_log - np.where(mask, log_mag, 0.0)
        excl_sign = np.prod(sgn, axis=1, keepdims=True) * sgn
        prod = np.clip(excl_sign * np.exp(excl_log),
                       -1.0 + 1e-12, 1.0 - 1e-12)
        out = 2.0 * np.arctanh(prod)

    return np.where(mask, np.clip(out, -_LLR_CLIP, _LLR_CLIP), 0.0)


def _decode_block(channel_llr: np.ndarray, h: np.ndarray, mask: np.ndarray,
                  max_iter: int, algorithm: str, alpha: float
                  ) -> tuple[np.ndarray, int, int]:
    """One codeword. Returns (bits, syndrome weight, iterations run).

    Standard flooding schedule. The stopping rule is the syndrome and not the
    iteration count: a valid codeword is a valid codeword and further
    iterations cannot improve it.
    """
    l_ch = np.clip(np.asarray(channel_llr, dtype=np.float64),
                   -_LLR_CLIP, _LLR_CLIP)
    e = np.where(mask, l_ch[None, :], 0.0)

    bits = (l_ch < 0).astype(np.uint8)
    syndrome = int(((h @ bits) % 2).sum())
    if syndrome == 0:
        return bits, 0, 0

    for it in range(1, max_iter + 1):
        m = _check_update(e, mask, algorithm, alpha)
        total = np.clip(l_ch + m.sum(axis=0), -_LLR_CLIP, _LLR_CLIP)
        bits = (total < 0).astype(np.uint8)
        syndrome = int(((h @ bits) % 2).sum())
        if syndrome == 0:
            return bits, 0, it
        e = np.where(mask, total[None, :] - m, 0.0)

    return bits, syndrome, max_iter


class LDPCCode:
    """LDPC decoding against a supplied or catalogue-identified parity-check matrix."""

    name = "ldpc"
    detail = ("LDPC belief propagation (normalised min-sum or sum-product); "
              "blind identification against the registry/ldpc_catalogue "
              "closed set by syndrome density - open-set H recovery is out "
              "of scope")

    # -- CODES protocol -----------------------------------------------------

    def blind_recover(self, llrs, catalogue=None, min_blocks: int = MIN_ID_BLOCKS,
                      z_min: float = ID_Z_MIN, density_max: float = ID_DENSITY_MAX):
        """Which catalogue code this stream uses, and where its codewords start
        - or None.

        CLOSED-SET IDENTIFICATION, NOT OPEN-SET RECOVERY. The distinction is
        the whole of the 13 Sep change and it is not a softening of the earlier
        refusal:

          open-set   recover an ARBITRARY unknown H from a noisy stream. Still
                     out of scope, still refused, and nothing below attempts
                     it. There is no reliable published method at the error
                     rates a real receiver produces, and returning a
                     plausible-looking H we had not recovered remains the worst
                     available answer.

          closed-set decide which H out of a known finite list, and at which
                     bit offset. Decisive, measured, and implemented here.

        This is the same shape as two closed-set searches the project already
        trusts - the CCSDS symbol interleaver's six legal depths settled by
        whether RS decodes, and the LTE QPP coefficient table in
        `s4_recover/pseudorandom.py`. A downlink is overwhelmingly more likely
        to use a published code than a bespoke one, so "try the list" is not a
        weaker method, it is the method that fits the problem.

        The statistic is syndrome density on the HARD decisions - see
        `ldpc_catalogue` for the two populations and the measured separation.
        Belief propagation is deliberately not used to decide: BP against a
        wrong H converges to a wrong codeword and then reports a zero syndrome
        for it, which is exactly the confidently-wrong failure this file's own
        header warns about. Counting failed checks never changes a bit, so it
        cannot manufacture agreement.

        Returns a params mapping `decode` accepts as-is (it carries `H` and an
        exact `offset`), plus the evidence: `code_name`, `provenance`,
        `syndrome_density`, `z_score` and the runner-up's margin. None means no
        catalogue entry cleared the threshold, which is a real answer about a
        finite catalogue and not a claim about every LDPC code in existence.
        """
        bits = llr_to_bits(llrs)
        if bits.size == 0:
            return None

        # READS THE INPUT, not a score, and first. Every linear code contains
        # the zero word, so an all-zero stream scores a perfect syndrome
        # against the WHOLE catalogue at once - a tie at the ceiling that no
        # margin test between candidates can break, and a decode that is
        # genuinely correct for a codeword nobody transmitted. See
        # ldpc_catalogue's header.
        degenerate = _degenerate_reason(bits)
        if degenerate is not None:
            return None

        if catalogue is None:
            from .ldpc_catalogue import load_catalogue
            catalogue = load_catalogue()

        scored = []
        for entry in catalogue:
            n = entry.n
            if bits.size < min_blocks * n:
                continue                  # not enough bits to be decisive here
            offset, density, n_checks = _best_offset_by_syndrome(
                bits, entry.h, min_blocks)
            if offset is None:
                continue
            z = _syndrome_z(density, n_checks)
            scored.append((z, density, offset, n_checks, entry))

        if not scored:
            return None
        scored.sort(key=lambda t: -t[0])
        z, density, offset, n_checks, entry = scored[0]

        # Both conditions, not either. z alone scales with the number of checks,
        # so a long capture makes a feeble bias look significant; the density
        # ceiling is what says "this is a code seen through noise" rather than
        # "this is a faint correlation measured very precisely". Same reasoning
        # as STAT_FALLBACK_MAX_IMPLIED_BER in rank_collapse.
        if z < z_min or density > density_max:
            return None

        # THE MARGIN, not just the threshold. See ID_RUNNER_UP_RATIO: clearing
        # the threshold says a code fits, and only beating the runner-up says
        # which code it is. Applied after the threshold rather than instead of
        # it, because a catalogue of one has no runner-up and must still be
        # answerable.
        runner_up = scored[1][0] if len(scored) > 1 else None
        if (runner_up is not None and runner_up >= z_min
                and z < ID_RUNNER_UP_RATIO * runner_up):
            return None
        params = dict(entry.as_params())
        params.update({
            "offset": int(offset),
            "syndrome_density": float(density),
            "z_score": float(z),
            "checks_tested": int(n_checks),
            "blocks_tested": int(n_checks // entry.m) if entry.m else 0,
            "catalogue_size": len(catalogue),
            "runner_up_z": (float(runner_up) if runner_up is not None else None),
            "method": "closed-set catalogue identification by syndrome density",
        })
        return params

    def decode(self, llrs, params: dict) -> np.ndarray:
        """Decode a soft stream against the supplied H and return source bits.

        `params`:
          H | H_rows | H_alist  exactly one; see `parity_check_from_params`
          max_iter              iteration cap per block (default MAX_ITER)
          algorithm             "min-sum" (default) or "sum-product"
          normalisation         min-sum scale (default MIN_SUM_NORMALISATION)
          offset                bit index in `llrs` where the first codeword
                                starts; omit to search
          search_offsets        how many forward offsets to try when `offset`
                                is absent. Pair it with S3's
                                `llr_start_bit_tolerance`: the reported start
                                is never an over-estimate, so searching FORWARD
                                over that many bits is enough and searching
                                backwards is wasted work.
          info_positions        which columns carry the source bits
          k                     how many source bits per codeword

        **`k` and `info_positions` describe the ENCODER and cannot be derived
        from H.** H says which words are codewords; it does not say which of
        their bits the sender considered payload. The default - the first
        `n - m` positions - is the systematic convention and is right for both
        fixtures in this repo, but a mismatch produces a valid codeword and
        wrong source bits, which is a silent failure. It is a default, said out
        loud, rather than a deduction.
        """
        h = parity_check_from_params(params)
        m, n = h.shape
        mask = h.astype(bool)
        max_iter = int(params.get("max_iter", MAX_ITER))
        algorithm = str(params.get("algorithm", "min-sum"))
        if algorithm not in ("min-sum", "sum-product"):
            raise ValueError(f"unknown algorithm {algorithm!r}")
        alpha = (float(params.get("normalisation", MIN_SUM_NORMALISATION))
                 if algorithm == "min-sum" else 1.0)

        arr = np.asarray(llrs, dtype=np.float64).ravel()
        if arr.size < n:
            raise ValueError(
                f"stream carries {arr.size} values, one codeword needs {n}")

        k = int(params.get("k", n - m))
        positions = params.get("info_positions")
        positions = (np.arange(k) if positions is None
                     else np.asarray(list(positions), dtype=int))

        offset = self._pick_offset(arr, h, mask, params, max_iter,
                                   algorithm, alpha)
        n_blocks = (arr.size - offset) // n
        out = np.empty(n_blocks * positions.size, dtype=np.uint8)
        for b in range(n_blocks):
            start = offset + b * n
            bits, _, _ = _decode_block(arr[start:start + n], h, mask,
                                       max_iter, algorithm, alpha)
            out[b * positions.size:(b + 1) * positions.size] = bits[positions]
        return out

    def validate(self, bits) -> dict:
        """Is this output plausible source data, on its own terms?

        Deliberately weak and the same shape as `ConvCode.validate`, for the
        same reason: bits alone catch only the degenerate cases. `syndrome`
        below is the real check, and unlike a bit error rate it needs no
        reference stream - which makes it the one check in this file that a
        blind receiver can actually run on its own output.
        """
        arr = np.asarray(bits, dtype=np.uint8).ravel()
        if arr.size == 0:
            return {"ok": False, "reason": "empty", "n_bits": 0}
        ones = float(arr.mean())
        degenerate = ones < 0.02 or ones > 0.98
        return {
            "ok": bool(not degenerate),
            "reason": ("near-constant output - decoder did not lock"
                       if degenerate else ""),
            "n_bits": int(arr.size),
            "ones_fraction": ones,
        }

    # -- beyond the protocol, and the part that means something -------------

    def syndrome(self, llrs, params: dict) -> dict:
        """Per-block syndrome weight and iteration count for a stream.

        The honest report on a decode. `validate` asks whether the output looks
        like data; this asks whether the decoder actually found codewords, and
        it is computable without any reference bits - so it is a check S3's own
        blindness rules allow a receiver to run on itself.
        """
        h = parity_check_from_params(params)
        m, n = h.shape
        mask = h.astype(bool)
        max_iter = int(params.get("max_iter", MAX_ITER))
        algorithm = str(params.get("algorithm", "min-sum"))
        alpha = (float(params.get("normalisation", MIN_SUM_NORMALISATION))
                 if algorithm == "min-sum" else 1.0)

        arr = np.asarray(llrs, dtype=np.float64).ravel()
        offset = self._pick_offset(arr, h, mask, params, max_iter,
                                   algorithm, alpha)
        weights, iters = [], []
        for b in range((arr.size - offset) // n):
            start = offset + b * n
            _, w, it = _decode_block(arr[start:start + n], h, mask,
                                     max_iter, algorithm, alpha)
            weights.append(w)
            iters.append(it)
        clean = sum(1 for w in weights if w == 0)
        return {
            "offset": int(offset),
            "blocks": len(weights),
            "blocks_converged": clean,
            "converged_fraction": (clean / len(weights)) if weights else 0.0,
            "syndrome_weights": weights,
            "iterations": iters,
            "checks_per_block": int(m),
        }

    # -- internals ----------------------------------------------------------

    def _pick_offset(self, arr, h, mask, params, max_iter, algorithm,
                     alpha) -> int:
        """Where the first codeword starts, in this stream's own index.

        `offset` alone is taken as given. `offset` with `search_offsets` means
        "start there and try that many more", and `search_offsets` alone means
        "start at zero". Each candidate decodes its first block and the
        lightest syndrome wins, stopping on the first that reaches zero - a
        word satisfying every check is not going to be beaten.

        WHY A SEARCH AT ALL, AND WHY IT IS SHORT. S3 cannot report an exact
        start: `llr_start_bit` carries a one-symbol tolerance, the residue
        being the timing loop's discarded fractional interpolation position.
        What makes it usable is the direction. The reported value is never an
        over-estimate, so the stream's real first bit is
        `llr_start_bit + delta` for some `0 <= delta <= tolerance`.

        A caller therefore works out the first codeword boundary ASSUMING
        delta is zero, which lands at or AFTER the real one, and then searches
        back by the tolerance:

            first = -(-values["llr_start_bit"] // n) * n      # round up to n
            base  = first - values["llr_start_bit"] - values["llr_start_bit_tolerance"]
            decode(llrs[...], {"H": H, "offset": base,
                               "search_offsets": values["llr_start_bit_tolerance"]})

        That is `tolerance + 1` candidates - at most five, since the tolerance
        is one symbol. Without `llr_start_bit` it would be the length of the
        stream.
        """
        n = h.shape[1]
        base = int(params.get("offset") or 0)
        if params.get("offset") is not None and "search_offsets" not in params:
            return base
        span = int(params.get("search_offsets", 0))
        best, best_weight = base, None
        for off in range(base, base + span + 1):
            if off < 0 or arr.size - off < n:
                continue
            _, w, _ = _decode_block(arr[off:off + n], h, mask, max_iter,
                                    algorithm, alpha)
            if best_weight is None or w < best_weight:
                best, best_weight = off, w
            if w == 0:
                break
        return max(best, 0)


# One registration line, exactly as `conv_code.py` and `rs_code.py` do it. The
# package `__init__` is deliberately not touched: code plug-ins register on
# EXPLICIT import, so nothing pays for this file unless it asks for it.
register_code(LDPCCode())
