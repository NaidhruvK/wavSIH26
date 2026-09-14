"""S6 framing on the CCSDS attached sync marker, searched at bit level.

What reports/asm_framing.md claims, asserted:

  - the marker is found at ANY bit offset, not only on a byte boundary
  - both polarities, and a locked marker - not the printable test - sets polarity
  - a lock needs >= 2 markers at one spacing; random streams do not lock
  - a single chance match does not turn noise into a header
  - locked payload text is the frame bodies, markers removed
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s6_frame.payload import CCSDS_ASM, extract_text, find_asm  # noqa: E402

FRAME = 223


def _framed(n_frames=10, seed=0, text=False):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n_frames):
        if text:
            body = (b"HK SEQ=%05d MODE=NOMINAL " % k * 20)[:FRAME - 4]
        else:
            body = rng.integers(0, 256, FRAME - 4, dtype=np.uint8).tobytes()
        out.append(CCSDS_ASM + body)
    return np.unpackbits(np.frombuffer(b"".join(out), dtype=np.uint8))


@pytest.mark.parametrize("cut", [0, 1, 3, 7, 13, 1785])
def test_marker_found_at_any_bit_offset(cut):
    lock = find_asm(_framed()[cut:])
    assert lock is not None and lock.locked
    assert lock.frame_bits == FRAME * 8
    assert (lock.bit_offset + cut) % (FRAME * 8) == 0


@pytest.mark.parametrize("cut", [0, 5])
def test_inverted_stream_locks_and_reads_upright(cut):
    rep = extract_text(_framed()[cut:] ^ 1)
    assert rep.asm_lock and rep.asm_inverted and rep.inverted
    assert rep.header_hex == "1ACFFC1D"


def test_random_payload_header_is_the_marker_not_its_complement():
    """14 Sep: the printable-fraction polarity test flipped an upright random-
    payload stream and reported the header as E53003E2."""
    for seed in range(6):
        rep = extract_text(_framed(seed=seed))
        assert rep.asm_lock and not rep.inverted
        assert rep.header_hex == "1ACFFC1D"


def test_random_streams_do_not_lock():
    rng = np.random.default_rng(1)
    for _ in range(100):
        lock = find_asm(rng.integers(0, 2, 100_000, dtype=np.uint8))
        assert lock is None or not lock.locked


def test_a_single_chance_match_is_not_a_header():
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, 40_000, dtype=np.uint8)
    marker = np.unpackbits(np.frombuffer(CCSDS_ASM, dtype=np.uint8))
    bits[12_345:12_345 + 32] = marker                      # exactly one marker
    rep = extract_text(bits)
    assert find_asm(bits).locked is False
    assert not rep.asm_lock and not rep.has_header


def test_two_bit_errors_in_a_marker_still_lock():
    bits = _framed().copy()
    bits[1784 * 3 + 4] ^= 1
    bits[1784 * 3 + 20] ^= 1
    lock = find_asm(bits)
    assert lock.locked and lock.hits == 10


def test_locked_payload_is_one_frame_body_per_line():
    rep = extract_text(_framed(text=True)[3:])
    lines = rep.payload_text.split("\n")
    assert len(lines) >= 8
    assert all(line.startswith("HK SEQ=") for line in lines[:-1])
    assert "�" not in rep.payload_text
    assert "HK SEQ=00001" in lines[0]


def test_no_marker_leaves_the_old_behaviour():
    text = b"plain telemetry with no sync marker at all. " * 40
    rep = extract_text(np.unpackbits(np.frombuffer(text, dtype=np.uint8)))
    assert not rep.asm_lock and not rep.has_header
    assert rep.payload_text == rep.text
