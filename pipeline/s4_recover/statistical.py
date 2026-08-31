"""Statistical parity-check recovery, for when the exact rank test has died.

Why a second method exists. The exact rank test needs every row of the matrix
to lie in the code subspace. One flipped bit pushes its row out, and the
deficiency shrinks by one. Measured on a period-96 stream the deficiency falls
roughly linearly and reaches zero at about 0.5% BER (reports/ber_ceiling.md).
Above that the exact test returns nothing at all - which is the safe direction
to fail, but it is still a hard floor on what the receiver can decode.

The statistical method splits the problem in two, because the two halves have
very different error tolerance:

  GENERATION - find a candidate parity check. Draw span-1 same-phase windows
  at random and take the null space of that little system. If every drawn
  window happens to be error-free, the null vector IS the code's parity check;
  if not, it is an essentially uniform random vector. Repeat and count. The
  true check collects votes proportional to (1-p)^(span*(span-1)); the wrong
  ones spread themselves over 2^span possibilities and never accumulate. So
  the true answer wins by an enormous margin long before it becomes likely in
  any single draw. This is the half that limits us.

  VALIDATION - given a candidate h, measure how often the syndrome is zero
  across the whole stream. For a wrong h that is exactly 1/2. For the right h
  it is (1 + (1-2p)^w)/2 where w is the weight of h. Over a hundred thousand
  windows that gap is detectable at error rates far past anything generation
  can reach, and it also yields an estimate of p itself - so the validator
  reports the channel BER it inferred, which is a number we can check.

The asymmetry is the useful finding: recovering a check is much harder than
confirming one. Recover it once on a clean file, and you can then track it on
files far too noisy to have recovered it from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from math import sqrt

import numpy as np

__all__ = [
    "CheckValidation",
    "CheckCandidate",
    "StatisticalResult",
    "int_to_taps",
    "taps_to_int",
    "null_space_int",
    "pack_windows",
    "syndrome_validate",
    "vote_for_check",
    "statistical_recover",
]

MAX_SPAN = 40         # longest parity check we will look for
MAX_STRIDE = 4        # largest symbol size n we will consider
DEFAULT_SAMPLES = 1500
EXTRA_ROWS = 6        # rows drawn beyond `span` - see vote_for_check
Z_THRESHOLD = 8.0     # sigma. 8 is absurd on purpose - a false check is worse
                      # than no check, so the bar to claim one is very high.


# ---------------------------------------------------------------------------
# small GF(2) helpers, on packed ints. column c lives in bit (span-1-c).
# ---------------------------------------------------------------------------

def taps_to_int(taps) -> int:
    v = 0
    for c, t in enumerate(taps):
        if int(t):
            v |= 1 << (len(taps) - 1 - c)
    return v


def int_to_taps(value: int, span: int) -> np.ndarray:
    return np.array([(value >> (span - 1 - c)) & 1 for c in range(span)], dtype=np.uint8)


PACK_SPAN_LIMIT = 62   # int64 headroom for the vectorised packer


def pack_windows(bits: np.ndarray, span: int) -> list[int]:
    """Every stride-1 window of `span` bits, packed into Python ints.

    Vectorised, and hoisted out of the (stride, phase) loops by the caller.
    Packing per combination instead meant re-walking all ~60k windows for each
    of ~170 combinations - about ten million Python-level calls, which was the
    entire runtime of the blind search. Slicing a single packed list by
    [phase::stride] gives the same windows for free.
    """
    if span > PACK_SPAN_LIMIT:
        raise ValueError("span %d exceeds the int64 packer limit %d"
                         % (span, PACK_SPAN_LIMIT))
    windows = np.lib.stride_tricks.sliding_window_view(
        np.asarray(bits, dtype=np.uint8).ravel(), span)
    weights = (np.uint64(1) << np.arange(span - 1, -1, -1, dtype=np.uint64))
    return (windows.astype(np.uint64) @ weights).tolist()


def null_space_int(rows, span: int) -> list[int]:
    """Null space basis of the given rows, as packed ints.

    Rows are packed ints of `span` bits. Small by construction - this is called
    once per random draw, so it runs on ints rather than numpy to avoid paying
    array-creation overhead a few hundred thousand times.
    """
    pivot: dict[int, int] = {}   # leading column -> reduced row
    for r in rows:
        cur = r
        while cur:
            col = span - 1 - (cur.bit_length() - 1)
            other = pivot.get(col)
            if other is None:
                pivot[col] = cur
                break
            cur ^= other

    # back-substitute so each pivot column appears in exactly one row
    pivot_cols = sorted(pivot)
    for col in reversed(pivot_cols):
        row = pivot[col]
        bit = span - 1 - col
        for other_col in pivot_cols:
            if other_col < col and (pivot[other_col] >> bit) & 1:
                pivot[other_col] ^= row

    free = [c for c in range(span) if c not in pivot]
    basis = []
    for f in free:
        vec = 1 << (span - 1 - f)
        fbit = span - 1 - f
        for col in pivot_cols:
            if (pivot[col] >> fbit) & 1:
                vec |= 1 << (span - 1 - col)
        basis.append(vec)
    return basis


# ---------------------------------------------------------------------------
# validation: does this candidate check actually hold, more often than chance?
# ---------------------------------------------------------------------------

@dataclass
class CheckValidation:
    span: int
    stride: int
    phase: int
    weight: int
    n_windows: int
    n_zero: int
    bias: float           # 2*P(syndrome=0) - 1; 0 for a wrong check
    z_score: float        # sigma above the null hypothesis of P=1/2
    implied_ber: float | None
    passed: bool

    def describe(self) -> str:
        ber = "n/a" if self.implied_ber is None else "%.4f" % self.implied_ber
        return ("span=%d stride=%d phase=%d weight=%d | bias=%.4f z=%.1f "
                "implied_BER=%s over %d windows"
                % (self.span, self.stride, self.phase, self.weight, self.bias,
                   self.z_score, ber, self.n_windows))


def syndrome_validate(bits: np.ndarray, check: int, span: int, stride: int,
                      phase: int, z_threshold: float = Z_THRESHOLD) -> CheckValidation:
    """Measure how often `check` is satisfied, and how surprising that is.

    Under the null hypothesis that the check is unrelated to the data, the
    syndrome is a fair coin and n_zero ~ Binomial(N, 1/2). The z-score is how
    many standard deviations we are above that. It is not a goodness score to
    be tuned - it is a probability statement, and it is what lets us say "no
    code structure detected" and mean it.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    taps = int_to_taps(check, span)
    weight = int(taps.sum())
    if weight == 0 or len(bits) < span + stride:
        return CheckValidation(span, stride, phase, weight, 0, 0, 0.0, 0.0, None, False)

    windows = np.lib.stride_tricks.sliding_window_view(bits, span)[phase::stride]
    if len(windows) == 0:
        return CheckValidation(span, stride, phase, weight, 0, 0, 0.0, 0.0, None, False)

    syndrome = (windows @ taps) & 1
    n = int(len(syndrome))
    n_zero = int(n - syndrome.sum())

    bias = 2.0 * n_zero / n - 1.0
    z = (n_zero - n / 2.0) / sqrt(n / 4.0)

    implied = None
    if bias > 0:
        # bias = (1-2p)^weight  =>  p = (1 - bias^(1/weight)) / 2
        implied = float((1.0 - bias ** (1.0 / weight)) / 2.0)

    return CheckValidation(span, stride, phase, weight, n, n_zero, float(bias),
                           float(z), implied, bool(z >= z_threshold))


# ---------------------------------------------------------------------------
# generation: vote for a check by sampling small same-phase systems
# ---------------------------------------------------------------------------

@dataclass
class CheckCandidate:
    check: int
    span: int
    stride: int
    phase: int
    votes: int
    n_samples: int

    @property
    def vote_fraction(self) -> float:
        return self.votes / self.n_samples if self.n_samples else 0.0


def vote_for_check(bits: np.ndarray, span: int, stride: int, phase: int,
                   n_samples: int = DEFAULT_SAMPLES,
                   rng: np.random.Generator | None = None,
                   extra_rows: int = EXTRA_ROWS,
                   packed_all: list[int] | None = None) -> CheckCandidate | None:
    """Draw random same-phase systems and return the most-voted null vector.

    Windows must share a phase: a parity check on a rate-1/n code holds only on
    windows whose start is a multiple of n. Mixing phases guarantees the drawn
    system has no meaningful null vector, which is why `stride` is searched
    rather than assumed.

    We draw span+EXTRA_ROWS windows, not span-1. Drawing the bare minimum is
    the obvious choice and it is the wrong one, for two measured reasons:

      - span-1 random vectors out of a 13-dimensional space are independent
        only ~29% of the time, so 71% of clean draws come back with a
        2-dimensional null space and get discarded. The extra rows push that
        yield to ~99%.
      - a draw containing an error is then almost certainly full rank, so it
        contributes NO vote instead of a random one. Spurious votes fall from
        0.55 to 0.01 per draw at 5% BER, which is what keeps the tally clean
        exactly where it is hardest to read.

    Both effects push the same way, so the extra rows cost nothing.
    """
    rng = rng or np.random.default_rng(0)
    if packed_all is None:
        packed_all = pack_windows(bits, span)
    packed = packed_all[phase::stride]
    n_windows = len(packed)
    if n_windows < span * 4:
        return None

    counts: dict[int, int] = {}
    draw = min(span + extra_rows, n_windows)
    idx = rng.integers(0, n_windows, size=(n_samples, draw))
    for row in idx:
        basis = null_space_int([packed[i] for i in row], span)
        if len(basis) == 1:            # exactly determined - the useful case
            v = basis[0]
            counts[v] = counts.get(v, 0) + 1

    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: kv[1])
    return CheckCandidate(best[0], span, stride, phase, best[1], n_samples)


@dataclass
class StatisticalResult:
    status: str                      # ok | failed
    check: int | None = None
    taps: list[int] | None = None
    validation: CheckValidation | None = None
    candidate: CheckCandidate | None = None
    reason: str = ""

    def describe(self) -> str:
        if self.status != "ok":
            return "no validated parity check - " + self.reason
        return "check=%s | %s" % ("".join(str(b) for b in self.taps),
                                  self.validation.describe())


def statistical_recover(bits: np.ndarray, max_span: int = MAX_SPAN,
                        max_stride: int = MAX_STRIDE,
                        n_samples: int = DEFAULT_SAMPLES,
                        z_threshold: float = Z_THRESHOLD,
                        seed: int = 0,
                        spans=None,
                        time_budget_s: float | None = None) -> StatisticalResult:
    """Smallest span carrying a parity check that survives the syndrome test.

    Spans are searched in increasing order and the first validated one wins:
    the shortest check is the code's own, and every longer one is a shift or a
    combination of it.

    Within a span every (stride, phase) is evaluated and the one with the
    LARGEST bias is taken, not the first that clears the threshold. That is not
    a detail. A check on a rate-1/n code holds only on windows whose start is a
    multiple of n, so scanning at stride 1 mixes satisfied and unsatisfied
    windows and halves the bias - which still passes an 8-sigma test while
    reporting the wrong symbol size and a badly inflated channel BER. Picking
    the maximum recovers n as well as h.

    `time_budget_s` caps the wall clock and returns what has been found so far.
    The cost of this search is worst on inputs that contain nothing - every
    span, stride and phase gets tried before the answer "no" comes back - and
    those are exactly the inputs someone reaches for when they want to see the
    system waste time (risk #5). A budget turns an unbounded search into a
    bounded one without weakening any answer it does return: a validated check
    is validated regardless of how much of the space was searched. What shrinks
    is only the range over which "no" can be claimed, and the result says so.

    `spans` restricts the search to a known set. Use it when the span is
    already known from a clean file: generation is the error-limited half of
    this method, and skipping it is what lets a known check be tracked on
    streams far too noisy to have recovered it from.

    Every dimension of this search is bounded (risk #5).
    """
    rng = np.random.default_rng(seed)
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    span_range = list(spans) if spans is not None else list(range(4, max_span + 1))

    started = time.monotonic()
    exhausted = True
    searched_to = 0

    for span in span_range:
        if time_budget_s is not None and time.monotonic() - started > time_budget_s:
            exhausted = False
            break
        searched_to = span
        packed_all = pack_windows(bits, span)   # once per span, not per combination
        found = []
        for stride in range(1, max_stride + 1):
            for phase in range(stride):
                cand = vote_for_check(bits, span, stride, phase, n_samples, rng,
                                      packed_all=packed_all)
                if cand is None or cand.votes < 3:
                    continue
                val = syndrome_validate(bits, cand.check, span, stride, phase,
                                        z_threshold)
                if val.passed:
                    found.append((cand, val))
        if found:
            # Any multiple of the true symbol size shows the same expected bias
            # on a subset of the windows - stride 4 looks as good as stride 2
            # and differs only by sampling noise. So take the maximum bias, then
            # step back down to the SMALLEST stride that is statistically
            # indistinguishable from it. That one is the real symbol size n,
            # and it is also the one measured over the most windows.
            best_bias = max(v.bias for _, v in found)
            tol = 3.0 / sqrt(min(v.n_windows for _, v in found))
            viable = [(c, v) for c, v in found if v.bias >= best_bias - tol]
            cand, val = min(viable, key=lambda cv: (cv[1].stride, cv[1].phase))
            return StatisticalResult(
                "ok", cand.check, [int(b) for b in int_to_taps(cand.check, span)],
                val, cand)

    if exhausted:
        return StatisticalResult(
            "failed",
            reason="no check up to span %d survived the %.0f-sigma syndrome test"
                   % (span_range[-1] if span_range else max_span, z_threshold))
    return StatisticalResult(
        "failed",
        reason="no check up to span %d survived the %.0f-sigma syndrome test; "
               "the %.1fs budget stopped the search before span %d, so longer "
               "checks are not ruled out"
               % (searched_to, z_threshold, time_budget_s, span_range[-1]))
