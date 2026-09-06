"""Retry across the hypotheses S2 ranked, within a bound.

4 Sep, Block C. Owner: Anvith.

S2 does not hand S3 an answer. It hands over a *ranked list* on every field it
estimates - `symbol_rate_hypotheses`, `cfo_hypotheses`, and (once the
classifier lands) a ranking over modulations. Until today S3 read the top of
each list and ignored the rest, which is the same as pretending the ranking was
a decision.

It is not, and the corpus says so loudly: S2's top carrier-offset hypothesis is
wrong on 33 of 36 files, and taking it leaves 32 of them demodulating at a bit
error rate of about 0.485. Reading the rest of a list that was already being
computed turns **4 files decoding into 29**. See `reports/s3_lock_gate.md`.

WHAT MAKES THIS BOUNDED RATHER THAN A SWEEP
-------------------------------------------
The registry product is 6 modulations x 3 symbol rates x 5 carrier offsets - 54
to 78 combinations after de-duplication - and a full receive costs 0.2-1.0 s.
Run naively that is over a minute for one file, inside a 90-second budget for
the whole pipeline: risk #5, arriving by the front door on the day the plan
says to open it.

Three things keep it cheap, in order of how much they save:

1.  SCREEN BEFORE RUNNING. `lockcheck.signal_presence` answers "is there a
    signal at this rate" from one FFT, in 8-28 ms on the corpus, without
    touching the receiver chain. A candidate that fails it cannot produce bits,
    so it never costs a chain run.

2.  SCREEN ONCE PER *DISTINCT* MEASUREMENT. Presence depends on the family and
    the rate; alignment depends on the rate and the offset. Neither depends on
    which of the four PSK/QAM plug-ins is asking - see `_Screen`, where the
    keys are argued rather than assumed. Measured on the corpus: **54 to 78
    candidates, 12 to 14 measurements, 2 to 12 survivors**, so the screening
    pass costs about a fifth of a second and removes most of the work.

3.  STOP ON THE FIRST CLEAN LOCK. A candidate whose every check passed is not
    improved on by trying more, so the loop returns it.

A wall clock sits behind all three, because the argument above is about the
corpus and a judge will bring something else.

WHAT IT DOES NOT DO
-------------------
It does not silently repair S2. A carrier offset the alignment check rejects
produces a *new candidate* carrying the measured correction - scored beside
every other candidate, and recorded in `hypotheses` with the reason it was
created. The rejected one stays in the record. An orchestrator that quietly
patched its input would leave the bug upstream with nothing pointing at it, and
the whole reason this was found today is that the number was visible.

It also names no scheme. The modulation list comes from `registry.MODULATIONS`,
so a plug-in registered tomorrow is searched tomorrow with no edit here.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from registry import MODULATIONS

from .base import S2Params
from .lockcheck import carrier_alignment, signal_presence, strongest_line
from .result import Hypothesis, S3Result

__all__ = ["receive_best", "Candidate", "params_from_s2",
           "SEARCH_BUDGET_S", "MAX_CANDIDATES", "MAX_CHAIN_RUNS"]

SEARCH_BUDGET_S = 20.0
"""Wall clock for the whole search, screening included.

The Command Center budgets 90 seconds for a file end to end, and S4's rotation
search already reserves its own. 20 s leaves S3 room for roughly twenty full
chain runs at the corpus's worst measured 1.0 s, which is far more than the
screen ever lets through, while capping what an adversarial input can cost.
The result says when the clock, rather than the evidence, ended the search.

THE VALUE HAS NOT MOVED; THE REASONING ABOVE WAS INCOMPLETE, and 7 Sep is where
that showed. "Twenty runs at 1.0 s" is measured on the corpus, whose files are
80 000 samples. A chain run costs time roughly in proportion to the capture, so
a capture three times longer costs about three times as much per run - 1.5-1.6 s
each on the 240 000-sample signal in the blind-estimates test - while this
number stays 20 s. The budget is therefore a fixed clock over a variable amount
of work, and its real unit is "how many runs on THIS input", not "how many runs".

What that cost, before the 7 Sep fixes: that test signal needed eight chain runs
to reach its answer and 12.1 s to do it here, 21.5 s on Nehal's machine, and the
whole failure was that a search which overruns does not slow down - it returns
the best of what it had run, which was a different modulation. The fixes took it
to three runs and 3.4 s, and the corpus's worst file from 11.12 s to 6.97 s.
Widening the budget instead would have bought the same test a pass and left the
mechanism in place. See `reports/s3_search_cost.md`.

Quote the worst-case margin as a RANGE, not a number. Two independent runs of
the same 252 files on the same idle machine put the worst file at 6.97 s and at
8.46 s, and disagreed about which file it was - so the honest reading is 7-8.5 s
against this 20 s, a margin of roughly 2.4-2.9x. A single worst-case second is
the kind of figure this whole finding is a warning about.
"""

MAX_CANDIDATES = 96
"""Ceiling on combinations *considered*, before screening. Guards against an
upstream stage handing over a hypothesis list that is longer than anyone
intended - the sort of thing that turns into a five-minute stage without a
single line of it looking wrong."""

MAX_CHAIN_RUNS = 12
"""Ceiling on full receiver runs, after screening. The screen is what is
supposed to keep this small; this is the backstop for an input the screen finds
plausible everywhere, which is a thing noise-shaped signals do."""

RESCUE_PRIOR = 0.5
"""How far a rate-rescued candidate sorts below the S2-derived one it replaces.

It keeps the modulation prior it inherited, so the classifier's ranking still
orders the rescued candidates among themselves; the factor only says that a
rate S3 found for itself is weaker evidence than one S2 offered. In the case
this exists for, every S2 rate has already been refused and the rescued
candidates are the only survivors, so the factor decides nothing - which is
the point. It must never reorder a search that was working.
"""

RATE_DEDUP_REL = 1.5e-5
"""Relative grid the rate axis of `Candidate.key()` de-duplicates on.

It is one bin of the line search that proposes these rates. `_LINE_NFFT` is
2**18 and the corpus runs 4 samples/symbol, so a bin is `sps / _LINE_NFFT` =
1.53e-05 of the symbol rate - 0.76 Hz at 50 kHz. Two rates inside one bin are
one reading of one spectrum, and `_line_score_at` already takes the maximum
over the bin either side, so no cheap check in this stage can separate them.

Measured either side of that on 7 Sep, one corpus file per modulation at
20 dB, in `reports/s3_search_cost.md`: every file returns an identical
status and an identical raw bit error rate out to 5e-05 of relative rate
error, and the tightest two - 2-FSK and BPSK - first diverge at 1e-04, where
they turn `failed` rather than wrong. So this grid sits 3.3x inside the
largest error measured to change nothing, and 6.7x inside the smallest
measured to change anything.
"""


@dataclass
class Candidate:
    """One (modulation, symbol rate, carrier offset) triple to try."""

    modulation: str
    symbol_rate: float
    cfo_hz: float
    prior: float                      # from S2's ranking; higher is likelier
    origin: str = "s2"                # s2 | zero-cfo | residual-corrected
    rejected: str | None = None       # why the screen refused it

    def params(self, base: dict[str, Any]) -> dict[str, Any]:
        p = dict(base)
        p["symbol_rate"] = self.symbol_rate
        p["cfo_hz"] = self.cfo_hz
        return p

    def key(self) -> tuple:
        """Identity for de-duplication: both axes on what a check can resolve.

        Two offsets closer together than a quarter of what
        `lockcheck.CARRIER_OFFSET_LIMIT` will even notice are the same
        hypothesis, and running the chain twice to find that out is a quarter
        of a second thrown away per pair. It happens constantly: correcting
        S2's 12500 Hz by the measured -12402 Hz lands on 97.7 Hz, which is the
        `cfo = 0` candidate that was already in the queue.

        THE RATE AXIS HAD THE SAME PROBLEM AND NONE OF THE SAME CARE until
        7 Sep, when it was `round(rate, 3)` - a fixed 1 mHz grid, an ABSOLUTE
        tolerance on a quantity whose error is relative, and 300x finer than
        the FFT bin any of these rates is read out of. The rescue proposes a
        rate off the line search while S2 reports an interpolated one, so the
        two arrive at the same rate by different routes and disagree in the
        eighth digit. On the blind-search test signal they were 50000.000000
        and 50000.002618 Hz - 5.2e-08 apart, 1/300th of one bin - and the
        search paid THREE full chain runs, 5.0 s of a 12.1 s search, to find
        out they demodulate identically. See `RATE_DEDUP_REL` for the grid and
        the measurement behind it.

        The rate grid is logarithmic because a relative grid has to be.
        Dividing a rate by a grid defined as a fraction OF that rate yields
        `round(1 / RATE_DEDUP_REL)` for every rate there has ever been, which
        collapses the axis to a single cell and merges 27 kHz with 50 kHz; the
        logarithm is what turns "within a factor of 1 + rel" into "within one
        cell" without that trap.

        Quantising is a hash and not a comparison, so a pair that straddles a
        cell boundary still costs one extra run. That is exactly the guarantee
        the offset axis has always given, and the cost of a miss is one run
        rather than a wrong answer.
        """
        from .lockcheck import CARRIER_OFFSET_LIMIT
        cell = round(math.log(max(self.symbol_rate, 1e-9))
                     / math.log1p(RATE_DEDUP_REL))
        grid = max(CARRIER_OFFSET_LIMIT * self.symbol_rate / 4.0, 1e-6)
        return (self.modulation, cell, round(self.cfo_hz / grid))

    def label(self) -> dict[str, Any]:
        return {"modulation": self.modulation,
                "symbol_rate": round(float(self.symbol_rate), 1),
                "cfo_hz": round(float(self.cfo_hz), 1),
                "origin": self.origin}


@dataclass
class _Screen:
    """Memoised cheap checks, keyed by what each one actually depends on.

    The keys are a correctness claim, not just a cache policy, so they are
    worth spelling out:

    - **presence** is measured on the RAW capture, never a de-rotated copy,
      because both statistics behind it are carrier-invariant: `|x|^2` removes
      the carrier by construction, and the derivative of the instantaneous
      frequency turns a constant offset into a constant that the mean removal
      takes out. So one measurement per (family, rate) covers every carrier
      hypothesis, and the four PSK/QAM plug-ins share one measurement because
      they share a family.
    - **alignment** does depend on the offset, since applying it is the whole
      point, but not on which plug-in is asking.

    54 to 78 candidates therefore need at most 2 x rates x offsets
    measurements - 12 to 14 on the corpus.
    """

    iq: np.ndarray
    fs: float
    presence: dict = field(default_factory=dict)
    alignment: dict = field(default_factory=dict)
    peak: dict = field(default_factory=dict)
    n_measurements: int = 0

    def presence_of(self, family: str, rate: float):
        k = (family, round(rate, 3))
        if k not in self.presence:
            self.presence[k] = signal_presence(self.iq, self.fs, rate, family)
            self.n_measurements += 1
        return self.presence[k]

    def alignment_of(self, rate: float, cfo: float):
        k = (round(rate, 3), round(cfo, 3))
        if k not in self.alignment:
            x = self.iq
            if cfo:
                x = x * np.exp(-2j * np.pi * (cfo / self.fs)
                               * np.arange(x.size))
            self.alignment[k] = carrier_alignment(x, self.fs, rate)
            self.n_measurements += 1
        return self.alignment[k]

    def line_peak_of(self, family: str):
        """Where this family's cyclostationary line is, measured once.

        Same statistic, same spectrum and same carrier-invariance argument as
        `presence_of`, so one measurement per family covers every rate and
        every offset - two for the whole search.
        """
        if family not in self.peak:
            self.peak[family] = strongest_line(self.iq, self.fs, family)
            self.n_measurements += 1
        return self.peak[family]


def params_from_s2(s2_result: Any, fs: float | None = None) -> dict[str, Any]:
    """Flatten an S2 result into the mapping `receive_best` reads.

    Duck-typed on purpose. S3 must not import `pipeline.s2_estimate`: S2 is
    upstream, and a stage that imports the stage feeding it cannot be tested,
    swapped or run without it. Everything here is a `getattr` with a default,
    so an S2 that grows a field gets used and an S2 that lacks one still works.
    """
    get = lambda n, d=None: getattr(s2_result, n, d)          # noqa: E731
    return {
        "fs": float(fs if fs is not None else get("fs", 0.0)),
        "symbol_rate": get("symbol_rate_hz"),
        "cfo_hz": get("cfo_hz") or 0.0,
        "symbol_rate_hypotheses": list(get("symbol_rate_hypotheses") or []),
        "cfo_hypotheses": list(get("cfo_hypotheses") or []),
        "modulation_hypotheses": list(get("modulation_hypotheses") or []),
    }


def _ranked(entries: Iterable, numeric: bool = True,
            value_index: int = 0,
            score_index: int = -1) -> list[tuple[Any, float]]:
    """(value, score) pairs out of S2's ranked tuples, longest form first.

    `symbol_rate_hypotheses` is [(rate, score)] and `cfo_hypotheses` is
    [(cfo, m, score)]. Reading position -1 for the score and 0 for the value
    covers both without this module having to know which is which - and
    survives S2 adding a field, which it has done once already.

    `numeric=False` is for `modulation_hypotheses`, which is
    [(class_name, probability)] - the VALUE is a string. This function used to
    coerce every value with `float()`, so the first classifier ranking handed
    to `receive_best` raised `ValueError: could not convert string to float:
    'qpsk'`. Nothing in this repo produced that field yet when the code was
    written, and it would have fired the morning Dheeraj's classifier merged.
    A value is a value; only the score is a number.
    """
    out: list[tuple[Any, float]] = []
    for e in entries or ():
        if isinstance(e, (tuple, list)) and len(e) >= 2:
            value, score = e[value_index], e[score_index]
        elif isinstance(e, (int, float, str)):
            value, score = e, 0.0
        else:
            continue
        try:
            score = float(score)
            if numeric:
                value = float(value)
        except (TypeError, ValueError):
            continue
        out.append((value, score))
    return out


def _normalise(scores: Sequence[float]) -> list[float]:
    """Scores onto 0..1 so rates and offsets can be combined into one prior.

    S2's rate scores are peak-over-median (single digits to ~100) and its CFO
    scores are a different peak-over-median on a different spectrum. They are
    not comparable in absolute terms, only in rank, so each list is scaled
    against its own maximum before the two are multiplied.
    """
    if not scores:
        return []
    top = max(scores) or 1.0
    return [max(s, 0.0) / top for s in scores]


def _build_candidates(base: dict[str, Any],
                      modulations: Sequence[str]) -> list[Candidate]:
    rates = _ranked(base.get("symbol_rate_hypotheses"))
    if not rates:
        r = base.get("symbol_rate")
        rates = [(float(r), 1.0)] if r else []
    cfos = _ranked(base.get("cfo_hypotheses"))
    if not cfos:
        cfos = [(float(base.get("cfo_hz") or 0.0), 1.0)]

    # Zero is always a candidate. It is the hypothesis "the upstream estimate
    # is wrong and there is no offset", and on this corpus it is the correct
    # one 36 times out of 36 - which nothing downstream could have discovered
    # while the list it was handed did not contain it.
    if not any(abs(c) < 1e-9 for c, _ in cfos):
        cfos = cfos + [(0.0, 0.0)]

    mod_prior = dict(_ranked(base.get("modulation_hypotheses"), numeric=False)
                     or ())
    # A modulation the classifier did not rank must sort BELOW every one it
    # did, not above them. The default used to be 1.0, so a classifier saying
    # "qpsk 0.91, 8psk 0.06, 16qam 0.03" put the three it never mentioned at
    # the FRONT of the queue - and with `stop_on_clean_lock` on, the first of
    # those to lock would have won. Unranked still means tried, because the
    # classifier is allowed to be wrong and 4 Sep's cross-check is exactly
    # "corrupt the top hypothesis and the pipeline still decodes"; it only
    # means tried last.
    unranked_prior = (min(mod_prior.values()) * 0.5) if mod_prior else 1.0

    rate_scores = _normalise([s for _, s in rates])
    cfo_scores = _normalise([s for _, s in cfos])

    out: list[Candidate] = []
    for name in modulations:
        mp = float(mod_prior.get(name, unranked_prior)) if mod_prior else 1.0
        for (rate, _), rs in zip(rates, rate_scores):
            if not np.isfinite(rate) or rate <= 0:
                continue
            for (cfo, _), cs in zip(cfos, cfo_scores):
                if not np.isfinite(cfo):
                    continue
                out.append(Candidate(name, float(rate), float(cfo),
                                     prior=mp * (0.1 + rs) * (0.1 + cs)))
    out.sort(key=lambda c: -c.prior)
    deduped: list[Candidate] = []
    seen: set[tuple] = set()
    for c in out:
        if c.key() in seen:
            continue
        seen.add(c.key())
        deduped.append(c)
    return deduped[:MAX_CANDIDATES]


def _breadth_first(survivors: Sequence[Candidate]) -> list[Candidate]:
    """One run per modulation before any modulation gets a second.

    7 Sep. The classifier's ranking is a prior over MODULATIONS, but the queue
    it orders is a list of (modulation, rate, offset) triples, so a single
    confident verdict buys every offset under it before any other modulation is
    reached at all. That is a category error, and it is what turns a wrong
    classifier call into a clock problem instead of a ranking problem.

    Measured, on the signal in
    `test_s3_runs_on_blind_estimates_with_no_labels_in_the_path`: the
    classifier reads a QPSK capture as 8-PSK at probability 0.999, so 8-PSK's
    three surviving offsets ran first, at 1.5-1.6 s each, and QPSK - ranked
    third at 0.000141 - was not reached until 5.0 s of chain time had gone.
    Interleaving reaches it after 8-PSK's best and 2-FSK's best, at 1.6 s.

    WHAT THIS DOES NOT CHANGE, which is the part that had to be argued before
    it could be written: the FIRST candidate run is identical either way. It is
    still the top-ranked modulation at its most conservative offset, because
    round one is taken in the order the modulations first appear and that order
    is the prior order. Every candidate still runs, in the same set, under the
    same ceilings. Only the order of everything after the first failure moves,
    and it moves from "exhaust this modulation" to "ask the next one".

    That reordering is visible to `stop_on_clean_lock`, so it was not assumed
    to be safe - it was measured across all 252 corpus files and the full
    cross-hypothesis sweep before it was kept. See `reports/s3_search_cost.md`.
    """
    first_seen: dict[str, int] = {}
    depth: dict[str, int] = {}
    ordered: list[tuple[int, int, Candidate]] = []
    for c in survivors:                      # already in prior order
        first_seen.setdefault(c.modulation, len(first_seen))
        d = depth.get(c.modulation, 0)
        depth[c.modulation] = d + 1
        ordered.append((d, first_seen[c.modulation], c))
    ordered.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in ordered]


def _quality(res: S3Result, cand: "Candidate") -> tuple:
    """Sort key for a completed run. Higher is better.

    `estimated_output_ber` only enters when S3 marked it VALID. That flag is
    the whole point of the 4 Sep lock work: on a run that failed the alignment
    check the estimate reads 0.000000 against an actual 0.485, so ranking on it
    unguarded would put the worst candidate first, every time.

    The third term is Occam and it is not decoration. Two candidates can be
    indistinguishable on everything the receiver can measure and still differ
    in how large a claim they make about the input: `4fsk_13dB_2033` produced
    an identical estimate under a 0 Hz offset and under a -49 951 Hz one, and
    the large offset won on a meaningless tie-break of tone margin, decoding at
    a bit error rate of 0.248 because it had slipped every tone label by one.
    A hypothesis that needs a bigger correction needs more evidence for it, so
    on a tie the smaller correction wins.
    """
    rank = {"ok": 2, "low_confidence": 1, "failed": 0}[res.status]
    v = res.values
    valid = bool(v.get("estimated_output_ber_valid"))
    ber = float(v.get("estimated_output_ber", 1.0)) if valid else 1.0
    n_llrs = int(v.get("n_llrs", 0) or 0)
    correction = abs(cand.cfo_hz) / max(cand.symbol_rate, 1e-9)
    return (rank, -ber, -round(correction, 3), float(res.confidence), n_llrs)


def receive_best(iq: np.ndarray, params: dict[str, Any],
                 modulations: Sequence[str] | None = None,
                 budget_s: float = SEARCH_BUDGET_S,
                 max_chain_runs: int = MAX_CHAIN_RUNS,
                 stop_on_clean_lock: bool | None = None) -> S3Result:
    """Best demodulation over S2's ranked hypotheses, bounded.

    `params` is `params_from_s2(...)`, or any mapping with `fs` plus either
    `symbol_rate` or the ranked lists. `modulations` restricts the search to a
    ranked subset; the default is every registered plug-in, in registration
    order.

    S2's classifier landed on 5 Sep and its ranking arrives through `params`
    as `modulation_hypotheses`, not through this argument - which is the
    difference between a PRIOR and a RESTRICTION, and the distinction is the
    reason the corpus still decodes where the classifier is wrong. A ranking
    orders the queue and an unranked modulation is tried last; `modulations`
    means the others are never tried at all. 2-FSK and 4-FSK classify at 0%
    below 10 dB (Dheeraj's `reports/s2_coverage.md`), and 4-FSK is wrong on 6
    of 7 files at 20 dB with the right answer sitting at rank 2, so a
    restriction there would lose files a prior only reorders.

    `stop_on_clean_lock=None` (the default) decides for itself, and the rule is
    worth stating because getting it wrong costs correctness rather than time:
    stopping at the first `ok` is only sound when the ORDER means something.
    With a modulation ranking from S2, it does, and the first clean lock is the
    likeliest candidate that worked. Without one the order is registration
    order, which means nothing at all - and 4-FSK, registered last, loses to
    2-FSK on its own file, because a 2-FSK plug-in on a 4-FSK signal does lock,
    to half the tones. Measured: 4fsk_20dB_2035 chosen as 2-FSK at an estimated
    BER of 0.089 when 4-FSK on the same file estimates 0.000000. So with no
    ranking, every survivor is run and the best is chosen on its own reported
    quality, which is evidence rather than an accident of import order.

    Returns an ordinary `S3Result`, so every existing caller works unchanged.
    Its `hypotheses` carry the whole search: what was tried, what the screen
    refused and why, and what each surviving run came back with.
    """
    t0 = time.perf_counter()
    deadline = t0 + float(budget_s)
    x = np.asarray(iq, dtype=np.complex128)
    fs = float(params.get("fs", 0.0))

    ranked_input = bool(modulations) or bool(params.get("modulation_hypotheses"))
    if stop_on_clean_lock is None:
        stop_on_clean_lock = ranked_input

    names = list(modulations) if modulations else list(MODULATIONS)
    names = [n for n in names if n in MODULATIONS]
    if not names:
        return S3Result(status="failed", reason="no modulation plug-ins registered",
                        elapsed_ms=(time.perf_counter() - t0) * 1e3)

    candidates = _build_candidates(params, names)
    if not candidates:
        return S3Result(status="failed",
                        reason="S2 supplied no usable symbol rate hypothesis",
                        elapsed_ms=(time.perf_counter() - t0) * 1e3)

    screen = _Screen(x, fs)
    seen = {c.key() for c in candidates}
    queue = list(candidates)
    tried: list[Candidate] = []
    survivors: list[Candidate] = []
    exhausted = False

    # --- screening pass. Cheap, memoised, and it also GROWS the queue: a
    # candidate rejected for a wrong carrier offset carries the correction that
    # would fix it, so the correction becomes a new candidate rather than a
    # silent patch.
    i = 0
    while i < len(queue):
        if time.perf_counter() > deadline:
            exhausted = True
            break
        c = queue[i]
        i += 1
        tried.append(c)
        plug = MODULATIONS[c.modulation]
        family = getattr(plug, "family", "psk")

        pres = screen.presence_of(family, c.symbol_rate)
        if pres.failed:
            c.rejected = pres.detail
            # The rate axis gets the same treatment the offset axis already
            # got below: a candidate refused by a measurement carries, in that
            # same measurement, the correction that would fix it. "No line at
            # the rate you claimed" is one FFT away from "the line is at this
            # other rate", and until 5 Sep the search threw that away and
            # returned `failed` with zero chain runs.
            #
            # Bounded so it stays a fallback and not a second estimator: one
            # rate per family, only from a candidate that has already been
            # refused, and the proposal re-enters this same screen rather than
            # skipping it. If the rescued rate is not itself convincing, it is
            # rejected exactly like anything else.
            peak = screen.line_peak_of(family)
            if peak is not None:
                rate, _score = peak
                new = Candidate(c.modulation, rate, c.cfo_hz,
                                prior=c.prior * RESCUE_PRIOR,
                                origin="rate-rescued")
                if new.key() not in seen and len(queue) < MAX_CANDIDATES:
                    seen.add(new.key())
                    queue.append(new)
            continue

        align = screen.alignment_of(c.symbol_rate, c.cfo_hz)
        if align.failed:
            c.rejected = align.detail
            corrected = c.cfo_hz + float(align.value or 0.0)
            new = Candidate(c.modulation, c.symbol_rate, corrected,
                            prior=c.prior * 0.9, origin="residual-corrected")
            if new.key() not in seen and len(queue) < MAX_CANDIDATES:
                seen.add(new.key())
                queue.append(new)
            continue

        survivors.append(c)

    # Priority first, then the SMALLER correction. The second term matters only
    # when `stop_on_clean_lock` is on, and then it matters a lot: the early exit
    # takes the first `ok` it reaches, and S2's own ranking over carrier offsets
    # is produced by the estimator whose failure this whole day is about. Trying
    # the most conservative offset first means the early exit lands on the
    # hypothesis that claimed least, rather than on whichever one S2 liked.
    survivors.sort(key=lambda c: (-c.prior, abs(c.cfo_hz) / max(c.symbol_rate, 1e-9)))
    survivors = _breadth_first(survivors)

    # --- the expensive pass, on what survived
    best: tuple[tuple, Candidate, S3Result] | None = None
    runs = 0
    for c in survivors:
        if runs >= max_chain_runs or time.perf_counter() > deadline:
            exhausted = exhausted or runs < len(survivors)
            break
        res = MODULATIONS[c.modulation].receive(x, c.params(params))
        runs += 1
        q = _quality(res, c)
        if best is None or q > best[0]:
            best = (q, c, res)
        if stop_on_clean_lock and res.status == "ok":
            break

    elapsed = (time.perf_counter() - t0) * 1e3
    trail = _trail(tried, survivors, screen, runs, exhausted)

    if best is None:
        why = ("every candidate was refused by the cheap screen"
               if tried else "no candidates were built")
        detail = next((c.rejected for c in tried if c.rejected), None)
        return S3Result(
            status="failed", confidence=0.0,
            values={"search_candidates": len(tried),
                    "search_screened_out": len(tried) - len(survivors),
                    "search_chain_runs": 0,
                    "search_measurements": screen.n_measurements,
                    "search_budget_exhausted": exhausted},
            hypotheses=trail,
            reason=f"{why}: {detail}" if detail else why,
            elapsed_ms=elapsed)

    _, chosen, res = best
    res.values.update({
        "search_candidates": len(tried),
        "search_screened_out": len(tried) - len(survivors),
        "search_chain_runs": runs,
        "search_measurements": screen.n_measurements,
        "search_budget_exhausted": exhausted,
        "search_chosen": chosen.label(),
        "symbol_rate_used": float(chosen.symbol_rate),
        "cfo_hz_used": float(chosen.cfo_hz),
    })

    # House rule: a check that cannot see must say so. A search the clock cut
    # short has NOT seen the candidates it never reached, and until 7 Sep it
    # said that only in `search_budget_exhausted`, a key nothing was obliged to
    # read, while `status` and `reason` looked exactly like a finished search
    # that had weighed the field and come back unsure. Those are different
    # claims and a consumer has to be able to tell them apart: the first is a
    # verdict, the second is a partial result that a faster machine would have
    # improved on. Nehal hit precisely this from the other side - the same file
    # returning `ok`/QPSK unloaded and `low_confidence`/8-PSK under load.
    #
    # The result itself is kept, not downgraded. It is the best of what was
    # actually run, and throwing it away would lose files to a slow machine
    # rather than merely mislabelling them.
    # Name the bound that actually applied. `exhausted` is set by EITHER the
    # clock or `max_chain_runs`, and blaming the clock for a run-ceiling stop
    # would be the same species of false claim this note exists to prevent: 11
    # of the 252 corpus files run to the ceiling, several of them flagged
    # exhausted at about 2 s, where 20 s was never the constraint.
    unreached = max(len(survivors) - runs, 0)
    if exhausted and unreached:
        bound = (f"a ceiling of {max_chain_runs} chain runs"
                 if runs >= max_chain_runs else f"a {budget_s:g} s budget")
        note = (f"search truncated by {bound}: {runs} of {len(survivors)} "
                f"surviving candidates were run and {unreached} never reached "
                "- this is the best of what ran, not a survey of the field")
        res.reason = f"{res.reason}; {note}" if res.reason else note

    res.hypotheses = trail + list(res.hypotheses)
    res.elapsed_ms = elapsed
    return res


def _trail(tried: Sequence[Candidate], survivors: Sequence[Candidate],
           screen: _Screen, runs: int, exhausted: bool) -> list[Hypothesis]:
    """The search, as `hypotheses` - the audit trail a stage card can render.

    Rejections are kept, not dropped. "S3 chose 8-PSK" is not an answer anybody
    can check; "S3 refused these five for these reasons and chose the sixth" is.
    """
    out = [
        Hypothesis(
            value=c.label(),
            score=float(c.prior),
            evidence=(c.rejected if c.rejected
                      else "passed the cheap screen; "
                           + ("demodulated" if c in survivors[:runs]
                              else "not reached inside the budget")),
        )
        for c in tried
    ]
    out.append(Hypothesis(
        value={"screened": len(tried), "survived": len(survivors),
               "measurements": screen.n_measurements, "chain_runs": runs,
               "budget_exhausted": exhausted},
        score=0.0,
        evidence="search summary: measurements are the cheap spectral checks, "
                 "chain runs are full demodulations",
    ))
    return out
