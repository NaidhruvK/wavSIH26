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

That matters for the 6 September core-lock gate, which is 90 seconds for the
WHOLE analysis across all seven stages. 8-PSK alone was spending 70 of them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .rank_collapse import RecoveryResult, blind_recover

__all__ = ["RotationChoice", "recover_over_rotations", "ROTATION_BUDGET_S"]

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


def recover_over_rotations(candidates, statistical_fallback: bool = True
                           ) -> RotationChoice | None:
    """Best rotation, or None when no rotation produced a confident recovery.

    `candidates` is S3's `llrs_by_rotation` - soft LLR arrays, not hard bits.
    Nothing here hard-slices: `blind_recover` does that at its own entry, and
    the caller needs the floats afterwards to decode (de-interleaving an
    integer-cast LLR array returns zeros - see interleavers.py).
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

    # Nothing at all on the cheap path. This is the case the statistical
    # method was built for, so now it is worth its budget - bounded.
    deadline = time.monotonic() + ROTATION_BUDGET_S
    hit, tried, stopped = _sweep(True, deadline)
    if hit is None:
        return None
    return RotationChoice(hit[1], hit[2], tried, used_fallback=True,
                          budget_exhausted=stopped)
