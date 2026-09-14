# Pseudo-random interleavers — recovered blind where they are algebraic, characterised where they are not

**Date:** 13 Sep 2026. **Stage:** S4. **Files:** `pipeline/s4_recover/pseudorandom.py` (new),
`pipeline/s4_recover/rank_collapse.py`, `service/orchestrator.py` (`adapt_s4`,
`REQUIRED_PLUGIN_MODULES`). **Study:** `reports/pseudorandom_interleaver_study.py`,
raw rows in `reports/pseudorandom_interleavers.csv`.

## The gap

SIH26147 lists pseudo-random interleaving. Raaya recovered block, diagonal,
convolutional and CCSDS symbol interleavers, and the S4 docstring had promised
pseudo-random "on 7 Sep". It never landed. A scrambler is not a PR interleaver,
so there was nothing to point a judge at.

## What can and cannot be recovered — the argument, not a budget

Write the received stream as rows of length L. A period-K interleaver permutes
positions within each period, so at L = K it permutes the **columns** of that
matrix and nothing else. Column permutation is multiplication by an invertible
permutation matrix P, and over GF(2)

```
rank(R·P) = rank(R)
```

Two consequences:

- **The period is always observable.** The rank collapse at L = K is identical
  for block, diagonal and every pseudo-random interleaver of period K. S4 already
  measured this for block and diagonal without it being the stated point.
- **The permutation is not observable from the rank profile.** All K! permutations
  give byte-identical profiles. For K = 96 that is log2(96!) = **498.3 bits** of
  key; for K = 512, 3875.2. No capture length reduces it.

So an *unstructured, keyed* permutation cannot be inverted from a single capture,
and Raaya does not claim to. But deployed "pseudo-random" interleavers are not
unstructured — the receiver has to rebuild the table — they are generated from a
few parameters. That space is searchable.

## What was built

**The QPP family** (`qpp`): π(i) = (f1·i + f2·i²) mod K. This is the 3GPP LTE turbo
interleaver (TS 36.212 Table 5.1.3-3) and, at f2 = 0, the textbook
relative-prime interleaver. Registered as one INTERLEAVERS plug-in; S4 sweeps it
like every other family.

- The 60 LTE triples with K ≤ 512 are tried first. All 60 are verified as
  bijections at import. The table only orders the search; the open sweep covers
  the same space, so a mis-transcribed entry would cost time, not correctness.
- Bijectivity is **computed**, not taken from the Sun–Takeshita condition.
- **Coefficient pairs alias.** (f1 + K/2, f2 + K/2) gives the same map as (f1, f2)
  for even K, because (K/2)·i(i+1) ≡ 0 mod K. At K = 96 the 512 valid pairs are
  only 256 distinct permutations. Candidates are de-duplicated by permutation,
  and **recovery is scored by permutation equality**. A coefficient-comparing test
  first reported correct recoveries as failures.
- **Prefilter.** One GF(2) rank on a 3 600-bit prefix at L = 36. A correct
  de-interleave must be rank deficient there, for every rate-1/2..1/4 code with
  K ≤ 9. It costs 0.12 ms against 7.6–8.3 ms for the full functional test, and
  lets 1–2 of 2 048–8 192 permutations through. It can only reject. Everything it
  passes still goes through the unchanged functional test.

**The honest verdict for what cannot be inverted.** Suppose S4 finds a period and
no family restores a code. It used to report *"period found but no factorisation
restored a code"*. It now returns `interleaver_verdict = period-only` with the
period, how many candidates and families were tried, and the key-space bound. The
adapter surfaces these as fields (`interleaver_verdict`, `permutation_recovered`,
`period_structure`, `key_space_bits`).

**It says "period-K structure", not "interleaving".** The first draft said
*"interleaving is present at period 96"*. Run on an LDPC downlink through the
real pipeline, that sentence was wrong. The collapse was the LDPC code's own
block length (n = 96). A block code collapses at multiples of n exactly as a block
interleaver does at its period. S5 then identified and decoded the code. The
wording now names both readings.

## Budget fixes this required

| Problem | Before | After |
|---|---|---|
| `recover_interleaver` shared one 600-candidate counter across families in registry order, so a family registered last could be starved | order-dependent | per-family cap, plus a 9 s wall clock checked per candidate |
| `blind_recover`'s statistical fallback ran after the 12 s walk with its own 8 s | 18.4–19.3 s on an unstructured K = 96 permutation. **S4 timed out at 15 s and the verdict never reached the report.** | 13 s total budget: 13.2–13.4 s, then 11.5–12.4 s with the prefilter |

## Measured

Rate-1/2 K = 7 stream, 120 012 coded bits (supports periods up to 315), blind
through `blind_recover`, no truth fed in.

| Arm | Cap 288, no prefilter | Cap 32 768 + prefilter | Worst time |
|---|---|---|---|
| LTE table triples, K = 40..288 (16 sizes) | 16 / 16 | **16 / 16** | 3.5 s |
| Relative prime f2 = 0, K = 32..256 (12) | 12 / 12 | **12 / 12** | 3.2 s |
| Random off-table QPP, K = 48..192 (12) | **3 / 12** | **12 / 12** | 2.7 s |
| Unstructured keyed permutation, K = 96 (8) | not inverted, period reported, 8 / 8 | not inverted, period reported, 8 / 8 | 12.4 s |
| Regressions: block 8×12, diagonal 8×12, conv 4×1, raw coded, uncoded random | 5 / 5 | 5 / 5 | 9.0 s |

In the first column, 9 of the 12 off-table misses had the true permutation at
rank 451–1458, past the 288 cap. That column is also the version whose docstring
claimed "11 of 12" before any study had run. The claim was wrong. It is corrected
in the code and recorded here.

Through `orchestrate()` from a QPSK WAV at 20 dB, S4 returned `qpp {period 96,
f1 11, f2 24}`, rate 1/2 K = 7, generators 0o171/0o133, in 2.4 s. S5 decoded it
(`tests/e2e/test_e2e_blind_families.py`).

## Limits — say these out loud

- **Unstructured keyed permutations are not inverted.** Period and key-space
  bound only. This is a theorem, not a missing feature.
- **ARP** (DVB-RCS, IEEE 802.16e duo-binary) and the **UMTS R99** prime
  interleaver are not implemented. ARP's (P0, P1..P3) is only tractable from a
  published table, and there is no verified copy of one here. Those streams get
  the `period-only` verdict.
- **K = 512** needs about 295 000 coded bits before the period is visible. It was
  recovered once on 400 000 bits in 18.7 s, which is past the 15 s stage timeout.
  That is a CLI result, not an upload-path claim.
- The prefilter's L = 36 covers rate 1/2 up to K = 18, rate 1/3 up to K = 12 and
  rate 1/4 up to K = 9. Longer codes would be screened out under the correct
  permutation.
- All of this is exact-rank, so it inherits S4's measured noise ceiling
  (`reports/ber_ceiling.md`). Recovering an interleaver under noise remains the
  open robustness item it already was.
- Synthetic streams only.
