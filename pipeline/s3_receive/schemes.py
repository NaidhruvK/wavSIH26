"""One description of each modulation, so nothing else has to special-case them.

Before this existed, `order` was doing three jobs at once: how many points the
constellation has, how many bits a symbol carries, and how many rotations the
carrier loop can settle into. For PSK those three numbers are equal and the
conflation is invisible. 16-QAM is where it breaks - sixteen points, four bits,
but only **four** rotational ambiguities, because a square QAM constellation
maps onto itself every 90 degrees and not every 22.5.

Emitting sixteen rotation candidates instead of four would hand S4 twelve
hypotheses that cannot be right and multiply its sweep by four for nothing,
which is risk #5 paid for by a naming mistake.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .bitmap import bits_per_symbol, qam16_constellation

__all__ = ["Scheme", "SCHEMES", "scheme", "psk_constellation"]


def psk_constellation(order: int) -> np.ndarray:
    """Unit-power M-PSK, indexed by increasing angle - the order bitmap.py
    Gray-labels against."""
    if order == 2:
        return np.array([1.0 + 0j, -1.0 + 0j])
    return np.exp(1j * (np.pi / order + 2 * np.pi * np.arange(order) / order))


@dataclass(frozen=True)
class Scheme:
    name: str
    family: str
    points: np.ndarray          # unit-power constellation, position-indexed
    symmetry: int               # rotations the constellation is invariant under
    detail: str = ""

    @property
    def order(self) -> int:
        return int(self.points.size)

    @property
    def bits(self) -> int:
        return bits_per_symbol(self.order)


SCHEMES: dict[str, Scheme] = {
    "bpsk": Scheme("bpsk", "psk", psk_constellation(2), 2,
                   "BPSK, Gardner timing + Costas, 1 bit/symbol"),
    "qpsk": Scheme("qpsk", "psk", psk_constellation(4), 4,
                   "QPSK, Gardner timing + Costas, 2 bits/symbol"),
    "8psk": Scheme("8psk", "psk", psk_constellation(8), 8,
                   "8-PSK, decision-directed Costas, 3 bits/symbol"),
    "16qam": Scheme("16qam", "qam", qam16_constellation(), 4,
                    "16-QAM, MMA equaliser + decision-directed carrier, "
                    "4 bits/symbol, 4-fold rotational ambiguity"),
}


def scheme(name: str) -> Scheme:
    try:
        return SCHEMES[name]
    except KeyError:
        raise ValueError(f"unknown modulation scheme {name!r}") from None
