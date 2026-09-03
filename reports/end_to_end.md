# The full chain through a real receiver — measured

**Nehal · 4 September 2026.** My Stage 4–6 against Anvith's Stage 3, through a
real modulator and channel. Regenerate with
`python reports/end_to_end_study.py`.

Supersedes the 3 September version of this file. **That version's numbers were
right and its explanation of them was wrong** — see "Correcting yesterday"
below. Measured against `origin/main` at `093f431`, so Anvith's roll-off fix
and tap caps are in the path.

```
payload -> conv encode 1/2 K=7 -> block interleave 8x12 -> QPSK
        -> AWGN + CFO + fractional timing offset
        -> S3 demodulate blind -> LLRs
        -> S4 recover interleaver and code blind
        -> S5 Viterbi -> S6 payload
```

Two arms, identical except for the payload: one carrying random bits, one
carrying ASCII text. 3 seeds x 6 SNRs each, 36 files.

---

## The numbers

`raw BER` is the best rotation after FFT cross-correlation alignment, counting
a fully inverted stream as a match.

| Arm | SNR | raw BER | interleaver + code recovered | message readable |
|---|---|---|---|---|
| random | 16 dB | 0.00000 | **3/3** | n/a |
| random | 14 dB | 0.00000 | **3/3** | n/a |
| random | 12 dB | 0.00000 | **3/3** | n/a |
| random | 10 dB | 0.00000 | **3/3** | n/a |
| random | 8 dB | 0.00000 | **3/3** | n/a |
| random | 6 dB | 0.00006 | 0/3 | n/a |
| text | 16 dB | 0.00000 | **3/3** | **3/3** |
| text | 14 dB | 0.00000 | **3/3** | **3/3** |
| text | 12 dB | 0.00000 | **3/3** | **3/3** |
| text | 10 dB | 0.00000 | **3/3** | **3/3** |
| text | 8 dB | 0.00000 | **3/3** | **3/3** |
| text | 6 dB | 0.00005 | 0/3 | 0/3 |

**30 of 36 recover. 15 of 18 text files print the message**, at a printable
fraction of 1.000. Yesterday those columns read 15 of 36 and **0 of 18**.

Timing, whole chain per file including Viterbi: median 24 s, max 50 s. The 90 s
per-analysis budget holds with room, and the maximum is a 6 dB file — the ones
that fail are the ones that cost most, because nothing short-circuits.

**The two arms now agree.** They differ only in payload, so any gap between
them was always a bug rather than a result. That sentence is the whole of
yesterday's finding, and it is now an assertion in
`tests/unit/test_structured_source.py::test_random_and_text_arms_agree`.

## Blind in, message out — through the real receiver, for the first time

Yesterday's file said this plainly:

> The readable-text demo has never run through the real receiver. It works
> through the synthetic zoo, where the payload goes straight to the encoder.

That is no longer true, and it was not true for the reason anyone thought.

```
16 dB, text arm, seed 1, rotation 0
period=96  block(depth=8,width=12)  rate 1/2 K=7  G=(0o171, 0o133)
printable : 100.0%
plied. RAAYA SIH26147 -- this message went through a modulator, a noisy
channel and a blind receiver. Nothing about the interleaver or the code...
```

Nothing about that file was supplied: not the modulation, not the symbol rate,
not the interleaver, not the code, not the generators, not the polarity.

## Correcting yesterday

Yesterday's report named `detect_signature` taking the smallest collapse as
the cause, and said a structured payload "defeats it entirely, at every SNR".
**I checked that before fixing it, and it does not reproduce.**
`detect_signature` returns the true period 96 on every rotation of every file
in the text arm, and the transmitted stream recovers cleanly at every start
offset. The measurement was real; the mechanism I attached to it was not.

What actually happened was one step further on, and it took three separate
defects lining up:

**1. A false positive won the rotation ranking.** On the *wrong* rotations the
statistical fallback returned `ok` at 0.59 with "period=4, rate 1/2 K=2" — a
memory-1 artefact of ASCII, not a code. The study ranks rotations by shortest
constraint span, so span 4 beat the true span 14 and the garbage rotation won.
Every text row was decided by a rotation that should have declined. The
correct rotations were sitting right there returning `period=96,
block(8,12), G=(0o171, 0o133)`.

**2. De-interleaving destroyed the LLRs.** Every function in
`interleavers.py` began `np.asarray(bits, dtype=np.uint8)`. A permutation does
not care what it is permuting, so that cast bought nothing and silently
truncated every soft value handed to it. De-interleaving a real receiver's
output returned an array of zeros, and Viterbi decoded zeros into zeros.

This is the 3 September `harden` bug one stage further along — that one was
`blind_recover` assuming hard bits at its entry, this one is the
de-interleavers assuming them at theirs. It hid because the *recovery* path
hard-slices by design, so only the *decode* path was affected, and every test
before today de-interleaved zoo bits. `tests/contract/test_llr_contract.py`
has carried the rule since 2 Sep — "an integer dtype destroys the soft
information" — and asserted it of S3's output, never of anything consuming it.

**3. Polarity.** With the LLRs surviving, the chain decoded — to the
complement of the message. A coherent receiver cannot tell 0° from 180°, so
half of S3's rotations carry the stream inverted; the rank test is blind to
inversion, so both recover identical parameters and both decode without
complaint. Measured on one file: rotation 2 printable 1.000, rotation 0
printable 0.001, same parameters. The study picks by rotation index and got
the inverted one.

This is **risk #9 arriving exactly as the register worded it** — "decode
succeeds but bits are inverted". The printable fraction was already the
evidence needed to settle it, so `extract_text` now reads both polarities and
keeps the better one, reporting which it used.

Three defects, one visible symptom. The first is why nothing was recovered,
and the second and third are why nothing would have been readable even if it
had been.

## What was fixed, and the one thing that was not

Four paths could return `ok` on a structured source; all four are closed and
the guards now meet at a single exit (`_finalise`). Details in the commits and
in `tests/unit/test_structured_source.py`.

**Still open, and now measured rather than assumed.** An interleaved stream
carrying a *short repeating* payload is refused, not recovered. Two things
defeat it, and only the first was known:

- its own periodicity collapses before the interleaver's — a repeating
  11-character payload collapses at L=44 against a true period of 96. The
  candidate walk handles this: `iter_signatures` offers later collapses.
- the block-boundary offset is chosen by argmax of deficiency, and on a
  structured source that argmax carries **no signal at all**. Measured across
  three fixtures, the true offset sits within **one** of the maximum while
  ranking 39th, 59th and 71st of 96.

So the alignment cannot be resolved from the curve — exactly as the family
cannot (block and diagonal are byte-identical, 1 Sep) and the period cannot.
It needs the same treatment, a functional test per candidate, and that costs a
family search per offset, which does not fit the budget. Deferred with a test
that fails loudly if it ever improves on its own.

This does not affect the demo message, whose own period is longer than the
interleaver's, and it does not affect random payloads. It would affect real
telemetry with short repeating frame headers, which is why it is written down
rather than filed away.

## The threshold is still zero bit errors

Unchanged from yesterday, and it is physics rather than a bug. Every success
sits at raw BER exactly 0.00000; the step to 5e-5 takes recovery from 3/3 to
0/3. There is no degradation region for the *exact* rank test, and the
statistical fallback cannot help because it recovers the code, not the
interleaver's factorisation.

**For the demo this is the number that governs**: the chain needs an SNR high
enough for a bit-perfect demodulation, not merely a good one. On this channel,
QPSK, that is 8 dB. Anyone quoting the 5% burst-error ceiling from
`burst_channel.md` must say in the same breath that it is the ceiling for
recovering the CODE from an already-de-interleaved stream, not for this chain.
