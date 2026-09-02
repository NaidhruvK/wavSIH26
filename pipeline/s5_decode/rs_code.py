"""The ReedSolomon plug-in - block codes over GF(256), behind the CODES protocol.

    blind_recover(llrs)   -> recovered (n, k) and byte alignment, or None
    decode(llrs, params)  -> decoded data bits
    validate(bits)        -> a report on whether the output is plausible

WHY THIS DOES NOT USE RANK COLLAPSE, unlike the convolutional plug-in.

RS(255,223) has a binary image of dimension 223*8 = 1784 inside 255*8 = 2040,
so the rank deficiency is real - 256 - but it only appears at a row length of
2040 bits. Detecting that needs L*(L+margin) ~= 4.3 million bits before the
sweep can even reach it, against a MAX_PERIOD of 512. Rank collapse is the
right tool for convolutional codes and the wrong one here.

WHAT IT USES INSTEAD. A Reed-Solomon decoder is its own detector. Feed it a
candidate block length and parity count: on the correct hypothesis every block
decodes with zero or very few corrected symbols, and on a wrong one the decoder
either fails outright or reports corrections everywhere. That is a sharp,
cheap test, and it is honest about what it is - a search over a BOUNDED SET OF
STANDARD PROFILES, not an open-ended blind recovery. RS parameters are
standardised in practice, and claiming more than a dictionary search would be
overstating it.

Alignment matters as much as the parameters: a block boundary in the wrong
place makes a correct (n, k) look wrong, so offsets are searched too.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from registry import register_code
from pipeline.s5_decode.conv_code import llr_to_bits

__all__ = ["ReedSolomonCode", "RSParams", "STANDARD_PROFILES"]

# (n, k) pairs worth trying, most likely first. CCSDS 131.0-B specifies
# (255,223); DVB uses (204,188); the rest are common shortenings.
# Only profiles with meaningful correction power (nsym >= 16, so t >= 8).
#
# The weak shortenings (255,247) and (255,251) were removed after they caused
# wrong answers rather than missed ones. A 4-parity code corrects at most 2
# symbols, so it "fits" any block that happens to lie within distance 2 of one
# of its codewords - and at 1% BER it found such runs and was selected over the
# truth, returning confidently wrong data. A weak code fitting is near-worthless
# evidence, and including it bought nothing except a way to be wrong.
#
# The trade is stated rather than hidden: a genuine RS(255,251) stream is now
# outside the searched set and will be declined. Declining is the failure this
# project can live with.
STANDARD_PROFILES = [
    (255, 223),   # CCSDS 131.0-B - the one the problem statement names
    (255, 239),   # nsym 16
    (204, 188),   # DVB-T outer code, nsym 16
]

MIN_BLOCKS = 4          # fewer than this and "it decoded" means little
MAX_BLOCKS_TRIED = 24   # cap the work per hypothesis
ERRATA_TOLERANCE = 0.02  # corrected symbols per symbol before we disbelieve it


@dataclass
class RSParams:
    n: int
    k: int
    offset: int
    blocks_checked: int
    errata_rate: float

    @property
    def nsym(self) -> int:
        return self.n - self.k

    def as_dict(self) -> dict:
        d = asdict(self)
        d["nsym"] = self.nsym
        d["family"] = "reed-solomon"
        return d


def _bits_to_bytes(bits: np.ndarray) -> np.ndarray:
    arr = np.asarray(bits, dtype=np.uint8).ravel()
    arr = arr[: len(arr) // 8 * 8]
    return np.packbits(arr) if arr.size else np.zeros(0, dtype=np.uint8)


def _try_profile(data: np.ndarray, n: int, k: int, offset: int):
    """Try every block; return (blocks_tried, decoded_fraction, errata_rate).

    Returns the FRACTION of blocks that decode rather than rejecting on the
    first failure, because that fraction is the discriminator and the errata
    rate is not.

    Errata rate is actively misleading across profiles. A weak code corrects at
    most t = (n-k)/2 symbols, so whenever it succeeds at all it necessarily
    reports few corrections. Measured at 0.2% BER, the true RS(255,223) scored
    0.017 while a wrong RS(255,251) scored 0.008 - and "fewest corrections
    wins" therefore picked the wrong code and returned wrong data. Decode
    fraction has no such bias: the true profile decodes every block, a wrong
    one only gets lucky on some.
    """
    import reedsolo

    rs = reedsolo.RSCodec(n - k)
    tail = data[offset:]
    n_blocks = min(len(tail) // n, MAX_BLOCKS_TRIED)
    if n_blocks < MIN_BLOCKS:
        return 0, 0.0, 1.0

    ok, errata = 0, 0
    for b in range(n_blocks):
        block = bytes(tail[b * n:(b + 1) * n])
        try:
            _, _, pos = rs.decode(block)
        except Exception:
            continue
        ok += 1
        errata += len(pos)
    if ok == 0:
        return n_blocks, 0.0, 1.0
    return n_blocks, ok / float(n_blocks), errata / float(ok * n)


class ReedSolomonCode:
    """Reed-Solomon over GF(256), recovered against standard profiles."""

    name = "reed-solomon"
    detail = "RS(n,k) over GF(256), bounded search over standard profiles"

    # -- CODES protocol ----------------------------------------------------

    def blind_recover(self, llrs):
        """Identify (n, k) and the byte alignment, or None.

        None is a real answer. A stream that is not RS-coded must not be
        reported as one, and the decoder failing IS the evidence for that.
        """
        data = _bits_to_bytes(llr_to_bits(llrs))
        if data.size < STANDARD_PROFILES[0][0] * MIN_BLOCKS:
            return None

        best, best_key = None, None
        for n, k in STANDARD_PROFILES:
            for offset in range(n):          # bounded: at most n alignments
                blocks, frac, rate = _try_profile(data, n, k, offset)
                if blocks < MIN_BLOCKS or frac < 1.0 or rate > ERRATA_TOLERANCE:
                    continue
                # Rank: every block must decode (already required), then prefer
                # the STRONGEST code. A 32-parity code decoding every block is
                # a far less likely coincidence than a 4-parity one doing so,
                # and it is the claim that survives noise.
                key = (-(n - k), rate)
                cand = RSParams(n, k, offset, blocks, rate)
                if best is None or key < best_key:
                    best, best_key = cand, key
        return best

    def decode(self, llrs, params) -> np.ndarray:
        """RS-decode every whole block and return the DATA bits.

        Blocks that cannot be corrected are dropped rather than guessed at -
        a decoder that invents 223 bytes when it cannot correct is worse than
        one that returns less.
        """
        import reedsolo

        p = params if isinstance(params, RSParams) else RSParams(
            n=params["n"], k=params["k"], offset=params.get("offset", 0),
            blocks_checked=params.get("blocks_checked", 0),
            errata_rate=params.get("errata_rate", 0.0))

        data = _bits_to_bytes(llr_to_bits(llrs))[p.offset:]
        rs = reedsolo.RSCodec(p.nsym)
        t = p.nsym // 2                      # correction capability, in symbols
        out = bytearray()
        for b in range(len(data) // p.n):
            block = bytes(data[b * p.n:(b + 1) * p.n])
            try:
                decoded, full, _ = rs.decode(block)
            except Exception:
                continue                     # honest failure - drop the block

            # MISCORRECTION GUARD. Beyond t symbol errors a Reed-Solomon
            # decoder does not always fail: it can converge on a DIFFERENT
            # valid codeword and return it without complaint. Measured at 5%
            # BER, decode returned plausible bytes that were simply not the
            # payload - the one failure mode this project has otherwise never
            # had.
            #
            # The check is cheap and decisive: re-encode what came out and
            # count how many symbols it disagrees with what came in. A genuine
            # correction differs in at most t places by definition. Anything
            # more means the decoder landed on the wrong codeword, so the block
            # is dropped rather than returned.
            reenc = bytes(rs.encode(bytes(decoded)))
            if len(reenc) != len(block):
                continue
            differing = sum(1 for x, y in zip(reenc, block) if x != y)
            if differing > t:
                continue

            out.extend(decoded)
        if not out:
            return np.zeros(0, dtype=np.uint8)
        return np.unpackbits(np.frombuffer(bytes(out), dtype=np.uint8))

    def validate(self, bits) -> dict:
        arr = np.asarray(bits, dtype=np.uint8).ravel()
        if arr.size == 0:
            return {"ok": False, "reason": "empty", "n_bits": 0}
        ones = float(arr.mean())
        degenerate = ones < 0.02 or ones > 0.98
        return {
            "ok": bool(not degenerate),
            "reason": "near-constant output - decoder did not lock" if degenerate else "",
            "n_bits": int(arr.size),
            "ones_fraction": ones,
        }

    # -- beyond the protocol ------------------------------------------------

    def correction_load(self, llrs, params) -> dict:
        """How hard the decoder had to work. Near zero means the parameters are
        right and the channel is clean; rising means one of those is untrue."""
        p = params if isinstance(params, RSParams) else RSParams(**params)
        data = _bits_to_bytes(llr_to_bits(llrs))
        blocks, decoded_fraction, rate = _try_profile(data, p.n, p.k, p.offset)
        return {"blocks": blocks,
                "decoded_fraction": decoded_fraction,
                "errata_rate": rate,
                "symbols_corrected_per_block": rate * p.n}


register_code(ReedSolomonCode())
