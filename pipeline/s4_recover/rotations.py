"""Recovery across the phase rotations a coherent receiver cannot resolve.

S3 emits `llrs_by_rotation` because a carrier loop locks to the constellation,
not to the transmitter's absolute phase: BPSK has 2 indistinguishable
rotations, QPSK 4, 8-PSK 8. Exactly one of them (or one conjugate pair) is the
transmitted stream; the rest are wrong by construction.

This module exists so the orchestrator does not have to rediscover two rules
that were each paid for with a day's measurement.

RULE 1 - RANK BY SHORTEST CONSTRAINT SPAN (Anvith, 3 Sep; verified from the S4
side the same day). Confidence cannot choose between rotations - it is
identical for all that return a code. Span can. Enumerating all eight rotations
of a QPSK stream gives:

    0 deg, 180 deg        period 14, (0o171, 0o133)   true
    conj 90, conj 270     period 14, (0o133, 0o171)   I/Q exchanged
    the other four        period 16 or 18             a different code

The four survivors at period 14 decode to the SAME payload at 100% source-bit
agreement - the "swapped pair" is I and Q exchanged, which no coherent receiver
can distinguish and which decodes identically. So shortest-span resolves the
ambiguity completely rather than partially.

RULE 2 - SCREEN FIRST, THEN PAY (4 Sep, measured on the zoo's RF corpus). The
statistical fallback exists for a single stream you have reason to believe
carries a code, and it spends up to 8 seconds of wall clock proving a negative.
Running it once per rotation is exactly backwards: most rotations are wrong BY
CONSTRUCTION, so the search pays its most expensive path on inputs already
known to be mostly hopeless. Measured on zoo/corpus/rf, per file:

    8-PSK  8 dB   8 rotations   70.3 s -> 1.4 s
    8-PSK 20 dB   8 rotations   64.0 s -> 2.6 s
    QPSK  20 dB   4 rotations   18.1 s -> 1.2 s
    BPSK  20 dB   2 rotations    0.6 s -> 0.6 s   (fallback never fired)

**Every status was identical either way.** The fallback contributed nothing on
any of the 36 files; it only burned the budget. So: screen every rotation with
the fallback OFF, and re-run with it ON only when screening found nothing at
all - which is the case the fallback was actually built for.

Combined with the S3 pre-flight below, across the whole 36-file RF corpus:

    worst single file    72.1 s -> 27.6 s
    whole corpus          746 s -> 112 s
    recovery              26/36 -> 26/36   (unchanged)
    confidently wrong         0 -> 0

That matters for the 6 September core-lock gate, which is 90 seconds for the
WHOLE analysis across all seven stages. 8-PSK alone was spending 70 of them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .rank_collapse import RecoveryResult, blind_recover

__all__ = ["RotationChoice", "recover_over_rotations", "ROTATION_BUDGET_S",
           "PREFLIGHT_BER_LIMIT", "preflight_reason"]

# Wall clock for the EXPENSIVE pass only, across all rotations together.
#
# Screening every rotation cheaply fixed the files that recover, and did
# nothing for the files that do not: when no rotation produces a code, the
# search falls through to the fallback and pays 8 s per rotation exactly as
# before. Measured on the zoo RF corpus, the worst file went 72.1 s -> 73.3 s.
# Those declining files are the risk #5 case - a judge's out-of-envelope input
# is precisely a file where nothing will be found.
#
# The capability is NOT removed. On all 36 RF files and all 73 bits-only files
# the fallback rescued exactly nothing, so deleting it would have been
# defensible - but "it has never fired" is not "it can never fire", and this
# module is not the place to make that call. Bounding it is: the search gets a
# fixed budget and reports honestly when the budget, rather than the evidence,
# ended it.
ROTATION_BUDGET_S = 25.0

# --- the S3 pre-flight, and why it gates only the EXPENSIVE pass -----------
#
# S3 reports `estimated_output_ber` for free. On the zoo RF corpus it separated
# recovery from failure perfectly: every recovery <= 1.5e-6, every failure
# >= 7.5e-5, a fifty-fold gap with nothing in it. That looks like an oracle.
#
# IT IS NOT AN ORACLE, and the corpus is why it looked like one: it sets
# cfo=0, phase=0 and timing_offset=0. Re-measured on 28 files through a channel
# with cfo 1e-4, phase 0.7 rad and timing 0.3 symbols, the two populations
# OVERLAP:
#
#     no impairments (36 files)   recovered <= 1.52e-06   failed >= 7.48e-05
#     with impairments (28 files) recovered <= 1.19e-05   failed >= 1.08e-05
#
# Two files at 4 dB BPSK, seeds 1 and 2, sat at 1.254e-05 and 1.191e-05 - a 5%
# difference in the estimate - and one recovered while the other did not. Any
# hard threshold in that region is a coin toss.
#
# Across all 64 files:
#
#     threshold   recoveries SUPPRESSED   hopeless files skipped
#     1e-5                          1                        14   <- unsafe
#     2e-5                          0                        12
#     3e-5                          0                        12
#     5e-5                          0                        11
#     1e-4                          0                         9
#
# So the limit is 3e-5: the widest margin (2.5x over the worst observed
# recovery) that still skips everything 2e-5 does.
#
# THE DESIGN MATTERS MORE THAN THE NUMBER. Suppressing a real recovery loses a
# demo; spending 25 wasted seconds does not. So this gate never decides whether
# to ATTEMPT recovery - the cheap screening pass always runs, and across all
# 137 files measured to date every single recovery came from that cheap pass
# and the statistical fallback rescued nothing. The gate only decides whether
# the EXPENSIVE fallback pass is worth its 25 seconds. A recovery therefore
# cannot be suppressed by this threshold being wrong.
PREFLIGHT_BER_LIMIT = 3e-5


def preflight_reason(estimated_output_ber: float | None,
                     valid: bool = False) -> str | None:
    """A sentence for the stage card when S3's own estimate says not to bother.

    Returns None when there is nothing to say. Only speaks when S3 marked the
    estimate VALID - Anvith's own note is that it reads optimistically when the
    receiver has not locked, and an optimistic estimate errs toward attempting,
    which is the safe direction.
    """
    if not valid or estimated_output_ber is None or estimated_output_ber < 0:
        return None
    if estimated_output_ber <= PREFLIGHT_BER_LIMIT:
        return None
    return ("S3 estimates %.1e output BER; blind recovery of the interleaver "
            "needs better than about %.0e, so the deep search was skipped. "
            "Raise the SNR or supply a longer capture."
            % (estimated_output_ber, PREFLIGHT_BER_LIMIT))


@dataclass
class RotationChoice:
    index: int                  # which rotation S3 offered won
    result: RecoveryResult
    n_screened: int             # how many rotations were tried
    used_fallback: bool         # did the expensive path run at all?
    budget_exhausted: bool = False   # did the wall clock end the search?

    @property
    def span(self) -> int | None:
        return self.result.code.span if self.result.code else None


def _is_confident(res: RecoveryResult) -> bool:
    """A rotation only competes if it produced something checkable."""
    return (res.status == "ok"
            and res.code is not None
            and res.code.span is not None
            and bool(res.generators_octal))


def recover_over_rotations(candidates, statistical_fallback: bool = True,
                           estimated_output_ber: float | None = None,
                           estimated_ber_valid: bool = False
                           ) -> RotationChoice | None:
    """Best rotation, or None when no rotation produced a confident recovery.

    `candidates` is S3's `llrs_by_rotation` - soft LLR arrays, not hard bits.
    Nothing here hard-slices: `blind_recover` does that at its own entry, and
    the caller needs the floats afterwards to decode (de-interleaving an
    integer-cast LLR array returns zeros - see interleavers.py).

    Pass S3's `estimated_output_ber` and `estimated_output_ber_valid` through
    and the expensive fallback pass is skipped when the receiver itself says
    the demodulation is too poor to recover from. The cheap pass runs
    regardless, so this can save time but cannot cost a recovery - see
    PREFLIGHT_BER_LIMIT.
    """
    cands = list(candidates)
    if not cands:
        return None

    def _sweep(use_fallback: bool, deadline: float | None = None):
        best, tried, stopped = None, 0, False
        for idx, cand in enumerate(cands):
            if deadline is not None and time.monotonic() > deadline:
                stopped = True
                break
            res = blind_recover(np.asarray(cand, dtype=float),
                                statistical_fallback=use_fallback)
            tried += 1
            if not _is_confident(res):
                continue
            # Shortest span wins; rotation index breaks an exact tie so the
            # choice is deterministic across runs.
            key = (res.code.span, idx)
            if best is None or key < best[0]:
                best = (key, idx, res)
        return best, tried, stopped

    hit, tried, _ = _sweep(False)
    if hit is not None:
        return RotationChoice(hit[1], hit[2], tried, used_fallback=False)

    if not statistical_fallback:
        return None

    # S3's own estimate, used only to decide whether the expensive pass is
    # worth its 25 seconds. The cheap pass above has already run.
    if preflight_reason(estimated_output_ber, estimated_ber_valid) is not None:
        return None

    # Nothing at all on the cheap path. This is the case the statistical
    # method was built for, so now it is worth its budget - bounded.
    deadline = time.monotonic() + ROTATION_BUDGET_S
    hit, tried, stopped = _sweep(True, deadline)
    if hit is None:
        return None
    return RotationChoice(hit[1], hit[2], tried, used_fallback=True,
                          budget_exhausted=stopped)
