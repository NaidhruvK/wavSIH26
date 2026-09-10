# experimental — NOT part of the demo set

`make_text_capture.py` builds an RF capture carrying a readable message, so the
UI's payload panel would end with the sentence on screen rather than ~39%% printable
random bits. It does not work, and the failure is informative.

Measured through the real pipeline:

    s3_receive   ok               modulation=qpsk
    s4_recover   LOW_CONFIDENCE   period=96 found, generators=None
    s5_decode    FAILED

This is the structured-source gap, reached from the direction that matters. The
generator pins `start_offset=0`, but the RECEIVER introduces its own bit offset
relative to the interleaver block boundary, so the stream S4 sees is a repeating
ASCII payload at a non-zero effective offset - the 1-in-10 case.

With `sweep_alignments=True` S4 reaches `ok` and names the interleaver, but still
returns `generators=None`, so S5 cannot decode. The sweep does not rescue it.

Why this matters beyond the demo: real telemetry carries repeating frame headers.
This is that case, and it is the gap most likely to matter on non-synthetic data.
Readable-text output is available today only through the bits-domain CLI
(`python -m pipeline.s4_recover.cli --demo --text`), which keeps offset 0.
