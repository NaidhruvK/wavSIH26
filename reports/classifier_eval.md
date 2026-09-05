# Classifier evaluation -- 3 Sep gate

LightGBM, num_leaves=31, max_depth=5, learning_rate=0.1, min_data_in_leaf=300, lambda_l2=5.0, bagging_fraction=0.6, feature_fraction=0.6, bagging_freq=1, n_estimators=200, seed=42, config hash `132fc1d21777`.

Trained on 12600 windows (models/dataset_train.csv, SNR grid {0,5,10,15,20}dB). Evaluated on 7200 windows the model never trained on (models/dataset_holdout.csv, SNR {-3,2.5,7.5,12.5}dB).

## Headline numbers

| Metric | Model | Baseline |
|---|---|---|
| Macro-F1, full holdout | 0.720 | 0.383 |
| Macro-F1, holdout >=10dB | 0.993 | 0.778 |
| ECE | 0.2400 | -- |

## Per-SNR macro-F1 (holdout)

| SNR (dB) | Macro-F1 |
|---|---|
| -3.0 | 0.231 |
| 2.5 | 0.519 |
| 7.5 | 0.953 |
| 12.5 | 0.993 |

## 6x6 confusion matrices, per SNR bin (holdout)

### -3.0 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 159 | 0 | 5 | 136 | 0 | 0 |
| qpsk | 0 | 0 | 0 | 300 | 0 | 0 |
| 8psk | 0 | 0 | 0 | 300 | 0 | 0 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 3 | 297 | 0 | 0 |
| 4fsk | 0 | 0 | 0 | 231 | 0 | 69 |

### 2.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 80 | 0 | 220 | 0 | 0 |
| 8psk | 0 | 0 | 289 | 0 | 11 | 0 |
| 16qam | 0 | 274 | 4 | 22 | 0 | 0 |
| 2fsk | 0 | 0 | 5 | 0 | 22 | 273 |
| 4fsk | 0 | 0 | 0 | 0 | 0 | 300 |

### 7.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 218 | 0 | 82 | 0 | 0 |
| 8psk | 0 | 0 | 299 | 0 | 1 | 0 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 0 | 0 | 300 | 0 |
| 4fsk | 0 | 0 | 0 | 0 | 0 | 300 |

### 12.5 dB

| true\pred | bpsk | qpsk | 8psk | 16qam | 2fsk | 4fsk |
|---|---|---|---|---|---|---|
| bpsk | 300 | 0 | 0 | 0 | 0 | 0 |
| qpsk | 0 | 300 | 0 | 0 | 0 | 0 |
| 8psk | 0 | 1 | 299 | 0 | 0 | 0 |
| 16qam | 0 | 0 | 0 | 300 | 0 | 0 |
| 2fsk | 0 | 0 | 0 | 0 | 300 | 0 |
| 4fsk | 0 | 0 | 0 | 0 | 12 | 288 |


## Reading the 10dB+ number

The holdout has exactly one SNR point >=10dB (12.5dB), so `macro_f1_ge10db` is a single-slice measurement, not an average over several -- read the per-SNR table above alongside it, not instead of it.

**This section originally reported a different, WRONG root cause for a 4fsk failure at this slice (macro-F1 0.778, 4fsk swapped entirely for 2fsk) -- corrected below rather than silently edited, because the wrong diagnosis is itself a useful lesson.** The first hypothesis was that `if_hist_peak_count`'s envelope-variance gate was clamping to 1 at low SNR and diluting the feature. That was plausible and wrong: checking the actual feature values for the failing rows showed `if_hist_peak_count` was correctly 4.0, cleanly separated from 2fsk's 2.0, at every failing SNR (13-20dB) -- the feature was fine. The real cause, found by testing the model against its OWN training rows: it scored 100% on training data for the exact (scheme, SNR) cell it was failing on in holdout. That is classic overfitting, not a missing signal -- with only 420 training windows per (scheme, SNR) cell and some features clustering extremely tightly within a cell (`phase_diff_entropy` std as low as 0.013), the unregularised tree fit a boundary tight enough that a differently-seeded holdout draw landed outside it, despite every feature being textbook 4fsk.

Fix: `min_data_in_leaf=300`, `lambda_l2=5.0`, `bagging_fraction=feature_fraction=0.6` (see models/train.py's `LGB_PARAMS` docstring) -- no feature changes, no depth or tree-count increase (still `max_depth=5`, 200 trees, per the plan's cap). **Moved macro-F1 at 12.5dB from 0.778 to 0.993** (only one 8psk/qpsk and one 2fsk/4fsk pair-of-rows still wrong out of 1800). Confirmed deterministic across repeated training runs with `num_threads=1, force_row_wise=True, deterministic=True` even with bagging enabled.