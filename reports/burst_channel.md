# Stage 4 under realistic errors — the assumption was backwards

**Nehal · 1 September 2026**

Regenerate with `python reports/burst_channel_study.py`. Outputs
`burst_channel.png`, `burst_channel.csv`, `burst_row_damage.csv`.

---

## The correction

Every ceiling measured before today used **independent** bit flips, and every
report carrying those numbers — including `ber_ceiling.md` — called them *"an
optimistic bound"* on the grounds that real demodulator errors are bursty.

That was reasoning, not measurement, and **it was backwards.**

| Error model | Exact rank test | Statistical |
|---|---|---|
| Independent | 0.30 % BER | 3.0 % |
| Mean burst 5 | 0.75 % | ≥ 5.0 % |
| Mean burst 20 | 2.0 % | ≥ 5.0 % |
| Mean burst 100 | **5.0 %** | ≥ 5.0 % |

**The exact rank test's envelope widens roughly 16×** — 0.30 % to 5.0 % — when
the same number of errors arrives in realistic bursts rather than scattered.
5.0 % is the top of the grid, not a measured failure, so the true figure is
higher still.

## Why — and it is not subtle once seen

**Rank collapse counts damaged ROWS, not damaged bits.** A row of the matrix is
ruined by one error exactly as thoroughly as by twenty. So clustering the same
errors into fewer rows leaves more clean rows, and the collapse survives.

At 1 % BER on 96-bit rows:

| Mean burst | Bits in error | Rows damaged |
|---|---|---|
| 1 (independent) | 4 043 | **62.8 %** |
| 5 | 3 998 | 28.1 % |
| 20 | 3 754 | 10.4 % |
| 100 | 3 805 | **3.7 %** |

Same error count. Seventeen times fewer damaged rows.

## The channel

Gilbert–Elliott, the standard model for a receiver that loses runs rather than
scattered symbols: a GOOD state with no errors and a BAD state erring at 50 %
(the demodulator guessing while a loop is unlocked). Parameterised by overall
BER and mean burst length, so the comparison is strictly *same errors,
different clustering* rather than two different channels.

Validated before use: realised BER within 20 % of target across the grid, and
the good/bad dwell times come out as requested.

## What this does NOT say

**It does not mean decoding gets easier.** Bursts are precisely what a
convolutional decoder cannot handle — which is the entire reason interleavers
exist. On the same stream, S4 gets easier and S5 gets harder. The envelope
report has to carry both, and quoting only the first half would be exactly the
kind of selective number this project has been trying not to produce.

**It does not solve interleaver recovery under noise.** This is the honest
counterweight and it is the middle panel of the figure. Recovering the
interleaver's *depth × width* still fails at **any** non-zero BER, under every
error model. Bursts help a great deal — 0 % → 83 % success at 0.1 % BER — but
nothing reaches 100 %, so the ceiling by the strict definition is 0 % across
the board. The pipeline recovers the *code* under noise, via the statistical
fallback, and not the *interleaver*. That remains the open problem and it is
the right thing to spend the Oct–Nov robustness window on.

**It is still a model.** Real errors are not Gilbert–Elliott either. This
converts "we will find out on 3 September" into "we expect roughly this shape,
and here is why", which is worth having two days early — not into a finished
answer. The 3 Sep measurement against Anvith's real LLRs stands.

## Two things found while doing this

**The scrambler in the test fixture was not what it claimed.** The default
`0o177` was commented as "the degree-6 maximal-length polynomial used in
several CCSDS profiles". Its actual period is **7**, not 63. Validating the
7 Sep blind Berlekamp–Massey recovery against a period-7 sequence would have
proved nearly nothing. Replaced with the real CCSDS 131.0-B pseudo-randomiser,
`0o435`, degree 8, period 255 — verified by measuring the period rather than by
reading the polynomial.

**Scrambling does not hide the code from rank collapse.** This matters for the
5 Sep concatenated chain. Scrambling is an *affine* map — XOR with a fixed
sequence — not a linear one, so it could in principle destroy the collapse
entirely. It does not: the deficiency shrinks but stays large and stays at
multiples of the period.

| Row length | Unscrambled | Scrambled (degree 8) |
|---|---|---|
| 96 | 42 | 34 |
| 192 | 90 | 82 |
| 288 | 138 | 130 |

The deficiency lost is the **degree of the scrambler** — the LFSR sequence
satisfies its own linear recurrence, so it adds only that many dimensions to
the row space. Exact in 17 of 18 (polynomial, row length) pairs measured; one
case lost less where the sequence period interacts with the row length, so it
is an indicator rather than a law.

**The consequence: CCSDS can be unwound without descrambling first.** The
period and the interleaver come out of a scrambled stream directly, which
removes the chicken-and-egg the concatenated profile appeared to have.
