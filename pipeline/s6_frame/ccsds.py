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
from pipeline.s4_recover.interleavers import (
    block_deinterleave, symbol_deinterleave, CCSDS_DEPTHS)
from pipeline.s4_recover.rank_collapse import ROW_MARGIN, blind_recover
from pipeline.s6_frame.descramble import (
    recover_scrambler, descramble_known, STANDARD_RANDOMISERS)
from pipeline.s6_frame.payload import extract_text
from pipeline.s5_decode.rs_code import _bits_to_bytes, _try_profile
from registry import CODES

__all__ = ["CCSDSResult", "find_scrambler_period_blind", "recover_ccsds",
           "RS_CODEWORD_BYTES"]

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
RS_CODEWORD_BYTES = 255            # symbol interleaving is defined per codeword
SCRAMBLER_SHIFT_CANDIDATES = 6     # shifts that may pay for a full blind_recover
PAYLOAD_ENTROPY_MARGIN = 1.0       # bits/byte between randomiser hypotheses
                                   # before one is claimed - see _resolve_randomiser

# Row length for the cheap "is this a codeword?" screen in the scrambler
# search. It must be deficient for EVERY code in the declared envelope and
# full rank on unstructured data.
#
# This was 14 - the span of rate-1/2 K=7, the one code the chain was built
# against - and it made the screen a false-negative generator for everything
# else. Measured deficiency at a single row length:
#
#     stream          L=14   L=36   L=60   L=72
#     rate 1/2 K=7       1     12     24     30
#     rate 1/2 K=9       0     10     22     28    <- rejected at 14
#     rate 1/2 K=3       5     16     28     34
#     rate 1/3 K=7       0     18     34     42    <- rejected at 14
#     uncoded random     0      0      0      0
#
# 60 works because it is a multiple of both candidate symbol sizes (2 and 3)
# and comfortably above the largest span in the envelope - rate 1/3 at K=9 is
# span 27. Deficiency is L/n - m there, so every declared code shows it and
# unstructured data does not. Same cost: one rank computation per shift.
SCREEN_ROW_LEN = 60


@dataclass
class CCSDSResult:
    status: str                       # ok | partial | failed
    stages: dict = field(default_factory=dict)
    reason: str = ""
    generators_octal: tuple | None = None
    interleaver: dict | None = None
    scrambler_poly: int | None = None
    randomiser: str | None = None     # which STANDARD_RANDOMISERS entry, if any
    randomiser_ambiguous: bool = False  # RS accepted several; payload could not
    randomiser_note: str = ""           # how the randomiser was settled, if at all
    rs_params: object | None = None
    payload: bytes = b""
    text: str = ""
    printable_fraction: float = 0.0

    def summary(self) -> str:
        done = [k for k, v in self.stages.items() if v]
        return "%s | peeled: %s | %s" % (
            self.status, " -> ".join(done) or "nothing", self.reason or "")


def find_scrambler_period_blind(bits: np.ndarray, stride: int = 2,
                                max_shift: int = MAX_SCRAMBLER_SHIFT,
                                max_candidates: int = SCRAMBLER_SHIFT_CANDIDATES):
    """Smallest shift whose self-difference shows a code, or None.

    Needs no parity check, which is the point - it is what breaks the
    chicken-and-egg between descrambling and code recovery. Only multiples of
    `stride` are tried: a shift that is not a whole number of code symbols
    leaves the two codewords out of phase and their sum is not a codeword.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    limit = min(max_shift, len(bits) // 3)

    # THE SCREEN RANKS, IT DOES NOT THRESHOLD, and that is a 6 September fix to
    # a 5 September fix of mine. `b431082` moved SCREEN_ROW_LEN from 14 to 60
    # because 14 is the span of rate-1/2 K=7 and nothing else, so the screen
    # was a false-negative generator for every other code in the envelope.
    # That was right. What it did NOT notice is that the test on the other side
    # of it - "deficiency > 0" - stopped screening anything at all. Measured on
    # the scrambled fixture, 255 shifts searched:
    #
    #     SCREEN_ROW_LEN = 14    1 of 255 shifts passed
    #     SCREEN_ROW_LEN = 60  255 of 255 shifts passed
    #
    # so every shift paid for a full `blind_recover` and the search went from
    # about a second to 268 s - past the 90 s core-lock budget on its own, with
    # `reports/ccsds_chain.md` still quoting the pre-fix 55.8 s.
    #
    # The reason is structural, not a tuning miss. The sum of two codewords is
    # a codeword at EVERY shift that is a whole number of symbols - that is the
    # premise the whole method rests on - so the code's own deficiency is
    # present everywhere and only the residual scrambler distinguishes the
    # shifts. At L = 14 the code contributes a deficiency of just 1, so the
    # residual buries it except at the true shift; the old screen worked by
    # sitting exactly on that margin, which is not a property to rely on. At
    # L = 60 the code contributes 24 and survives the residual everywhere.
    #
    # What still separates them is the SIZE of the collapse, cleanly:
    #
    #     254 wrong shifts   deficiency 16   (min = median = max)
    #     the true shift     deficiency 24   ( = L/n - m for rate 1/2 K=7)
    #     wrong shifts scoring >= the true one:  0 of 254
    #
    # So sweep the deficiency for every shift - 255 ranks, about 0.1 s - take
    # the median as the floor the residual imposes, and pay for a recovery only
    # on shifts that stand above it. No knowledge of n or m is used, the
    # expensive oracle still makes every claim, and a stream with no scrambler
    # produces a flat profile, no candidates, and a cheap honest "no".
    profile: list[tuple[int, int]] = []
    for shift in range(stride, limit + 1, stride):
        diff = bits[:-shift] ^ bits[shift:]
        if len(diff) < 8192:
            break
        M = reshape_rows(diff, SCREEN_ROW_LEN, 0,
                         max_rows=SCREEN_ROW_LEN + ROW_MARGIN)
        if M.size:
            profile.append((shift, SCREEN_ROW_LEN - rank_gf2(M)))

    if not profile:
        return None, None

    floor = float(np.median([d for _shift, d in profile]))
    candidates = [sh for sh, d in profile if d > floor][:max_candidates]
    for shift in candidates:
        diff = bits[:-shift] ^ bits[shift:]
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


def _randomiser_candidates(decoded):
    """(name, poly, stream) to test, "no randomiser" first and always.

    Ordering is not cosmetic. This project's own layer order puts the
    scrambler on the CHANNEL, outside the convolutional code, where
    `find_scrambler_period_blind` has already dealt with it before Viterbi
    ran - so by here the stream carries no randomiser and the first candidate
    is the answer. The real CCSDS 131.0-B order puts the randomiser INSIDE the
    code instead, so it survives Viterbi and is still sitting on this stream.
    Trying the null hypothesis first means the existing path costs nothing and
    cannot change the answer it already gave.
    """
    yield None, None, decoded
    for name, poly, seed in STANDARD_RANDOMISERS:
        yield name, poly, descramble_known(decoded, poly, seed)


def _peel_symbol_layers(decoded, rs):
    """The CCSDS transmit order: randomiser over a BYTE-interleaved RS stream.

    Five permuting depths times two randomiser hypotheses is ten
    de-interleavings, each rejected by the cheap screen in about 0.04 s, plus
    one extra full `blind_recover` for the un-permuted randomised stream. So
    this whole phase costs about one expensive confirmation, and it runs
    before the 465-pair bit-level grid rather than after it.

    Returns EVERY surviving (interleaver, rs_params, de_stream, randomiser)
    rather than the first. See `_resolve_randomiser`: for the real CCSDS
    randomiser the RS decoder cannot tell the hypotheses apart, so stopping at
    the first acceptance is how the chain returned confident garbage.
    """
    hits = []
    for name, poly, stream in _randomiser_candidates(decoded):
        if name is not None:
            # The un-interleaved case has to be tried per randomiser too:
            # CCSDS I=1 is a legal profile, and on that stream there is a
            # randomiser to remove but no permutation to undo.
            direct = rs.blind_recover(stream)
            if direct is not None:
                hits.append((None, direct, stream, name))
                continue                      # this randomiser is settled
        for depth in CCSDS_DEPTHS:
            if depth == 1:
                continue                      # identity - covered by `direct`
            de = symbol_deinterleave(stream, depth, RS_CODEWORD_BYTES)
            if len(de) < RS_CODEWORD_BYTES * 8 * MIN_RS_BLOCKS:
                continue
            if not _rs_screen(de):
                continue                      # cheap rejection
            prm = rs.blind_recover(de)        # expensive confirmation
            if prm is not None:
                hits.append(({"family": "ccsds-symbol", "depth": depth,
                              "n_bytes": RS_CODEWORD_BYTES}, prm, de, name))
                break                         # one depth per randomiser
    return hits


def _peel_bit_layers(decoded, rs):
    """This project's own order: RS bit-interleaved beneath the code.

    The 465-pair grid, 16.9 s. Unchanged from the 5 September chain except
    that it now also runs against each known randomiser - which only happens
    after every cheaper hypothesis has already been declined. Collects every
    surviving randomiser, for the reason given in `_peel_symbol_layers`.
    """
    hits = []
    for name, poly, stream in _randomiser_candidates(decoded):
        for depth, width in _interleaver_candidates(stream):
            de = block_deinterleave(stream, depth, width)
            if len(de) < RS_CODEWORD_BYTES * 8 * MIN_RS_BLOCKS:
                continue
            if not _rs_screen(de):
                continue
            prm = rs.blind_recover(de)
            if prm is not None:
                hits.append(({"family": "block", "depth": depth,
                              "width": width}, prm, de, name))
                break                         # one pair per randomiser
    return hits


# ---------------------------------------------------------------------------
# Resolving a randomiser the Reed-Solomon decoder cannot see
# ---------------------------------------------------------------------------

def _payload_bytes(rs, de, params) -> bytes:
    """The RS data bits of one hypothesis, packed. `decode` returns bits."""
    return np.packbits(np.asarray(rs.decode(de, params), dtype=np.uint8)).tobytes()


def _byte_entropy(raw: bytes) -> float:
    """Shannon entropy over byte values, bits per byte. 8.0 is structureless.

    WHY ENTROPY AND NOT THE PRINTABLE FRACTION, which is what the rest of this
    repo reaches for. Printability answers "is this text", and the payload of a
    real downlink very often is not. Entropy answers the question actually being
    asked - "did removing this layer expose structure, or destroy it" - and it
    has the property that matters here: on a payload that was random to begin
    with it CANNOT separate the hypotheses, and it says so by tying, rather than
    by picking one. A discriminator that fails loudly on the case it cannot
    judge is the whole point; see `_resolve_randomiser`.
    """
    if not raw:
        return 8.0
    counts = np.bincount(np.frombuffer(raw, dtype=np.uint8), minlength=256)
    p = counts[counts > 0] / len(raw)
    return float(-(p * np.log2(p)).sum())


def _resolve_randomiser(hits, rs):
    """Pick among hypotheses the RS decoder accepted, or decline to.

    THE REED-SOLOMON DECODER IS BLIND TO THE CCSDS RANDOMISER, and this
    function exists because of it. Measured: the randomiser's LFSR period is
    255 BITS, an RS(255,223) block is 255 bytes = 2040 bits = exactly eight
    whole periods, so every codeword is XORed with the same 255-byte pattern K
    - and K is ITSELF an exact RS codeword. RS is linear over GF(256), so

        C + K  is a codeword, exactly, with nothing to correct.

    "Every block decoded at errata_rate 0.0" therefore says NOTHING about
    whether the randomiser came off, and the ambiguity is symmetric: applying
    the randomiser to an un-randomised stream also produces codewords, so no
    ordering of the hypotheses fixes it. Pinned by
    `test_the_ccsds_randomiser_is_invisible_to_the_reed_solomon_decoder`.

    Only the payload can separate them, so that is where the decision is made -
    and it is reported as such rather than folded into the RS verdict.

    Returns (best, ambiguous, note).
    """
    if not hits:
        return None, False, ""
    if len(hits) == 1:
        return hits[0], False, ""

    scored = sorted(((_byte_entropy(_payload_bytes(rs, de, prm)), il, prm, de, nm)
                     for il, prm, de, nm in hits), key=lambda t: t[0])
    lo, hi = scored[0], scored[1]
    margin = hi[0] - lo[0]
    names = ", ".join("%s (%.2f b/byte)" % (t[4] or "no-randomiser", t[0])
                      for t in scored)

    if margin < PAYLOAD_ENTROPY_MARGIN:
        return None, True, (
            "%d randomiser hypotheses all produced valid Reed-Solomon "
            "codewords and the payload cannot separate them (%s; margin %.2f "
            "< %.2f bits/byte). The CCSDS randomiser's keystream is itself an "
            "RS codeword, so RS acceptance carries no information about it - "
            "declining rather than guessing" % (len(hits), names, margin,
                                                PAYLOAD_ENTROPY_MARGIN))

    _e, il, prm, de, nm = lo
    return (il, prm, de, nm), False, (
        "randomiser settled at the payload layer, not by RS: %s" % names)


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

    # --- layers 2 and 1: randomiser and interleaver, RS as sole judge ---
    #
    # TWO LAYER ORDERS ARE SEARCHED HERE, not one, and that is the 6 September
    # change. Until today this chain assumed the Command Center's stated order
    # (RS -> bit-interleave -> convolutional -> scrambler), which puts the
    # scrambler on the channel and the interleaver on BITS. The real
    # CCSDS 131.0-B transmit order is
    #
    #     RS -> byte-interleave -> randomise -> convolutional
    #
    # so the randomiser is INSIDE the code and survives Viterbi, and the
    # interleaver permutes SYMBOLS rather than bits. Measured against a corpus
    # file built to the real standard, the old chain peeled the convolutional
    # layer correctly and then stopped at "no de-interleaving produced a
    # Reed-Solomon codeword" - a true statement about a search that could not
    # have succeeded, which is the failure mode worth removing.
    #
    # Cheapest hypothesis first: the symbol phase is ten screened
    # de-interleavings at about 0.04 s each plus one full confirmation; the
    # bit-level grid below it is 465 pairs.
    rs = CODES["reed-solomon"]

    # EVERY surviving randomiser at the cheapest layer configuration that has
    # any, not the first one to be accepted. RS cannot judge the randomiser
    # (see `_resolve_randomiser`), so first-accept silently returned garbage.
    hits = [(None, prm, stream, name)
            for name, _poly, stream in _randomiser_candidates(decoded)
            for prm in (rs.blind_recover(stream),) if prm is not None]
    if not hits:
        hits = _peel_symbol_layers(decoded, rs)
    if not hits:
        hits = _peel_bit_layers(decoded, rs)

    if not hits:
        res.status = "partial"
        res.reason = ("convolutional layer recovered and decoded, but no "
                      "combination of the known randomisers and the block or "
                      "CCSDS-symbol interleavers produced a Reed-Solomon "
                      "codeword")
        return res

    best, ambiguous, note = _resolve_randomiser(hits, rs)
    res.randomiser_ambiguous, res.randomiser_note = ambiguous, note
    if best is None:
        res.status = "partial"
        res.reason = note
        return res

    res.interleaver, res.rs_params, de, randomiser = best
    if res.interleaver:
        res.stages["deinterleave"] = True
    if randomiser is not None:
        res.stages["derandomise"] = True
        res.randomiser = randomiser
        if res.scrambler_poly is None:
            res.scrambler_poly = dict(
                (n, poly) for n, poly, _seed in STANDARD_RANDOMISERS)[randomiser]

    # --- the payload ----------------------------------------------------
    # ReedSolomonCode.decode returns the DATA bits, 0/1 uint8 - not bytes.
    payload_bits = np.asarray(rs.decode(de, res.rs_params), dtype=np.uint8)
    res.payload = np.packbits(payload_bits).tobytes()
    res.stages["reed-solomon"] = True

    rep = extract_text(payload_bits)
    res.text, res.printable_fraction = rep.text, rep.printable_fraction
    res.status = "ok"
    return res
