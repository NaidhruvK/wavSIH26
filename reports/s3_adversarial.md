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

`estimate()` on the input, then `receive_best` over S2's ranked
hypotheses — what S3 can do when it is asked properly. **This is not what
the service currently calls; see §10.**

| case | class | declared fs | statuses over seeds | modulation | reported Rs | measured BER | worst s |
|---|---|---|---|---|---|---|---|
| control: clean qpsk | control | 200,000 | 8x `ok` | `qpsk` | 50,000 | 0.00e+00–0.00e+00 | 1.12 |
| pure noise | absence | 200,000 | 8x `failed` | `2fsk` | 58,954 | — no reference | 0.26 |
| DC only | absence | 200,000 | 8x `failed` | — none claimed | — | — no reference | 0.06 |
| clipped (saturated) | degraded | 200,000 | 8x `ok` | `qpsk` | 50,000 | 0.00e+00–0.00e+00 | 1.04 |
| two overlapping signals | degraded | 200,000 | 8x `low_confidence` | `16qam`, `2fsk`, `4fsk`, `8psk` | 50,000 | 4.81e-01–4.86e-01 | 6.68 |
| empty band | absence | 200,000 | 7x `failed`, 1x `low_confidence` | `16qam` | 12,515 | — no reference | 2.97 |
| wrong sample rate | degraded | 48,000 | 8x `ok` | `qpsk` | 12,000 | 0.00e+00–0.00e+00 | 1.03 |

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
on every seed and costs **6.29–6.68 s** here. The next
most expensive adversarial case peaks at 2.97 s (`empty band`, on
the one seed in eight where it also runs to the ceiling) and the rest are
under 1.1 s.
That is the correct behaviour — there is no right answer to converge on, so
the search exhausts its list — but it is the number to carry into a budget
discussion, because two emitters in one band is not a contrived input.

On the slower dev box (measured at 2.09x this one, 7 Sep) that is roughly
**14.0 s against the 20 s budget** — inside it, with the
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
4 Sep unit tests cover, and — per §10 — **what the service actually does
today**, with `name` hardcoded to `qpsk`. A plug-in handed an explicit rate
has no search, no rescue and no deadline.

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
as a stereo (I, Q) WAV at the declared rate, so they ingest through S0
like any corpus file. They are **not** in `zoo/corpus/rf/` on purpose:
every S3 study globs that directory and six extra files would silently
move the denominator of every corpus number in this project.

**They are 32-bit float, not PCM_16 like the corpus, and that is not
cosmetic.** The first version followed the corpus format; checked
afterwards, `empty_band.wav` had **2 distinct sample values** across
240,000 samples. At a peak of 4.85e-06 one PCM_16 quantum is 3.05e-05, so
the capture collapsed onto ±1 LSB — a one-bit dither pattern where the
array in memory is thermal noise 120 dB down. **The one property that case
exists to test is the one a fixed-point format cannot carry.**
`read_wav_iq` calls `sf.read`, which returns float64 for any subtype, so
nothing downstream sees a difference.

Regeneration is **sample-exact, not byte-exact**, and the distinction is
the format's rather than a weakness in the check: libsndfile writes a
`PEAK` chunk on float WAVs carrying a creation **timestamp**, so all six
differ at byte 60 and nowhere else.
`test_the_committed_files_are_reproducible_from_the_study` regenerates into
a temp directory and compares decoded samples, rate and subtype — which is
all anything downstream reads.

## 8. Every refusal says why, in numbers

The day's integration line is "nothing unhandled remains; every failure has
a message a human can act on". S3's half, seed 0 of each case, verbatim from
`reason`:

| case | status | reason |
|---|---|---|
| pure noise | `failed` | every candidate was refused by the cheap screen: no symbol-rate line at 45351 Hz (3.8x local median, needs 4.5x) - either nothing is here or the rate is wrong |
| DC only | `failed` | every candidate was refused by the cheap screen: no symbol-rate line at 5000 Hz (0.0x local median, needs 4.5x) - either nothing is here or the rate is wrong |
| clipped (saturated) | `ok` | *none, and correctly so — there is nothing to explain* |
| two overlapping signals | `low_confidence` | the receiver estimates its own output BER at 0.451, over the 0.05 a lock should produce - it is describing a demodulation it cannot claim; mean tone margin 0.058 below 0.150; search truncated by a ceiling of 12 chain runs: 12 of 18 surviving candidates were run and 6 never reached - this is the best of what ran, not a survey of the field |
| empty band | `low_confidence` | carrier lock 0.07 below 0.59; the receiver estimates its own output BER at 0.0895, over the 0.05 a lock should produce - it is describing a demodulation it cannot claim |
| wrong sample rate | `ok` | *none, and correctly so — there is nothing to explain* |

Each one names the statistic, the threshold it missed and by how much. The
two `ok` rows carry no reason, which is right — there is nothing to
explain. `two overlapping signals` also reports its own truncation
("12 of 18 surviving candidates were run and 6 never reached — this is the
best of what ran, not a survey of the field"), which is the 7 Sep fix #3
doing its job on an input it was not written for.

## 9. What the six files found OUTSIDE S3 — for Naidhruv, and one for Dheeraj

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

## 10. The service never calls the blind search, and demodulates everything as QPSK

**This is the largest finding of the day and it was found by accident** —
by running the six adversarial files through `python -m service.cli analyze`
and noticing that all six reported `modulation: qpsk`, including the ones
`receive_best` calls `16qam` and `2fsk`. It is not S3's to fix and nothing
here has been changed; `service/` is Naidhruv's.

### Measured, 40 random corpus files, both paths

| path | decodes | modulation correct |
|---|---|---|
| `receive_best(iq, params_from_s2(s2, fs))` — what S3 can do | **35/40** | **37/40** |
| `MODULATIONS[chosen_scheme].receive(...)` — what the service does | **11/40** | **11/40** |

24 of 40 files decode on one path and not the other. Every disagreement
has `chosen_scheme == "qpsk"` against a true scheme of 2fsk, 4fsk, 8psk or
16qam. Scored with the repo's own `corpus.measured_ber` against the
transmitted bits.

### The chain, read rather than inferred

1. **`adapt_s2` reads a field that does not exist.**
   `service/orchestrator.py:323` is
   `order_hint = getattr(raw, "order_hint", 0)`. **`S2Result` has no
   `order_hint`** — its field is `fsk_order_hint`. So the `getattr` default
   fires on every input and `order_hint` is **0 on 30 of 30** corpus files
   measured.
2. **`order_hint == 0` takes the `else` branch** of the if/elif ladder at
   `orchestrator.py:341-349`, which returns
   `[Hypothesis("qpsk", 0.7), Hypothesis("bpsk", 0.3)]` — always.
3. **Dheeraj's classifier is computed and discarded.**
   `S2Result.modulation_hypotheses` carries the ML ranking and is populated
   on **28 of 30** files; `adapt_s2` never reads it. On `2fsk_15dB_6028` it
   says `2fsk` at **0.9987** while the adapter hands S3 `qpsk` at 0.7.
4. **`orchestrate` takes `s2_res.hypotheses[0].value`** (line 844) — `qpsk`.
5. **`_run_s3` (line 856) runs that ONE plug-in**, never `receive_best`. No
   search, no ranked fallback, no rate rescue, no breadth-first ordering —
   the whole of `e7b9649` is unreachable from the API and the CLI.

### Why it is invisible

Same shape as the two other integration defects found this week, and the
third instance of the same species in this one file: a `getattr` against a
field name that does not exist, silently taking its default. The 7 Sep
notes already record “one orchestrator test asserting `est.symbol_rate`
where `S2Result` has `symbol_rate_hz`”. Nothing raises, every stage returns
`ok`, and the report looks complete — it is simply wrong about the
modulation. A corpus file that decodes perfectly in S3's own tests comes
back as noise through the service, and no test compares the two paths.

### The fix is small and it is Naidhruv's

Stated because it is a day before freeze, not to pre-empt his call:

* `adapt_s2` should prefer `raw.modulation_hypotheses` when it is present
  and fall back to the ladder only when it is not — that alone restores
  Dheeraj's classifier, which is right on 28 of 30.
* `_run_s3` should call `receive_best(iq, params_from_s2(s2_raw, fs))`, the
  entry point S3 exposes for exactly this. It reads the ranking as a PRIOR
  rather than a restriction, so it still recovers files the classifier gets
  wrong — which is the difference between 35/40 and 11/40.
* If neither lands before freeze, the honest fallback is to stop reporting
  a modulation the service did not determine: `qpsk` is a hardcoded default
  presented to a judge as a finding.

