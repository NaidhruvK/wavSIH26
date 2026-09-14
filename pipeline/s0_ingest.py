"""pipeline/s0_ingest.py

S0 -- file ingest and format sniffing.

Reads 2-channel WAV (I, Q) as written by zoo/rf.py, plus raw IQ files
(int8/int16/float32, either byte order, interleaved or planar channel
layout) with ranked-hypothesis sniffers for every part of the format that
isn't declared. SigMF metadata read/write is a stretch item and is
stubbed for now.

7 Sep: endianness and channel-layout detection, added to the 29 Aug dtype
sniffer -- the 7 Sep plan's "format sniffer... endianness and
interleaving detection, with the evidence shown". Two separate, blind
statistics, not one combined guess:

  - dtype/endianness: scored on whether decoded sample magnitudes are
    bounded, nonzero and not piled up at the extreme edge of the range --
    unchanged method from 29 Aug, extended to try both byte orders for
    the multi-byte dtypes.
  - I/Q channel layout (interleaved I,Q,I,Q,... vs planar all-I-then-
    all-Q): scored on lag-1 autocorrelation of each half-channel. A
    genuinely oversampled RF capture is smooth sample-to-sample within
    one real channel; splitting the wrong way pairs unrelated bytes and
    that structure collapses toward zero. Measured on the real RF
    corpus (tests/unit/test_s0_ingest.py): correct-split autocorrelation
    0.44-0.87 vs ~0.00 wrong, for every scheme except 4fsk, where even
    the CORRECT split autocorrelates near zero -- its tone spacing at
    this sps rotates the phase far enough within one sample that
    adjacent same-channel samples decorrelate regardless of alignment.
    Stated as a measured limitation, not chased: this detector is
    unreliable for a constant-envelope signal whose modulation index is
    high relative to its samples-per-symbol.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

__all__ = ["S0Result", "read_wav_iq", "read_raw_iq", "sniff_raw_format",
           "sniff_iq_layout", "ingest"]

# dtype label -> (numpy dtype, full-scale divisor). "int16"/"float32" keep
# their original (native == little-endian on every machine this runs on)
# meaning for backward compatibility; "_be" siblings are the 7 Sep addition.
_DTYPE_MAP: dict[str, tuple[np.dtype, float]] = {
    "int8": (np.dtype(np.int8), 128.0),
    "int16": (np.dtype("<i2"), 32768.0),
    "int16_be": (np.dtype(">i2"), 32768.0),
    "float32": (np.dtype("<f4"), 1.0),
    "float32_be": (np.dtype(">f4"), 1.0),
}


@dataclass
class S0Result:
    """Shaped like the eventual StageResult (status/confidence/hypotheses)
    per the Command Center contract -- Naidhruv, point me at the real
    Pydantic model and I will conform exactly."""
    status: str                    # "ok" | "failed"
    iq: np.ndarray | None
    fs: float | None
    source_format: str             # "wav" | "raw_int8" | "raw_int16" | "raw_int16_be" | "raw_float32" | "raw_float32_be" | "unknown"
    hypotheses: list = field(default_factory=list)          # ranked (dtype_label, score, evidence)
    layout: str | None = None                                # "interleaved" | "planar", raw files only
    layout_hypotheses: list = field(default_factory=list)    # ranked (layout_label, score, evidence)
    reason: str | None = None
    file_path: str = ""
    # WHERE fs CAME FROM. "wav_header" | "caller_hint" | "assumed_default".
    # The samples cannot confirm fs (see s1_detect.check_sampling_rate), so
    # every Hz figure downstream is exactly as good as this field. It exists
    # because the raw-IQ path used to write `fs_hint or 200_000.0` and hand the
    # invented number on with nothing marking it - a symbol rate reported in Hz
    # off an assumed fs is wrong by an unknown factor and looked measured.
    fs_source: str = "unknown"


RAW_DEFAULT_FS = 200_000.0
"""The sample rate assumed for a raw IQ file with no hint. The zoo's rate, and
nothing more authoritative than that - hence `fs_source="assumed_default"`."""


def read_wav_iq(path: str | Path) -> tuple[np.ndarray, float]:
    """Read a 2-channel WAV (I, Q columns) into a complex IQ array."""
    data, fs = sf.read(str(path), always_2d=True)
    if data.shape[1] < 2:
        raise ValueError(f"{path}: expected 2-channel (I,Q) WAV, got {data.shape[1]} channel(s)")
    iq = data[:, 0].astype(np.float64) + 1j * data[:, 1].astype(np.float64)
    return iq, float(fs)


def _decode_raw_samples(path: str | Path, dtype: str) -> np.ndarray:
    """Bytes -> flat, scaled, real-valued sample stream. No I/Q pairing
    yet -- dtype and channel-layout are separate questions, decided by
    separate evidence, and this is the shared step both need."""
    np_dtype, scale = _DTYPE_MAP[dtype]
    raw = np.fromfile(str(path), dtype=np_dtype).astype(np.float64)
    return raw / scale


def read_raw_iq(path: str | Path, dtype: str, fs: float,
                 layout: str = "interleaved") -> np.ndarray:
    """Read a raw IQ binary file into a complex array.

    dtype: "int8" | "int16" | "int16_be" | "float32" | "float32_be"
    layout: "interleaved" (I,Q,I,Q,...) | "planar" (all I, then all Q)
    """
    raw = _decode_raw_samples(path, dtype)
    n = (raw.size // 2) * 2
    raw = raw[:n]
    if layout == "planar":
        i_ch, q_ch = raw[:n // 2], raw[n // 2:]
    else:
        i_ch, q_ch = raw[0::2], raw[1::2]
    return i_ch + 1j * q_ch


def _int8_misread_as_int16_evidence(path: str | Path) -> float:
    """How strongly the bytes look like 1-byte samples that would be
    misread as 2-byte ones, independent of the magnitude heuristic below.

    7 Sep: the magnitude heuristic alone cannot reliably tell int8 from
    int16 -- reinterpreting two adjacent, moderate-amplitude int8 samples
    as one int16 raw code routinely still looks "bounded" (measured: a
    real int8 corpus file scored 0.9998 as int8 and 1.0000 as int16,
    effectively a coin flip). The fix is a different, much sharper
    question: for GENUINE int16 data, the low byte of each sample is
    fine sub-LSB quantisation detail -- noise, uncorrelated sample to
    sample. For int8 data misread as int16, the "low byte" of each fake
    16-bit sample is actually a real, smoothly-varying 8-bit sample in
    its own right, so it autocorrelates strongly. Measured on the real
    RF corpus: low-byte autocorrelation 0.64-0.88 for true int8 files,
    versus -0.05 to 0.00 for every true int16/float32 file tried --
    over a 10x margin, the cleanest signal found for any part of this
    sniffer. Returns that autocorrelation directly; sniff_raw_format
    gates int8 in when it clears 0.3 and gates it OUT (regardless of the
    magnitude score) when it doesn't, since the two tests answer
    different questions and this one is the more reliable of the two for
    exactly the case it targets.
    """
    raw_i16 = np.fromfile(str(path), dtype="<i2")
    if raw_i16.size < 8:
        return 0.0
    low_byte = (raw_i16 & 0xFF).astype(np.int16)
    low_byte[low_byte > 127] -= 256
    x = low_byte.astype(np.float64) - np.mean(low_byte)
    den = float(np.sum(x * x)) + 1e-12
    return float(np.sum(x[:-1] * x[1:]) / den)


def sniff_raw_format(path: str | Path) -> list[tuple[str, float, str]]:
    """Ranked (dtype_label, score, evidence) hypotheses for a raw IQ
    file's sample type and byte order.

    Two separate discriminators, not one score standing in for both
    questions:

    - byte WIDTH (is this 1-byte samples or 2/4-byte ones?):
      _int8_misread_as_int16_evidence, see its docstring -- far more
      reliable than the magnitude heuristic for this specific question.
    - byte ORDER and general plausibility (int16 vs int16_be vs float32
      vs float32_be, and int8's own sanity check): values should be
      bounded/nonzero, and not cluster near the extreme edge of the
      dtype's range, or -- for a byte-swapped multi-byte float/int --
      decode to values that aren't finite at all. Unchanged since 29 Aug.
      Measured limitation, stated rather than chased further: this signal
      is NOT reliable for byte order specifically when the channel layout
      is ALSO planar rather than interleaved (see
      tests/unit/test_s0_ingest.py's pinned misses) -- two independent
      ambiguities compounding is harder than either alone, and a third,
      sharper discriminator for byte order specifically was not found in
      the time available today.
    """
    import warnings

    int8_evidence = _int8_misread_as_int16_evidence(path)
    is_int8 = int8_evidence > 0.3

    candidates = ["int8", "int16", "int16_be", "float32", "float32_be"]
    scored = []
    for dt in candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                iq = read_raw_iq(path, dt, fs=1.0)
            if iq.size == 0 or not np.isfinite(iq).all():
                scored.append((dt, 0.0, "non-finite or empty decode"))
                continue
            mag = np.abs(iq)
            bounded = float(np.mean(mag < 10.0))
            nonzero = float(np.mean(mag > 1e-6))
            extreme = float(np.mean(mag > 0.9 * np.max(mag))) if np.max(mag) > 0 else 1.0
            score = bounded * nonzero * (1.0 - extreme)
            evidence = f"bounded={bounded:.2f} nonzero={nonzero:.2f} extreme={extreme:.2f}"
            if dt == "int8":
                evidence += f" low_byte_autocorr={int8_evidence:.2f}"
                if not is_int8:
                    score *= 0.05   # width evidence says this is NOT 1-byte samples
            elif not is_int8:
                pass   # width evidence agrees this candidate's byte count is plausible
            else:
                score *= 0.05       # width evidence says this SHOULD be int8, not this
            scored.append((dt, round(float(score), 4), evidence))
        except Exception as e:
            scored.append((dt, 0.0, f"decode failed: {e}"))
    return sorted(scored, key=lambda t: t[1], reverse=True)


def sniff_iq_layout(raw: np.ndarray) -> list[tuple[str, float, str]]:
    """Ranked (layout_label, score, evidence) hypotheses for whether a
    flat, already-dtype-decoded real sample stream is channel-interleaved
    (I,Q,I,Q,...) or planar (all I samples, then all Q samples).

    Evidence: lag-1 autocorrelation of each resulting half-channel. A
    genuinely oversampled RF capture is smooth sample-to-sample within
    one real channel, so correctly split channels show strong positive
    autocorrelation; splitting the wrong way pairs samples that don't
    belong together (either two different quadrature components at the
    same instant, or two disjoint time halves treated as simultaneous)
    and that structure collapses toward zero. See module docstring for
    the measured margins and the one known-weak case (4fsk)."""
    n = raw.size
    if n < 8:
        return [("interleaved", 0.0, "too few samples"),
                ("planar", 0.0, "too few samples")]

    def _lag1_autocorr(x: np.ndarray) -> float:
        x = x - np.mean(x)
        den = float(np.sum(x * x)) + 1e-12
        return float(np.sum(x[:-1] * x[1:]) / den)

    half = n // 2
    a1, a2 = raw[0:2 * half:2], raw[1:2 * half:2]
    b1, b2 = raw[:half], raw[half:2 * half]

    score_interleaved = (_lag1_autocorr(a1) + _lag1_autocorr(a2)) / 2.0
    score_planar = (_lag1_autocorr(b1) + _lag1_autocorr(b2)) / 2.0

    hyps = [
        ("interleaved", round(max(score_interleaved, 0.0), 4),
         f"channel autocorr={score_interleaved:.3f}"),
        ("planar", round(max(score_planar, 0.0), 4),
         f"channel autocorr={score_planar:.3f}"),
    ]
    return sorted(hyps, key=lambda t: t[1], reverse=True)


def ingest(path: str | Path, fs_hint: float | None = None) -> S0Result:
    """Top-level entry: read a file, return an S0Result.

    WAV files are unambiguous (format + sample rate are in the header).
    Raw IQ files need dtype/endianness and channel-layout hints, or the
    sniffers' top hypotheses -- tried in that order, since layout is
    decided on the bytes as decoded by the winning dtype.
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
            # The header is authoritative for a WAV; a caller hint that
            # disagrees is ignored rather than preferred, as before.
            return S0Result(status="ok", iq=iq, fs=fs, source_format="wav",
                             file_path=str(path), fs_source="wav_header")

        # raw IQ: sniff dtype/endianness first, then channel layout on
        # the winning dtype's decoded byte stream.
        hyps = sniff_raw_format(path)
        best_dt, best_score, _dt_evidence = hyps[0]
        if best_score <= 0.0:
            return S0Result(status="failed", iq=None, fs=None,
                             source_format="unknown", hypotheses=hyps,
                             reason="no plausible raw IQ format found",
                             file_path=str(path))

        raw_samples = _decode_raw_samples(path, best_dt)
        layout_hyps = sniff_iq_layout(raw_samples)
        best_layout = layout_hyps[0][0]

        # A raw file carries no sample rate. The default stays - downstream
        # stages need a number to express Hz in - but it is now LABELLED, and
        # the reason says in words what the label means.
        if fs_hint:
            fs, fs_source, note = float(fs_hint), "caller_hint", None
        else:
            fs, fs_source = RAW_DEFAULT_FS, "assumed_default"
            note = ("raw IQ carries no sample rate and none was supplied, so "
                    "fs=%.0f Hz is ASSUMED. Symbol rate, CFO and bandwidth in "
                    "Hz scale with that assumption; samples-per-symbol and "
                    "fractional bandwidth do not. Pass fs_hint for true Hz."
                    % RAW_DEFAULT_FS)
        iq = read_raw_iq(path, best_dt, fs, layout=best_layout)
        return S0Result(status="ok", iq=iq, fs=fs, source_format=f"raw_{best_dt}",
                         hypotheses=hyps, layout=best_layout,
                         layout_hypotheses=layout_hyps, file_path=str(path),
                         fs_source=fs_source, reason=note)

    except Exception as e:
        return S0Result(status="failed", iq=None, fs=None, source_format="unknown",
                         reason=str(e), file_path=str(path))
