"""pipeline/s0_ingest.py

S0 -- file ingest and format sniffing.

Reads 2-channel WAV (I, Q) as written by zoo/rf.py, plus raw IQ files
(int8/int16/float32) with a ranked-hypothesis format sniffer for the case
where the format isn't declared. SigMF metadata read/write is a stretch item
(7 Sep in the Command Center) and is stubbed for now.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

__all__ = ["S0Result", "read_wav_iq", "read_raw_iq", "sniff_raw_format",
           "ingest"]


@dataclass
class S0Result:
    """Shaped like the eventual StageResult (status/confidence/hypotheses)
    per the Command Center contract -- Naidhruv, point me at the real
    Pydantic model and I will conform exactly."""
    status: str                    # "ok" | "failed"
    iq: np.ndarray | None
    fs: float | None
    source_format: str             # "wav" | "raw_int8" | "raw_int16" | "raw_float32" | "unknown"
    hypotheses: list = field(default_factory=list)   # ranked (format, score) for raw files
    reason: str | None = None
    file_path: str = ""


def read_wav_iq(path: str | Path) -> tuple[np.ndarray, float]:
    """Read a 2-channel WAV (I, Q columns) into a complex IQ array."""
    data, fs = sf.read(str(path), always_2d=True)
    if data.shape[1] < 2:
        raise ValueError(f"{path}: expected 2-channel (I,Q) WAV, got {data.shape[1]} channel(s)")
    iq = data[:, 0].astype(np.float64) + 1j * data[:, 1].astype(np.float64)
    return iq, float(fs)


def read_raw_iq(path: str | Path, dtype: str, fs: float) -> np.ndarray:
    """Read a raw interleaved-IQ binary file: I,Q,I,Q,... in the given dtype.

    dtype: "int8" | "int16" | "float32"
    """
    np_dtype = {"int8": np.int8, "int16": np.int16, "float32": np.float32}[dtype]
    raw = np.fromfile(str(path), dtype=np_dtype)
    if raw.size % 2 != 0:
        raw = raw[:-1]  # drop a stray trailing sample
    raw = raw.reshape(-1, 2).astype(np.float64)
    if dtype == "int8":
        raw /= 128.0
    elif dtype == "int16":
        raw /= 32768.0
    return raw[:, 0] + 1j * raw[:, 1]


def sniff_raw_format(path: str | Path) -> list[tuple[str, float]]:
    """Ranked hypotheses for a raw IQ file's dtype, with visible evidence.

    Scores on two signals: values should be bounded/nonzero, AND should not
    cluster near the extreme edge of the dtype's range. A file misread at
    the wrong byte width still looks "bounded", but tends to spread much more
    uniformly across the full range (including the edges) than genuine
    scaled sample data does -- that's the discriminator.
    """
    import warnings

    candidates = ["int8", "int16", "float32"]
    scored = []
    for dt in candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                iq = read_raw_iq(path, dt, fs=1.0)
            if iq.size == 0 or not np.isfinite(iq).all():
                scored.append((dt, 0.0))
                continue
            mag = np.abs(iq)
            bounded = float(np.mean(mag < 10.0))
            nonzero = float(np.mean(mag > 1e-6))
            extreme = float(np.mean(mag > 0.9 * np.max(mag))) if np.max(mag) > 0 else 1.0
            score = bounded * nonzero * (1.0 - extreme)
            scored.append((dt, round(float(score), 4)))
        except Exception:
            scored.append((dt, 0.0))
    return sorted(scored, key=lambda t: t[1], reverse=True)


def ingest(path: str | Path, fs_hint: float | None = None) -> S0Result:
    """Top-level entry: read a file, return an S0Result.

    WAV files are unambiguous (format + sample rate are in the header).
    Raw IQ files need a dtype hint or the sniffer's top hypothesis.
    """
    path = Path(path)
    if not path.exists():
        return S0Result(status="failed", iq=None, fs=None,
                         source_format="unknown", reason=f"file not found: {path}",
                         file_path=str(path))

    suffix = path.suffix.lower()
    try:
        if suffix in (".wav",):
            iq, fs = read_wav_iq(path)
            return S0Result(status="ok", iq=iq, fs=fs, source_format="wav",
                             file_path=str(path))

        # raw IQ: sniff format, use top hypothesis
        hyps = sniff_raw_format(path)
        best_dt, best_score = hyps[0]
        if best_score <= 0.0:
            return S0Result(status="failed", iq=None, fs=None,
                             source_format="unknown", hypotheses=hyps,
                             reason="no plausible raw IQ format found",
                             file_path=str(path))
        fs = fs_hint or 200_000.0  # unknown for raw files without a sidecar
        iq = read_raw_iq(path, best_dt, fs)
        return S0Result(status="ok", iq=iq, fs=fs, source_format=f"raw_{best_dt}",
                         hypotheses=hyps, file_path=str(path))

    except Exception as e:
        return S0Result(status="failed", iq=None, fs=None, source_format="unknown",
                         reason=str(e), file_path=str(path))