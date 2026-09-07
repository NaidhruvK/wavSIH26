# The concatenated CCSDS profile, peeled off blind

**Nehal · 5 September 2026**, extended 6 September. Four coding layers, none
of them supplied. `pipeline/s6_frame/ccsds.py`.

> **Which layer order each half of this report measures.** Everything down to
> "Honest limits" is the **Command Center's stated order** — RS, then a
> **bit**-level interleaver, then the convolutional code, then a scrambler on
> the channel — gated by `tests/unit/test_ccsds_chain.py`. The 6 September
> section at the end is the **real CCSDS 131.0-B transmit order**, which is a
> different chain and not a relabelling of this one, gated by
> `tests/unit/test_ccsds_real_order.py`. Both pass; they are not the same
> claim, and on 5 September only the first one existed.

```
transmit   payload -> RS(255,223) outer -> block interleave 8x12
                   -> convolutional 1/2 K=7 inner -> randomiser
recover    scrambler period -> descramble -> conv -> Viterbi
                   -> de-interleave -> Reed-Solomon -> text
```

| | unscrambled | scrambled |
|---|---|---|
| layers peeled | conv → viterbi → deint → RS | **scrambler → descramble** → conv → viterbi → deint → RS |
| generators | `(0o171, 0o133)` ✔ | `(0o171, 0o133)` ✔ |
| interleaver | `block(8, 12)` ✔ | `block(8, 12)` ✔ |
| outer code | `RS(255, 223)`, offset 0 ✔ | `RS(255, 223)`, offset 0 ✔ |
| printable | **100.0 %** | **100.0 %** |
| payload vs transmit | **byte-exact** | **byte-exact** |
| time | 54.2 s | 55.8 s [†](#the-scrambler-screen-stopped-screening) |

> † **The 55.8 s was measured on code with a correctness bug in it**, and
> after that bug was fixed on 5 September the same arm took **364 s**. It is
> back to 48.7 s as of 6 September, by a different route. Read
> "The scrambler screen stopped screening" below before quoting either
> number.

**Gate met.** *"Full concatenated profile decodes end to end"* and *"known
payload text appears correctly."*

---

## Two things I had wrong, and had to overturn today

### 1. The interleaver is invisible to the rank test in this ordering

Every earlier study in this repo built `conv encode → interleave`, so the
interleaver permuted the convolutional **codeword**. Convolutional constraints
are *local* — span 14 — so permuting them destroys that locality and the rank
deficiency reappears at the interleaver's period. That is why S4 has been able
to read interleaver depth×width off the curve since 29 August.

CCSDS puts the interleaver one layer further in: it permutes the **RS**
codeword, and the convolutional encoder wraps the result. And:

> **A permutation preserves rank over GF(2).**

Reordering coordinates inside the analysis window cannot change the dimension
of a row space. RS(255,223) places its binary-image constraints at a row length
of 2040 bits — an order of magnitude past `MAX_PERIOD` — so there is simply
nothing at any searchable L for the sweep to find.

I did not reason this out; I measured a collapse at L=96 on one file and
reported *"better than I predicted — the interleaver IS visible."* **That was
wrong.** Those deficiencies were the ASCII payload's own structure, and they
moved when I changed the message:

| payload | deficient L, sweeping 8…200 | true period 96 present? |
|---|---|---|
| ASCII (message A) | 96, 122, 183, 192 | appeared to be |
| ASCII (message B) | 112, 147, 168, 192, 196 | **no** |
| **random** | **nothing, at any length to 81 600 bits** | **no** |

A first version of `_interleaver_candidates` ranked candidates from that curve.
It could never have worked; it only looked right on the one file whose payload
happened to collapse near 96. This is the fourth time this week that reading a
curve where only a functional test can decide has produced a wrong answer.

**So the interleaver is found functionally: a bounded (depth, width) grid, with
the Reed-Solomon decoder as the sole judge.** RS is a far stronger oracle than
any rank test — a wrong de-interleaving does not accidentally produce whole
blocks that decode with zero corrections.

### 2. The scrambler's chicken-and-egg is breakable

`descramble.recover_scrambler` needs the code's parity check; the scrambler is
what hides the code. Neither can go first, and `docs/HANDOFF.md` has carried
that as an open problem since 2 September.

The way out is that an additive scrambler is periodic. For a shift `P` that is
a multiple of both the scrambler period **and** the code's symbol size:

```
r[n] XOR r[n+P]  =  c[n] XOR c[n+P]
```

The scrambler cancels, and the XOR of two codewords is another codeword. So `P`
is searched with the **rank test on the self-difference**, which needs no parity
check at all, and the code recovered from the difference stream unlocks
everything downstream. `find_scrambler_period_blind`.

That is why the scrambled arm above peels all four layers rather than three.

## What it costs, and the one number that is a problem

| step | time |
|---|---|
| conv recovery (rank collapse) | ~4 s |
| **Viterbi, 48 000 coded bits** | **~45 s** |
| interleaver grid, 465 pairs, screened | 16.9 s |
| RS confirmation + decode | ~5 s |
| **total** | **~55 s** |

**Viterbi is 80 % of the cost and it is commpy being pure Python** — 163 kbit
takes 167 s, so the chain caps its input at 48 000 coded bits. That is a known,
documented constraint, not a new one.

The interleaver grid was the part that could have killed this. The full
`ReedSolomonCode.blind_recover` costs ~2.2 s per candidate, so reaching an 8×12
interleaver at grid index 190 would have cost **421 s**. A cheap screen — one
RS profile at eight byte alignments, early-exit on the first bad block —
rejects a wrong candidate in **0.038 s**:

| | full oracle per candidate | cheap screen |
|---|---|---|
| whole 465-pair grid | 421 s | **16.9 s** |
| hits returned | — | **exactly one: (8, 12)** |
| false positives | — | **0** |

Same shape as the rotation screening in `s4_recover/rotations.py`: reject
cheaply, confirm expensively, and never let the cheap test be the thing that
makes the claim.

## Honest limits

- **This section is not bit-for-bit CCSDS 131.0-B.** The blue book randomises
  *before* the convolutional encoder and attaches an unrandomised sync marker;
  the fixture above follows the Command Center's stated order (randomiser
  outermost) and interleaves **bits**, where CCSDS interleaves **symbols**
  (bytes) at depth I ∈ {1..8}. Stated on 5 September so nobody would quote it
  as standards-compliant. **Closed on 6 September** — see the section below,
  which measures the real order against a generator built to it.
- **Dheeraj's zoo had no concatenated profile** on 5 September, so this section
  runs against `tests/fixtures/local_zoo.make_ccsds_stream`. **Closed on
  6 September**: `zoo/ccsds.py` and eight files in `zoo/corpus/ccsds/` landed
  on `main` in `bcd0a88`, built to the standard order from a written request.
- **The sync marker is still absent.** CCSDS attaches an unrandomised
  attached sync marker ahead of each frame, and neither the fixture above nor
  the corpus files carry one. Everything here therefore assumes the stream
  starts on a frame boundary. That is frame synchronisation and it is still
  open — see the phase limit in the 6 September section.
- **Zero BER only.** Every number here is a clean stream. The chain inherits
  S4's cliff, so a real capture needs a bit-perfect demodulation before any of
  this runs.
- **The fixture was proven before the recovery was trusted** — descrambling
  with the known polynomial returns the convolutional codeword at residual
  0.000000. `test_the_generator_inverts_with_known_parameters`.


---

# 6 September — the real CCSDS 131.0-B transmit order

**Nehal · 6 September 2026.** Gated by `tests/unit/test_ccsds_real_order.py`
(16 tests, 84 s). Generator: `zoo/ccsds.py`, Dheeraj's, landed today in
`bcd0a88` after the request logged in the limits above.

```
transmit   payload -> RS(255,223) outer -> BYTE interleave (depth I)
                   -> randomiser -> convolutional 1/2 K=7 inner
recover    conv -> Viterbi -> derandomise -> symbol de-interleave
                   -> Reed-Solomon -> payload
```

## What the 5 September chain did with it, before any change

Run unmodified against `zoo.ccsds.make_ccsds_stream` at depths 1 and 4, it
peeled **two layers of four** and then stopped:

```
status   = partial
stages   = conv, viterbi
G        = (0o171, 0o133)          <- exactly right
reason   = "convolutional layer recovered and decoded, but no
            de-interleaving produced a Reed-Solomon codeword"
```

That reason was **true and the search behind it could not have succeeded**,
which is the failure worth removing. Two assumptions broke at once:

| | Command Center order | real CCSDS order |
|---|---|---|
| where the randomiser sits | on the channel, **outside** the code | **inside** the code, above the interleaver |
| what the interleaver permutes | **bits** | **symbols** (bytes of an RS codeword) |
| what survives Viterbi | nothing to descramble | the randomiser, still on the stream |

Neither is a tuning problem. `recover_scrambler` needs a parity check to take
a syndrome against, and after Viterbi the only code left is Reed-Solomon,
whose binary-image constraints sit at L = 2040 — an order of magnitude past
anything the rank sweep reaches. And a **bit**-level de-interleaver of any
(depth, width) cannot undo a permutation that moves whole bytes.

## The change

Two additions, both bounded, both settled by the Reed-Solomon decoder rather
than by any curve:

1. **`CCSDSSymbolInterleaver`** — a fourth registered interleaver family
   (`pipeline/s4_recover/interleavers.py`). Its `rank_signature()` returns
   **0**, meaning "the sweep will not find this one"; returning a row length
   there would be a number the orchestrator would act on and it would be a lie.
2. **`STANDARD_RANDOMISERS`** — a table of published randomisers of the
   declared envelope (`pipeline/s6_frame/descramble.py`), tried **after** the
   null hypothesis. Same move `rs_code.STANDARD_PROFILES` already makes for
   Reed-Solomon: a constant out of a blue book is not truth read from a corpus,
   and a stream matching none of them is declined rather than guessed.

Cheapest hypothesis first: the symbol phase is ten screened de-interleavings
at ~0.04 s plus one full confirmation, against 465 pairs for the bit-level
grid, so the existing path pays about one confirmation and cannot change the
answer it already gave.

## Result — every standard depth, blind

| depth I | status | layers peeled | interleaver found | RS | payload |
|---|---|---|---|---|---|
| 1 | ok | conv → viterbi → derandomise → RS | — (I=1 is the identity) | (255,223) off 0, errata 0.0 | **byte-exact** |
| 2 | ok | + symbol de-interleave | `ccsds-symbol(2)` ✔ | ✔ | **byte-exact** |
| 3 | ok | + symbol de-interleave | `ccsds-symbol(3)` ✔ | ✔ | **byte-exact** |
| 4 | ok | + symbol de-interleave | `ccsds-symbol(4)` ✔ | ✔ | **byte-exact** |
| 5 | ok | + symbol de-interleave | `ccsds-symbol(5)` ✔ | ✔ | **byte-exact** |
| 8 | ok | + symbol de-interleave | `ccsds-symbol(8)` ✔ | ✔ | **byte-exact** |

Generators `(0o171, 0o133)` recovered on all six. Wall clock 25–38 s per file,
measured while the test suite was competing for the machine — treat those as an
upper bound, not as the 5 September numbers' successor.

## The two primitives are pinned against an independent implementation

Both new pieces are checked against **Dheeraj's** code, not against a second
copy of my own assumptions — the same reason `conv_reference` is pinned
against commpy rather than trusted for reading well.

- `symbol_interleave` reproduces `zoo.ccsds.ccsds_interleave` **bit for bit at
  every depth in {1,2,3,4,5,8}**, and round-trips.
- `additive_keystream` reproduces `zoo.bits_only.lfsr_scramble` bit for bit,
  and its period is **measured at 255**, not assumed from the polynomial's
  degree. A fixture in this repo has already carried a polynomial mislabelled
  as maximal-length once (period 7, not 63), which is why that is an assertion.
- A burst test asserts the property the standard exists for, not just the
  permutation's algebra: `depth` consecutive transmitted bytes land in `depth`
  **different** codewords.
- The false-positive guard is restated for the widened search. Every new
  hypothesis is a new way to find something that is not there; uncoded noise
  through the new paths still returns not-`ok` and an empty payload.

## Honest limits, 6 September

- **The randomiser phase is assumed to be 0.** Its period is 255 bits, coprime
  with both the 8-bit symbol and the rate-1/2 code, so a capture that does not
  begin on the randomiser's first bit descrambles to noise. It holds here
  because the convolutional encoder starts on that bit, so Viterbi's output
  does too. A capture starting mid-frame needs a phase search this does not do
  — that is frame synchronisation, and it belongs with the sync-marker work.
- **This is the bits-level chain, not the RF one.** These runs take
  `zoo.ccsds.make_ccsds_stream`'s coded bits directly. The eight WAV files in
  `zoo/corpus/ccsds/` have not been driven end to end from the waveform;
  Dheeraj's own note on `bcd0a88` says a full RS decode through the real
  channel needs a byte-alignment search across a non-conv-aligned offset from
  the RRC filter's edge transients. **That is mine, and it is not done.**
- **Zero BER.** As on 5 September, every number here is a clean stream.


---

## The scrambler screen stopped screening

**6 September.** Found by timing the suite, not by a failing test - every test
passed throughout.

The 5 September table above put the scrambled arm at **55.8 s**, 1.6 s more
than the unscrambled arm. That should not have been believable on its face: the
scrambled arm does everything the unscrambled one does *plus* a self-difference
search over 255 shifts, each of which can pay for a full `blind_recover`. I did
not question it at the time.

### What happened

`b431082`, late on 5 September, moved `SCREEN_ROW_LEN` from **14** to **60**.
That was a correct fix and the reasoning in the commit still stands: 14 is the
constraint span of rate-1/2 K=7 and *nothing else*, so a screen at 14 rejected
rate-1/2 K=9 and rate-1/3 K=7 outright - it was a false-negative generator for
most of the declared envelope.

What it did not notice is the test on the other side of the screen. The
condition was `deficiency > 0`, and at L=60 that is satisfied by **everything**:

| `SCREEN_ROW_LEN` | shifts searched | shifts passing the screen |
|---|---|---|
| 14 (before `b431082`) | 255 | **1** |
| 60 (after `b431082`) | 255 | **255** |

So every shift paid for a full `blind_recover`, and `find_scrambler_period_blind`
went from about a second to **268 s** - past the 90 s core-lock budget for the
entire seven-stage analysis, on one function, silently. The whole scrambled arm
measured **364 s** tonight against the 55.8 s still printed above it.

### Why a bare threshold cannot work here, at any row length

This is structural, not a tuning miss, and it is worth stating because the
obvious repair - pick a better `SCREEN_ROW_LEN` - does not exist.

The method rests on the sum of two codewords being a codeword. That is true at
**every** shift which is a whole number of code symbols, not only at the
scrambler's period. So the code's own deficiency is present at every shift in
the search, and what distinguishes the true one is only that the residual
scrambler term vanishes there. At L=14 the code contributes a deficiency of
just 1, so the residual buries it everywhere except the true shift - the old
screen worked by sitting exactly on that margin, which is not a property to
build on. At L=60 the code contributes 24 and survives the residual everywhere.

What still separates them cleanly is the **size** of the collapse:

| | deficiency at L=60 |
|---|---|
| 254 wrong shifts | **16** (min = median = max) |
| the true shift, 510 | **24** ( = L/n - m for rate 1/2, K=7) |
| wrong shifts scoring ≥ the true one | **0 of 254** |

### The fix: the screen ranks, it does not threshold

Sweep the deficiency for all 255 shifts - 255 rank computations, ~0.1 s - take
the **median** as the floor the residual imposes, and pay for a recovery only
on shifts standing above it, capped at `SCRAMBLER_SHIFT_CANDIDATES = 6`. No
knowledge of *n* or *m* is used, the expensive oracle still makes every claim,
and a stream with no scrambler gives a flat profile, no candidates, and a cheap
honest "no".

| | before | after |
|---|---|---|
| `find_scrambler_period_blind` | 268.1 s | **5.1 s** |
| scrambled arm, end to end | 364.3 s | **48.7 s** |
| `tests/unit/test_ccsds_chain.py` | 640 s+ | **205 s** |
| answer returned | shift 510, `(0o171, 0o133)` | **identical** |

`b431082`'s correctness fix is kept in full - the screen still runs at L=60 and
still covers every code in the envelope.

### The guard that was missing

`test_the_scrambler_screen_actually_screens` now asserts the search returns
shift 510 **and** completes inside 60 s. The bound is deliberately loose: it
exists to catch a 50x regression on a busy machine, not to measure performance.

The lesson is the one this file already carries twice. The screen had a test
for the half of its job that can fail loudly - "never a cheap yes" - and none
for the half that fails silently. A screen that admits everything is not a
screen, and nothing in a green suite says so. **Only the clock knew.**


---

## The randomiser in the corpus is not the randomiser in the blue book

**6 September.** Found by checking a constant against the standard instead of
against our own code, which is the only way this class of thing is ever found.

`zoo/bits_only.py` carries

```python
# Real CCSDS 131.0-B pseudo-randomiser: h(x) = x^8+x^7+x^5+x^3+1, period 255.
CCSDS_SCRAMBLER = 0o435
```

The comment and the constant are different polynomials:

| | value | polynomial |
|---|---|---|
| `0o435` (what the corpus applies) | 285 = `0x11D` | x⁸ + x⁴ + x³ + x² + 1 |
| CCSDS 131.0-B (what the comment names) | 425 = `0x1A9` = `0o651` | x⁸ + x⁷ + x⁵ + x³ + 1 |

No reading reconciles them — the reciprocal of `0o435` is `0o561`, still not
`0o651`. `0x11D` is the **GF(256) field polynomial of Reed-Solomon**, which is
a very plausible thing to have reached for while writing an RS-and-randomiser
generator.

**It is a mislabel, not a malfunction.** Both polynomials are primitive of
degree 8 — measured, both give period 255 — so the corpus is a valid
period-255 additive scrambler, self-consistent between generator and receiver,
and every recovery number measured against it stands unchanged.

**What it would have broken is the only thing `STANDARD_RANDOMISERS` exists
for.** That table is the "try the published profiles of the declared envelope"
move, the same one `rs_code.STANDARD_PROFILES` makes. A table whose standard
entry is not the standard declines the one stream it was written to catch: a
real CCSDS downlink would have been handed to it and refused. I had inherited
the constant straight from the corpus without checking it, so my own new code
carried the same error for about an hour.

Both are now carried, the blue book's first:

```python
CCSDS_RANDOMISER = 0o651   # x^8+x^7+x^5+x^3+1, CCSDS 131.0-B
CORPUS_RANDOMISER = 0o435  # x^8+x^4+x^3+x^2+1, what zoo.bits_only applies

STANDARD_RANDOMISERS = [
    ("ccsds-131.0-B",    CCSDS_RANDOMISER,  0xFF),
    ("zoo-corpus-0o435", CORPUS_RANDOMISER, 0xFF),
]
```

Cost of the extra hypothesis is one screened pass on the failure path. Pinned
by `test_the_blue_books_randomiser_is_in_the_table_and_is_not_the_corpus_one`,
which asserts the tap sets `{8,7,5,3,0}` and `{8,4,3,2,0}` explicitly and
re-measures both periods, so neither can be quietly swapped back.

**Dheeraj should decide what happens to the corpus.** Either the comment is
corrected — cheapest, and nothing downstream moves — or the constant is, which
means regenerating `zoo/corpus/ccsds/` and re-running anything measured against
it. My receiver works either way. What must not survive is a corpus file
labelled CCSDS-conformant that is not, because that is precisely the claim this
whole report is careful not to make.
