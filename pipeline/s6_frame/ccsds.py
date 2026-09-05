"""The concatenated CCSDS profile, peeled off blind - the 5 September column.

    Reed-Solomon outer -> interleaver -> convolutional inner -> scrambler

Four coding layers, none of them supplied. This is the artefact the Command
Center calls out as answering the whole problem statement at once, because a
CCSDS chain exercises every element the PS names in a single file.

WHERE THE INTERLEAVER SITS CHANGES EVERYTHING, and it caught me out today.

Every earlier study in this repo used `conv encode -> interleave`, so the
interleaver scrambled the convolutional CODEWORD and the rank collapse showed
up at the interleaver period in the received stream. In the CCSDS ordering the
interleaver is one layer further in - it permutes the RS codeword, and the
convolutional encoder wraps the result. So on the channel stream:

    the convolutional code is the OUTERMOST layer and is read directly,
    at its own span of 14. There is no interleaver visible at all.

Measured: `blind_recover` on a concatenated stream returns
`period=14, interleaver=none, K=7, G=(0o171, 0o133)` - the generators exactly
right and the interleaver correctly absent, because at that point in the chain
it genuinely is. The interleaver only becomes visible AFTER Viterbi, in the
decoded bit stream.

HOW THE INTERLEAVER IS FOUND, and it is NOT by the rank curve. A permutation
preserves rank over GF(2), so an interleaver sitting on a Reed-Solomon codeword
is invisible to the sweep - RS puts its binary-image constraints at L = 2040,
far past MAX_PERIOD, and reordering coordinates inside a 96-bit window cannot
change the dimension of a row space. Measured, with a random payload: NO
deficiency at any L up to 81 600 bits. With an ASCII payload there are
deficiencies, but they move when the message changes, because they belong to
the payload rather than the interleaver. See `_interleaver_candidates`.

So the candidates come from a bounded grid and the Reed-Solomon decoder is the
sole judge: de-interleave, and ask whether whole blocks decode. A cheap screen
rejects a wrong candidate in 0.04 s, so the 465-pair grid costs 16.9 s and
returns exactly one hit - the true (8, 12) - with no false positives.

THE SCRAMBLER AND ITS CHICKEN-AND-EGG. `descramble.recover_scrambler` needs the
code's parity check, and the scrambler is what hides the code - so neither can
go first. The way out is that an additive scrambler is periodic: for a shift P
that is a multiple of BOTH the scrambler period and the code's symbol size,

    r[n] XOR r[n+P] = c[n] XOR c[n+P]

and the XOR of two codewords is another codeword, with the scrambler gone. So
P is searched with the RANK TEST on the self-difference - which needs no parity
check - and the code recovered from the difference stream unlocks everything
else. See `find_scrambler_period_blind`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pipeline.s4_recover.gf2 import rank_gf2, reshape_rows
from pipeline.s4_recover.interleavers import block_deinterleave
from pipeline.s4_recover.rank_collapse import ROW_MARGIN, blind_recover
from pipeline.s6_frame.descramble import recover_scrambler
from pipeline.s6_frame.payload import extract_text
from pipeline.s5_decode.rs_code import _bits_to_bytes, _try_profile
from registry import CODES

__all__ = ["CCSDSResult", "find_scrambler_period_blind", "recover_ccsds"]

# Bounds. Every one of these exists so the chain cannot run away on a file
# whose content it does not understand (risk #5).
MAX_DEINTERLEAVE_CANDIDATES = 400  # (depth, width) pairs tried against RS
MAX_INTERLEAVER_DEPTH = 16         # grid bound; CCSDS depths are 1..8
MAX_INTERLEAVER_WIDTH = 32
DECODE_CAP_BITS = 48_000           # coded bits into Viterbi; commpy is pure
                                   # Python and 163 kbit takes 167 s
MAX_SCRAMBLER_SHIFT = 2048         # self-difference search, in bits
MIN_RS_BLOCKS = 4                  # fewer than this and "it decoded" means little
RS_SCREEN_OFFSETS = 8              # byte alignments tried in the cheap screen


@dataclass
class CCSDSResult:
    status: str                       # ok | partial | failed
    stages: dict = field(default_factory=dict)
    reason: str = ""
    generators_octal: tuple | None = None
    interleaver: dict | None = None
    scrambler_poly: int | None = None
    rs_params: object | None = None
    payload: bytes = b""
    text: str = ""
    printable_fraction: float = 0.0

    def summary(self) -> str:
        done = [k for k, v in self.stages.items() if v]
        return "%s | peeled: %s | %s" % (
            self.status, " -> ".join(done) or "nothing", self.reason or "")


def find_scrambler_period_blind(bits: np.ndarray, stride: int = 2,
                                max_shift: int = MAX_SCRAMBLER_SHIFT):
    """Smallest shift whose self-difference shows a code, or None.

    Needs no parity check, which is the point - it is what breaks the
    chicken-and-egg between descrambling and code recovery. Only multiples of
    `stride` are tried: a shift that is not a whole number of code symbols
    leaves the two codewords out of phase and their sum is not a codeword.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    limit = min(max_shift, len(bits) // 3)
    for shift in range(stride, limit + 1, stride):
        diff = bits[:-shift] ^ bits[shift:]
        if len(diff) < 8192:
            break
        # A cheap necessary condition before paying for a full recovery: the
        # difference must be rank deficient at the code's own span.
        M = reshape_rows(diff, 14, 0, max_rows=14 + ROW_MARGIN)
        if M.size and 14 - rank_gf2(M) > 0:
            res = blind_recover(diff, statistical_fallback=False)
            if res.status == "ok" and res.generators_octal:
                return shift, res
    return None, None


def _interleaver_candidates(decoded: np.ndarray) -> list[tuple[int, int]]:
    """(depth, width) worth trying. Bounded, and NOT taken from the rank curve.

    THE RANK TEST CANNOT SEE THIS INTERLEAVER AT ALL, and the reason is
    structural rather than a tuning problem: **a permutation preserves rank
    over GF(2)**. Interleaving reorders coordinates inside the analysis window,
    which cannot change the dimension of the row space.

    The interleaver was visible in every earlier study in this repo only
    because it permuted a CONVOLUTIONAL codeword, whose parity constraints are
    LOCAL - span 14 - so scrambling their positions destroys that locality and
    the deficiency reappears at the interleaver's period instead. Reed-Solomon
    has no such local structure: RS(255,223) puts its binary-image constraints
    at a row length of 2040 bits, an order of magnitude past MAX_PERIOD, so
    permuting within 96 bits leaves nothing for the sweep to find.

    Measured on the decoded stream, 40 RS blocks, sweeping L = 8..200:

        ASCII payload    deficient at 112, 147, 168, 192, 196 - and the values
                         MOVE when the message changes, because they are the
                         payload's own structure, not the interleaver's
        random payload   deficient NOWHERE, at any length up to 81 600 bits

    The true period, 96, appears in neither. An earlier version of this
    function ranked candidates by that curve and could not have worked; it
    only appeared to on one file whose payload happened to collapse near 96.

    So the candidates come from a bounded grid and the Reed-Solomon decoder is
    the only judge. RS is a far stronger oracle than any rank test: a wrong
    de-interleaving does not accidentally produce whole blocks that decode
    with zero corrections.
    """
    out: list[tuple[int, int]] = []
    for depth in range(2, MAX_INTERLEAVER_DEPTH + 1):
        for width in range(2, MAX_INTERLEAVER_WIDTH + 1):
            out.append((depth, width))
    # Small periods first: cheap to test and by far the commonest in practice.
    out.sort(key=lambda dw: (dw[0] * dw[1], dw[0]))
    return out[:MAX_DEINTERLEAVE_CANDIDATES]


def _rs_screen(de: np.ndarray, offsets: int = RS_SCREEN_OFFSETS) -> bool:
    """Cheap necessary condition: does RS(255,223) decode whole blocks here?

    The full `ReedSolomonCode.blind_recover` sweeps 255 byte alignments x 3
    profiles and costs about 2.2 s. Paying that for every (depth, width) in the
    grid costs 421 s to reach an 8x12 interleaver - far outside any budget.

    But a WRONG de-interleaving fails on its very first block, so one profile
    at a handful of alignments settles it. Measured on the 465-pair grid: the
    sweep drops from 421 s to 16.9 s and returns exactly one hit, the true
    (8, 12), with no false positives. The expensive call then runs once, on
    the survivor, to pin the profile and the alignment properly.

    Same shape as the rotation screening in s4_recover/rotations.py: reject
    cheaply, confirm expensively, and never let the cheap test be the one that
    makes the claim.
    """
    data = _bits_to_bytes(de)
    for off in range(offsets):
        blocks, frac, _rate = _try_profile(data, 255, 223, off,
                                           stop_on_first_failure=True)
        if blocks >= MIN_RS_BLOCKS and frac >= 1.0:
            return True
    return False


def recover_ccsds(bits, decode_cap: int = DECODE_CAP_BITS) -> CCSDSResult:
    """Peel RS <- interleaver <- convolutional <- scrambler, blind.

    Returns `partial` rather than `failed` when some layers came off and the
    rest did not - which is the useful answer, because knowing the inner code
    and the scrambler of a stream you cannot fully decode is still a result.
    """
    bits = np.asarray(bits).ravel()
    if bits.dtype.kind == "f":
        bits = (bits < 0).astype(np.uint8)          # LLR convention: +ve is 0
    bits = np.asarray(bits, dtype=np.uint8)
    res = CCSDSResult(status="failed", stages={})

    # --- layer 4: the scrambler, outermost ------------------------------
    stream = bits
    inner = blind_recover(bits)
    scrambled = inner.status != "ok" or not inner.generators_octal

    if scrambled:
        shift, from_diff = find_scrambler_period_blind(bits)
        if from_diff is None:
            res.reason = ("no convolutional code found, and no self-difference "
                          "shift up to %d exposed one either" % MAX_SCRAMBLER_SHIFT)
            return res
        res.stages["scrambler-period"] = True
        hyp = recover_scrambler(bits, from_diff.parity_taps,
                               stride=from_diff.code.n)
        if hyp is None:
            res.reason = ("found a code in the self-difference at shift %d, but "
                          "the scrambler itself did not come back" % shift)
            res.generators_octal = from_diff.generators_octal
            res.status = "partial"
            return res
        from pipeline.s6_frame.descramble import descramble
        stream = descramble(bits, hyp)
        res.scrambler_poly = getattr(hyp, "poly", None) or getattr(hyp, "poly_octal", None)
        res.stages["descramble"] = True
        inner = blind_recover(stream)

    # --- layer 3: the convolutional inner code --------------------------
    if inner.status != "ok" or not inner.generators_octal:
        res.reason = "inner convolutional code not recovered: " + (inner.reason or "")
        return res
    res.generators_octal = inner.generators_octal
    res.stages["conv"] = True

    # --- Viterbi, against the RECOVERED generators ----------------------
    head = stream[:decode_cap]
    decoded = CODES["conv"].decode(head, {
        "n": inner.code.n, "memory": inner.code.memory,
        "generators_octal": inner.generators_octal,
        "span": inner.code.span, "parity_taps": inner.parity_taps})
    decoded = np.asarray(decoded, dtype=np.uint8)
    res.stages["viterbi"] = True

    # --- layer 2 and 1: interleaver, settled by the RS decoder ----------
    rs = CODES["reed-solomon"]
    best = None
    direct = rs.blind_recover(decoded)
    if direct is not None:
        best = (None, direct, decoded)                 # no interleaver at all
    else:
        for depth, width in _interleaver_candidates(decoded):
            de = block_deinterleave(decoded, depth, width)
            if len(de) < 255 * 8 * MIN_RS_BLOCKS:
                continue
            if not _rs_screen(de):
                continue                               # cheap rejection
            prm = rs.blind_recover(de)                 # expensive confirmation
            if prm is not None:
                best = ({"family": "block", "depth": depth, "width": width}, prm, de)
                break

    if best is None:
        res.status = "partial"
        res.reason = ("convolutional layer recovered and decoded, but no "
                      "de-interleaving produced a Reed-Solomon codeword")
        return res

    res.interleaver, res.rs_params, de = best
    if res.interleaver:
        res.stages["deinterleave"] = True

    # --- the payload ----------------------------------------------------
    # ReedSolomonCode.decode returns the DATA bits, 0/1 uint8 - not bytes.
    payload_bits = np.asarray(rs.decode(de, res.rs_params), dtype=np.uint8)
    res.payload = np.packbits(payload_bits).tobytes()
    res.stages["reed-solomon"] = True

    rep = extract_text(payload_bits)
    res.text, res.printable_fraction = rep.text, rep.printable_fraction
    res.status = "ok"
    return res
