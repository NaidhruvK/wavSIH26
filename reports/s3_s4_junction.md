# The S3 to S4 junction, measured

**Anvith, 3 Sep.** Real demodulator output into Stage 4 for the first time. Every prior ceiling was measured against injected errors; this one is not.

Stream: 120 000 source bits, rate 1/2 K=7, generators 0o171/0o133, no scrambler, and **no injected errors** - every error below was made by the receiver. Two arms, identical but for the interleaver: one block interleaved 8x12 (period 96), one with none at all, so a failure can be attributed to the interleaver or to the code rather than to the junction as a whole.

`raw BER` is the best rotation, counting a fully inverted stream as a match. `false code` counts rotations that returned `ok` with the WRONG generators.

| Arm | Modulation | SNR | lock | raw BER | est BER | mean burst | recovered | false code |
|---|---|---|---|---|---|---|---|---|
| interleaved | 8psk | 14 dB | 0.845 | 0.00000 | 0.00000 | 0.00 | 1/8 | 0 |
| interleaved | 8psk | 10 dB | 0.657 | 0.00012 | 0.00028 | 1.00 | 0/8 | 0 |
| interleaved | bpsk | 4 dB | 0.873 | 0.00000 | 0.00001 | 0.00 | 0/2 | 0 |
| interleaved | bpsk | 2 dB | 0.801 | 0.00015 | 0.00030 | 1.00 | 0/2 | 0 |
| interleaved | bpsk | 1 dB | 0.754 | 0.00078 | 0.00116 | 1.00 | 0/2 | 0 |
| interleaved | qpsk | 10 dB | 0.898 | 0.00000 | 0.00000 | 0.00 | 2/4 | 0 |
| interleaved | qpsk | 6 dB | 0.760 | 0.00012 | 0.00005 | 1.00 | 0/4 | 0 |
| interleaved | qpsk | 5 dB | 0.707 | 0.00023 | 0.00024 | 1.00 | 0/4 | 0 |
| interleaved | qpsk | 4 dB | 0.643 | 0.00095 | 0.00097 | 1.00 | 0/4 | 0 |
| no-interleaver | qpsk | 10 dB | 0.894 | 0.00000 | 0.00000 | 0.00 | 2/4 | 2 |
| no-interleaver | qpsk | 5 dB | 0.699 | 0.00027 | 0.00026 | 1.00 | 2/4 | 2 |
| no-interleaver | qpsk | 3 dB | 0.561 | 0.00288 | 0.00282 | 1.00 | 2/4 | 2 |

## What this says

**1. The interleaver is what fails, not the code.**

With the 8x12 interleaver, the highest raw BER from which recovery still succeeded was **0.00000** - which is to say it needs the stream to be exact. The first errors that appear, at 1.2e-4, take it to zero.

Without the interleaver, on the same bits through the same receiver, the code comes back correctly at a raw BER of **0.00288**, via the statistical fallback. That is close to the 0.30 % independent-error ceiling `ber_ceiling.md` already records - reached here with real demodulator errors rather than injected ones.

This confirms Nehal's documented open problem (recovering the interleaver's depth x width fails at any non-zero BER) from the other side of the junction. **The consequence for the demo envelope: the full chain needs an SNR high enough for ZERO raw bit errors, not merely a low BER.** For QPSK on this stream that is about 8-10 dB.

**2. My errors are independent, not bursty.**

Mean error-run length across every case that had errors: **1.00** bits. Nehal's injected models were 1.0 (independent) and 20 or 100 (Gilbert-Elliott), and the prediction was that real demodulator errors would land between them.

They land at the independent end, for a reason worth keeping: a carrier loop either tracks or slips. While it tracks, the errors are thermal noise crossing a decision boundary, which is memoryless. When it slips, the stream is not bursty but unusable. So the independent-error ceiling governs this junction, and the 16x wider envelope in `burst_channel.md` is real but does not apply here.

**3. The rank test cannot select the rotation.**

This one changes a design decision, so it is worth reading carefully.

On the un-interleaved arm, **all four** QPSK rotations return `status=ok` at 0.90-0.95 confidence. Two give the true 0o171/0o133. The two I/Q-swapped ones give **0o355/0o213 at period 16** - a confident, wrong answer, at every SNR tested.

They are not false positives in the risk #15 sense. A rotation applies a fixed permutation to the bits, and a permuted linear code is still a linear code, so S4 is correctly reporting a structure that genuinely is there. It simply is not ours.

So carrying every rotation and letting the rank test select - the stated mitigation for risk #9 - does not discriminate on its own. **The discriminator already exists**: the correct rotations recover at period 14, the wrong ones at 16. Nehal's rank-by-shortest-span rule, applied ACROSS rotations rather than within one stream, picks the right one in every case here. Worth wiring into the 4 Sep hypothesis-fallback loop, instead of ranking rotations by confidence, which is identical for all four.

On the interleaved arm no false codes appear, because the wrong rotations fail at the interleaver stage before they ever reach the code. That is luck, not protection.

**4. Cost.**

A rotation carrying no recoverable structure is the expensive case: the statistical fallback runs to its full budget before saying no, about 7.5 s against 0.1 s for one that recovers. Four rotations is ~15 s, and 8-PSK's eight are ~60 s. The orchestrator should stop at the first `ok`, and should try the likely rotations first.

## Method

`tests/fixtures/rf_channel.py` takes Nehal's `local_zoo.make_stream()` output, modulates it, and puts it through noise, a carrier offset and a fractional timing offset. S3 demodulates blind, from S2-shaped parameters only. The resulting LLRs go to `blind_recover()` unchanged. Regenerate with `python reports/s3_s4_junction_study.py`; re-render this file from the CSV with `--render-only`.

Measured on Python 3.12 with scipy 1.18.0, **not** the pinned 3.11.9 / 1.17.1. Nehal's 225 tests pass on this interpreter, but these numbers are not yet byte-comparable with the S4 reports.
