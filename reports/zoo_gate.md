# S4 against Dheeraj's real zoo

**Nehal · 4 September 2026.** The standing job from `docs/HANDOFF.md` §9: *"the
moment Dheeraj's zoo lands, delete `tests/fixtures/local_zoo.py`, point the
tests at the real corpus, re-run the gates, report any number that moves."*

Regenerate with `python reports/zoo_gate_study.py` and
`python reports/zoo_rf_study.py`.

Two corpora landed on `main` at `96e14c6`: 73 bits-only files and 36 RF WAVs.

---

## 1. Is the zoo itself correct?

Contract compliance is read off the JSON; **correctness is not**. A corpus that
merely labels itself is not ground truth, so the streams were checked against
their own truth structurally.

| Contract item (`docs/zoo-bits-only-contract.md`) | Status |
|---|---|
| `uint8` 0/1, `.npy` | pass, all 73 |
| ≥ 150 000 coded bits | pass — 159 845 to 160 000 |
| `poly_notation`, `error_model`, `pipeline_order`, `seed`, `start_offset` | all present |
| pipeline order encode → interleave → scramble → inject | as specified |
| same period, different factorisation (8×12 **and** 16×6) | both present |
| uncoded random file, labelled | present (`uncoded_random_999`) |
| `start_offset` not a block boundary | present — e.g. 13, 72, 34, 78, 30, 44, 21 |

**The structural check.** For every clean unscrambled file, the stream was
de-interleaved at the stated offset with the stated depth×width and multiplied
by the parity check of the stated generators. Residual syndrome **0.000000 on
every one**. The data matches its own labels, independently of anything my code
believes.

`polys_octal: [121, 91]` is `0o171 / 0o133` — the same convention as S4, so
risk #10 does not bite.

## 2. Bits-only corpus — 73 files

```
clean, unscrambled     period 6/6    depth x width 6/6    generators 6/6
BER 0.001 - 0.02       full recovery 0/30
scrambled (any BER)    full recovery 0/36,  declined or downgraded 36/36
uncoded random         failed  -> declined
CONFIDENTLY WRONG ANSWERS                              0
```

**6 of 73 files fully recover, and that is not a defect — it is the published
envelope meeting a corpus deliberately built outside it.** 36 files are
scrambled and 30 carry injected errors; both are documented open problems. The
number to read is the first line and the last: everything inside the envelope
recovers completely, and nothing anywhere produces a wrong answer.

**This matters for the 4 September gate** (*"≥40 % of the corpus decodes end to
end"*). Against a corpus composed like this one, that gate is unreachable by
construction — not because recovery is weak, but because 92 % of the files are
outside the declared envelope. Either the corpus is weighted toward the
envelope or the gate is stated against the in-envelope subset. **That is a
decision for the 09:00 sync, not something to quietly reinterpret on the day.**

### Where the cliff actually is

The corpus BER grid is `0.0` then `0.001`, and everything is either perfect or
hopeless — so the grid cannot see our own operating edge. Measured with the
zoo's **own** generator (`zoo.bits_only.make_stream`, 3 seeds per point):

| injected BER | period | depth×width | generators |
|---|---|---|---|
| 0 | 3/3 | 3/3 | 3/3 |
| 2 × 10⁻⁵ | 3/3 | **0/3** | **0/3** |
| 5 × 10⁻⁵ … 2 × 10⁻³ | 3/3 | 0/3 | 0/3 |
| 5 × 10⁻³ | 0/3 | 0/3 | 0/3 |

Two separate limits, and they are three orders of magnitude apart:

- **Period detection survives to ~2 × 10⁻³**, which confirms the 0.30 % ceiling
  published in `ber_ceiling.md` — that number holds against the real zoo.
- **Factorisation and generators die at the FIRST bit error.** At 2 × 10⁻⁵ on a
  160 kbit stream that is roughly three flipped bits, and recovery goes 3/3 to
  0/3.

This independently reproduces, from the zoo side, what `end_to_end.md` found
from the receiver side. Two different measurements, two different generators,
same conclusion: **the chain needs a bit-perfect demodulation, not a good one.**

**Request to Dheeraj:** BER points at 2e-5, 5e-5, 1e-4, 2e-4, 5e-4. The whole
operating envelope lives between the corpus's 0.0 and its 0.001, and right now
no corpus file lands in it.

## 3. RF corpus — 36 WAVs, 6 modulations × 6 SNRs

The strongest end-to-end evidence available today, because each stage came from
a different person: **Dheeraj's modulator and channel → Anvith's S3 → my S4.**
`end_to_end.md` measured the same chain against *my* fixture, which is a
self-consistency check — my transmitter and my recovery could agree with each
other and both be wrong. This removes that coupling on the transmit side.

| scheme | S3 locked | period | depth×width | generators |
|---|---|---|---|---|
| bpsk | 6/6 | **6/6** | **6/6** | **6/6** |
| 2fsk | 6/6 | 5/6 | 5/6 | 5/6 |
| 4fsk | 6/6 | 5/6 | 5/6 | 5/6 |
| qpsk | 6/6 | 5/6 | 5/6 | 5/6 |
| 8psk | 6/6 | 3/6 | 3/6 | 3/6 |
| 16qam | 6/6 | 2/6 | 2/6 | 2/6 |

| SNR | full recovery |
|---|---|
| 20 dB | **6/6** |
| 15 dB | **6/6** |
| 13 dB | 5/6 |
| 10 dB | 4/6 |
| 8 dB | 4/6 |
| 4 dB | 1/6 |

**26 of 36 full recovery, across all six modulations, with zero confidently
wrong answers.**

Two honesty notes on that number:

- **It is parameter recovery, not exact-bit decode.** The Command Center
  scorecard line "end-to-end exact-bit success" additionally requires the
  Viterbi step, which this study does not run. Do not quote 26/36 against that
  row.
- **These files are EASIER than my own fixture.** The corpus sets
  `cfo_norm = 0`, `phase_rad = 0`, `timing_offset_sym = 0`; my fixture used
  1e-4, 0.7 rad and 0.3 symbols. The impairments S3 exists to remove are
  switched off here.

### S3 already knows whether S4 will succeed

The most useful thing to come out of this run, and it belongs to Anvith's stage
rather than mine. Sorting all 36 files by S3's own `estimated_output_ber`
separates the two outcomes completely:

| | files | S3 estimated output BER |
|---|---|---|
| recovered | 26 | **≤ 1.5 × 10⁻⁶** |
| failed | 10 | **≥ 7.5 × 10⁻⁵** |

Fifty-fold gap, nothing in between, no interleaving anywhere in the sorted
list. **EVM does not separate them at all** — BPSK at 4 dB has 33 % EVM and
recovers; 16-QAM at 13 dB has 11.7 % EVM and fails. The right number is the
estimated BER, not the constellation quality.

Two things follow:

- **A free pre-flight check for the orchestrator.** S3 computes this number
  already. The pipeline can decide *before* paying up to 32 s for the S4 search
  whether the search can possibly succeed, and say so on the stage card:
  *"this capture demodulates at 3 × 10⁻⁴; recovery needs better than about
  10⁻⁵"* is an answer a human can act on. A silent decline is not.
- **A third independent confirmation of the cliff.** The zoo's bits-only sweep
  puts it at 2 × 10⁻⁵ injected BER, `end_to_end.md` put it at the first bit
  error, and now the receiver's own estimate brackets it between 1.5 × 10⁻⁶ and
  7.5 × 10⁻⁵. Three measurements, three different routes, one conclusion.

Stated honestly: this is 36 files on one channel model with no CFO, phase or
timing impairment. It is a strong correlation on this corpus, not a proven law,
and it should be re-checked when S2 lands and when a real capture exists.

**Anvith — nothing here needs fixing in S3.** It locked 6/6 on every file at
every SNR, and its self-reported quality metric predicts my stage's outcome
exactly. This is a request to keep `estimated_output_ber` in the stage result
and to treat it as a first-class output, not a diagnostic.

## 4. The rotation search was spending 70 seconds to learn nothing

Found while timing the RF corpus. 8-PSK files were taking 63–72 s each against
a **90 s budget for the whole seven-stage analysis**.

The cost was not the recovery. S3 offers one LLR array per phase rotation it
cannot resolve — 2 for BPSK, 4 for QPSK, 8 for 8-PSK — and the search ran
`blind_recover` on each with the statistical fallback enabled. The fallback
spends up to 8 s of wall clock *proving a negative*, and most rotations are
wrong by construction, so it was paying the most expensive path on precisely
the inputs least likely to reward it:

| file | with fallback per rotation | screening first |
|---|---|---|
| 8-PSK 8 dB, 8 rotations | 70.3 s | **1.4 s** |
| 8-PSK 20 dB, 8 rotations | 64.0 s | **2.6 s** |
| QPSK 20 dB, 4 rotations | 18.1 s | **1.2 s** |
| BPSK 20 dB, 2 rotations | 0.6 s | 0.6 s |

**Every status was identical either way**, on all 36 files. The fallback
rescued nothing; it only burned the budget.

`pipeline/s4_recover/rotations.py` now screens every rotation with the fallback
off and re-runs with it on only when screening found nothing at all — which is
the case the statistical method was actually built for — under a 25 s wall
clock for the whole expensive pass. The capability is bounded, not removed:
"it has never fired" is not "it can never fire".

| | before | after |
|---|---|---|
| worst single file | 72.1 s | **32.3 s** |
| whole 36-file corpus | 746 s | **258 s** |
| median file | — | 2.0 s |
| recovery | 26/36 | **26/36** |
| confidently wrong | 0 | **0** |

That is the difference between fitting the 6 September core-lock budget and
not. It is offered to Naidhruv as a callable entry point so the orchestrator
does not have to rediscover either rule.

## 5. `tests/fixtures/local_zoo.py` is NOT deleted, and here is why

My own instruction said to delete it the moment the zoo landed. **Following
that instruction today would delete test coverage rather than duplication**,
because `zoo/bits_only.py` does not yet generate three things my suite depends
on:

| knob | local_zoo | zoo/bits_only | what it covers |
|---|---|---|---|
| `payload_text` | yes | **no** | every 3–4 Sep finding. Structured payloads are what exposed four false-positive paths; random bits hide the entire class |
| `mean_burst` | yes | **no** | the Gilbert-Elliott channel. Bursts move the ceiling ~16× (0.30 % → 5.0 %), so every zoo BER number is the pessimistic bound |
| diagonal / convolutional interleavers | yes | **no** | the 1 Sep gate. The corpus is block-only, so the diagonal ≥8/10 bar cannot be re-run against it |

The rule behind the instruction — *two sources of ground truth must not
coexist* — is satisfied a better way: **the gates now run on the real corpus**
(this file), and `local_zoo` is demoted from ground truth to a parametric
generator for cases the corpus cannot express. The two were checked against
each other in §1 and agree.

Delete `local_zoo` the day those three knobs exist in `zoo/`. Not before.

## 6. What moved

| | before (local_zoo) | now (real zoo) |
|---|---|---|
| clean recovery | 16/16 block depths | 6/6 corpus files |
| BER ceiling, period | 0.30 % | confirmed, dies at 5e-3 |
| BER ceiling, factorisation | "fails at any BER" | **measured: 2e-5** |
| false positives | 0 on uniform random | 0 on the whole corpus |
| modulations end to end | 1 (QPSK, my fixture) | **6 of 6** |
| worst-case file time | not measured | 72.1 s → 32.3 s |

No published number moved in the wrong direction. The two that sharpened —
the factorisation cliff and the worst-case time — both did so by being
measured properly for the first time.
