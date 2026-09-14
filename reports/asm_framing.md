# S6 framing on the CCSDS ASM — shipped, measured, and scoped

**Date:** 14 Sep 2026. **Stage:** S6. **Files:** `pipeline/s6_frame/payload.py`
(`find_asm`, `extract_text`), `service/orchestrator.py` (`adapt_s6`),
`web/src/components/PayloadViewer.jsx`. **Capture:**
`demo/signals/qpsk_20dB_asm_telemetry.wav` (`demo/make_asm_telemetry_capture.py`).
**Studies:** `reports/asm_framing_study.py` (and `--geometry`),
`demo/make_asm_telemetry_capture.py --sweep`.

## The gap

S6 had a `raw.find(b"\x1a\xcf\xfc\x1d")` on the decoded **bytes**, and no capture
anywhere in the repo carried the marker, so no run had ever exercised it. The
payload panel never displayed `has_header`, and told every viewer "no stage in
this chain performs frame synchronisation". So the choice was: ship a capture
that hits the ASM, or stop implying S6 is general.

## What shipped

- **`find_asm`, a bit-level correlator** for `1ACFFC1D` in both polarities,
  tolerating 2 bit errors in 32. A **lock** needs ≥ 2 markers at one consistent
  spacing, so the frame length is measured, not configured.
- **A lock realigns the payload onto the marker** and emits one frame body per
  line with the markers removed. Joined together, each later marker had decoded
  mid-text as replacement glyphs.
- **A lock sets polarity.** Previously S6 chose polarity by printable fraction,
  which is a coin flip for binary data. On a random-payload framed stream it
  flipped an upright stream and reported the header as `E53003E2`, the
  complement of the marker it had found. Fixed and pinned by a test.
- **A single chance match does nothing.** 5 of 200 random 100 000-bit streams
  contain one; realigning on it would call noise a header.
- **Panel:** `ASM LOCK · 1ACFFC1D` badge, a `Frames 3 × 223 B` pill, and a note
  saying this is sync on a known marker.

## Measured

**S4 survival and ASM detection, bits domain.** Rate-1/2 K=7 code, 8×12 block
interleaver, 12 start offsets per arm:

| Source | S4 correct | Old byte search | Bit-level lock |
|---|---|---|---|
| random bytes, no ASM | 12 / 12 | 0 / 12 | 0 / 12 |
| demo message repeated **exactly**, no ASM | **1 / 12** | 0 / 12 | 0 / 12 |
| ASM + random bytes | 12 / 12 | 12 / 12 | **12 / 12** |
| ASM + housekeeping text varying per frame | 12 / 12 | 12 / 12 | **12 / 12** |

**Why bit level.** With 8×12 at rate ½, each block is 48 source bits, so the
decode always starts on a byte boundary and a byte search happens to work. A 5×8
block is 20 source bits:

| 5×8 interleaver, ASM + text, 10 offsets | S4 decodable | Old byte search | Bit-level lock |
|---|---|---|---|
| | 10 / 10 | **1 / 10** | **10 / 10** |

**Through the real orchestrator from the WAV** (`--sweep`, all 12 generator
offsets): **12 of 12** reach all seven stages ok **and** ASM lock, 3 markers per
decode, frame 1 784 bits = 223 bytes, 8.9–12.3 s each.

**Through the upload API** (the path the UI uses), the shipped capture:

| Result | Value |
|---|---|
| Stages ok | 7/7 |
| Time | 12.4 s |
| `asm_lock` / `asm_hits` / `asm_frame_bits` | True / 3 / 1784 |
| Header | `1ACFFC1D` |
| Printable | 98.3 % |

Payload text from the same run, one frame per line:

```
HK SEQ=00001 BATT=7.37V TEMP=+20.7C MODE=NOMINAL RSSI=-095 …
HK SEQ=00002 BATT=7.44V TEMP=+21.4C MODE=NOMINAL RSSI=-100 …
```

The headline capture `qpsk_20dB_textpayload` is unchanged on the same server:
7/7, no lock, no header.

## What the gap actually is

The structured-source gap is **not** "text" and **not** "framing". Varying
housekeeping text in ASM frames recovers at 12 of 12 offsets. A single message
repeated exactly recovers at 1 of 12. The exact long periodicity of the source is
what defeats the rank collapse, and a marker does not fix that.

## Say this, and only this

> S6 is printable-text extraction plus bit-level synchronisation on a **known**
> marker, the CCSDS ASM, in either polarity. It is not a general frame
> synchroniser: it does not discover an unknown header. A source that repeats
> exactly still declines at S4.

## Limits

- Known marker only. No unknown-header discovery, no frame-length hypothesis
  without a marker.
- A lock needs ≥ 2 markers inside the decoded prefix. The service decodes
  12 000 coded bits = 750 source bytes, so frames longer than about 370 bytes
  will show at most one marker and **no lock**.
- No CRC or frame-header field parsing.
- Synthetic capture.
