"""S6: turn recovered bits back into something a person can read.

The last step of the chain, and the one that decides whether anyone believes
the rest of it. Recovered parameters are a claim a viewer has to trust;
readable text arriving out of a file the system was told nothing about is not.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

import numpy as np

__all__ = [
    "CCSDS_ASM",
    "CCSDS_ASM_INV",
    "PayloadReport",
    "bits_to_bytes",
    "calculate_byte_entropy",
    "extract_text",
    "find_asm",
    "AsmLock",
]

CCSDS_ASM = b"\x1a\xcf\xfc\x1d"
CCSDS_ASM_INV = b"\xe5\x30\x03\xe2"

PRINTABLE = set(range(32, 127)) | {9, 10, 13}


def calculate_byte_entropy(raw: bytes) -> float:
    """Calculate Shannon entropy in bits per byte (0.0 to 8.0).

    empty input -> 0.0
    identical bytes -> 0.0
    uniformly distributed byte values -> up to 8.0
    """
    if not raw:
        return 0.0
    n = len(raw)
    counts = Counter(raw)
    entropy = 0.0
    for count in counts.values():
        p = count / n
        entropy -= p * math.log2(p)
    return float(entropy)


@dataclass
class PayloadReport:
    n_bytes: int
    printable_fraction: float
    text: str
    looks_like_text: bool
    inverted: bool = False        # was the stream read in inverted polarity?
    entropy: float = 0.0          # Shannon entropy in bits per byte (0.0 to 8.0)
    has_header: bool = False
    header_hex: str = ""
    header_entropy: float = 0.0
    payload_entropy: float = 0.0
    payload_text: str = ""
    # Bit-level ASM search (find_asm). asm_lock needs ASM_MIN_HITS markers at
    # one consistent spacing; asm_bit_offset is where the first sits in the
    # decoded stream; asm_frame_bits is the measured frame length.
    asm_lock: bool = False
    asm_hits: int = 0
    asm_bit_offset: int | None = None
    asm_frame_bits: int | None = None
    asm_inverted: bool = False

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


ASM_MAX_ERRORS = 2
"""Bit errors tolerated in a 32-bit ASM match.

A random 32-bit window lands within 2 errors of the marker with probability
(1 + 32 + 496) / 2^32 = 1.2e-7, so over a 100 000-bit stream and both
polarities the expected number of chance hits is 0.025. That is why a single
hit is never called a lock - see ASM_MIN_HITS.
"""

ASM_MIN_HITS = 2
"""Hits needed, at a CONSISTENT spacing, before S6 reports an ASM lock.

Two chance hits would also need to sit a whole number of frames apart; with the
per-window rate above, that is not a thing that happens by accident. One hit is
reported as a candidate only.
"""


@dataclass
class AsmLock:
    bit_offset: int           # first hit, in the decoded stream's bit index
    inverted: bool            # matched the complement - stream polarity is flipped
    hits: int                 # matches at the frame spacing
    frame_bits: int | None    # spacing between consecutive hits, if >= 2
    errors: int               # bit errors in the first hit
    locked: bool              # hits >= ASM_MIN_HITS at a consistent spacing


def find_asm(bits, max_errors: int = ASM_MAX_ERRORS) -> AsmLock | None:
    """Bit-level search for the CCSDS attached sync marker 1ACFFC1D.

    WHY BIT-LEVEL. S6 used to search the BYTES of the decode for the marker. The
    Viterbi output starts wherever the de-interleaved stream happened to start,
    which is an arbitrary bit, not a byte boundary - so the marker was on a byte
    boundary only when that arbitrary start was a multiple of 8, and the byte
    search missed it the other seven times in eight. Framing then re-aligns the
    bytes to the marker, which is the whole point of having one.

    Both polarities are searched. A coherent receiver cannot tell 0 from 180
    degrees, and for a binary payload the marker is the only thing that can -
    the printable-fraction test S6 uses for text has nothing to work with there.

    Returns None when nothing matches within `max_errors`. A single match is
    returned with `locked=False`.
    """
    arr = np.asarray(bits, dtype=np.uint8).ravel()
    asm_bits = np.unpackbits(np.frombuffer(CCSDS_ASM, dtype=np.uint8)).astype(np.int8)
    n = asm_bits.size
    if arr.size < n:
        return None
    signed = arr.astype(np.int8) * 2 - 1
    ref = asm_bits * 2 - 1
    corr = np.correlate(signed.astype(np.int32), ref.astype(np.int32), mode="valid")
    threshold = n - 2 * max_errors                # corr = n - 2 * distance
    best = None
    for inverted, sign in ((False, 1), (True, -1)):
        hits = np.flatnonzero(sign * corr >= threshold)
        if hits.size == 0:
            continue
        frame_bits, consistent = None, 1
        if hits.size >= 2:
            gaps = np.diff(hits)
            frame_bits = int(np.bincount(gaps).argmax())
            # hits that sit a whole number of frames from the first one
            consistent = int(np.sum(((hits - hits[0]) % frame_bits) == 0))
        errors = int((n - sign * corr[hits[0]]) // 2)
        cand = AsmLock(bit_offset=int(hits[0]), inverted=inverted, hits=consistent,
                       frame_bits=frame_bits, errors=errors,
                       locked=consistent >= ASM_MIN_HITS)
        if best is None or (cand.locked, cand.hits) > (best.locked, best.hits):
            best = cand
    return best


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
        return PayloadReport(
            0, 0.0, "", False,
            inverted=False, entropy=0.0,
            has_header=False, header_hex="",
            header_entropy=0.0, payload_entropy=0.0,
            payload_text="",
        )

    # A LOCKED sync marker settles polarity; the printable fraction only settles
    # it for text. On a random payload the printable test is a coin flip, and on
    # 14 Sep it flipped an upright ASM-framed stream and reported the header as
    # E53003E2 - the complement of the marker it had found.
    lock = find_asm(bits)
    printable = _printable_fraction(raw)
    inverted = False
    if resolve_polarity:
        flipped = (np.frombuffer(raw, dtype=np.uint8) ^ 0xFF).tobytes()
        flipped_printable = _printable_fraction(flipped)
        if lock is not None and lock.locked:
            if lock.inverted:
                raw, printable, inverted = flipped, flipped_printable, True
        elif flipped_printable > printable:
            raw, printable, inverted = flipped, flipped_printable, True

    entropy = calculate_byte_entropy(raw)
    text = raw.decode("utf-8", errors="replace")

    asm_pos = raw.find(CCSDS_ASM)
    if asm_pos != -1:
        has_header = True
        header_bytes = raw[asm_pos : asm_pos + 4]
        header_hex = header_bytes.hex().upper()
        payload_bytes = raw[asm_pos + 4 :]
        header_entropy = calculate_byte_entropy(header_bytes)
        payload_entropy = calculate_byte_entropy(payload_bytes)
        payload_text = payload_bytes.decode("utf-8", errors="replace")
    else:
        asm_inv_pos = raw.find(CCSDS_ASM_INV)
        if asm_inv_pos != -1:
            has_header = True
            header_bytes = raw[asm_inv_pos : asm_inv_pos + 4]
            header_hex = header_bytes.hex().upper()
            payload_bytes = raw[asm_inv_pos + 4 :]
            header_entropy = calculate_byte_entropy(header_bytes)
            payload_entropy = calculate_byte_entropy(payload_bytes)
            payload_text = payload_bytes.decode("utf-8", errors="replace")
        else:
            has_header = False
            header_hex = ""
            header_entropy = 0.0
            payload_bytes = raw
            payload_entropy = entropy
            payload_text = text

    # The byte search above only sees a marker that happens to sit on a byte
    # boundary of the decode. The bit-level search sees it wherever it is, and
    # when it locks, the payload is re-aligned to it - which is what a sync
    # marker is for. A lock overrides the byte search, so the header is always
    # the marker read in the lock's own polarity. `text` stays as decoded.
    # LOCKED only. A single chance match (measured: 5 of 200 random 100 000-bit
    # streams have one) would otherwise re-align the payload onto noise and call
    # it a header.
    if lock is not None and lock.locked:
        arr = np.asarray(bits, dtype=np.uint8).ravel()[lock.bit_offset:]
        aligned = bits_to_bytes(arr ^ 1 if lock.inverted else arr)
        has_header = True
        header_bytes = aligned[:4]
        header_hex = header_bytes.hex().upper()
        payload_bytes = aligned[4:]
        header_entropy = calculate_byte_entropy(header_bytes)
        payload_entropy = calculate_byte_entropy(payload_bytes)
        payload_text = payload_bytes.decode("utf-8", errors="replace")
        # With a locked, byte-multiple frame length every boundary is known, so
        # the payload is the frame BODIES, one per line, markers removed. Left
        # joined, each later marker decoded mid-text as replacement glyphs.
        fb = lock.frame_bits
        if lock.locked and fb and fb % 8 == 0 and fb // 8 > 4:
            step = fb // 8
            bodies = [aligned[i + 4:i + step] for i in range(0, len(aligned), step)
                      if aligned[i:i + 4] and len(aligned[i + 4:i + step]) > 0]
            payload_text = "\n".join(b.decode("utf-8", errors="replace") for b in bodies)

    return PayloadReport(
        n_bytes=len(raw),
        printable_fraction=printable,
        text=text,
        looks_like_text=printable >= min_printable,
        inverted=inverted,
        entropy=entropy,
        has_header=has_header,
        header_hex=header_hex,
        header_entropy=header_entropy,
        payload_entropy=payload_entropy,
        payload_text=payload_text,
        asm_lock=bool(lock.locked) if lock else False,
        asm_hits=int(lock.hits) if lock else 0,
        asm_bit_offset=lock.bit_offset if lock else None,
        asm_frame_bits=lock.frame_bits if lock else None,
        asm_inverted=bool(lock.inverted) if lock else False,
    )
