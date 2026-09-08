# Adversarial input to S3 — every case returns a status, never a traceback

8 Sep, the "break it deliberately" row. Six named inputs, each over
8 seeds, through **both** the named-plug-in path and the blind
search the service actually calls. Regenerate with
`python reports/s3_adversarial_study.py` (`--render-only` re-renders
this file from `s3_adversarial.csv`; `--write-files` rewrites the six
`.wav` files under `reports/s3_adversarial/`).

## 1. The known-answer cell, first

`control: clean qpsk` is a 20 dB QPSK capture with the correct sample
rate. It reads `ok` on **8 of 8** seeds, modulation
`qpsk`, worst measured BER
**0.00e+00** over 8 seeds — scored with the repo's
own `corpus.measured_ber`. If that row is not `ok` this harness is broken
and no other row in this file means anything. **It has already fired once
today**: the first draft hand-rolled its own transmitter and the control
came back `low_confidence` on 8 of 8, which is what exposed that three of
the six cases were being built on a signal S3 already refused.

## 2. The definition of done

| question | result |
|---|---|
| tracebacks, every path, every case | **0** of 504 runs |
| statuses outside `ok`/`low_confidence`/`failed`/`out_of_envelope` | **0** |
| non-finite values in an LLR array | **0** |
| **`ok` on a case with no signal in it** | **0** of 280 |

The last row is the one that matters, and it is deliberately not "`ok` on
any adversarial case". Those are two different questions — see §3.

## 3. Absence versus damage

**`ok` is forbidden on the absence cases** (pure noise, DC, empty band,
all zeros, single impulse): nothing is transmitting, so a lock is a
confident lie. This is S3's half of the day's gate item, the same question
Nehal's column asks of S4 as "uncoded random data must not produce a false
code detection".

**`ok` is correct on the degraded cases** (clipped, two overlapping, wrong
sample rate) when the answer is right — a signal IS present. Scoring these
the same way would have marked the clipped row a defect: QPSK is
constant-modulus, clipping at a quarter of peak takes peak-to-average from
1.72 to 1.02 and leaves the symbols intact, so a receiver that refused it
would be worse, not safer.

## 4. The six, through the blind search

The path the service takes: `estimate()` on the input, then `receive_best`
over S2's ranked hypotheses.

| case | class | declared fs | statuses over seeds | modulation | reported Rs | measured BER | worst s |
|---|---|---|---|---|---|---|---|
| control: clean qpsk | control | 200,000 | 8x `ok` | `qpsk` | 50,000 | 0.00e+00–0.00e+00 | 1.06 |
| pure noise | absence | 200,000 | 8x `failed` | `2fsk` | 58,954 | — no reference | 0.23 |
| DC only | absence | 200,000 | 8x `failed` | — none claimed | — | — no reference | 0.05 |
| clipped (saturated) | degraded | 200,000 | 8x `ok` | `qpsk` | 50,000 | 0.00e+00–0.00e+00 | 1.01 |
| two overlapping signals | degraded | 200,000 | 8x `low_confidence` | `16qam`, `2fsk`, `4fsk`, `8psk` | 50,000 | 4.81e-01–4.86e-01 | 6.58 |
| empty band | absence | 200,000 | 7x `failed`, 1x `low_confidence` | `16qam` | 12,515 | — no reference | 2.50 |
| wrong sample rate | degraded | 48,000 | 8x `ok` | `qpsk` | 12,000 | 0.00e+00–0.00e+00 | 1.06 |

### The one real finding: a wrong `fs` is invisible, by construction

`wrong sample rate` is a clean 200 kHz QPSK capture whose header says
48 kHz. S3 returns `ok`, modulation `qpsk`, measured BER
0.00e+00 — a **completely correct
demodulation** — and reports `symbol_rate_used` of
12,000 Hz against a true 50,000 Hz.

That ratio is exactly 48000/200000. Every stage of S3 works on
`fs / symbol_rate` — samples per symbol — so a declared `fs` wrong by a
factor *k* produces a symbol rate wrong by the same *k*, a residual CFO
wrong by the same *k*, and **every internal consistency check passing**,
because all of them are ratio-based. `sps_estimated` still reads 4.00007.

**This is not a defect in S3 and S3 cannot fix it.** Absolute time is not
in the samples; it arrives only from the WAV header or the service's
`fs_hint` form field. But it is a confidently-wrong *number* in a
user-visible field carried under an `ok` status, and it is reachable by a
judge in five seconds without touching the signal. The honest statement is
that every absolute-frequency quantity S3 reports is *proportional to the
declared sample rate*, and is only as trustworthy as that header.

### 4.1 A refused result still carries a modulation name

On **1 of 8** pure-noise seeds the search runs far enough
to name a modulation before refusing, and `values['modulation']` is left
populated on the refused result — `2fsk` at 58,954 Hz, with `n_llrs` 0 and
`status` `failed`. The contract holds: the status is the refusal and there
is no stream attached to the claim.

It is still worth stating, because the failure it invites is a consumer
that reads `values['modulation']` without reading `status` first, and gets
"2fsk" for a band containing nothing but noise. Every consumer in this
repo reads `status` first and none is affected today. **Flagged rather than
changed**: blanking the field would lose the diagnostic that says which
hypothesis got furthest, which is what makes a refusal debuggable — the
house rule is that a check which cannot see must SAY so, and this one does.

### 4.2 The most expensive input in the set is a realistic one

`two overlapping signals` runs to the chain-run ceiling (12)
on every seed and costs **6.15–6.58 s** here. The next
most expensive adversarial case peaks at 2.50 s (`empty band`, on
the one seed in eight where it also runs to the ceiling) and the rest are
under 1.1 s.
That is the correct behaviour — there is no right answer to converge on, so
the search exhausts its list — but it is the number to carry into a budget
discussion, because two emitters in one band is not a contrived input.

On the slower dev box (measured at 2.09x this one, 7 Sep) that is roughly
**13.8 s against the 20 s budget** — inside it, with the
smallest margin of anything measured this week. The corpus worst case is
6.97 s here for comparison, so this input is not an outlier in cost; it is
simply the first adversarial one measured at all.

The modulation claimed varies across 4 families by seed
(`16qam`, `2fsk`, `4fsk`, `8psk`) while the measured BER stays at
0.48 — a coin flip. A receiver with no stable preference, saying
`low_confidence` every time, is exactly the honest signature for an input
with two right answers and no way to choose.

## 5. The same inputs through every named plug-in

`MODULATIONS[name].receive(iq, params)` with a plausible rate — what the
4 Sep unit tests cover. Kept so the two paths can be compared: a plug-in
handed an explicit rate has no search, no rescue and no deadline.

| case | statuses over all plug-ins x seeds | `ok` | tracebacks |
|---|---|---|---|
| control: clean qpsk | 40x `low_confidence`, 8x `ok` | 8 | 0 |
| pure noise | 48x `failed` | 0 | 0 |
| DC only | 48x `failed` | 0 | 0 |
| clipped (saturated) | 40x `low_confidence`, 8x `ok` | 8 | 0 |
| two overlapping signals | 48x `low_confidence` | 0 | 0 |
| empty band | 48x `failed` | 0 | 0 |
| wrong sample rate | 40x `low_confidence`, 8x `ok` | 8 | 0 |

## 6. Degenerate extras

Not named by the row; carried since 4 Sep and re-measured here because
they cost nothing once the harness exists. Both are absence cases.

| case | blind search | plug-in path |
|---|---|---|
| all zeros | 8x `failed` | 48x `failed` |
| single impulse | 8x `failed` | 48x `failed` |

## 7. The six files

`--write-files` writes seed 0 of each case to `reports/s3_adversarial/`
as a stereo (I, Q) WAV at the declared rate, the same format
`zoo/rf.write_wav_pair` produces, so they ingest through S0 like any
corpus file. They are **not** in `zoo/corpus/rf/` on purpose: every S3
study globs that directory and six extra files would silently move the
denominator of every corpus number in this project.

## 8. What the six files found OUTSIDE S3 — for Naidhruv, and one for Dheeraj

Running the six through `python -m service.cli analyze` end to end (S0-S6,
no tracebacks, every stage returned a status) shows the whole chain's
verdict on a file containing nothing but noise:

| stage | status | confidence | what its own values say |
|---|---|---|---|
| s0_ingest | `ok` | 1.00 | a valid WAV — true |
| s1_detect | `ok` | **0.98** | `snr_db` **−10.2**, `occupied_bw` 198 kHz of 200, `burst_count` 0 |
| s2_estimate | `ok` | **0.90** | `symbol_rate` 45,350 Hz, `symbol_rate_score` **0.0** |
| s3_receive | `failed` | 0.00 | `signal_present: fail`, metric 3.83 against 4.5 |

**S3 is the first stage in the chain that refuses pure noise.** The final
answer is therefore correct — but a judge reads the stage cards on the way
to it, and three of them are green and confident on an empty band. That is
Command Center risk #15 ("false positive: claims a code where none
exists — a judge WILL try this") rendered on screen, and the 8 Sep gate
calls the false-positive test mandatory for exactly this reason.

**Neither of Dheeraj's stages is at fault, and this was checked rather than
assumed.** `s1_detect.detect()` returns `status="ok"` whenever it did not
raise and the array is non-empty — it carries no detection predicate at
all, because S1 is a measurement stage (PSD, SNR, occupied BW, bursts) and
not a decision stage. Its numbers are honest: −10.2 dB SNR and 99% of the
band occupied is precisely what noise looks like. The status is right and
the *confidence attached to it downstream* is what is wrong.

**Two things in `service/orchestrator.py`, both in the adapters:**

1. **`adapt_s1` (line 293) hardcodes `confidence=0.98` for any `ok`.** It
   means "the stage ran", but it renders as a detection confidence. Every
   number needed to compute a real one is already in `values` three lines
   above — `snr_db`, `occupied_bw_hz`, `burst_count`. The attached
   hypothesis has the same shape: `"continuous"` at score **0.95**, with
   `evidence="0 bursts detected"` — a 95% score whose stated evidence is
   that nothing was found.

2. **`adapt_s2` (line 338) inverts its own confidence at zero.** The line is
   `min(1.0, max(0.1, score / 10.0)) if score else 0.9`. A `symbol_rate_score`
   of exactly **0.0** is falsy, so it takes the `else` branch and renders
   **0.90**:

   | `symbol_rate_score` | rendered confidence |
   |---|---|
   | **0.0** | **0.90** |
   | 0.5 | 0.10 |
   | 1.0 | 0.10 |
   | 5.0 | 0.50 |
   | 9.0 | 0.90 |

   No evidence at all reports the same confidence as a score of 9, and
   **nine times** the confidence of a score of 0.5. The guard is testing
   truthiness where it means "is present", and 0.0 is both present and the
   worst possible score. `pure_noise.wav` hits it on every run.

Neither is S3's to fix and neither has been touched — `service/` is
Naidhruv's. Both are one-line changes in his adapters, both are reproducible
from `reports/s3_adversarial/pure_noise.wav`, and the second one is a
two-character fix (`if score else` -> `if score is not None else`, or drop
the fallback). Raised here with the measurement attached rather than edited.

