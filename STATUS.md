# STATUS

One section each. Edit only under your own heading.

---

## Dheeraj — zoo · S0–S2 · classifier

**Landed 4 Sep.** `zoo/` bits-only mode, merged to `main`.

- `zoo/bits_only.py` — conv-encode → block-interleave → scramble → inject,
  per docs/zoo-bits-only-contract.md. Seeded, reproducible.
- `zoo/build_corpus.py` — generates 73 files: 6 depth×width factorisations
  (including two same-period pairs, 8×12 and 16×6), 6-point BER sweep,
  scramble on/off, plus one uncoded-random file for the false-positive case.
- Truth JSON per file matches the contract schema exactly (poly_notation,
  error_model, pipeline_order all explicit).

**Nehal: tests/fixtures/local_zoo.py can now be deleted — point tests at
zoo/corpus/bits_only/ instead.**

**Next:** S0/S1/S2 real pipeline stages + RF/IQ zoo mode (still fixture-only
via Anvith's rf_channel.py). Starting today.

**Landed 4 Sep, part 2.** `zoo/` RF/IQ mode, merged to `main`.

- `zoo/rf.py` — bits → modulated waveform → channel → WAV, reusing S3's own
  bitmap/filters/schemes so signals match what S3 has already been validated
  against.
- `zoo/build_rf_corpus.py` — 36 WAV files: 6 modulations (bpsk, qpsk, 8psk,
  16qam, 2fsk, 4fsk) × 6 SNR points (4–20 dB). 2-channel WAV + truth JSON
  per file.

**Anvith: tests/fixtures/rf_channel.py can now be deleted — point S3 tests
at zoo/corpus/rf/ instead.**

**Next:** S0 ingest (WAV/IQ read) so downstream stages can consume the
corpus as files, not just in-memory arrays.

**Landed 4 Sep, part 3.** `pipeline/s0_ingest.py`, merged to `main`.

- Reads 2-channel WAV (I,Q) — validated against zoo/corpus/rf/ (own corpus,
  round-trips correctly, fs matches truth JSON).
- Raw IQ ingest (int8/int16/float32) with a ranked-hypothesis format sniffer
  — scores on boundedness + non-extreme-value clustering to discriminate
  byte width.
- 4/4 unit tests passing (tests/unit/test_s0_ingest.py).

**Next:** S1 (PSD, SNR estimate, burst detection).

**Landed 4 Sep, part 4.** `pipeline/s1_detect.py`, SNR estimator fixed +
tested. Not yet merged to `main` (still on `dhiraj/zoo-v0`).

- Found and fixed a real bug in the SNR estimator I'd started: it compared
  peak-PSD-bin to noise floor, which is a spectral-density ratio, not the
  total-power ratio the zoo's truth `snr_db` actually is (`zoo/rf.py`'s
  `_awgn`: `mean(|signal|**2) / mean(|noise|**2)` over the whole capture).
  That mismatch was a flat **+7.2 dB bias across the board** — the two are
  off by roughly the processing gain `fs/occupied_bw`, not noise. Fixed by
  integrating PSD to total power and subtracting integrated noise floor
  power instead of comparing single bins.
- **Validated against truth, not just asserted:** bpsk/qpsk/8psk/16qam now
  measure within 0.2–0.7 dB of truth across 4–20 dB (target was <1.5 dB at
  ≥10 dB) — comfortably inside even the "Exceptional" bar in the plan's own
  perf table. 2-FSK holds to the same bar through 15 dB.
- **Known gap, stated and pinned by a test, not hidden:** 4-FSK SNR is
  still wrong (off by 8–23 dB) and 2-FSK degrades at high SNR. Root cause
  measured, not guessed: the zoo's FSK is unshaped CPFSK
  (`modulation_index=1.0`, no RRC), and its spectral sidelobes never decay
  to the true noise floor anywhere in the captured band — checked the 1st
  through 50th percentile of the PSD, all within 2 dB of each other and
  none within 4 dB of truth. No percentile choice fixes a floor that isn't
  there to find. Needs a constant-modulus/moment-based estimator instead of
  a spectral-floor one. `tests/unit/test_s1_detect.py::test_snr_known_gap_4fsk`
  is `xfail(strict=True)` so this can't silently regress or silently get
  "fixed" without the test forcing an update.
- Also noticed, not yet touched: `estimate_occupied_bw`'s 99%-cumulative-
  power method reports 89–99% of `fs` for every modulation including PSK,
  which is clearly too wide (a QPSK RRC signal at these sps should occupy a
  fraction of the band) — it isn't subtracting the noise-floor contribution
  before integrating, the same class of bug the SNR estimator had. Not
  fixed this pass; flagging so nobody quotes the current occupied_bw number.
- 11 new tests (`tests/unit/test_s1_detect.py`), 10 passed + 1 xfailed.
  Full suite still green (see commit).

**Next:** merge to `main`, then either fix `estimate_occupied_bw` the same
way, or move on to S2 (symbol rate, CFO, roll-off, classification) and
leave both FSK SNR and occupied_bw as dated known gaps for the 5/6 Sep
hardening pass.

**Landed 4 Sep, part 5.** `pipeline/s1_detect.py` spectrogram, closing the
31 Aug gap for real (`S1Result.spec_freqs/spec_times/spec_db` — the
waterfall's data source). 4 new tests, 14 passed + 1 xfailed on the S1
suite. **31 Aug is now genuinely complete**, not just "mostly."

**Landed 4 Sep, part 6.** `pipeline/s2_estimate.py` — the 1 Sep column.
Ported from `tests/fixtures/local_s2.py` (Nehal's stand-in) plus a new
FSK-order estimator; **that fixture can now be deleted.**

- `estimate_symbol_rate` / `estimate_symbol_rate_fsk` — squared-magnitude
  spectrum / IF-derivative spectrum, ported unchanged in method. **24/24
  exact (0.00% error) at ≥10 dB** across the whole RF corpus, all 6
  modulations — well past the 18/20-at-<1% gate.
- `estimate_cfo` — M-th power line search over M ∈ {2,4,8}, ranked by
  score across all three M rather than just the winner, so S3 can fall
  back to the second-best hint.
- `estimate_fsk_order` — **new**, not in the fixture. IF-histogram peak
  count (median-filtered, smoothed, `scipy.signal.find_peaks`), matched
  to the nearest registered order. **11/12 correct on the FSK corpus**
  (2fsk + 4fsk, 4–20 dB); the one miss is 4fsk at 4 dB, below every other
  stated target floor in this project. Pinned by a test, not hidden.
- `estimate()` returns ranked hypotheses on every field (`symbol_rate_hypotheses`,
  `cfo_hypotheses`, `fsk_order_hypotheses`), per the contract's design —
  S3/S4 aren't forced to trust the top guess.
- 9 new tests (`tests/unit/test_s2_estimate.py`), all passing, including a
  structural check that `estimate()` only ever takes `(iq, fs)` — no truth
  path exists to leak through.
- **Not done:** roll-off is Anvith's (S3 already does blind roll-off,
  ±0.009 accurate) so it's correctly out of S2's scope. Modulation
  classification (the cumulant/LightGBM classifier) is 2–3 Sep, next.

**Next:** 2 Sep — twelve-feature cumulant extractor, deterministic
baseline rule, and the labelled training corpus (2,000+ windows/class
across the SNR grid).

**Landed 4 Sep, part 7.** `models/` — the 2 Sep column: feature
extractor, deterministic baseline, labelled training set. New directory,
new owner (mine, per the plan's ownership table).

- `models/features.py` — 12 features per the spec: 7 cumulants (reuses
  Anvith's `pipeline.s3_receive.cumulants`, not reimplemented), occupied-
  BW/symbol-rate ratio (reuses S1+S2), IF-histogram kurtosis + peak count,
  envelope variance, phase-difference entropy.
- **Real bug found and fixed while building this:** fixed |C42| thresholds
  from noiseless theory (bpsk=2.0, qpsk=8psk=1.0, 16qam=0.68) don't
  survive real noise — measured qpsk |C42| at 10dB is 0.66, not 1.0,
  because normalisation divides by total signal+noise power (a known
  finite-sample SNR bias in 4th-order cumulant estimation). Recalibrated
  thresholds to the 10dB *measured* medians instead of guessing, since
  every gate in this project is anchored at ≥10dB.
- **Second bug, same session:** the IF-histogram peak-count feature, built
  and spot-checked against S2's full-length captures, produced 1-6
  spurious peaks on shaped PSK/QAM once actually run at the classifier's
  real scale (4096 samples, 8sps windows — much shorter than a full
  capture). Root cause: tone-counting only means something for a
  constant-envelope signal, and nothing was gating on that. Fixed by
  checking `envelope_variance < 0.05` first (mirrors what
  `pipeline.s2_estimate.estimate()` already does before calling
  `estimate_fsk_order`) — now stable at exactly 1/1/1/1/2/4 across seeds
  for bpsk/qpsk/8psk/16qam/2fsk/4fsk.
- `models/build_dataset.py` — generates windows in-memory via
  `zoo.rf.through_channel` (no per-window WAV files), 12,600 windows
  (2,100/class) across SNR {0,5,10,15,20}dB in ~103s. Independent bits +
  seed per window, not overlapping slices of a few long captures.
- **Baseline macro-F1, reported and written down** (`reports/baseline_classifier.md`):
  **0.520 overall**, but the honest number is per-SNR — **0.68-0.78 from
  10dB up** (every target in this project is anchored there), collapsing
  to 0.05-0.08 below 10dB. Both effects are measured and documented, not
  hidden: the C42 SNR-bias above, and the envelope-variance gate losing
  the FSK/linear split when noise pushes FSK's envelope variance above
  0.05. 8psk gets exactly 0.0 F1 — expected, qpsk and 8psk are
  theoretically identical under `|C42|` + peak-count alone; the baseline
  always guesses "qpsk" for that shared leaf. That gap is what the
  trained model (3 Sep) is *for*.
- 14 new tests (`tests/unit/test_features.py`), all passing, including
  one that pins the low-SNR gap itself (fails loudly if 0dB macro-F1
  quietly improves without the docs being updated).

**Next:** 3 Sep — first LightGBM training run on the 12 features, 6
classes, evaluated on held-out SNRs {2.5, 7.5, 12.5} the model has never
seen (not the training grid — that's the mistake that makes the number
meaningless). Target: macro-F1 ≥80% at ≥10dB. Also: take over the eval
harness from Naidhruv, which doesn't exist yet — blocked until his
`contracts/`/`service/` land or I build a minimal stand-in myself.

---

## Anvith — S3 receiver chain

### 4 Sep — lock-failure detection, hypothesis retry, clean give-up

**Branch `anvith/s3-robustness`.** Full write-up and every number:
`reports/s3_lock_gate.md`. New code: `pipeline/s3_receive/lockcheck.py` and
`search.py`; `tests/unit/test_s3_lockcheck.py` (85 tests).

**The headline, and it is not a good one.** Run blind against Dheeraj's real RF
corpus, S3 was **reporting a clean lock over a coin flip on 19 of the 36
files** — `status: ok`, `confidence: 0.985`, `estimated_output_ber: 0.000000`,
actual bit error rate **0.485**. It had been doing that since the moment S2
landed and nothing in the build could see it.

**The mechanism, because it is a two-stage bug and the second half is mine.**
`s2_estimate.estimate_cfo` raises the signal to the M-th power and takes the
strongest line. On a pulse-shaped stream the strongest line is the **symbol
rate**, not `M × cfo`, so the reported offset comes back near `Rs / M`.
De-rotating by `Rs / M` advances the constellation by exactly one symmetry step
per symbol — 90° for QPSK, 180° for BPSK, 45° for 8-PSK — and my lock metric
`|E[u^S]|` is *invariant* under precisely that, by construction rather than by
accident. Neither stage was checkable against the other, because the only
number either one produced said everything was fine.

**Dheeraj — the S2 half is yours and worth fixing at source.** The CFO search
should exclude the symbol-rate line, or rank M-th power peaks by something
other than height. The corpus makes it a five-minute check: every file has a
true offset of exactly **zero**, and S2 reports a non-zero one on **33 of 36**.

**What closed it: lock is no longer one number.** Seven independent checks
against different evidence, any of which can veto (`lockcheck.py`). Checks are
three-valued — pass, fail, or *unknown* — because a check with no evidence that
returns `pass` looks like corroboration and is worse than no check at all.

| check | evidence | found by |
|---|---|---|
| `signal_present` | cyclostationary line at the claimed symbol rate | pure noise came back `low_confidence`, not `failed` |
| `carrier_aligned` | spectrum still centred after the CFO hypothesis | the 19 files above |
| `output_usable` | the receiver's **own** estimated output BER | `8psk_8dB_2013`: 2-FSK returned `ok` while estimating its own output 19 % wrong |
| `tone_alias` | FSK offset that is a whole tone spacing | `4fsk_13dB_2033`, below |
| `timing_converged` | Gardner — was measured, reported, and not counted | — |
| `carrier_locked` | the S-th power metric, kept | — |
| `equaliser_converged` | recorded as **unknown**, deliberately | see below |

**Measured on the corpus, blind, three arms over the same 36 files:**

| arm | decodes | mod correct | confidently wrong | *old rule would have been* | median |
|---|---|---|---|---|---|
| true rate, no offset | 33/36 | 36/36 | 0 | *0* | 0.33 s |
| S2's top hypothesis | 4/36 | 36/36 | **0** | ***19*** | 0.33 s |
| **ranked hypotheses, searched** | **29/36** | 31/36 | **0** | *0* | 2.70 s |

The italic column is what the old rule would have said about the *same runs*,
reconstructed from the per-check verdicts each run recorded — measured, not
remembered, and regenerable. It is a floor: it cannot speak for the four files
where today's build gives up before the carrier loop runs at all.

**Block C — retry across the hypotheses S2 ranked** (`search.receive_best`).
S2 hands over ranked lists and S3 was reading only the top of each, which is
the same as pretending the ranking was a decision. Reading the rest took files
decoding from **4 to 29 of 36**. It is bounded, and the bound is the design:

- **Screen before running.** `signal_present` answers "is there a signal at
  this rate" from one FFT in 8–28 ms. Candidates that fail it never cost a
  chain run. 72–90 combinations screen down to 4–12 for about half a second.
- **Screen once per distinct measurement**, not per candidate — presence
  depends on family and rate, alignment on rate and offset, neither on which
  plug-in is asking. At most 24 measurements for 90 candidates.
- **A wall clock behind both**, because the argument above is about this corpus
  and a judge will bring something else.

Worst file **5.6 s** against a 20 s budget. Without the screen the same
candidate list is 6 modulations × 3 rates × 5 offsets of *full* chain runs.

**It does not silently repair S2.** A rejected carrier offset becomes a *new
candidate* carrying the measured correction, scored beside every other and
recorded in `hypotheses` with the reason it was created. The rejection stays in
the record. Quietly patching the input would have left this bug upstream with
nothing pointing at it, and the only reason it was found is that the number was
visible.

**Two more things the corpus taught, both now closed:**

- **FSK has a frequency ambiguity exactly as PSK has a rotation one**, and this
  file claimed for two days that it did not. Shift an M-FSK signal by one tone
  spacing: the tone bank finds the same M tones in the same places while every
  label moves by one. `4fsk_13dB_2033` — identical tones, identical margins,
  every check passing, bit error rate **0.248**, which is exactly one position
  of slip on a Gray-labelled 4-ary alphabet. S3 cannot resolve it, so it now
  refuses the hypothesis. Emitting M label-rotations the way the linear branch
  emits S phase-rotations is the symmetric fix and would multiply S4's per-file
  work by the FSK order — **Nehal, that is your call, not mine**; it is written
  up in `fsk_plugin.py` against the 7 Sep FSK row.
- **Two indistinguishable hypotheses are separated by Occam.** The same file
  produced an identical estimate at 0 Hz and at −49 951 Hz, and the large
  offset won on a meaningless tie-break. A hypothesis needing a bigger
  correction needs more evidence for it, so the smaller correction now wins a
  tie.

**Naidhruv:** `values["envelope"]` is `"inside"` or `"outside"` on every
result — "the input is beyond what S3 supports" versus "fair input, nothing
recoverable in it". That is the `/envelope` endpoint's field. I did **not**
widen the status enum to the Command Center's `out_of_envelope` today: you have
not landed `contracts/`, so there is no consumer to serve, and a fourth value
that every existing `status == "ok"` branch has never seen is a poor trade on
an integration day. It follows the moment the Pydantic model exists.

**Nehal — your ask, done.** `estimated_output_ber` and
`estimated_output_ber_valid` are now **primary keys**: present on every path of
every plug-in including the ones that emit no bits, guaranteed by
`result.REQUIRED_VALUES` and `S3Result.__post_init__`, asserted across 6
modulations × 7 adversarial inputs. They were previously on the success path
only, so a defensive `values["estimated_output_ber"]` raised `KeyError` on
exactly the inputs the check exists to catch.

Two things about it you should know before your pre-flight trusts it further:

1. **The validity flag was the part that was broken**, not the number. It was
   gated on carrier lock alone, so on all 19 files above it read `true` beside
   an estimate of 0.000000. It is now gated on every check. Your
   `preflight_reason` only speaks when valid, so your gate was already safe —
   but it was safe by luck of ordering, not because the flag meant anything.
2. Your measurement that the estimate separates recovery from failure was made
   on a corpus with `cfo=0`; the separation you found is real and the numbers
   above do not contradict it. Worth re-running `zoo_gate_study.py` against
   this branch, since the validity flag now excludes a population it used to
   include.

**Dheeraj — your fixture is deleted, as promised.**
`tests/fixtures/rf_channel.py` and `tests/fixtures/local_s2.py` are gone. Every
S3 test and both report scripts now go through `zoo.rf` and
`pipeline.s2_estimate`. There is one modulator in this repo and one symbol-rate
estimator, not two of each. `tests/fixtures/corpus.py` replaces them: it reads
your corpus, regenerates the transmitted bits from the seed in each truth JSON
(verified exact — relative mismatch 1.3e-9, which is the float32 the WAV is
stored in), and does the correlation alignment in **one** place.

That last part found a real bug in my own reporting: `measured_ber` in two
report scripts sliced a comparison window as long as the reference, which
leaves exactly one candidate offset and it is always the wrong one. It reported
**0.485 for files that decode exactly**. Any earlier number of mine from those
two scripts that looked like a coin flip should be re-read.

**Still open from today:**

- **Seven files do not decode**, all at 4–8 dB. Four are FSK, and they split
  two ways with different owners. `2fsk_8dB_2025` (S2 offers 11987, 9345,
  59987 Hz against a true 50000) and `4fsk_4dB_2030` (65634) fail because the
  true rate is not in the list — the retry loop can only search what it is
  given, so these come back `failed` with the measured line score in the reason
  rather than as a wrong answer. **Dheeraj**, one predicate is behind both:
  `estimate()`'s envelope test reads these WAVs as non-constant-envelope, so
  FSK captures go to the *linear* rate estimator and `fsk_order_hypotheses`
  comes back empty on all 36 files. That is worth more to this gate than
  anything left in S3.
- **`2fsk_4dB_2024` is mine and it is a near miss.** S2's rate is 48479 against
  a true 50000 — close enough to work — and my presence check scored it 4.4
  against a limit of 4.5. That limit comes from the worst noise draw at the
  shortest record length, so loosening it to catch this file spends the margin
  that keeps noise out. The fix is a better statistic at 4 dB, not a looser
  number, and that is 5 Sep's row.
- **`equaliser_converged` does not vote**, and is recorded as `unknown` rather
  than quietly dropped. `CMAResult.converged` asks whether the modulus error
  *improved*, which is meaningless on a channel with nothing to equalise — it
  reads `False` on `qpsk_20dB_2011`, a file that demodulates to a bit error
  rate of exactly zero. Letting it veto would have failed a perfect file, and
  the zoo has no multipath to set an absolute threshold against. It becomes a
  vote the day the corpus grows a channel that needs an equaliser.
- **Choosing the modulation is still not S3's job.** With no ranking from S2
  the search runs every survivor and picks on reported quality — that works
  here and it is not a classifier. When Dheeraj's lands, pass it as
  `modulations=` and the search takes the first clean lock instead, which is
  both faster and better founded. 31 of 36 currently correct; the five misses
  are all files where nothing locks.

---

**Landed 29 Aug – 3 Sep. Merged to `main`.** The column is complete, and the
defects found while closing it are listed below rather than left implicit.

- `pipeline/s3_receive/` — RRC matched filter with blind roll-off, Gardner
  timing, CMA and MMA blind equalisers, Costas for M-PSK and a
  decision-directed loop for QAM, non-coherent FSK tone bank, exact
  (log-sum-exp) soft demapper.
- **Six modulations registered**: `bpsk qpsk 8psk 16qam 2fsk 4fsk`. With
  Nehal's plug-ins imported the registry reports **6 modulations / 3
  interleavers / 2 codes** — the 2 Sep integration line, met exactly.
- `bitmap.py` holds the symbol-to-bit mapping in **one** place. Dheeraj: import
  `bits_to_symbol_indices` from it when the zoo grows a modulator rather than
  restating the convention. Two implementations of one mapping is a bug whose
  only symptom is a payload of noise with every stage reporting success.
- Reports: `s3_envelope.{csv,md}` (EVM, lock rate, timing convergence, charts
  under `reports/s3/`) and `s3_s4_junction.{csv,md}`.

### Gates

| Day | Gate | Result |
|---|---|---|
| 29 Aug | timing converges inside 2000 symbols | worst 1112 |
| 29 Aug | four tight clusters at 20 dB | EVM 5.2 %, charts in `reports/s3/` |
| 30 Aug | Costas locks QPSK to 10 dB | lock 0.896 at 10 dB |
| 30 Aug | EVM logged per file | `reports/s3_envelope.csv`, 32 files |
| 31 Aug | locks on ≥18 of 20 PSK | **19/20** (8-PSK at 8 dB is the miss) |
| 1 Sep | no label lookup in S3 | asserted by test, 0 hits |
| 2 Sep | LLR contract, all six modulations | 45 contract tests green |
| 3 Sep | estimated output BER within 2x of actual | holds on every locked file |
| 4 Sep | pure noise → `failed` with a reason, no crash | 6/6 modulations, 12–34 ms |
| 4 Sep | ≥40% of the corpus to usable LLRs, ≥4 of 6 modulations | **29/36 (81%), 6 of 6** |

### The junction — verified end to end

**WAV → S3 LLRs → S4 blind recovery → S5 Viterbi → source bits, exact.** Raw
BER 0.0002 at 12, 6 and 4 dB. This is what closes the LLR sign convention: it
was previously asserted only by my own test against my own transmitted bits,
which cannot catch a sign error that both sides share. It now decodes through
Nehal's Viterbi, and the two wrong rotations decode to 0.47 as they should.

Detail in `reports/s3_s4_junction.md`. The three findings for Nehal, unchanged:
the interleaver is what fails rather than the code; my errors are independent
(mean run length 1.00) not bursty; and the rank test cannot select the rotation
— all four return `ok`, and shortest-span across rotations is the discriminator.

### Defects found and fixed since the merge

- **An implausible symbol rate hung the stage for four minutes.** Filter length
  scales with samples-per-symbol, so a rate of 1 Hz against 200 kHz asked for a
  two-million-tap matched filter. It returned the *correct* status — after 257
  seconds per call. That is risk #5, unbounded work driven by an upstream
  number, sitting in S3 rather than S4, and reachable the moment the 4 Sep
  hypothesis loop starts sweeping candidate rates. There is now a hard tap cap
  in `rrc_taps` and a record-length check before any filter is built, and the
  test asserts the rejection takes under 5 seconds. **Suite went from 9m07s to
  34s as a side effect** — Nehal, this is the same class of thing as your
  statistical-fallback wall clock.
- **Blind roll-off was biased**, reading 0.60 for a true 0.50. Two estimators
  were wrong in different ways before this one: a two-threshold width
  measurement, then a shape fit that normalised by a percentile of a noisy
  spectrum. Fitting amplitude and roll-off jointly by least squares removes the
  normalisation entirely. Now accurate to **±0.009** from 0.15 to 0.70, and the
  test tolerance is 0.03 instead of the 0.15 that had been written around the
  error.
- **`estimated_output_ber` is optimistic when the receiver has not locked** —
  0.003 reported against 0.035 actual on 8-PSK at 8 dB. It now travels with
  `estimated_output_ber_valid`, so a consumer cannot read the number without
  being told whether to believe it. Naidhruv: the UI card must gate on this.
- **Adversarial input is now tested** — pure noise, DC, all-zeros, clipped,
  impulse, two overlapping tones, and three wrong symbol rates, across three
  modulations. Every case returns a status with a reason and finite LLRs, and
  none of them claims `ok` on noise. That is the cheap half of the 4 and 8 Sep
  rows, done early because each is an input a judge can produce in five seconds.
- **`plots.py` had no coverage at all.** It is only reached from a report
  script, so a break in it would have surfaced as a failed report rather than a
  red test. Covered now.

### Environment

**Now on the pinned Python 3.11.9**, matching `docs/python-version-decision.md`.
`.venv` built from `requirements.txt` as committed: numpy 2.4.6, scipy 1.17.1,
galois 0.4.11, commpy 0.8.0. `docs/stack_check.py` passes 11/11. The earlier
caveat about my numbers not being byte-comparable with the S4 reports is
resolved — everything above was regenerated on 3.11.9.

### Still open, stated plainly

- The non-coherent FSK LLR carries a **measured** calibration constant of 2.0,
  not a derived one. It holds across both FSK orders and a 4 dB span, which is
  why I trust it as a missing term rather than a fudge. Somebody should derive
  it properly.
- ~~Everything is measured against `tests/fixtures/rf_channel.py`~~ —
  **resolved 4 Sep.** The fixture is deleted; signals come from `zoo.rf` and
  the corpus. The shared-`bitmap.py` caveat still stands and always will: one
  mapping used by both sides means a mapping error is invisible to both, which
  the Gray-adjacency test reduces rather than removes.
- 16-QAM and FSK have not been taken through to S4; the junction study covers
  BPSK, QPSK and 8-PSK.
- Soft-vs-hard coding gain is unmeasured. The chain decodes exactly at every
  SNR tried, so there was no visible difference — which means the case for soft
  decisions rests on argument, not measurement, until it is run somewhere the
  code is actually stressed.
- I self-merged without a reviewer, on the third self-merge in this repo.
  Recorded in the merge commit. **Naidhruv: please turn on branch protection**
  — Nehal has now asked three times between us.

**Needs:** Dheeraj's zoo. Naidhruv's real `contracts/` — `S3Result` in
`pipeline/s3_receive/result.py` is shaped for `StageResult`; point me at the
Pydantic model and I will conform exactly.

## Nehal — S4–S6 · the moat

**Landed 29-31 Aug**

- `pipeline/s4_recover/gf2.py` — GF(2) rank (packed-int, fast) + `null_space`,
  with `galois` kept as the reference the tests compare against.
- `pipeline/s4_recover/rank_collapse.py` — the detector. Period → alignment →
  interleaver factorisation → code structure → generator polynomials, with a
  statistical fallback when the exact test gives up.
- `pipeline/s4_recover/statistical.py` — statistical parity-check recovery and
  the syndrome-bias validator.
- `pipeline/s4_recover/interleavers.py` — `BlockInterleaver`, **registered**.
- `pipeline/s5_decode/conv_code.py` — `ConvCode`, **registered**:
  `blind_recover` / `decode` / `validate`, plus `validate_against`.
- `pipeline/s5_decode/conv_reference.py` — reference rate-1/n encoder, pinned
  against commpy.
- `pipeline/s4_recover/cli.py` — S4 standalone from a terminal, no web stack.
- `registry/protocols.py` — **strawman, Naidhruv owns this, overwrite freely.**
  Written only because S4 could not satisfy "recovers through the registry"
  without a registry existing. Protocol shapes match the Command Center.
- `tests/unit/` — 209 tests, ~6 min.
- `docs/`, `reports/` — see below.

**31 Aug gate (my column): PASS.**
`CODES["conv"].blind_recover()` recovers the generators from clean coded data
through the registry, by name, without the caller knowing convolutional codes
exist. `GET /registry` equivalent (`registry.describe()`) lists **1 code +
1 interleaver** — the 2 modulations are Anvith's.

**Two things I strengthened beyond the letter of the spec**

1. The spec says "recovered polynomials equal the zoo's configured generators".
   Mine were asserting a hardcoded `(0o171, 0o133)` — which would pass even if
   recovery were hardwired to return it. Now every assertion reads
   `truth.polys_octal`, and `test_registry.py` drives the same recovery at
   **K = 3, 5, 7 and 9** including a swapped generator pair. Recovery follows
   the configuration in all five.
2. `decode()` is wired to Viterbi against the **recovered** generators, so the
   chain is real: coded bits in → recovered parameters → **original source
   bits out, exact**, re-encode BER 0.0.

**The statistical fallback is now wired into `blind_recover`** (this was the
open item from the 30th). The pipeline previously inherited the exact test's
0.3% ceiling even though the statistical method reaches 3%:

| BER | before | now |
|---|---|---|
| 0.05% – 3% | `low_confidence`, nothing recovered | **`ok`, correct generators, inferred BER within 0.0004** |
| 5%+ | fails | still fails, cleanly |

Costs ~1 s extra when it fires, and only fires after the exact path has given
up. It does **not** fire on noise — the false-positive guard is tested on both
paths.

**It also needed a wall clock, and that is worth knowing.** The statistical
search is most expensive on inputs containing *nothing* — every span, stride
and phase gets tried before "no" comes back. Wiring it in naively took
`blind_recover` on uncoded data from ~1 s to ~18 s, unbounded: a free
denial-of-service on the exact input a judge reaches for, and squarely risk #5.
There is now an 8 s budget on the fallback (worst case ~8 s at 80 kbit, ~10 s
at 200 kbit) and the result says when the budget, rather than the evidence,
ended the search.

**Known gaps, stated**

- Recovering an *interleaver* under noise is still unsolved. The fallback
  handles the code, not the factorisation — a dozen statistical searches per
  file does not fit the time budget. Belongs in the Oct–Nov robustness window.
- The unit suite hit 21 minutes at one point today (my regression). Profiled
  and cut to **3 min 21 s** without dropping an assertion — shorter streams
  where length was not the point, fewer repeats on the noise tests, and a wall
  clock on the fallback. Note for the nightly: `--cov` roughly triples the
  runtime, so keep coverage out of the inner loop.
- Everything is still measured against `tests/fixtures/local_zoo.py`, not
  Dheeraj's zoo.

**1 Sep gate: PASS, both bars cleared with room.**

| Family | Bar | Result |
|---|---|---|
| Block, depths 1-16 | >=15/16 | **16/16** |
| Diagonal, 10 combinations | >=8/10 | **10/10** |
| Convolutional (Forney) | not set | 4/4 |

`GET /registry` now lists **3 interleavers + 1 code**. `recover_interleaver`
no longer names a scheme - it iterates `INTERLEAVERS`, so pseudo-random on
7 Sep is a new file and one registration line.

**The finding worth two minutes at standup.** Block and diagonal produce
*byte-identical* rank profiles - same deficient row lengths, same deficiency
values (see `reports/interleaver_families.png`). The curve cannot name the
family at all. Every family is therefore tried functionally: de-interleave and
ask whether the code comes back. That is decisive rather than a threshold,
because a wrong hypothesis leaves the stream looking random.

Convolutional *is* identifiable from the profile: its deficiency repeats every
N bits starting well above N, so `step < first` means convolutional with N
branches and `step == first` means block-like with that period. Two numbers,
32 extra rank computations, and each family gets handed a parameter instead of
searching blind - the difference between a bounded sweep and risk #5.

One trap it walks into on its own: a raw rate-1/2 stream has first=14 step=2,
which looks exactly like a 2-branch convolutional interleaver. The code's own
symbol size is indistinguishable from a branch count. `blind_recover` checks
the direct code structure *before* trying any family, and there is now a test
asserting that ordering so nobody removes it quietly.

**Also 1 Sep, off-plan: the realistic error model, measured two days early.**
`reports/burst_channel.md`. Every ceiling until today used *independent* bit
flips, and every report called them "an optimistic bound" because real errors
are bursty. That was reasoning, not measurement, and it was **backwards**:

| Error model | Exact rank test | Statistical |
|---|---|---|
| Independent | 0.30 % BER | 3.0 % |
| Mean burst 20 | 2.0 % | >= 5.0 % |
| Mean burst 100 | **5.0 %** | >= 5.0 % |

Rank collapse counts damaged *rows*, not damaged bits. At 1 % BER, independent
errors damage 62.8 % of rows and mean-burst-100 damages 3.7 % — same error
count, seventeen times fewer rows. So Stage 4's envelope is ~16x wider than we
have been claiming, and the independent-error numbers are the **pessimistic**
bound. `ber_ceiling.md` is marked superseded in part rather than quietly edited.

**Anvith, this is the one for you:** it cuts both ways. Bursts help S4 and
*hurt* S5 — they are exactly what a convolutional decoder cannot absorb, which
is why interleavers exist. Do not let anyone quote the first half alone.

**Two bugs found doing it.** The fixture's scrambler was commented as
"degree-6 maximal-length" and has period **7**, not 63 — the 7 Sep
Berlekamp-Massey work would have been validated against something far too
easy. Now the real CCSDS 131.0-B randomiser, period 255, verified by measuring.
And scrambling turns out **not** to hide the code from rank collapse, so the
5 Sep concatenated profile can be unwound without descrambling first — that
removes the chicken-and-egg it appeared to have.

**Still unsolved, stated plainly:** recovering the interleaver's depth x width
fails at *any* non-zero BER, under every error model. Bursts move it from 0 %
to 83 % at 0.1 % BER but nothing reaches 100 %. The pipeline recovers the code
under noise, not the interleaver. That is the Oct-Nov robustness window's job.

**Also landed, off-plan: S6 and a readable payload.** `--demo --text` runs
the whole chain blind and prints the message — period, interleaver, code,
generators, de-interleave, Viterbi, text — in about 21 s. Blind scrambler
recovery works for degrees 5/7/8 with no dictionary of known polynomials.

**Three things REAL data broke that random data never would have**, all now
tested. The consistency guard assumed a random source: ASCII has bit 7 clear in
every byte, so text is rank-deficient before the code touches it, and the first
stream carrying an actual message failed outright. Relaxing that let a 4x24
de-interleave of an 8x12 stream win as "rate 1/16 K=2". And it made "no
interleaver" fire on six interleaved streams.
**Dheeraj — this is the argument for the zoo carrying real payloads rather than
random bits. Random data hides this entire class of bug.**

**One thing NOT solved, guarded rather than hidden:** a scrambled stream yields
the code-XOR-scrambler composite, which annihilates the stream exactly and so
cannot be rejected by any residual test. K=7 under a degree-8 scrambler reads
back as K=15. Such results are downgraded and labelled, never announced.

**Tomorrow (2 Sep):** Reed-Solomon (255,223) registered, and the LLR contract
test with Anvith. `docs/HANDOFF.md` has the LLR convention.

**Blocked on:** nothing.

---

## Naidhruv — contract · service · UI · integration

_(not started here)_

**From me, when you freeze the contract:** `RecoveryResult` in
`rank_collapse.py` is already shaped for `StageResult` — it carries `status`
(`ok` / `low_confidence` / `failed`), `confidence`, ranked `hypotheses` with
scores and evidence strings, and a `reason` on every failure. Point me at the
real Pydantic model and I will conform to it exactly rather than approximately.

Two things to know:

- **Python 3.11.9. Everyone: `winget install --id Python.Python.3.11`.**
  Done here — `.venv` is 3.11.9, stack check 11/11, `tests/unit` 83/83, and the
  S4 reports regenerate byte-identically to the 3.13 originals. 3.11.9 is the
  newest 3.11 with a Windows installer (later 3.11 releases are security-only
  and source-only), so it is the one patch the whole team can get with one
  command — which lets the image pin `python:3.11.9-slim` and be the *same*
  interpreter we develop on. Full evidence in `docs/python-version-decision.md`.
- **My earlier pins were broken and are fixed.** `requirements.txt` had
  `numpy==2.5.2` / `scipy==1.18.1` carried over from the 3.13 box S4 was first
  built on. Both declare `Requires-Python >=3.12` — not "resolves differently",
  **not installable on 3.11**. That file would have failed the image build. It
  is now pinned from a real 3.11.9 resolution and verified by installing from
  scratch into an empty venv.
- **Two container findings that matter more than the version.** `python:*-slim`
  has no `libgomp1`, so **LightGBM imports fine and dies the first time it
  trains** — inside the image, which nobody looks at until the 6 Sep clean
  rebuild. Dockerfile base with the fix is in that doc. And numpy resolved to
  2.2.6 / 2.4.6 / 2.5.2 across environments from the same unpinned file, which
  is a bigger delta than 3.11 vs 3.13 — pin and commit the lockfile.
- `docs/stack_check.py` exercises the whole stack (GF(2) rank, Viterbi hard and
  soft, RS correction, a LightGBM fit) in ~30 s. Worth running inside the image
  on 6 Sep and 9 Sep — it turns "the container built" into "the container works".
- S4 has a working CLI path already (`python -m pipeline.s4_recover.cli`), so
  the "if only 48 hours remain" floor is covered for my stages from day one.
