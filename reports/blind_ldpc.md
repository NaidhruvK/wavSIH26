# Blind LDPC — closed-set identification from the upload path

**Date:** 13 Sep 2026. **Stage:** S5. **Files:** `pipeline/s5_decode/ldpc_catalogue.py`
(new), `pipeline/s5_decode/ldpc_code.py` (`blind_recover`), `registry/ldpc_catalogue/`
(new), `service/orchestrator.py` (`_run_s5`, `adapt_s5`). **Study:**
`reports/blind_ldpc_study.py`.

## The gap, which was two gaps

1. `LDPCCode.blind_recover` returned `None` unconditionally.
2. **The LDPC decoder could not be reached from the upload button.** `_run_s5`
   named one plug-in, `CODES.get("conv")`. It declined outright whenever S4 had
   not locked a rate-1/2 convolutional code, so `reed-solomon` and `ldpc` were
   registered and tested but never called on the service path.

## Two different problems

| | Open-set | Closed-set |
|---|---|---|
| Question | recover an arbitrary unknown H | which H, out of a known list, and at what offset |
| Status | **still refused** — no reliable method at real receiver error rates | **implemented** |

The closed-set problem is the one a SIGINT receiver usually faces, because
downlinks use published codes. It has the same shape as two searches the repo
already trusted: the CCSDS interleaver's six legal depths, and the LTE QPP table.

## Method

For each catalogue entry and each of its n codeword offsets, count the failed
parity checks on the **hard decisions**:

- wrong H, or right H at the wrong offset: each check fails with probability ½
- right H at bit error rate ε, row weight w: P(fail) = (1 − (1 − 2ε)^w) / 2

The statistic is z = √N · (1 − 2·p̂). A match needs **z ≥ 8.0**, **p̂ ≤ 0.25**, and
**z ≥ 2× the runner-up** (when the runner-up also clears 8.0).

Belief propagation is deliberately not used to decide. BP against a wrong H can
converge to a wrong codeword with a zero syndrome, whereas counting failed checks
never changes a bit. A two-pass offset search keeps the cost down: a 48-row screen
over all offsets, then the full H on the top 4.

## Findings during the work

- **The nominal null is the wrong null.** The offset search reports the best of n
  alignments, so the null is an order statistic. The measured null is below; the
  8σ normal-tail p-value is not quoted.
- **Nested catalogue entries produced a near false positive.** The first reference
  construction shared an identity block row across lengths. A true n = 192 stream
  scored **z = +7.54 against the wrong n = 96 matrix**, 0.46 below threshold. Two
  fixes shipped: the construction no longer nests (seeded on n), and the
  runner-up ratio now covers the general class. A test builds H plus a subset of
  H's rows and asserts refusal.
- **Every linear code accepts the zero word**, so an all-zero stream ties the
  whole catalogue at a perfect score. A guard reads the input (near-constant or
  exactly periodic streams are refused) before any scoring.

## Measured

Catalogue: 7 entries — 802.16e (WiMAX) n = 1440 r½ and n = 960 r¾, two MacKay
(3,6) n = 96 codes (all four from commpy's published designs), and three
`reference-*` constructions of ours at n = 48/96/192.

| Test | Result |
|---|---|
| Identify each entry, start shifted 37 bits, 6+ blocks | **7 / 7** exact code **and** exact offset, 0.00–0.23 s |
| True-code z | +12.0 (n = 48) … +65.7 (n = 1440) |
| Worst wrong-code z, any stream vs any other entry | **+3.0** |
| 200 random streams vs n = 48 entry | mean +2.24, p99 +3.50, max **+3.67**, 0 over 8.0 |
| Winner / runner-up on real matches | 6.3× … 24.2× (rule is 2×) |
| Refused: random, zeros, ones, alternating, period-8, biased P(1)=0.7, ASCII | **7 / 7** |
| Bit errors, n = 96 Gallager, 12 blocks | identified at 0.5, 1, 2, 3, 5 % (z = +8.6 at 5 %); refused at 8 %, 10 % |
| Identification output → `decode` | 12 / 12 blocks converge to zero syndrome |
| Per-plugin blind cost, 24 000-LLR stream | conv 0.00 s, ldpc 0.27 s, reed-solomon 2.22 s |

## S5 is now registry-driven

1. If S4 locked a rate-1/2 conv code with generators, S5 takes that route
   (unchanged, including the CCSDS outer RS peel).
2. Otherwise **every registered code's `blind_recover` is asked**, bounded by a
   9 s clock. The first match decodes. What was tried is recorded
   (`codes_tried`), and a plug-in the clock did not reach is reported as not
   reached.

`adapt_s5` no longer describes every decode as a "trellis traceback". An LDPC
decode reports belief propagation, the blocks that converged and the identified
code's name. Parity-check matrices are reduced to their shape before they enter
the report.

**Through `orchestrate()` from a QPSK WAV at 20 dB:** S5 identified
`gallager-n96-r1_2-963` blind, decoded 235 / 235 blocks to zero syndrome, and
output 11 280 bits in 2.2–2.9 s. It recorded `conv: declined; reed-solomon:
declined` (`tests/e2e/test_e2e_blind_families.py`).

## Limits — say these out loud

- **Closed-set only.** A code not in `registry/ldpc_catalogue/` is refused as "no
  catalogue match". It is never matched to the nearest entry.
- **CCSDS 231.1-O-1, DVB-S2 and 802.11n matrices are not in the catalogue.**
  There is no verified copy here. Adding one is dropping an alist file into the
  directory, with no code change. Until then, do not claim those standards.
- The `reference-*` entries are our constructions, and are named as such.
- Needs ≥ 6 codeword blocks, aligned hard decisions, and no bit slips within
  the scored blocks.
- The identification z is measured on synthetic streams, not off-air captures.
