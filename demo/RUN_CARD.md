# Raaya live demo — run card

One page. Two people should be able to run this without opening any generator.
**Do not create a new capture in front of the panel. Do not change the offset live.**

---

## T-15 min — before the panel sits down

```powershell
cd C:\dev\raaya
.venv\Scripts\python -m service.cli run            # serves API + UI on :8000
```

1. Open **http://localhost:8000** and check the header shows the service as healthy.
2. **Warm it once.** Upload `demo\signals\qpsk_20dB_textpayload.wav` and let it
   finish. Server start compiles the GF(2) kernels, and the first run warms the
   rest, so the live run is the second one.
3. Keep a second terminal open at `C:\dev\raaya` for the CLI backup.

## The headline — upload → wait → sentence (~17 s)

1. Drop **`demo\signals\qpsk_20dB_textpayload.wav`** on the upload zone. Leave
   the fs field alone: a WAV's header wins, and S0 shows `fs source: wav_header`.
2. Seven stage cards fill in. Expected (rehearsed 14 Sep, 16.5 s):

| Card | Point at |
|---|---|
| S2 | symbol rate ≈ 50 000 Hz at fs 200 000, so 4 samples/symbol |
| S3 | QPSK |
| S4 | **block interleaver, depth 8 × width 12, period 96 · rate 1/2, K = 7 · generators 0o171, 0o133** |
| S5 | ok, Viterbi |
| S6 | ok, **99.9 % printable** |

3. Open the **payload** panel. The sentence is on screen:
   *"RAAYA SIH26147 -- BLIND SIGNAL RECOVERY. This capture was demodulated,
   de-interleaved and decoded with no prior knowledge…"*

**Say:** "Nothing about this file was given to the pipeline. The modulation, the
interleaver's depth and width, the code rate and both generator polynomials were
all recovered from the waveform, and the message is what came out."

**If asked about the one odd glyph at the start:** "The decode starts mid-byte.
Nothing in this chain does frame sync on this capture, so the first byte is
partial."

## Optional second upload — framed telemetry (~13 s)

Drop **`demo\signals\qpsk_20dB_asm_telemetry.wav`**. All seven cards ok; the
payload panel shows **ASM LOCK · 1ACFFC1D**, `Frames 3 × 223 B`, and one
housekeeping frame per line with `HK SEQ=00001`, `00002`, `00003`.

**Say:** "S6 found the CCSDS sync marker at bit level and framed on it; the frame
length is measured, not configured. It syncs on a known marker. It does not
discover an unknown header."

## The refusal — rehearse this, so you say the reason instead of debugging (~14 s)

Drop **`zoo\corpus\rf\16qam_13dB_2021.wav`**. Expected:

| Card | Status | What it says |
|---|---|---|
| S0–S3 | ok | |
| S4 | **low confidence** | period-96 structure present, no code restored |
| S5 | failed | no registered code identified this stream (conv, reed-solomon, ldpc all declined) |
| S6 | failed | no payload to frame |

**Say:** "16-QAM needs 15 dB; we measured that boundary. At 13 dB the period is
still found, but bit errors erase the exact parity check, so S4 declines instead
of guessing, and nothing downstream invents a payload. Every one of the ten
sub-envelope cases we measured fails this way, and none gives a confident wrong
answer."

**If a judge says "change the offset" or "use your own text":** "That's our
documented gap. With a repeating text payload, 11 of 12 generator offsets decline
at S4, because structured source bits add their own rank collapses. It fails
honestly rather than wrongly, and it's the next robustness item." Do not try it
live.

## If it breaks — in this order, no debugging forward

1. **CLI, no API, no network** — rehearsed 14 Sep, 24 s, prints `TEXT RECOVERED`:
   ```powershell
   .venv\Scripts\python -m pipeline.s4_recover.cli --demo --text
   ```
2. **The gate**, eight captures scored against truth:
   `.venv\Scripts\python demo\run_demo.py`
3. **Tagged image** — `git checkout v1.0 && docker compose up`.
   ⚠ **`v1.0` predates the text capture, and no image is built on this machine
   (checked 14 Sep).** It shows the eight-capture gate, not the sentence. Only
   treat this as a headline backup after a newer tag has been cut and its image
   built.

## Rehearsal log

| Date | Who | Headline | Refusal | CLI backup | Image |
|---|---|---|---|---|---|
| 14 Sep | Claude (API upload, same file) | 7/7 ok, 16.5 s, sentence present | declined as above, 13.9 s | 23.8 s, TEXT RECOVERED | not runnable: no image, tag predates capture |
| 14 Sep | Claude (API upload) | framed telemetry: 7/7 ok, 12.4 s, ASM LOCK, 3 frames | | | |
| | person 1 | | | | |
| | person 2 | | | | |
