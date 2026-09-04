# Classifier evaluation -- 3 Sep gate

LightGBM, num_leaves=31, max_depth=5, n_estimators=200, seed=42, config hash `525b649e17f8`.

Trained on 12600 windows (models/dataset_train.csv, SNR grid {0,5,10,15,20}dB). Evaluated on 7200 windows the model never trained on (models/dataset_holdout.csv, SNR {-3,2.5,7.5,12.5}dB).

## Headline numbers

| Metric | Model | Baseline |
|---|---|---|
| Macro-F1, full holdout | 0.693 | 0.383 |
| Macro-F1, holdout >=10dB | 0.778 | 0.778 |
| ECE | 0.2827 | -- |

## Per-SNR macro-F1 (holdout)

| SNR (dB) | Macro-F1 |
|---|---|
| -3.0 | 0.294 |
| 2.5 | 0.527 |
| 7.5 | 0.950 |
| 12.5 | 0.778 |

## 6x6 confusion matrices, per SNR bin (holdout)

### -3.0 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 174 | 0 | 0 | 21 | 0 | 105 |
| qpsk | 0 | 0 | 0 | 296 | 0 | 4 |
| 8psk | 0 | 0 | 0 | 297 | 0 | 3 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 0 | 268 | 0 | 32 |
| 4fsk | 0 | 0 | 0 | 87 | 0 | 213 |

### 2.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 0 | 0 | 300 | 0 | 0 |
| 8psk | 0 | 0 | 272 | 12 | 16 | 0 |
| 16qam | 0 | 169 | 0 | 131 | 0 | 0 |
| 2fsk | 0 | 0 | 45 | 1 | 34 | 220 |
| 4fsk | 0 | 0 | 0 | 0 | 0 | 300 |

### 7.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 217 | 0 | 83 | 0 | 0 |
| 8psk | 0 | 0 | 300 | 0 | 0 | 0 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 6 | 0 | 294 | 0 |
| 4fsk | 0 | 0 | 0 | 0 | 0 | 300 |

### 12.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 300 | 0 | 0 | 0 | 0 |
| 8psk | 0 | 0 | 300 | 0 | 0 | 0 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 0 | 0 | 300 | 0 |
| 4fsk | 0 | 0 | 0 | 0 | 300 | 0 |


## Reading the 10dB+ number

The holdout has exactly one SNR point >=10dB (12.5dB), so `macro_f1_ge10db` is a single-slice measurement, not an average over several -- read the per-SNR table above alongside it, not instead of it. At 12.5dB the model gets 5 of 6 classes exactly right and swaps 4fsk entirely for 2fsk (see the confusion matrix), which alone caps that slice's macro-F1 at 0.778 -- just under the plan's 0.80 Minimum-tier target. It is not a training bug: fixed (re-run three times, byte-identical predictions each time --
`num_threads=1, force_row_wise=True, deterministic=True` was needed to get that; earlier runs without it silently varied run to run). Root cause traced to the training data, not the model: `if_hist_peak_count` is clamped to 1 whenever `envelope_variance >= 0.05` (see models/features.py), which fires on a large fraction of BOTH 2fsk and 4fsk training rows at low SNR (841/2100 and 840/2100 report peak_count==1), diluting what is otherwise a near-perfect discriminator (2 vs 4) into a feature the tree can't fully trust. The baseline's hardcoded `>=4`/`>=2` threshold sidesteps this because it was never fit to the noisy low-SNR rows in the first place -- which is also why the baseline and model land on the *same* 0.778 at this slice, for opposite reasons (baseline's fixed gap is qpsk/8psk, not 2fsk/4fsk -- see reports/baseline_classifier.md). 7.5dB, a HARDER holdout point, scores 0.950 -- clear evidence this is a specific decision-boundary artifact at 12.5dB, not a general high-SNR failure.

Next step, not attempted this pass (out of scope for a first training run per the plan): feed an SNR estimate as an explicit feature, or split peak_count into a raw (ungated) value plus a separate envelope-constancy confidence feature, so the tree can learn the SNR-dependent reliability itself instead of losing that information to a hand-picked 0.05 gate.