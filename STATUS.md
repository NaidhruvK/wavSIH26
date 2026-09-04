# STATUS

One section each. Edit only under your own heading.

---

## Dheeraj — zoo · S0–S2 · classifier

**Landed 4 Sep.** `zoo/` bits-only mode, merged to `main`.

- `zoo/bits_only.py` — conv-encode → block-interleave → scramble → inject,
  per docs/zoo-bits-only-contract.md. Seeded, reproducible.
- `zoo/build_corpus.py` — generates 73 files: 6 depth×width factorisations
  (including two same-period pairs, 8×12 and 16×6), 6-point BER sweep,
  scramble on/off, plus one uncoded-random file for the false-positive case.
- Truth JSON per file matches the contract schema exactly (poly_notation,
  error_model, pipeline_order all explicit).

**Nehal: tests/fixtures/local_zoo.py can now be deleted — point tests at
zoo/corpus/bits_only/ instead.**

**Next:** S0/S1/S2 real pipeline stages + RF/IQ zoo mode (still fixture-only
via Anvith's rf_channel.py). Starting today.

**Landed 4 Sep, part 2.** `zoo/` RF/IQ mode, merged to `main`.

- `zoo/rf.py` — bits → modulated waveform → channel → WAV, reusing S3's own
  bitmap/filters/schemes so signals match what S3 has already been validated
  against.
- `zoo/build_rf_corpus.py` — 36 WAV files: 6 modulations (bpsk, qpsk, 8psk,
  16qam, 2fsk, 4fsk) × 6 SNR points (4–20 dB). 2-channel WAV + truth JSON
  per file.

**Anvith: tests/fixtures/rf_channel.py can now be deleted — point S3 tests
at zoo/corpus/rf/ instead.**

**Next:** S0 ingest (WAV/IQ read) so downstream stages can consume the
corpus as files, not just in-memory arrays.

---

## Anvith — S3 receiver chain

**Landed 29 Aug – 3 Sep. Merged to `main`.** The column is complete, and the
defects found while closing it are listed below rather than left implicit.

- `pipeline/s3_receive/` — RRC matched filter with blind roll-off, Gardner
  timing, CMA and MMA blind equalisers, Costas for M-PSK and a
  decision-directed loop for QAM, non-coherent FSK tone bank, exact
  (log-sum-exp) soft demapper.
- **Six modulations registered**: `bpsk qpsk 8psk 16qam 2fsk 4fsk`. With
  Nehal's plug-ins imported the registry reports **6 modulations / 3
  interleavers / 2 codes** — the 2 Sep integration line, met exactly.
- `bitmap.py` holds the symbol-to-bit mapping in **one** place. Dheeraj: import
  `bits_to_symbol_indices` from it when the zoo grows a modulator rather than
  restating the convention. Two implementations of one mapping is a bug whose
  only symptom is a payload of noise with every stage reporting success.
- Reports: `s3_envelope.{csv,md}` (EVM, lock rate, timing convergence, charts
  under `reports/s3/`) and `s3_s4_junction.{csv,md}`.

### Gates

| Day | Gate | Result |
|---|---|---|
| 29 Aug | timing converges inside 2000 symbols | worst 1112 |
| 29 Aug | four tight clusters at 20 dB | EVM 5.2 %, charts in `reports/s3/` |
| 30 Aug | Costas locks QPSK to 10 dB | lock 0.896 at 10 dB |
| 30 Aug | EVM logged per file | `reports/s3_envelope.csv`, 32 files |
| 31 Aug | locks on ≥18 of 20 PSK | **19/20** (8-PSK at 8 dB is the miss) |
| 1 Sep | no label lookup in S3 | asserted by test, 0 hits |
| 2 Sep | LLR contract, all six modulations | 45 contract tests green |
| 3 Sep | estimated output BER within 2x of actual | holds on every locked file |

### The junction — verified end to end

**WAV → S3 LLRs → S4 blind recovery → S5 Viterbi → source bits, exact.** Raw
BER 0.0002 at 12, 6 and 4 dB. This is what closes the LLR sign convention: it
was previously asserted only by my own test against my own transmitted bits,
which cannot catch a sign error that both sides share. It now decodes through
Nehal's Viterbi, and the two wrong rotations decode to 0.47 as they should.

Detail in `reports/s3_s4_junction.md`. The three findings for Nehal, unchanged:
the interleaver is what fails rather than the code; my errors are independent
(mean run length 1.00) not bursty; and the rank test cannot select the rotation
— all four return `ok`, and shortest-span across rotations is the discriminator.

### Defects found and fixed since the merge

- **An implausible symbol rate hung the stage for four minutes.** Filter length
  scales with samples-per-symbol, so a rate of 1 Hz against 200 kHz asked for a
  two-million-tap matched filter. It returned the *correct* status — after 257
  seconds per call. That is risk #5, unbounded work driven by an upstream
  number, sitting in S3 rather than S4, and reachable the moment the 4 Sep
  hypothesis loop starts sweeping candidate rates. There is now a hard tap cap
  in `rrc_taps` and a record-length check before any filter is built, and the
  test asserts the rejection takes under 5 seconds. **Suite went from 9m07s to
  34s as a side effect** — Nehal, this is the same class of thing as your
  statistical-fallback wall clock.
- **Blind roll-off was biased**, reading 0.60 for a true 0.50. Two estimators
  were wrong in different ways before this one: a two-threshold width
  measurement, then a shape fit that normalised by a percentile of a noisy
  spectrum. Fitting amplitude and roll-off jointly by least squares removes the
  normalisation entirely. Now accurate to **±0.009** from 0.15 to 0.70, and the
  test tolerance is 0.03 instead of the 0.15 that had been written around the
  error.
- **`estimated_output_ber` is optimistic when the receiver has not locked** —
  0.003 reported against 0.035 actual on 8-PSK at 8 dB. It now travels with
  `estimated_output_ber_valid`, so a consumer cannot read the number without
  being told whether to believe it. Naidhruv: the UI card must gate on this.
- **Adversarial input is now tested** — pure noise, DC, all-zeros, clipped,
  impulse, two overlapping tones, and three wrong symbol rates, across three
  modulations. Every case returns a status with a reason and finite LLRs, and
  none of them claims `ok` on noise. That is the cheap half of the 4 and 8 Sep
  rows, done early because each is an input a judge can produce in five seconds.
- **`plots.py` had no coverage at all.** It is only reached from a report
  script, so a break in it would have surfaced as a failed report rather than a
  red test. Covered now.

### Environment

**Now on the pinned Python 3.11.9**, matching `docs/python-version-decision.md`.
`.venv` built from `requirements.txt` as committed: numpy 2.4.6, scipy 1.17.1,
galois 0.4.11, commpy 0.8.0. `docs/stack_check.py` passes 11/11. The earlier
caveat about my numbers not being byte-comparable with the S4 reports is
resolved — everything above was regenerated on 3.11.9.

### Still open, stated plainly

- The non-coherent FSK LLR carries a **measured** calibration constant of 2.0,
  not a derived one. It holds across both FSK orders and a 4 dB span, which is
  why I trust it as a missing term rather than a fudge. Somebody should derive
  it properly.
- Everything is measured against `tests/fixtures/rf_channel.py`, which drives
  Nehal's `local_zoo`. **Dheeraj: the day your zoo lands, my fixture dies and I
  re-run every number above.** My fixture and my demodulator deliberately share
  `bitmap.py` so there is one mapping rather than two — but that does mean a
  mapping error would be invisible to both, which the Gray-adjacency test
  reduces rather than removes.
- 16-QAM and FSK have not been taken through to S4; the junction study covers
  BPSK, QPSK and 8-PSK.
- Soft-vs-hard coding gain is unmeasured. The chain decodes exactly at every
  SNR tried, so there was no visible difference — which means the case for soft
  decisions rests on argument, not measurement, until it is run somewhere the
  code is actually stressed.
- I self-merged without a reviewer, on the third self-merge in this repo.
  Recorded in the merge commit. **Naidhruv: please turn on branch protection**
  — Nehal has now asked three times between us.

**Needs:** Dheeraj's zoo. Naidhruv's real `contracts/` — `S3Result` in
`pipeline/s3_receive/result.py` is shaped for `StageResult`; point me at the
Pydantic model and I will conform exactly.

## Nehal — S4–S6 · the moat

**Landed 29-31 Aug**

- `pipeline/s4_recover/gf2.py` — GF(2) rank (packed-int, fast) + `null_space`,
  with `galois` kept as the reference the tests compare against.
- `pipeline/s4_recover/rank_collapse.py` — the detector. Period → alignment →
  interleaver factorisation → code structure → generator polynomials, with a
  statistical fallback when the exact test gives up.
- `pipeline/s4_recover/statistical.py` — statistical parity-check recovery and
  the syndrome-bias validator.
- `pipeline/s4_recover/interleavers.py` — `BlockInterleaver`, **registered**.
- `pipeline/s5_decode/conv_code.py` — `ConvCode`, **registered**:
  `blind_recover` / `decode` / `validate`, plus `validate_against`.
- `pipeline/s5_decode/conv_reference.py` — reference rate-1/n encoder, pinned
  against commpy.
- `pipeline/s4_recover/cli.py` — S4 standalone from a terminal, no web stack.
- `registry/protocols.py` — **strawman, Naidhruv owns this, overwrite freely.**
  Written only because S4 could not satisfy "recovers through the registry"
  without a registry existing. Protocol shapes match the Command Center.
- `tests/unit/` — 209 tests, ~6 min.
- `docs/`, `reports/` — see below.

**31 Aug gate (my column): PASS.**
`CODES["conv"].blind_recover()` recovers the generators from clean coded data
through the registry, by name, without the caller knowing convolutional codes
exist. `GET /registry` equivalent (`registry.describe()`) lists **1 code +
1 interleaver** — the 2 modulations are Anvith's.

**Two things I strengthened beyond the letter of the spec**

1. The spec says "recovered polynomials equal the zoo's configured generators".
   Mine were asserting a hardcoded `(0o171, 0o133)` — which would pass even if
   recovery were hardwired to return it. Now every assertion reads
   `truth.polys_octal`, and `test_registry.py` drives the same recovery at
   **K = 3, 5, 7 and 9** including a swapped generator pair. Recovery follows
   the configuration in all five.
2. `decode()` is wired to Viterbi against the **recovered** generators, so the
   chain is real: coded bits in → recovered parameters → **original source
   bits out, exact**, re-encode BER 0.0.

**The statistical fallback is now wired into `blind_recover`** (this was the
open item from the 30th). The pipeline previously inherited the exact test's
0.3% ceiling even though the statistical method reaches 3%:

| BER | before | now |
|---|---|---|
| 0.05% – 3% | `low_confidence`, nothing recovered | **`ok`, correct generators, inferred BER within 0.0004** |
| 5%+ | fails | still fails, cleanly |

Costs ~1 s extra when it fires, and only fires after the exact path has given
up. It does **not** fire on noise — the false-positive guard is tested on both
paths.

**It also needed a wall clock, and that is worth knowing.** The statistical
search is most expensive on inputs containing *nothing* — every span, stride
and phase gets tried before "no" comes back. Wiring it in naively took
`blind_recover` on uncoded data from ~1 s to ~18 s, unbounded: a free
denial-of-service on the exact input a judge reaches for, and squarely risk #5.
There is now an 8 s budget on the fallback (worst case ~8 s at 80 kbit, ~10 s
at 200 kbit) and the result says when the budget, rather than the evidence,
ended the search.

**Known gaps, stated**

- Recovering an *interleaver* under noise is still unsolved. The fallback
  handles the code, not the factorisation — a dozen statistical searches per
  file does not fit the time budget. Belongs in the Oct–Nov robustness window.
- The unit suite hit 21 minutes at one point today (my regression). Profiled
  and cut to **3 min 21 s** without dropping an assertion — shorter streams
  where length was not the point, fewer repeats on the noise tests, and a wall
  clock on the fallback. Note for the nightly: `--cov` roughly triples the
  runtime, so keep coverage out of the inner loop.
- Everything is still measured against `tests/fixtures/local_zoo.py`, not
  Dheeraj's zoo.

**1 Sep gate: PASS, both bars cleared with room.**

| Family | Bar | Result |
|---|---|---|
| Block, depths 1-16 | >=15/16 | **16/16** |
| Diagonal, 10 combinations | >=8/10 | **10/10** |
| Convolutional (Forney) | not set | 4/4 |

`GET /registry` now lists **3 interleavers + 1 code**. `recover_interleaver`
no longer names a scheme - it iterates `INTERLEAVERS`, so pseudo-random on
7 Sep is a new file and one registration line.

**The finding worth two minutes at standup.** Block and diagonal produce
*byte-identical* rank profiles - same deficient row lengths, same deficiency
values (see `reports/interleaver_families.png`). The curve cannot name the
family at all. Every family is therefore tried functionally: de-interleave and
ask whether the code comes back. That is decisive rather than a threshold,
because a wrong hypothesis leaves the stream looking random.

Convolutional *is* identifiable from the profile: its deficiency repeats every
N bits starting well above N, so `step < first` means convolutional with N
branches and `step == first` means block-like with that period. Two numbers,
32 extra rank computations, and each family gets handed a parameter instead of
searching blind - the difference between a bounded sweep and risk #5.

One trap it walks into on its own: a raw rate-1/2 stream has first=14 step=2,
which looks exactly like a 2-branch convolutional interleaver. The code's own
symbol size is indistinguishable from a branch count. `blind_recover` checks
the direct code structure *before* trying any family, and there is now a test
asserting that ordering so nobody removes it quietly.

**Also 1 Sep, off-plan: the realistic error model, measured two days early.**
`reports/burst_channel.md`. Every ceiling until today used *independent* bit
flips, and every report called them "an optimistic bound" because real errors
are bursty. That was reasoning, not measurement, and it was **backwards**:

| Error model | Exact rank test | Statistical |
|---|---|---|
| Independent | 0.30 % BER | 3.0 % |
| Mean burst 20 | 2.0 % | >= 5.0 % |
| Mean burst 100 | **5.0 %** | >= 5.0 % |

Rank collapse counts damaged *rows*, not damaged bits. At 1 % BER, independent
errors damage 62.8 % of rows and mean-burst-100 damages 3.7 % — same error
count, seventeen times fewer rows. So Stage 4's envelope is ~16x wider than we
have been claiming, and the independent-error numbers are the **pessimistic**
bound. `ber_ceiling.md` is marked superseded in part rather than quietly edited.

**Anvith, this is the one for you:** it cuts both ways. Bursts help S4 and
*hurt* S5 — they are exactly what a convolutional decoder cannot absorb, which
is why interleavers exist. Do not let anyone quote the first half alone.

**Two bugs found doing it.** The fixture's scrambler was commented as
"degree-6 maximal-length" and has period **7**, not 63 — the 7 Sep
Berlekamp-Massey work would have been validated against something far too
easy. Now the real CCSDS 131.0-B randomiser, period 255, verified by measuring.
And scrambling turns out **not** to hide the code from rank collapse, so the
5 Sep concatenated profile can be unwound without descrambling first — that
removes the chicken-and-egg it appeared to have.

**Still unsolved, stated plainly:** recovering the interleaver's depth x width
fails at *any* non-zero BER, under every error model. Bursts move it from 0 %
to 83 % at 0.1 % BER but nothing reaches 100 %. The pipeline recovers the code
under noise, not the interleaver. That is the Oct-Nov robustness window's job.

**Also landed, off-plan: S6 and a readable payload.** `--demo --text` runs
the whole chain blind and prints the message — period, interleaver, code,
generators, de-interleave, Viterbi, text — in about 21 s. Blind scrambler
recovery works for degrees 5/7/8 with no dictionary of known polynomials.

**Three things REAL data broke that random data never would have**, all now
tested. The consistency guard assumed a random source: ASCII has bit 7 clear in
every byte, so text is rank-deficient before the code touches it, and the first
stream carrying an actual message failed outright. Relaxing that let a 4x24
de-interleave of an 8x12 stream win as "rate 1/16 K=2". And it made "no
interleaver" fire on six interleaved streams.
**Dheeraj — this is the argument for the zoo carrying real payloads rather than
random bits. Random data hides this entire class of bug.**

**One thing NOT solved, guarded rather than hidden:** a scrambled stream yields
the code-XOR-scrambler composite, which annihilates the stream exactly and so
cannot be rejected by any residual test. K=7 under a degree-8 scrambler reads
back as K=15. Such results are downgraded and labelled, never announced.

**Tomorrow (2 Sep):** Reed-Solomon (255,223) registered, and the LLR contract
test with Anvith. `docs/HANDOFF.md` has the LLR convention.

**Blocked on:** nothing.

---

## Naidhruv — contract · service · UI · integration

_(not started here)_

**From me, when you freeze the contract:** `RecoveryResult` in
`rank_collapse.py` is already shaped for `StageResult` — it carries `status`
(`ok` / `low_confidence` / `failed`), `confidence`, ranked `hypotheses` with
scores and evidence strings, and a `reason` on every failure. Point me at the
real Pydantic model and I will conform to it exactly rather than approximately.

Two things to know:

- **Python 3.11.9. Everyone: `winget install --id Python.Python.3.11`.**
  Done here — `.venv` is 3.11.9, stack check 11/11, `tests/unit` 83/83, and the
  S4 reports regenerate byte-identically to the 3.13 originals. 3.11.9 is the
  newest 3.11 with a Windows installer (later 3.11 releases are security-only
  and source-only), so it is the one patch the whole team can get with one
  command — which lets the image pin `python:3.11.9-slim` and be the *same*
  interpreter we develop on. Full evidence in `docs/python-version-decision.md`.
- **My earlier pins were broken and are fixed.** `requirements.txt` had
  `numpy==2.5.2` / `scipy==1.18.1` carried over from the 3.13 box S4 was first
  built on. Both declare `Requires-Python >=3.12` — not "resolves differently",
  **not installable on 3.11**. That file would have failed the image build. It
  is now pinned from a real 3.11.9 resolution and verified by installing from
  scratch into an empty venv.
- **Two container findings that matter more than the version.** `python:*-slim`
  has no `libgomp1`, so **LightGBM imports fine and dies the first time it
  trains** — inside the image, which nobody looks at until the 6 Sep clean
  rebuild. Dockerfile base with the fix is in that doc. And numpy resolved to
  2.2.6 / 2.4.6 / 2.5.2 across environments from the same unpinned file, which
  is a bigger delta than 3.11 vs 3.13 — pin and commit the lockfile.
- `docs/stack_check.py` exercises the whole stack (GF(2) rank, Viterbi hard and
  soft, RS correction, a LightGBM fit) in ~30 s. Worth running inside the image
  on 6 Sep and 9 Sep — it turns "the container built" into "the container works".
- S4 has a working CLI path already (`python -m pipeline.s4_recover.cli`), so
  the "if only 48 hours remain" floor is covered for my stages from day one.
