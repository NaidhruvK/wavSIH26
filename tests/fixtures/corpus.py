"""Reading Dheeraj's RF corpus, and measuring S3 against its truth.

4 Sep. This file REPLACES `tests/fixtures/rf_channel.py`, which is deleted.

That fixture existed because S3 needed modulated signals before the zoo had a
modulator, and it carried its own copy of the modulate-and-add-noise path. Two
implementations of one channel is the same class of bug as two implementations
of one bit mapping: everything agrees with itself and nothing is checked. It is
gone. `zoo/rf.py` is now the only place in this repo that turns bits into a
waveform, and everything below either reads the corpus it wrote or calls it.

WHAT THIS PROVIDES

    load(name)              one corpus file: (iq, fs, truth)
    reference_bits(truth)   the exact coded bits that were transmitted,
                            regenerated from the seed in the truth JSON
    measured_ber(res, tx)   harness-only: the lowest bit error rate over the
                            rotations S3 emitted, aligned by correlation
    synth(...)              a parametric signal for a unit test, made by
                            calling zoo.rf - no modulation logic lives here

REGENERATION IS EXACT, and that is worth one sentence because everything below
depends on it. `zoo.bits_only.make_stream` is seeded, and the truth JSON
carries the seed, so the transmitted bit stream can be rebuilt bit for bit.
Checked by re-modulating one and comparing against the WAV: the relative
mismatch is 1.3e-9, which is the float32 the WAV is stored in and nothing else.
So a bit error rate measured here is against what was actually sent, not
against a re-derivation that might share an error with the receiver.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.s0_ingest import read_wav_iq            # noqa: E402
from pipeline.s3_receive import llr_to_bits           # noqa: E402
from zoo.bits_only import make_stream                 # noqa: E402
from zoo.rf import through_channel as _zoo_channel    # noqa: E402

__all__ = ["RF_DIR", "corpus_files", "corpus_names", "load", "reference_bits",
           "align", "measured_ber", "synth", "N_SOURCE_BITS"]

RF_DIR = ROOT / "zoo" / "corpus" / "rf"

N_SOURCE_BITS = 20_000
"""What `zoo.rf.make_rf_file` used when the corpus was built.

Coupled to `zoo/build_rf_corpus.py`, which takes the default. It is not in the
truth JSON - `n_bits_used` is the count actually carried, after the trailing
partial symbol is dropped - so `reference_bits` asserts the regenerated stream
is long enough rather than trusting this constant silently.
"""


def corpus_files() -> list[Path]:
    return sorted(RF_DIR.glob("*.wav"))


def corpus_names() -> list[str]:
    return [p.stem for p in corpus_files()]


def load(name: str) -> tuple[np.ndarray, float, dict]:
    """One corpus file as (iq, fs, truth). `name` is the stem, no extension."""
    wav = RF_DIR / f"{name}.wav"
    truth = json.loads((RF_DIR / f"{name}.json").read_text())
    iq, fs = read_wav_iq(wav)
    return iq, float(fs), truth


def reference_bits(truth: dict) -> np.ndarray:
    """The coded bits that were transmitted, rebuilt from the truth JSON.

    Everything the zoo's bit pipeline is configured by is in the JSON -
    interleaver depth and width, whether it was scrambled, the injected error
    rate, the seed - so this reads the configuration rather than restating it.
    """
    il = truth.get("interleaver") or {}
    bits, _ = make_stream(
        n_source_bits=N_SOURCE_BITS,
        depth=il.get("depth"), width=il.get("width"),
        scramble=truth.get("scrambler") is not None,
        ber=float(truth.get("injected_ber", 0.0)),
        seed=int(truth["seed"]),
    )
    n_used = int(truth["n_bits_used"])
    if bits.size < n_used:
        raise AssertionError(
            f"regenerated {bits.size} coded bits but the truth says {n_used} "
            f"were transmitted - N_SOURCE_BITS ({N_SOURCE_BITS}) no longer "
            "matches how zoo/build_rf_corpus.py was run")
    return bits[:n_used]


def align(rx: np.ndarray, tx: np.ndarray,
          window: int = 20000) -> tuple[float, int]:
    """(bit error rate, offset) of `rx` inside `tx`, by FFT cross-correlation.

    S3 drops an acquisition prefix whose length it does not report in bits, so
    `rx` is a contiguous run of `tx` starting somewhere unknown - about 2200
    bits in on a corpus QPSK file.

    `window` matters more than it looks. It must be well under `tx.size` or the
    correlation has nowhere to search: comparing 39 898 received bits against
    39 898 transmitted ones leaves exactly one candidate offset, which is
    always zero, which is always wrong. That bug reported a bit error rate of
    0.485 for files that in fact decode exactly, and it is the reason this is
    one function with one window rather than three copies in three report
    scripts.
    """
    tx = np.asarray(tx).astype(np.uint8).ravel()
    rx = np.asarray(rx).astype(np.uint8).ravel()
    n = int(min(rx.size, window, tx.size // 2))
    if n < 1000:
        return 1.0, -1
    a = 1.0 - 2.0 * rx[:n].astype(float)
    b = 1.0 - 2.0 * tx.astype(float)
    L = 1 << int(np.ceil(np.log2(tx.size + n)))
    c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)
    c = c[: tx.size - n + 1]
    off = int(np.argmax(np.abs(c)))
    return float(np.mean(rx[:n] != tx[off : off + n])), off


def measured_ber(res, tx: np.ndarray) -> float:
    """Lowest bit error rate over the rotations S3 emitted.

    A fully inverted stream counts as a match, because a rotation that flips
    every bit carries exactly the same information and S4 recovers from it
    identically - see `phase_rotation_candidates`.

    HARNESS ONLY. S3 cannot make this comparison; it has no reference bits.
    Anything in `pipeline/` that reached for this would be reading the answer
    key, which is the thing the 1 Sep gate exists to forbid.
    """
    best = 1.0
    for cand in getattr(res, "llrs_by_rotation", None) or []:
        e, _ = align(llr_to_bits(cand), tx)
        best = min(best, e, 1.0 - e)
    return best


def synth(scheme: str, n_bits: int = 60000, snr_db: float = 25.0,
          sps: int = 4, beta: float = 0.35, cfo_norm: float = 0.0,
          phase_rad: float = 0.0, timing_offset_sym: float = 0.0,
          seed: int = 7, fs: float = 200_000.0,
          bits: np.ndarray | None = None
          ) -> tuple[np.ndarray, float, float, int]:
    """A parametric signal for a unit test: (iq, fs, symbol_rate, n_bits_used).

    A thin call into `zoo.rf.through_channel` and nothing else - no
    constellation, no pulse shape, no noise model of its own. A unit test still
    needs to ask for 8-PSK at 6 dB with a half-symbol timing error, which no
    fixed corpus can answer, but it must ask the zoo for it.

    `n_bits_used` is how many of `bits` actually fitted into whole symbols; a
    caller comparing against its own reference should slice to it.
    """
    if bits is None:
        bits = np.random.default_rng(seed).integers(0, 2, n_bits).astype(np.uint8)
    iq, n_used = _zoo_channel(bits, scheme, sps, beta, snr_db,
                              cfo_norm, phase_rad, timing_offset_sym, seed)
    return iq, fs, fs / float(sps), int(n_used)
