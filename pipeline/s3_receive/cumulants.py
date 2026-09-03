"""Higher-order cumulants.

The MODULATIONS registry protocol asks every plug-in for
theoretical_cumulants(), so the UI can show a measured cumulant beside its
closed-form value and a judge can read why the answer is 8-PSK without trusting
a model. That makes the values S3's responsibility even though the classifier
that consumes them is S2's.

The theoretical values are evaluated exactly over the finite constellation
rather than copied from a table. Published cumulant tables differ in
normalisation and sign convention between sources, and a transcription error
would be invisible until it quietly cost accuracy in S2. Evaluating the same
estimator on the noiseless constellation cannot disagree with itself.

Estimator conventions (Swami & Sadler), for zero-mean unit-power s:
    C20 = E[s^2]
    C21 = E[|s|^2]
    C40 = E[s^4]      - 3 C20^2
    C41 = E[s^3 s*]   - 3 C20 C21
    C42 = E[|s|^4]    - |C20|^2 - 2 C21^2
    C60 = E[s^6]      - 15 C20 C40 - 15 C20^3
    C63 = E[|s|^6]    - 9 C42 C21 - 6 C21^3
"""
from __future__ import annotations

import numpy as np

__all__ = ["cumulants", "normalise_power", "CUMULANT_KEYS"]

CUMULANT_KEYS = ("C20", "C21", "C40", "C41", "C42", "C60", "C63")


def normalise_power(s: np.ndarray) -> np.ndarray:
    s = np.asarray(s, dtype=np.complex128)
    s = s - np.mean(s)
    p = np.sqrt(np.mean(np.abs(s) ** 2))
    return s / p if p > 0 else s


def cumulants(s: np.ndarray, normalise: bool = True) -> dict[str, complex]:
    """Sample cumulants of a complex sequence. Feed it a constellation and the
    result is the closed-form value; feed it a received window and the result is
    the measurement to compare against it."""
    x = normalise_power(s) if normalise else np.asarray(s, dtype=np.complex128)
    if x.size == 0:
        return {k: complex("nan") for k in CUMULANT_KEYS}

    m20 = np.mean(x**2)
    m21 = np.mean(np.abs(x) ** 2)
    m40 = np.mean(x**4)
    m41 = np.mean(x**3 * np.conj(x))
    m42 = np.mean(np.abs(x) ** 4)
    m60 = np.mean(x**6)
    m63 = np.mean(np.abs(x) ** 6)

    c20 = m20
    c21 = m21
    c40 = m40 - 3.0 * c20**2
    c41 = m41 - 3.0 * c20 * c21
    c42 = m42 - np.abs(c20) ** 2 - 2.0 * c21**2
    c60 = m60 - 15.0 * c20 * c40 - 15.0 * c20**3
    c63 = m63 - 9.0 * c42 * c21 - 6.0 * c21**3

    return {"C20": complex(c20), "C21": complex(c21), "C40": complex(c40),
            "C41": complex(c41), "C42": complex(c42), "C60": complex(c60),
            "C63": complex(c63)}
