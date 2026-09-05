# The carrier lock threshold, per scheme - 5 Sep

**Anvith.** Regenerate with `python reports/s3_lock_threshold_study.py`. Every one of the 252 corpus files run through all 4 linear plug-ins at the true symbol rate with no carrier offset, which is 1008 runs and two populations per scheme.

`admit` is a run whose hypothesis was correct **and** which decoded under 1% raw bit error rate - refusing one of those is a false negative and costs S4 a working file. `refuse` is everything else. A run counts as admitted only when its carrier lock clears the threshold **and** no other check vetoed, so these are the stage's verdicts and not one check's.

## The two populations

| scheme | incumbent | admit: min / median | refuse: max / median | gap | chosen |
|---|---|---|---|---|---|
| bpsk | 0.60 | 0.857 / 0.979 | 0.060 / 0.017 | 14.36x | **0.23** |
| qpsk | 0.60 | 0.636 / 0.924 | 0.328 / 0.034 | 1.94x | **0.46** |
| 8psk | 0.60 | 0.488 / 0.803 | 0.184 / 0.129 | 2.65x | **0.30** |
| 16qam | 0.55 | 0.784 / 0.936 | 0.437 / 0.047 | 1.79x | **0.59** |

## What the change costs and buys

`before` is the value this study replaced, written down in `PREVIOUS` so the comparison survives the change landing. Counts are runs whose hypothesis was correct and which decoded (`admitted`), the same minus those this threshold refused (`missed`), and genuine failures it let through (`wrong`).

| scheme | before | after | at before | at after | false negatives recovered | false positives added |
|---|---|---|---|---|---|---|
| bpsk | 0.60 | **0.23** | 42 admitted, 0 missed, 0 wrong | 42 admitted, 0 missed, 0 wrong | **0** | 0 |
| qpsk | 0.60 | **0.46** | 42 admitted, 0 missed, 0 wrong | 42 admitted, 0 missed, 0 wrong | **0** | 0 |
| 8psk | 0.60 | **0.30** | 28 admitted, 7 missed, 0 wrong | 35 admitted, 0 missed, 0 wrong | **7** | 0 |
| 16qam | 0.55 | **0.59** | 28 admitted, 0 missed, 0 wrong | 28 admitted, 0 missed, 0 wrong | **0** | 0 |

## Per scheme

### bpsk

- 42 admit, 38 refuse, 84 runs gave up before the carrier loop and are in neither.
- admit >= 0.857, refuse <= 0.060, ratio 14.36x

| SNR | carrier lock, correct hypothesis (min .. max) |
|---|---|
| 4 dB | 0.857 .. 0.887 |
| 8 dB | 0.950 .. 0.957 |
| 10 dB | 0.968 .. 0.973 |
| 13 dB | 0.986 .. 0.987 |
| 15 dB | 0.991 .. 0.992 |
| 20 dB | 0.997 .. 0.997 |

### qpsk

- 42 admit, 77 refuse, 84 runs gave up before the carrier loop and are in neither.
- admit >= 0.636, refuse <= 0.328, ratio 1.94x

| SNR | carrier lock, correct hypothesis (min .. max) |
|---|---|
| 4 dB | 0.636 .. 0.662 |
| 8 dB | 0.837 .. 0.848 |
| 10 dB | 0.896 .. 0.902 |
| 13 dB | 0.946 .. 0.949 |
| 15 dB | 0.965 .. 0.967 |
| 20 dB | 0.989 .. 0.990 |

### 8psk

- 35 admit, 21 refuse, 84 runs gave up before the carrier loop and are in neither.
- admit >= 0.488, refuse <= 0.184, ratio 2.65x

| SNR | carrier lock, correct hypothesis (min .. max) |
|---|---|
| 4 dB | 0.033 .. 0.163 |
| 8 dB | 0.488 .. 0.515 |
| 10 dB | 0.651 .. 0.672 |
| 13 dB | 0.802 .. 0.818 |
| 15 dB | 0.867 .. 0.886 |
| 20 dB | 0.956 .. 0.958 |

### 16qam

- 28 admit, 15 refuse, 84 runs gave up before the carrier loop and are in neither.
- admit >= 0.784, refuse <= 0.437, ratio 1.79x

- **7 near-miss runs excluded from both**: carrier lock 0.680..0.788 at 0.0117..0.0124 raw BER, between the 1% decode line and the 2% genuine-failure line. At the chosen threshold they all pass.

| SNR | carrier lock, correct hypothesis (min .. max) |
|---|---|
| 4 dB | 0.034 .. 0.329 |
| 8 dB | 0.680 .. 0.788 |
| 10 dB | 0.784 .. 0.848 |
| 13 dB | 0.887 .. 0.956 |
| 15 dB | 0.919 .. 0.976 |
| 20 dB | 0.933 .. 0.993 |

