"""S6: turn recovered bits back into something a person can read.

The last step of the chain, and the one that decides whether anyone believes
the rest of it. Recovered parameters are a claim a viewer has to trust;
readable text arriving out of a file the system was told nothing about is not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["PayloadReport", "bits_to_bytes", "extract_text"]

PRINTABLE = set(range(32, 127)) | {9, 10, 13}


@dataclass
class PayloadReport:
    n_bytes: int
    printable_fraction: float
    text: str
    looks_like_text: bool
    inverted: bool = False        # was the stream read in inverted polarity?

    def preview(self, width: int = 220) -> str:
        t = self.text[:width].replace("\n", " ")
        return t + ("..." if len(self.text) > width else "")


def bits_to_bytes(bits) -> bytes:
    """MSB-first, which is the convention everything else in the chain uses."""
    arr = np.asarray(bits, dtype=np.uint8).ravel()
    arr = arr[: len(arr) // 8 * 8]
    if arr.size == 0:
        return b""
    return np.packbits(arr).tobytes()


def _printable_fraction(raw: bytes) -> float:
    return sum(1 for b in raw if b in PRINTABLE) / len(raw)


def extract_text(bits, min_printable: float = 0.85,
                 resolve_polarity: bool = True) -> PayloadReport:
    """Decode to text, and say honestly whether it looks like text at all.

    The printable fraction is the guard. Random bits are ~30% printable, so a
    high fraction is strong evidence the whole chain - parameters, alignment,
    de-interleaving, decoding - was right. Reporting bytes without that number
    would let noise be presented as a payload.

    POLARITY, which is risk #9 arriving exactly as the register predicted it
    ("decode succeeds but bits are inverted"). A coherent receiver cannot
    distinguish 0 degrees from 180 degrees, so half the rotations S3 offers
    carry the whole stream inverted. Both recover the same interleaver, the
    same code and the same generators - the rank test is blind to inversion -
    and both decode without complaint. One yields the message and the other
    yields its complement. Measured 4 Sep on a real capture: rotation 2 gave
    printable 1.000 and rotation 0 gave 0.001 on the same file, same
    parameters.

    The printable fraction is already the evidence needed to settle it, so
    both polarities are read and the better one is kept. This is decisive
    rather than a threshold WHEN THE PAYLOAD IS TEXT, and honest about the
    case where it is not: for a random payload the two polarities are equally
    plausible and nothing here can separate them. That case needs a sync
    marker - the CCSDS attached sync marker is the standard answer and it is
    7 Sep framing work. Until then `inverted` says which way the stream was
    read, so the claim travels with the caveat.
    """
    raw = bits_to_bytes(bits)
    if not raw:
        return PayloadReport(0, 0.0, "", False)

    printable = _printable_fraction(raw)
    inverted = False
    if resolve_polarity:
        flipped = (np.frombuffer(raw, dtype=np.uint8) ^ 0xFF).tobytes()
        flipped_printable = _printable_fraction(flipped)
        if flipped_printable > printable:
            raw, printable, inverted = flipped, flipped_printable, True

    text = raw.decode("utf-8", errors="replace")
    return PayloadReport(len(raw), printable, text,
                         printable >= min_printable, inverted)
