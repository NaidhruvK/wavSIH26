# S2 live-classification coverage matrix -- 4 Sep

pipeline.s2_estimate.estimate() run against all 252 files in zoo/corpus/rf/, classifier fed S2's own estimated symbol rate (not truth). Top-1 accuracy per scheme x SNR.

| scheme \ SNR(dB) | 4 | 8 | 10 | 13 | 15 | 20 | overall |
|---|---|---|---|---|---|---|---|
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 42/42 (100%) |
| qpsk | 0/7 | 5/7 | 7/7 | 7/7 | 7/7 | 7/7 | 33/42 (79%) |
| 8psk | 6/7 | 7/7 | 7/7 | 7/7 | 6/7 | 7/7 | 40/42 (95%) |
| 16qam | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 42/42 (100%) |
| 2fsk | 0/7 | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | 28/42 (67%) |
| 4fsk | 0/7 | 0/7 | 7/7 | 0/7 | 0/7 | 0/7 | 7/42 (17%) |

## Reading this table

bpsk/qpsk/8psk/16qam are solid from 10dB up (matches reports/classifier_eval.md's holdout numbers). 2fsk/4fsk are not uniform: 2fsk is perfect at >=10dB and 0% below it (the envelope-variance gate documented in models/features.py). 4fsk is perfect at EXACTLY 10dB and wrong above it (13-20dB) -- the same decision-boundary artifact traced in reports/classifier_eval.md's "Reading the 10dB+ number" section, now confirmed on full-length live captures too, not just the 4096-sample holdout windows. Not a resampling-bridge artifact: the SNR pattern (works at 10dB, fails above it) matches the held-out evaluation exactly.