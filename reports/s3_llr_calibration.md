# Are S3's LLRs calibrated per-bit, or only on average?

Owner: Anvith. Regenerate with `./.venv/Scripts/python.exe reports/s3_llr_calibration_study.py` (`--render-only` re-renders this file from the CSV).

The premise check under `reports/s3_ldpc_design.md`. Sum-product belief propagation is the first consumer in this project whose answer depends on LLR MAGNITUDES rather than only on their signs and their sum, so it is the first one that needs this measured. Viterbi is scale-invariant, Reed-Solomon sees hard bits, and S4 hard-slices - none of them could have told us.

30 files, one per (modulation, SNR) cell, demodulated through the true symbol rate so the number is the demapper's and not the search's.

## Read this table first

The known-answer check. This script labels every bit right or wrong itself, from its own alignment and its own rotation choice. If that machinery is sound, aggregating it must reproduce the repo's own `corpus.measured_ber`, and its mean predicted error must reproduce `softmap.estimated_ber`. Where those disagree, nothing below the line means anything.

| file | status | this study | `measured_ber` | this study pred | `estimated_ber` | agrees |
|---|---|---|---|---|---|---|
| `16qam_10dB_2020` | ok | 0.003158 | 0.003158 | 0.002931 | 0.002931 | yes |
| `16qam_15dB_2022` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `16qam_20dB_2023` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `16qam_4dB_2018` | low_confidence | 0.424922 | 0.424922 | 0.055782 | 0.055782 | yes |
| `16qam_8dB_2019` | ok | 0.011587 | 0.011587 | 0.010982 | 0.010982 | yes |
| `2fsk_10dB_2026` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `2fsk_15dB_2028` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `2fsk_20dB_2029` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `2fsk_4dB_2024` | ok | 0.003756 | 0.003756 | 0.002832 | 0.002832 | yes |
| `2fsk_8dB_2025` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `4fsk_10dB_2032` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `4fsk_15dB_2034` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `4fsk_20dB_2035` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `4fsk_4dB_2030` | ok | 0.005521 | 0.005521 | 0.004532 | 0.004532 | yes |
| `4fsk_8dB_2031` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `8psk_10dB_2014` | ok | 0.000301 | 0.000301 | 0.000273 | 0.000273 | yes |
| `8psk_15dB_2016` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `8psk_20dB_2017` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `8psk_4dB_2012` | low_confidence | 0.240169 | 0.240169 | 0.031112 | 0.031112 | yes |
| `8psk_8dB_2013` | ok | 0.002956 | 0.002956 | 0.002685 | 0.002685 | yes |
| `bpsk_10dB_2002` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `bpsk_15dB_2004` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `bpsk_20dB_2005` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `bpsk_4dB_2000` | ok | 0.000000 | 0.000000 | 0.000002 | 0.000002 | yes |
| `bpsk_8dB_2001` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `qpsk_10dB_2008` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `qpsk_15dB_2010` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `qpsk_20dB_2011` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |
| `qpsk_4dB_2006` | ok | 0.001154 | 0.001154 | 0.000850 | 0.000850 | yes |
| `qpsk_8dB_2007` | ok | 0.000000 | 0.000000 | 0.000000 | 0.000000 | yes |

Every row agrees, so the per-bin numbers below rest on the same labelling the rest of the project already trusts.

## Calibration by |LLR| bin

`predicted` is the mean of `1 / (1 + exp(|llr|))` over the bin - what the LLR promises. `empirical` is how often those bits were actually wrong. `ratio` above 1 means the demapper is over-confident: it promised more reliability than it delivered.

A bin is scored only when it holds at least 20 errors and its lower edge is under 8. Everything else reads `no-power` - not `ok`. Zero errors in a high-confidence bin is consistent with the prediction and with a prediction ten times smaller, and calling that a pass would be corroboration invented out of an absence.

`status` is S3's own verdict on the file. It is in this table because the two verdicts behave completely differently and reading the rows without it is how the first draft of the summary below went wrong.

| modulation | SNR | status | LLR magnitude bin | bits | errors | empirical | predicted | ratio | verdict |
|---|---|---|---|---|---|---|---|---|---|
| bpsk | 4 dB | ok | [2, 4) | 1 | 0 | 0.00000 | 0.02507 | - | no-power |
| bpsk | 4 dB | ok | [4, 8) | 5 | 0 | 0.00000 | 0.00229 | - | no-power |
| bpsk | 4 dB | ok | [8, 16) | 131 | 0 | 0.00000 | 0.00001 | - | no-power |
| bpsk | 4 dB | ok | [16, inf) | 19818 | 0 | 0.00000 | 0.00000 | - | no-power |
| bpsk | 8 dB | ok | [16, inf) | 19935 | 0 | 0.00000 | 0.00000 | - | no-power |
| bpsk | 10 dB | ok | [16, inf) | 19960 | 0 | 0.00000 | 0.00000 | - | no-power |
| bpsk | 15 dB | ok | [16, inf) | 19923 | 0 | 0.00000 | 0.00000 | - | no-power |
| bpsk | 20 dB | ok | [16, inf) | 19965 | 0 | 0.00000 | 0.00000 | - | no-power |
| qpsk | 4 dB | ok | [0, 0.5) | 7 | 5 | 0.71429 | 0.45014 | - | no-power |
| qpsk | 4 dB | ok | [0.5, 1) | 11 | 5 | 0.45454 | 0.30607 | - | no-power |
| qpsk | 4 dB | ok | [1, 2) | 28 | 8 | 0.28571 | 0.16961 | - | no-power |
| qpsk | 4 dB | ok | [2, 4) | 76 | 5 | 0.06579 | 0.05243 | - | no-power |
| qpsk | 4 dB | ok | [4, 8) | 501 | 0 | 0.00000 | 0.00316 | - | no-power |
| qpsk | 4 dB | ok | [8, 16) | 4942 | 0 | 0.00000 | 0.00002 | - | no-power |
| qpsk | 4 dB | ok | [16, inf) | 14370 | 0 | 0.00000 | 0.00000 | - | no-power |
| qpsk | 8 dB | ok | [8, 16) | 8 | 0 | 0.00000 | 0.00002 | - | no-power |
| qpsk | 8 dB | ok | [16, inf) | 19950 | 0 | 0.00000 | 0.00000 | - | no-power |
| qpsk | 10 dB | ok | [16, inf) | 19945 | 0 | 0.00000 | 0.00000 | - | no-power |
| qpsk | 15 dB | ok | [16, inf) | 19960 | 0 | 0.00000 | 0.00000 | - | no-power |
| qpsk | 20 dB | ok | [16, inf) | 19949 | 0 | 0.00000 | 0.00000 | - | no-power |
| 8psk | 4 dB | low_confidence | [0, 0.5) | 435 | 216 | 0.49655 | 0.43866 | 1.13 | ok |
| 8psk | 4 dB | low_confidence | [0.5, 1) | 401 | 174 | 0.43391 | 0.32053 | 1.35 | ok |
| 8psk | 4 dB | low_confidence | [1, 2) | 903 | 333 | 0.36877 | 0.18712 | 1.97 | ok |
| 8psk | 4 dB | low_confidence | [2, 4) | 2081 | 662 | 0.31812 | 0.05260 | 6.05 | over-confident |
| 8psk | 4 dB | low_confidence | [4, 8) | 5060 | 1449 | 0.28636 | 0.00436 | 65.62 | over-confident |
| 8psk | 4 dB | low_confidence | [8, 16) | 5727 | 1444 | 0.25214 | 0.00007 | - | no-power |
| 8psk | 4 dB | low_confidence | [16, inf) | 5329 | 510 | 0.09570 | 0.00000 | - | no-power |
| 8psk | 8 dB | ok | [0, 0.5) | 32 | 14 | 0.43750 | 0.42829 | - | no-power |
| 8psk | 8 dB | ok | [0.5, 1) | 28 | 11 | 0.39286 | 0.32084 | - | no-power |
| 8psk | 8 dB | ok | [1, 2) | 78 | 12 | 0.15385 | 0.18477 | - | no-power |
| 8psk | 8 dB | ok | [2, 4) | 247 | 16 | 0.06478 | 0.04853 | - | no-power |
| 8psk | 8 dB | ok | [4, 8) | 1295 | 6 | 0.00463 | 0.00331 | - | no-power |
| 8psk | 8 dB | ok | [8, 16) | 6664 | 0 | 0.00000 | 0.00003 | - | no-power |
| 8psk | 8 dB | ok | [16, inf) | 11618 | 0 | 0.00000 | 0.00000 | - | no-power |
| 8psk | 10 dB | ok | [0, 0.5) | 2 | 1 | 0.50000 | 0.43488 | - | no-power |
| 8psk | 10 dB | ok | [0.5, 1) | 3 | 0 | 0.00000 | 0.29657 | - | no-power |
| 8psk | 10 dB | ok | [1, 2) | 10 | 3 | 0.30000 | 0.19665 | - | no-power |
| 8psk | 10 dB | ok | [2, 4) | 22 | 2 | 0.09091 | 0.05270 | - | no-power |
| 8psk | 10 dB | ok | [4, 8) | 187 | 0 | 0.00000 | 0.00279 | - | no-power |
| 8psk | 10 dB | ok | [8, 16) | 2076 | 0 | 0.00000 | 0.00002 | - | no-power |
| 8psk | 10 dB | ok | [16, inf) | 17653 | 0 | 0.00000 | 0.00000 | - | no-power |
| 8psk | 15 dB | ok | [16, inf) | 19927 | 0 | 0.00000 | 0.00000 | - | no-power |
| 8psk | 20 dB | ok | [16, inf) | 19962 | 0 | 0.00000 | 0.00000 | - | no-power |
| 16qam | 4 dB | low_confidence | [0, 0.5) | 778 | 372 | 0.47815 | 0.43769 | 1.09 | ok |
| 16qam | 4 dB | low_confidence | [0.5, 1) | 801 | 372 | 0.46442 | 0.32137 | 1.45 | ok |
| 16qam | 4 dB | low_confidence | [1, 2) | 1661 | 745 | 0.44853 | 0.18475 | 2.43 | over-confident |
| 16qam | 4 dB | low_confidence | [2, 4) | 3310 | 1422 | 0.42961 | 0.05412 | 7.94 | over-confident |
| 16qam | 4 dB | low_confidence | [4, 8) | 6125 | 2404 | 0.39249 | 0.00480 | 81.71 | over-confident |
| 16qam | 4 dB | low_confidence | [8, 16) | 4500 | 1798 | 0.39956 | 0.00008 | - | no-power |
| 16qam | 4 dB | low_confidence | [16, inf) | 2791 | 1371 | 0.49122 | 0.00000 | - | no-power |
| 16qam | 8 dB | ok | [0, 0.5) | 127 | 54 | 0.42520 | 0.44204 | 0.96 | ok |
| 16qam | 8 dB | ok | [0.5, 1) | 137 | 47 | 0.34307 | 0.32211 | 1.06 | ok |
| 16qam | 8 dB | ok | [1, 2) | 303 | 58 | 0.19142 | 0.18199 | 1.05 | ok |
| 16qam | 8 dB | ok | [2, 4) | 927 | 60 | 0.06473 | 0.05189 | 1.25 | ok |
| 16qam | 8 dB | ok | [4, 8) | 3557 | 10 | 0.00281 | 0.00369 | - | no-power |
| 16qam | 8 dB | ok | [8, 16) | 8364 | 0 | 0.00000 | 0.00005 | - | no-power |
| 16qam | 8 dB | ok | [16, inf) | 6349 | 0 | 0.00000 | 0.00000 | - | no-power |
| 16qam | 10 dB | ok | [0, 0.5) | 30 | 11 | 0.36667 | 0.44508 | - | no-power |
| 16qam | 10 dB | ok | [0.5, 1) | 41 | 15 | 0.36585 | 0.32399 | - | no-power |
| 16qam | 10 dB | ok | [1, 2) | 75 | 15 | 0.20000 | 0.18636 | - | no-power |
| 16qam | 10 dB | ok | [2, 4) | 267 | 18 | 0.06742 | 0.05030 | - | no-power |
| 16qam | 10 dB | ok | [4, 8) | 1316 | 4 | 0.00304 | 0.00321 | - | no-power |
| 16qam | 10 dB | ok | [8, 16) | 7172 | 0 | 0.00000 | 0.00003 | - | no-power |
| 16qam | 10 dB | ok | [16, inf) | 11049 | 0 | 0.00000 | 0.00000 | - | no-power |
| 16qam | 15 dB | ok | [4, 8) | 1 | 0 | 0.00000 | 0.00150 | - | no-power |
| 16qam | 15 dB | ok | [8, 16) | 19 | 0 | 0.00000 | 0.00002 | - | no-power |
| 16qam | 15 dB | ok | [16, inf) | 19942 | 0 | 0.00000 | 0.00000 | - | no-power |
| 16qam | 20 dB | ok | [16, inf) | 19960 | 0 | 0.00000 | 0.00000 | - | no-power |
| 2fsk | 4 dB | ok | [0, 0.5) | 29 | 13 | 0.44828 | 0.44241 | - | no-power |
| 2fsk | 4 dB | ok | [0.5, 1) | 31 | 9 | 0.29032 | 0.32034 | - | no-power |
| 2fsk | 4 dB | ok | [1, 2) | 90 | 27 | 0.30000 | 0.18486 | 1.62 | ok |
| 2fsk | 4 dB | ok | [2, 4) | 254 | 16 | 0.06299 | 0.05038 | - | no-power |
| 2fsk | 4 dB | ok | [4, 8) | 1175 | 9 | 0.00766 | 0.00357 | - | no-power |
| 2fsk | 4 dB | ok | [8, 16) | 5558 | 1 | 0.00018 | 0.00003 | - | no-power |
| 2fsk | 4 dB | ok | [16, inf) | 12831 | 0 | 0.00000 | 0.00000 | - | no-power |
| 2fsk | 8 dB | ok | [4, 8) | 1 | 0 | 0.00000 | 0.00047 | - | no-power |
| 2fsk | 8 dB | ok | [8, 16) | 39 | 0 | 0.00000 | 0.00001 | - | no-power |
| 2fsk | 8 dB | ok | [16, inf) | 19922 | 0 | 0.00000 | 0.00000 | - | no-power |
| 2fsk | 10 dB | ok | [16, inf) | 19929 | 0 | 0.00000 | 0.00000 | - | no-power |
| 2fsk | 15 dB | ok | [16, inf) | 19920 | 0 | 0.00000 | 0.00000 | - | no-power |
| 2fsk | 20 dB | ok | [16, inf) | 19927 | 0 | 0.00000 | 0.00000 | - | no-power |
| 4fsk | 4 dB | ok | [0, 0.5) | 63 | 28 | 0.44444 | 0.43722 | 1.02 | ok |
| 4fsk | 4 dB | ok | [0.5, 1) | 57 | 18 | 0.31579 | 0.31466 | - | no-power |
| 4fsk | 4 dB | ok | [1, 2) | 130 | 26 | 0.20000 | 0.17739 | 1.13 | ok |
| 4fsk | 4 dB | ok | [2, 4) | 348 | 23 | 0.06609 | 0.04686 | 1.41 | ok |
| 4fsk | 4 dB | ok | [4, 8) | 1517 | 13 | 0.00857 | 0.00347 | - | no-power |
| 4fsk | 4 dB | ok | [8, 16) | 5859 | 2 | 0.00034 | 0.00003 | - | no-power |
| 4fsk | 4 dB | ok | [16, inf) | 11951 | 0 | 0.00000 | 0.00000 | - | no-power |
| 4fsk | 8 dB | ok | [4, 8) | 1 | 0 | 0.00000 | 0.00087 | - | no-power |
| 4fsk | 8 dB | ok | [8, 16) | 62 | 0 | 0.00000 | 0.00002 | - | no-power |
| 4fsk | 8 dB | ok | [16, inf) | 19879 | 0 | 0.00000 | 0.00000 | - | no-power |
| 4fsk | 10 dB | ok | [16, inf) | 19939 | 0 | 0.00000 | 0.00000 | - | no-power |
| 4fsk | 15 dB | ok | [16, inf) | 19960 | 0 | 0.00000 | 0.00000 | - | no-power |
| 4fsk | 20 dB | ok | [16, inf) | 19934 | 0 | 0.00000 | 0.00000 | - | no-power |

## What this means for the LDPC path

The split below is by S3's own `status`, and it is the result rather than a way of arranging it. Pooling the two answers the wrong question: a consumer chooses whether to decode AFTER reading `status`, so what matters is how the LLRs behave inside each verdict, not on average across both.

### Files S3 returned `ok` on - what an LDPC decoder would be fed

This is the population the design can rely on.

| modulation | scored bins | median ratio | worst ratio | reading |
|---|---|---|---|---|
| 16qam | 4 | 1.06 | 1.25 | calibrated |
| 2fsk | 1 | 1.62 | 1.62 | calibrated |
| 4fsk | 3 | 1.13 | 1.41 | calibrated |

### Files S3 refused (`low_confidence`) - the contrast

These LLRs never reach a decoder unless somebody ignores `status`. The numbers show what happens if they do.

| modulation | scored bins | median ratio | worst ratio | reading |
|---|---|---|---|---|
| 8psk | 5 | 1.97 | 65.62 | over-confident |
| 16qam | 5 | 2.43 | 81.71 | over-confident |

See `reports/s3_ldpc_design.md` for what the design does with this.
