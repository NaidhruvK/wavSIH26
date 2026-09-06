# The rate rescue: what it finds, and what it refuses - 5 Sep

**Anvith.** Regenerate with `python reports/s3_rate_rescue_study.py`. FFTs only, no receiver chain, so it is cheap to re-run when the corpus changes.

## 1. On a real capture, does it find the right rate?

Asking each file's own family, over all 252 corpus files:

- **252/252** land within 1% of the true symbol rate.
- Worst relative error 0.0000%, median 0.0000%.
- Line score at the proposed rate: 19.7 .. 196.9, against a `LINE_PRESENT_LIMIT` of 8.0.

By modulation and SNR - `found/files`, within 1%:

| modulation | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB |
|---|---|---|---|---|---|---|
| 16qam | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 2fsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 4fsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 8psk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| bpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| qpsk | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |

## 2. On noise, is the proposal refused?

The rescue proposes the strongest line in the spectrum, and noise has a strongest line too. What stops it mattering is that the proposal re-enters the same presence screen as every other candidate. So the question is not what score noise reaches - it is what the screen says about the rate noise proposes.

| population | draws | screen `fail` | `unknown` | `pass` | worst score |
|---|---|---|---|---|---|
| `noise-200000` | 128 | 116 | 12 | **0** | 4.85 |
| `noise-640000` | 128 | 128 | 0 | **0** | 2.91 |
| `noise-80000` | 128 | 125 | 3 | **0** | 4.73 |

`pass` is the column that matters and it reads **0**. `LINE_ABSENT_LIMIT` is 4.5 and `LINE_PRESENT_LIMIT` is 8.0; a proposal landing in the band between them comes back `unknown`, which does not veto, so those candidates do reach the chain and are refused by the checks downstream of it. That is the same path a marginal S2 rate already took before this existed, and `test_the_rate_rescue_does_not_let_noise_through` pins the outcome end to end rather than trusting this table.

