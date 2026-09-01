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


def extract_text(bits, min_printable: float = 0.85) -> PayloadReport:
    """Decode to text, and say honestly whether it looks like text at all.

    The printable fraction is the guard. Random bits are ~30% printable, so a
    high fraction is strong evidence the whole chain - parameters, alignment,
    de-interleaving, decoding - was right. Reporting bytes without that number
    would let noise be presented as a payload.
    """
    raw = bits_to_bytes(bits)
    if not raw:
        return PayloadReport(0, 0.0, "", False)
    printable = sum(1 for b in raw if b in PRINTABLE) / len(raw)
    text = raw.decode("utf-8", errors="replace")
    return PayloadReport(len(raw), printable, text, printable >= min_printable)
