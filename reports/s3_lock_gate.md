# S3 lock-failure detection and hypothesis retry - the 4 Sep gate

**Anvith.** Measured on Dheeraj's 252-file RF corpus (`zoo/corpus/rf/`), blind. Regenerate with `python reports/s3_lock_gate_study.py`.

Bit error rates are against the bits the zoo actually transmitted, regenerated from the seed in each truth JSON. `decodes` means the best rotation came back under **1%** raw BER.

## The three arms

| arm | what S3 was told | decodes | mod correct | **confidently wrong** | *would have been, old rule* | median s |
|---|---|---|---|---|---|---|
| `truth-params` | the true symbol rate, no carrier offset | **231/252** | 252/252 | **0** | *0* | 0.29 |
| `s2-top` | S2's top hypothesis on every field | **178/252** | 252/252 | **0** | *24* | 0.26 |
| `search` | S2's *ranked* hypotheses, searched | **230/252** | 238/252 | **0** | *8* | 0.36 |

## The last column, and why it is the point

Every arm above runs TODAY's code, so `confidently wrong` is what the build now reports. The italic column is what the *old* rule - `ok` from the carrier lock metric alone - would have said about the very same runs. It is computed from the per-check verdicts each run recorded, so it is measured rather than remembered.

On the `s2-top` arm the old rule still returns `ok` on **24 of 252** files it should not.

The cause is one line in two stages meeting. `s2_estimate.estimate_cfo` raised the signal to the M-th power and took the strongest line; on a pulse-shaped stream that line is the **symbol rate**, not `M x cfo`, so the offset came back near `Rs / M`. De-rotating by `Rs / M` advances the constellation exactly one symmetry step per symbol, and S3's lock metric `|E[u^S]|` is invariant under precisely that rotation. Neither stage was checkable against the other, because the only number either produced said everything was fine.

**That half is fixed.** Dheeraj landed it on 5 Sep (`426a780`, 'Fix S2 CFO estimator falling into the M-th power spectral-line trap') and it is the largest single move in this table. The `s2-top` arm - S3 reading S2's top hypothesis and nothing else, which is what the stage did before 4 Sep - went from **4 of 36 files decoding on 4 Sep** to **178 of 252** on the same code path today. Measured on the corpus this morning: every file still has a true offset of exactly zero, and S2 now reports a non-zero one on 93 of 252 rather than 33 of 36 - so the estimator is right far more often, and the hypothesis-search and alignment check below are what cover the remainder rather than papering over it.

## What closed it

Independent checks against different evidence, any one of which can veto a claim of lock (`pipeline/s3_receive/lockcheck.py`). Four are new today; the carrier lock metric is kept, because it is right about what it is right about:

- **`signal_present`** - a cyclostationary line at the claimed symbol rate. Spectral, so it survives every carrier and timing error there is. Separates 'nothing is here' from 'I did not lock', which is what makes pure noise a `failed` with a reason rather than a shrug.
- **`carrier_aligned`** - the spectrum is still centred after the carrier-offset hypothesis has been applied. This is the one that catches the failure above, and its measurement doubles as the correction the retry loop tries next.
- **`output_usable`** - the receiver may not claim `ok` while its own estimated output error rate says the output is junk. Found by `8psk_8dB_2013`, where the 2-FSK plug-in returned `ok` at a mean tone margin of 0.319 while estimating its own output BER at 0.19.
- **`alphabet_used`** (linear) - does the received cloud use the whole constellation this hypothesis claims? The only check that can refuse a constellation which CONTAINS the true one. QPSK's four points are four of 16-QAM's sixteen, so a QPSK capture read as 16-QAM locks perfectly and reports an estimated BER of 1.8e-21 against an actual 0.482. Measured: correct hypothesis >= 0.992 evenness, wrong-but-`ok` <= 0.670, across four schemes and 4-25 dB.
- **`tone_alias`** (FSK) - the frequency twin of the rotation ambiguity. An offset of one tone spacing maps the tone bank onto itself and slips every symbol label by one: identical tones, identical margins, every other check passing, and a bit error rate of 0.248 on `4fsk_13dB_2033`. Refused rather than guessed.
- **`timing_converged`** - a verdict the Gardner loop was already computing, reported, and then not counted.

With them, `confidently wrong` on this corpus is **0**, and files decoding went from **178** to **230** of 252.

## Per modulation, `search` arm

| modulation | decodes | files | worst SNR that decodes |
|---|---|---|---|
| 16qam | 28 | 42 | 10 dB |
| 2fsk | 42 | 42 | 4 dB |
| 4fsk | 41 | 42 | 4 dB |
| 8psk | 35 | 42 | 8 dB |
| bpsk | 42 | 42 | 4 dB |
| qpsk | 42 | 42 | 4 dB |

## Harness table, by modulation and SNR bin


### Decodes - best rotation under 1% raw bit error rate

| modulation | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB | all |
|---|---|---|---|---|---|---|---|
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| qpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| 8psk | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **35/42** |
| 16qam | 0/7 | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | **28/42** |
| 2fsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| 4fsk | 7/7 | 6/7 | 7/7 | 7/7 | 7/7 | 7/7 | **41/42** |

This is the one the day gate is written against. It is measured against the bits the zoo transmitted, so it is what S4 would get, not what S3 believes it got.

### Locks - S3 returned `status: ok`

| modulation | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB | all |
|---|---|---|---|---|---|---|---|
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| qpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| 8psk | 0/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **35/42** |
| 16qam | 0/7 | 6/7 | 7/7 | 7/7 | 7/7 | 7/7 | **34/42** |
| 2fsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | **42/42** |
| 4fsk | 7/7 | 6/7 | 7/7 | 7/7 | 7/7 | 7/7 | **41/42** |

S3's own claim, made blind. Read it beside the row below it.

### Confidently wrong - `ok`, estimate marked valid, real BER >= 10%

| modulation | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB | all |
|---|---|---|---|---|---|---|---|
| bpsk | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |
| qpsk | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |
| 8psk | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |
| 16qam | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |
| 2fsk | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |
| 4fsk | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | 0/7 | **0/42** |

Every cell here should be 0. A non-zero cell is worse than a failed one: downstream reads `status` before it reads anything else, so this is a stage telling S4 to spend its budget on noise.

### Against the 5 Sep targets

| family | SNR floor | files | locks | decodes | confidently wrong | verify |
|---|---|---|---|---|---|---|
| **PSK** | ≥10 dB | 84 | **84/84** (100%) | 84/84 (100%) | 0 | **PASS** |
| **FSK** | ≥10 dB | 56 | **56/56** (100%) | 56/56 (100%) | 0 | **PASS** |
| **16-QAM** | ≥13 dB | 21 | **21/21** (100%) | 21/21 (100%) | 0 | **PASS** |

`verify` is the 5 Sep row's line - lock rate at or above 90% above the family's floor - **and** zero confidently wrong, which the row does not say and which is the only reason the first number means anything.

## Against the 5 Sep day gate

The gate is written for the whole pipeline - at least 65% of corpus files at 10 dB or better decoding to exact bits across 5 or more modulations, and Nehal's concatenated CCSDS chain recovering its payload text. S4 and S5 finish that; S3 owns the front of it and can report its own half:

- **100%** of the files at 10 dB and above reach LLRs under 1% raw BER (168/168), across **6 of 6** modulations.
- Over the whole corpus including 4 and 8 dB it is **91%** (230/252), across 6 of 6.
- No input in this study, or in the adversarial set in `tests/unit/test_s3_receive.py`, raised out of `receive()`.

Quoting either number without the corpus size attached is how a 24/24 becomes a claim about a receiver rather than about 36 files, so: **252 files**, seven seeds per (modulation, SNR) cell.

## Every file that did not decode, `search` arm

All 252 rows are in `s3_lock_gate.csv`; this table is the complement, because it is the list the next day's work is drawn from. Sorted by SNR descending: a miss at 20 dB is a defect, a miss at 4 dB may be the operating envelope, and they should not be read in the same breath.

| file | true | chosen | status | est BER | valid | measured BER | runs | s | why not |
|---|---|---|---|---|---|---|---|---|---|
| 16qam_8dB_2019 | 16qam | 16qam | `low_confidence` | 1.05e-02 | no | 0.01106 ⚠ | 12 | 1.98 | carrier lock 0.49 below 0.59 |
| 16qam_8dB_3019 | 16qam | 16qam | `ok` | 1.07e-02 | yes | 0.01294 ⚠ | 1 | 0.25 |  |
| 16qam_8dB_4019 | 16qam | 16qam | `ok` | 1.09e-02 | yes | 0.01239 ⚠ | 1 | 0.26 |  |
| 16qam_8dB_5019 | 16qam | 16qam | `ok` | 1.26e-02 | yes | 0.01395 ⚠ | 2 | 0.52 |  |
| 16qam_8dB_6019 | 16qam | 16qam | `ok` | 1.07e-02 | yes | 0.01229 ⚠ | 1 | 0.25 |  |
| 16qam_8dB_7019 | 16qam | 16qam | `ok` | 1.06e-02 | yes | 0.01269 ⚠ | 1 | 0.25 |  |
| 16qam_8dB_8019 | 16qam | 16qam | `ok` | 1.01e-02 | yes | 0.01217 ⚠ | 1 | 0.27 |  |
| 4fsk_8dB_7031 | 4fsk | qpsk | `low_confidence` | 1.04e-01 | no | 0.48183 ⚠ | 12 | 1.83 | carrier lock 0.01 below 0.46; the receiver estimates its own output BER at 0.104, over the 0.05 a lock should produce -  |
| 16qam_4dB_2018 | 16qam | bpsk | `low_confidence` | 1.25e-01 | no | 0.47852 ⚠ | 12 | 2.60 | carrier lock 0.03 below 0.23; the receiver estimates its own output BER at 0.125, over the 0.05 a lock should produce -  |
| 16qam_4dB_3018 | 16qam | 4fsk | `low_confidence` | 3.66e-01 | no | 0.48326 ⚠ | 12 | 2.19 | the receiver estimates its own output BER at 0.366, over the 0.05 a lock should produce - it is describing a demodulatio |
| 16qam_4dB_4018 | 16qam | 2fsk | `low_confidence` | 3.46e-01 | no | 0.47776 ⚠ | 12 | 2.41 | the receiver estimates its own output BER at 0.346, over the 0.05 a lock should produce - it is describing a demodulatio |
| 16qam_4dB_5018 | 16qam | 2fsk | `low_confidence` | 2.86e-01 | no | 0.47913 ⚠ | 12 | 1.77 | the receiver estimates its own output BER at 0.286, over the 0.05 a lock should produce - it is describing a demodulatio |
| 16qam_4dB_6018 | 16qam | 2fsk | `low_confidence` | 4.08e-01 | no | 0.47875 ⚠ | 12 | 1.79 | the receiver estimates its own output BER at 0.408, over the 0.05 a lock should produce - it is describing a demodulatio |
| 16qam_4dB_7018 | 16qam | 2fsk | `low_confidence` | 3.07e-01 | no | 0.47968 ⚠ | 12 | 2.01 | the receiver estimates its own output BER at 0.307, over the 0.05 a lock should produce - it is describing a demodulatio |
| 16qam_4dB_8018 | 16qam | 2fsk | `low_confidence` | 2.57e-01 | no | 0.47984 ⚠ | 12 | 1.78 | the receiver estimates its own output BER at 0.257, over the 0.05 a lock should produce - it is describing a demodulatio |
| 8psk_4dB_2012 | 8psk | 2fsk | `low_confidence` | 3.57e-01 | no | 0.48232 ⚠ | 12 | 2.59 | the receiver estimates its own output BER at 0.357, over the 0.05 a lock should produce - it is describing a demodulatio |
| 8psk_4dB_3012 | 8psk | 16qam | `low_confidence` | 4.85e-02 | no | 0.48457 ⚠ | 12 | 2.15 | carrier lock 0.04 below 0.59 |
| 8psk_4dB_4012 | 8psk | 4fsk | `low_confidence` | 3.47e-01 | no | 0.48614 ⚠ | 12 | 2.30 | the receiver estimates its own output BER at 0.347, over the 0.05 a lock should produce - it is describing a demodulatio |
| 8psk_4dB_5012 | 8psk | 2fsk | `low_confidence` | 3.02e-01 | no | 0.48155 ⚠ | 12 | 2.34 | the receiver estimates its own output BER at 0.302, over the 0.05 a lock should produce - it is describing a demodulatio |
| 8psk_4dB_6012 | 8psk | 2fsk | `low_confidence` | 3.22e-01 | no | 0.48063 ⚠ | 12 | 2.31 | the receiver estimates its own output BER at 0.322, over the 0.05 a lock should produce - it is describing a demodulatio |
| 8psk_4dB_7012 | 8psk | 8psk | `low_confidence` | 3.81e-02 | no | 0.48368 ⚠ | 12 | 2.31 | carrier lock 0.12 below 0.30 |
| 8psk_4dB_8012 | 8psk | 2fsk | `low_confidence` | 2.81e-01 | no | 0.47975 ⚠ | 12 | 2.31 | the receiver estimates its own output BER at 0.281, over the 0.05 a lock should produce - it is describing a demodulatio |

## Cost

The search considers up to 12 full receiver runs and rejects the rest with one FFT each. Median 0.36 s per file, worst 9.91 s, against a 20 s budget and a 90 s whole-pipeline window. The screen is what makes that true: without it the same candidate list is 6 modulations x 3 rates x 5 offsets of full chain runs.

## Known gaps, stated - 5 Sep

- **8-PSK and 16-QAM at 4 dB do not decode, on any arm.** That is the operating envelope and not a lock-detection failure: `truth-params` does not decode them either, at a median raw bit error rate of 0.23 and 0.31 with the true rate and no offset. Nothing in S3 recovers a stream the demodulator cannot demodulate, and the checks correctly refuse all of them.
- **16-QAM at 8 dB lands just the wrong side of the decode line, and knows it.** Seven files, raw bit error rate 0.0117-0.0124 against the 1% this study calls decoding, with the receiver's own estimate at 0.0100-0.0109 - right to within 13%, `status: ok`, correctly. They are counted as misses here and they are not misses downstream: 1.2% is inside the 3% Nehal measured as the ceiling for statistical code recovery. The number to move is the demodulator's, not the threshold's, and moving the threshold to claim them would be changing the definition of the gate to pass it.
- **FSK below 10 dB was the largest single gap, and most of it was not S3's.** S2's symbol rate is exact on 224 of 252 files. The 28 exceptions are every 2-FSK and 4-FSK file at 4 and 8 dB, wrong by up to 81% - and `fsk_order_hypotheses` comes back empty on exactly those 28, not on all files as this report said on 4 Sep. **Dheeraj** has this documented and quantified in `reports/s2_envelope.md` as a deliberate low-SNR-only gap; what that write-up could not know is what it costs downstream, which is the whole of it: handed the true rate, S3 decodes all 28 at a median raw bit error rate of 0.004. The receiver was never the problem on those files. S3 now rescues the rate for itself (`lockcheck.strongest_line`, `reports/s3_rate_rescue.md`), which closes the gap from this side without touching S2 - but fixing the envelope predicate at source is still worth more, because every stage downstream of S2 inherits the wrong rate and only this one now works around it.
- **A correction to what this report said on 4 Sep about `2fsk_4dB_2024`.** It was written up as a presence-threshold near miss - line score 4.4 against a limit of 4.5 - with the conclusion that 4 dB needed a better statistic rather than a looser number. The statistic was fine. Measured today: the 4.4 was scored at 48 479 Hz, the rate S2 offered; at the true 50 000 Hz the same statistic on the same file scores **45.2**, which is five times the limit for declaring a line present. The threshold was never what stood in the way, the rate was, and a study of the threshold would have spent the day tuning a number that was already right.
- **Choosing the modulation is still not S3's job.** Dheeraj's classifier has landed and `receive_best` reads its ranking through `params_from_s2`, taking the first clean lock instead of running every survivor - which is where the drop in median time comes from. Where the classifier is wrong the search still recovers, because an unranked modulation is tried last rather than not at all.
