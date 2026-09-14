# Sampling frequency — what the samples can tell you, and a detector that did not ship

**Date:** 13 Sep 2026. **Stages:** S0, S1. **Files:** `pipeline/s0_ingest.py`
(`fs_source`), `pipeline/s1_detect.py` (`check_sampling_rate`),
`service/orchestrator.py` (`adapt_s0`, `adapt_s1`). **Study:**
`reports/sampling_rate_study.py`.

## The gap

The PS asks for sampling frequency. Raaya read fs from the WAV header or a caller
hint. For a raw `.IQ` file with no hint, `s0_ingest` wrote
`fs = fs_hint or 200_000.0` and passed the invented number on **unlabelled**.
Every Hz figure downstream — symbol rate, CFO, bandwidth — was then scaled by an
unknown factor while looking measured.

## The physics

fs is the label on the time axis, not a property of the numbers. Relabel a
200 kHz capture as 400 kHz and no sample changes. Every Hz estimate doubles and
every dimensionless one stays put. The study does exactly that:

```
fs=200000  {'occupied_fraction': 0.292, 'oversampling': 3.42, 'fs_observable': False}
fs=400000  {'occupied_fraction': 0.292, 'oversampling': 3.42, 'fs_observable': False}
every field identical: True
```

So **absolute fs cannot be estimated from a waveform without an external
reference**, such as a known symbol rate or a known carrier. Anything that
returned one would be inventing it.

## What shipped

- **Provenance.** `S0Result.fs_source` is `wav_header`, `caller_hint` or
  `assumed_default`. An assumed default also carries a reason saying which Hz
  values scale with the assumption. It sits directly after `fs` on the stage card.
- **Relabel-invariant ratios.** S1 reports `occupied_fraction` (99 % signal-power
  bandwidth / fs) and `oversampling`. S2 already reports samples per symbol. These
  are properties of the samples. The ratio is SNR-sensitive in the same way the
  existing occupied-bandwidth estimator is: QPSK sps = 4 measures 0.292 at 20 dB
  and 0.674 at 5 dB.
- **The Waterfall tab.** S1 had always computed the spectrogram, and the adapter
  dropped it, so the UI showed "unavailable" on every run. It is now written as
  a `waterfall_plot` artifact: rows are time, decimated to ≤ 256 × 256.

## What did not ship: an aliasing detector

The idea: an under-sampled capture wraps, and wrapped energy should land at the
band edges, so edge power should flag it. It was built and measured on 42
correctly sampled captures (BPSK/QPSK/8PSK/16QAM, sps 2/4/8, β 0.2/0.35/0.5,
5/20 dB, CFO-shifted) and 12 genuinely under-sampled ones (decimated without an
anti-alias filter to an effective sps of 1.14–1.60).

| Population | Edge power fraction |
|---|---|
| Correctly sampled (42) | 0.00005 – 0.00483 |
| Under-sampled (12) | 0.00000 – 0.00531 |

The populations overlap completely. **0 of 12 aliased captures were flagged.**
The cause: once the spectrum fills the band, the percentile noise floor lands on
the folded skirts and subtracts exactly the energy the test looks for. A detector
that says "consistent" on every aliased input is worse than none, so it was
removed. The study keeps the statistic so the negative result is reproducible.

## Limits

- Absolute fs is not estimated. The honest claim is **fs from the header or hint,
  labelled with its source, plus fs-independent parameters measured blind**.
- Aliasing is not detected.
