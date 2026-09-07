"""LDPCCode - belief propagation against a SUPPLIED parity-check matrix.

7 September, day-clock block C. Design, and the two measurements it rests on:
`reports/s3_ldpc_design.md`.

WHERE THIS FILE LIVES, AND WHY IT IS HERE RATHER THAN IN s5_decode
------------------------------------------------------------------
A `CODES` plug-in belongs beside `conv_code.py` and `rs_code.py` in
`pipeline/s5_decode/`. That directory is Nehal's, and the rule this project
runs on is that a file in someone else's directory is a request at the sync
and never an edit - it is what has kept four people on one pipeline at
near-zero merge conflicts all week.

So it lives here, in the S3 owner's own directory, and it is built to move:

  * it imports NOTHING from `pipeline.s3_receive`,
  * it reaches the rest of the system only through `registry.register_code`,
  * every test reaches it by name through `CODES["ldpc"]`, never by import.

Relocating it is `git mv` plus changing one import line in
`tests/unit/test_s3_ldpc_junction.py`. Nothing else refers to its path.

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

BLIND RECOVERY OF H IS OUT OF SCOPE, AND `blind_recover` SAYS SO
----------------------------------------------------------------
The Command Center puts "blind LDPC parity-check recovery" on the *Do not
build, ever, this sprint* list, on research grounds: recovering an unknown H
from a noisy stream has no reliable published method at the error rates a real
receiver produces. `blind_recover` therefore returns `None`. That is the
house rule about checks that cannot see, applied to a decoder: returning a
plausible-looking H it had not recovered is the confidently-wrong failure this
repo has been bitten by repeatedly.

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
    """LDPC decoding against a parity-check matrix the caller supplies."""

    name = "ldpc"
    detail = ("LDPC belief propagation (normalised min-sum or sum-product) "
              "against a SUPPLIED parity-check matrix; blind H recovery is "
              "out of scope and returns None")

    # -- CODES protocol -----------------------------------------------------

    def blind_recover(self, llrs):
        """Always `None`, and that is the specified behaviour rather than a gap.

        Recovering an unknown LDPC parity-check matrix from a noisy soft stream
        is on the Command Center's *do not build* list on research grounds. A
        method that returned a plausible-looking H it had not recovered would
        be worse than this one: it would put a confident wrong answer where an
        honest refusal belongs.
        """
        return None

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
