"""Bits in, RF out - the missing half of the 3 Sep junction.

Nehal's `local_zoo.make_stream()` produces coded, interleaved, scrambled bits
and then *injects* errors. That was the right stand-in for characterising S4
alone, and it is exactly what the 3 Sep junction has to stop using: injected
errors are independent, and a demodulator's errors are not.

This module replaces the injector with an actual channel. It takes the same
coded bitstream, puts it on a carrier through the same modulator S3 expects,
adds noise, offset and timing error, and hands back a waveform. Feed that to
S3 and the errors reaching S4 are the errors a receiver really makes.

OWNERSHIP: Anvith. It is a test fixture, not a pipeline stage, and it dies the
same day Dheeraj's zoo grows a modulator - at which point the corpus carries
these files and nothing has to generate them.

It deliberately imports the bit mapping from `pipeline.s3_receive.bitmap`
rather than restating it. A fixture that carries its own copy of the
constellation labelling can only ever prove that S3 agrees with itself.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s3_receive.bitmap import (bits_per_symbol,  # noqa: E402
                                        bits_to_symbol_indices)
from pipeline.s3_receive.filters import rrc_taps  # noqa: E402
from pipeline.s3_receive.schemes import scheme  # noqa: E402

__all__ = ["ChannelSpec", "modulate_bits", "through_channel", "snr_for_target_ber"]


@dataclass
class ChannelSpec:
    scheme: str = "qpsk"
    sps: int = 4
    beta: float = 0.35
    snr_db: float = 20.0
    cfo_norm: float = 0.0            # cycles/sample
    phase_rad: float = 0.0
    timing_offset_sym: float = 0.0   # fraction of a symbol
    seed: int = 0
    fs: float = 200_000.0
    # FSK only. Expressed as a modulation index h = df * T, NOT in cycles per
    # sample: non-coherent detection needs h >= 1 for the tones to be
    # orthogonal over a symbol, and at h = 0.4 the tone bank's outputs overlap
    # so heavily that decisions stay mostly right while the decision MARGIN -
    # and therefore every LLR derived from it - collapses. Defaulting this to a
    # raw 0.05 with 8 samples/symbol meant h = 0.4, which made the soft output
    # look broken when the fixture was.
    modulation_index: float = 1.0
    meta: dict = field(default_factory=dict)

    @property
    def symbol_rate(self) -> float:
        return self.fs / self.sps


def _frac_delay(x: np.ndarray, delay_samples: float) -> np.ndarray:
    if not delay_samples:
        return x
    f = np.fft.fftfreq(x.size)
    return np.fft.ifft(np.fft.fft(x) * np.exp(-2j * np.pi * f * delay_samples))


def _awgn(x: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    p = float(np.mean(np.abs(x) ** 2))
    npow = p / (10.0 ** (snr_db / 10.0))
    return x + rng.normal(0, np.sqrt(npow / 2), x.size) + \
        1j * rng.normal(0, np.sqrt(npow / 2), x.size)


def modulate_bits(bits: np.ndarray, spec: ChannelSpec) -> tuple[np.ndarray, int]:
    """Bits -> noiseless complex baseband. Returns (waveform, n_bits_used).

    Trailing bits that do not fill a symbol are dropped, and the count of bits
    actually carried is returned so the caller can slice its own reference to
    match rather than guessing.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    name = spec.scheme
    sps = int(spec.sps)

    if name.endswith("fsk"):
        order = int(name[:-3])
        b = bits_per_symbol(order)
        n_used = (bits.size // b) * b
        idx = bits_to_symbol_indices(bits[:n_used], order)
        sep = spec.modulation_index / float(sps)      # cycles/sample
        tones = (np.arange(order) - (order - 1) / 2.0) * sep
        inst = np.repeat(tones[idx], sps)
        x = np.exp(2j * np.pi * np.cumsum(inst))
        return x, n_used

    sch = scheme(name)
    b = sch.bits
    n_used = (bits.size // b) * b
    idx = bits_to_symbol_indices(bits[:n_used], sch.order)
    pts = sch.points / (np.sqrt(np.mean(np.abs(sch.points) ** 2)) or 1.0)
    syms = pts[idx]

    up = np.zeros(syms.size * sps, dtype=np.complex128)
    up[::sps] = syms
    return np.convolve(up, rrc_taps(spec.beta, sps), mode="same"), n_used


def through_channel(bits: np.ndarray, spec: ChannelSpec) -> tuple[np.ndarray, int]:
    """The full path: modulate, delay, offset, rotate, add noise."""
    rng = np.random.default_rng(spec.seed)
    x, n_used = modulate_bits(bits, spec)
    if spec.timing_offset_sym:
        x = _frac_delay(x, spec.timing_offset_sym * spec.sps)
    if spec.cfo_norm or spec.phase_rad:
        n = np.arange(x.size)
        x = x * np.exp(1j * (2 * np.pi * spec.cfo_norm * n + spec.phase_rad))
    return _awgn(x, spec.snr_db, rng), n_used


def snr_for_target_ber(scheme_name: str, target_ber: float) -> float:
    """Rough SNR giving a wanted raw bit error rate, for sweeping the junction.

    Coherent M-PSK, Gray-mapped, from the standard nearest-neighbour union
    bound; treated as a starting point for a search rather than a prediction,
    because the receiver's own imperfections move it.
    """
    from scipy.special import erfcinv

    if scheme_name.endswith("fsk"):
        order = int(scheme_name[:-3])
        b = bits_per_symbol(order)
        # non-coherent orthogonal FSK, symbol error ~ (M-1)/2 exp(-Es/2N0)
        es_n0 = -2.0 * np.log(max(2.0 * target_ber, 1e-12) / max(order - 1, 1))
        return float(10 * np.log10(max(es_n0, 1e-3) / b) + 10 * np.log10(b))

    sch = scheme(scheme_name)
    b = sch.bits
    q = erfcinv(2.0 * min(max(target_ber * b, 1e-12), 0.4)) * np.sqrt(2.0)
    if sch.family == "qam":
        es_n0 = (q**2) * 10.0 / 2.0 / 3.0 * 3.0
    elif sch.order == 2:
        es_n0 = q**2 / 2.0
    else:
        es_n0 = (q / np.sin(np.pi / sch.order)) ** 2 / 2.0
    return float(10 * np.log10(max(es_n0, 1e-3)))
