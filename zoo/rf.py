"""zoo/rf.py

RF/IQ zoo mode: bits -> modulated waveform -> channel -> WAV file + truth JSON.

This REPLACES tests/fixtures/rf_channel.py as the source of RF test signals.
Once files from here are on disk, that fixture can be deleted and Anvith's
S3 tests re-run against the real corpus.

Reuses the exact modulation/channel logic from rf_channel.py (bit mapping,
RRC pulse shaping, AWGN, CFO, timing offset) so the signals S3 has already
been validated against don't silently change underneath it.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import soundfile as sf

from pipeline.s3_receive.bitmap import bits_per_symbol, bits_to_symbol_indices
from pipeline.s3_receive.filters import rrc_taps
from pipeline.s3_receive.schemes import scheme

from zoo.bits_only import make_stream, lfsr_scramble, CCSDS_SCRAMBLER

__all__ = ["RFTruth", "modulate_bits", "through_channel", "make_rf_file",
           "write_wav_pair"]


@dataclass
class RFTruth:
    scheme: str
    fs: float
    sps: int
    beta: float
    snr_db: float
    cfo_norm: float
    phase_rad: float
    timing_offset_sym: float
    seed: int
    n_bits_used: int
    code: dict
    interleaver: dict | None
    scrambler: dict | None
    injected_ber: float
    error_model: str

    def as_dict(self) -> dict:
        return asdict(self)


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


def modulate_bits(bits: np.ndarray, scheme_name: str, sps: int, beta: float,
                   modulation_index: float = 1.0) -> tuple[np.ndarray, int]:
    """Bits -> noiseless complex baseband. Returns (waveform, n_bits_used)."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()

    if scheme_name.endswith("fsk"):
        order = int(scheme_name[:-3])
        b = bits_per_symbol(order)
        n_used = (bits.size // b) * b
        idx = bits_to_symbol_indices(bits[:n_used], order)
        sep = modulation_index / float(sps)
        tones = (np.arange(order) - (order - 1) / 2.0) * sep
        inst = np.repeat(tones[idx], sps)
        x = np.exp(2j * np.pi * np.cumsum(inst))
        return x, n_used

    sch = scheme(scheme_name)
    b = sch.bits
    n_used = (bits.size // b) * b
    idx = bits_to_symbol_indices(bits[:n_used], sch.order)
    pts = sch.points / (np.sqrt(np.mean(np.abs(sch.points) ** 2)) or 1.0)
    syms = pts[idx]

    up = np.zeros(syms.size * sps, dtype=np.complex128)
    up[::sps] = syms
    return np.convolve(up, rrc_taps(beta, sps), mode="same"), n_used


def through_channel(bits: np.ndarray, scheme_name: str, sps: int, beta: float,
                     snr_db: float, cfo_norm: float, phase_rad: float,
                     timing_offset_sym: float, seed: int
                     ) -> tuple[np.ndarray, int]:
    """Full path: modulate, delay, offset, rotate, add noise."""
    rng = np.random.default_rng(seed)
    x, n_used = modulate_bits(bits, scheme_name, sps, beta)
    if timing_offset_sym:
        x = _frac_delay(x, timing_offset_sym * sps)
    if cfo_norm or phase_rad:
        n = np.arange(x.size)
        x = x * np.exp(1j * (2 * np.pi * cfo_norm * n + phase_rad))
    return _awgn(x, snr_db, rng), n_used


def make_rf_file(
    scheme_name: str = "qpsk",
    n_source_bits: int = 20_000,
    fs: float = 200_000.0,
    sps: int = 4,
    beta: float = 0.35,
    snr_db: float = 20.0,
    cfo_norm: float = 0.0,
    phase_rad: float = 0.0,
    timing_offset_sym: float = 0.0,
    depth: int | None = 8,
    width: int | None = 12,
    scramble: bool = False,
    ber: float = 0.0,
    seed: int = 0,
) -> tuple[np.ndarray, RFTruth]:
    """Coded bits -> full RF waveform ready to write as WAV, with truth."""
    coded_bits, bits_truth = make_stream(
        n_source_bits=n_source_bits, depth=depth, width=width,
        scramble=scramble, ber=ber, seed=seed,
    )
    iq, n_used = through_channel(
        coded_bits, scheme_name, sps, beta, snr_db,
        cfo_norm, phase_rad, timing_offset_sym, seed,
    )
    truth = RFTruth(
        scheme=scheme_name, fs=fs, sps=sps, beta=beta, snr_db=snr_db,
        cfo_norm=cfo_norm, phase_rad=phase_rad,
        timing_offset_sym=timing_offset_sym, seed=seed, n_bits_used=n_used,
        code=bits_truth.code, interleaver=bits_truth.interleaver,
        scrambler=bits_truth.scrambler, injected_ber=ber,
        error_model="independent",
    )
    return iq, truth


def write_wav_pair(iq: np.ndarray, truth: RFTruth, out_dir: Path, name: str) -> None:
    """2-channel WAV (I, Q) + truth JSON sidecar, per the Command Center spec."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stereo = np.stack([iq.real, iq.imag], axis=-1).astype(np.float32)
    # normalise headroom so WAV doesn't clip
    peak = np.max(np.abs(stereo)) or 1.0
    stereo = stereo / peak * 0.9
    sf.write(str(out_dir / f"{name}.wav"), stereo, int(truth.fs))
    with open(out_dir / f"{name}.json", "w") as f:
        json.dump(truth.as_dict(), f, indent=2)