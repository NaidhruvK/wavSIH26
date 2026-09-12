# experimental — the offsets that DON'T work, kept as evidence

**SUPERSEDED 11 Sep. The headline claim in this file was "it does not work".
It does work, at one offset in twelve, and that capture now ships in
`demo/signals/qpsk_20dB_textpayload.wav`.** What follows is the measurement
that found it, kept because the failures are the useful part.

## What this file used to say

`make_text_capture.py` built an RF capture carrying a readable message so the
UI's payload panel would end with a sentence on screen rather than ~39 %
printable random bits. Measured through the real pipeline it gave:

    s3_receive   ok               modulation=qpsk
    s4_recover   LOW_CONFIDENCE   period=96 found, generators=None
    s5_decode    FAILED

and the conclusion drawn was that an RF capture carrying text does not decode.

## Why that conclusion was wrong

The diagnosis was right and the conclusion did not follow from it. The
diagnosis: the generator pins `start_offset=0`, but the RECEIVER contributes its
own bit offset relative to the interleaver block boundary, so what S4 sees is

    (generator offset + receiver offset) mod 96

Pinning the generator half to 0 says nothing about the sum. The conclusion drawn
was that the sum therefore cannot be controlled. It can — by moving the half
that *is* controllable until the sum lands somewhere that works.

## The sweep

Twelve candidates, one per 8 bits of generator offset, each a genuine waveform
through all seven stages of the real orchestrator:

| start_offset | S4 | S5 | printable |
|---|---|---|---|
| 0, 8, 16, 24, 32, 40, 48, 56, 64, 72 | low_confidence, generators=None | failed | — |
| 80 | ok, but generators=None | failed | — |
| **88** | **ok** | **ok** | **0.9987** |

1 of 12, which is the documented "roughly 1 offset in 10" arrived at from the
other direction. The winner was then verified three consecutive times: 7/7
stages, every recovered parameter equal to truth (period 96, block 8×12, rate
1/2, K=7, G=(0o171, 0o133)), 10.7–16.6 s.

The single non-printing byte in the 0.9987 is the leading partial byte, where
the decode starts mid-message because nothing in this chain does frame
synchronisation. It is a byte-alignment artifact, not an error surviving the
decode.

## What the shipping capture does and does not prove

It **does** prove a real blind recovery ending in a readable message from a
waveform, with the recovery never seeing the truth JSON or the text.

It does **not** prove text payloads work in general. Eleven of twelve offsets
decline. If a judge asks for a fresh text capture at a different offset, the
honest answer is that it will most likely decline at S4, that this is the known
structured-source gap, and that it fails honestly rather than producing a wrong
answer. Do not generate a new one in front of a panel.

## The files here

`make_text_capture.py`, `qpsk_20dB_textpayload.{wav,json}` in this directory are
the **offset-0 version that fails**, kept deliberately so the failure stays
reproducible. The working generator is `demo/make_text_capture.py`.
