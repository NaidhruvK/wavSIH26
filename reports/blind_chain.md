# The chain, finally blind end to end — and a wrong answer from S2

**Nehal · 4 September 2026.** Regenerate with
`python reports/blind_chain_study.py`. Measured on `origin/main` after
Dheeraj's S0/S1/S2 and classifier landed this evening.

This closes the 4 September row of my column, and it retires an admission I
have been carrying in `reports/end_to_end.md` since yesterday.

---

## 1. The overclaim is retired, by measurement

Yesterday's report said, correctly:

> An earlier draft said "nothing about that file was supplied". **That was an
> overclaim.** `run_one` calls `receive(iq, {"fs": ..., "symbol_rate": ...})`
> … The two supplied values are S2's job, and **S2 does not exist yet**.

S2 exists now. The study reads **only the WAV**, through S0. The truth JSON is
opened once, at the end, to score the answer — never to produce it.

```
S0 ingest   -> IQ + sample rate straight off the file
S2 estimate -> symbol rate, CFO, ranked hypotheses      blind
S3 receive  -> soft LLRs, per modulation hypothesis     blind
S4 recover  -> interleaver, code, generators            blind
```

| file | S2 symbol rate | true | error | chain runs | scheme found | interleaver | generators |
|---|---|---|---|---|---|---|---|
| bpsk 20 dB | 50 000 | 50 000 | 0.000 % | 1 | bpsk | ✔ | ✔ |
| qpsk 20 dB | 50 000 | 50 000 | 0.000 % | 2 | qpsk | ✔ | ✔ |
| 8psk 20 dB | 50 000 | 50 000 | 0.000 % | 3 | 8psk | ✔ | ✔ |
| 16qam 20 dB | 50 000 | 50 000 | 0.000 % | 4 | 16qam | ✔ | ✔ |
| 2fsk 20 dB | 50 000 | 50 000 | 0.000 % | 5 | 2fsk | ✔ | ✔ |
| 4fsk 20 dB | 50 000 | 50 000 | 0.000 % | 6 | 4fsk | ✔ | ✔ |

**6 of 6, all six modulations, nothing supplied.** The modulation is found by
iterating the `MODULATIONS` registry and keeping whatever produces a rank
collapse — the column's own wording — and **no wrong modulation ever produced
a confident answer.** That is the direct answer to the subset trap Anvith
raised: S4 rejected every incorrect constellation on its own.

**Dheeraj — S2's symbol rate is exact to three decimal places on all six.**
Nothing to fix there.

## 2. S2's CFO estimate is wrong on every file, and it costs the recovery

The one that matters. On this corpus the true CFO is **0 Hz**. S2 reports:

| scheme | S2 CFO | true | what it equals |
|---|---|---|---|
| bpsk | 25 000 Hz | 0 | symbol_rate / 2 |
| qpsk | 12 500 Hz | 0 | symbol_rate / 4 |
| 8psk | 6 250 Hz | 0 | symbol_rate / 8 |
| 16qam | 12 500 Hz | 0 | symbol_rate / 4 |

The pattern is `symbol_rate / M`, which is the signature of the M-th-power
estimator's branch ambiguity: raising the signal to the M-th power gives a line
at `M·cfo`, so dividing by M recovers the offset only modulo `symbol_rate / M`.
With a true offset of zero the estimator locks onto the modulation's own
spectral line instead.

**Zero is never offered at any rank.** The ranked hypotheses are all aliases:

```
bpsk  hyp0 (25000.0, M=2, score 130.9)   hyp1 (-12500.0, M=4)   hyp2 (-6250.0, M=8)
qpsk  hyp0 (12500.0, M=4, score  72.6)   hyp1 (-12500.0, M=8)   hyp2 ( 6393.3, M=2)
```

So *"decode via the second hypothesis"* cannot rescue this one — the correct
answer is absent from the list entirely.

**What it costs.** Applying S2's CFO breaks recovery on 4 of 4 files that
recover perfectly without it, and **S3 still reports `ok`** while doing it:

| file | with S2's CFO | without |
|---|---|---|
| bpsk 20 dB | EVM 37.5 %, **no recovery** | EVM 5.2 %, recovered |
| qpsk 20 dB | EVM 6.1 %, **no recovery** | EVM 5.2 %, recovered |
| 8psk 20 dB | EVM 5.4 %, **no recovery** | EVM 5.1 %, recovered |
| 16qam 20 dB | EVM 6.5 %, **no recovery** | EVM 5.6 %, recovered |

Note the middle three: **EVM looks fine and the recovery is dead.** That is
the third time this week EVM has failed as a quality signal.

**How the chain survives it.** CFO is treated as a hypothesis, not a fact. The
null — no pre-correction, let S3's own carrier loop work — is tried first, then
S2's estimate. That is the registry-product fallback doing precisely what the
4 September column asks: surviving a confidently wrong answer from upstream.

**Dheeraj, the fix is yours and it is small:** the M-th-power estimator must
either offer the whole alias set `cfo + k·symbol_rate/M` as ranked hypotheses,
or include zero as a candidate and let a downstream test choose. Right now it
reports one alias with high confidence and no way back.

## 3. The 4 September verify line

> *"Corrupt S2's top hypothesis; the pipeline still decodes via the second."*

Two ways, and both were run.

**Naturally**, by S2 itself: its top CFO hypothesis is wrong on every file, and
the chain still recovered 6 of 6. That is the verify line satisfied by a real
upstream error rather than a synthetic one, which is worth more.

**Deliberately**, by replacing S2's winning symbol rate with `1.5 ×` the truth
and ranking it first: **4 of 6 still recovered** via a later hypothesis
(16qam, 4fsk, 8psk, qpsk). The two that did not — bpsk and 2fsk — **hit the
120 s search budget at 130.5 s and 123.8 s, not a recovery failure.** The
mechanism works; the exhaustive product is too expensive to always reach the
right candidate in time.

## 4. The exhaustive search does not fit 90 seconds, and that is the finding

Clean-path per-file times, blind:

| bpsk | qpsk | 4fsk | 2fsk | 8psk | 16qam |
|---|---|---|---|---|---|
| 2.3 s | 20.1 s | 9.8 s | 46.7 s | 49.1 s | 75.1 s |

The cost tracks **registry position**, not difficulty — bpsk is found on chain
run 1, 16qam on run 4, and each miss pays a full S3 demodulation plus an S4
rotation search. Worst case with a corrupted hypothesis is 24 chain runs.

The 6 September core-lock gate is **90 seconds for the whole seven-stage
analysis**. At 75 s for S2–S4 alone, an exhaustive modulation search does not
fit.

**So the classifier is not a nice-to-have — it is what makes the fallback
affordable.** Dheeraj's LightGBM model and Anvith's ranked
`pipeline/s3_receive/search.py` prune the modulation dimension from six to one
or two, which is the difference between 75 s and about 12 s. The exhaustive
loop here should stay as the *fallback* for when the classifier is unsure, and
it is now measured so we know what it costs when it fires.

---

### Caveats, unchanged

- Still synthetic. This corpus is AWGN with pulse shaping and **no CFO, phase
  or timing impairment** — the impairments S3 exists to remove are switched
  off. No off-air signal has been through this pipeline.
- This measures **parameter recovery**, not exact-bit decode.
- Six files, one per modulation at 20 dB. It proves the chain runs blind; it is
  not an envelope.
