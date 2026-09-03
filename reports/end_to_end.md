# The full chain through a real receiver — measured

**Nehal · 3 September 2026.** First systematic end-to-end run: my Stage 4–6
against Anvith's Stage 3, through a real modulator and channel. Regenerate with
`python reports/end_to_end_study.py`.

```
payload -> conv encode 1/2 K=7 -> block interleave 8x12 -> QPSK
        -> AWGN + CFO + fractional timing offset
        -> S3 demodulate blind -> LLRs
        -> S4 recover interleaver and code blind
```

Two arms, identical except for the payload: one carrying random bits, one
carrying ASCII text. 3 seeds x 6 SNRs each, 36 files.

---

## The numbers

`raw BER` is the best rotation after FFT cross-correlation alignment, counting
a fully inverted stream as a match.

| Arm | SNR | raw BER | S4 recovered the interleaver |
|---|---|---|---|
| random | 16 dB | 0.00000 | **3/3** |
| random | 14 dB | 0.00000 | **3/3** |
| random | 12 dB | 0.00000 | **3/3** |
| random | 10 dB | 0.00000 | **3/3** |
| random | 8 dB | 0.00000 | **3/3** |
| random | 6 dB | 0.00006 | **0/3** |
| text | 16 dB | 0.00000 | **0/3** |
| text | 14 dB | 0.00000 | **0/3** |
| text | 12 dB | 0.00000 | **0/3** |
| text | 10 dB | 0.00000 | **0/3** |
| text | 8 dB | 0.00000 | **0/3** |
| text | 6 dB | 0.00004 | **0/3** |

**15 of 36.** The 3 Sep gate asks for "at least one real end-to-end file at
high SNR", so it passes — but that is a floor, and the shape of the 15 matters
far more than the count.

## What the numbers actually say

**1. The threshold is zero bit errors, not low BER.**

Every success sits at raw BER exactly 0.00000. The single step from 0 to
6e-5 — six errors in a hundred thousand bits — takes recovery from 3/3 to 0/3.
There is no degradation region. This independently reproduces Anvith's claim 1
from the other side of the junction, and it is the number that should govern
the demo: **the chain needs an SNR high enough for a perfect demodulation, not
merely a good one.** For QPSK on this channel that is about 8 dB.

**2. A structured payload defeats it entirely, at every SNR.**

This is the finding I did not have this morning and it is the more serious one.
The text arm fails **0/18 — including at 16 dB with a demodulation that has
zero bit errors.** It is not a noise problem at all.

ASCII has bit 7 clear in every byte, so the source is rank-deficient before the
code touches it. When the source's own periodicity is shorter than the
interleaver period, that collapse comes first and `detect_signature` takes the
smallest. Measured directly on the transmitted stream: a repeating
11-character payload puts the first collapse at L=33, a 162-character one at
L=54. The true interleaver period, 96, is never reached.

**3. On the correct rotation it returns `ok` with garbage, rather than
declining.**

At 16 dB, text arm, the rotation with a perfect demodulation returns:

```
status=ok  confidence=0.62  period=4  K=1  generators=None  interleaver=NONE
```

The three wrong rotations return `low_confidence`. So the *correct* one
produces the most confident nonsense. That is the failure mode this project has
worked hardest to avoid, and it is present.

**4. It also breaks the rotation-selection rule I endorsed this morning.**

I verified Anvith's recommendation — rank rotations by shortest constraint span
— and reported that it resolves the phase ambiguity completely. On a clean
synthetic stream it does. Here it does not: the garbage answer has span 4,
which is the *shortest*, so shortest-span actively selects it. The rule is
sound only when the code is the sole source of structure. **That correction
belongs on my earlier claim, not on Anvith's report** — his statement was about
rotations on an unstructured stream and remains correct there.

## What this means for the demo

Stated plainly, because it is easy to overclaim from the 15/36:

- **Random payload, zero bit errors: the chain works end to end**, with the
  interleaver, the code and both generators recovered from a real receiver's
  LLRs. That is real and it is new today.
- **The readable-text demo has never run through the real receiver.** It works
  through the synthetic zoo, where the payload goes straight to the encoder. It
  does not survive the structured-source problem above. Anyone showing
  `--demo --text` should say it is a zoo file, not a received signal.
- The gap between those two sentences is the honest state of the pipeline
  tonight.

## Corrections to earlier claims

- **`reports/end_to_end.csv` as first committed was meaningless.** raw BER was
  computed without alignment and read ~0.49 at every SNR, because the receiver
  has group delay and the streams were simply not lined up. Every row said
  `recovered=0`. Replaced.
- **My "gate PASS" was based on one hand-run case**, not this sweep. It happens
  to hold, but it was thin evidence when I reported it.
- **"Shortest span resolves the phase ambiguity"** is true only for
  unstructured sources. See point 4.

## What to fix, in order

1. `detect_signature` must not take the smallest collapse unconditionally. The
   interleaver period is the one whose *deficiency profile* matches an
   interleaver rather than a source artefact — a collapse at a period that does
   not also produce a consistent code after de-interleaving should be skipped
   rather than accepted.
2. Returning `ok` at 0.62 with `period=4, K=1, generators=None` is wrong on its
   face. A result with no generators and no interleaver is not `ok`.
3. Only then re-run this study. The 6 dB row will not move — that is physics,
   not a bug.
