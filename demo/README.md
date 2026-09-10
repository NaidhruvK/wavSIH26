# Raaya — the demo, and exactly what it proves

Eight captures, blind, through all seven real stages. **Nothing about any file
is supplied to the recovery.** The truth JSON beside each capture is read only
to score the answer afterwards.

## Run it

```bash
python demo/run_demo.py            # one pass
python demo/run_demo.py --twice    # the gate: correct, twice consecutively
```

Exit code is 0 only if every capture passed every pass, so it is a gate and not
just a screen.

**What a pass means, exactly.** For each capture the runner scores four things
against the truth JSON beside it: the modulation was identified; the
interleaver family, depth, width and period S4 recovered EQUAL the truth; the
code rate, constraint length K and both generator polynomials EQUAL the truth;
and all seven stages reported ok inside 90 s. Before 10 Sep it scored only the
modulation name and the stage statuses, so a run that recovered the wrong
interleaver would still have printed a pass.

The truth JSON is read ONLY to score the answer, never to produce it.

In the container:

```bash
docker run --rm --network none raaya:v1.0 python demo/run_demo.py --twice
```

`--network none` is deliberate: the target deployment is air-gapped, and the
demo must prove it needs nothing from a network.

The single-file headline demo, which generates its own stream and then recovers
it blind, prints the recovered message as text:

```bash
python -m pipeline.s4_recover.cli --demo --text
```

## The eight captures, and why these

| capture | modulation | SNR |
|---|---|---|
| `bpsk_20dB_2005` | BPSK | 20 dB |
| `qpsk_20dB_2011` | QPSK | 20 dB |
| `8psk_20dB_2017` | 8-PSK | 20 dB |
| `16qam_20dB_2023` | 16-QAM | 20 dB |
| `2fsk_20dB_2029` | 2-FSK | 20 dB |
| `4fsk_20dB_2035` | 4-FSK | 20 dB |
| `qpsk_15dB_2010` | QPSK | 15 dB |
| `16qam_15dB_2022` | 16-QAM | 15 dB |

All six modulations, plus two lower-SNR captures to show the envelope is not a
cliff at 20 dB.

## The operating envelope — measured, not claimed

Every modulation, every corpus SNR, through the real orchestrator. Cells are
stages reporting `ok` out of seven:

| | 4 dB | 8 dB | 10 dB | 13 dB | 15 dB | 20 dB |
|---|---|---|---|---|---|---|
| BPSK | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| QPSK | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 8-PSK | 3/7 | 4/7 | 4/7 | 7/7 | 7/7 | 7/7 |
| 16-QAM | 3/7 | 4/7 | 4/7 | 4/7 | 7/7 | 7/7 |
| 2-FSK | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| 4-FSK | 4/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |

**Everything completes at ≥ 15 dB. 16-QAM needs ≥ 15 dB, 8-PSK ≥ 13 dB.**

The half worth saying out loud: **every one of the ten sub-envelope cases fails
honestly.** Either `FAILED — no rank collapse at any period from 8 to 152; the
search stopped there because …` or `LOW_CONFIDENCE — period found but no
factorisation restored a code`. Not one produced a confident wrong answer. The
boundary is stated as a number and the system declines outside it.

That is why a 16-QAM capture at 13 dB is **not** in this set — it does not
complete, and it is excluded for that measured reason.

## What the recovered bits are checked against

The gate above scores PARAMETERS. The bits themselves are scored by
`tests/e2e/test_decoded_bits_match_transmitter.py`, which regenerates the
payload the transmitter actually sent (the corpus generator is seeded, and the
seed is in the filename) and compares it against what S5 decoded.

Measured 10 Sep across all eight captures: **every residual bit error sits at
index 6 or lower, and three of the eight are exact from bit 0.** Those first
few bits are a Viterbi decoder entering the trellis mid-codeword with no state
history. Past bit 6 there is not one wrong bit in any capture.

Say it this way to a scientist: the chain returns the transmitted payload bit
for bit, apart from a decoder start-up transient of at most seven bits at the
head of the stream.

## If a judge asks to change something

**Safe:** any capture in `zoo/corpus/rf/` at ≥ 15 dB; any modulation; re-running
any number of times; running with the network off; running the CLI with the API
stopped.

**Will decline, by design:** captures below the envelope above; uncoded or
random data; a stream that repeats exactly (it is refused as carrying no
information, because any "code" found in it is an artifact of the repetition).

**Do not change:** the parameters of `--demo --text`. That demo pins
`start_offset=0`. A repeating text payload at a non-zero offset defeats the rank
collapse — measured 1 of 10 offsets, against 10 of 10 for an unstructured
payload. It is a known and documented gap (STATUS.md, `docs/HANDOFF.md`), it
fails honestly rather than wrongly, and it is the gap most likely to matter on
real telemetry, which carries repeating frame headers.

## If it breaks in front of a judge

1. Switch to the already-warm backup machine.
2. Run the CLI path instead — it needs no API and no network:
   `python -m pipeline.s4_recover.cli --demo --text`
3. Fall back to the tagged image: `git checkout v1.0 && docker compose up`.

Do not debug forward in front of the panel.
