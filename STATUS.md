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

**Landed 4 Sep, part 8.** `models/train.py` + `models/build_holdout.py` —
the 3 Sep column: first LightGBM run, held-out-SNR evaluation, confusion
matrices. Full report: `reports/classifier_eval.md`.

- `models/build_holdout.py` — 7,200 windows at SNR {-3, 2.5, 7.5, 12.5}dB,
  asserted at import time to share zero values with the training grid
  {0,5,10,15,20} — the plan's stated failure mode (validating on the
  training grid) is structurally impossible here, not just avoided by
  discipline.
- **Real bug found and fixed: LightGBM wasn't deterministic run-to-run**
  despite a fixed seed. Same config, same data, different predictions on
  repeated `lgb.train()` calls — caught by actually re-training twice and
  diffing predictions, not by trusting `seed=`. Needs `num_threads=1` +
  `force_row_wise=True` alongside `deterministic=True`; confirmed
  byte-identical predictions across 3 repeated runs after the fix. Pinned
  by `tests/unit/test_train.py::test_train_is_deterministic`.
- **Result: macro-F1 = 0.778 at the one holdout SNR ≥10dB (12.5dB)** —
  just under the plan's 0.80 Minimum-tier target, and NOT a general
  high-SNR failure: 7.5dB (a harder, lower-SNR holdout point) scores
  **0.950**. Root cause traced, not guessed (full writeup in the
  report's "Reading the 10dB+ number" section): the model swaps 4fsk
  for 2fsk entirely at 12.5dB, because `if_hist_peak_count`'s
  envelope-variance gate (added Monday, this session) clamps to 1 for
  ~40% of both FSK classes' *training* rows at low SNR, diluting what
  is otherwise a clean 2-vs-4 discriminator. The baseline dodges this
  same slice by coincidence — it lands on the identical 0.778 at 12.5dB,
  but for the opposite reason (its gap is qpsk/8psk, not 2fsk/4fsk).
  **Model still clearly beats baseline overall: 0.693 vs 0.383 macro-F1
  across the full holdout.**
- Suggested next step, not attempted (out of scope for a first run):
  feed SNR as an explicit feature, or split peak_count into a raw value
  plus a separate confidence flag instead of collapsing both into one
  gated number.
- 5 new tests (`tests/unit/test_train.py`), all passing.

**Still blocked:** the eval harness handover. `eval/` doesn't exist —
Naidhruv's `contracts/`/`service/`/`registry/` (real, not the strawman)
are prerequisites for a *pipeline* eval harness, and still show
"(not started here)" in his section below. What's built today
(`models/train.py`'s own report) covers the *classifier's* evaluation
need for the 3 Sep gate, but not the broader per-scheme coverage matrix
the full eval harness is supposed to produce across all seven stages.
Flagging again for standup — this is now the second stream (S2/S3
already noted it) waiting on the same missing piece.

**Landed 4 Sep, part 9.** The 4 Sep column: expanded corpus, classifier
wired into live S2, per-scheme coverage matrix.

- `zoo/build_rf_corpus.py` — 36 → **252 files** (6 schemes × 6 SNRs × 7
  reps), toward the 250-file target. **Purely additive: the original 36
  files are byte-identical** (hash-verified before and after — the first
  rep keeps the original seed formula on purpose) so nothing that globs
  or references the existing corpus by name breaks.
- `models/classify.py` — serves `models/classifier.txt` in-process,
  model loaded once. Bridges S2's native captures (arbitrary fs/sps) to
  the classifier's training regime (4096 samples, fixed 8sps) by
  resampling using **S2's own estimated symbol rate, not truth** —
  `resample_window()`. Returns ranked top-3 hypotheses + a
  `low_confidence` flag (<0.70) that folds the deterministic baseline's
  guess in when the model isn't sure, per the ML spec's failure-handling
  design.
- `pipeline/s2_estimate.py::estimate()` — new `modulation_hypotheses` /
  `modulation_low_confidence` fields, `classify=True` param. Import is
  lazy (inside the call) because `models.features` imports from this
  same module — a real circular-import risk, not a style choice.
  Degrades to empty hypotheses rather than crashing S2 if
  `models/classifier.txt` doesn't exist in a checkout (`FileNotFoundError`
  caught explicitly).
- `reports/s2_coverage_study.py` → `reports/s2_coverage.{csv,md}` — the
  per-scheme coverage matrix, run through live `estimate()` across all
  252 corpus files (not a held-out set — this is coverage on real
  captures, complementary to `classifier_eval.md`'s held-out numbers).
  **bpsk 100%, 16qam 100%, 8psk 95%, qpsk 79%** (the qpsk/8psk case the
  baseline structurally cannot solve — the model gets it right on live
  captures, including at 4-8dB where the holdout set didn't test it).
  **2fsk 67%, 4fsk 17%** — both driven by known, already-diagnosed gaps:
  2fsk is perfect ≥10dB / zero below it (the envelope-variance gate);
  4fsk is perfect at *exactly* 10dB and wrong at 13-20dB, the same
  decision-boundary artifact `classifier_eval.md` traced on the holdout
  set — now confirmed on full-length live captures too, with the same
  SNR pattern, which rules out the resampling bridge as the cause.
- 8 new tests (`tests/unit/test_classify.py`), including one pinning the
  4fsk gap and one confirming S2 degrades gracefully (doesn't crash) if
  the model file is absent.

**4 Sep column complete.**

**Landed 4 Sep, part 10 — the 4fsk bug, actually fixed, and the earlier
diagnosis corrected rather than quietly left wrong.** The "known gap"
reported above was traced to the wrong root cause. Real one, found by
testing the model against its own training rows: it scored **100% on
the training data for the exact (scheme, SNR) cells it was failing on
in holdout** — classic overfitting, not a missing or diluted feature.
`if_hist_peak_count` was checked directly on the failing examples and
was correctly 4.0 the whole time; the envelope-gate theory was
plausible and wrong. Root cause: only 420 training windows per
(scheme, SNR) cell, and some features cluster extremely tightly within
a cell (`phase_diff_entropy` std as low as 0.013) — the unregularised
tree fit a boundary tight enough that a differently-seeded holdout
example landed outside it.

**Fix: regularisation only, no feature or capacity changes** —
`min_data_in_leaf=300`, `lambda_l2=5.0`,
`bagging_fraction=feature_fraction=0.6` (`models/train.py`'s
`LGB_PARAMS`, defined once and reused everywhere after the earlier
stale-header lesson). Still `max_depth=5`, 200 trees — the plan's cap,
untouched. **Macro-F1 at the one ≥10dB holdout point: 0.778 → 0.993**
(exceeds even the "Exceptional" 95% tier). Overall holdout macro-F1:
0.693 → 0.720. Live-corpus 4fsk coverage: 17% → 52%, now perfect at
10–15dB. Confirmed deterministic across repeated training runs with
bagging enabled (`num_threads=1, force_row_wise=True,
deterministic=True`).

**Not fully closed — a smaller, different residual, found only because
the live corpus tests SNRs the holdout set never covered:** 4fsk at
20dB is still wrong on 6/7 files. Qualitatively different from the
original bug though — no longer a *confident* wrong answer (top pick
0.4–0.8 vs. previously ~0.99), and 4fsk stays the #2 hypothesis at
14–42% every time, so the ranked-hypothesis design still carries the
right answer for S3/S4's rank test. Pinned by
`test_classify_4fsk_residual_gap_at_20db` (asserts top-2, not top-1,
since a 20dB coin-flip isn't worth pinning file-by-file).

`reports/classifier_eval.md` and `reports/s2_coverage.md` both
regenerated and corrected — the wrong original diagnosis is left
visible in `classifier_eval.md` with a note explaining the correction,
not deleted, since it's a real lesson about testing a model against
its own training data before trusting a feature-level theory.

Next: 5 Sep — concatenated CCSDS chain (Nehal's, not mine) and driving
S2 accuracy down the SNR range / producing envelope charts (mine).

**Out-of-band fix, reported by a teammate: `estimate_cfo` was reporting
a false CFO of `Rs/M` on every clean file.** The classic M-th power
spectral-line trap. Root cause: `z = z - np.mean(z)` before the FFT
nulled the DC bin -- exactly where the true line sits when CFO is
genuinely 0. With DC removed, `argmax` locked onto the next-strongest
line instead, a symbol-rate-related cyclostationary artifact rather
than the carrier. Confirmed on bpsk (false CFO = Rs/2), qpsk (Rs/4),
8psk (Rs/8) — every file in the corpus has `cfo_norm=0.0` (see
`zoo/rf.py`), so this was checkable directly against truth. **EVM
doesn't catch this** (a residual phase ramp barely moves symbols off
their decision regions), **but Stage 4's algebraic recovery does, since
it has zero tolerance for any rotation** — which is exactly how the
teammate found it: EVM looked fine, S4 recovery was completely broken.

Fixed by not demeaning. Verified the true M now wins on SCORE, not just
plausibility: on every modulation tested, the M matching the signal's
own PSK order lands its peak at k=0 with a HIGHER score than any false
alias — not a coincidental pick. **112/112 clean at ≥10dB across the
full PSK/QAM corpus** (bpsk/qpsk/8psk/16qam × every rep × every SNR
≥10dB), within 200Hz of true 0.

Also, per the teammate's explicit request: `estimate_cfo` now returns a
5th element, `cfo_alias_hypotheses` — every `m`-th root per order (not
just the closest-to-zero pick `hyps` keeps for backward compat), with
an explicit 0 Hz candidate guaranteed present even if no order's peak
search happens to land there. `S2Result` gets a matching
`cfo_alias_hypotheses` field. 6 new tests in
`tests/unit/test_s2_estimate.py`, including one that checks the root
cause (score, not just value) rather than just the symptom.

**Found while fixing this: I ported the exact same bug from
`tests/fixtures/local_s2.py`** (Nehal's 30 Aug stand-in) when I wrote
the real module — it has the identical `z = z - np.mean(z)` line. That
fixture is explicitly labelled "dies when pipeline/s2_estimate.py
lands" and was supposed to be retired once my real module existed, but
`tests/unit/test_s3_receive.py` still imports `estimate_blind` from it
directly, not from `pipeline.s2_estimate`. **If the teammate who found
this was testing through that path, the bug is still live there** —
not touching `tests/fixtures/local_s2.py` myself (it's not mine), but
flagging clearly, a fourth time now, that it needs to be deleted and
repointed at the real module.

**Also found and fixed, unrelated: `models/classifier.txt` was
corrupted in my own local working tree** — `core.autocrlf=true` with no
`.gitattributes` let git's LF→CRLF conversion mangle the LightGBM
text-dump model on checkout (confirmed the committed blob itself was
fine via `git show`; only checked-out copies broke). This would hit
*any* teammate on Windows who clones or checks out this repo, not just
me. Added `.gitattributes` marking `models/classifier.txt` and the
dataset CSVs `-text` so it can't recur for anyone.

### 5 Sep — driving S2 accuracy down the SNR range / envelope charts

Root-caused (not just re-measured) the still-open gap flagged in
`s2_coverage.md`: 2fsk/4fsk sit at 0% live-classification accuracy at
4-8dB, while every other bin is solid. New report,
`reports/s2_envelope_study.py` (writes `s2_envelope.{csv,md,png}`),
plots the mechanism directly: both envelope-constancy gates in this
codebase (`models.features.envelope_variance < 0.05`, and
`pipeline.s2_estimate`'s own `std/mean < 0.25`) are noise-dominated at
low SNR, and **FSK's noisiest in-scheme case (4dB) is numerically
closer to "constant-envelope" than clean 20dB PSK/QAM is**, by both
metrics. That's a hard crossover, not a tuning gap: no single fixed
threshold on either statistic can get both ends of the SNR range right,
proven with the actual corpus numbers in the report, not asserted.

Tried fixing it anyway: removed the `models.features` gate (peak_count
was being clamped to 1 for FSK below 10dB, discarding the one feature
that matters most for it), on the theory the classifier could learn the
cutoff contextually since `envelope_variance` already reaches it as its
own feature. Ungated, real corpus windows at 8dB *do* stay separable
(peak_count medians ~2/~5/~1 for 2fsk/4fsk/PSK-QAM) and the retrained
holdout macro-F1 barely moved. But the full targeted test suite caught
what that aggregate hid: `test_if_hist_peak_count_matches_scheme`
started failing at 15dB (spurious peaks on qpsk/8psk/16qam — exactly
what the original gate's docstring had already warned about),
`test_baseline_macro_f1_on_training_set` dropped below its regression
floor, and a previously-solid 4fsk-at-15dB classification flipped to
2fsk. **Reverted.** Same root cause as the `s2_estimate` threshold:
proven by measurement, not assumed, to be a genuine crossover this one
scalar feature cannot resolve — not a threshold anyone picked badly.

An SNR-adaptive threshold was the next idea and was rejected too:
`pipeline.s1_detect.estimate_snr` is itself off by 8-23dB specifically
for 4fsk (its own known, documented gap), so adaptively thresholding
the exact class most affected on a broken SNR estimate trades one gap
for a worse one. Left as a known, quantified, low-SNR-only gap,
consistent with every gate in this project being anchored at ≥10dB —
the tripwire's own bar. `models/features.py`'s docstring documents the
attempt and the measured reason it didn't survive testing, same
transparency as the 4fsk overfitting misdiagnosis correction in
`classifier_eval.md`: a disproven hypothesis kept visible, not silently
dropped. `models/dataset_train.csv`, `dataset_holdout.csv`,
`classifier.txt`, `reports/classifier_eval.md` and `s2_coverage.md` were
all regenerated during the experiment and regenerated back — confirmed
byte-identical to what's already committed, so nothing here touches the
live classifier.

Nehal's concatenated CCSDS chain (5 Sep, not mine) not investigated.

### 5 Sep, later — second CFO bug from the same teammate: FSK was never fixed

The teammate who found the 426a780 M-th-power alias bug came back with a
sharper finding: `estimate_cfo`'s fix was correct, but `estimate()` was
calling it unconditionally — on FSK captures too, which it was never
meant for. Measured independently by the teammate across the corpus:

| scheme | files | \|CFO err\| ≥ 100 Hz |
|---|---|---|
| bpsk/qpsk/8psk/16qam | 112 | 0 |
| 2fsk | 28 | 28 |
| 4fsk | 28 | 28 |

**My own "112/112" claim in the 426a780 writeup was exactly this —
4 of 6 modulation families, silently reported as if it were all six.**
The 56 FSK files were never in that count and were still reporting the
same ~symbol_rate/2 false CFO the whole time. Same mistake shape as the
qpsk/8psk-only test list catching me out earlier this session with the
envelope gate, and worth naming plainly rather than letting "112/112"
stand uncorrected in the historical record above.

Root cause, confirmed by reading the code the teammate pointed at: an
M-FSK signal has no suppressed carrier for `x**M` to expose — it has M
discrete tones — so `estimate_cfo`'s M-th-power line search locks onto a
tone-spacing artifact instead of anything carrier-related. Not a bug in
an applicable estimator (that was 426a780); an inapplicable estimator
being run at all. **Measured downstream cost, not just theory:** the
teammate ran 4-FSK recovery with and without the CFO estimate applied —
succeeds without it, fails with it, at both 13dB and 20dB.

Fix: new `estimate_cfo_fsk`, an IF-tone centroid estimator. An M-FSK
tone ladder is symmetric about zero IF by construction (that symmetry
*is* what zero CFO means for FSK), so the mean of the M tone centres
recovers a real CFO shift directly, independent of which tones a given
window's bits happened to visit. Refines each coarse histogram-bin peak
(too wide alone, ~fs/60) to the mean of the raw instantaneous-frequency
samples nearest it. Shares its tone-detection step
(`_fsk_tone_peaks`) with `estimate_fsk_order` so the two can never
disagree on tone count. `estimate()` now routes to it by
`constant_envelope`, same pattern already used for symbol-rate
selection.

**Validated per scheme, not pooled — the exact fix the teammate asked
for:** all six modulation families now report \|CFO\| < 100Hz at ≥10dB
through the real `estimate()` entry point: bpsk/qpsk/8psk/16qam exact
(0.0Hz — the M-th-power line lands precisely at k=0), 2fsk worst-case
54.9Hz, 4fsk worst-case 84.5Hz (was ~25000Hz for both, unconditionally,
before this fix). New tests assert per-scheme, including one that runs
`estimate()` itself rather than either estimator directly, specifically
so a future partial fix can't be miscounted as complete again.

Teammate's second, smaller ask — a zoo corpus file for the full
concatenated CCSDS profile (RS outer → byte-level interleaver, depth
I∈1..8 → randomiser → convolutional inner, in the real standard's order,
not `tests/fixtures/local_zoo.make_ccsds_stream`'s bit-level stand-in) —
not started yet, next up.

### 6 Sep, CORE LOCK — the third finding from the same teammate, a real CCSDS corpus file, and the system envelope

**Third finding, same teammate, same file, restated three times across the
morning** (the earlier fix had already shipped — 55cb628 — each time; the
last two messages were the identical bug report, verified against a repo
state that already had the fix). Confirmed on the current `origin` tip
both times: 56/56 FSK + 112/112 linear = 168/168, no drift.

**Their second ask: a real CCSDS corpus file.** `zoo/ccsds.py` implements
the actual CCSDS 131.0-B transmit order — RS(255,223) outer → BYTE-level
interleaving across `depth` consecutive codewords (a real transpose of
the codeword matrix, not `tests/fixtures/local_zoo.make_ccsds_stream`'s
bit-level interleave-then-randomise-after, which that file's own
docstring already flags as non-standard) → the CCSDS pseudo-randomiser →
the rate-1/2 K=7 convolutional inner code. Verified correct in isolation
before any WAV file was built on top of it: `tests/unit/test_ccsds.py`
round-trips the full chain over a clean channel for interleave depths
1/4/8, plus a dedicated test that a contiguous transmitted burst really
does spread across `depth` different codewords (the entire reason to
interleave a burst channel ahead of a block code).

Written to `zoo/corpus/ccsds/`, deliberately **not** `zoo/corpus/rf/`:
every existing corpus-wide test (including today's own
`reports/envelope_study.py`) globs `rf/*dB_*.wav` and regenerates ground
truth via `zoo.bits_only.make_stream`'s single-code schema — dropping a
differently-coded file in there would silently corrupt every one of
those measurements, without any of them having been wrong to assume what
they assumed about that directory. 8 files across 4 modulations, 3
SNRs, 3 interleave depths; `zoo/build_ccsds_corpus.py` regenerates them.

**Verified through the real RF channel, not just abstractly:** on the
cleanest file (qpsk, 20dB, depth 1), S2 estimates the exact symbol rate
and CFO=0.0 blind, S3 demodulates to a bitstream that matches the true
coded stream **128344/128344** bits exactly once aligned, and Viterbi-
decoding S3's real output matches Viterbi-decoding the true reference
bits **64166/64166** exactly. What is *not* done: full RS-decode through
the real channel, which needs a byte-alignment search across a
non-conv-encoder-aligned bit offset from RRC filter edge transients —
that is a frame-synchronization problem, which is Nehal's/Anvith's
blind-recovery territory (S3/S4-S6), not something folded into the
corpus generator. The corpus file's validity and decodability are
proven; wiring a blind receiver to actually find that alignment is the
next person's job, same ownership boundary as everywhere else in this
project.

**`reports/envelope.md` drafted, per the 6 Sep plan's block B/C/D** ("SNR
floor and BER ceiling per modulation, stated as numbers", "commit the
report and its charts together"). `reports/envelope_study.py` is the
first measurement in this project to run S0→S1→S2 (mine, truly blind —
S2's own `estimate()`, not the channel's true parameters) into S3
(Anvith's, via the registry, exactly the way a real orchestrator would
call it) across all six modulations and the full 252-file corpus, and
score raw BER against the exact source bits each file's seed reproduces
deterministically. Every prior cross-stage number (`s3_s4_junction.md`)
fed S3 the channel's TRUE symbol rate directly, by design, to isolate
the S3/S4 junction from S2 error — a fine choice for that question, but
it meant no report on record said what S2's *actual* estimate costs
end-to-end. This one does:

| scheme | SNR floor (zero raw BER) |
|---|---|
| bpsk | 8 dB |
| qpsk | 8 dB |
| 8psk | 13 dB |
| 16qam | 20 dB |
| 2fsk | 10 dB |
| 4fsk | 10 dB |

Caught and fixed a bug in my own measurement script before trusting these
numbers: `low_confidence` S3 results (a real LLR output, just an
unlocked-carrier flag) were being scored identically to a hard failure
(sentinel BER of 1.0) — findable because it's the same "distinguish a
real answer from a can't-answer" mistake this project keeps having to
correct itself on (the `test_cfo_alias_hypotheses_cover_every_alias_per_order`
scoring mixup, 5 Sep; the 4fsk overfitting misdiagnosis, 3 Sep). Fixed
to score `low_confidence` for real and use `NaN` (not a fake `1.0`) for
genuine non-measurements, which also surfaced a second thing worth
stating plainly rather than treating as noise: **2fsk/4fsk below 10dB
report raw BER ≈0.48-0.63 (chance), not because today's CFO fix
regressed** — confirmed directly (`estimate('4fsk_4dB_...')` still
returns `constant_envelope=False`) — **but because the SAME envelope-gate
crossover documented in `reports/s2_envelope.md` yesterday misroutes
those files to the linear CFO estimator below 10dB, so they never reach
`estimate_cfo_fsk` at all below that line.** One root cause, two
symptoms (classifier accuracy yesterday, raw BER today), left open both
times for the same measured reason: no fixed threshold on that statistic
can get both ends of the SNR range right, and this project's targets are
anchored at ≥10dB everywhere else too.

`models/classifier.txt` frozen this morning per the 6 Sep plan, config
hash `132fc1d21777` unchanged since 3 Sep — no retraining today.

### 7 Sep — Nehal's review of yesterday's work: one documentation ask, one real bug, one gap closed

Nehal independently re-verified the FSK CFO fix (168/168 at ≥10dB,
worst cases reproduced exactly) and, separately, pressure-tested
`zoo/ccsds.py` against his own S4-S6 chain — three findings, all
addressed:

**1. The 10dB CFO floor was a silent routing artifact, now stated as a
number.** He measured that `estimate()`'s `constant_envelope` check
(`std/mean < 0.25`) tracks `1/sqrt(2·SNR_linear)` almost exactly for
FSK — it is measuring SNR, not envelope structure, and the modulation
contributes nothing to it. Below ~9dB it silently misroutes to the
linear CFO path with no failure signal (`status="ok"`, confidently
wrong). Not a defect chasable by a threshold tweak — `s2_envelope.md`
already proved that crossover can't be widened without breaking clean
high-SNR PSK/QAM. Fixed by documentation, per his explicit ask: added
to `reports/envelope_study.py` / `envelope.md` §3, stating plainly that
S2's declared CFO floor for FSK is 10dB and `cfo_hz` shouldn't be
trusted below it regardless of `status`.

**2. `CCSDS_SCRAMBLER` was mislabelled — a real bug, now fixed.**
`zoo/bits_only.py`'s `CCSDS_SCRAMBLER = 0o435` was actually 0x11D, the
GF(256) Reed-Solomon field polynomial, not the CCSDS 131.0-B randomiser
(0o651 = 0x1A9 = x^8+x^7+x^5+x^3+1) its own comment and name describe —
an easy constant to reach for while writing an RS-and-randomiser
generator in the same file. Both are primitive degree-8 (period 255
either way), so nothing was corrupted — the corpus was a valid,
self-consistent scrambler between this generator and Nehal's receiver
checking against the same constant — but the label was wrong. Fixed
the constant (not just the comment), matching the whole point of
`zoo/ccsds.py` being the *standards-accurate* alternative to the
existing fixture. `zoo/corpus/ccsds/` regenerated with the corrected
polynomial; `tests/unit/test_bits_only.py` pins the fix (checks the
exact tap positions match h(x), and that the sequence has period
exactly 255, not some smaller divisor that would also have satisfied
"primitive of degree 8").

**3. `.gitattributes` had a gap Nehal caught before it bit anyone:**
`*.payload.bin` (the new CCSDS corpus's raw payload bytes) had no
`-text`/`binary` marking, the exact autocrlf hole that corrupted
`models/classifier.txt` before. Today's eight files are pure ASCII
with no newline bytes, so the heuristic's "text" guess happened to be
a no-op — the first `payload_text` containing a newline would have
been silently mangled on any Windows checkout otherwise. Added
`*.bin binary`.

**Also landed: `payload_text` and `mean_burst` on `zoo.bits_only.make_stream`**,
the two remaining things `tests/fixtures/local_zoo.py` could do that
the real zoo couldn't — the reason Nehal still had 12 test files, 7
report studies, and `pipeline/s4_recover/cli.py` importing from
`tests/`. Ported `gilbert_elliott_mask`/`inject_burst_errors` from that
fixture (his own description of the model, unchanged) rather than
reimplementing the physics differently. `payload_text` repeats real
text to fill `n_source_bits`, same construction as the fixture's
version, so a caller switching from one to the other sees identical
bits. This doesn't retire the fixture itself — that's Nehal's call, on
his own files — but the blocker on his side is gone.

Full regression suite re-run after all of the above.

### 7 Sep, same day — the OneDrive problem hit my machine too, same fix as Nehal's

That full-suite re-run above surfaced 4 failures in `tests/unit/test_rank_spike.py`
(not my file, not touched today) — `blind_recover`'s statistical fallback
(`pipeline/s4_recover/rank_collapse.py`, `STAT_FALLBACK_BUDGET_S = 8.0`,
wall-clock) running out of its time budget before finding the period.
Didn't assume it was unrelated to my work: reproduced it away from my
changes first — 29/29 passing standalone, 45/45 passing run directly
after every file this session touched — before concluding it was
environmental, not a regression.

Root cause was already diagnosed and fixed by Nehal, on his own machine,
the night before (`4db1455`, `nehal/rs-runtime`, not yet merged): this
whole repo lives under OneDrive (`...\OneDrive\Desktop\SIH\wavSIH26`),
which syncs every test write and every regenerated report and becomes
the top CPU process on the machine during a full suite run — his
measurement was 83,600 CPU-seconds of OneDrive activity during one run,
one test going from ~280s to **4h57m**. A wall-clock-budgeted search
like the statistical fallback is exactly the kind of thing that
degrades under that contention without any logic being wrong.

Applied his exact fix here: fresh clone to `C:\dev\wavSIH26` (not a copy
— a Windows venv bakes in absolute paths and doesn't survive a move),
fresh `.venv` on the pinned Python 3.11.9, `docs/stack_check.py` 11/11,
`.gitattributes` verified working on a clean checkout
(`models/classifier.txt` MD5-identical to the OneDrive copy). Full
suite: **396 passed, 1 xfailed, 0 failed** — `test_rank_spike.py` clean
this time — in **11m55s**, against 37-44 minutes for the same suite on
the OneDrive path across this session's last two runs. Confirms both
Nehal's diagnosis and his fix, independently, on a second machine.

**Not yet done: the old OneDrive clone hasn't been deleted.** Same call
Nehal made on his own machine — left in place rather than delete a
working copy that still has everything pushed and nothing unique in it,
until it's confirmed the new location is what gets used going forward.

### 7 Sep, later — the CV router carries its own diagnostic now

Nehal's follow-up sharpened the 10dB-floor finding: `envelope_cv`
(`std(|x|)/mean(|x|)`) gives 2fsk and 4fsk the IDENTICAL value to three
decimal places at every SNR — proof the statistic carries no modulation
information at all, only an SNR one. Worse, he found that documenting
the floor in a report doesn't protect every consumer: his own chain
survives a bad low-SNR FSK CFO because `search.receive_best` defaults
`cfo=0`, but Naidhruv's orchestrator calls `plugin.receive()` directly
(`orchestrator.py:696`), with no such fallback in the path.

His ask, explicit about scope: not a redesign, just make the decision
say so in the *result*, not only in a report a caller has to already
know to go read. `S2Result` now carries `envelope_cv` — the raw
statistic, always populated (even when a caller passes
`constant_envelope` explicitly, a path that previously never computed
it at all) — so any consumer, orchestrator included, can apply its own
policy to `cfo_hz` instead of trusting `constant_envelope` blind.
Deliberately did NOT pair it with a new `low_confidence`-style boolean:
picking a threshold on `envelope_cv` for that is exactly the
undecidable crossover `s2_envelope.md` already proved has no single
right answer — inventing a second one under the same pressure that
produced the first threshold bug would repeat the mistake, not fix it.
Two new tests in `test_s2_estimate.py`, one of which pins Nehal's exact
measured table (2fsk/4fsk `envelope_cv` at all six SNRs, to 3dp) as a
regression guard.

**Worth relaying to Naidhruv directly**, since it's his file: the
`orchestrator.py:696` direct-call path has no `cfo=0` fallback the way
Nehal's own receiver wrapper does, so it's the one place in the system
still fully exposed to a bad FSK CFO below 10dB. Not something I can
fix from here — his integration layer, his call on how to handle it
(check `envelope_cv`, catch it downstream, or accept the stated floor).

### 7 Sep — the winning layer: S0 format sniffer, endianness + channel layout, evidence shown

Block B/C/D/E per the plan: extend the 29 Aug dtype-only sniffer
(`pipeline/s0_ingest.py`) to also recover byte order and I/Q channel
layout blind, with visible evidence, tested against 12 deliberately
mislabelled raw files. **Gate: 12/12**, additive only — `pipeline/s0_ingest.py`'s
existing WAV path, `read_wav_iq`, and every pre-7-Sep test are unchanged;
nothing in the 6 Sep core path was touched.

Two separate discriminators, each independently measured before trusting
it, not tuned to force a number:

- **Byte width (int8 vs 2/4-byte)**: the existing bounded/nonzero/extreme
  magnitude heuristic turned out NOT reliable for this specific question
  — measured a real int8 file scoring 0.9998 as int8 and 1.0000 as
  int16, an effective coin flip. Found a much sharper signal instead:
  for genuine int16 data the low byte of each sample is quantisation
  noise (autocorrelation ≈0); for int8 data misread as int16, that "low
  byte" is actually a real, smooth 8-bit sample, so it autocorrelates
  strongly. Measured 0.64–0.88 for true int8 vs −0.05 to 0.00 for every
  true int16/float32 file tried — a 10x+ margin, gates the byte-width
  decision as a hard prior ahead of the existing magnitude score.
- **Channel layout (interleaved I,Q,I,Q,... vs planar all-I-then-all-Q)**:
  lag-1 autocorrelation of each half-channel. A genuinely oversampled RF
  capture is smooth sample-to-sample within one real channel; splitting
  the wrong way pairs unrelated bytes and that structure collapses
  toward zero. Measured 0.44–0.87 correct vs ≈0.00 wrong, for every
  scheme tried except 4fsk (below).

Both discriminators were validated against the real RF corpus, not
synthetic noise, before either shipped.

**Two known, measured gaps, pinned rather than hidden** (same pattern as
`test_fsk_order_known_gap_at_low_snr`) — a 3-file `s0_sniffer_known_gaps`
corpus plus two tests that assert the CURRENT miss, so either starting
to pass is a signal to promote the file and delete the test:

- Byte-order recovery when the layout is ALSO planar: two independent
  ambiguities compounding is harder than either alone, and a
  discriminator sharp enough for that specific combination wasn't found
  today. Every individual byte-order case in the main 12-file corpus
  stays in an interleaved layout, where it's reliable — measured, not
  assumed (checked deliberately: swapping only the scheme under an
  unrelated dtype, e.g. accidentally combining 4fsk's layout gap with a
  new dtype instead of actually avoiding it, was caught and fixed before
  it became a silent hole in the 12/12 claim).
- 4fsk's own channel-layout detection: its tone spacing at this sps
  decorrelates adjacent same-channel samples regardless of alignment, so
  even the CORRECT split autocorrelates near zero. Still exercised in
  interleaved cases (dtype detection has no such problem); excluded only
  from layout-sensitive cases.

`zoo/build_s0_sniffer_corpus.py` (new, mine) builds both corpora from
real `zoo/corpus/rf` signals — the adversarial part is genuinely the
format ambiguity, not an easier synthetic signal. 22 new/changed tests
in `test_s0_ingest.py`, all passing; existing 4 tests unchanged and
still passing.

---

## Anvith — S3 receiver chain

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
- Everything is measured against `tests/fixtures/rf_channel.py`, which drives
  Nehal's `local_zoo`. **Dheeraj: the day your zoo lands, my fixture dies and I
  re-run every number above.** My fixture and my demodulator deliberately share
  `bitmap.py` so there is one mapping rather than two — but that does mean a
  mapping error would be invisible to both, which the Gray-adjacency test
  reduces rather than removes.
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
