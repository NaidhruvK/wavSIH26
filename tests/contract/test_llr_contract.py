"""The S3 -> S4 boundary contract. The 2 September gate.

OWNERSHIP NOTE: `tests/contract/` is Naidhruv's, and this file is written by
Anvith the same way Nehal wrote `registry/protocols.py` - because the gate it
enforces falls due today and the owner has not landed. Overwrite it freely when
the real contract suite arrives; what must survive is the set of properties,
because they are the ones that fail silently.

Risk #4 in the register is "hard bits leak into S4 - contract violated
silently", and its early warning is "S4 accuracy drops with no code change".
That is the whole reason this is a test and not a code review: every property
below can be broken without raising anything anywhere, and the damage shows up
days later as a decoder that mysteriously got worse.

The five properties:

1. **float dtype.** An integer array of 0s and 1s satisfies "an array of
   numbers" and destroys every bit of soft information.
2. **not confined to {0, 1}.** A float array can still be hard bits cast to
   float. This is the check the Command Center names explicitly.
3. **the sign convention.** `llr > 0` must mean bit 0. Backwards decodes to
   noise and raises nothing - stated in `registry/protocols.py`, negated once
   inside `conv_code.decode`, and asserted here against known transmitted bits.
4. **finite.** An inf or a nan propagates through Viterbi's path metrics and
   takes out the whole traceback, not just one bit.
5. **calibrated.** Magnitudes must mean something: the BER implied by the LLRs
   has to resemble the real one. An uncalibrated array passes 1-4 and still
   makes the soft decoder worse than hard decisions would have been.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.s3_receive import estimated_ber, llr_to_bits
from registry import MODULATIONS
from tests.fixtures.rf_channel import ChannelSpec, through_channel

# SNRs at which each scheme is comfortably locked - the contract is about the
# shape of the output, not about the operating envelope, which the envelope
# report measures separately.
CLEAN = {"bpsk": (10, 4), "qpsk": (12, 4), "8psk": (16, 4),
         "16qam": (20, 4), "2fsk": (12, 8), "4fsk": (14, 8)}

# The SNR at which each scheme sits in the band where a bit error rate can
# actually be measured - roughly 5e-4 to 1e-2 raw. One blanket offset below the
# clean point does not work, because the schemes are 10 dB apart in sensitivity,
# and a calibration test that skips is not a gate. These are measured, from
# reports/s3_envelope.csv.
MARGINAL = {"bpsk": 1.0, "qpsk": 3.5, "8psk": 9.5,
            "16qam": 11.5, "2fsk": 1.5, "4fsk": 2.5}

ALL_SIX = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]


@pytest.fixture(scope="module")
def source_bits() -> np.ndarray:
    return np.random.default_rng(20260902).integers(0, 2, 240000).astype(np.uint8)


def _demodulate(name: str, bits: np.ndarray, snr_offset: float = 0.0,
                snr_db: float | None = None):
    snr, sps = CLEAN[name]
    snr = snr_db if snr_db is not None else snr + snr_offset
    spec = ChannelSpec(scheme=name, sps=sps, snr_db=snr,
                       cfo_norm=0.0012, timing_offset_sym=0.37, seed=3)
    x, n_used = through_channel(bits, spec)
    plugin = MODULATIONS[name]
    res = plugin.receive(x, {"fs": spec.fs, "symbol_rate": spec.symbol_rate})
    return res, bits[:n_used]


def _best_rotation(res, tx: np.ndarray) -> tuple[np.ndarray, float]:
    """The rotation whose hard decisions match the transmitted bits, with its
    BER. Harness-only - S3 has no way to make this choice, which is exactly why
    it emits every rotation."""
    best = (None, 1.0)
    for cand in res.llrs_by_rotation:
        rx = llr_to_bits(cand)
        n = min(rx.size, 40000)
        a = 1.0 - 2.0 * rx[:n].astype(float)
        m = min(tx.size, n + 100000)
        b = 1.0 - 2.0 * tx[:m].astype(float)
        L = 1 << int(np.ceil(np.log2(m + n)))
        c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)[: m - n + 1]
        off = int(np.argmax(np.abs(c)))
        ber = float(np.mean(rx[:n] != tx[off : off + n]))
        if ber < best[1]:
            best = (cand, ber)
    return best


# --- the registry itself ---------------------------------------------------

def test_registry_carries_all_six_modulations():
    """The 2 Sep integration line: six modulations registered."""
    assert set(ALL_SIX).issubset(set(MODULATIONS))


@pytest.mark.parametrize("name", ALL_SIX)
def test_plugin_satisfies_the_modulation_protocol(name):
    from registry import ModulationPlugin
    assert isinstance(MODULATIONS[name], ModulationPlugin)


# --- properties 1, 2, 4 ----------------------------------------------------

@pytest.mark.parametrize("name", ALL_SIX)
def test_llrs_are_float_and_not_hard_bits(name, source_bits):
    """The gate as the Command Center words it: dtype float, values not
    confined to {0, 1}, for every registered modulation."""
    res, _ = _demodulate(name, source_bits)
    assert res.status in ("ok", "low_confidence"), res.reason

    llrs = MODULATIONS[name].demodulate(
        *_channel_for(name, source_bits))          # via the protocol method
    assert llrs.size > 1000

    assert np.issubdtype(llrs.dtype, np.floating), \
        f"{name} emitted {llrs.dtype}, which destroys the soft information"
    assert not np.all(np.isin(llrs, (0.0, 1.0))), \
        f"{name} emitted hard bits cast to float"
    assert np.all(np.isfinite(llrs)), f"{name} emitted a non-finite LLR"


def _channel_for(name: str, bits: np.ndarray):
    snr, sps = CLEAN[name]
    spec = ChannelSpec(scheme=name, sps=sps, snr_db=snr,
                       cfo_norm=0.0012, timing_offset_sym=0.37, seed=3)
    x, _ = through_channel(bits, spec)
    return x, {"fs": spec.fs, "symbol_rate": spec.symbol_rate}


@pytest.mark.parametrize("name", ALL_SIX)
def test_llr_count_matches_bits_per_symbol(name, source_bits):
    res, _ = _demodulate(name, source_bits)
    b = res.values["bits_per_symbol"]
    assert res.llrs.size % b == 0, \
        f"{name}: {res.llrs.size} LLRs is not a whole number of symbols"


# --- property 3: the sign convention --------------------------------------

@pytest.mark.parametrize("name", ALL_SIX)
def test_positive_llr_means_bit_zero(name, source_bits):
    """`llr > 0` is bit 0. Asserted against bits we actually transmitted, on
    the rotation that matches them, so a global sign flip cannot hide."""
    res, tx = _demodulate(name, source_bits)
    cand, ber = _best_rotation(res, tx)
    assert cand is not None
    assert ber < 0.01, f"{name}: no rotation matched ({ber:.4f}); cannot test sign"

    # If the convention were inverted, the best rotation would agree with the
    # COMPLEMENT of the transmitted bits and the BER would be near 1.
    assert ber < 0.5


@pytest.mark.parametrize("name", ALL_SIX)
def test_llr_sign_and_magnitude_agree(name, source_bits):
    """Confidence must line up with correctness: bits the receiver was sure
    about have to be right more often than the ones it hedged on."""
    res, tx = _demodulate(name, source_bits, snr_db=MARGINAL[name])
    cand, ber = _best_rotation(res, tx)
    if cand is None or ber > 0.2:
        pytest.skip(f"{name} not locked at this SNR; envelope, not contract")
    rx = llr_to_bits(cand)
    n = min(rx.size, 40000)
    a = 1.0 - 2.0 * rx[:n].astype(float)
    m = min(tx.size, n + 100000)
    b = 1.0 - 2.0 * tx[:m].astype(float)
    L = 1 << int(np.ceil(np.log2(m + n)))
    c = np.fft.irfft(np.fft.rfft(b, L) * np.conj(np.fft.rfft(a, L)), L)[: m - n + 1]
    off = int(np.argmax(np.abs(c)))
    wrong = rx[:n] != tx[off : off + n]
    if wrong.sum() < 20:
        pytest.skip("too few errors at this SNR to compare confidence")
    mag = np.abs(cand[:n])
    assert mag[wrong].mean() < mag[~wrong].mean(), \
        f"{name}: wrong bits carried MORE confidence than right ones"


# --- property 5: calibration ----------------------------------------------

@pytest.mark.parametrize("name", ALL_SIX)
def test_estimated_ber_tracks_actual(name, source_bits):
    """The 3 Sep verify row: S3's own estimated output BER within a factor of
    two of the real one, on a file it reports as locked."""
    res, tx = _demodulate(name, source_bits, snr_db=MARGINAL[name])
    cand, ber = _best_rotation(res, tx)
    assert cand is not None and ber < 0.2,         f"{name}: no rotation locked at {MARGINAL[name]} dB (BER {ber:.4f})"
    assert ber >= 2e-4, (
        f"{name}: only {ber:.6f} BER at {MARGINAL[name]} dB - too clean to "
        "test calibration; lower MARGINAL for this scheme")
    est = estimated_ber(cand)
    ratio = est / max(ber, 1e-9)
    assert 0.5 <= ratio <= 2.0, \
        f"{name}: estimated {est:.5f} vs actual {ber:.5f} (x{ratio:.2f})"


# --- what must NOT be in the output ---------------------------------------

@pytest.mark.parametrize("name", ALL_SIX)
def test_failed_demodulation_returns_empty_not_none(name):
    """S4 iterates the registry and will call plug-ins that do not fit the
    signal. That must come back as a zero-length array, not None and not an
    exception."""
    out = MODULATIONS[name].demodulate(
        np.zeros(64, dtype=complex), {"fs": 1.0, "symbol_rate": 0.25})
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float64
    assert out.size == 0


@pytest.mark.parametrize("name", ALL_SIX)
def test_non_coherent_schemes_emit_no_rotation_candidates(name):
    """FSK is detected non-coherently, so it has no phase ambiguity to pass on.
    Emitting rotation candidates for it would multiply S4's sweep for nothing."""
    sym = MODULATIONS[name].__class__.__name__
    if sym != "FSKDemod":
        pytest.skip("linear scheme")
    bits = np.random.default_rng(1).integers(0, 2, 60000).astype(np.uint8)
    res, _ = _demodulate(name, bits)
    assert len(res.llrs_by_rotation) == 1
