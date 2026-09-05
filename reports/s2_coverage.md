# S2 live-classification coverage matrix -- 4 Sep

pipeline.s2_estimate.estimate() run against all 252 files in zoo/corpus/rf/, classifier fed S2's own estimated symbol rate (not truth). Top-1 accuracy per scheme x SNR.

| scheme \ SNR(dB) | 4 | 8 | 10 | 13 | 15 | 20 | overall |
|---|---|---|---|---|---|---|---|
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 42/42 (100%) |
| qpsk | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 35/42 (83%) |
| 8psk | 2/7 | 7/7 | 7/7 | 7/7 | 6/7 | 7/7 | 36/42 (86%) |
| 16qam | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 42/42 (100%) |
| 2fsk | 0/7 | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | 28/42 (67%) |
| 4fsk | 0/7 | 0/7 | 7/7 | 7/7 | 7/7 | 1/7 | 22/42 (52%) |

## Reading this table

bpsk/16qam are perfect; qpsk/8psk solid from 8dB up (both real improvements from the regularisation fix in reports/classifier_eval.md's "Reading the 10dB+ number" section -- an overfitting bug, not a missing feature: the model scored 100% on its own training rows for the exact cases it was failing on in holdout, traced to per-(scheme,SNR)-cell training clusters as tight as std=0.013 on some features). 2fsk is perfect >=10dB and 0% below it -- the envelope-variance gate documented in models/features.py, a *different*, still-open, low-SNR-only gap. 4fsk went from 17% to 52% after the same fix (perfect at 10-15dB, up from wrong everywhere except exactly 10dB) but is not fully resolved: 6 of 7 files are wrong at 20dB, though no longer confidently wrong -- probabilities run 0.4-0.8 for the incorrect top pick, with 4fsk consistently the #2 hypothesis at 14-42%, so the ranked-hypothesis design (not just top-1) still carries the right answer for S3/S4's rank test to recover. This 20dB slice was never covered by the holdout evaluation (holdout SNRs are {-3,2.5,7.5,12.5}dB) -- a live-corpus-only finding, not something the regularisation search was tuned against.