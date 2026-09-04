# S3 lock-failure detection and hypothesis retry - the 4 Sep gate

**Anvith.** Measured on Dheeraj's 36-file RF corpus (`zoo/corpus/rf/`), blind. Regenerate with `python reports/s3_lock_gate_study.py`.

Bit error rates are against the bits the zoo actually transmitted, regenerated from the seed in each truth JSON. `decodes` means the best rotation came back under **1%** raw BER.

## The three arms

| arm | what S3 was told | decodes | mod correct | **confidently wrong** | *would have been, old rule* | median s |
|---|---|---|---|---|---|---|
| `truth-params` | the true symbol rate, no carrier offset | **33/36** | 36/36 | **0** | *0* | 0.27 |
| `s2-top` | S2's top hypothesis on every field | **4/36** | 36/36 | **0** | *19* | 0.27 |
| `search` | S2's *ranked* hypotheses, searched | **29/36** | 31/36 | **0** | *0* | 2.28 |

## The last column, and why it is the point

Every arm above runs TODAY's code, so `confidently wrong` is what the build now reports. The italic column is what the *old* rule - `ok` from the carrier lock metric alone - would have said about the very same runs. It is computed from the per-check verdicts each run recorded, so it is measured rather than remembered.

On the `s2-top` arm, which is what S3 did until this morning, the old rule returns `ok` on **19 of 36** files whose real bit error rate is around 0.485 - a coin flip, reported as a clean lock, with `estimated_output_ber` reading 0.000000 beside it.

The cause is one line in two stages meeting. `s2_estimate.estimate_cfo` raises the signal to the M-th power and takes the strongest line; on a pulse-shaped stream that line is the **symbol rate**, not `M x cfo`, so the offset comes back near `Rs / M`. De-rotating by `Rs / M` advances the constellation exactly one symmetry step per symbol, and S3's lock metric `|E[u^S]|` is invariant under precisely that rotation. Neither stage was checkable against the other, because the only number either produced said everything was fine.

**Dheeraj** - the S2 half is yours and it is worth fixing at source: the CFO search should exclude the symbol-rate line, or rank M-th power peaks by something other than height. The corpus makes it easy to check, because every file has a true offset of exactly zero and S2 reports a non-zero one on 33 of 36.

## What closed it

Independent checks against different evidence, any one of which can veto a claim of lock (`pipeline/s3_receive/lockcheck.py`). Four are new today; the carrier lock metric is kept, because it is right about what it is right about:

- **`signal_present`** - a cyclostationary line at the claimed symbol rate. Spectral, so it survives every carrier and timing error there is. Separates 'nothing is here' from 'I did not lock', which is what makes pure noise a `failed` with a reason rather than a shrug.
- **`carrier_aligned`** - the spectrum is still centred after the carrier-offset hypothesis has been applied. This is the one that catches the failure above, and its measurement doubles as the correction the retry loop tries next.
- **`output_usable`** - the receiver may not claim `ok` while its own estimated output error rate says the output is junk. Found by `8psk_8dB_2013`, where the 2-FSK plug-in returned `ok` at a mean tone margin of 0.319 while estimating its own output BER at 0.19.
- **`alphabet_used`** (linear) - does the received cloud use the whole constellation this hypothesis claims? The only check that can refuse a constellation which CONTAINS the true one. QPSK's four points are four of 16-QAM's sixteen, so a QPSK capture read as 16-QAM locks perfectly and reports an estimated BER of 1.8e-21 against an actual 0.482. Measured: correct hypothesis >= 0.992 evenness, wrong-but-`ok` <= 0.670, across four schemes and 4-25 dB.
- **`tone_alias`** (FSK) - the frequency twin of the rotation ambiguity. An offset of one tone spacing maps the tone bank onto itself and slips every symbol label by one: identical tones, identical margins, every other check passing, and a bit error rate of 0.248 on `4fsk_13dB_2033`. Refused rather than guessed.
- **`timing_converged`** - a verdict the Gardner loop was already computing, reported, and then not counted.

With them, `confidently wrong` on this corpus is **0**, and files decoding went from **4** to **29** of 36.

## Per modulation, `search` arm

| modulation | decodes | files | worst SNR that decodes |
|---|---|---|---|
| 16qam | 4 | 6 | 10 dB |
| 2fsk | 4 | 6 | 10 dB |
| 4fsk | 4 | 6 | 10 dB |
| 8psk | 5 | 6 | 8 dB |
| bpsk | 6 | 6 | 4 dB |
| qpsk | 6 | 6 | 4 dB |

## Against the 4 Sep gate

The gate is written for the whole pipeline (≥40% of the corpus to exact bits, ≥4 of 6 modulations, no unhandled exception). S3 owns the first two stages of that and can report its own half:

- **81%** of the corpus reaches LLRs under 1% raw BER (29/36).
- **6 of 6** modulations are represented among them: 16qam, 2fsk, 4fsk, 8psk, bpsk, qpsk.
- No input in this study, or in the adversarial set in `tests/unit/test_s3_receive.py`, raised out of `receive()`.

## Every file, `search` arm

| file | true | chosen | status | est BER | valid | measured BER | runs | s | why not |
|---|---|---|---|---|---|---|---|---|---|
| 16qam_4dB_2018 | 16qam | 8psk | `low_confidence` | 8.60e-02 | no | 0.48467 ⚠ | 12 | 2.63 | carrier lock 0.04 below 0.60; the receiver estimates its own output BER at 0.086, over the 0.05 a lock should produce -  |
| 16qam_8dB_2019 | 16qam | 16qam | `ok` | 1.22e-02 | yes | 0.01493 ⚠ | 12 | 1.81 |  |
| 16qam_10dB_2020 | 16qam | 16qam | `ok` | 2.85e-03 | yes | 0.00306 | 12 | 1.82 |  |
| 16qam_13dB_2021 | 16qam | 16qam | `ok` | 7.48e-05 | yes | 0.00010 | 6 | 0.93 |  |
| 16qam_15dB_2022 | 16qam | 16qam | `ok` | 7.00e-08 | yes | 0.00000 | 12 | 1.81 |  |
| 16qam_20dB_2023 | 16qam | 16qam | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 1.84 |  |
| 2fsk_4dB_2024 | 2fsk | - | `failed` | 1.00e+00 | no | 1.00000 ⚠ | 0 | 0.13 | every candidate was refused by the cheap screen: no symbol-rate line at 48479 Hz (4.4x local median, needs 4.5x) - eithe |
| 2fsk_8dB_2025 | 2fsk | - | `failed` | 1.00e+00 | no | 1.00000 ⚠ | 0 | 0.13 | every candidate was refused by the cheap screen: no symbol-rate line at 11987 Hz (3.9x local median, needs 4.5x) - eithe |
| 2fsk_10dB_2026 | 2fsk | 2fsk | `ok` | 0.00e+00 | yes | 0.00000 | 2 | 0.31 |  |
| 2fsk_13dB_2027 | 2fsk | 2fsk | `ok` | 0.00e+00 | yes | 0.00000 | 2 | 0.30 |  |
| 2fsk_15dB_2028 | 2fsk | 2fsk | `ok` | 0.00e+00 | yes | 0.00000 | 2 | 0.29 |  |
| 2fsk_20dB_2029 | 2fsk | 2fsk | `ok` | 0.00e+00 | yes | 0.00000 | 4 | 0.42 |  |
| 4fsk_4dB_2030 | 4fsk | - | `failed` | 1.00e+00 | no | 1.00000 ⚠ | 0 | 0.05 | every candidate was refused by the cheap screen: no symbol-rate line at 65634 Hz (4.0x local median, needs 4.5x) - eithe |
| 4fsk_8dB_2031 | 4fsk | bpsk | `low_confidence` | 9.75e-02 | no | 0.48376 ⚠ | 4 | 1.74 | carrier lock 0.23 below 0.60; the receiver estimates its own output BER at 0.0975, over the 0.05 a lock should produce - |
| 4fsk_10dB_2032 | 4fsk | 4fsk | `ok` | 0.00e+00 | yes | 0.00000 | 2 | 0.13 |  |
| 4fsk_13dB_2033 | 4fsk | 4fsk | `ok` | 0.00e+00 | yes | 0.00000 | 4 | 0.21 |  |
| 4fsk_15dB_2034 | 4fsk | 4fsk | `ok` | 0.00e+00 | yes | 0.00000 | 2 | 0.13 |  |
| 4fsk_20dB_2035 | 4fsk | 4fsk | `ok` | 0.00e+00 | yes | 0.00000 | 4 | 0.20 |  |
| 8psk_4dB_2012 | 8psk | 8psk | `low_confidence` | 2.94e-02 | no | 0.23039 ⚠ | 12 | 3.06 | carrier lock 0.16 below 0.60 |
| 8psk_8dB_2013 | 8psk | 8psk | `low_confidence` | 2.81e-03 | no | 0.00281 | 12 | 2.97 | carrier lock 0.49 below 0.60 |
| 8psk_10dB_2014 | 8psk | 8psk | `ok` | 3.11e-04 | yes | 0.00025 | 12 | 2.45 |  |
| 8psk_13dB_2015 | 8psk | 8psk | `ok` | 1.60e-07 | yes | 0.00000 | 12 | 2.53 |  |
| 8psk_15dB_2016 | 8psk | 8psk | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 2.65 |  |
| 8psk_20dB_2017 | 8psk | 8psk | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 2.94 |  |
| bpsk_4dB_2000 | bpsk | bpsk | `ok` | 1.52e-06 | yes | 0.00000 | 6 | 4.67 |  |
| bpsk_8dB_2001 | bpsk | bpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 4.79 |  |
| bpsk_10dB_2002 | bpsk | bpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 4.50 |  |
| bpsk_13dB_2003 | bpsk | bpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 4.77 |  |
| bpsk_15dB_2004 | bpsk | bpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 4.75 |  |
| bpsk_20dB_2005 | bpsk | bpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 4.69 |  |
| qpsk_4dB_2006 | qpsk | qpsk | `ok` | 9.65e-04 | yes | 0.00115 | 6 | 2.34 |  |
| qpsk_8dB_2007 | qpsk | qpsk | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 4.34 |  |
| qpsk_10dB_2008 | qpsk | qpsk | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 4.63 |  |
| qpsk_13dB_2009 | qpsk | qpsk | `ok` | 0.00e+00 | yes | 0.00000 | 12 | 4.47 |  |
| qpsk_15dB_2010 | qpsk | qpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 2.23 |  |
| qpsk_20dB_2011 | qpsk | qpsk | `ok` | 0.00e+00 | yes | 0.00000 | 6 | 2.34 |  |

## Cost

The search considers up to 12 full receiver runs and rejects the rest with one FFT each. Median 2.28 s per file, worst 4.79 s, against a 20 s budget and a 90 s whole-pipeline window. The screen is what makes that true: without it the same candidate list is 6 modulations x 3 rates x 5 offsets of full chain runs.

## Known gaps, stated

- **The 4 dB files mostly do not decode**, on any arm. That is the operating envelope, not a lock-detection failure - `truth-params` does not decode them either. 5 Sep is the day that moves.
- **The four FSK misses split two ways, and the halves have different owners.** `2fsk_8dB_2025` (S2 offers 11987, 9345, 59987 Hz against a true 50000) and `4fsk_4dB_2030` (65634) fail because the true rate is not in the list; the retry loop can only search what it is given. **Dheeraj**: one predicate is behind both - `estimate()`'s envelope test reads these WAVs as non-constant-envelope, so FSK captures go to the LINEAR symbol-rate estimator, and `fsk_order_hypotheses` comes back empty on all 36 files for the same reason. That is worth more to this gate than anything left in S3.
- **`2fsk_4dB_2024` is mine, and it is a near miss.** S2's rate is 48479 against a true 50000, close enough to work, and the presence check scored it 4.4 against a limit of 4.5. The limit is set from the worst noise draw measured at the shortest record length, so lowering it to catch this file would spend the margin that keeps noise out. The right fix is a better statistic at 4 dB, not a looser threshold; 5 Sep is the day for it.
- **Choosing the modulation is not S3's job** and this does not make it so. With no ranking from S2, the search runs every survivor and picks on reported quality, which works on this corpus and is not a classifier. When Dheeraj's lands, pass it as `modulations=` and the search takes the first clean lock instead.
