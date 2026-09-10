# S3 operating envelope

**Anvith.** Regenerated from the build on `main`. Every number here comes from `reports/s3_envelope_study.py`, whose signals are now made by **`zoo.rf`** - Dheeraj's real modulator. The stand-in it used to call, `tests/fixtures/rf_channel.py`, is deleted. The parametric sweep stays a sweep rather than becoming a corpus read because it needs SNRs and samples-per-symbol the 36-file corpus does not carry; `reports/s3_lock_gate.md` is the one measured on the corpus itself.

## Gate evidence

- **31 Aug, lock rate:** 20 of 20 PSK files report `ok`. Gate asks for at least 18 of 20.
- **29 Aug, timing convergence:** worst case **817** symbols. Gate asks for under 2000.
- **30 Aug, EVM per file:** the table below, and `reports/s3_envelope.csv`.
- **3 Sep, estimated vs measured BER:** both columns below. The estimate is only meaningful where the receiver reports `ok` - see the caveat under the table.

## Per file

| File | status | lock | EVM % | timing conv | est BER | measured BER |
|---|---|---|---|---|---|---|
| bpsk_20dB_sps4 | ok | 0.981 | 10.547 | 817 | 0.00000 | 0.00000 |
| bpsk_16dB_sps4 | ok | 0.975 | 12.717 | 816 | 0.00000 | 0.00000 |
| bpsk_13dB_sps4 | ok | 0.966 | 15.419 | 104 | 0.00000 | 0.00000 |
| bpsk_10dB_sps4 | ok | 0.949 | 19.603 | 92 | 0.00000 | 0.00000 |
| bpsk_8dB_sps4 | ok | 0.929 | 23.479 | - | 0.00000 | 0.00000 |
| qpsk_20dB_sps4 | ok | 0.989 | 5.158 | 110 | 0.00000 | 0.00000 |
| qpsk_16dB_sps4 | ok | 0.973 | 8.143 | 82 | 0.00000 | 0.00000 |
| qpsk_13dB_sps4 | ok | 0.947 | 11.467 | - | 0.00000 | 0.00000 |
| qpsk_10dB_sps4 | ok | 0.896 | 16.12 | - | 0.00000 | 0.00000 |
| qpsk_8dB_sps4 | ok | 0.840 | 20.189 | - | 0.00000 | 0.00000 |
| qpsk_20dB_sps8 | ok | 0.994 | 3.707 | 102 | 0.00000 | 0.00000 |
| qpsk_16dB_sps8 | ok | 0.985 | 5.838 | 102 | 0.00000 | 0.00000 |
| qpsk_13dB_sps8 | ok | 0.971 | 8.218 | 102 | 0.00000 | 0.00000 |
| qpsk_10dB_sps8 | ok | 0.943 | 11.562 | 102 | 0.00000 | 0.00000 |
| qpsk_8dB_sps8 | ok | 0.910 | 14.502 | - | 0.00000 | 0.00000 |
| 8psk_20dB_sps4 | ok | 0.957 | 5.138 | 793 | 0.00000 | 0.00000 |
| 8psk_16dB_sps4 | ok | 0.895 | 8.115 | 106 | 0.00000 | 0.00000 |
| 8psk_13dB_sps4 | ok | 0.802 | 11.431 | 89 | 0.00000 | 0.00000 |
| 8psk_10dB_sps4 | ok | 0.641 | 16.059 | 89 | 0.00028 | 0.00028 |
| 8psk_8dB_sps4 | ok | 0.489 | 20.041 | - | 0.00267 | 0.00243 |
| 16qam_22dB_sps4 | ok | 0.922 | 6.28 | 408 | 0.00000 | 0.00000 |
| 16qam_18dB_sps4 | ok | 0.917 | 8.093 | 803 | 0.00000 | 0.00028 |
| 16qam_15dB_sps4 | ok | 0.907 | 10.389 | 813 | 0.00001 | 0.00025 |
| 16qam_13dB_sps4 | ok | 0.865 | 12.543 | 813 | 0.00015 | 0.00047 |
| 2fsk_16dB_sps8 | ok | 0.950 | - | - | 0.00000 | 0.00000 |
| 2fsk_12dB_sps8 | ok | 0.922 | - | - | 0.00000 | 0.00000 |
| 2fsk_8dB_sps8 | ok | 0.876 | - | - | 0.00000 | 0.00000 |
| 2fsk_5dB_sps8 | ok | 0.826 | - | - | 0.00000 | 0.00000 |
| 4fsk_18dB_sps8 | ok | 0.943 | - | - | 0.00000 | 0.00000 |
| 4fsk_14dB_sps8 | ok | 0.909 | - | - | 0.00000 | 0.00000 |
| 4fsk_10dB_sps8 | ok | 0.856 | - | - | 0.00000 | 0.00000 |
| 4fsk_7dB_sps8 | ok | 0.797 | - | - | 0.00000 | 0.00000 |

## The caveat that matters

**S3's estimated output BER runs optimistic, and `status == ok` does not on its own make it safe to quote.** The estimate comes from the LLR magnitudes, which are calibrated against a noise variance measured on a constellation the receiver believes it has locked. When it has not locked, the variance is measured against the wrong reference. On a dense constellation it can also be optimistic while the lock is genuine, because the nearest-symbol distance the variance is measured over understates the true error probability.

More than 4x optimistic **while reporting `ok`** -- the case that is not covered by gating on status, and the reason this list is no longer filtered to failures:

- `16qam_18dB_sps4` — estimated 0.00000, measured 0.00028 (92x)
- `16qam_15dB_sps4` — estimated 0.00001, measured 0.00025 (23x)

Anything consuming `estimated_output_ber` must gate on `status` first, and must not treat the number as an upper bound even then. S4 takes the LLRs rather than the number, so it is unaffected; the UI card and the envelope report quote it and should say which direction it errs in.

## Charts

- `reports\s3\eye_qpsk_20dB_sps4.png`
- `reports\s3\constellation_qpsk_20dB_sps4.png`
- `reports\s3\timing_qpsk_20dB_sps4.png`
- `reports\s3\eye_qpsk_10dB_sps4.png`
- `reports\s3\constellation_qpsk_10dB_sps4.png`
- `reports\s3\timing_qpsk_10dB_sps4.png`
- `reports\s3\eye_8psk_20dB_sps4.png`
- `reports\s3\constellation_8psk_20dB_sps4.png`
- `reports\s3\timing_8psk_20dB_sps4.png`
- `reports\s3\eye_16qam_22dB_sps4.png`
- `reports\s3\constellation_16qam_22dB_sps4.png`
- `reports\s3\timing_16qam_22dB_sps4.png`
- `reports\s3\s3_envelope.png`
