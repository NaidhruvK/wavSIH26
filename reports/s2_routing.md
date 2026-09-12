# S2 symbol-rate estimator routing — measured, and changed

**Date:** 12 Sep 2026. **Stage:** S2. **Files:** `pipeline/s2_estimate.py`,
`service/orchestrator.py` (`adapt_s2`).

## What was wrong

`estimate()` chose between the two symbol-rate estimators with

```python
constant_envelope = envelope_cv < 0.25       # std(|x|) / mean(|x|)
```

and the 7 Sep note on that line already said what it really measures:

> this routing statistic is an SNR test wearing a modulation test's name —
> measured identically for 2fsk and 4fsk to three decimal places at every SNR,
> and it tracks 1/sqrt(2*SNR_linear) almost exactly. It is not choosing between
> modulations; it is choosing between "SNR above ~9dB" and not, and below that
> line it silently misroutes FSK to the linear CFO path with no failure signal
> (status stays "ok").

That prediction is now confirmed with numbers, and it cost real answers.

## How it surfaced

The first off-air signals ever put through this pipeline: **TRISAT** (FSK, 9766
baud) and **KS-1Q** (FSK, 20000 baud), both real amateur-satellite recordings
whose documented framing is CCSDS Concatenated — conv r=1/2 K=7 with
`0o171, 0o133` plus Reed-Solomon, the code S4 searches for. Both baud rates were
confirmed present in the audio by a cyclostationary check outside Raaya
(9765.7 Hz and 20000.3 Hz against documented 9766 and 20000).

```
2fsk_20dB (synthetic, in-corpus)   envelope_cv = 0.070  -> FSK estimator   correct
trisat    (real off-air FSK)       envelope_cv = 0.387  -> linear          WRONG
ks_1q     (real off-air FSK)       envelope_cv = 0.503  -> linear          WRONG
```

Real off-air FSK carries roughly **5.5x the envelope variation** of the
synthetic corpus, so it fails a test every corpus capture passes easily. S2
returned 1590 Hz for a 9766 baud signal, with `status="ok"`.

## The replacement, and why it is not another threshold

Each estimator already returns its own ranked peak list, scored as height over
the local median. Those scores are **not comparable between the two**, because
they are computed on different transforms — `|x|^2` for the linear estimator,
instantaneous frequency for the FSK one. On TRISAT the linear estimator scored
112.4 and the FSK one 34.3, and the FSK one was right.

What *is* comparable is each estimator's top peak over **its own runner-up** —
dimensionless, internal to one transform, and it answers the question that
actually separates the two cases: one line, or a forest?

```
TRISAT, linear : 1590(112.4), 2030(108.5), 2989(105.1)   dominance 1.04  forest
TRISAT, fsk    : 9766( 34.3), 8865(  4.8), 12850( 4.7)   dominance 7.14  one line
```

So: run both, keep the one whose own peak stood out. No threshold on
`envelope_cv`, and no new constant anywhere.

## Measurement — all 252 captures in `zoo/corpus/rf`

Symbol rate within 1% of truth (`fs / sps` from the truth JSON, read only to
score the answer):

| routing rule | correct |
|---|---|
| `envelope_cv < 0.25` (previous) | 224 / 252 — **88.9%** |
| higher peak dominance (current) | 252 / 252 — **100.0%** |

**Regressions: 0. Rescues: 28.**

| scheme | previous | current | envelope_cv range |
|---|---|---|---|
| bpsk | 42/42 | 42/42 | 0.405–0.455 |
| qpsk | 42/42 | 42/42 | 0.290–0.422 |
| 8psk | 42/42 | 42/42 | 0.279–0.421 |
| 16qam | 42/42 | 42/42 | 0.404–0.469 |
| 2fsk | 28/42 | **42/42** | 0.070–0.378 |
| 4fsk | 28/42 | **42/42** | 0.070–0.379 |

Every one of the 28 rescues is 2FSK or 4FSK at **4 dB or 8 dB** — precisely the
population the 7 Sep note predicted, where noise lifts `envelope_cv` over 0.25.

On the real captures: TRISAT now returns **9765.7 Hz against a true 9766**, an
error of 0.003%, on the first off-air signal this pipeline has ever seen.

## What did NOT change

**CFO routing.** `constant_envelope` still selects `estimate_cfo_fsk` vs
`estimate_cfo`, and still gates `estimate_fsk_order`. This study measured symbol
rate and nothing else, and a change to carrier-offset routing would be shipped
on someone else's measurement. The two selectors can now disagree;
`symbol_rate_estimator` reports which one produced the rate, so no caller has to
infer it from `constant_envelope`, which no longer implies it.

**The operating envelope.** End to end, verified against the matrix in
`demo/README.md`: `2fsk_8dB` 7/7, `2fsk_4dB` 4/7, `qpsk_20dB` 7/7 — unchanged.
S3's candidate search was already rescuing the bad estimate downstream, so the
end-to-end envelope never showed this defect. What changes is that S2's own
answer is now right, the misroute is visible rather than silent, and S3 starts
its search from a correct estimate instead of recovering from a wrong one.

**KS-1Q still fails, correctly.** Its 20000 baud at fs 48 kHz is **sps 2.40**,
below the 2.5 floor of `sps_range=(2.5, 40.0)`, so the true rate is outside the
search band by construction and no routing rule reaches it. S2 returns a weak
answer (dominance 1.07 — no peak stood out) and S3's screen refuses it: "no
symbol-rate line at 1399 Hz (2.4x local median, needs 4.5x)". The system
declines rather than answering wrongly, which is the intended behaviour.

## Now visible instead of silent

`adapt_s2` built its `values` mapping without `envelope_cv` or
`constant_envelope`, so the statistic surfaced on 7 Sep specifically to let a
caller distrust the routing reached nobody — not the database, not the UI, not
the report. S2's stage values now carry `symbol_rate_estimator`, `envelope_cv`
and `symbol_rate_dominance`, ordered so they appear on the stage card rather
than only in `report.json`.

A dominance near 1.0 means no peak stood out and the rate beside it should not
be trusted. That is **reported, not gated on** — S3's screen already refuses a
candidate with no symbol-rate line, and the rejection belongs there.

## Still open

**Risk #8 is narrowed, not closed.** These recordings are 48 kHz mono audio from
a receiver's output, converted to I/Q by Hilbert transform outside the pipeline.
Some of the elevated `envelope_cv` is that conversion and some is the recording
itself. A raw I/Q capture remains the test that would close it.

## Pinned by

`tests/unit/test_s2_estimate.py` — `_peak_dominance` on the real TRISAT peak
lists, the four formerly-misrouted corpus captures, the estimator/`constant_envelope`
disagreement, and high-SNR PSK controls against the rescue costing accuracy.
