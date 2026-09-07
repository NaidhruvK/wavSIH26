# The full chain through a real receiver — measured

**Nehal · 4 September 2026.** My Stage 4–6 against Anvith's Stage 3, through a
real modulator and channel. Regenerate with
`python reports/end_to_end_study.py`.

Supersedes the 3 September version of this file. **That version's numbers were
right and its explanation of them was wrong** — see "Correcting yesterday"
below. Measured against `origin/main` at `093f431`, so Anvith's roll-off fix
and tap caps are in the path.

**Re-measured 6 September, and one number moved.** `anvith/s3-robustness`
deleted `tests/fixtures/rf_channel.py`; this study was the last file importing
it and is now on `tests.fixtures.corpus.synth`. **The channel implementation
changed underneath the study**, so every number below was re-run rather than
carried over — the 4 September figures had been measured by code that no
longer exists. All 36 rows reproduce the same verdicts (30/36 recover, 15/18
print). The printable fraction did not: see below. `reports/end_to_end.csv` is
the re-run.

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
fraction of **0.9993 to 1.000** — 8 of the 15 at 1.000, 7 at 0.9993, which is
one non-printing byte in a 1400-byte payload. Yesterday those columns read
15 of 36 and **0 of 18**.

**The 0.9993 is one byte, and it is measured rather than reasoned about.**
Decoding 16 dB / seed 1 and counting: the payload is **1499 bytes with exactly
one non-printing byte, at position 0** — value `0xBC`, and 1 - 1/1499 = 0.9993.
It is the leading partial byte, where the decode starts mid-message: the
recovered text below begins `plied. RAAYA SIH26147`, mid-word, because nothing
in this chain does frame synchronisation and the payload has no sync marker to
align to. So it is a byte-alignment boundary artifact, not noise surviving the
decode — `raw_ber` is 0.00000 on every one of these rows.

The 4 September version of this file published a flat 1.000. **That figure came
from the deleted channel and it is the only number the re-run changed.** Which
of the two is "right" is not a question I can settle: the channel that produced
the 1.000 no longer exists to measure against. What can be said is that the
verdict columns are unmoved and the delta is one boundary byte, which is the
same absent-frame-sync gap already recorded under Limits.

Timing, whole chain per file including Viterbi: median 26 s, max 47 s. The 90 s
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
printable : 99.93%
plied. RAAYA SIH26147 -- this message went through a modulator, a noisy
channel and a blind receiver. Nothing about the interleaver or the code...
```

### Exactly what was blind, and what was not

An earlier draft of this section said "nothing about that file was supplied".
**That was an overclaim and it is corrected here.** `run_one` calls
`MODULATIONS["qpsk"].receive(iq, {"fs": ..., "symbol_rate": ...})`, so:

| Supplied to the receiver | Recovered blind |
|---|---|
| the modulation family (`qpsk`, chosen by name) | RRC roll-off beta |
| the sample rate | carrier phase and CFO |
| the symbol rate | symbol timing offset |
| | the phase-rotation ambiguity |
| | interleaver family, period and depth x width |
| | the block alignment |
| | code rate, constraint length, both generator polynomials |
| | payload polarity |

The two supplied values are S2's job, and **S2 does not exist yet** - Dheeraj
has no commits. The classifier that picks the modulation and the symbol-rate
estimator that feeds `sps` are both his 1-2 Sep column. So the correct claim
today is: *everything from the matched filter onward is blind.* When S2 lands,
this study should stop passing `fs` and `symbol_rate` from the ChannelSpec and
take them from S2's output instead, and these numbers must be re-measured.
Until that happens, quoting this as a fully blind chain is wrong.

### And what this is NOT

**No off-air signal has ever been through this pipeline.** `rf_channel.py` is a
synthetic channel: RRC pulse shaping, AWGN, a constant CFO, a fixed fractional
timing offset. Real captures bring multipath, interference, AGC transients,
phase noise, non-constant CFO drift and burst fading, none of which is modelled
here. That is risk #8 in the register - over-fitting to our own zoo - and the
plan's answer is the 21 Sep - 20 Oct window: RTL-SDR captures, SatNOGS audio
through the .wav path, and gr-satellites as an independent oracle.

Nothing in this report should be read as evidence about real signals. It is
evidence that the algorithm chain is correct against a channel we wrote
ourselves, which is a necessary step and not the same claim.

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
the inverted one. (Those two figures are on the 4 September channel. The
6 September re-run reproduces the same contrast on the same file at 0.9993
against 0.0007 — the conclusion is unchanged, and the 0.0007 is the same
single boundary byte counted from the other polarity.)

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

**For the demo this is the number that governs, and it is the single biggest
risk to a real-data demonstration**: the chain needs an SNR high enough for a
bit-perfect demodulation, not merely a good one. On this channel, QPSK, that is
8 dB. A real capture that demodulates at 1e-5 raw BER - which most would call
an excellent link - recovers **nothing**. Risk #1 in the register is worded as
"S4 works on injected errors, fails on real LLRs"; the measured shape of that
risk is not a gentle degradation but a cliff at the first bit error. Anyone quoting the 5% burst-error ceiling from
`burst_channel.md` must say in the same breath that it is the ceiling for
recovering the CODE from an already-de-interleaved stream, not for this chain.
