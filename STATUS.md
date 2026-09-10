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

### 7 Sep, later still — `random_case` and `make_rs_stream` ported, unblocking `local_zoo.py`'s deletion

Nehal counted what's actually blocking his own standing instruction to
delete `tests/fixtures/local_zoo.py` (it's overdue since the zoo landed
in full) rather than estimating: two functions with no equivalent in
`zoo/` — `random_case` (a randomly-parameterised trial: pick
depth/width from a pool, size the stream so the hardest pool entry is
still searchable, start at a random offset) and `make_rs_stream` (a
plain RS(n,k) stream, no interleaver or scrambler — `zoo/ccsds.py`
already covers the concatenated, standards-accurate profile). Ported
both into `zoo/bits_only.py`, reusing `make_stream`'s own
`start_offset` handling for `random_case` rather than the fixture's
manual post-hoc trim (mine already draws one internally when none is
given, so the fixture's separate trim step just isn't needed). 11 new
tests in `test_bits_only.py`: reproducibility from seed alone, the
pool draw actually lands in `DEPTH_WIDTH_POOL`, the default length
clears `bits_needed(MAX_POOL_PERIOD)`, both offset modes, and
`make_rs_stream`'s RS round-trip verified through `reedsolo` directly
(encode via mine, decode via the library, bytes match the source
payload) rather than assumed from the encode step alone.

He also flagged a correction on his own reasoning, not mine to act on:
the justification he'd given earlier for keeping `local_zoo.py`
("Dheeraj's generator only does block interleavers") was wrong —
`local_zoo.make_stream` was block-only too, so the fixture never
carried diagonal or convolutional-interleaver coverage either. Noted
here since it's now part of the record, not something this commit
changes.

**Confirmed, not assumed, per his direct question**: all 252
`zoo/corpus/rf/*.json` files carry `"scrambler": null` — checked every
one, zero exceptions. One thing worth his knowing that he didn't ask
about: `zoo/corpus/ccsds/` (a separate directory) is *always*
scrambled by design — if anything on his side ever reads from there
too, the "nothing in the corpus is scrambled" assumption his S5 skip
relies on would not hold for that corpus.

Deleting `tests/fixtures/local_zoo.py` itself, and repointing the 12
test files and 7 report studies that import from it, is explicitly
his to do — not touched here.

Full regression suite: 437 passed, 1 xfailed.

### 8 Sep — break it deliberately: reproducibility locked, not just claimed

Today's column is verification, not new feature work: final envelope
run from the frozen build, regenerate from a genuinely clean checkout,
confirm the report matches the shipping binary exactly, lock it.

**Not done from an existing working copy — a real fresh clone.**
`git clone` to a throwaway directory, `git checkout dhiraj/zoo-v0` at
`2509d75`, a brand-new venv built from scratch on the pinned Python
3.11.9 (not reused from any existing `.venv`), `docs/stack_check.py`
11/11 there. The point of a clean checkout is that nothing from a
working session's accumulated state can be silently propping the
numbers up — a stale cached `.pyc`, an import left over from an
earlier experiment, a venv with one extra package installed by hand
along the way.

From that clean clone: `reports/envelope_study.py` regenerated
(`envelope.md`, `envelope_ber.csv`, `envelope_ber.png`) — **zero-byte
diff** against what's committed. Same for `models/build_dataset.py`,
`build_holdout.py` and `models/train.py` — `dataset_train.csv`,
`dataset_holdout.csv` and `reports/classifier_eval.md` all diff empty
too (after normalising the one known, already-documented CRLF artifact
from Python's `csv` module, not a real content difference), and
training reproduced the exact same config hash, `132fc1d21777`,
unchanged since 3 Sep — `models/classifier.txt` byte-identical.

**Report matches the shipping binary, and it's not a claim — every
number above was independently reproduced today, from nothing but the
git history and the pinned dependency versions.** Locking it here:
`reports/envelope.md` and `reports/classifier_eval.md` are frozen from
this point — no further edits planned before the 9 Sep freeze unless a
teammate finds something that changes the underlying measurement, the
same standard every other "known, stated limit" in this project has
already been held to.

Verification clone deleted after use — nothing left behind but this
entry and the fact that it happened.

---

## Anvith — S3 receiver chain

### 9 Sep — the guard pass: five things in S3 left the stage as a traceback, and none of them can now

**MERGED to `origin/main` as `1d181ab`**, five commits behind it, pushed at
17:46 against the 18:00 freeze. Self-merged, the seventh in this repo - branch
protection is still an open ask to Naidhruv. Verified ON MAIN after the merge
rather than on the branch: the merged tree is byte-identical to the branch tip
the full suite passed on, and `reports/s3_guard_probe.py` re-run on merged main
gives 803 cases, 0 unexpected throws, 4 of 4 control cells ok.

**The row:** "No new code. Read S3 end to end for anything that can throw.
Guards only." Definition of done: guard commits only, and the diff contains no
new functionality.

**Done. The diff, stated so it can be checked rather than taken on trust:**
three files under `pipeline/s3_receive/`, **+102/-8**. Counted rather than
eyeballed: 50 of the added lines are neither blank nor comment, 10 of those are a
docstring paragraph, so **40 lines of code** — and every one of them is either
`if <unusable>: return <the sentinel this function already documents>`,
`try/except: <the default it already had>`, or an existing expression re-indented
into one of those. **No new function, no new key on any
result, no new status, no threshold moved, no constant touched, no signature
changed.** Beside them, two files that are not stage code: 184 lines of tests in
`tests/unit/test_s3_adversarial.py` pinning the guards, and
`reports/s3_guard_probe.py`, the sweep that found them - so tomorrow's reader can
re-run the measurement instead of believing this entry. `git status` lists
`pipeline/s3_receive/`, `tests/unit/test_s3_*`, `reports/s3_*` and this
insertion, and nothing else.

**Method, because "I read it and it looked fine" is not a measurement.** Read
all 18 files in `pipeline/s3_receive/` plus `pipeline/s5_decode/ldpc_code.py`
(4 740 lines), then exercised the surface rather than trusting the read. The
sweep is committed as `reports/s3_guard_probe.py` and runs in about 90 s; it
exits non-zero on an unexpected throw, so it is a check and not only a report.
**Run on a pristine `0cc87b3` worktree and on this tree, same script, same
signal:**

| sweep | what it covers | cases | UNEXPECTED before | after |
|---|---|---|---|---|
| A | every plug-in x `receive`/`demodulate`/`classify_features` x 12 hostile captures | 216 | 0 | 0 |
| B | `receive_best` x 34 hostile parameter sets x 5 captures, plus `params_from_s2` | 187 | **24** | **0** |
| C | `lockcheck`, `softmap`, `bitmap`, the LDPC decode path | 165 | **24** | **0** |
| D | everything else `__init__` exports | 235 | 0 | 0 |
| | **total** | **803** | **48** | **0** |

55 further raises are the documented refusal contract - a record too short for
the timing loop, an order that is not a power of two, an unregistered scheme
name - and that count is **identical on both arms**, so nothing was quietly
turned from a deliberate refusal into a silent pass. Each is listed with its
reason in the script's `EXPECTED`. All four control cells read `ok` on both
arms.

**Sweep A is the one worth reading twice: the plug-in surface was already
airtight, 216 of 216, before I changed anything.** The catch-all in
`LinearDemod.receive` and `FSKDemod.receive` does what it claims on every
hostile capture I could build - empty, one sample, all-NaN, all-inf, 1e300,
1e-300, real-valued, integer dtype, 2-D, a Python list. **Everything found today
is outside those two try blocks**, which is exactly where a stage stops being
defended by them.

#### The five, in the order they would have cost time

**1. An unusable sample rate left the whole stage as a `ZeroDivisionError`.**
`receive_best` defaults `fs` to `0.0` when the mapping carries no `fs` key, and
zero is not a small sample rate — it is no frequency axis at all. Measured on a
clean 15 dB QPSK capture:

| `fs` | before | after |
|---|---|---|
| `0.0` | **ZeroDivisionError** | `failed`, names the rate |
| key absent | **ZeroDivisionError** | `failed`, names the rate |
| `inf` | **ZeroDivisionError** | `failed`, names the rate |
| `"wide"` | **ValueError** | `failed`, names the rate |
| `None` | **TypeError** | `failed`, names the rate |
| `nan` | `failed`: "every candidate was refused by the cheap screen" | `failed`, names the rate |
| `-200000.0` | `failed`: "every candidate was refused by the cheap screen" | `failed`, names the rate |

Both throwing frames are one line: `np.fft.rfftfreq(n, d=1.0 / fs)` in
`lockcheck._averaged_spectrum`. `1.0 / fs` is a plain Python division, so `0.0`
raises there and `inf` makes `d` exactly `0.0` and raises the same thing inside
numpy. `carrier_offset` reaches it by a second route — `scipy.signal.welch`
rejects a non-positive or NaN `fs` itself.

**The last two rows are the quieter half and I nearly missed them.** They did
not raise; they returned a `failed` whose reason was *"every candidate was
refused by the cheap screen"* — a verdict over a field that had no frequency
axis to be measured on. That is the same false-claim defect fix #3 closed on
7 Sep and §9c closed again this morning, arriving a third time through a
different door.

**Every plug-in has refused exactly this by name since 4 Sep**
(`base.unusable_reason`). The search never reached one, because the screening
pass runs first. Guarded in both places: in `lockcheck`, where the division is,
and in `receive_best`, so the reason names the rate instead of blaming the
screen.

**Reachability, stated precisely rather than talked up: this is NOT reachable
from the service today.** `service/orchestrator.py:762` reads
`getattr(s0_raw, "fs", None) or fs_hint or 200000.0`, and that `or` chain floors
any falsy rate at 200000.0. It is reachable from the documented public entry
point — `receive_best(iq, params)` with a hand-built mapping, or
`params_from_s2(s2_result)` with no `fs` argument — and what invites it is S3's
own default, not anybody else's input.

**2. `params_from_s2` survived an S2 that lost a field and not one that changed
its type.** Its docstring promises "everything here is a `getattr` with a
default, so an S2 that grows a field gets used and an S2 that lacks one still
works". A present-but-`None` attribute takes the attribute, not the default, so
`float(None)` raised TypeError; a ranked list arriving as a scalar raised
`TypeError: 'int' object is not iterable`. **This is the exact shape of 8 Sep's
`order_hint` finding** — a default that cannot fire because the attribute is
there — now in my own file rather than in Naidhruv's. An unreadable number
becomes `0.0`, which finding 1 now refuses by name; an unreadable ranking
becomes an empty ranking, which is what the function already returns for an
absent field.

**3. A symbol rate that would not coerce raised out of `_build_candidates`.**
`_ranked` has dropped an uncoercible hypothesis since the morning the classifier
landed and handed this module the string `'qpsk'` where it expected a number.
The two singleton fallbacks beside it were the same coercion written without the
same care. **The scores are unchanged, so no valid input moves prior** — only
the failure path is new, and it lands on the empty list `receive_best` already
answers with "S2 supplied no usable symbol rate hypothesis".

**4. `bits_per_symbol(0)` raised from inside the check that exists to catch it.**
`(0).bit_length() - 1` is `-1`, and `1 << -1` raises
`ValueError: negative shift count` one line before the message that would have
said what was wrong. It did raise — about its own arithmetic rather than about
the input. Every valid order is untouched and an invalid one still raises
`ValueError`; only what it says changed.

**5. No hang anywhere in S3, and this was checked rather than assumed.** Three
real `while` loops in the package. `bitmap.gray_inverse` is bounded at 64.
`search.receive_best`'s screening loop grows its own queue as it goes, and is
bounded by `MAX_CANDIDATES` and a `seen` set with the index advancing every
iteration. `timing.gardner_sync` advances `pos` by `period / 2` twice per
iteration, and `period` is clipped to `sps * (1 ± max_rate_dev)` with
`max_rate_dev = 0.05` and `sps >= 2.0` enforced at entry — so the tracked period
cannot reach zero and the loop cannot stall. **A stall would be worse than a
throw on demo day and the row does not name it, so it is worth saying that it is
not there.** `filters.rrc_taps` already caps taps at 8 191, which is the
allocation blow-up I went looking for and someone had already closed.

#### What did NOT change, and where this has no power

**252 corpus files, 15 outcome columns, run end to end through
`estimate` → `params_from_s2` → `receive_best` on a pristine `0cc87b3` worktree
and on this tree: zero differing cells out of 3 780, `reason` byte for byte.**
`status == "ok"` on 238 of 252 both sides; confidently wrong 0 both sides.

**Say the limit out loud: every corpus file carries `fs = 200000.0` and
well-formed parameters, so NOT ONE ROW enters any branch this diff touches.**
That table is evidence that the normal path did not move and is **not** evidence
about the guards. The evidence about the guards is the 803-case sweep above and
the tests below. This is house rule 8 applied to a regression check, and it is
the same caution §9c had to add this morning.

**Tests.** S3 unit + `tests/contract` on the guarded tree, before the new tests
were written: **372 passed, 4 skipped** — the same number §9c recorded this
morning, so nothing that already existed moved. With the new section:
**386 passed, 4 skipped**. `tests/unit/test_s3_adversarial.py` goes
**56 -> 70**: 5 new tests, 14 cases, every assertion on a status, a reason or a
sentinel and not one on the clock.

**The FULL suite on the guarded tree: 945 passed, 4 skipped, 2 xfailed, 0
failed, 17m37s.** Run because a freeze day is the wrong day to merge on a
targeted subset, and because `lockcheck` is imported by `reports/` and `search`
by anything that adapts S2 - neither is S3-private. The one warning is a
starlette/anyio deprecation that predates this branch. For comparison, 8 Sep
recorded 900 passed / 4 skipped / 2 xfailed in 18m36s on this box.

**The known-answer cell is FIRST in the new section, not after it.** Every other
test there asserts that something is REFUSED, and a capture S3 could not
demodulate at all would make all of them pass while proving nothing. That is
precisely the 8 Sep hand-rolled-transmitter failure, where three of six
adversarial cases could only ever have reported a refusal — so the countermeasure
now guards the tests written to prevent its cousins.

#### Found, measured, NOT touched

- **`filters.estimate_occupied_band` and `estimate_rolloff` raise
  `IndexError: index -1 is out of bounds` on an EMPTY capture**, where every
  other function in the package answers cleanly. Left alone deliberately:
  `estimate_occupied_band` has no caller in the repo at all, and
  `estimate_rolloff`'s single caller (`linear.py:288`) sits behind the
  record-length check that already refuses a capture this short. Unreachable
  today, and inventing an occupied band for an empty array would be a worse
  answer than a raise. It is the message that is wrong, not the refusal.
- **`carrier_alignment` returns PASS when `carrier_offset` had nothing to
  measure.** `carrier_offset` documents 0.0 as "absence of evidence", and
  alignment reads it as a measured zero and passes. Not reachable as a false
  confirmation today — `signal_presence` fails first on every input where the
  offset is unmeasurable, and the search now refuses an unusable `fs` before
  either runs — but it is a `pass` with no evidence behind it, which house rule
  3 says is worse than no check. **Changing a check's verdict is not a guard**,
  so it is not a freeze-day change. Worth twenty minutes after the 11th.
- **`bitmap.symbol_labels` has no ceiling** where `rrc_taps` has one:
  `symbol_labels(2**40)` asks for 8 TiB. Its order always arrives from a
  registered `Scheme` (largest is 16), so there is no path to it. Recorded
  because the asymmetry with `rrc_taps` is the kind of thing that reads as an
  oversight later.
- **`pipeline/s5_decode/ldpc_code.py` is in Nehal's directory and I did not
  touch it.** Probed through `CODES["ldpc"].decode` on empty, short, all-NaN and
  all-inf streams and with no parameters: every case raises a deliberate
  `ValueError` naming the shortfall, which matches how `ConvCode` and `RsCode`
  behave, and nothing on the service path dispatches LDPC anyway
  (`reports/s3_ldpc_design.md` §7). Nothing owed.

#### Block D — the 60-second explanation of the receiver chain

Written down rather than rehearsed silently, because 10 Sep's row is "each can
narrate their stage in 60 s, practise once against each other" and a version on
paper is one the others can hold me to.

**Length, counted rather than felt.** The first draft ran 169 words. A person
explaining something technical speaks at 130-150 words per minute, so that is
68-78 s - over budget, and I had written "about 62 s" under it by assuming 160.
**137 words is what fits**, counted on the block below: 55 s at 150, 59 s at
140, 63 s at 130. The blindness gate came out of the narration and into the follow-ups
below, where it answers a question rather than spending eight seconds unasked.

> Stage 3 is the receiver. It gets a raw capture and, from Stage 2, ranked
> guesses at symbol rate, carrier offset and modulation. It never gets the
> answer.
>
> For each guess it runs one cheap check first: is there a symbol-rate line
> where you say there is? One FFT, and most of the field is gone before any real
> work. What survives goes through the chain - matched filter, Gardner timing
> recovery, blind equaliser, Costas carrier loop - and comes out as soft bits,
> the log-likelihood ratios Stages 4 and 5 need.
>
> The part I would point you at is that it refuses. Seven checks run, six get a
> vote, any one can veto. Across 252 files it is confidently wrong zero times. A
> wrong answer given confidently is worse than no answer. That is the design.

**"How do you know it never sees the answer?"** A test greps every file in this
directory, case-insensitively, for the word - and fails if it appears even in a
comment. `reports/` and `tests/` are exempt and may read the answer key; the
stage itself may not.

**The follow-up I expect, and the answer, because "where does it fail" is the
question a judge actually asks.** 8-PSK and 16-QAM at 4 dB — fourteen files. It
refuses all fourteen rather than guessing. How much of that is physics is
measured, not asserted: `reports/s3_bound.md` puts seven cells at 1.0–1.5x the
ideal AWGN bound and those two at 7.2x and 12.5x, so most of the gap is the
carrier loop and is written up rather than explained away. Do **not** say "it is
the operating envelope" — that claim was repeated for two days on an
observation that never tested it, and the bound calculation is what disproved
it.

**Numbers checked today before saying them out loud**, because the 7 Sep entry
records a worst-case second being copied rather than re-read: seven checks with
six voting is measured on `qpsk_20dB_2011` (`equaliser_converged` records
`unknown` and does not vote, which §8 already lists as open); 252 files and zero
confidently wrong are from today's own before/after run, both arms.

### 9 Sep, small hours — the Core Lock S3 failure is a test asserting a property of the MACHINE, plus one real defect it turned up

**Naidhruv's report:** Core Lock Docker full pytest, one S3 failure,
`tests/unit/test_s3_lockcheck.py::test_a_search_the_clock_cut_short_says_so`,
expected `search_budget_exhausted=True`, got `False`.

**The receiver is not at fault and neither is his image. The test was.** It ran
the real search against a real `budget_s=0.9` and asserted the clock won — which
is an assertion about how fast the box is, not about what the code does.
Measured here on the same signal (`synth("qpsk", n_bits=120000, snr_db=16,
cfo_norm=0.0015, timing_offset_sym=0.42, seed=11)`):

| budget | wall | `search_budget_exhausted` | chain runs |
|---|---|---|---|
| unbounded | 3.62 s | False | 3 |
| 0.9 s | 2.13 s | **True** | 1 |
| 1.5 s | 1.99 s | **True** | 1 |
| **2.0 s** | 3.23 s | **False** | **3** |
| 5.0 s | 3.88 s | False | 3 |

The whole search costs 3.62 s on this box, so a 0.9 s budget cuts it off after
one chain run. **Any box that runs this workload ~4x faster finishes the field
inside 0.9 s and correctly reports `exhausted=False`** — which is what Docker
saw. I could not reproduce it: there is no Docker on this machine (Dheeraj has
the daemon, per his 8 Sep entry), so the exact ratio is his to confirm, not
mine to assert. **One datapoint settles it if you want it on the record**, run
inside the image:

```bash
python -c "
from tests.fixtures.corpus import synth
from pipeline.s2_estimate import estimate
from pipeline.s3_receive.search import receive_best, params_from_s2
import time
x, fs, rs, _ = synth('qpsk', n_bits=120000, snr_db=16.0, sps=4,
                     cfo_norm=0.0015, timing_offset_sym=0.42, seed=11)
p = params_from_s2(estimate(x, fs), fs)
t = time.perf_counter(); r = receive_best(x, p, budget_s=600.0)
print(round(time.perf_counter()-t, 2), 's,', r.values['search_chain_runs'], 'runs')"
```

Under 0.9 s there means it is pure speed and nothing else is going on.

**This is the wall-clock-assertion trap my own notes already name, sprung from
the fast side instead of the slow one.** The 7 Sep entry says every new test
here asserts on WORK — keys, ordering, chain runs — "which reads the same on any
machine", and names `assert elapsed < N` as the instrument that produced Nehal's
flake in the first place. Then I wrote `budget_s=0.9` and asserted the outcome
of a race. The sibling test one line below,
`test_a_search_stopped_by_the_run_ceiling_does_not_blame_the_clock`, had it
right all along: it bounds the search with `max_chain_runs=1`, a unit of work,
and cannot flake anywhere.

**The fix: the budget is now spent in ticks of work.** `search.time` is swapped
for a counter that advances one unit per `perf_counter()` reading, and
`receive_best` reads it once on entry, once per screened candidate and once per
chain-run iteration — so a tick budget is a work budget. Two candidates and 3.5
ticks put entry at 1.0, the two screened candidates at 2.0 and 3.0, the first
chain run admitted at 4.0 and the second refused at 5.0: **one run made, one
survivor never reached, on every machine at every speed.** The shape the
arithmetic assumes is asserted from an unbounded reference run in the same test
rather than trusted, and the failure message says so if it ever moves.

Two tests added beside it:

- `test_the_truncation_flag_and_the_note_never_disagree` — the only claim about
  real seconds that is safe to make on an unknown box. Not "0.9 s truncates
  this search", which is a claim about the box; the invariant is that
  `search_budget_exhausted` and the `truncated` note in `reason` cannot
  contradict each other, whichever way the clock falls. Swept over four real
  budgets, so a fast box exercises the `False` branch of every one and a slow
  box the `True` branch.
- `test_a_search_cut_short_before_any_run_does_not_blame_the_screen` — the
  defect below.

#### The defect the probing turned up, and it is mine

**A search the clock stopped mid-screen claimed it had surveyed the field.**
Measured on the same signal at a 0.2 s budget, before the fix:

```
status=failed  exhausted=True  runs=0
reason: every candidate was refused by the cheap screen: no symbol-rate line
        at 27040 Hz (3.6x local median, needs 4.5x) - either nothing is here
        or the rate is wrong
```

**12 of 54 candidates had been screened. 42 were never looked at**, and one of
the twelve's rejection detail is quoted after the sentence as though it were the
finding. This is exactly the false claim fix #3 closed on 7 Sep — for the path
that HAS a result. The path that has none was left open, and it is the one a
tight budget reaches first. It now reads:

```
search truncated by a 0.2 s budget before anything could be demodulated: 12 of
54 candidates were screened, 5 survived and none was run - this is not a
verdict over the field
```

The one-candidate rejection detail is dropped in that case for the same reason:
it is not why the search stopped. The appended note on the path that does have a
result also grew a second clause, because "survived the screen and was never
run" and "the screen never reached it" are two different facts and a truncated
screen produces both.

#### Verification

- S3 unit set + `tests/contract`: **372 passed, 4 skipped, 5m36s** (S3 unit was
  308, now 310 with the two new tests; contract 62/4).
- **Before/after on 32 corpus files**, every 8th of the 252 so the sample spans
  every modulation x SNR cell, blind `search` arm at the default budget:
  **all nine outcome columns identical on all 32** — status, modulation, chain
  runs, candidates, screened out, exhausted, chosen, rate used, and `reason`
  byte for byte.
- **State that sample's limit rather than let it read as more than it is:**
  `exhausted` was True on **0 of the 32**, so the sample never entered the
  branch I changed. It shows the normal path did not move; it is not evidence
  about the fix. What covers the fix is the budget sweep above (0.05 / 0.2 /
  0.6 / 600 s plus a `max_chain_runs=1` ceiling stop) and the three tests.
- On the path where screening completes, the appended note is **byte-identical
  before and after** — measured, not argued: same signal at a 0.6 s budget
  produces the same sentence on both trees.
- Both changed files compiled from the source string with the `.pyc` bypassed
  and `SyntaxWarning` as an error, per the 8 Sep lesson about a check that
  answers from a cache.

**Scope against today's row**, which says read S3 for anything that can throw,
no new code, guard commits only: the diff is one red test made
machine-independent, two tests added, and a false claim removed from a `reason`
string. No status, no LLR, no threshold and no constant moved. `SEARCH_BUDGET_S`
is untouched — widening it would have bought the test a pass and left both
mechanisms, which is the 7 Sep lesson.

#### The other two failures in the same report — neither is on `main`, neither is S3's

Naidhruv asked the S2/eval owners to check ownership and regression on
`tests/eval/test_harness.py::TestEvalHarness::test_cli_main_entry` and
`tests/service/test_orchestrator.py::TestOrchestrator::test_get_s2_estimate_does_not_import_local_s2`.
Traced both, touched neither:

1. **`test_cli_main_entry` fails when the corpus is absent — which is what the
   Core Lock image is.** `eval/__main__.py:112` on `main` looks for
   `zoo/corpus/rf/*.json`; with none it calls `parser.print_help()` and returns
   0, so `--json` mode prints the argparse usage text and the test's
   `json.loads(output)` raises `JSONDecodeError: Expecting value: line 1
   column 1`. Reproduced here by pointing `config.repo_root` at an empty
   directory: corpus present → parses as JSON; corpus absent → usage text.
   **Same root cause as the corpus-missing report Dheeraj traced yesterday**:
   `fc259ea` on `naidhruv/integration` adds `zoo/corpus/` to `.dockerignore`.
   **Naidhruv already has the fix on his own branch — `8c6bd0e` "fix: make eval
   json mode work without corpus" — and it is not on `main`.** Merging that
   branch or cherry-picking that commit closes it.

2. **`test_get_s2_estimate_does_not_import_local_s2` does not exist on `main`** —
   it is only on `origin/naidhruv/integration`, at `test_orchestrator.py:406`.
   It is a test-isolation defect, not a regression in anyone's stage. It patches
   `sys.modules["pipeline.s2_estimate"] = None` and expects `get_s2_estimate()`
   to return None, but `service/orchestrator.py:183` does `from pipeline import
   s2_estimate`, which reads the **attribute off the already-imported `pipeline`
   package** and never consults `sys.modules`. So it passes in a cold process
   and fails in any run where something has already imported the module — which
   in a full suite is everything. Measured in one process:

   ```
   COLD (pipeline.s2_estimate not yet imported): get_s2_estimate() -> None
   WARM (after `import pipeline.s2_estimate`):   get_s2_estimate() -> <function estimate>
   ```

   His file and his branch, so his call, but the smallest fix is to patch the
   package attribute alongside the `sys.modules` entry —
   `mock.patch.object(pipeline, "s2_estimate", None)` is enough to make
   `get_s2_estimate()` fall through to the `return None` it is testing for.
   Worth noting the branch also carries `test_s2_resolves_to_the_real_pipeline_stage`,
   which pins the same behaviour without the isolation problem.

### 8 Sep — "break it deliberately": the six adversarial inputs, and three findings that are not mine

**The row is met and the verify line is met.** Six adversarial inputs to S3 —
pure noise, DC, clipped, two overlapping signals, empty band, wrong sample
rate — each over 8 seeds, through **both** the named-plug-in path and the blind
search the service actually calls. Then the six as real `.wav` files through
`python -m service.cli analyze`, S0–S6.

| | result |
|---|---|
| tracebacks, every path, every case | **0 of 504 runs** |
| statuses outside `ok`/`low_confidence`/`failed`/`out_of_envelope` | **0** |
| non-finite values in an LLR array | **0** |
| **`ok` on a case with no signal in it** | **0 of 280** |
| six files end to end through the CLI | **6 clean statuses, 0 exceptions** |
| **the FULL suite** | **900 passed, 4 skipped, 2 xfailed, 0 failed** (18m36s) |

**The full suite is GREEN for the first time this week.** It has read red in my
notes since 7 Sep (31 failed / 780 passed / 6 errors). Both causes are gone:
Nehal fixed the `registry.clear()` teardown at source, and the `service/` half
was never a code defect — see the third item below.

Full write-up, per-seed table and reproduction: `reports/s3_adversarial.md`.
Study: `reports/s3_adversarial_study.py` (`--render-only`, `--write-files`).
Files: `reports/s3_adversarial/*.wav`. Tests:
`tests/unit/test_s3_adversarial.py`, **56 tests**; the S3 unit set is
**308 passed** with them (was 252).

**Why this was not already covered.** The 4 Sep adversarial block in
`test_s3_receive.py` calls `MODULATIONS[name].receive(iq, params)` — a NAMED
plug-in handed a symbol rate. The service calls `receive_best`, which has a
ranked search, a rate rescue, a de-duplication grid and a deadline that the
plug-in path never touches. All of that landed on 7 Sep in `e7b9649` and none
of it had ever been shown an adversarial input.

**"Adversarial" turned out to be two questions, and scoring them as one was a
bug in my own study.** A hard-clipped QPSK capture comes back `ok`/qpsk and is
**right** to: QPSK is constant-modulus, clipping at a quarter of peak takes
peak-to-average from 1.72 to 1.02 and the symbols survive (measured BER 0.00
against the transmitted bits). So the set splits — **absence** (noise, DC,
empty band, zeros, impulse) where `ok` is a confident lie and must never
happen, and **degraded** (clipped, overlapping, mislabelled) where `ok` is
correct when the answer is correct. My first pass called the clipped row a
defect. The tests assert the two classes separately for this reason.

#### The S3 finding: a wrong `fs` is invisible, by construction

`wrong_sample_rate.wav` is a clean 200 kHz QPSK capture whose header says
48 kHz. S3 returns `ok`, modulation `qpsk`, measured BER **0.00** — a
completely correct demodulation — and reports `symbol_rate_used` of
**12,000 Hz against a true 50,000 Hz**. That is exactly 48000/200000.

Every stage of S3 works on `fs / symbol_rate`, so a declared `fs` wrong by a
factor *k* gives a symbol rate wrong by the same *k*, a residual CFO wrong by
the same *k*, and **every internal consistency check passing** — they are all
ratio-based. `sps_estimated` still reads 4.00007.

**S3 cannot fix this and it is not a defect.** Absolute time is not in the
samples; it arrives only from the WAV header or the service's `fs_hint` form
field. But it is a confidently-wrong *number* in a user-visible field under an
`ok` status, reachable by a judge in five seconds without touching the signal.
The honest sentence is: **every absolute-frequency quantity S3 reports is
proportional to the declared sample rate and is only as trustworthy as that
header.** Pinned by `test_a_mislabelled_sample_rate_scales_the_reported_rate`
so a future change here is visible rather than silent.

Also worth having before the gate: **`two overlapping signals` is the most
expensive input measured this week** — it runs to the chain-run ceiling on
every seed at **6.15–6.58 s** here, ~13.8 s on Nehal's 2.09x box against the
20 s budget. Correct behaviour (no right answer to converge on, so the search
exhausts its list) and inside budget, but it is the smallest margin in the set
and two emitters in one band is not a contrived input.

#### NAIDHRUV — READ THIS ONE FIRST: the service demodulates everything as QPSK

Found by running the six adversarial files through `python -m service.cli
analyze` and noticing all six reported `modulation: qpsk`, including the ones
`receive_best` calls `16qam` and `2fsk`. Not touched — `service/` is yours.
Full write-up `reports/s3_adversarial.md` §10.

**Measured, 40 random corpus files, both paths, scored with
`corpus.measured_ber` against the transmitted bits:**

| path | decodes | modulation correct |
|---|---|---|
| `receive_best(...)` — what S3 can do | **35/40** | **37/40** |
| `MODULATIONS[chosen_scheme].receive(...)` — what the service does | **11/40** | **11/40** |

24 of 40 disagree, and every disagreement has `chosen_scheme == "qpsk"` against
a true scheme of 2fsk / 4fsk / 8psk / 16qam.

**The chain, read rather than inferred:**

1. **`orchestrator.py:323` reads a field that does not exist.**
   `order_hint = getattr(raw, "order_hint", 0)` — **`S2Result` has no
   `order_hint`**; its field is `fsk_order_hint`. The default fires on every
   input: `order_hint` is **0 on 30 of 30** corpus files measured.
2. `order_hint == 0` takes the `else` branch of the ladder at 341-349, which
   returns `[qpsk 0.7, bpsk 0.3]` — always.
3. **Dheeraj's classifier is computed and discarded.**
   `S2Result.modulation_hypotheses` is populated on **28 of 30** files and
   `adapt_s2` never reads it. On `2fsk_15dB_6028` it says `2fsk` at **0.9987**
   while the adapter hands S3 `qpsk` at 0.7.
4. `orchestrate:844` takes `s2_res.hypotheses[0].value` → `qpsk`.
5. **`_run_s3` (856) runs that one plug-in, never `receive_best`** — so the
   search, rate rescue and breadth-first ordering from `e7b9649` are
   unreachable from the API and the CLI.

This is the third instance of the same species in this file — a `getattr`
against a name that does not exist, silently taking its default. My 7 Sep notes
already record "one orchestrator test asserting `est.symbol_rate` where
`S2Result` has `symbol_rate_hz`". Nothing raises; every stage returns `ok`; the
report just says the wrong modulation.

**Suggested, and it is your call:** have `adapt_s2` prefer
`raw.modulation_hypotheses` when present, and have `_run_s3` call
`receive_best(iq, params_from_s2(s2_raw, fs))`. `receive_best` treats the
ranking as a PRIOR rather than a restriction, which is the difference between
35/40 and 11/40. If neither lands before freeze, the honest fallback is to stop
reporting a modulation the service did not determine — `qpsk` is currently a
hardcoded default shown to a judge as a finding.

#### NAIDHRUV — two confidence bugs the six files found, both in your adapters

Running `pure_noise.wav` end to end. No tracebacks anywhere; the final answer is
correct because S3 refuses. But a judge reads the stage cards on the way to it:

| stage | status | confidence | what its own values say |
|---|---|---|---|
| s0_ingest | `ok` | 1.00 | a valid WAV — true |
| s1_detect | `ok` | **0.98** | `snr_db` **−10.2**, `occupied_bw` 198 kHz of 200, `burst_count` 0 |
| s2_estimate | `ok` | **0.90** | `symbol_rate` 45,350 Hz, `symbol_rate_score` **0.0** |
| s3_receive | `failed` | 0.00 | `signal_present: fail`, metric 3.83 vs 4.5 |

**S3 is the first stage in the chain that refuses pure noise**, and three green
confident cards precede it. That is risk #15 rendered on screen, on the day the
command centre calls the false-positive test mandatory because "a judge WILL
try this".

1. **`adapt_s1`, `service/orchestrator.py:293` — `confidence=0.98` is a
   constant for any `ok`.** It means "the stage ran" and renders as a detection
   confidence. Everything needed for a real one is already in `values` three
   lines up: `snr_db`, `occupied_bw_hz`, `burst_count`. Same shape in the
   attached hypothesis: `"continuous"` at score **0.95** with
   `evidence="0 bursts detected"` — a 95% score whose stated evidence is that
   nothing was found.

2. **`adapt_s2`, `service/orchestrator.py:338` — the confidence inverts at
   zero.** The line is `min(1.0, max(0.1, score / 10.0)) if score else 0.9`. A
   `symbol_rate_score` of exactly **0.0** is falsy, takes the `else`, and
   renders **0.90**:

   | `symbol_rate_score` | 0.0 | 0.5 | 1.0 | 5.0 | 9.0 |
   |---|---|---|---|---|---|
   | rendered confidence | **0.90** | 0.10 | 0.10 | 0.50 | 0.90 |

   No evidence at all reports the same confidence as a score of 9 and **nine
   times** that of a score of 0.5. The guard tests truthiness where it means
   "is present", and 0.0 is both present and the worst possible score.
   `pure_noise.wav` hits it every run. Two characters:
   `if score is not None else`, or drop the fallback.

**Third, and this one is good news: `tests/service` is GREEN.** It read 13
failed / 47 passed here, and the visible error was
`TypeError: cannot unpack non-iterable Route object` at `service/main.py:587` —
three steps downstream of the cause. The chain, read rather than inferred:
starlette 1.6.0's testclient requires **`httpx2`**, which Nehal pinned in
`requirements.txt` today (`a3e69df`) and which was **not installed in this
`.venv`**; so `from fastapi.testclient import TestClient` raises RuntimeError;
so `main.py` falls back to `FallbackTestClient`; whose `_match_route` unpacks
`app.routes` as 4-tuples while `HAS_FASTAPI` is True and the routes are real
starlette `Route` objects. `pip install httpx2==2.12.0` — the pin already in
your requirements — takes it to **60 passed**. Not a code defect; a stale venv.

That also settles the apparent contradiction between my 7 Sep note ("the string
httpx does not appear once in the failure log") and Nehal's requirements comment
crediting httpx2 with the 41 failures. **Both were right, about two different
problems.** My note was right that `httpx` did not appear in the Route-error
log; Nehal was right that the test client could not be constructed at all. The
blanket phrasing of my note was broader than what it had measured.

**Neither of the two confidence bugs touched — `service/` is yours.** Both
reproduce from `reports/s3_adversarial/pure_noise.wav`. **And this is not Dheeraj's bug**: I
checked `s1_detect.detect()` rather than assuming, and it returns `status="ok"`
whenever it did not raise on a non-empty array — it carries no detection
predicate because S1 is a measurement stage, not a decision stage. Its numbers
are honest; −10.2 dB SNR over 99% of the band is exactly what noise looks like.
The status is right and the confidence attached downstream is what is wrong.

The six files are yours to use for the failure matrix if they help.

#### NEHAL — LDPC on the service path, written down so nobody files it as a bug

Full answer, checked on `4d25434` rather than remembered:
**`reports/s3_ldpc_design.md` §7.**

**Nothing supplies H on the service path and nothing is designed to.** One
correction to the framing: "CLI/test-only" gives the CLI too much credit.
`service/cli.py:109` calls `orchestrate` with `run_id`, `file_path`, `fs_hint`,
`mod_scheme_hint` and **no `stage_overrides`**, so `analyze` reaches the same
hardcoded `CODES.get("conv")` the HTTP path does. Accurate statement:
**in-process-Python-only** — `CODES["ldpc"]` by name, or
`orchestrate(..., stage_overrides={"s5_decode": ...})`.

**Line 909 is the visible half, not the binding one.** Making it iterate `CODES`
would not make LDPC reachable:

```
CODES                            ['conv', 'ldpc', 'reed-solomon']   <- your loader fix works
ldpc.blind_recover(<any llrs>)   -> None
ldpc.decode(llrs, {})            -> ValueError: no parity-check matrix supplied
```

The failure would move from "never dispatched" to "dispatched and declines",
which looks identical from outside and is harder to debug. **The binding
constraint is transport, and there is none**: grepping `service/`, `contracts/`
and `web/` for `H`, `H_rows`, `H_alist`, `parity`, `alist` returns one hit —
`parity_taps` in `adapt_s4`, convolutional taps, unrelated. `/upload` takes
`file`, `fs_hint`, `mod_scheme_hint`, full stop.

**It should ship this way**, and that is a judgement so it is on the table: the
judge uploads a WAV and no demo input carries an H; blind recovery is the only
thing that would supply one and it is on the *do not build, ever, this sprint*
list; and an alist upload is new file-parsing surface on a public route 24 hours
before freeze, for a case nobody will exercise. **Deliberately unreachable
through the API — a decoder held ready for an input the service has no way to
receive.**

What would have to change, in order, so it is a decision with a price and not an
oversight: a transport carrying one of the three H forms
`parity_check_from_params` already accepts; a dispatch that selects a code
plug-in **at the same time** (or the result is a silent decline); and a guard
that decodes `status == "ok"` streams only — non-negotiable, because on a
refused stream the demodulator emits magnitudes of 4–8 promising ~0.4% error
over bits wrong 29–39% of the time (81.7x worst per-bin against 1.62x on the
`ok` population). §7 also says plainly that `CODES.get("conv")` is **not** a
house-rule-5 violation to be scored: the code plug-ins take different parameters
from each other, unlike the modulation plug-ins, so that seam is genuinely
harder and it is yours and Naidhruv's call how it should look.

**Your three fixes, verified here independently.** `CODES` reads
`['conv', 'ldpc', 'reed-solomon']` through `load_plugins()`. The registry
snapshot/restore in `test_registry_contract.py` is in place. And thank you for
the S3 flake confirmation on the box that actually had it — 8/8 at ~10.5 s
against 20 s. Chain runs 8 → 3 is the number that reads the same on both our
machines, which is why it was the one worth quoting.

#### What I got wrong today

- **I hand-rolled a QPSK transmitter inside my own study.** Rectangular pulses,
  its own noise. The known-answer cell caught it on the first run: the clean
  control came back `low_confidence`/2fsk on **8 of 8** seeds and 0 of 8 `ok`.
  The receiver was right and the generator was wrong — S3's matched filter is
  RRC. Worse than the control row: `clipped`, `two overlapping` and `wrong
  sample rate` were all **built on** that generator, so three of the six cases
  were clipping, summing and mislabelling a signal S3 already refused, and could
  only ever have reported a refusal whatever the receiver did. That is §10's "a
  study that measured something other than what its title said", and it is the
  same species as 4 Sep's deleted `rf_channel.py`: `synth`'s own docstring
  records that a second modulator was removed so the repo would have exactly
  one, and I quietly added one back. **The known-answer cell has now paid on
  five separate days. Put it in the table first, every time.**
- **I wrote the six files in the corpus's own PCM_16 format and it destroyed
  one of them.** Checked during verification rather than assumed:
  `empty_band.wav` came back with **2 distinct sample values** across 240,000.
  At a peak of 4.85e-06 one PCM_16 quantum is 3.05e-05, so the whole capture
  collapsed onto ±1 LSB — a one-bit dither pattern where the array in memory is
  thermal noise 120 dB down. **The one property that case exists to test is
  exactly the one a fixed-point format cannot carry**, and my own comment three
  lines above the `sf.write` explained why the level had to be preserved while
  the subtype threw it away. Now `subtype="FLOAT"` (239,585 distinct values),
  and the on-disk verdict now matches the in-memory seed-0 case, which it did
  not before. Following the corpus was the right instinct and the wrong call.
- **Then I over-corrected and asserted byte-identity on those files.** Red on
  all six at byte 60 while every sample matched: libsndfile stamps a `PEAK`
  chunk with a creation **timestamp** on float WAVs, so a float WAV is
  deliberately not byte-reproducible. It would have been a permanently red test
  guarding a property the format does not offer. Now compares decoded samples,
  rate and subtype — which is all anything downstream reads. Two wrong versions
  of one check in a row, in opposite directions, and the second looked stricter.
- **`hash(case)` as a seed.** Python salts string hashing per process, so the
  study would have drawn a different corpus on every run and the six committed
  `.wav` files would not have regenerated — while looking perfectly
  deterministic inside any single run. Caught by reading it back before running,
  not by running it. Now `zlib.crc32`, and
  `test_the_committed_files_are_reproducible_from_the_study` pins it.
- **I wrote a false timing claim into the report** — "well under a second for
  every other adversarial case" — when `empty band` had peaked at 2.50 s in the
  table directly above it. Caught by re-reading the rendered markdown against
  its own CSV. Fixed to name the real second-worst case.
- **My first probe shared one RNG stream across cases in dict order**, so adding
  a case re-drew the others and `empty band` changed verdict between two runs of
  what looked like the same experiment. Neither verdict was wrong; the single
  draw was never a measurement. Everything is per-case seeded and swept over 8
  seeds now.

### 7 Sep, afternoon — the S3 budget fix exists and is NOT on main, plus the 7 Sep column

**NEHAL — read this first. Your measurement is right and your diagnosis is
right. The fix is already written; it is in PR #13 and PR #13 is not merged,
so your tree cannot have it.** You checked that `search.py` is bit-identical to
`origin/main` before reporting, which was the correct thing to do and is
exactly what pins the problem: `origin/main` does not contain the fix.
`git diff --stat origin/main pipeline/s3_receive/search.py` against
`anvith/s3-core-lock` is +141/-6.

**Measured on this machine, same signal, same params, both trees:**

| | `origin/main` (your tree) | `anvith/s3-core-lock` (PR #13) |
|---|---|---|
| chain runs to reach QPSK | 8 | **3** |
| `receive_best` wall time | 10.25 s | **3.02 s** |
| pytest wall, 8 fresh processes | 12.21–12.57 s | **4.29–4.53 s** |
| smallest budget still answering `ok`/QPSK | 9 s | **2 s** |
| answer at a 5 s budget | `low_confidence`/8-PSK | **`ok`/QPSK** |

**Your 21.4 s is consistent with my 10.25 s** — your box measures 2.09x mine on
this workload. Scaling the fixed branch by the same factor puts the answer at
about **6.3 s against the 20 s budget, 3.2x margin**, where main gives you
107%. It also explains the result that surprised you: stopping OneDrive takes
21.4 s to 18.8 s, which is **94% of the budget**. At 94% the run-to-run
variance still straddles the deadline, so the flake survives a quiet machine —
your table showed exactly that, and the arithmetic agrees with it.

**I could not reproduce the flake here, and that is not evidence.** 8 fresh
processes on `origin/main` on this machine: 8 passes. The budget governs
`receive_best`, which costs 10.25 s here against your 21.4 s - so this box has
**1.95x headroom where yours has 0.93x**. A machine fast enough
not to see it is not a machine that has tested it — the chain-run count is the
number that reads the same on any hardware, and it is 8 against 3.

**Both things you asked for stayed exactly as they were.**

* `lockcheck.ALPHABET_ENTROPY_LIMIT` is **0.90**, unchanged and untouched. You
  were right that it is the hero here: an 8-PSK answer to a QPSK signal is what
  a truncated search returns, four of the eight points are the QPSK
  constellation and the other four are empty, and the guard refusing it is the
  guard working.
* `SEARCH_BUDGET_S` is **20.0**, unchanged. Widening it would have bought the
  test a pass and left the mechanism. Its docstring moved instead: the budget
  is a fixed clock over work that scales with capture length, so "twenty runs
  at 1.0 s" is true of the corpus's 80 000-sample files and not of a 240 000-
  sample one.

**Your suggestion 3 I did NOT take, and here is why.** Accepting
`low_confidence` when `search_budget_exhausted` is True would make the 1 Sep
blind-path gate pass on the machine where it matters most — a slow one — while
the chain no longer reached bits. What I took instead is the half of your point
that is unarguable: **that test failed with the wrong error message, and it
cost you a day.** The first assertion to go was `status == "ok"`, and the text
it printed came from the evenness guard, which reads as an accusation against
`lockcheck` and is not one. There is now an assertion that fires BEFORE it,
reading (the count is filled in at run time - this is the text as printed on a
truncated run):

    the search did not finish: 1 chain runs, stopped at one of its two bounds.
    What it returned is the best of a partial candidate list rather than the
    search's answer, so read the reason below as a symptom and not as a
    verdict. The fix is to find why the answer got expensive - NOT to raise
    SEARCH_BUDGET_S, and NOT to loosen ALPHABET_ENTROPY_LIMIT.
    reason: only 4 of 8 constellation points carry traffic (evenness 0.667,
    needs 0.90) - ...; search truncated by a 1 s budget: 1 of 18 surviving
    candidates were run and 17 never reached - this is the best of what ran,
    not a survey of the field

It names neither bound, on purpose: `search_budget_exhausted` is raised by the
clock **or** by `MAX_CHAIN_RUNS`, `reason` already names the one that applied,
and a second claim free to contradict it is the exact failure this area keeps
producing. Asserted on the search's own verdict about itself, never on a wall
clock — `assert elapsed < N` is the instrument that produced the flake.

**S3's own tests, run in their own session because of the registry issue
below: 252 passed, 0 skipped** (`tests/unit/test_s3_receive.py`,
`test_s3_lockcheck.py`, `test_s3_ldpc_junction.py`).

**Action: PR #13 needs merging.** `e7b9649` is timestamped 01:29 and your
report 10:29 — **the fix existed nine hours before you started measuring**, in a
branch you had no reason to look in. That is on me, not on you: a fix that is
not merged is a fix nobody has. I have brought `origin/main` into the branch —
it was 17 commits behind, and the merge is clean.

---

#### The merge re-verified: 0 of 756 corpus rows changed

`origin/main` moved from `3f366c3` to `b6eeb30` while this branch sat: PR #12
(Dheeraj's zoo), PR #14 (Nehal's 6 Sep) and PR #16 (Naidhruv's integration),
the last of which **replaced `registry/protocols.py`
wholesale** — 155 lines, the strawman finally becoming the real registry.
Elsewhere in those 17 commits `zoo/bits_only.py` gained 113 lines and its
`CCSDS_SCRAMBLER` constant changed. Either could have moved an S3 number, so
the corpus study was re-run on the merged tree rather than quoted from the CSV.

| arm | before merge | after merge |
|---|---|---|
| `truth-params` | 231/252 decode, 252/252 mod correct, 0 confidently wrong | identical |
| `s2-top` | 202/252, 252/252, 0 | identical |
| `search` | 231/252, 240/252, 0 | identical |

**756 rows, zero changed outcomes.** Worst case 6.99 s against 6.97 s before,
inside the ~20% run-to-run spread this machine has. `pipeline/s3_receive/` and
`pipeline/s2_estimate.py` are byte-identical across those 17 commits, which is
why — but that was checked after measuring, not instead of it.

---

#### 7 Sep column: block B was already done, block D is 42/42, block C is a design and block E is OPEN

**Block B — 4-FSK plug-in — was already satisfied before the day started.**
Registered, `family = "fsk"`, decoding `4fsk_20dB_2035` end to end from blind
estimates. **Third day running that a row was written against a picture that
had already moved.** The half hour spent checking has now paid four times.

**Block D — ten 4-FSK files through the same chain — is 42 of 42.** Every
4-FSK file in the corpus, at every SNR including 4 dB: `ok`, chose 4-FSK, zero
confidently wrong, worst case 3.4 s. Ten of them are now pinned as tests
(`test_ten_4fsk_files_decode_through_the_same_blind_chain`), and the ten
deliberately include 4 dB and 8 dB — the files where S2's envelope predicate
hands S3 a symbol rate wrong by up to 81% and the answer comes through
`lockcheck.strongest_line`, the rate rescue. Those are the half that can
regress; testing only the clean SNRs would have left the rescue unpinned.

**Blocks C and E are CLOSED.** `pipeline/s5_decode/ldpc_code.py`, registered
as `CODES["ldpc"]`; design, measurements and acceptance numbers in
`reports/s3_ldpc_design.md`. The Command Center's definition of done for this
row is "**both registered** and passing through the same chain", and both now
are — `MODULATIONS["4fsk"]` and `CODES["ldpc"]`, each reached by name.

**NEHAL — there is a file of mine in your directory, and here is exactly what
it does and does not touch.** A `CodePlugin` belongs beside `conv_code.py` and
`rs_code.py`, and the LDPC row is on my day-clock column, so I wrote it and put
it where it belongs rather than leaving a decoder inside the receiver stage. It
spent its first afternoon in `pipeline/s3_receive/` precisely because the rule
is that your folder is a request and not an edit; it moved once that was
agreed. What it costs you:

* **it touches no existing file.** `pipeline/s5_decode/__init__.py` is empty
  and stays empty — code plug-ins register on explicit import, exactly as
  `conv_code.py` and `rs_code.py` do. `git show --stat` on the move shows one
  added file and nothing else in your directory.
* **it imports nothing from `pipeline.s3_receive`** — numpy and the registry,
  that is all. No coupling to my stage came with it.
* **every test reaches it by name through `CODES["ldpc"]`**, never by import,
  so rewriting, renaming or throwing it away costs one line.

Rewrite it or replace it freely; nothing outside its own tests depends on its
internals.

**Block E's four criteria, measured rather than asserted.** Chain: information
bits → IRA encoder → `zoo.rf.through_channel` at 2 dB with a carrier offset and
a fractional timing error → `MODULATIONS["qpsk"].receive` →
`CODES["ldpc"].decode`.

| criterion | result |
|---|---|
| decodes where the raw stream does not | S3 `ok`, raw BER **0.0091**, source bits wrong after decoding **0**, 5/5 blocks to a zero syndrome |
| alignment found inside the promised window | `llr_start_bit_tolerance + 1` offsets — at most five — hits the boundary every run |
| the wrong sign fails | negate every LLR: **0 of 5** blocks converge, output at 47% BER |
| `blind_recover` returns `None` | on zeros, on noise, on a ramp; wired into nothing |

The SNR is picked so the raw stream is *not* already correct — at 5 dB and
above it is exact, and a decode that succeeds there shows the plumbing runs and
nothing else. **The edge, because a decoder nobody has found the edge of is a
decoder nobody has measured:** it still clears a **6.0%** raw rate at −1 dB
where S3 has fallen to `low_confidence`, and at −2 dB S3 returns `failed` with
no LLRs. On this code the binding limit is the receiver, not the decoder. Over
plain AWGN with no receiver in the way it takes 6.5% to zero.

**That last number cuts against my own design rule and I would rather say so.**
§3 below says an LDPC decoder should gate on `status == "ok"`, and here a
`low_confidence` stream at 6% raw error decoded perfectly. The rule is
justified by the 82×-over-confident case, not by every refused stream — it is
conservative, it is the right default, and it is not free.

**Normalised min-sum is the default, not sum-product**, because min-sum's
check update is positively homogeneous and so immune to the *scale* half of a
calibration error. It is **not** immune to a shape error, and saying otherwise
would be the overclaim; what makes it safe is that the measured shape error
inside the `ok` population is small (1.06–1.62 across bins). Both algorithms
are implemented and both are pinned. `MIN_SUM_NORMALISATION = 0.75` is an
inherited literature default and is labelled as one — there is no corpus of
LDPC-coded captures here to tune it against, and a constant chosen on one arm
is the mistake this stage has been punished for twice.

What the day produced instead is the part that is mine and that the plug-in
cannot be written without: **the two things S3 has to supply an LDPC decoder,
both measured, one of them missing until this afternoon.**

**1. Where the stream starts — NEW, and it was a real gap.** Nothing had
needed it: Viterbi, Reed-Solomon and S4 are all indifferent to the start
offset. A block code decoded against a supplied H is not — a codeword has a
first bit. `values` did not support the answer: adding up everything a consumer
could see left it short by a **constant 507 symbols** - 507 bits on BPSK and
2028 on 16-QAM, the shortfall scaling with bits per symbol. The missing 507 is
three quantities the stage knows and a
consumer cannot see — Gardner's 2-symbol interpolator head start, the
500-symbol settling trim, the equaliser's centre tap at 5 of 11.

S3 now reports `llr_start_bit` and `llr_start_bit_tolerance` on both branches.
Measured against the harness's `align` over **all 36 (modulation, SNR) cells:
36 of 36 inside tolerance**, error never negative and never more than one
symbol, with `carrier_settled_at` ranging 0 to 3328. The residue is the timing
loop's fractional interpolation position, so one symbol is a floor and not
slack — calling it exact would have been the more useful claim and the false
one. A decoder now searches **at most 5 forward offsets instead of 40 000.**

**2. Whether the magnitudes can be trusted — measured, and it splits on
`status`.** `reports/s3_llr_calibration.md`. Viterbi maximises a *sum* of LLRs
and is invariant to scaling them; sum-product belief propagation combines them
through `tanh` and is not. So BP is the first consumer in this project whose
answer depends on the magnitudes being right, and `estimated_ber`'s existing
factor-of-two contract is an *aggregate* — a demapper can pass it while being
over-confident on strong bits and under-confident on weak ones, which is a
correct mean and a useless reliability curve.

| population | worst per-bin ratio, empirical / promised |
|---|---|
| files S3 returns `ok` on | **1.62x** — calibrated |
| files S3 refuses (`low_confidence`) | **81.7x** (16-QAM 4 dB), 65.6x (8-PSK 4 dB) |

On a refused file the demapper emits magnitudes of 4 to 8 — promising ~0.4%
error — over bits wrong 29% and 39% of the time. **So the design rule is that
an LDPC decoder gates on `status == "ok"` and never decodes a refused stream**,
and the recommended algorithm is normalised min-sum rather than sum-product,
because min-sum is invariant to exactly the scaling this had to go and measure.

**Where that study has no power, said plainly:** only three of six schemes
produced a scorable bin in the `ok` population. BPSK, QPSK and 8-PSK decode
with too few errors at every SNR here to measure a reliability curve at all —
19 818 of 19 955 BPSK bits at 4 dB sit in the `|LLR| >= 16` bin with zero
errors, which is consistent with the promise and with a promise ten times
smaller. Listed as unmeasured, not as passing.

**A mistake this made, caught by its own known-answer check.** The calibration
study carries a column pair that must reproduce `corpus.measured_ber` and
`softmap.estimated_ber` from the repo's own functions. It fired on 8 of 30
rows — and the fault was mine and in the check: it compared a windowed mean
against a whole-array one, two different populations. Fixed, now 30 of 30
agree. A known-answer check that fires on its own mismatched populations is
worse than none, because it teaches you to ignore it. **Second thing that went
wrong in the same study**: the summary table first ranked each modulation by
its *median* bin ratio and printed "8psk … calibrated" over a file whose worst
bin was 66x out, because it had pooled a result S3 stands behind with one S3
refused. A decoder meets every bin, not the middle one. Ranked on the worst bin
now, and split by `status`.

---

#### For other people

**Nehal:** PR #13 (above). Separately, `reports/s3_ldpc_design.md` §6 is a
request for one new file, `pipeline/s5_decode/ldpc_code.py` — it touches
nothing existing, because `__init__.py` in that package is empty and plug-ins
self-register on explicit import, so the diff is a single added file. Spec,
measurements and acceptance criteria are all in that document. Happy to write
it if you would rather it came from this side; it is your directory, so it is
your call.

**Naidhruv:** `contracts/`, `service/`, `web/` and `eval/` are on `main` now
(3, 9, 26 and 4 files) — that closes the thing I was going to raise as the
tripwire this morning. **`git tag -l` is still empty**, so `v0.4` was never
cut and today's `v0.5` gate reads "v0.4's E2E suite still passes unchanged"
against a tag that does not exist. The E2E suite itself does exist
(`3bd8648`). Worth cutting the tag before the gate is judged.

**Two things on `main` make the suite red, and I checked both on a clean
`origin/main` worktree before saying so.** Full suite here:
**31 failed, 780 passed, 5 skipped, 2 xfailed, 6 errors in 14m42s.** Nehal's
10:29 run reported 678 passed and one failure because **PR #16 merged at
11:36, after it** — his numbers predate the integration rather than
contradicting these.

**1. `starlette` is an unpinned transitive dependency and has drifted to
1.6.0**, which the pinned `fastapi==0.141.1` cannot work with:
`TypeError: cannot unpack non-iterable Route object` 27 times, plus
`AttributeError: 'Middleware' object has no attribute 'options'`, across
`tests/service/` and `tests/e2e/`. `requirements.txt` pins fastapi and not the
library fastapi is built on, so `pip install -r requirements.txt` resolves a
different stack depending on the day it runs. **The image builds from that
file, so this is a freeze-day problem rather than a today problem.** Pinning
the starlette that `fastapi==0.141.1` was exercised against should be the whole
fix. (Also: `httpx` is absent, which FastAPI's `TestClient` wants — but it is
NOT the cause here. I guessed it was, and the string does not appear once in
the failure log.)

**2. `registry.clear()` leaves the registry empty, and it takes the S3-S4-S5
junction contract with it.** `TestRegistryContract.tearDown` calls
`registry.clear()`, which empties the global `MODULATIONS` dict; Python's
import cache means nothing re-registers afterwards. Measured on `origin/main`
at `b6eeb30`, not on my branch:

| command | result on clean main |
|---|---|
| `pytest tests/contract` | 58 passed, **4 errors** — `KeyError: 'qpsk'` in `test_s3_s4_s5_chain.py` |
| `pytest tests/contract tests/unit/test_s3_receive.py` | **34 failed, 4 errors** |
| `pytest tests` (everything) | those same unit tests PASS |

**The full suite hides it**, because `tests/service` runs in between and
`service/orchestrator.py` re-registers the plug-ins as a side effect of
`750a05f`. So the greenness of a unit test currently depends on whether an
unrelated suite happened to repopulate global state first, and the four
junction contract tests — the ones that prove S3's LLRs reach S4 and decode —
are erroring in **every** ordering while the summary line says "58 passed".
Fix is yours to choose: `clear()` could snapshot and restore, or the fixture
could re-register rather than leave the dicts empty. I have not touched
`registry/` or `tests/contract/`.

**Two smaller ones, same run:** a Windows `PermissionError [WinError 32]`
deleting a still-open tmp wav in two `tests/e2e` cases, and
`tests/service/test_orchestrator.py::test_s2_fallback_detection` asserting
`est.symbol_rate` where `S2Result` has `symbol_rate_hz` (its `sys.modules`
patch is not taking, so it gets the real object).

**S3's numbers for the CORE LOCK gate are unchanged and re-verified:** at
>= 10 dB every modulation and every SNR is 7/7 lock and 7/7 decode — 168/168
decodes, 168/168 modulation correct, 0 confidently wrong. **Worst case
1.01–1.23 s**, quoted as a range because that is what two runs of the same 168
files on the same idle machine actually produced (1.23 s this morning, 1.01 s
after the merge, on `bpsk_13dB_2003`); a single figure here would be a
precision the instrument does not have. The 7 s worst case is the whole corpus
and every one of those files is at 4 dB, outside the gate. Do not budget S3
from it.

### 7 Sep — the 6 Sep column, closed against a finding of Nehal's

**Branch `anvith/s3-core-lock`**, off `main` at `3f366c3`. Report:
`reports/s3_search_cost.md`, regenerated by
`reports/s3_search_cost_study.py`.

**The three fixes are not the three cases the 6 Sep plan named, and the reason
is worth reading before the numbers.** That plan picked 16-QAM at 8 dB, 8-PSK
at 4 dB and 16-QAM at 4 dB off the 5 Sep harness. Two of those three my own
5 Sep write-up already records as *not defects* — the operating envelope, where
`truth-params` does not decode either and every check refuses correctly. Nehal
then handed over something that is a defect, is mine, and is a live risk to a
timed gate. I worked that instead. The named cases are re-measured below and
did not move; I did not try to move them.

**Nehal's finding, and the part that makes it more than a flaky test.**
`test_s3_runs_on_blind_estimates_with_no_labels_in_the_path` passed alone and
failed inside the full suite. Nehal reproduced the mechanism before handing it
over: at the 20 s budget it returned `ok`/QPSK in 21.5 s, already over budget on
an idle machine, and at 8 s or less it returned `low_confidence`/8-PSK.

That second half is the finding. **`receive_best` stops at a deadline and
returns the best of what it had actually run, so under load it does not get
slower — it answers differently.** A decode count taken on a quiet machine
cannot see that, and the machine at a timed gate is not quiet.

**The cause was not the budget.** On that signal Dheeraj's classifier reads a
QPSK capture as 8-PSK at probability 0.999, and the search then spent its whole
clock inside 8-PSK. Three things were wrong, in the order they cost time:

1. **The rate axis of `Candidate.key()` was never quantised.** The offset axis
   de-duplicates on a quarter of what the alignment check can notice and argues
   for it in its docstring; the rate axis was `round(rate, 3)` — a fixed 1 mHz
   grid, an *absolute* tolerance on a quantity whose error is relative. The
   rate rescue reads a rate off the line search while S2 reports an interpolated
   one, so the same rate arrives twice by two routes: `50000.000000` against
   `50000.002618` Hz, **5.2e-08 apart, 1/300th of the FFT bin either was read
   out of** — and each bought a full pass through the receiver at every carrier
   offset under it. Half the surviving candidate list was duplicates.
2. **One confident classifier call bought the whole budget.** The ranking is a
   prior over *modulations*; the queue it sorted is a list of (modulation, rate,
   offset) triples, so every offset under the top modulation ran before any
   other modulation was reached. That is how a ranking problem becomes a clock
   problem. Round one is now one candidate per modulation. **The first candidate
   run is identical either way**, so the `stop_on_clean_lock` argument is
   untouched for the common case; only the order after the first failure moves.
3. **A search the clock cut short did not say so.** It said it in
   `search_budget_exhausted`, a key nothing was obliged to read, while `status`
   and `reason` looked exactly like a finished search that had weighed the field
   and come back unsure. Those are different claims. `reason` now carries how
   many survivors actually ran — **and which bound stopped it**, because
   `search_budget_exhausted` is raised by the clock *or* by `MAX_CHAIN_RUNS`.
   My first draft blamed the budget for both, which invents the exact false
   claim the note exists to prevent; **11 of the 252 files run to the run
   ceiling**, several flagged exhausted at ~2 s where 20 s was never the
   constraint. Caught by checking the note against a case whose answer was
   already known, which is the 5 Sep countermeasure that keeps working.

| on Nehal's file | before | after |
|---|---|---|
| candidates built | 72 | 54 |
| survivors after the screen | 36 | **18** |
| chain runs to reach QPSK | 8 | **3** |
| wall seconds (this machine) | 12.1 | **3.4** |
| smallest budget still answering `ok`/QPSK | 12 s | **3 s** |

**The whole corpus, same harness before and after** — `3f366c3` against this
branch, 252 files. The before column is committed as
`reports/s3_search_cost_before.csv`, not remembered:

| arm | decodes | mod correct | confidently wrong | median s | worst s |
|---|---|---|---|---|---|
| `truth-params` | 231/252 | 252/252 | 0 | 0.34 → 0.33 | 1.00 → 1.03 |
| `s2-top` | 202/252 | 252/252 | 0 | 0.30 → 0.30 | 0.87 → 1.03 |
| **`search`** | 230 → **231**/252 | 239 → **240**/252 | **0 → 0** | 0.39 → 0.38 | **11.12 → 6.97** |

The two arms that do not go through `receive_best` are unchanged on every
outcome column, which is the sanity check on the ones that did move.

**Read the worst-case second as a range.** Two independent runs over the same
252 files on the same idle machine put the worst file at **6.97 s** and at
**8.46 s**, and disagreed about which file it was (`2fsk_4dB_8024` against
`2fsk_4dB_4024`). So the honest statement is **7–8.5 s against a 20 s budget, a
margin of about 2.4–2.9x**, up from 1.8x. Quoting one worst-case number to three
significant figures is precisely the habit this finding is a warning about.

**Exactly two files changed, and I am reporting both.** `4fsk_8dB_7031` was
chosen as BPSK at `low_confidence` and did not decode; it is now chosen as
4-FSK, `ok`, and decodes — the interleaving reached 4-FSK before BPSK's offsets
were exhausted. `8psk_4dB_3012` moved from 16-QAM to 2-FSK, both wrong, both
`low_confidence`, neither decoding either way: that is an 8-PSK file at 4 dB,
which is the envelope, and it is noise moving between two answers that are
correctly refused.

**Confidently wrong stayed 0, and the reordering is safe by construction, not
just by observation.** Reordering can change which modulation wins, and the
5 Sep lesson is that this class of defect is invisible to any arm that only ever
runs the correct plug-in. So `s3_lock_threshold_study.py` — the cross-hypothesis
sweep, which runs every corpus file through every *wrong* plug-in — was re-run.

Two things came back. Its 1008 rows are **bit-for-bit identical** before and
after — `git status` does not even list `s3_lock_threshold.csv` as modified
after a full re-run, which is a harder statement than any comparison I could
write myself. That is the regression check: these fixes touch the search's order
and de-duplication, never a demodulator, and the sweep bypasses the search
entirely, so identical output is what "I changed nothing underneath" looks like.
And the
standing number it reports is the actual argument: **of 840 wrong-hypothesis
runs, zero return `ok`.** `stop_on_clean_lock` fires only on `ok`, so on this
corpus there is no wrong-modulation trap for a reordering to fall into, whatever
order it uses.

**The limit on that claim:** the sweep covers the four linear PSK/QAM plug-ins
only, so it says nothing about the FSK branch — and `4fsk_8dB_7031`, one of the
two files that moved, is exactly there. The FSK branch is covered instead by the
`search` arm above, which runs the real search order over all 252 files and
reports 0 confidently wrong and 240/252 modulation-correct.

**`SEARCH_BUDGET_S` did not move**, and the temptation to move it is the point.
Widening it would have bought the failing test a pass and left the mechanism
in place. What did change is its docstring, which claimed "twenty runs at the
corpus's worst 1.0 s" — true of the corpus's 80 000-sample files, and not of
the 240 000-sample test signal, where a run costs 1.5–1.6 s. **The budget is a
fixed clock over an amount of work that scales with capture length**, so its
real unit is "runs on *this* input". Worth knowing for any judge file longer
than ours.

**`RATE_DEDUP_REL = 1.5e-5`**, one bin of the 2^18-point line search at 4
samples/symbol. Measured either side, one file per modulation at 20 dB: every
file returns an identical status and raw BER out to **5e-05** of relative rate
error, and the tightest two — 2-FSK and BPSK — first diverge at **1e-04**, where
they turn `failed` rather than wrong. The grid sits 3.3x inside the largest
error that changes nothing and 6.7x inside the smallest that changes anything.

**The three cases the plan named, now actually worked — and the verdict I had
been repeating since 5 Sep was wrong.** Report: `reports/s3_bound.md`,
regenerated by `reports/s3_bound_study.py`. **No change ships**, and the reason
is worth more than the three fixes would have been.

Those cases were carried as "the operating envelope, not a defect", on one
observation: `truth-params` does not decode them either, so the loss is in the
demodulator rather than in lock detection. That is true. It is a *different*
claim from "the loss is irreducible", and nobody had put a number on the second
one. So I computed the bit error rate an ideal coherent receiver gets in AWGN
and compared. The Es/N0 convention is **calibrated, not assumed** — `zoo.rf`
sets noise power over the whole sampled band at 4 samples/symbol while the
receiver matched-filters to the symbol rate, so there is 6.02 dB of processing
gain the `snr_db` label does not carry; both conventions are computed and only
one is consistent with the cells that work.

**In the 7 cells that carry measurable errors and are not one of the two
below, S3 sits 1.0–1.5x above the bound.** In 27 further cells it made zero bit
errors, which ~40 000 bits per file cannot separate from the bound either way —
those are consistent with it, not evidence about it, and are not counted. For
a blind receiver — blind rate, blind offset, blind modulation, a blind
equaliser and two blind loops ahead of the demapper — that is about half a dB
of implementation loss. Those cells have nothing left in them.

**Exactly two cells break the pattern, and they are the two I had called the
envelope:**

| case | measured | ideal | gap |
|---|---|---|---|
| 16-QAM @ 8 dB | 0.0124 | 0.00925 | 1.3x |
| **16-QAM @ 4 dB** | 0.4231 | 0.0586 | **7.2x** |
| **8-PSK @ 4 dB** | 0.3581 | 0.0288 | **12.5x** |

**16-QAM at 8 dB is the opposite of what the plan said.** The plan called it
"the closest to moving and the only one where a demodulator change plausibly
crosses the line". In fact **the line is below the floor**: an ideal receiver
gets 0.00925 and the study's decode line is 0.01000, so a perfect receiver
clears it by 8% and nothing else. S3 is 1.3x above the floor, so crossing that
line needs a receiver within ~0.3 dB of optimal — not a constant. Every
parameter I swept (MMA step size, tap count, equaliser warm-up) moved the median
by a few percent, and three of them cost a single file a **32x** degradation
that the decode count could not see — `16qam_8dB_3019`, 0.0130 → 0.416 at
`mu=5e-4`. That is 5 Sep's `ACQ_SYMBOLS` lesson repeating exactly.

**The 4 dB gap is real and it is the carrier loop.** Isolating the blind stages:

| arm | 16-QAM 4 dB | 8-PSK 4 dB | 16-QAM 8 dB | 20 dB |
|---|---|---|---|---|
| full chain | 0.4231 | 0.3581 | 0.0124, 0/7 | 0.0000 |
| equaliser bypassed | 0.4228 | 0.2982 | 0.0114, 1/7 | 0.0000 |
| **carrier loop 0.02 → 0.002** | **0.0691** | **0.0308** | 0.0104, 2/7 | 0.0000 |
| both | 0.0676 | 0.0305 | **0.0093, 6/7** | 0.0000 |

Narrowing the loop takes 8-PSK at 4 dB from 12.5x the bound to ~1.1x, and takes
16-QAM at 8 dB across the 1% line on **six of seven files**. It is the block-A
result the plan asked for.

**And it must not ship. Every corpus file has `cfo_norm` 0**, so the corpus can
show what a narrower loop gains and is *structurally incapable* of showing what
it costs. The loop's real job is a residual — the search de-rotates by each
candidate first and `carrier_alignment` refuses anything past 0.03 x Rs — so I
measured across that range synthetically. At 20 dB, where the receiver is
otherwise exact: **the incumbent 0.02 holds lock at every residual on every
scheme, and every narrower value loses lock somewhere inside the permitted
range.** QPSK reads cleanest — 0.02 and 0.01 exact everywhere, 0.005 fails at
0.03, 0.002 fails at **0.005**.

So narrowing would have bought 14 files at 4 dB that **still would not decode**
(the bound there is 0.059 and 0.029 against Nehal's 3% ceiling) and paid for
them by breaking every file with a real carrier offset. The incumbent wins on
evidence, not on a tie-break.

**Dheeraj — the corpus has a blind spot and it is load-bearing.** All 252 files
carry `cfo_norm` 0. I found a change that looks like a 12x win on every corpus
file and is a catastrophe on any file with an offset; only a synthetic test
caught it. **A few files with non-zero `cfo_norm` would close the hole**, and
until they exist, no loop constant can be justified from the corpus alone.

**What is still on the table** is a second gear-shift in `costas_loop`. It
already runs `ACQ_BW_RATIO` x wider for `ACQ_SYMBOLS` and then settles, so
acquisition is already separated from tracking; narrowing again *after* lock
would take the residual out during acquisition and still collect the
steady-state gain above. That is the textbook answer and it is worth real time —
but not a guess, because this loop has now twice punished a constant chosen on
one arm.

The stale-number note stands as well: nothing in the three shipped fixes touches
a demodulator, so those columns were re-measured rather than repeated.

| case | files | `truth-params` median raw BER | `status` | note |
|---|---|---|---|---|
| 16-QAM at 8 dB | 7 | **0.0124** (range 0.0116–0.0130) | `ok` on 7/7 | inside Nehal's 3% ceiling; misses only the study's own 1% line |
| 8-PSK at 4 dB | 7 | **0.358** (was quoted as 0.23) | refused on 7/7 | envelope |
| 16-QAM at 4 dB | 7 | **0.423** (was quoted as 0.31) | refused on 7/7 | envelope |

The two 4 dB rows are worse than my 5 Sep note claimed, not better, and every
check still refuses all 14 files — which is the right answer and the reason
neither is a defect. 16-QAM at 8 dB returns `ok` on all seven and is honest
about it: the receiver's own estimate tracks the real error.

**Dheeraj — your 6 Sep FSK CFO fix is worth +24 files and the harness now says
so.** The `s2-top` arm went **178 → 202 of 252** between the 5 Sep build and
`3f366c3`, measured on the same 252 files. It does not show up in the `search`
arm (230 both times) because the search was already absorbing that error by
reading the rest of your ranked list — so the fix bought margin rather than
decodes, which is the better of the two.

**Naidhruv — the 6 Sep CORE LOCK gate has not closed, and nothing is tagged.**
`git tag -l` is empty, so `v0.4` was never cut. `contracts/`, `service/`,
`web/` and `eval/` are still absent from `main`, though six commits carrying
them exist on `origin/naidhruv/integration` — so it is unmerged, not unstarted.
The gate is an integration gate and cannot close on work that is not on `main`.
Per the day clock this is the tripwire condition.

**S3's half of that gate, stated in the gate's own terms** — the gate asks for
a corpus file at ≥10 dB decoded correctly, under 90 s, across 5+ modulations:

> **168 of 168 files at ≥10 dB decode, 168/168 modulation correct, 0
> confidently wrong, all 6 modulations, worst case 1.23 s.**

Take **1.3 s** as S3's line in the 90 s budget when you plan the rest. The
7–8.5 s figure above is the worst file in the *whole* corpus and every one of
those is at 4 dB, which is outside this gate's ≥10 dB scope — do not budget
from it.

### 5 Sep — the row's target was already met; the work was the 4-8 dB half

**Branch `anvith/s3-robustness`**, merged with `main` at `116dc6b`. Reports:
`reports/s3_lock_gate.md` (the harness), `s3_lock_threshold.md`,
`s3_rate_rescue.md`, `s3_loop_bw.md`.

**Read the first number with the corpus size attached.** Everything below is
on Dheeraj's **252-file** corpus — seven seeds per (modulation, SNR) cell.
The 4 Sep write-up in the section under this one is on 36 files, one seed per
cell, and several of its numbers were a single noise draw.

**Today's verify line passed before I touched anything.** The row asks for a
lock rate of 90%+ at ≥10 dB for PSK and FSK. Measured on 252 files at the
start of the day: **168/168 files at ≥10 dB decode, 168/168 lock, 0
confidently wrong, across all 6 modulations** — 100%, not 90%. 16-QAM is
reliable at 10 dB, not the 13 dB the row asks for. So the day's real work was
where the row said it wasn't: 4 and 8 dB, where 49 of 252 files were missing.

### Where the 49 misses actually were

| miss | files | owner | state |
|---|---|---|---|
| 2FSK/4FSK at 4 and 8 dB | 28 | **upstream (S2)** — receiver already perfect | worked around in S3 today |
| 16-QAM at 8 dB | 7 | nobody — see below | not a defect |
| 8-PSK and 16-QAM at 4 dB | 14 | operating envelope | out of reach |
| 8-PSK at 8 dB reported `low_confidence` while decoding | 7 | **mine** | fixed today |

**1. The 28 FSK files were never a receiver problem, and that is the finding
worth carrying to standup.** Handed the true symbol rate, S3 demodulates every
one of them: **28/28 decode at a median raw BER of 0.004**, at both 4 and 8 dB.
Handed S2's parameters it produced *no LLRs at all* — the search returned
`failed` with `chain_runs = 0` on 21 of them.

The cause is upstream and Dheeraj has already documented it in
`reports/s2_envelope.md` as a deliberate, quantified, low-SNR-only gap: the
envelope predicate reads low-SNR FSK captures as non-constant-envelope, so they
go to the *linear* symbol-rate estimator. Measured this morning across 252
files: **S2's symbol rate is exact on 224 of 252**, and the 28 exceptions are
exactly the 2FSK/4FSK files at 4 and 8 dB, wrong by up to **81%**.
`fsk_order_hypotheses` is empty on exactly those 28 — **not on all files**,
which is what my 4 Sep report claimed and is now corrected.

**Dheeraj — what your write-up could not know is what the gap costs**, because
it is measured downstream: 28 files, 11% of the corpus, on a receiver that
handles all of them correctly the moment the rate is right. That is the largest
single item I can see on the board. It is still worth fixing at source, because
every stage below S2 inherits the wrong rate and only S3 now works around it.

**2. 16-QAM at 8 dB is not a defect and should not be treated as one.** Seven
files, raw BER **0.0117-0.0124**, against a 1% line this study draws. The
receiver's own estimate is 0.0100-0.0109 — right to within 13% — and it
returns `ok`, correctly. 1.2% is well inside the **3% ceiling Nehal measured**
for statistical code recovery, so these decode in the pipeline sense and count
as misses only in mine. Moving the decode line to claim them would be changing
the definition of the gate in order to pass it.

**3. 8-PSK and 16-QAM at 4 dB are the operating envelope.** `truth-params`
does not decode them either — median raw BER 0.23 and 0.31 with the true rate
and zero offset. Every check refuses them, which is the right answer.

### What that came to, measured the same way at the end of the day

| arm | decodes | mod correct | confidently wrong | median s |
|---|---|---|---|---|
| `truth-params` — the true rate, no offset | 231/252 | 252/252 | 0 | 0.37 |
| `s2-top` — S2's top hypothesis only | 178/252 | 252/252 | 0 | 0.31 |
| **`search` — S2's ranked hypotheses** | **230/252** | 239/252 | **0** | 0.46 |

**203/252 -> 230/252**, and the blind search is now within **one file** of what
the receiver can do when handed perfect parameters. 2-FSK is 42/42 and 4-FSK
41/42, both at every SNR including 4 dB. Modulation choice went 217 -> 239.

**Nothing at >=10 dB moved: still 168/168 decode, 168/168 lock, 0 confidently
wrong.** That was the thing to protect and it is intact.

**Confidently wrong is 0 on all 252 files on all three arms**, which is the
number that matters most and the one every change today was constrained by.

The 22 remaining misses, and every one of them is *refused* rather than
claimed:

| files | what | status |
|---|---|---|
| 7 | 16-QAM at 8 dB, raw BER 0.011-0.014 | `ok`, honestly — inside Nehal's 3% ceiling |
| 7 | 16-QAM at 4 dB, raw BER ~0.48 | `low_confidence` |
| 7 | 8-PSK at 4 dB, raw BER ~0.48 | `low_confidence` |
| 1 | `4fsk_8dB_7031`, chose QPSK at 0.48 | `low_confidence` |

Cost: worst case 11.4 s against a 20 s budget, on `2fsk_4dB_8024` — a file that
now decodes and used to return nothing, taking 10 chain runs to get there.
Median 0.46 s. These are wall-clock and were taken with another study running
on the same machine, so read them as an upper bound; the conclusion that the
search sits well inside its budget holds either way.

**One behaviour change to declare:** raising 16-QAM's threshold to 0.59 moves
`16qam_8dB_2019` from `ok` to `low_confidence`. It has a raw BER of 0.011 and
does not cross the decode line either way, so this is the threshold being more
honest rather than less useful — but it is a file that used to say `ok` and now
does not, and that belongs in writing rather than in a diff.

### Block A — the lock thresholds, per scheme instead of per family

`_LOCK_THRESHOLD` was keyed by family: `{"psk": 0.60, "qam": 0.55}`. One key
too coarse. The metric is `|E[u^S]|` with S the constellation's rotational
symmetry, so raising a noisy symbol to the S-th power raises its phase error
with it, and at a fixed symbol-error rate the metric falls as S rises.
**Measured at 8 dB, correct hypothesis, 252 files: bpsk 0.950, qpsk 0.837,
8psk 0.488, 16qam 0.680.** BPSK and 8-PSK cannot share a number, and 0.60 was
refusing every working 8-PSK file at 8 dB.

Set from the geometric midpoint of the gap between the two populations this
threshold is responsible for — 1008 runs, every corpus file through every
linear plug-in (`reports/s3_lock_threshold.md`):

| scheme | before | after | worst that decodes | best genuine failure | gap |
|---|---|---|---|---|---|
| bpsk | 0.60 | **0.23** | 0.857 | 0.060 | 14.36x |
| qpsk | 0.60 | **0.46** | 0.636 | 0.328 | 1.94x |
| 8psk | 0.60 | **0.30** | 0.488 | 0.184 | 2.65x |
| 16qam | 0.55 | **0.59** | 0.784 | 0.437 | 1.79x |

**7 false negatives recovered, 0 false positives added.** Two things worth
stating rather than burying:

- **16-QAM goes up.** The row says lower the thresholds; three of four come
  down hard and the measurement says this one was slightly loose. Reported as
  measured.
- **The one judgement in that table** is that runs between the 1% decode line
  and a 2% genuine failure are in neither population. On this corpus that band
  holds exactly the seven 16-QAM files above. Include them and 16-QAM does not
  separate at all — its worst decoding file reads 0.784 and its best
  non-decoding one 0.788.

QPSK's old margin was thinner than it looked: at 4 dB it reads 0.636 against a
0.60 threshold, a 6% margin. At 0.46 it is 1.39x either way.

### Block B — loop bandwidths, and the thing the sweep actually found

112 files x 5 bandwidths x 2 arms per knob, driving the real chain through
`LinearDemod`'s constructor rather than a copy of the loops. The second arm
always carries the impairment the loop exists to remove, because a sweep that
exercises only the clean side of a trade reports a straight line.

**No tracking bandwidth moved, in the end.** BPSK and QPSK read 28/28 in all
ten cells of both arms — no discriminating power, so no change. 16-QAM's timing
grid reads 12/14/13/14/13 with median BER 0.020/0.009/0.015/0.009/0.019:
non-monotone across a 16x range, which is a response with no reliable signal in
it rather than an optimum at 0.002.

**8-PSK's carrier bandwidth went 0.02 -> 0.04, shipped, and was reverted the
same evening. That reversal is the most important thing in this section.** The
sweep supported it: clean arm identical at 21/28, impaired arm 20/28 -> 21/28,
monotone across the grid. What the sweep cannot see is that **it only ever runs
the correct plug-in.** Run a QPSK capture through the 8-PSK plug-in — the
subset trap `alphabet_used` exists for — and the wider loop smears the
four-point cloud across all eight decision regions:

| 8-PSK carrier bw | `alphabet_used` | verdict | actual BER | self-estimate |
|---|---|---|---|---|
| 0.02 | 0.691 → **fail** | `low_confidence` | 0.484 | 0.0029 |
| 0.04 | 0.947 → **pass** | **`ok`** | 0.484 | 0.0035 |

On `qpsk_8dB_2007` the stage returned **`status: ok` with a self-estimated
output BER of 0.0035 over a stream 48.4% wrong** — the 4 Sep failure walking
back in through a different door, bought for one file on an injected-offset
arm. Reverted.

Two things I want on the record about it. It is **invisible to the lock-gate
harness**, because that study only ever runs the correct plug-in on each file
and the search picks QPSK for a QPSK capture — so `confidently wrong` stayed 0
across all 252 files while this was live. It was found only by re-running the
cross-hypothesis threshold study after changing the loop, which I did because
the thresholds had been measured against a loop I then modified. And it means
**a per-scheme sweep over correct hypotheses cannot see a check that only
wrong hypotheses exercise** — which is now written into the constant.

**What the sweep actually found was structural.** Handed a residual carrier
offset of 0.02 x Rs — one `CARRIER_OFFSET_LIMIT` explicitly permits, so the
pipeline really does hand it over — 16-QAM decoded **1 of 28** files at every
bandwidth that did not also cost clean files. That is an acquisition problem,
not a tracking one, and `costas_loop` had no acquisition phase: one bandwidth
end to end, while its sibling `gardner_sync` has gear-shifted since it was
written.

It now gear-shifts too, 4x for 100 symbols (`carrier.ACQ_SYMBOLS`).

| scheme | carrier bw | clean | impaired (before) |
|---|---|---|---|
| bpsk | 0.02 | 28/28 | 28/28 (28) |
| qpsk | 0.02 | 28/28 | 28/28 (28) |
| 8psk | 0.02 | 21/28 | 20/28 (18) |
| **16qam** | 0.02 | **14/28, unchanged** | **9/28 (1)** |

**How the 100 was arrived at is the part worth reading, because I got it wrong
first.** The constant shipped at 150, chosen from clean and offset decode
counts. Those counts are identical at 100 and 150 — and blind to
`16qam_8dB_5019`, which sits at raw BER 0.0119, above the 1% line either way,
so it is a non-decode before and after and contributes nothing to any count.
At 4x/150 that file loses carrier lock outright: metric 0.696 -> 0.023, raw
BER **0.0119 -> 0.4093**. Caught on the end-of-day verification pass by
diffing against a re-measured pre-change baseline, not by any test.

Re-chosen on a per-file regression check — a clean-arm file whose BER more
than doubles — over 8-PSK and 16-QAM, 4-13 dB, 56 files:

| ratio x symbols | clean decodes | offset decodes | regressions |
|---|---|---|---|
| 1.0 x 0 (single speed) | 35/56 | 22/56 | 0 |
| 4.0 x 50 | 35/56 | 28/56 | 0 |
| **4.0 x 100** | **35/56** | **31/56** | **0** |
| 4.0 x 150 (was shipped) | 35/56 | 30/56 | **1** — 34x |
| 8.0 x 50 | 34/56 | 32/56 | **4** — up to 8254x |

100 strictly dominates the 150 I first shipped: same clean count, one *more*
impaired-arm file, and no regression. The 8x row is why the column exists — a
wide acquisition on a decision-directed detector can slew the phase into a
wrong rotation and the narrow tracking loop then holds it there, so "wider
acquires better" stops being true well before a decode count notices.

**This is the same mistake I flagged elsewhere today and then made anyway:**
choosing on a binary count when the failure mode lives in a continuous
quantity. It is the reason 16-QAM's timing bandwidth was left alone, and I
should have applied it to my own new constant in the same hour.

**The corpus cannot see this problem at all.** Every file in it has a true
carrier offset of exactly zero, so the acquisition transient this fixes only
exists on a real capture or an injected one. It is the single thing done today
that no corpus number can verify, and a field capture would have found it the
expensive way.

**Stated rather than quietly taken:** 16-QAM at 0.04 reaches 13/28 impaired,
four better, and loses `16qam_10dB_4020` on the clean arm — raw BER 0.0029 ->
0.0299. That is a 10 dB file and >=10 dB is the region the day gate is written
on, so I did not trade a measured corpus file for an injected scenario. The
remaining exposure is 9/28 rather than 1/28, and choosing the last four is a
core-lock decision, not a quiet one.


### The rate rescue — `lockcheck.strongest_line`

The screen already computed the evidence and threw it away. `symbol_rate_line`
asks "how strong is the line at the rate I was given"; its new twin asks
"where is the line", off the **same statistic and the same averaged
spectrum**. When every candidate has been refused for absence, the search now
proposes that rate — exactly as it already proposed a corrected carrier offset
when a candidate was refused for misalignment. Same pattern, other axis.

Measured (`reports/s3_rate_rescue.md`), FFTs only, no chain:

- **252/252 corpus files: the proposed rate is the true one.** Worst relative
  error **0.0000%**; line score 19.7-196.9 against a present-limit of 8.0.
- **384 noise draws at three record lengths: the screen passes the proposal
  0 times.** 369 outright `fail`, 15 in the abstain band, 0 `pass`. Worst
  noise score 4.85 against the 8.0 needed to declare a line present.

It is deliberately not a symbol-rate estimator and must not become one: one
rate per family, only after S2's have all been refused, and the proposal
re-enters the same screen as any other candidate. Estimation is S2's stage.

### A correction to what I wrote on 4 Sep

I reported `2fsk_4dB_2024` as a presence-threshold near miss — line score 4.4
against a limit of 4.5 — and concluded that 4 dB needed **a better statistic,
not a looser number**. The statistic was fine. The 4.4 was scored at **48 479
Hz, the rate S2 offered**; at the true 50 000 Hz the same statistic on the same
file scores **45.2**, five times the limit. The threshold was never what stood
in the way. Had I taken that row at face value this morning I would have spent
the day tuning a number that was already right.

### New, and it belongs to everyone: the symbol rate is binary

**S3 tolerates a symbol-rate error of about 0.01% and fails at 0.05%.**
Measured on `qpsk_20dB_2011` and `16qam_20dB_2023`: 0.01% error decodes at BER
0.00000; 0.05% returns `failed`, and so does everything above it.

The mechanism is `signal_presence` looking for the line at the rate it was
given, on a 2^18-point spectrum whose bins are 0.76 Hz apart at fs = 200 kHz —
0.05% off is ~33 bins away and reads the noise floor. This is the right
behaviour: a clean refusal, never a confident lie. But it means a rate that is
3% wrong is not "slightly worse", it is nothing at all, and it is why the 28
FSK files produced no output rather than poor output.

I found this by mis-designing a study: the timing-loop sweep's impaired arm
used a 1% rate error and came back 0/28 in every cell of the grid. A sweep
where every cell reads zero is not a measurement, and chasing why gave the
number above.

### End-of-day verification, and the two defects it found

Ran the whole suite and re-ran every study against the code as it actually
ships. **549 passed, 4 skipped, 1 xfailed** (13 min); targeted plus contract
257 passed. Two defects in work I had already committed, both now fixed:

**1. `_CARRIER_LOOP_BW["8psk"] = 0.04` blinded the subset-trap check. Reverted.**
Detailed in Block B above. `status: ok` with a self-estimate of 0.0035 over a
stream 48.4% wrong. **It was invisible to the harness I had used all day** —
`reports/s3_lock_gate.md` runs only the correct plug-in per file, so
`confidently wrong` read 0 across all 252 files while this was live. It
surfaced only because I re-ran the *cross-hypothesis* threshold study, and I
only did that because the thresholds had been measured against a loop I then
modified. With 8-PSK back at 0.02 the populations separate again exactly as
first measured — admit ≥ 0.488, refuse ≤ 0.184, 2.65x — so every shipped
threshold is now validated against the loop that ships rather than one that
no longer exists.

**2. `ACQ_SYMBOLS = 150` cost one file 34x. Now 100.** I chose the acquisition
length on clean and impaired *decode counts*, which are identical at 100 and
150 and blind to `16qam_8dB_5019`: raw BER 0.0119, above the 1% line either
way, so a non-decode before and after that contributes to no count — and at
4x/150 it loses carrier lock outright, 0.696 → 0.023, BER 0.0119 → **0.4093**.
Re-chosen on a per-file regression check: 100 gives the same clean count, one
*more* impaired-arm file than 150, and zero regressions. Caught by diffing
against a re-measured pre-change baseline, not by any test.

**3. A number I could not reproduce.** The before-figure `search 203/252` came
from a CSV the after-run had overwritten — a memory, not a measurement. Now
re-measured from a worktree at `aed281b`; it reproduces 203 exactly, and
`reports/s3_lock_gate.md` carries the command so nobody has to take my word.

**4. `reports/s3_s4_junction.{csv,md}` re-measured** — Nehal's boundary, last
taken 3 Sep. **Every summary number is unchanged**, so the S3 output S4 sees
is the same shape it was; only per-rotation intermediates moved.

The thread joining 1 and 2 is worth stating once: **both were chosen on a
binary count when the failure lived in something continuous.** It is the same
error I identified and avoided on 16-QAM's timing bandwidth, then made twice
in the same hour on my own new constants.

### Open, mine

- Non-coherent FSK LLRs still carry a **measured** calibration constant of 2.0
  rather than a derived one (`softmap._NONCOHERENT_CALIBRATION`).
- `equaliser_converged` still records UNKNOWN and does not vote:
  `CMAResult.converged` asks whether modulus error improved, which is
  meaningless with nothing to equalise. Becomes a vote when the zoo grows a
  multipath channel.
- Soft-vs-hard coding gain still unmeasured.
- 8-PSK and 16-QAM at 4 dB are unreached by anything in S3.

### Needs

- **Nehal** — the rate rescue changes what S3 returns on low-SNR FSK: files
  that used to come back `failed` with no LLRs now return `ok` with a full
  soft stream. Worth re-running `zoo_gate_study.py`; the population it sees
  has grown.
- **Naidhruv** — `contracts/`, `service/`, `web/`, `eval/` are still zero
  entries on `main` and your STATUS section still reads "(not started here)".
  The **3 Sep integration gate has still not closed** — a file in through a
  browser and out as decoded bits through seven real stages. 4 Sep was its
  overflow. Raising it rather than absorbing it quietly, as the plan asks.

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
| `alphabet_used` | does the cloud use the whole constellation claimed? | the subset trap, below |
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

**The subset trap — found while checking my own work against Dheeraj's
classifier, and the nastiest of the lot.** QPSK's four points *are* four of
16-QAM's sixteen, and three of 8-PSK's eight. Run a QPSK capture through the
16-QAM plug-in and nothing about the reception is wrong: every symbol lands
exactly on a legal constellation point, so the decision-directed noise variance
comes out tiny and the LLRs come out enormous.

    qpsk signal, 16-QAM plug-in    status ok   confidence 0.984
                                   estimated_output_ber 1.8e-21
                                   ACTUAL BER 0.482

Every check listed above asks whether the receiver locked to the constellation
it was *told* to assume. None of them could ask whether that was the right
constellation — a four-point cloud is a perfectly good 16-QAM reception in
which twelve points happen never to be used. `alphabet_used` asks exactly that,
and a real 16-QAM stream uses all sixteen. Measured across four schemes × four
hypotheses × 4–25 dB: **correct hypothesis ≥ 0.992 evenness, wrong-but-`ok`
≤ 0.670.** It vetoes and never confirms — at 4 dB noise scatters symbols onto
every point and the check goes blind, which is precisely when the carrier and
output checks are doing the work.

**Nehal — this one matters to your pre-flight specifically.** On a
mis-classified file `estimated_output_ber` was not merely uninformative, it was
1.8e-21 with `valid: true`. It is now `false`.

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
  here and it is not a classifier. 31 of 36 currently correct; the five misses
  are all files where nothing locks at all.

**Dheeraj — I tested against your classifier branch before it merges, and
found two bugs on my side.** `modulation_hypotheses` is
`[(class_name, probability)]`, and my reader coerced every value with
`float()`, so the first ranking you handed over would have raised
`ValueError: could not convert string to float: 'qpsk'`. Second, a modulation
your classifier did not rank defaulted to a prior of 1.0 — *above* a
0.91-probability match — so the three schemes you never mentioned would have
been tried first. Both fixed and pinned against the exact shape
`S2Result` declares on `dhiraj/zoo-v0`. With the ranking wired in:

| what S2 says | result | chain runs |
|---|---|---|
| correct top guess | `ok` → qpsk | **1** |
| **corrupted** top guess (16qam at 0.80 on a QPSK file) | `ok` → qpsk | 3 |
| no ranking at all | `ok` → qpsk | 6 |

That middle row is the 4 Sep cross-check — *corrupt S2's top hypothesis and the
pipeline still decodes via the second* — holding from S3's side. It only holds
because of `alphabet_used`: before it, 16-QAM returned `ok` on that file and
the search stopped there.

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

**2 Sep gate: PASS.** Reed-Solomon (255,223) registered. Exact bit match on 20
streams per code at 0 % BER, both against *recovered* parameters - conv 20/20,
RS 20/20. Weak profiles (255,247) and (255,251) were REMOVED from the search
after they produced confidently wrong answers: a 4-parity code fits almost
anything within distance 2 of a codeword. A genuine RS(255,251) stream is
therefore outside the searched set and is declined rather than guessed at.

**3 Sep gate: PASS**, and the day found the bug it existed to find.
`blind_recover` assumed 0/1 and never hard-sliced, so real LLRs - which is what
S3 actually emits - had float values packed through `np.packbits`. A *perfect*
demodulation came back as "period=4, K=2, G=(0o1, 0o0)" at 0.95 confidence: a
confident wrong answer on the one input the whole pipeline exists to consume,
and it would have done that on every real file. Hardened at the entry
(`harden()`), two regression tests.

---

**4 Sep. The correction is mine, and it matters more than the fix.**

Last night's `reports/end_to_end.md` put the text arm at **0 of 18** - including
16 dB with a bit-perfect demodulation - and blamed `detect_signature` for taking
the smallest rank collapse. I re-measured that before fixing it and **the
diagnosis was wrong**. `detect_signature` returns the true period 96 on every
rotation of every file in that arm, and the transmitted stream recovers cleanly
at every start offset. The numbers were real; the mechanism I attached to them
was not. Three separate defects were lined up behind one symptom:

1. **A false positive won the rotation ranking.** On the *wrong* rotations the
   statistical fallback returned `ok` at 0.59 with "period=4, rate 1/2 K=2" - a
   memory-1 artefact of ASCII, not a code. The study ranks rotations by shortest
   span, so span 4 beat the true span 14 and the garbage rotation won. The
   correct rotations were sitting there returning `period=96, block(8,12),
   G=(0o171, 0o133)` the whole time.
2. **De-interleaving destroyed the LLRs.** Every function in `interleavers.py`
   began `np.asarray(bits, dtype=np.uint8)`. A permutation does not care what it
   is permuting, so that cast bought nothing and truncated every soft value.
   De-interleaving a real receiver's output returned **an array of zeros**, and
   Viterbi decoded zeros into zeros. This is the 3 Sep `harden` bug one stage
   further along, and it hid because the recovery path hard-slices by design -
   only the *decode* path needed the soft values, and every test before today
   de-interleaved zoo bits.
3. **Polarity - risk #9, arriving in the register's own words.** With the LLRs
   surviving, the chain decoded to the *complement* of the message. A coherent
   receiver cannot tell 0 deg from 180, both polarities recover identical
   parameters, and both decode without complaint. One file: rotation 2 printable
   1.000, rotation 0 printable 0.001, same parameters.

**Results, measured against `origin/main` at 093f431 so Anvith's roll-off fix is
in the path** (`reports/end_to_end.md`):

| | yesterday | today |
|---|---|---|
| interleaver + code recovered | 15/36 | **30/36** |
| text arm recovered | 0/18 | **15/18** |
| text arm printing the message | 0/18 | **15/18** at printable 1.000 |

Whole chain per file, median 24 s, max 50 s - inside the 90 s budget.

**Blind in, message out, through the real receiver - for the first time.**
Yesterday's file said the readable-text demo "has never run through the real
receiver". It has now: real modulator, real channel, blind S3, blind S4, Viterbi,
readable text.

**I first wrote that as "nothing about the file was supplied". That was an
overclaim and I am correcting it here.** The study calls
`MODULATIONS["qpsk"].receive(iq, {"fs": ..., "symbol_rate": ...})`, so the
modulation family and the symbol rate ARE supplied. Both are S2's job and S2
does not exist yet. What is genuinely blind: RRC roll-off, carrier phase and
CFO, symbol timing, the rotation ambiguity, the interleaver family, period and
depth x width, the block alignment, the code rate, the constraint length, both
generator polynomials, and the payload polarity.

**The honest sentence for the demo is "everything from the matched filter
onward is blind"** - not "nothing was supplied". When Dheeraj's S2 lands, this
study must stop taking `fs` and `symbol_rate` from the ChannelSpec and take
them from S2, and every number here must be re-measured.

**And nothing here is evidence about REAL signals.** `rf_channel.py` is a
channel we wrote: RRC, AWGN, one constant CFO, one fixed timing offset. No
multipath, no interference, no AGC transient, no phase noise, no fading. No
off-air capture has ever been through this pipeline. That is risk #8, and the
plan's answer is the 21 Sep - 20 Oct window (RTL-SDR, SatNOGS, gr-satellites as
an independent oracle). Anyone presenting this must not let "real receiver" be
heard as "real signal".

**Four paths could report `ok` on a structured source. All four are closed**, and
the guards now meet at one exit (`_finalise`) instead of living in whichever
branch happened to run. The recurring lesson, third instance: *deficiency cannot
DECIDE - only a functional test can.* The discriminator turned out to be
structural rather than a threshold - a real code has a **one**-dimensional null
space at its span, and the ASCII artefacts have 4, 7 and 19.

Also: a scrambled stream was walking around the K<=9 composite guard by coming
back through the *interleaver* path as `block(depth=1,width=32)`. Depth 1 is the
identity permutation - the direct reading wearing a hat, meeting a guard that
only existed in the branch it did not take. Guard moved to the exit; depth 1 is
no longer offered.

**4 Sep column done: hypothesis fallback across the registry product, bounded.**
`iter_signatures` walks successive collapse periods instead of only the first,
resuming the sweep so an ordinary file costs exactly what it did before. Bounded
by 6 candidates and a 12 s wall clock. Uncoded data produces *no* candidates at
all, so the judge's first input is untouched - still 8.4 s, still `failed`.

**Still open, and now measured rather than assumed.** An interleaved stream with a
*short repeating* payload is refused, not recovered. The block-boundary offset is
picked by argmax of deficiency, and on a structured source that argmax carries no
signal: across three fixtures the true offset sits within **one** of the maximum
while ranking 39th, 59th and 71st of 96. It needs a functional test per offset,
which is a family search per offset, which does not fit the budget. Logged with a
test that fails loudly if it ever improves on its own. Does not affect the demo
message (its period is longer than the interleaver's) or random payloads; would
affect real telemetry with short repeating frame headers.

**Anvith:** your roll-off fix and tap caps are in my numbers and changed nothing
in the recovery outcome - the 6 dB rows fail on non-zero BER, which is physics.
Your 3 Sep claim 1 reproduces from my side: the threshold is **zero bit errors**,
not low BER. And your shortest-span rotation rule is sound, but it was being
handed a false positive to rank; that was my bug, not yours.

**Dheeraj:** second time in three days that real payloads found something random
bits cannot. The zoo needs text payloads AND short repeating ones - the second
kind is what real telemetry frame headers look like and it is where this still
breaks.

**Naidhruv:** `PayloadReport` now carries `inverted` - the UI should say when a
payload was read in inverted polarity, because blind, we cannot tell 0 deg from
180 without a sync marker. That marker is 7 Sep framing work.

**Also 4 Sep: the RS runtime, which was blocking the 6 Sep gate. Fixed.**
`blind_recover` searched 255 alignments x 3 profiles, RS-decoding 24 blocks each,
but it accepts an alignment only at decoded fraction 1.0 - so one failed block
already settles it and the other 23 decodes only make the answer more precisely
negative. A wrong alignment fails on block one essentially always.

| | before | after |
|---|---|---|
| `blind_recover`, worst case (random data) | ~113 s | **1.8 s** |
| `blind_recover`, true RS stream | - | **3.7 s** |
| the RS false-positive test | 112.9 s | **5.2 s** |
| RS exact on 20 streams | 209.9 s | **52.3 s** |

Behaviour-preserving: the accepting path never takes the early exit, so the
errata rate that ranks profiles is still measured over every block, and a test
asserts both paths agree on frac == 1.0 for every alignment. Pinned with a wall
clock rather than a status, the way Anvith pinned his S3 tap cap.

**Next (5 Sep):** concatenated CCSDS chain - RS outer, interleaver,
convolutional inner, scrambler, recovered in sequence. Blocked on nothing; the
scrambled-stream composite is guarded and labelled rather than announced, and
1 Sep established that scrambling does not hide the code from rank collapse.

**4 Sep, later: I ran the 8 Sep adversarial gate early, and it was failing.**

The existing false-positive tests all used UNIFORM random data, which is the one
input a rank test finds easy. Nobody had tested DEGENERATE or merely PATTERNED
streams. Twelve adversarial inputs, none of them convolutionally coded - six came
back `status=ok`:

| input | claimed, at 0.63-0.70 confidence |
|---|---|
| all ones | `block(depth=...)` |
| alternating 0101 | `G=(0o1, 0o1)` plus an interleaver |
| period-8 pattern | `block(depth=...)` |
| uncoded ASCII, short repeat | a convolutional interleaver |
| uncoded ASCII, interleaved | `block(depth=...)` |
| biased 70/30 coin | `rate 1/1 K=4, inferred BER 0.3015` |

**None of these was a regression** - I checked by running the identical battery
against a worktree at yesterday's commit, and all six predate 3 September. They
have been there the whole time.

The last row is the one worth reading twice: 0.3015 is 1 - 0.7 to three
decimals. The syndrome test was measuring the SOURCE's own bias and reporting it
back as the channel's error rate. A biased i.i.d. stream makes every parity
check biased.

Three structural guards close all six, and **the audit now passes 12 of 12 with
zero `ok`**:

- `code_signature_holds()` - a rate-1/n code constrains its stream ONLY at
  multiples of n and is full rank everywhere else. This module's docstring has
  said exactly that since 29 August and nothing ever checked it. Degenerate
  streams are deficient at odd lengths too. Only lengths BELOW the span are
  checked, and that bound is load-bearing: a structured source adds odd-length
  deficiency at and above its own period, so checking the whole profile would
  reject the very streams the candidate walk exists to recover.
- `MIN_CODE_MEMORY` on the INTERLEAVER path, which never had it. `_finalise`
  treats "an interleaver was identified" as sufficient evidence, so a hypothesis
  backed by a memory-0 "code" walked through the exit guard untouched.
- `n >= 2` and an implied-BER bound on the statistical path. A rate-1/1 code has
  no redundancy to have recovered, and an implied error rate outside the
  method's own measured 3 % ceiling is not a code seen through noise.

**Also found by the same run: `summary()` raised KeyError** on a convolutional
hypothesis - it formatted `p["depth"]` and `p["width"]`, which every family has
except convolutional. That is the one method whose docstring promises it never
raises, and it is called from the UI on every result including the failures it
exists to explain. No test caught it because no test had ever printed one.

All of it is now `tests/unit/test_adversarial_s4.py`, 29 tests, ~98 s. **416
passed, 4 skipped** across unit + contract, and the end-to-end study is unchanged
at 30/36 and 15/18 - the guards cost nothing on the working path.

**Naidhruv / everyone - the general lesson:** a false-positive test is only as
good as its inputs, and uniform random is the easy case. The gate says "uncoded
random data must NOT produce a false code detection" and we were passing it while
claiming codes in all-ones.

---

**4 Sep, later still: Dheeraj's zoo landed and I ran every gate against it.**
Full write-up in `reports/zoo_gate.md`. Nothing below reads
`tests/fixtures/local_zoo.py`.

**First, is the zoo itself right?** Contract compliance I can read off the JSON,
but a corpus that merely labels itself is not ground truth. So for every clean
file I de-interleaved at the STATED offset with the STATED depth x width and
multiplied by the parity check of the STATED generators: **residual 0.000000 on
every one.** The data matches its own labels independently of anything my code
believes. Lengths 159 845-160 000 (contract: >=150 000), all fields present,
both same-period factorisations (8x12 and 16x6) there, uncoded file present,
start offsets deliberately off-boundary. **Dheeraj - this is a clean delivery.**

**Bits-only, 73 files.** Clean unscrambled: period 6/6, depth x width 6/6,
generators 6/6. BER 0.001-0.02: 0/30. Scrambled: 0/36, all declined or
downgraded. Uncoded random: declined. **Confidently wrong answers: 0.**

6 of 73 recover, and that is the published envelope meeting a corpus built
deliberately outside it - 36 files scrambled, 30 noisy, both documented open
problems. **But it means the 4 Sep gate ("at least 40% of the corpus decodes")
is unreachable against a corpus composed this way**, not because recovery is
weak but because 92% of the files are outside the declared envelope. Someone
has to decide whether the corpus gets weighted toward the envelope or the gate
gets stated against the in-envelope subset. That is a standup decision, not
something to reinterpret quietly on the day.

**RF corpus, 36 WAVs, 6 modulations x 6 SNRs.** Dheeraj's modulator -> Anvith's
S3 -> my S4, three different authors, which is the first time this chain has
been measured without my own fixture on the transmit side:

| | bpsk | 2fsk | 4fsk | qpsk | 8psk | 16qam |
|---|---|---|---|---|---|---|
| full recovery | **6/6** | 5/6 | 5/6 | 5/6 | 3/6 | 2/6 |

**26 of 36, all six modulations, zero confidently wrong.** 6/6 at 15 and 20 dB,
5/6 at 13, 4/6 at 10 and 8, 1/6 at 4 dB. Two honesty notes: it is PARAMETER
recovery, not exact-bit decode, so do not quote it against the scorecard's
"end-to-end exact-bit" row; and the corpus sets cfo=0, phase=0, timing=0, so
these files are EASIER than my own fixture.

**Where the cliff actually is - measured, with the zoo's own generator.** The
corpus BER grid is 0.0 then 0.001, so every file is either perfect or hopeless
and the grid cannot see our own edge:

| injected BER | period | depth x width | generators |
|---|---|---|---|
| 0 | 3/3 | 3/3 | 3/3 |
| **2e-5** | 3/3 | **0/3** | **0/3** |
| 2e-3 | 3/3 | 0/3 | 0/3 |
| 5e-3 | 0/3 | 0/3 | 0/3 |

Two limits three orders of magnitude apart. Period detection survives to ~2e-3,
**which confirms the 0.30 % ceiling in `ber_ceiling.md` against real data**.
Factorisation and generators die at the FIRST bit error - about three flipped
bits in 160 000.

**Dheeraj, the one request:** BER points at 2e-5, 5e-5, 1e-4, 2e-4, 5e-4. The
entire operating envelope lives between your 0.0 and your 0.001 and no corpus
file lands in it.

**S3 ALREADY KNOWS WHETHER S4 WILL SUCCEED, and this is Anvith's number.**
Sorting all 36 RF files by S3's own `estimated_output_ber` separates the
outcomes completely - every recovery <= 1.5e-6, every failure >= 7.5e-5, a
fifty-fold gap with nothing in between. **EVM does not separate them at all**
(BPSK at 33 % EVM recovers; 16-QAM at 11.7 % fails). So the orchestrator can
decide, for free and BEFORE paying up to 32 s for the S4 search, whether the
search can succeed - and the stage card can say "this capture demodulates at
3e-4, recovery needs better than about 1e-5" instead of declining silently.
**Anvith: nothing to fix, S3 locked 6/6 on every file. Please keep
`estimated_output_ber` as a first-class output rather than a diagnostic.**

**The rotation search was burning 70 s to learn nothing.** 8-PSK files were
taking 63-72 s against a 90 s WHOLE-analysis budget. The cost was not recovery:
S3 offers one LLR array per unresolvable phase rotation (2 for BPSK, 4 QPSK,
8 for 8-PSK) and `blind_recover` ran on each WITH the statistical fallback,
which spends 8 s proving a negative - on rotations that are wrong by
construction. Every status was identical without it, on all 36 files.
`pipeline/s4_recover/rotations.py` now screens cheaply and pays only when
screening found nothing, under a 25 s bound:

| | before | after |
|---|---|---|
| worst single file | 72.1 s | **32.3 s** |
| whole corpus | 746 s | **258 s** |
| recovery | 26/36 | **26/36** |

**Naidhruv:** that is a callable entry point, `recover_over_rotations()`, so the
orchestrator does not have to rediscover either the shortest-span rule or the
screening rule. It returns which rotation won and whether the budget ran out.

**I did NOT delete `tests/fixtures/local_zoo.py`, against my own instruction.**
Doing it today would delete coverage rather than duplication: `zoo/bits_only.py`
has no `payload_text` (every 3-4 Sep finding depends on structured payloads), no
`mean_burst` (bursts move the ceiling ~16x), and only block interleavers (so the
1 Sep diagonal gate cannot run against it). The rule behind the instruction -
two sources of truth must not coexist - is met a better way: the GATES now run
on the real corpus, `local_zoo` is demoted to a parametric generator for cases
the corpus cannot express, and the two were checked against each other and
agree. Delete it the day those three knobs exist in `zoo/`.

**423 passed, 4 skipped.**

---

**4 Sep, end of day: the chain is blind end to end, and S2 has a bug that costs
us the recovery.** Full write-up in `reports/blind_chain.md`.

**The overclaim I made yesterday is retired by measurement.** Every study of
mine passed `fs` and `symbol_rate` to S3 from the truth sidecar, because S2 did
not exist. It does now. The study reads ONLY the WAV, through S0; the truth JSON
is opened once at the end to score, never to produce.

| | S2 rate | true | err | runs | scheme | interleaver | generators |
|---|---|---|---|---|---|---|---|
| bpsk 20 dB | 50000 | 50000 | 0.000 % | 1 | bpsk | YES | YES |
| qpsk 20 dB | 50000 | 50000 | 0.000 % | 2 | qpsk | YES | YES |
| 8psk 20 dB | 50000 | 50000 | 0.000 % | 3 | 8psk | YES | YES |
| 16qam 20 dB | 50000 | 50000 | 0.000 % | 4 | 16qam | YES | YES |
| 2fsk 20 dB | 50000 | 50000 | 0.000 % | 5 | 2fsk | YES | YES |
| 4fsk 20 dB | 50000 | 50000 | 0.000 % | 6 | 4fsk | YES | YES |

**6 of 6, all six modulations, nothing supplied.** The modulation is found by
iterating the registry and keeping whatever produces a rank collapse - the
column's own wording - and **no wrong modulation ever produced a confident
answer**. Anvith: that is the direct answer to your subset trap from my side.
S4 rejected every incorrect constellation on its own, 0 false positives.

**DHERAJ - TWO THINGS, ONE PERFECT AND ONE BROKEN.**

Your symbol rate is exact to three decimals on all six files. Nothing to fix.

Your CFO estimate is wrong on every file, and it costs us the recovery. True CFO
on this corpus is **0 Hz**. S2 reports:

| scheme | S2 CFO | equals |
|---|---|---|
| bpsk | 25 000 Hz | symbol_rate / 2 |
| qpsk | 12 500 Hz | symbol_rate / 4 |
| 8psk | 6 250 Hz | symbol_rate / 8 |
| 16qam | 12 500 Hz | symbol_rate / 4 |

That is the M-th-power branch ambiguity: the estimator resolves `M*cfo` modulo
2*pi, so it recovers the offset only modulo `symbol_rate/M`, and with a true
offset of zero it locks onto the modulation's own spectral line. **Zero is never
offered at any rank** - every ranked hypothesis is an alias - so "decode via the
second hypothesis" cannot rescue it.

Applying it breaks recovery on **4 of 4** files that recover perfectly without
it, and S3 still says `ok`:

| file | with S2 CFO | without |
|---|---|---|
| bpsk | EVM 37.5 %, no recovery | EVM 5.2 %, recovered |
| qpsk | EVM 6.1 %, **no recovery** | EVM 5.2 %, recovered |
| 8psk | EVM 5.4 %, **no recovery** | EVM 5.1 %, recovered |
| 16qam | EVM 6.5 %, **no recovery** | EVM 5.6 %, recovered |

Read the middle three twice: **EVM looks fine and the recovery is dead.** Third
time this week EVM has failed as a quality signal. The fix is small - offer the
alias set `cfo + k*symbol_rate/M` as ranked hypotheses, or include zero and let
a downstream test choose. Today it reports one alias at high confidence with no
way back.

**My side survives it** by treating CFO as a hypothesis rather than a fact: the
null (no pre-correction, let S3's carrier loop work) is tried first, S2's
estimate second.

**THE 4 SEP VERIFY LINE, both ways.** *"Corrupt S2's top hypothesis; the
pipeline still decodes via the second."* Naturally - S2's top CFO hypothesis IS
wrong on every file and the chain still recovered 6/6, which is the line
satisfied by a real upstream error rather than a synthetic one. And
deliberately - replacing S2's winning symbol rate with 1.5x the truth,
**4 of 6 still recovered** via a later hypothesis. The two that did not hit the
120 s search budget at 130.5 s and 123.8 s; they ran out of time, they did not
fail to recover.

**NAIDHRUV / DHERAJ - THE COST FINDING, and it decides 6 Sep.** Clean-path blind
times: bpsk 2.3 s, 4fsk 9.8 s, qpsk 20.1 s, 2fsk 46.7 s, 8psk 49.1 s, 16qam
75.1 s. The cost tracks **registry position**, not difficulty - each miss pays a
full S3 demodulation plus an S4 rotation search, and worst case with a corrupted
hypothesis is 24 chain runs. The core-lock gate is 90 s for the WHOLE
seven-stage analysis, and S2-S4 alone is already 75 s on 16-QAM.

**So the classifier is not a nice-to-have, it is what makes the fallback
affordable.** Dheeraj's LightGBM model and Anvith's ranked `search.py` prune the
modulation dimension from six to one or two - the difference between 75 s and
about 12 s. The exhaustive loop stays as the fallback for when the classifier is
unsure, and it is now measured so we know what it costs when it fires.

**Heads-up on a merge break:** `anvith/s3-robustness` deletes
`tests/fixtures/rf_channel.py`, which `reports/end_to_end_study.py` (mine)
imports. It will break the moment that branch lands. His `tests/fixtures/
corpus.py` has `synth()` as the replacement; I will port it when the branch
merges rather than guess at it now.

---

## 10 Sep, independent pre-demo audit - the gate was scoring less than it
## printed, the UI plotted two invented curves, and every 4FSK capture was
## 0.42 dB from being refused

An end-to-end audit against the tagged tree, every claim executed rather than
read. Six defects, all fixed and re-verified. The core science came out of it
stronger than the repo's own evidence said, and is now pinned by a test that
did not exist.

### 0. THE HEADLINE, MEASURED FOR THE FIRST TIME: the decoded bits ARE the transmitted bits

Nothing in this repo had ever compared S5's output against the payload the
transmitter actually sent. `run_demo.py` scored the modulation name;
`test_e2e_real_signal` scored S4's recovered parameters; `reencode_ber` scores
self-consistency. A chain can pass all three and still hand back wrong bits.

The corpus generator is fully seeded, so the sent payload is reproducible.
Regenerated it and compared, all eight demo captures:

| capture | S4 params vs truth | source-bit errors | where |
|---|---|---|---|
| bpsk_20dB_2005 | MATCH | 1 of 7994 | bit 1 |
| qpsk_15dB_2010 | MATCH | 2 | bits 0, 2 |
| qpsk_20dB_2011 | MATCH | 2 | bits 1, 3 |
| 8psk_20dB_2017 | MATCH | **0** | - |
| 16qam_15dB_2022 | MATCH | 3 | bits 1, 5, 6 |
| 16qam_20dB_2023 | MATCH | 2 | bits 0, 2 |
| 2fsk_20dB_2029 | MATCH | **0** | - |
| 4fsk_20dB_2035 | MATCH | **0** | - |

**Every residual error in the whole set sits at bit index 6 or lower**, which
is a Viterbi entering a trellis mid-codeword with no state history. Three
captures are exact from bit 0. Past bit 6 there is not one wrong bit in any
capture. Worst-case source-bit BER 3.75e-04, all of it warm-up.

That is the strongest claim this project can make, and it is now the strictest
test in the repo: `tests/e2e/test_decoded_bits_match_transmitter.py` allows a
transient inside 16 bits and demands EXACTNESS past it, so an error at bit 400
fails while one at bit 3 does not.

### 1. The demo gate printed ALL EIGHT CORRECT while checking the modulation name and nothing else

`run_demo.py` scored `got == want` on modulation, all seven stages self-
reporting `ok`, and elapsed under 90 s. The truth JSON beside every capture
carries the interleaver family, depth, width, period and the code's rate, K and
generator polynomials. **None of it was ever compared.** A run that named the
modulation, reported ok everywhere and recovered the WRONG interleaver would
have printed ALL EIGHT CORRECT.

`check_recovery()` now scores all of it. Verified against deliberately
corrupted inputs: wrong depth/width, wrong generators, wrong K, wrong period,
wrong family, and nothing-recovered-at-all are each caught and named. The gate
still passes 8/8, so the claim was true. It just was not being checked.

### 2. The UI plotted two FABRICATED curves under a comment saying measured

`web/src/utils/visualizerData.js` carried `EMPIRICAL_ENVELOPE_DATA` headed
"measured across test zoo in reports/s3_envelope.csv". For BPSK, QPSK, 8PSK and
16QAM every value matches that CSV exactly. For 2FSK and 4FSK **none of it is
in the CSV**: the SNR points differ (CSV 2fsk 5/8/12/16, UI 10/12/15/20) and the
EVM values are invented outright. The CSV's `evm_percent` is EMPTY on all eight
FSK rows, correctly, because EVM is a distance to a constellation point and the
FSK receiver is a non-coherent frequency discriminator with no constellation.
The "Empirical EVM vs SNR" chart drew those numbers as measurements.

`ZERO_ERROR_SNR_THRESHOLDS` was wrong on three of six against the same CSV.

Fixed: FSK rows carry the measured carrier-lock at the measured SNRs with
`evm: null`; the EVM chart omits any scheme with no EVM and says why; the
thresholds are re-derived from the CSV; and a scheme whose lowest TESTED SNR
was already error-free is drawn as `<= x dB` rather than as an observed
crossing, which is four of the six.

**The test beside it is why this survived.** It asserted the constants equalled
themselves. It now reads `reports/s3_envelope.csv` and cross-checks every
point. Re-injecting the old 2FSK row fails it with "2fsk @ 10 dB is plotted but
is not a row in s3_envelope.csv".

Also stated there now: `measured_ber == 0` in that CSV means no errors in
40,000 demodulated bits, so it is a detection limit near 2.5e-05, not a zero.

### 3. EVERY 4FSK capture measured a negative SNR, 0.42 dB from total refusal

`estimate_snr`'s docstring recorded this as a known gap, "off by 8-23 dB".
Measured across all 504 corpus files it is worse than that reads: every 4FSK
file, true SNR 4 to 20 dB, estimated between **-3.16 and -4.58 dB**. The
estimate carried no information about the true SNR at all.

It is not just a wrong number on a card. `adapt_s1` refuses below -5.0 dB and
marks every downstream stage `out_of_envelope`. The worst cell (4fsk at 4 dB,
-4.58 dB) sat **0.42 dB from refusing a capture this pipeline decodes to the
exact transmitted bits**.

The docstring already named the fix, "a constant-modulus / moment-based
estimator", so it is now there. M2M4: with M2 = E|r|^2 and M4 = E|r|^4,
S = sqrt(2*M2^2 - M4) is exact for a constant-modulus signal, which unshaped
CPFSK is. `estimate_snr` takes the LARGER of the spectral and moment estimates,
and that is sound rather than convenient: S_hat = S*sqrt(2 - ka) with ka >= 1
for every signal by Jensen, so the moment estimator can only UNDERSTATE, and a
percentile floor contaminated by signal also only understates. Neither can push
the answer above truth.

| | before | after |
|---|---|---|
| bpsk/qpsk/8psk/16qam | +0.23 to +0.74 dB | **unchanged**, spectral still wins |
| 2fsk | -0.07 to -2.05 dB | within **0.01 dB** |
| 4fsk | -8.47 to -23.16 dB | within **0.02 dB** |

The strict xfail `test_snr_known_gap_4fsk` is now a passing test, plus four
more: no capture near the refusal gate; the moment estimator never overstating,
checked against truth on all 504 files because that property is what makes the
max safe; exactness on a synthetic unit-modulus signal; and declining on pure
noise. The stage card now reports `snr_method` and both estimates, so the
number is readable next to what produced it.

Live through the API on 4fsk_20dB_2035: **-3.19 dB becomes 20.00 dB** against a
truth of 20.

### 4. reports/s3_envelope.csv no longer reproduced, and regenerating it showed S3 is BETTER than its own committed evidence

The study is deterministic (seed 17, payload from `default_rng(3141)`),
confirmed by running it twice for zero differences outside `elapsed_ms`. So the
committed CSV was stale and S3 had moved under it. Regenerated:

- `8psk_8dB_sps4`: **low_confidence becomes ok**, measured BER 0.04785 to
  0.00243, and its estimate went from 16x optimistic to well calibrated.
- PSK lock rate 19/20 becomes **20/20**.
- `carrier_lock` and `evm_percent` did NOT move, which is why the UI values
  above are still right.
- 16QAM's measured BER moved the other way: 4.75e-04 at 13 dB, 2.5e-04 at 15,
  2.75e-04 at 18, zero only at 22.

### 5. A caveat section that could not contradict itself

`s3_envelope_study.py` builds "cases where the estimate was more than 4x
optimistic" with the filter `status != "ok" and measured > 4*estimated`. The
claim under test is that the estimate is only untrustworthy when status is not
ok, and the filter looked at nothing else. It could only ever confirm itself.

On the regenerated data it hid the two worst rows in the sweep, both reporting
`ok`: **16qam at 18 dB, estimated 3e-06 against 2.75e-04 measured, 92x** and at
15 dB, 23x. The filter now covers every row and splits flagged from `ok`, and
the report says plainly that gating on status is not sufficient.

Worth holding next to HANDOFF's rule that `estimated_output_ber` predicts
whether S4 can succeed. That correlation was measured on a 36-file PSK corpus.
On a dense constellation the estimate can be two orders optimistic while the
lock is genuine.

### 6. make test ran 184 of 997 tests

The target listed `tests/contract tests/service tests/eval tests/e2e` and
omitted `tests/unit`, which is **813 tests**: every S4/S5/S6 blind-recovery
test, the adversarial false-positive battery, and the S1/S2/S3 units. Anyone
following the documented workflow got a green result having never run the tests
that guard the science. Now `pytest tests/`.

`make docker-build` also tagged `wavsih26:phase8`, a third name for the image
that nothing else in the repo mentions. It now matches `docker-compose.yml` and
the release, `raaya:v1.0`.

### 7. Executed and clean - the UNVERIFIED list is shorter

The 10 Sep entry below lists "Web UI build, upload-path security (traversal,
size limits), load, the LDPC decode path" as never verified. Three are now
executed:

- **UI build:** builds clean (56 modules), 19/19 JS tests, and the built bundle
  is served by the API with every asset resolving. `/health`, `/envelope` and
  `/registry` all answer.
- **Upload-path security: 20 of 20 checks pass.** Four filename-traversal forms
  are contained to the upload directory; the extension allowlist rejects .exe,
  .py and .sh; the size cap returns 413 AND leaves no partial file; empty
  uploads are refused; six artifact-endpoint traversal forms (raw, URL-encoded,
  double-encoded, backslash) fail closed with nothing leaked.
- **Full path through the service:** upload, 202, poll, completed in 18.9 s,
  all seven stages ok, every recovered parameter equal to truth.

Still genuinely unverified: load beyond 10 concurrent uploads, and the LDPC
decode path.

### 8. One correction to the entry below

It states that `zoo/corpus` IS in the image because `.dockerignore` does not
exclude it, and calls the skip-condition docstring in
`test_e2e_real_signal.py` stale. On `main` today `.dockerignore` line 20 is
`zoo/corpus/`. The corpus is NOT in the image and that docstring is correct.
The demo is unaffected: `demo/signals/` is not excluded, which is why the
container gate runs.

### Not mine, flagged not touched

The working tree carries substantial uncommitted UI work (`web/src/App.jsx`,
`index.css`, every component, and a new `web/src/components/ui/`) that predates
this audit. It builds and its tests pass. It is not committed, and it is not
mine to commit.

---

## 10 Sep - v1.0 TAGGED. The 9 Sep gate run and passed, one day late.

The gate reads: "the exported image runs on a machine that has never seen the
repo, with no network, and processes all eight demo files correctly, twice."
Every clause of that was verified, not assumed.

| what | result |
|---|---|
| `main` | `3980735`, tagged **v1.0**, pushed |
| Full suite at the tag | **983 passed, 4 skipped, 2 xfailed, 0 failed, 0 errors** (989 collected) |
| Image | `raaya:v1.0`, 1.28 GB |
| Portable export | `C:\dev\raaya-release\raaya-v1.0.tar`, 291 MB |
| sha256 of the tar | `ec9341003c8dd1e155468c5ee8fe17b99979383cf2eff7d55606f5038d385bbd` |

**The export was verified the only way that means anything: the local image was
DELETED, restored from the tar alone, and the gate re-run offline.**

    docker load -i raaya-v1.0.tar
    docker run --rm --network none raaya:v1.0 python demo/run_demo.py --twice
    -> PASS 1: ALL EIGHT CORRECT
       PASS 2: ALL EIGHT CORRECT
       GATE PASS - 2 of 2 passes, every capture correct in all seven stages
       exit 0

8/8 both passes, 9.3-17.5 s per capture against a 90 s envelope, no network.

**Copy that tar to two USB sticks and one cloud drive** - that is the rest of the
9 Sep instruction and it is a manual step nobody has done yet. Verify each copy
with the sha256 above.

### What landed to get here

- Merged `naidhruv/integration` (11 commits: CCSDS outer RS into S5, S6 ASM
  framing, envelope refusal, UI). Three conflicts in `service/orchestrator.py`.
- **S5 was handed a budget longer than its own stage.** The branch set
  `S5_DECODE_MAX_BITS = 32_000` = 20.4 s of Viterbi inside a 15 s stage cap.
  Set to 16_000 (9.4 s, 1.6x margin). Third time this pattern has bitten.
  Its amplifier is worth remembering: **a timed-out stage is not cancellable** -
  Python cannot kill the thread - so the orphaned Viterbi starved the stages
  after it, and one overrun caused eight failures across two test classes.
- Created `demo/` - it had never existed, so the gate could not be run at all
  and `git checkout v1.0` had nothing to check out.

### Standing instructions for the panel

`demo/README.md` carries the envelope table and the rules. Two to hold:

1. **Do not change the parameters of `--demo --text`.** It pins
   `start_offset=0`; a repeating-text payload at a non-zero offset recovers
   1 of 10 against 10 of 10 for an unstructured payload.
2. **Do not add a sub-envelope capture to the demo set.** 16-QAM below 15 dB
   does not complete. It fails honestly, but it fails.

The strongest claim to make is not "six modulations". It is that **all ten
sub-envelope cases decline with a stated reason and none produces a confident
wrong answer** - and that is measured, in the README.

### Still UNVERIFIED - say so if asked

Web UI build, upload-path security (traversal, size limits, model
deserialisation), load beyond 10 concurrent uploads, the LDPC decode path. The
adversarial audit that would have covered these failed twice on session limits
and never ran. Nobody should claim these are fine.

---

## 10 Sep, pre-demo hardening - a FALSE POSITIVE that was shipping, a fifth
## silent-getattr, and the operating envelope measured rather than claimed

Adversarial pass the night before judging. Everything below was executed, not
read. Full suite with all three changes: 954 passed, 4 skipped, 2 xfailed,
0 failed, 0 errors.

### 1. CRITICAL, and it was already shipping: a false code recovery

    blind_recover(np.tile([1,0,1,1,0,0,1,0], 20_000))
      ->  status ok,  block(depth=5, width=2),  a recovered code

`10110010` repeated twenty thousand times, reported as a confident blind
recovery. Verified this is NOT something introduced tonight: it reproduces on
the shipping path with every flag at its default.

Every downstream guard passed it, and each was correct by its own terms - the
deficiency is real, the de-interleaved stream is consistent, the signature
holds, and `_residual_syndrome` is **exactly 0.0**, because a period-8 stream
annihilates almost any parity check handed to it. **Nothing that inspects the
RECOVERED PARAMETERS can catch this**, which is why the new guard reads the
INPUT and is the only test in that file independent of the recovery.

The 8 Sep gate asks that "uncoded random data does not trigger a false code
detection". Random data was tested and passes. PERIODIC data was never tested,
and it did not.

`exact_repetition_period()` separates the two completely - measured:

| stream | exact period | before | after |
|---|---|---|---|
| repeating 8-bit | 8 | **ok, block(5,2)** | failed |
| repeating 3-bit / 12-bit | 3 / 12 | recovered | failed |
| alternating 0101 | 2 | low_confidence | failed |
| all zeros / all ones | 1 | low_confidence | failed |
| uniform random | none | failed | failed |
| **real coded, random payload** | **none** | ok | **ok** |
| **real coded, TEXT payload** | **none** | ok | **ok** |

7 of 7 adversarial inputs decline; no true positive lost. A coded stream driven
by a real source is aperiodic, so an exact period is not weak evidence - it is
proof the stream carries no information. Three regression tests in
`tests/unit/test_adversarial_s4.py`; confirmed the first FAILS on the pre-guard
code, reporting ok with depth 5 width 2.

### 2. Fifth instance of the silent-getattr class, in the CCSDS chain

A reflective audit - every `getattr(x, "literal", default)` in shipping code
checked against every dataclass field in the project - returned one real hit:

    ccsds.py:461  getattr(hyp, "poly", None) or getattr(hyp, "poly_octal", None)

`ScramblerHypothesis` carries `degree, period, taps, state, syndrome_violations,
reason`. **Neither name has ever existed**, so `scrambler_poly` was None on every
blind recovery that succeeded - set immediately after `descramble(bits, hyp)`
used that same hypothesis correctly. The only other writer fills the field from
the `STANDARD_RANDOMISERS` dictionary, so a dictionary match reported a
polynomial and a BLIND recovery did not. Exactly backwards from what this stage
exists to demonstrate.

Fixed to pack the recovered Berlekamp-Massey connection polynomial, with the
representation stated in the code. **Deliberately NOT claimed to equal the CCSDS
0o651**: `taps` is a connection polynomial, not the Fibonacci tap-mask
`zoo.lfsr_scramble` takes, and the conversion is unverified. Reporting a
recovered value in a stated representation beats reporting None; claiming an
equality nobody checked would be the same error one layer up.

### 3. THE OPERATING ENVELOPE, measured - use this to pick demo files

All six modulations, all six corpus SNRs, through the real `orchestrate()`.
Stages reporting ok, out of seven:

| | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB |
|---|---|---|---|---|---|---|
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| qpsk | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 8psk | 3/7 | 4/7 | 4/7 | 7/7 | 7/7 | 7/7 |
| 16qam | 3/7 | 4/7 | 4/7 | **4/7** | 7/7 | 7/7 |
| 2fsk | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 4fsk | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |

**Every modulation completes at >= 15 dB. 16-QAM needs >= 15 dB; 8-PSK needs
>= 13 dB.** Pick the demo set accordingly - a 16-QAM file at 13 dB does not
complete, twice out of two.

The important half: **every failure is at S4 and every one is honest.** Either
"FAILED - no rank collapse at any period from 8 to 152; the search stopped there
because ..." or "LOW_CONFIDENCE - period found but no factorisation restored a
code". Not one of the 10 sub-envelope cases produced a confident wrong answer.
That is the claim worth making to a panel, and it is now measured.

### 4. The demo is pinned to its one working configuration

`--demo --text` hardcodes `start_offset=0`. Reproduced the documented 1/10:
repeating-text payload recovers at offset 0 only; random payload recovers 10/10
at every offset. **Do not re-run the demo with different parameters in front of
a judge.**

Tried to fix it by making the text non-repeating so it carries no periodicity of
its own. **That is worse: 0/10, failing even at offset 0**, because ASCII is
rank-deficient by construction - bit 7 clear in every byte is a linear
constraint every 8 bits. Recording the refuted hypothesis so nobody spends the
same hour.

### 5. The structured-source gap is closable, and the stated reason is wrong

HANDOFF defers it because "a dozen statistical searches per file does not fit
the time budget". Measured: **a full 96-alignment functional sweep is 3.83 s
worst case, 0.040 s per alignment**, against a 90 s envelope and a 15 s stage
cap. Cost is not the obstacle.

Standalone, sweep + shortest-span recovers **10/10 offsets** with correct
generators and readable text in under 1 s per case, against 1/10 shipping.

**It ships behind `sweep_alignments=False` and the reason is a false positive,
not the cost.** On the demo stream three alignments clear the full functional
gate - 51 (rate 1/6 K=3, span 18), 59 (rate 1/2 K=7, span 14, TRUE), 67 (span
18) - all with residual exactly 0.0. Shortest span separates them here. But
"residual is zero" is NOT decisive on a structured source, which the rest of
`rank_collapse.py` assumes it is, so on a stream where only artifacts clear the
gate this would turn an honest low_confidence into a confident wrong answer.
Integrated it reaches 6/10, not 10/10. Enable only after someone characterises
the artifact rate on a corpus, not on one file.

### 6. Container: the 9 Sep gate, actually run

Image builds (1.52 GB). `zoo/corpus` IS in it - 252 RF WAVs, 146 bits-only -
because `.dockerignore` does not exclude it. The skip-condition docstring in
`test_e2e_real_signal.py` claiming the corpus is excluded is stale.

With `--network none`:
- `--demo --text` recovers period=96, block(8,12), rate 1/2 K=7,
  G=(0o171, 0o133), 100% printable, ~21 s. **Offline, in-image.**
- Eight files, twice: 7 of 8 pass both runs at 7/7 stages inside 15 s each.
  The eighth is 16qam@13dB, which fails honestly at S4 both times - see the
  envelope above. Choose 15 dB or higher and this is 8/8.

### 7. Checked and clean (executed, not assumed)

- No shipping code imports from `tests/` - a defect that bit twice here.
- Every RNG in shipping code is seeded; no unseeded randomness reaches a result.
- All ten third-party imports are pinned in `requirements.txt`; none missing.
- No truth leakage: `report(bits, ...)` takes only bits, and there is no `truth`
  reference anywhere in s4_recover / s5_decode / s6_frame.

### 8. Still open - NOT fixed, and both are release-owned

- **There are ZERO git tags.** The plan expects v0.1 through v1.0, and the
  10 Sep emergency protocol is literally "git checkout v1.0 && docker compose
  up". **That fallback does not exist.**
- **There is no demo/ directory.** The 9 Sep gate names eight demo files; they
  have never been curated. The envelope table above says which to pick.

---

## 8 Sep, part 3 - the service demodulated EVERYTHING as QPSK, and the one
## real end-to-end test could not see it because its capture is QPSK

**Anvith found this and said it was not his to fix. It is mine - every line of
it is in `service/orchestrator.py`.** He measured it, I traced and fixed it.

### What was wrong, in one line

`adapt_s2` read `getattr(raw, "order_hint", 0)`. **S2Result has no
`order_hint`** - its field is `fsk_order_hint`. The default fired on every
input ever measured (0 on 30 of 30 corpus files), the ladder fell through to
its else branch, and every signal on the wire was announced as `qpsk`. Then
`_run_s3` ran that one named plug-in and never called `receive_best`, so the
blind search, the rate rescue and the breadth-first ordering were unreachable
from the API and the CLI alike.

Anvith's measurement, 40 random corpus files scored against transmitted bits:

| path | decodes | modulation correct |
|---|---|---|
| `receive_best(iq, params_from_s2(s2, fs))` | 35/40 | 37/40 |
| what the service actually did | **11/40** | **11/40** |

### What it cost end to end, measured here

One 20 dB file per scheme, through the real `orchestrate()`:

| truth | before | stages ok | after | stages ok |
|---|---|---|---|---|
| bpsk | qpsk, low_confidence | 5/7 | **bpsk, ok** | **7/7** |
| qpsk | qpsk, ok | 7/7 | qpsk, ok | 7/7 |
| 8psk | qpsk, low_confidence | 3/7 | **8psk, ok** | **7/7** |
| 16qam | qpsk, low_confidence | 3/7 | **16qam, ok** | **7/7** |
| 2fsk | qpsk, **FAILED** | 3/7 | **2fsk, ok** | **7/7** |
| 4fsk | qpsk, **FAILED** | 3/7 | **4fsk, ok** | **7/7** |

**One of six schemes worked, and it was the one my e2e test uses.**
`test_e2e_real_signal.py` runs `qpsk_15dB_2010.wav`, so the wrong answer was
the right answer and all seven stages stayed green. That is the same lesson as
this morning wearing different clothes: the test existed, it ran the real
chain, and it still could not fail. There is now a second capture in that file,
`2fsk_20dB_2029.wav`, chosen because 2-FSK failed hardest and no amount of
guessing qpsk can pass it. Confirmed it FAILS on the pre-fix code with
"s3_receive is FAILED - no symbol-rate line at 50000 Hz".

### The fix

1. `adapt_s2` reads `fsk_order_hint`, keeping `order_hint` as the fallback for
   dict-shaped S2s.
2. `adapt_s2` reads `modulation_hypotheses` - Dheeraj's classifier, populated
   on 28 of 30 files and 0.9987 on the worked example - which it had never
   read. The FSK ladder cannot name 16qam or 4fsk at all, so those were
   unreachable as a first hypothesis no matter what S2 found. The ladder stays
   as the fallback.
3. `_run_s3` calls `receive_best` with `params_from_s2(s2_raw, fs)` on the
   unhinted path. An explicit `mod_scheme_hint` stays a RESTRICTION - the
   caller named the scheme, so we run that one and nothing else.

**The budget is the part worth reading.** S3's own `SEARCH_BUDGET_S` is 20.0
and the service caps a stage at 15 s, so passing the default through would hand
the search a budget 1.3x longer than the stage it runs in and the stage would
die on the clock rather than return its best answer. `S3_SEARCH_BUDGET_S =
10.0`. Exactly the trap of the CLI's `DECODE_BITS = 24_000` carried into S5,
third time this pattern has bitten: a constant that is right for a caller with
no deadline, reused by one that has.

### A fourth instance of the same species, reported not acted on

`adapt_s2` also reads `symbol_rate_score`, which **S2Result does not have
either** - the ranked list is `symbol_rate_hypotheses`. So it was 0.0 on every
real input and `confidence` took its 0.9 default. The two test doubles set it
to 9.5 and 9.8, values chosen to sit just under the `/10` in the formula: the
formula was written against a field that does not exist, using numbers nothing
ever produced.

I did NOT wire the real number into that formula. Measured across the RF corpus
the statistic runs **19.0 at 4 dB to 48.2 at 20 dB**, so `score/10` would clip
to 1.0 for every file on disk - swapping a constant 0.9 for a constant 1.0,
which is worse for being confidently maximal. The real value is now reported as
`symbol_rate_peak_score` and the confidence mapping is untouched.
**Dheeraj - S2 is yours and this is a judgement about what the number means.**

### Verification

Three orchestrator tests and three e2e tests, all confirmed to FAIL on the
pre-fix code. Full suite: see the run below.

---

## 8 Sep, part 2 - the S5 seam hands soft LLRs to a byte-domain de-interleaver,
## and the re-encode check I added this morning cannot see it

Re-verified this morning's work against the tip rather than trusting my own
write-up, and found one more defect of the same family underneath it.

**Full suite on this branch before the fix below: 843 passed, 4 skipped, 2
xfailed, 0 failed, 0 errors in 26m11s.** My `a3e69df` message says 842; I
measured 843 on a clean run and cannot account for the extra one. Zero failures
either way, but the number in that commit message should not be quoted as exact.

### The defect

`_run_s5` de-interleaves with whatever family S4 names:

    stream = intl_plugin.deinterleave(stream, **intl.params)

`ccsds-symbol` works in the Reed-Solomon BYTE domain - `_to_bytes` packs bits,
so it returns uint8. That is correct where it belongs (after Viterbi, in
`s6_frame/ccsds.py`) and destructive here. Measured on 4096 float LLRs:

| de-interleaver | dtype out | negative LLRs surviving |
|---|---|---|
| `block_deinterleave` | float64 | 2066 of 2107 |
| `symbol_deinterleave` | **uint8** | **0 of 2107**, all values now {0, 1} |

`conv_code.decode` then sees dtype uint8 and silently takes its HARD path. It
raises nothing, returns 4074 bits, and `validate()` calls that **ok: True**
at entropy 0.9992.

**Reachable** because `ccsds-symbol` at depth 1 is the IDENTITY permutation, so
it clears the functional gate on exactly the streams the direct reading clears.
The shortest-span tie-break at `rank_collapse.py:840` excludes it only while
`direct` is non-None, and the direct reading is rejected whenever
`code_direct.span != first` - the family gate has no such constraint.

### The part that matters: my own re-encode check does not catch this

I claimed this morning that `validate_against` is the honest test of a decode.
It is - but it compares the decode against the POST-de-interleave stream, and
that stream is precisely what got destroyed. It measures garbage against
garbage:

| input | `validate_against` | re-encode BER | S5 reports |
|---|---|---|---|
| random normal LLRs | ok=False | 0.2826 | low_confidence |
| linspace LLRs | **ok=True** | **0.0059** | **ok** |

A uint8 truncation of a smooth ramp is highly structured, the decoder locks
onto that structure, and the re-encode agrees with itself. So the safety net is
input-dependent, not a guarantee, and the failure mode is a confident `ok` on
noise - the exact class `a3e69df` was written to close, one layer further in.

### The fix, and where it does NOT go

Not in the plug-in: the cast is legitimate there. The guard goes at the seam,
which is where the conventions say guards go. `_run_s5` now records whether it
was handed soft values and declines with the reason if the de-interleaver did
not hand them back.

**Scope checked, and it is narrow.** The CLI is unaffected - `cli.py:40` loads
`dtype=np.uint8`, so it is hard-bits-only by construction and the cast is a
no-op. The three `deinterleave` sites in `rank_collapse.py` are all the
RECOVERY path, which hard-slices by design. Orchestrator-only.

`tests/service/test_orchestrator.py::test_s5_declines_a_deinterleaver_that_destroys_soft_values`
asserts the premise (that `symbol_deinterleave` still destroys soft values, so
the test explains itself if that ever changes) and then that S5 declines.
**Confirmed it FAILS on the pre-guard code, reporting `StageStatus.OK`** - not
low_confidence, which is how I found that the re-encode check was blind to it.
`tests/service` + `tests/contract` + `tests/e2e` with the guard: 142 passed,
4 skipped, 0 failed.

---

## 8 Sep - the orchestrator could never decode a file, and the suite could not
## have told us. Both fixed, with the test that proves it.

**Start here: my 7 Sep numbers were measured on `main@100a30c` and main is now
`2fef069` - 23 commits on, all three of you.** Re-verified everything below
against the current tip rather than trusting the write-ups.

**Closed by you, confirmed by me, do not re-work:**

| | |
|---|---|
| **S3 flake** | **Gone.** 8/8 pass at ~10.5 s against the 20 s budget - on MY box, the slow one Anvith could not reproduce it on. `e7b9649` cut 8 chain runs to 3. |
| **Registry bug** | **Gone** (`750a05f`). 6 modulations, 4 interleavers, zero load errors. |
| **Core-lock gate** | 17.7 s twice consecutively against the 90 s budget. |
| `classifier.txt` autocrlf | Closed - loads, 1200 trees, 12 features. |

### 1. S5 COULD NOT DECODE ANY FILE, AND THE TYPE ERROR WAS THE SMALL HALF

`service/orchestrator.py` had one line that could not work on **any** input:

    code_params = s4_raw.code if hasattr(s4_raw, "code") else None
    return conv_plugin.decode(llrs, code_params or s4_res.values)

- S4 **ok** -> passes `CodeStructure(n, memory, span, consistent)`, which carries
  **no generators** (they are a sibling field on `RecoveryResult`) ->
  `TypeError: 'CodeStructure' object is not subscriptable`.
- S4 **failed** -> `code` is None, the fallback fires, and `s4_res.values` has
  `code_rate`/`K` not `n`/`memory` -> `KeyError: 'n'`.
- A dataclass is always truthy, so on the success path `or` never fired.

Reproduced both live, on three corpus files.

**The half that matters more: it never applied the offset and de-interleaver S4
had just recovered.** It decoded the stream as it arrived. Measured on
`qpsk_15dB_2010.wav`, same file, same recovered parameters:

| | re-encode BER |
|---|---|
| decode as it arrives (what main did) | **0.2948** |
| offset + de-interleave first (fixed) | **0.0005** |

**So the obvious fix - cast the params - would have shipped a stage that
returned confident noise and reported `ok`.** The crash is the only reason
nobody had seen it. S5 now applies what S4 found, and runs the plug-in's own
`validate_against` re-encode check; a decode that disagrees with its input is
reported `low_confidence`, not `ok`.

**Full S0->S6 now completes - the number I have been saying could not be
measured yet: 11.5 s, `in_envelope`, all seven stages `ok`, re-encode BER
0.0008.** Against a 90 s budget.

**S5 also has to fit a 15 s per-stage cap, and Viterbi is ~0.57 ms/coded-bit.**
The CLI's `DECODE_BITS = 24_000` is right for the CLI, which has no per-stage
timeout; carried into the service it put the slowest stage **1.1x** inside its
own deadline - the same shape as the S3 flake Anvith just spent a day removing.
Service decodes 12 000 (749 characters, 2.2x margin, 7.6 s); the CLI is
untouched.

### 2. TWO STAGES REPORTED `ok` ON NO INPUT

    adapt_s0 -> FAILED    adapt_s4 -> OK   <-
    adapt_s1 -> FAILED    adapt_s5 -> FAILED
    adapt_s2 -> LOW_CONF  adapt_s6 -> OK   <-
    adapt_s3 -> FAILED

`adapt_s4` because `getattr(raw, "status", "ok")` defaults to `"ok"`;
`adapt_s6` because the status was hardcoded. I watched S6 report **`ok` in 0 ms
with `n_bytes: 0`** immediately after S5 crashed - the last stage, the one that
shows the recovered message, green on a run that recovered nothing. Both now
fail with a reason.

### 3. ANVITH - YOUR LDPC PLUG-IN WAS INVISIBLE TO THE SERVICE

`REQUIRED_PLUGIN_MODULES` listed `conv_code` and `rs_code` but not
`ldpc_code`, so the API came up `CODES = {conv, reed-solomon}` while your unit
tests stayed green - a missing plug-in looks exactly like a scheme nobody tried.
Not your mistake and not Naidhruv's: the loader was written at 11:14, you moved
the plug-in into `pipeline/s5_decode/` at 14:43. A hand-maintained list in a
plug-in architecture will go stale again, so there is now a test that scans
`pipeline/` for top-level `register_*()` calls and fails if any module is not
loaded. Verified it catches the real gap.

### 4. MAIN WAS RED - 41 FAILED, 6 ERRORS - AND ONLY 3 WERE PRODUCT BUGS

My 7 Sep run was "678 passed, 1 failed". A clean run on `2fef069`:
**41 failed, 791 passed, 6 errors in 25m33s.** Five root causes, and the tally
reconciles exactly (14+14+10+1+1+1 failed, 4+2 errors):

- **28 failures: `httpx` was never pinned.** `fastapi.testclient` needs it;
  without it `service/main.py` *silently* falls back to its own
  `FallbackTestClient`, which is itself broken (`TypeError: cannot unpack
  non-iterable Route object`). One missing pin, 28 unrelated-looking TypeErrors.
  `httpx2==2.12.0` pinned (starlette 1.6.0 wants that name specifically).
- **14 failures: registry pollution.** `tests/contract/test_registry_contract.py`
  called `clear()` in `tearDown` and could never undo it - the real plug-ins
  register at *import* time, which does not re-run. Every test after it in the
  process saw an empty registry. Proved by ordering: the S3-S4-S5 chain file
  passes 4/4 alone and errors 4/4 after it; `test_s3_ldpc_junction.py` passes
  27/27 alone and fails 24 after it. **Anvith's LDPC work was never broken.**
  Now snapshots and restores.
- **The e2e suite failed a DIFFERENT RANDOM SUBSET every run.** Root cause is
  Windows-only: `_wait_for_job` returned when the run row went terminal, but the
  worker thread was still assembling the report and closing its SQLite handle,
  so `tearDown` deleted the temp directory out from under it -
  `PermissionError [WinError 32]`. On Linux the unlink succeeds and the race is
  invisible, **so this was only ever red on our machines and green in CI.** Now
  joins the job future; 14/14 on five consecutive runs.
- **`test_default_config_values` asserted `endswith("reports/artifacts")`** with
  a forward slash - passes in the container, fails on every one of our machines.
  Same Linux-only blind spot. Compares path parts now.
- **`service/cli.py` crashed on the ORDINARY success path.** It formatted
  `inferred_ber` guarding on key presence only, and `adapt_s4` always sets that
  key - it is `None` unless the *statistical* search ran. `f"{None:.4f}"`.
  `rank_collapse.py:158` gets this right; the service copy did not. Same trap
  fixed on `snr_db`.

`test_registry_endpoint` hardcoded `modulations=6, interleavers=3, codes=2`.
Those were a snapshot, not invariants - interleavers went to 4 with the CCSDS
symbol interleaver and codes to 3 with LDPC, so the test broke on precisely the
event the registry exists to make cheap. It now asserts the known plug-ins are
present and that the counts match the lists.

### 5. WHY ALL OF THIS SURVIVED 791 GREEN TESTS

Every one of these bugs lives at a seam between two of us, **and every
integration test stubs the seam.** `make_clean_overrides()` and
`get_deterministic_pipeline()` replace all seven stages with dummies, and not
one test in `tests/service/` or `tests/e2e/` referenced a corpus file - I
checked all ten. `conv_plugin.decode(llrs, s4_raw.code)` had **never once
executed under test.**

Compounded by assertions that cannot fail:
`test_e2e_successful_wav_analysis` asserts
`report["status"] in ("completed", "failed")` - the only two terminal values -
and then checks S0 only. A test named "successful analysis" passes when every
stage after S0 fails.

**So there is now `tests/e2e/test_e2e_real_signal.py`: one real capture, the
real `orchestrate()`, no stubs.** It asserts all seven stages `ok`, that S4
recovers the interleaver period and generators in the capture's own truth file,
that the re-encode BER is under 0.01, that S5 declares its decode a prefix, and
that the run fits 90 s. 14 s. **Checked that it fails on the pre-fix code - 5
failures naming `'CodeStructure' object is not subscriptable`** - because a
regression test nobody has seen fail is not evidence.

### 6. NAIDHRUV - FOUR OF YOUR COMMITS ARE STILL UNMERGED AND TWO FIX THIS

`origin/naidhruv/integration` is 4 ahead, 12 behind. `87776dc` removes the
`tests.fixtures.local_s2` fallback - shipping service code importing from
`tests/`, the same defect I fixed in my own CLI on 7 Sep. **I removed it here
too, independently, before I found you had already done it** - it was also
unreachable, since `pipeline.s2_estimate.estimate` has existed since 1 Sep. And
`fc259ea` cuts the Docker context by 118 MB.

**Your `fc259ea` is safe to merge and my 6 Sep note saying otherwise is wrong.**
I said excluding the corpus and deleting `local_zoo` were "the same decision".
They stopped being the same decision when I ported the CLI to `zoo.bits_only`:
verified `--demo --text` runs clean with `zoo/corpus/` entirely absent.

**Still open:** the RF arm of the CCSDS corpus is untouched and still mine;
`tests/fixtures/local_zoo.py` is still load-bearing for 12 test files and 7
studies; the descramble step between de-interleave and decode is in the CLI but
not in the service's S5 - it is an S6 concern and needs soft-domain handling, and
the RF corpus is `"scrambler": null`, so nothing is wrong today.

**Blocked on:** nothing.

---

## 5 Sep - the concatenated CCSDS chain. Gate met, both arms.

`reports/ccsds_chain.md`, `pipeline/s6_frame/ccsds.py`,
`tests/unit/test_ccsds_chain.py`. Four coding layers, none supplied.

| | unscrambled | scrambled |
|---|---|---|
| layers peeled | conv, viterbi, deint, RS | **scrambler, descramble**, conv, viterbi, deint, RS |
| generators | (0o171, 0o133) OK | (0o171, 0o133) OK |
| interleaver | block(8,12) OK | block(8,12) OK |
| outer code | RS(255,223) OK | RS(255,223) OK |
| printable | **100.0 %** | **100.0 %** |
| payload vs transmit | **byte-exact** | **byte-exact** |
| time | 54.2 s | 55.8 s |

**502 passed, 4 skipped, 1 xfailed.**

**TWO THINGS I HAD WRONG AND HAD TO OVERTURN TODAY.**

**1. The interleaver is INVISIBLE to the rank test in the CCSDS ordering.** Every
earlier study here interleaved the convolutional CODEWORD, whose constraints are
local (span 14), so permuting them moves the collapse to the interleaver period -
that is why S4 has read depth x width off the curve since 29 Aug. CCSDS
interleaves the RS codeword instead, and **a permutation preserves rank over
GF(2)**. RS puts its binary-image constraints at L=2040, far past MAX_PERIOD, so
there is nothing at any searchable L to find.

I did not reason that out. I measured a collapse at 96 on one file and reported
"better than I predicted - the interleaver IS visible". **That was wrong.** Those
deficiencies were the ASCII payload's own structure and they MOVED when I changed
the message: message A gave 96/122/183/192, message B gave 112/147/168/192/196,
and a RANDOM payload gives nothing at any length up to 81,600 bits. My first
version of the candidate search ranked off that curve and could never have
worked. Fourth time this week that reading a curve where only a functional test
can decide produced a wrong answer. The interleaver is now found functionally
with the RS decoder as sole judge.

**2. The scrambler chicken-and-egg is broken.** `recover_scrambler` needs the
code's parity check and the scrambler hides the code - open in HANDOFF since
2 Sep. But an additive scrambler is periodic, so for a shift P that is a multiple
of both its period and the symbol size, `r[n] XOR r[n+P] = c[n] XOR c[n+P]` - the
scrambler cancels and the XOR of two codewords is a codeword. Search P with the
RANK test on the self-difference, which needs no parity check, and the code from
the difference unlocks the rest. That is why the scrambled arm peels four layers.

**Cost, and the one number that is a problem.** Viterbi is 80 % of the 55 s and
it is commpy being pure Python (163 kbit takes 167 s), so the chain caps input at
48,000 coded bits. The interleaver grid nearly killed it: full RS blind_recover
is ~2.2 s per candidate, so reaching 8x12 at grid index 190 would cost **421 s**.
A cheap screen - one RS profile at 8 byte alignments, early exit on the first bad
block - rejects a wrong candidate in **0.038 s**, taking the 465-pair grid to
**16.9 s with exactly one hit, the true (8,12), and no false positives**.

**DHERAJ - YOUR CFO FIX IS RIGHT, AND IT IS INCOMPLETE.** Your root cause is
better than my report: the demean before the FFT nulled the DC bin, which is
exactly where the line sits at zero CFO. Verified across the corpus at >=10 dB:

| scheme | files | \|CFO err\| >= 100 Hz |
|---|---|---|
| bpsk, qpsk, 8psk, 16qam | 112 | **0** |
| **2fsk** | 28 | **28** |
| **4fsk** | 28 | **28** |

Your "112/112 clean files" is exactly the four LINEAR schemes. **All 56 FSK files
still report 25,000 Hz where the truth is 0** - the same rate/2 alias. It is not
cosmetic: I measured recovery with and without the estimate applied, and

    2fsk 20 dB / 13 dB   survives it (recovers either way)
    4fsk 20 dB / 13 dB   RECOVERS without it, FAILS with it

So the estimator is still blind for FSK and it costs us 4-FSK outright. My chain
survives because it treats CFO as a hypothesis and tries the null first, but any
orchestrator that trusts S2 loses 4-FSK.

**And I owe you one.** When I saw `models/classifier.txt` show a checksum
difference on checkout I called it "a phantom CRLF diff, not a content change"
and moved on. You found it was real - autocrlf breaking LightGBM's line parser
with "Model format error, expect a tree here". I saw the symptom and misjudged
it. Your `.gitattributes` fix is the right one.

**ASK: a concatenated profile in the corpus.** The zoo has conv-only and RS-only
streams; CCSDS is the only layer of the declared envelope with no corpus file, so
this runs against `local_zoo.make_ccsds_stream`. Also note my fixture is NOT
bit-for-bit CCSDS 131.0-B - the blue book randomises BEFORE the convolutional
encoder and interleaves SYMBOLS (bytes, depth I in 1..8), where I follow the
Command Center's stated order and interleave bits. Fine for testing whether four
layers peel; not a standards claim.

### 7. THE FULL SUITE, RUN FOR THE FIRST TIME THIS WEEK - AND S3 IS FLAKY ON A CLOCK

**678 passed, 1 failed, 4 skipped, 1 xfailed in 27m14s.** I had been quoting
"the CCSDS suites are green" and calling the full run too slow to bother with.
It was worth 27 minutes.

**ANVITH - `test_s3_runs_on_blind_estimates_with_no_labels_in_the_path` is
flaky: 2 passes in 8 fresh processes.** Not my branch - `search.py`,
`lockcheck.py`, `linear.py`, `s2_estimate.py` and the test file are all
bit-identical to `origin/main` on this branch; I checked before saying so.

I first called it a deterministic failure and said main was red. **Both wrong** -
the first two samples agreed and I generalised from them. Inside one process it
is perfectly stable (5 calls, 5 x `ok`); the variation is BETWEEN processes.

**Mechanism, measured.** `receive_best` enforces `SEARCH_BUDGET_S = 20.0` via a
deadline checked at `search.py:425` and `:485`. Same signal, only the budget
varied:

| `budget_s` | status | modulation | exhausted | elapsed |
|---|---|---|---|---|
| **20.0 (default)** | ok | qpsk | False | **21 437 ms** |
| 5.0 | low_confidence | **8psk** | True | 6 877 ms |
| 30.0 | ok | qpsk | False | 21 375 ms |

**The right answer costs ~21.4 s against a 20.0 s budget.** It passes only when
the overshoot lands between two deadline checks. When the budget bites, S3
returns **8psk for a QPSK signal** - and Anvith's evenness guard catches it and
refuses to say `ok`. **That guard is doing its job and must not be loosened to
make the test green**; the defect is upstream, in the search not reaching qpsk
inside the budget.

**Why this outranks one flaky test: the core-lock gate is "under 90 s, twice
consecutively".** A stage whose correctness depends on how much wall clock it
gets will pass or fail that gate for reasons unrelated to the code. And the
OneDrive measurement below means the margin that exists on a quiet machine is
not there on the demo machine. Written up for Anvith with a reproduction.

### 8. Two of my own numbers were stale, and one of my findings was wrong

Re-audited Naidhruv against his CURRENT tip `5530a2b`, not the `a9602d6` I
wrote up on 6 Sep. The registry bug is still real and still reproduces
(`{'modulations': 0, 'interleavers': 0, 'codes': 0}` at S3 time), but
**`orchestrator.py:675/725` are now `693/742`, and his branch is 24 commits
behind main, not 22.** Corrected in what I sent him.

And I briefly concluded S4 could not handle non-zero start offsets, which would
have sent Dheeraj chasing a generator bug that does not exist. **The corpus
disproved it**: all six clean `zoo/corpus/bits_only/` files carry non-zero
offsets (72, 34, 78, 30, 44, 21) and all six recover. My sweep had changed two
variables at once. The true claim is narrower and is item 6 above.

### 9. THE GATE IS NOT AT RISK, AND THE ONEDRIVE THEORY WAS WRONG. BOTH MEASURED.

**The core-lock number, on `main` at `100a30c`, twice consecutively:**

| | run 1 | run 2 |
|---|---|---|
| `--demo --text`, OneDrive running | **25.8 s** | **24.7 s** |
| same, OneDrive stopped | 22.7 s | 21.6 s |

Budget is 90 s. Both `ok` at confidence 0.95, payload printable 100 %. **That is
a 3.5x margin on the noisy machine.** My 6 Sep note said the gate "cannot be
measured honestly on a machine in this state" - it can, and it passes. Caveat
that matters: this is S4->S6 from bits. **The full S0->S6 number cannot be
measured at all yet, because the orchestrator is Naidhruv's and still cannot
run S3 or S5.**

**THE STALE-COPY THEORY IS DEAD. Do not spend time on it.**
`OneDrive\Desktop
aaya` is already gone and `OneDrive\Desktop\SIH` contains
**zero entries** - an empty Files On-Demand placeholder (reparse tag
0x9000e01a), not a real copy. Deleting it frees nothing and would only remove
it from the cloud. The churn is `OneDrive\Desktop` holding **~250 000 files
across a dozen unrelated projects** (RAG App 50k+, lychee 36k, HA-QCNN 36k,
LLM Red-Team Lab 32k, BlockVerify 22k). That is other work and it is not ours
to delete. HANDOFF's instruction rests on a premise that is no longer true.

OneDrive is nonetheless real: **112 % of one core, sustained, on an idle
machine** (22.47 CPU-s in a 20-s window). Cumulative 83 600 s (4 Sep) ->
158 313 s (6 Sep) -> **202 906 s (7 Sep)**. Stopping it buys ~12 %. Worth doing
before a timed run; not worth deleting anything for.

**AND THE PREDICTION I MADE FROM IT WAS WRONG.** 21.4 s x 0.88 = 18.8 s should
have fitted Anvith's 20 s budget and killed his flake. It did not:

| | passed | failed |
|---|---|---|
| Anvith's S3 test, OneDrive running | 2 | 6 |
| same, OneDrive stopped | 2 | 4 |

**4 passes in 14 runs either way.** The search's own run-to-run variance is
wider than the headroom, so the flake is intrinsic, not load-induced. **Nobody
can make it go away with a quiet machine - it has to be fixed in the code.**
That raises the priority of his item rather than lowering it, and it is in what
I sent him.

**Blocked on:** nothing.

---

## 6 Sep - both asks to Dheeraj landed. One is verified clean, one is now built
## against, and there is a hole under the first that his report does not cover.

`main` moved eight commits while this branch sat unpushed; merged it, no
conflicts, 657 tests collect. Branch is `nehal/6sep` off `nehal/rs-runtime`.

### 1. DHERAJ - YOUR FSK CFO FIX IS RIGHT. I RE-MEASURED IT MYSELF.

`55cb628`, verified the same way I measured the bug on 5 Sep: through
`estimate()` itself, per scheme, against `cfo_norm * fs` from the truth JSON,
all 252 corpus files. **At >= 10 dB: 168 of 168 files inside 100 Hz, zero
failures.**

| scheme | files >=10 dB | fail | worst |
|---|---|---|---|
| bpsk, qpsk, 8psk, 16qam | 112 | **0** | 0.0 Hz |
| 2fsk | 28 | **0** | 54.9 Hz |
| 4fsk | 28 | **0** | 84.5 Hz |

Your 54.9 and 84.5 reproduce exactly on my side. The per-scheme reporting is
what I asked for and it is the right change - it is what makes the next two
paragraphs visible instead of invisible.

**THE HOLE: BELOW 10 dB, 28 OF THE 84 FSK FILES ARE STILL WRONG, AND IT IS NOT
YOUR ESTIMATOR.** (84 = 42 per FSK scheme, 6 SNRs x 7 seeds; the 28 are every
one at 4 and 8 dB. My 5 Sep note said "56 FSK files" - that was the >= 10 dB
slice, 28 per scheme, and it is not the denominator here.) The same run,
extended to the whole corpus rather than the >= 10 dB slice:

| scheme | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB |
|---|---|---|---|---|---|---|
| 2fsk worst err | **25 000 Hz** | **25 000 Hz** | 54.9 | 30.1 | 18.3 | 18.5 |
| 4fsk worst err | **25 000 Hz** | **25 000 Hz** | 84.5 | 47.1 | 28.8 | 31.6 |
| 8psk worst err | **9 675 Hz** (7/7) | **3 482 Hz** (2/7) | 0.0 | 0.0 | 0.0 | 0.0 |

Every one of the 28 FSK files at 4 and 8 dB reports the identical
`symbol_rate/2` alias - the exact shape of the bug you just fixed.
**`estimate_cfo_fsk` is never called on them.** `estimate()` routes on `std(|x|)/mean(|x|) < 0.25`, and I measured
that ratio per file:

| SNR | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB |
|---|---|---|---|---|---|---|
| FSK envelope CV | 0.377 | 0.264 | **0.215** | 0.155 | 0.125 | 0.070 |
| routed as | linear | linear | constant-envelope | c-e | c-e | c-e |

**That statistic is measuring SNR, not envelope structure.** For a
constant-envelope carrier in AWGN the envelope CV is ~1/sqrt(2*SNR): predicted
0.224 at 10 dB against 0.215 measured, 0.281 at 8 dB against 0.264. The
modulation contributes nothing to it. So the threshold 0.25 is in effect
"SNR > 9 dB", the fix passes at 10 dB by **0.035 of margin in a quantity that
moves monotonically with noise**, and when it flips there is no failure signal
at all - just a confident 25 kHz. My chain survives it because
`search.receive_best` always carries `cfo = 0` as a candidate, but an
orchestrator that trusts `S2Result.cfo_hz` loses 4-FSK below 10 dB exactly as
it did last week.

Not filed as a defect in your column because 10 dB may well be the declared S2
floor - but if it is, that floor belongs in the report next to the 168/168, and
the routing statistic should not be the thing that enforces it silently.

### 2. THE REAL CCSDS ORDER NOW PEELS. `zoo/ccsds.py` was worth asking for.

`bcd0a88` gave me a generator built to the standard order. Run my 5 Sep chain
against it unchanged, depths 1 and 4:

    status = partial | stages = conv, viterbi | G = (0o171, 0o133) correct
    reason = "no de-interleaving produced a Reed-Solomon codeword"

**Two of four layers.** A true statement about a search that could not have
succeeded. Both assumptions broke at once, and neither is tuning:

- the randomiser is INSIDE the convolutional code, so it survives Viterbi.
  `recover_scrambler` cannot touch it - it needs a parity check to take a
  syndrome against, and the only code left after Viterbi is RS, whose
  constraints sit at L = 2040, far past anything the sweep reaches.
- the interleaver permutes BYTES. No bit-level (depth, width) can undo it.

Fixed with two bounded additions, both judged by the RS decoder and nothing
else. `CCSDSSymbolInterleaver` is a fourth registered family whose
`rank_signature()` returns **0** - "the sweep will not find this one" - because
returning a row length there would be a number the orchestrator would act on
and it would be false. `STANDARD_RANDOMISERS` is the same move
`rs_code.STANDARD_PROFILES` already makes: try the published profiles of the
declared envelope, decline anything that matches none. The null hypothesis is
tried first, so the 5 Sep path pays about one extra confirmation and cannot
change the answer it already gave.

**Result - every standard depth, blind, payload byte-exact:**

| depth I | 1 | 2 | 3 | 4 | 5 | 8 |
|---|---|---|---|---|---|---|
| status | ok | ok | ok | ok | ok | ok |
| interleaver found | - (I=1 identity) | 2 | 3 | 4 | 5 | 8 |
| payload | exact | exact | exact | exact | exact | exact |

`reports/ccsds_chain.md` (extended), `tests/unit/test_ccsds_real_order.py`
(16 tests, 84 s). Both new primitives are pinned against **Dheeraj's**
implementation rather than a second copy of my own assumptions:
`symbol_interleave` reproduces `zoo.ccsds.ccsds_interleave` bit for bit at all
six depths, and `additive_keystream` reproduces `zoo.bits_only.lfsr_scramble`
bit for bit with its period **measured** at 255 rather than assumed from the
degree - this repo has already shipped a polynomial mislabelled as
maximal-length once.

I also corrected the 5 Sep report rather than leaving it to be misread: its
table is now explicitly labelled as the Command Center's order, because "the
concatenated CCSDS profile decodes byte-exact" was true of a chain that is not
the standard's.

### 3. Merge break, fixed. `reports/end_to_end_study.py`

`anvith/s3-robustness` deleted `tests/fixtures/rf_channel.py` as promised.
Only one file still imported it - the tests on `main` were already ported -
and it is now on `tests.fixtures.corpus.synth`. **The channel implementation
changed underneath it**, so `reports/end_to_end.md`'s numbers were measured by
code that no longer exists and have to be re-measured before they are quoted
again. Smoke-tested at 16 dB seed 1: raw BER 0.0, recovered, interleaver
correct, text readable, printable 0.9993 against the 1.000 previously
published - a small delta, and exactly why the re-run is not optional.

### 4. MY 5 SEP FIX PUT A 268-SECOND FUNCTION IN THE CHAIN AND EVERY TEST PASSED

Found by reading the suite's `--durations`, not by a failure. The scrambled
CCSDS arm took **364 s** tonight against the **55.8 s** in my own report. First
two hypotheses were both wrong and both worth recording: it is not my 6 Sep
change (measured in isolation, `_peel_symbol_layers` costs **2.4 s**), and it is
not the machine (the unscrambled arm is 50 s tonight against 54.2 s published -
unchanged).

It is `b431082`, my last commit of 5 September. Moving `SCREEN_ROW_LEN` from 14
to 60 was **right** - 14 is the span of rate-1/2 K=7 and nothing else, so the
screen was rejecting most of the declared envelope. But the condition on the
other side of it was still `deficiency > 0`, and at L=60 that is true of
everything:

| `SCREEN_ROW_LEN` | shifts searched | passing the screen |
|---|---|---|
| 14 (before the fix) | 255 | **1** |
| 60 (after the fix) | 255 | **255** |

Every shift then paid for a full `blind_recover`. **`find_scrambler_period_blind`
alone: 268 s - past the 90 s core-lock budget for the whole seven-stage
analysis, in one function.** I shipped that last night and wrote a commit
message about correctness without timing what I had done.

Why no better row length exists: the sum of two codewords is a codeword at
EVERY shift that is a whole number of symbols - that is the premise the method
rests on - so code structure is present at every shift and only its SIZE picks
out the true one. At L=14 the code's deficiency is 1 and the residual scrambler
buries it; the old screen worked by sitting exactly on that margin. Measured at
L=60: **254 wrong shifts all at deficiency 16, the true shift at 24, zero
overlap.**

So the screen now **ranks instead of thresholding** - sweep all 255
deficiencies (~0.1 s), take the median as the floor, and pay for a recovery
only above it, capped at 6 candidates. No knowledge of n or m, the expensive
oracle still makes every claim, and a stream with no scrambler gives a flat
profile and a cheap honest no.

| | before | after |
|---|---|---|
| `find_scrambler_period_blind` | 268.1 s | **5.1 s** |
| scrambled arm end to end | 364.3 s | **48.7 s** |
| `test_ccsds_chain.py` | 640 s+ | **205 s** |
| answer | shift 510, `(0o171, 0o133)` | **identical** |

`b431082`'s correctness fix is kept in full - still L=60, still covers every
code in the envelope.

**The guard that was missing is now there.**
`test_the_scrambler_screen_actually_screens` asserts the search returns 510 AND
finishes inside 60 s. The screen had a test for the half of its job that fails
loudly - "never a cheap yes" - and none for the half that fails silently. A
screen that admits everything is not a screen, and a green suite will not tell
you. Only the clock knew. Fourth time this week that a number I did not measure
was a number I had wrong.

**This also means the OneDrive note below did NOT cause the 364 s** - I checked
that first and it was the wrong tree. Both findings are real and they are
independent.

### 4b. DHERAJ - THE CORPUS RANDOMISER IS NOT THE CCSDS RANDOMISER

Checked the constant against the blue book rather than against our own code.
`zoo/bits_only.py` has `CCSDS_SCRAMBLER = 0o435` under a comment naming
h(x) = x^8+x^7+x^5+x^3+1. Those are different polynomials:

    0o435 = 285 = 0x11D = x^8 + x^4 + x^3 + x^2 + 1   <- RS GF(256) field poly
    0o651 = 425 = 0x1A9 = x^8 + x^7 + x^5 + x^3 + 1   <- CCSDS 131.0-B

The reciprocal of 0o435 is 0o561, so no convention reconciles them. 0x11D is
the Reed-Solomon field polynomial - an extremely easy thing to reach for while
writing an RS-and-randomiser generator.

**Mislabel, not malfunction.** Both are primitive of degree 8 - I measured both
periods at 255 - so the corpus is a valid additive scrambler, self-consistent
between your generator and my receiver, and no recovery number moves.

**But I had copied the constant into `STANDARD_RANDOMISERS` without checking
it**, and that table exists precisely to catch a REAL downlink. A standard-
profiles table whose standard entry is not the standard declines the one stream
it was written for. Mine carried that error for about an hour today. Both
polynomials are now in the table, blue book first, pinned by a test that
asserts the tap sets explicitly.

Your call which way to fix it: correct the comment (cheap, nothing moves) or
correct the constant (regenerate `zoo/corpus/ccsds/` and re-measure anything
against it). My chain works either way. What should not survive is a corpus
file labelled CCSDS-conformant that is not - that is the exact claim I spent
5 Sep being careful *not* to make about my own fixture.

**ANSWERED 7 SEP - `9b4c524` corrected the CONSTANT and regenerated the
corpus.** `zoo.bits_only.CCSDS_SCRAMBLER` is now 0o651, so the generator and
the blue book agree and the corpus is CCSDS-conformant on this layer for real.
My receiver follows it: `CORPUS_RANDOMISER` is renamed `LEGACY_ZOO_RANDOMISER`
and demoted in `STANDARD_RANDOMISERS` to what it actually is - not a standard,
the RS field polynomial, carried only so a pre-`9b4c524` capture still
descrambles instead of reading as noise. Tried last, RS still the judge.

**The pin did its job.** `test_known_randomiser_matches_the_generators_lfsr`
asserted `CORPUS_RANDOMISER == CCSDS_SCRAMBLER` against Dheeraj's live constant
rather than a second copy of my own, so the change surfaced as a red test on
merge (`assert 285 == 425`) instead of as a silent descramble-to-noise. That
was the whole point of pinning against their implementation, and it is the
first time this week a cross-lane change announced itself.

Dheeraj also took the `.gitattributes` line in the same commit, so my version
of it was dropped in the merge in favour of theirs - same rule, `*.bin binary`,
verified still `binary: set` after resolving.

### 4c. AND FIXING THE MISLABEL BROKE MY GATE, FOR A REASON WORTH THE WHOLE DAY

**The 6 Sep gate now xfails, and it is not the test that is wrong.** Merging
`9b4c524` turned `test_the_real_transmit_order_peels_to_a_byte_exact_payload`
red at both depths, with the worst possible shape:

    status = ok    stages = conv, viterbi, reed-solomon
    rs_params = RSParams(n=255, k=223, offset=0, blocks_checked=8,
                         errata_rate=0.0)
    printable_fraction = 0.3957        <- garbage
    payload == expected : False

Eight blocks, offset 0, **zero corrections** - the strongest confidence signal
the RS layer can produce - on a payload that is wrong. `derandomise` is absent
from `stages`: the chain accepted the NO-RANDOMISER hypothesis and never tried
one.

**Root cause, measured, and it is structural rather than bad luck.** The CCSDS
randomiser is an LFSR of period 255 BITS. An RS(255,223) block is 255 bytes =
2040 bits = **exactly eight whole periods**, so every codeword is XORed with the
same 255-byte pattern K. I tested K itself:

| keystream | K as an RS(255,223) block |
|---|---|
| `0o651`, the real CCSDS one | **decodes, errata = 0 - K IS a codeword** |
| `0o435`, the old mislabel | rejects |

RS is linear over GF(256). If K is a codeword then for any codeword C,
**C + K is a codeword, exactly.** So "RS decoded every block at errata_rate
0.0" carries *no information whatsoever* about whether the randomiser came off.
The randomiser maps the code onto itself.

**This kills the premise I built 6 Sep on.** I wrote that both new primitives
were "judged by the RS decoder and nothing else". For the real standard's
randomiser that judge is blind, and reordering the hypotheses does not help:
applying the randomiser to an un-randomised stream also yields codewords, so
the ambiguity is symmetric. **Only the payload can separate them.**

And the 6 Sep gate passed only because `0o435` happened to break the code. I
was being marked by an examiner who could not read - which is exactly the
"green suite tells you nothing" failure I wrote up twice this week, arriving a
third time in a form no timing check would have caught.

Pinned by `test_the_ccsds_randomiser_is_invisible_to_the_reed_solomon_decoder`
(passing - it asserts the property in both directions) and the gate is
`xfail(strict=True)` so it cannot be quietly declared fixed.

**FIXED, and the fix is both of the options I was weighing, because either one
alone reproduces the bug in a new costume.** A payload discriminator on its own
answers the random-payload case with no evidence to answer from - confident
garbage again, just chosen differently. "Always ambiguous" on its own throws
away an answer the evidence does support and loses the blind-in/message-out
demo. So:

1. `_peel_*` now return **every** surviving randomiser instead of the first.
   First-accept was the actual defect; RS was never able to rank them.
2. `_resolve_randomiser` decides on the PAYLOAD, and only when the evidence is
   decisive. RS acceptance stays a hard necessary condition - the payload never
   admits anything, it only chooses among what RS already accepted.
3. When the evidence ties, the chain returns `partial` with
   `randomiser_ambiguous=True` and both candidates named. It never guesses.

**The measure is byte entropy, not the printable fraction this repo reaches for
elsewhere, and that choice is the point.** Printability asks "is this text",
which a real downlink often is not. Entropy asks "did removing this layer expose
structure or destroy it" - and on a payload that was random to begin with it
CANNOT separate the hypotheses, so it ties and forces the honest answer instead
of inventing one. Measured, both depths:

| payload | `ccsds-131.0-B` | no randomiser | margin | result |
|---|---|---|---|---|
| text | **4.07** b/byte | 7.90 | **3.83** | resolved, payload byte-exact |
| random | 7.89 | 7.88 | **0.01** | `partial`, declined |

Threshold `PAYLOAD_ENTROPY_MARGIN = 1.0` b/byte sits ~380x clear of the tie and
~4x clear of the decision, so it is not balanced on a margin the way the L=14
scrambler screen was. Both depths peel byte-exact again, depth 4 still recovers
the interleaver, and `test_a_random_payload_is_declined_rather_than_guessed`
pins the half that must fail.

**Known limit, stated rather than discovered later: a real downlink whose
payload is compressed or encrypted will tie, and this chain will return
`partial` on it.** That is correct - the information is genuinely not in the
stream - but it means the randomiser cannot be settled blind for such a mission.
CCSDS 131.0-B mandates the randomiser, so the profile itself is the missing
prior; wiring that in is a deliberate "assume the standard" step and I have not
taken it unilaterally. **DHERAJ / NAIDHRUV: that is the open question, not the
correctness of the chain.**

Everything else on the branch was unaffected throughout: the symbol interleaver,
the scrambler screen ranking, all six depths, and the 268 s -> 5.1 s fix.

**And one line of `.gitattributes`, because it is the autocrlf hole again.**
Your fix covers `*.wav`, `*.npy` and the three `models/` files. It does not
cover `*.bin`, and the new corpus ships eight `.payload.bin`:

    git check-attr text binary -- zoo/corpus/ccsds/...payload.bin
    text: unspecified   binary: unspecified

so git falls back to the content heuristic, and those files are pure ASCII with
**zero NUL bytes** - it will call them text. **Nothing is corrupted today**: I
checked all eight against their blobs and all match, because they also contain
zero newline bytes, so the conversion is a no-op. But `payload_text` is
caller-supplied and the first payload with a newline in it gets mangled on
every Windows checkout - the exact failure mode `models/classifier.txt` already
cost us. `*.bin binary` closes it.

### 5. NAIDHRUV - THE SERVICE NEVER REGISTERS THE PLUG-INS. S3 AND S5 CANNOT RUN.

Audited `naidhruv/integration` (a9602d6) tonight because the core-lock gate
needs the orchestrator and it has never been run against current `main`. This
is the most severe thing in the repo right now and it fails **silently**.

The registry is populated by import side-effect - that is my design and it is
in `registry/protocols.py`: `register_modulation()` runs when
`pipeline.s3_receive` is imported, `register_code()` when
`pipeline.s5_decode.conv_code` and `rs_code` are. Grepped every `.py` in his
`service/` and `eval/`; there are exactly four pipeline imports:

    orchestrator.py:87   pipeline.s0_ingest.ingest
    orchestrator.py:95   pipeline.s1_detect.detect
    orchestrator.py:125  pipeline.s4_recover.rank_collapse.blind_recover
    orchestrator.py:133  pipeline.s6_frame.payload.extract_text

None of them registers a modulation or a code. Reproduced with his exact import
set:

    at service start / S3 time : {'modulations': 0, 'interleavers': 0, 'codes': 0}
    after his lazy S4 import   : {'modulations': 0, 'interleavers': 4, 'codes': 0}

- `orchestrator.py:675` `MODULATIONS.get(scheme)` -> None -> **S3 never runs**
- `orchestrator.py:725` `CODES.get("conv")` -> None -> **S5 never runs**
- `main.py` `GET /registry` -> **0 / 0 / 0**, and that is the endpoint the
  31 Aug gate reads. It would report an empty system while every unit test in
  the repo passes, because the tests import the plug-in modules directly and
  the service does not.

Four import lines fix it. What matters more is the assertion after them: a
service whose registry reports zero should **refuse to start**. This is exactly
the failure class I built the registration-time protocol check for - "a plug-in
missing a method should fail when the module is imported, not three stages into
an analysis in front of a judge" - and it walked straight past it, because
nothing was imported at all.

**His branch is also 22 commits behind `main`** (base `c3ba631`, 4 Sep 17:09).
It predates both S2 CFO fixes, all of Anvith's `lockcheck.py` and `search.py`,
Dheeraj's classifier fix and the CCSDS corpus, and my 4-6 Sep work.

**And `orchestrator.py:658` trusts S2's single CFO** and calls
`plugin.receive()` directly rather than `receive_best`, which is the "any
orchestrator that trusts S2 loses 4-FSK" case I wrote on 5 Sep. `search.py`
postdates his branch point so this is staleness, not an oversight - but it is
the call to make on the rebase. Minor, same file: `orchestrator.py:114` imports
`tests.fixtures.local_s2`, deleted on `main` - verified `ImportError`, so that
fallback is dead.

### 6. ANVITH - I AUDITED YOUR LANE AND FOUND NOTHING, WHICH IS ALSO A RESULT

Recording it so "no finding" is distinguishable from "not checked".
`S3Result.as_stage_result()` matches Naidhruv's `contracts.StageResult` shape
exactly, and the status vocabularies line up - S3 emits
`ok | low_confidence | failed`, his `StageStatus` carries those plus
`out_of_envelope`. No validation break at the seam. `receive_best` is in
`pipeline.s3_receive.__all__`, so it is discoverable and the orchestrator's not
using it is Naidhruv's staleness rather than a discoverability problem.

The gap I would prioritise is his own declared one: 16-QAM and FSK have not
been taken through to S4, while we claim six modulations end to end and the
junction study covers three.

### Still open, stated plainly

- **The RF arm of the CCSDS corpus is untouched, and it is mine.** The eight
  WAVs in `zoo/corpus/ccsds/` have not been driven from the waveform. Dheeraj's
  note on `bcd0a88` says a full RS decode through the real channel needs a
  byte-alignment search across a non-conv-aligned offset from the RRC filter's
  edge transients. That is frame synchronisation, it is the same gap as the
  absent sync marker, and it is the next thing.
- **The randomiser phase is assumed to be 0.** Period 255 is coprime with both
  the 8-bit symbol and the rate-1/2 code, so a capture not starting on the
  randomiser's first bit descrambles to noise. Holds here only because the
  convolutional encoder starts on that bit.
- **`tests/fixtures/local_zoo.py` is still alive and is now overdue.** My own
  standing instruction in `docs/HANDOFF.md` is to delete it the moment the zoo
  lands, and the zoo has now landed in full - including the CCSDS profile that
  was its last excuse. Counted rather than estimated: **12 test files, 7
  studies, and one pipeline module**. The two generators are genuinely
  independent implementations - neither imports the other, only comments
  reference across - which is exactly the two-sources-of-truth risk I wrote
  that instruction about. Not done today: it is a day of work with real
  coverage at stake, and it should be a decision rather than a drive-by.
- **`pipeline/s4_recover/cli.py:167` imports `tests.fixtures.local_zoo`**, and
  that one is not just a cleanup item. It is shipping pipeline code reaching
  into `tests/`, on the `--demo` path - which is both the plan's "if only 48
  hours remain" floor AND the container's default `CMD`. It works today:
  `.dockerignore` does not exclude `tests/`, so `COPY . .` carries the fixture
  into the image. But it means **deleting `local_zoo.py` breaks the image's
  default command**, and the two jobs have to be done together.

  I started to point it at `zoo.bits_only` and stopped, because it is not the
  small change it looks like. `zoo.bits_only.make_stream` has **no
  `payload_text` and no `mean_burst`**, and its `Truth` carries the interleaver
  as a nested dict rather than `.period` / `.depth` / `.width`. So the port
  either drops `--text` - which is the "blind in, message out" demo, the one
  in the pitch - and `--burst`, or it needs those two parameters added to
  Dheeraj's generator first. **DHERAJ: that is the ask.** Two keyword arguments
  on `make_stream`, and then `local_zoo` has nothing left that the zoo cannot
  do. Until then the CLI keeps its `tests/` import and it is written down here
  rather than discovered on 8 September.

- **MOVING THE REPO OFF ONEDRIVE DID NOT STOP ONEDRIVE, and this affects
  tomorrow's timed gate.** Measured tonight while the suite was running:
  OneDrive.exe burned **19.0 CPU-seconds in a 20-second window** - a full core,
  continuously - against pytest's own 19.7 in the same window. It is matching
  the test suite 1:1. Cumulative CPU on the process was **158,313 s**, against
  the 83,600 s recorded in HANDOFF on 4 September. And the suite itself
  averaged only ~17 % of one core over 37 minutes wall, so it is not CPU-bound;
  it is waiting.

  I cannot prove the churn is the two stale copies - I did not isolate it, and
  a `du` over them did not finish in five minutes, which is its own data point.
  What is certain is that HANDOFF says to delete `OneDrive\\Desktop\\raaya` and
  `OneDrive\\Desktop\\SIH` once `C:\\dev\\raaya` is trusted, both are still
  there, and **the core-lock gate is "under 90 s, twice consecutively"** - which
  cannot be measured honestly on a machine in this state, repo location
  notwithstanding. My own fault in part: I ran the old SIH suite once tonight
  before finding the live clone, which wrote `.pytest_cache` into the synced
  folder. Deleting the two copies is a destructive step and I have not taken
  it.

**NAIDHRUV - one thing for the 6 Sep clean rebuild, measured not guessed.** The
Docker build context is **124 MB, of which 113 MB is `zoo/corpus/`** (93 MB rf,
8.3 MB the new ccsds files) plus 5.5 MB of `models/` training CSVs. None of it
is needed at runtime - `models/classifier.txt` is, the datasets are not, and
the corpus is test input. That is 91 % of the context shipped to the daemon and
baked into a layer on every build. Your call and your file; I have not touched
it, because excluding `zoo/` would break the `--demo` CMD above and the two
decisions are the same decision.

**Blocked on:** nothing.

---

## Naidhruv — contract · service · UI · integration

**Landed 9 Sep.** v1.0 Freeze: CCSDS Real-Signal Synchronization & Production Budget Lock.

- **CCSDS Sub-byte Synchronization**: Fixed sub-byte bit phase search ($0..7$) in `peel_ccsds_outer` over post-Viterbi bitstreams. Verified on canonical real signal `ccsds_qpsk_20dB_depth1_9001.wav` (locks at `shift=4`).
- **Real Randomiser Synchronization**: Exploits the algebraic property that the CCSDS 131.0-B randomiser period ($255$ bytes) divides the RS codeword length ($255$ bytes) and interleave group length ($I \times 255$ bytes). Aligning to codeword and group boundaries locks the LFSR phase deterministically to seed `0xFF`.
- **Arbitrary Depth > 1 Interleave Group Alignment**: Implemented bounded group boundary search for symbol interleaving $I \in [2, 3, 4, 6, 8]$. Decodes all $I$ parallel codewords and validates against Shannon payload entropy ($< 6.5$ bits/byte) to reject false positives.
- **Production S5 Decode Budget**: Locked `S5_DECODE_MAX_BITS = 32_000` in `service/orchestrator.py`. Mathematical analysis and empirical sweep proved $30,500$ bits is the exact minimum required to assemble a complete depth-4 group after an arbitrary $881$-byte offset; $32,000$ provides safe margin with $25.1$s S5 runtime (total $28.1$s), comfortably within the $90$s envelope.
- **Canonical Validation**:
  - `depth-1` (9001): PASS (1,561 bytes, exact truth match at byte offset 223).
  - `depth-4` (9002): PASS (892 bytes, exact truth match at byte offset 180).
  - Canonical suite: 6/6 QPSK/8PSK/16QAM depth-1 and depth-4 files match truth payload 100%. Depth-8 files (9007, 9008) execute S0-S6 within envelope ($< 51$s) but exceed 32k budget for full group assembly.
- **Test Suites**:
  - `tests/unit/test_ccsds_real_order.py`: 23/23 PASSED (including 3 new regression tests for sub-byte shift, arbitrary codeword start, and depth-4 arbitrary start).
  - `tests/e2e/test_e2e_real_signal.py`: 6/6 PASSED (7 subtests passed, runtime ~39s).
  - Web UI: `npm test` 17/17 PASSED, `npm run build` PASSED.

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

### 8 Sep, later — synced dhiraj/zoo-v0 with main before opening the 7-8 Sep PR

`dhiraj/zoo-v0` had drifted 53 commits behind `origin/main` (PR #17 had already
carried the earlier zoo work in; the 7-8 Sep commits — S0 format sniffer,
`random_case`/`make_rs_stream` port, the reproducibility lock — were sitting on
top of that, unmerged). Rather than open a PR against a stale base, merged
`origin/main` in first: Anvith's S3 LDPC decode path, Nehal's S3/S6 CCSDS
integration fixes, and the new service/eval/web layer. Clean auto-merge, no
conflicts, verified with a dry run before committing for real.

Ran the full suite against the merged result, not just my own files:
**771 passed, 2 xfailed** (my pinned 4FSK layout-detection gap, plus one from
the newly-merged S3 work), zero failures, ~28 min. Pushed as `d5b4238`.

No PR opened yet — no `gh` CLI in this environment. Compare view is at
`https://github.com/NaidhruvK/wavSIH26/compare/main...dhiraj/zoo-v0`.

### 8 Sep, later still — Naidhruv's corpus-missing-from-image report: real, but not on main

Naidhruv reported the Core Lock Docker image has no `zoo/corpus/*.wav`, failing
`test_reads_own_zoo_wav` and `test_fs_matches_truth_json`. Traced it: commit
`fc259ea` ("chore: reduce Docker build context") on `origin/naidhruv/integration`
adds

```
zoo/corpus/
models/dataset_*.csv
```

to `.dockerignore`. That commit landed 7 Sep, **after** his last merge into
`main` (PR #16) — so it never reached `main`, it's only live on his own branch.

Verified against current `main` (`71b0f2c`) with a real Docker build (daemon
confirmed up, no cache reuse): 252 corpus files present at
`/app/zoo/corpus/rf/` in the built image, and both named tests pass inside the
container. So this isn't a `main` defect — it reproduces only on his branch.

The underlying tension is real, though, not just a stray line: that
`.dockerignore` change is a reasonable instinct (118 MB of test fixtures
shouldn't ship in the production image), but if Core Lock's acceptance gate
runs `pytest` inside that same built image, shrinking the image and running
the corpus-dependent unit tests inside it are in direct conflict. Not my file
to fix (`.dockerignore`/Dockerfile is Naidhruv's) — relaying the exact commit
and the reproduction so he can pick the resolution (multi-stage test layer,
mount the corpus in at test time, or scope the exclusion narrower).

### 9 Sep — demo freeze day: guard pass on S0/S1/S2/classify, no new code

Today's row: read my own stages for anything that can throw, guard commits
only, nothing else. Matches Anvith's identical pass on S3 this morning
(`08832de`/`fab99be`).

Walked `pipeline/s0_ingest.py`, `pipeline/s1_detect.py`,
`pipeline/s2_estimate.py`, `models/classify.py`, `models/features.py`.
`ingest()`, `detect()` and `estimate()` all already wrap their body in a
broad `except Exception`, so nothing in any of them can reach a caller
uncaught — confirmed, not assumed, by running S0->S1->S2->classify over
Anvith's six adversarial `.wav` files (`reports/s3_adversarial/`: pure
noise, DC-only, clipped, two overlapping signals, empty band, wrong sample
rate). All six: `status="ok"` at every stage, no exception, and the two
with nothing to classify (`pure_noise`, `empty_band`) correctly degrade to
`modulation_hypotheses=[]` rather than a false guess.

**One real gap found and fixed.** `estimate()`'s classify block caught only
`FileNotFoundError` around the call into `models.classify.classify` --
its own comment says "degrade, don't crash S2", but any OTHER exception
from classification (a corrupt `classifier.txt`, a feature-extraction edge
case) fell through to `estimate()`'s own outer handler instead, which
reports `status="failed"` for the WHOLE result -- discarding a symbol-rate
and CFO estimate that had already been computed successfully, over a
classifier-only failure that has nothing to do with either. Widened to
`except Exception`, matching the comment's stated intent. Pinned with
`test_a_classifier_exception_degrades_instead_of_failing_s2`
(`tests/unit/test_s2_estimate.py`): monkeypatches `models.classify.classify`
to raise `RuntimeError`, asserts `estimate()` still returns `status="ok"`
with a valid `symbol_rate_hz`/`cfo_hz` and an empty, honest
`modulation_hypotheses=[]`.

**Verification:** full suite, **774 passed, 2 xfailed, 0 failed** (22m),
plus the six-file adversarial run above. Scope held to the row: one
narrowed exception clause, one test, no thresholds or estimators touched.
