# Stage 4 — the rank-collapse signature

**Nehal · 29 August 2026 · evidence for the day-one gate**

Regenerate with `python reports/rank_profile_study.py`. Outputs
`rank_profile.png` and `rank_profile.csv`.

---

## What was measured

Chop a received bitstream into rows of `L` bits, take the rank of that matrix
over GF(2), and plot `L − rank` against `L`. Nothing in the measurement is told
the modulation, the code or the interleaver.

Three streams, 200 000 source bits each, rate 1/2 K=7 with generators
(171, 133) octal:

| Stream | Deficiency behaviour | Reading |
|---|---|---|
| Uncoded random | **0 at every L, up to L = 300** | Nothing claimed. This is the false-positive guard. |
| Coded, no interleaver | `L/2 − 6` at every **even** L ≥ 14; 0 at every odd L | Deficient only on even L ⇒ n = 2. First deficiency at L = 14 ⇒ span = n(m+1) ⇒ m = 6, K = 7. |
| Coded + block interleaved 8×12 | Nonzero **only** at L = 96, 192, 288 | Smallest deficient L is the interleaver period, 96 = 8×12. |

The middle row is the useful one: the deficiency does not merely appear, it
matches the closed-form prediction `L/n − m` exactly at every point. That is
what turns the sweep from a detector into a measurement — n and m are *read
off* the curve rather than searched for.

## Recovering the parameters

The period alone does not give the interleaver, because 8×12 and 16×6 have
identical rank profiles. The split is resolved functionally: de-interleave with
each factorisation of 96 and keep whichever restores the convolutional
signature. On every trial exactly one factorisation does, and the others leave
the stream indistinguishable from random — a wrong hypothesis produces no
structure at all, not weaker structure, which is what makes the test decisive
rather than a threshold.

With the period and factorisation known, the null space of the collapsed matrix
at L = span is one-dimensional, and that single vector is the code's parity
check. Unpacking it recovers **0o171 and 0o133 exactly**, on every trial.

The block alignment falls out of the same sweep. The collapse survives any
start offset but is largest when rows line up with the true block boundary, so
`argmax` over offsets recovers an alignment we were never given. Across the ten
gate trials, `start_trim + recovered_offset` was an exact multiple of the period
every time.

## The day-one gate

```
pytest tests/unit -q     →  83 passed
```

`test_rank_spike_ten_of_ten` — 10 randomly parameterised streams, random
interleaver from a pool of twelve factorisations, **random start offset**, all
recovered correctly: period, depth×width, alignment, and both generator
polynomials.

**Result: 10/10.** The premise holds.

## Three things this cost, worth writing down

**The generator polynomial convention (risk #10) bit immediately.** The parity
check on the interleaved output needs both tap vectors *reversed*; the natural
ordering fails on ~50% of windows, which looks exactly like noise rather than
like a bug. Budgeted half a day for this in the register — it took twenty
minutes because the test compared against a check that must annihilate the
stream exactly, so "half right" was not a passing state.

**The same convention bit twice, and the second time nothing caught it.**
Our encoder was using the reversed generator bit order. Encode and
blind-recover round-tripped perfectly against each other, so every S4 test
passed and the recovered polynomials read back as 0o171 and 0o133 — correct
against ourselves, wrong against the world. It surfaced only when the encoder
was compared against `commpy`, which is an independent implementation. The
standard reading is LSB-first: for g(D) = g0 + g1·D + … + g6·D⁶ written in
octal, the octal's LSB is g0, the coefficient multiplying the current input
bit. Fixed in `poly_to_taps`/`taps_to_poly`, and now pinned by
`test_our_encoder_matches_commpy_bit_for_bit`.

Worth being precise about the impact: on a real CCSDS downlink S4 would have
reported **0o117 and 0o155** instead of 0o171 and 0o133. Not a crash, not a
degraded number — a confident, plausible, wrong answer, of exactly the kind an
NTRO panel would recognise instantly. A self-consistent system cannot detect
this about itself; only an outside implementation can.

**A short stream is not a negative.** A period-192 interleaver in a stream that
only supports searching to L = 168 originally came back as "no code structure
detected" — a false negative wearing the clothes of a confident finding. Every
negative now carries the range it searched and whether stream length is what
stopped it. A rank measurement needs comfortably more rows than columns, so the
searchable period is roughly `sqrt(n_bits)`; `max_searchable_period()` returns
it, and the CLI prints it before anything else.

## Limits, stated

- Block interleavers only. Diagonal and convolutional families land 1 Sep.
- Rate 1/2 unpacks to generators; other rates report n and m but not yet G.
- Period search capped at 512, constraint span at 64, factorisations at 64 —
  the sweep is content-influenced and must not be allowed to run away (risk #5).
- Everything here is on **clean** data. The error-rate behaviour is a separate
  measurement: see `ber_ceiling.md`.
