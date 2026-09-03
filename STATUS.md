# STATUS

One section each. Edit only under your own heading.

---

## Dheeraj — zoo · S0–S2 · classifier

_(not started here)_

**What Nehal needs from you, and by when:** see `docs/zoo-bits-only-contract.md`.
Short version: the bits-only mode, with per-file truth JSON and a configurable
*seeded* injected BER. I have been running against a local stand-in
(`tests/fixtures/local_zoo.py`) all evening; the moment yours lands I delete
mine and re-run the gate against the real corpus. Two sources of ground truth
must not coexist.

---

## Anvith — S3 receiver chain

**Landed 29 Aug – 3 Sep, all on `anvith/s3-receive`.** Two days late; the whole
column is now in.

- `pipeline/s3_receive/` — RRC matched filter with blind roll-off, Gardner
  timing, CMA and MMA blind equalisers, Costas for M-PSK and a
  decision-directed loop for QAM, non-coherent FSK tone bank, exact
  (log-sum-exp) soft demapper.
- **Six modulations registered**: `bpsk qpsk 8psk 16qam 2fsk 4fsk`. 4-FSK was
  one registration line because `FSKDemod` already generalised on order, so the
  2 Sep "all six" gate is literal rather than nearly-met; 7 Sep's 4-FSK row
  becomes measurement rather than new code.
- `pipeline/s3_receive/bitmap.py` — **the symbol-to-bit mapping, written down
  once**. Dheeraj: when the zoo grows a modulator, import
  `bits_to_symbol_indices` from here rather than restating it. Two
  implementations of one convention is a bug that shows up as a payload of
  noise with every stage reporting success.
- `tests/contract/test_llr_contract.py` — the 2 Sep gate. Written into
  Naidhruv's directory on the same basis Nehal wrote `registry/protocols.py`:
  the gate fell due and the owner had not landed. Overwrite freely; keep the
  properties.
- `tests/unit/test_s3_receive.py` (46), `tests/fixtures/rf_channel.py` (bits →
  RF, the missing half of the junction), `reports/s3_s4_junction_study.py`.

**2 Sep gate: PASS.** LLR contract green for all six — float dtype, not
confined to {0,1}, finite, `llr > 0` means bit 0 asserted against transmitted
bits, and a real continuum of magnitudes at marginal SNR.

**3 Sep gate (my row): PASS.** S3's own estimated output BER tracks the measured
one within a factor of two on every scheme, at the SNR where each is marginal.
The one case outside it is 8-PSK at 8 dB, where the receiver has genuinely lost
lock and reports `low_confidence` rather than a number.

**Nehal — four things from the junction, in order of how much they change what
you do.** Full detail in `reports/s3_s4_junction.md`.

1. **The rank test cannot select the rotation, and that breaks risk #9's stated
   mitigation.** On an un-interleaved stream, all four QPSK rotations return
   `status=ok` at confidence 0.90–0.95. Two give the true `0o171/0o133`; the
   two I/Q-swapped ones give `0o355/0o213` at period 16. They are not false
   positives in your sense — a rotation applies a fixed bit permutation to a
   linear code, and the result is a genuinely valid linear code, just not ours.
   **The discriminator you already have is span**: correct rotations recover at
   period 14, wrong ones at 16. Your "shortest span wins" rule applied *across*
   rotations picks the right one. Worth wiring into the 4 Sep fallback loop
   rather than scoring rotations on confidence.
2. **The interleaver is what fails, not the code.** Same stream, same SNRs, the
   only difference being the 8×12 block interleaver: with it, recovery works
   only at exactly zero raw BER; without it, the code comes back correctly down
   to 3 dB and 0.29 % BER, via your statistical fallback. That is your
   documented open problem, now measured against real receiver errors rather
   than injected ones.
3. **My errors are independent, not bursty — mean run length 1.00–1.22.** Your
   prediction was that real demodulator errors would land between the injected
   models. At the SNRs where a coherent receiver still holds lock they land at
   the *independent* end, because the carrier loop either tracks or slips, and
   while it tracks the errors are memoryless. Bursts appear when it slips, and
   a slipped stream is not usable anyway. So the 0.30 % independent ceiling is
   the relevant one for the junction, not the 5 % bursty one.
4. **Cost note.** A rotation carrying no code structure runs the statistical
   fallback to its full budget: ~7.5 s against ~0.1 s for one that recovers.
   Four rotations is ~15 s, not 0.4 s. Stop at the first `ok`.

**Four bugs found by measurement, all now pinned by tests.** Each cost real
time, so they are written down rather than quietly fixed:

- The Gardner error sign was inverted. The loop settled perfectly — onto the
  zero crossing half a symbol from the decision instant. Steady error trace,
  closed eye. Only the eye diagram distinguishes the two.
- Timing loop gain was expressed in absolute samples, so it halved at 8 sps.
  Showed up as a 0.13 % rate bias and a constellation that decayed over a long
  record while looking clean at the start.
- **LLRs were emitted for the acquisition transient.** On a 16-QAM file at
  22 dB, 312 bit errors — every one of them in the first 2000 bits, the
  remaining 38 000 exact. Large-and-wrong LLRs are worse for a soft decoder
  than erasures. The equaliser warm-up and the carrier settle point are both
  trimmed now, the latter against the stream's own final lock quality rather
  than an absolute threshold.
- The 16-QAM lock metric moved only between 0.24 and 0.33 across 10–20 dB, and
  0.24 was a stream decoding at 49 % BER. No threshold fits in that gap. Fixed
  with the reduced-constellation trick: measure on the top quartile by
  magnitude, which for 16-QAM is the corners, and they sit at exact multiples
  of 45°.

**Stated plainly, not hidden**

- Max-log demapping was replaced with exact log-sum-exp. Max-log is biased
  over-confident on 16-QAM — it reported 0.00076 BER against an actual 0.00310.
  Fine for feeding a decoder, not fine when the stage also has to report how
  good its output is.
- The non-coherent FSK LLR carries a **measured** calibration constant of 2.0,
  not a derived one. It holds across both FSK orders and a 4 dB span, which is
  why I trust it as a missing term rather than a fudge, but somebody should
  derive it properly.
- Blind roll-off estimation reads high at wide roll-off: 0.60 for a true 0.50,
  within 0.05 at 0.2 and 0.35. Costs well under a decibel. October window.
- Everything is measured against `tests/fixtures/rf_channel.py` driving Nehal's
  `local_zoo`, because there is still no zoo. **Dheeraj: the moment yours
  lands, my fixture dies and I re-run every number.**
- **I am on Python 3.12, not the pinned 3.11.9** — no 3.11 on this machine yet.
  Nehal's 225 tests pass unchanged under it and scipy resolves to 1.18.0 rather
  than the pinned 1.17.1. Fixing before the 6 Sep clean rebuild; flagging it now
  because it means my numbers are not yet byte-comparable with Nehal's.

**Needs:** Dheeraj's zoo. Naidhruv's real `contracts/` — `S3Result` in
`pipeline/s3_receive/result.py` is shaped for `StageResult`, point me at the
Pydantic model and I will conform exactly. And branch protection on `main`,
which Nehal has now asked for twice.

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
