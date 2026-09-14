# Raaya — the demo, and exactly what it proves

Ten captures, blind, through all seven real stages. **Nothing about any file
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

## The captures, and why these

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
| `qpsk_20dB_textpayload` | QPSK | 20 dB |
| `qpsk_20dB_asm_telemetry` | QPSK | 20 dB |

All six modulations, plus two lower-SNR captures to show the envelope is not a
cliff at 20 dB, plus one capture carrying a readable message.

**The ninth is the one to put on screen.** The other eight carry RANDOM payload
bits, so the UI's payload panel reads ~39 % printable - which is the correct
answer for random data, and unmoving to watch. `qpsk_20dB_textpayload` carries
text, and the panel ends with the sentence on screen:

> RAAYA SIH26147 -- BLIND SIGNAL RECOVERY. This capture was demodulated,
> de-interleaved and decoded with no prior knowledge...

99.87 % printable. The single non-printing byte is the leading partial byte,
where the decode starts mid-message because this capture carries no sync marker
for S6 to frame on.

**Say what it proves, and what it does not.** It is a genuine blind recovery -
the recovery never sees the truth JSON or the message. It is NOT evidence that
text payloads work in general: the generator offset was swept through the real
pipeline and 11 of 12 offsets decline at S4. That is the known structured-source
gap. Do not generate a fresh text capture in front of a panel; see
`demo/make_text_capture.py` and `demo/experimental/README.md`.

## Framed telemetry — what S6 does, and what it does not

`demo/signals/qpsk_20dB_asm_telemetry.wav` carries CCSDS-style frames: the
attached sync marker `1ACFFC1D` followed by a 219-byte housekeeping body whose
sequence counter and readings change every frame. Upload it and the payload
panel shows **ASM LOCK · 1ACFFC1D**, three markers at a measured 1 784-bit
(223-byte) spacing, and one frame body per line:

> HK SEQ=00001 BATT=7.37V TEMP=+20.7C MODE=NOMINAL RSSI=-095 …
> HK SEQ=00002 BATT=7.44V TEMP=+21.4C MODE=NOMINAL RSSI=-100 …

**It is not a lucky offset.** `python demo/make_asm_telemetry_capture.py --sweep`
runs all 12 generator offsets through the real orchestrator: **12 of 12** reach
all seven stages ok AND an ASM lock (`reports/asm_framing.md`). Because
`run_demo.py` scores every WAV in `demo/signals/`, it is also in the gate, scored
against its truth JSON like the others: 14 Sep, 10 of 10 captures MATCH, 7/7
stages, 10.0 s for this one.

**Say exactly this about S6:** it is printable-text extraction plus bit-level
synchronisation on a **known** marker, the CCSDS ASM, in either polarity. It is
**not** a general frame synchroniser. It does not discover an unknown header,
and a source that repeats **exactly** — like the text capture's single message —
still hits the structured-source gap at S4 (1 of 12 offsets), marker or not.
What the framing study measured is narrower and true: frames whose content
varies frame to frame recover at every offset.

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
stopped; re-running the text capture as often as you like - it is deterministic.

**Will decline, by design:** captures below the envelope above; uncoded or
random data; a stream that repeats exactly (it is refused as carrying no
information, because any "code" found in it is an artifact of the repetition).

**Do not change:** the parameters of `--demo --text`. That demo pins
`start_offset=0`. A repeating text payload at a non-zero offset defeats the rank
collapse — measured 1 of 10 offsets, against 10 of 10 for an unstructured
payload. It is a known and documented gap (STATUS.md, `docs/HANDOFF.md`), and
it fails honestly rather than wrongly. Measured 14 Sep, it is narrower than
"repeating headers": a repeating sync marker and repeating field labels with
content that varies frame to frame recovered at 12 of 12 offsets. What declines
is a source that repeats EXACTLY (`reports/asm_framing.md`). Real telemetry
with long static stretches could still sit closer to the exact case, and that
has not been measured.

## If it breaks in front of a judge

1. Switch to the already-warm backup machine.
2. Run the CLI path instead — it needs no API and no network:
   `python -m pipeline.s4_recover.cli --demo --text`
3. Fall back to the tagged image: `git checkout v1.0 && docker compose up`.

Do not debug forward in front of the panel.
