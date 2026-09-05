# The concatenated CCSDS profile, peeled off blind

**Nehal · 5 September 2026.** The 5 September column. Four coding layers, none
of them supplied. `pipeline/s6_frame/ccsds.py`, gated by
`tests/unit/test_ccsds_chain.py`.

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
| time | 54.2 s | 55.8 s |

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

- **This is not bit-for-bit CCSDS 131.0-B.** The blue book randomises *before*
  the convolutional encoder and attaches an unrandomised sync marker; my
  fixture follows the Command Center's stated order (randomiser outermost) and
  interleaves **bits**, where CCSDS interleaves **symbols** (bytes) at depth
  I ∈ {1..8}. That matters for interoperating with a real downlink and does not
  matter for what this tests — whether four layers can be peeled in sequence
  without being told any of them. Stated so nobody quotes it as
  standards-compliant.
- **Dheeraj's zoo has no concatenated profile**, so this runs against
  `tests/fixtures/local_zoo.make_ccsds_stream`. That is one of the three cases
  `local_zoo` is deliberately retained for. **Requesting a CCSDS profile in the
  corpus** — it is the only layer of the envelope with no corpus file.
- **Zero BER only.** Every number here is a clean stream. The chain inherits
  S4's cliff, so a real capture needs a bit-perfect demodulation before any of
  this runs.
- **The fixture was proven before the recovery was trusted** — descrambling
  with the known polynomial returns the convolutional codeword at residual
  0.000000. `test_the_generator_inverts_with_known_parameters`.
