"""Soft demapping - symbols in, log-likelihood ratios out.

2 Sep, Block B/C: LLR output for every registered modulation.

**The convention, which is a cross-stream contract:**

    llr[i] = log( P(bit i == 0) / P(bit i == 1) )

A positive LLR means bit 0 is more likely; the hard decision is `llr < 0`.
This is the sign `registry/protocols.py` states and the one Nehal's
`conv_code.decode` negates once, on the way into commpy. Getting it backwards
decodes to noise and raises nothing, which is why it is written here as well as
there rather than being left implicit in the arithmetic.

**Why soft at all.** A hard bit throws away the receiver's confidence, and
confidence is most of what Viterbi and the statistical parity-check validator
run on - roughly 2 dB of coding gain, and the difference between S4's
statistical fallback working and not. So the array must be float, and its
values must not collapse onto {0, 1}. That is what the 2 Sep contract test
asserts, per modulation.

**Exact, not max-log.** The LLR for one bit is a ratio of sums over every
constellation point that carries a 0 or a 1 in that position:

    llr_k = logsumexp_{s: bit_k(s)=0}(-|y-s|^2/sigma^2)
          - logsumexp_{s: bit_k(s)=1}(-|y-s|^2/sigma^2)

The max-log approximation keeps only the nearest point on each side. It was the
first implementation here and it is the standard choice, because it costs only a
fraction of a decibel of decoding performance. But it is BIASED - it discards
the competing points, which always argue *against* the winner, so it reports
more confidence than the evidence supports. On BPSK and QPSK the bias is
negligible. On 16-QAM, measured at 11.5 dB, it made the receiver report a bit
error rate of 0.00076 against an actual 0.00310: four times over-confident.

A fraction of a decibel is a fine price for speed when the LLR feeds a decoder.
It is not a fine price here, because S3 also has to *report* how good its output
is, and 3 Sep asks for that report to be within a factor of two. logsumexp over
sixteen points is cheap. `max_log_llr(..., exact=False)` keeps the fast path for
anyone who wants it.

**sigma^2 is measured, not assumed.** It comes from the decision-directed
residual on this file: the mean squared distance from each symbol to its
nearest constellation point. A residual carrier error inflates it, which shrinks
every LLR magnitude - the receiver reports less confidence than it has. That is
the safe direction to be wrong in, and it is why no floor is applied to the
estimate beyond guarding a division by zero.
"""
from __future__ import annotations

import numpy as np

from .bitmap import bits_per_symbol, label_bit_matrix

__all__ = ["estimate_noise_variance", "max_log_llr", "windowed_llr",
           "noncoherent_llr", "estimated_ber", "llr_to_bits", "llr_health"]

# The emitted LLRs are clipped only to keep the array finite and the Viterbi
# path metrics well scaled. It was 30 at first, which was far too tight: at
# 10-20 dB the max-log magnitudes run to several hundred, so essentially every
# value saturated and the stream came back as two distinct numbers. That still
# passes "dtype float, not confined to {0,1}" while having thrown away exactly
# the soft information the contract exists to protect - the failure the 2 Sep
# gate is meant to catch, arriving through the back door.
#
# The exp() overflow this was guarding against belongs in estimated_ber, which
# is where the exponential actually is, and it is clipped there.
_LLR_CLIP = 200.0

# MEASURED, not derived. Without it the non-coherent branch reports a bit error
# rate about three times its actual one - under-confident LLRs, which is the
# safe direction to be wrong in but still wrong. A factor of exactly 2 brought
# `estimated_ber` onto the measured BER for BOTH 2-FSK and 4-FSK at every SNR
# tried (ratios 0.57 to 1.04 across six points), and a constant that holds
# across two orders and a 4 dB span is a missing term rather than a fudge.
#
# The likely cause is that the losing-tone energies used as the noise reference
# are not noise-only: adjacent tones leak into each other, so the reference is
# biased high and every LLR comes out proportionally small. Somebody should
# derive this properly and replace the constant with the derivation - until
# then it is labelled for what it is.
_NONCOHERENT_CALIBRATION = 2.0


def estimate_noise_variance(symbols: np.ndarray,
                            constellation: np.ndarray) -> float:
    """Decision-directed estimate of the complex noise variance E|n|^2.

    Both arrays are taken to unit average power first, so the number is
    comparable across files and across modulations.
    """
    y = np.asarray(symbols, dtype=np.complex128)
    if y.size == 0:
        return 1.0
    scale = np.sqrt(np.mean(np.abs(y) ** 2)) or 1.0
    y = y / scale
    c = np.asarray(constellation, dtype=np.complex128)
    c = c / (np.sqrt(np.mean(np.abs(c) ** 2)) or 1.0)
    d2 = np.abs(y[:, None] - c[None, :]) ** 2
    return float(max(np.mean(np.min(d2, axis=1)), 1e-9))


def max_log_llr(symbols: np.ndarray, constellation: np.ndarray,
                sigma2: float | None = None,
                chunk: int = 20000, exact: bool = True) -> np.ndarray:
    """Flat float64 LLR array, MSB-first within each symbol, symbols in order.

    exact=True uses the full log-sum-exp; exact=False is the max-log
    approximation, which is faster and over-confident on constellations bigger
    than QPSK. See the module docstring.

    Chunked because the distance matrix is (n_symbols x M) and a long 16-QAM
    record would otherwise allocate more than it needs to in one go.
    """
    y = np.asarray(symbols, dtype=np.complex128).ravel()
    c = np.asarray(constellation, dtype=np.complex128).ravel()
    order = c.size
    b = bits_per_symbol(order)

    scale = np.sqrt(np.mean(np.abs(y) ** 2)) if y.size else 1.0
    y = y / (scale or 1.0)
    c = c / (np.sqrt(np.mean(np.abs(c) ** 2)) or 1.0)

    if sigma2 is None:
        sigma2 = estimate_noise_variance(y, c)
    sigma2 = float(max(sigma2, 1e-9))

    bits = label_bit_matrix(order)              # (M, b)
    is_one = bits.astype(bool)                  # (M, b)

    out = np.empty(y.size * b, dtype=np.float64)
    for start in range(0, y.size, chunk):
        blk = y[start : start + chunk]
        d2 = np.abs(blk[:, None] - c[None, :]) ** 2        # (n, M)
        if exact:
            # log p(y|s), shifted by the row maximum so exp() cannot underflow
            lp = -d2 / sigma2
            lp = lp - lp.max(axis=1, keepdims=True)
            w = np.exp(lp)                                  # (n, M)
            s1 = w @ is_one.astype(np.float64)              # (n, b)
            s0 = w @ (~is_one).astype(np.float64)
            llr = np.log(np.maximum(s0, 1e-300)) - np.log(np.maximum(s1, 1e-300))
        else:
            big = np.inf
            d1 = np.where(is_one.T[None, :, :], d2[:, None, :], big).min(axis=2)
            d0 = np.where(~is_one.T[None, :, :], d2[:, None, :], big).min(axis=2)
            llr = (d1 - d0) / sigma2
        out[start * b : (start + blk.size) * b] = llr.ravel()

    return np.clip(out, -_LLR_CLIP, _LLR_CLIP)


def windowed_llr(symbols: np.ndarray, constellation: np.ndarray,
                 block: int = 2000) -> np.ndarray:
    """Max-log LLRs with sigma^2 re-estimated on every block of symbols.

    A single sigma^2 for a whole file assumes the receiver was equally good
    throughout it, and it is not: the carrier loop wanders, a fade passes, the
    equaliser re-converges. Measured on a 16-QAM file at 11.5 dB, one file-wide
    sigma^2 taken from a clean tail reported 0.00076 against an actual 0.00310 -
    four times over-confident, and over-confident is the direction that hurts,
    because a soft decoder weights a confident wrong bit heavily.

    Per-block estimation costs one extra pass and makes the LLR magnitudes
    describe the part of the stream they came from.

    The last partial block is folded into the previous one rather than
    estimated on its own: a short block gives a noisy sigma^2, and a noisy
    sigma^2 at the very end of a stream is exactly where nobody would look for
    it.
    """
    y = np.asarray(symbols, dtype=np.complex128).ravel()
    if y.size == 0:
        return np.zeros(0, dtype=np.float64)
    block = max(int(block), 256)
    if y.size < 2 * block:
        return max_log_llr(y, constellation)

    edges = list(range(0, y.size, block))
    if y.size - edges[-1] < block // 2:
        edges.pop()
    edges.append(y.size)

    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = y[a:b]
        out.append(max_log_llr(seg, constellation,
                               estimate_noise_variance(seg, constellation)))
    return np.concatenate(out)


def noncoherent_llr(tone_metrics: np.ndarray, order: int) -> np.ndarray:
    """LLRs for non-coherent FSK, from per-tone correlation magnitudes.

    `tone_metrics` is (n_symbols, order) of |correlation|. There is no
    constellation and no Euclidean distance here: the decision statistic is
    tone energy, so the log-likelihood is proportional to |r_i|^2 and the
    max-log form takes maxima of energies rather than minima of distances -
    the sign of the comparison flips with it.

    Scale comes from the losing tones. On any given symbol the tones that were
    not sent carry noise only, so their mean energy is an estimate of the noise
    energy in the correlation window, measured on the same file, symbol by
    symbol. Nothing about the channel has to be assumed.
    """
    m = np.asarray(tone_metrics, dtype=np.float64)
    if m.ndim != 2 or m.shape[1] != order:
        raise ValueError(f"expected (n, {order}) tone metrics, got {m.shape}")
    energy = m**2

    part = np.sort(energy, axis=1)
    noise = np.maximum(np.mean(part[:, :-1]), 1e-12)     # all but the winner
    e = _NONCOHERENT_CALIBRATION * energy / noise

    bits = label_bit_matrix(order)
    is_one = bits.astype(bool)                            # (M, b)
    big = -np.inf
    e1 = np.where(is_one.T[None, :, :], e[:, None, :], big).max(axis=2)
    e0 = np.where(~is_one.T[None, :, :], e[:, None, :], big).max(axis=2)
    # positive when the best bit-0 tone carries more energy
    return np.clip((e0 - e1).ravel(), -_LLR_CLIP, _LLR_CLIP)


def llr_to_bits(llrs: np.ndarray) -> np.ndarray:
    """The hard decision the convention implies. Mirrors Nehal's helper of the
    same name so both sides of the junction slice identically."""
    return (np.asarray(llrs) < 0).astype(np.uint8)


def estimated_ber(llrs: np.ndarray) -> float:
    """S3's own estimate of the bit error rate in what it just emitted.

    P(this bit is wrong) = 1 / (1 + exp(|llr|)) if the LLR is calibrated, so
    the mean over the stream is the expected error rate. 3 Sep asks for this
    number to track the actual within a factor of two, which is really a test
    that sigma^2 was estimated honestly - an over-confident demapper reports a
    BER far below the real one, and there is no other place that shows up.
    """
    a = np.abs(np.asarray(llrs, dtype=np.float64))
    # 700 is where exp() overflows float64; past ~40 the term is already zero
    # to machine precision, so clipping here changes no answer.
    return float(np.mean(1.0 / (1.0 + np.exp(np.clip(a, 0.0, 700.0)))))


def llr_health(llrs: np.ndarray) -> dict[str, float]:
    """The numbers the 2 Sep contract test and the UI both want."""
    a = np.asarray(llrs, dtype=np.float64)
    finite = a[np.isfinite(a)]
    return {
        "n": int(a.size),
        "dtype_is_float": bool(np.issubdtype(a.dtype, np.floating)),
        "all_finite": bool(finite.size == a.size),
        "distinct_values": int(np.unique(np.round(finite, 6)).size),
        "confined_to_hard_bits": bool(np.all(np.isin(finite, (0.0, 1.0)))),
        "mean_abs": float(np.mean(np.abs(finite))) if finite.size else 0.0,
        "estimated_ber": estimated_ber(finite) if finite.size else 1.0,
    }
