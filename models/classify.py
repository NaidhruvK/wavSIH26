"""models/classify.py

Serves the trained classifier in-process for live S2 (4 Sep column).
Model loaded once at import, never from user input, never retrained here.

Bridges the gap between S2's native captures (arbitrary fs, whatever sps
the signal actually has) and the classifier's training regime (fixed
4096-sample windows resampled to 8 samples/symbol, power-normalised) --
resample_window does that conversion using S2's OWN estimated symbol rate,
not a truth value.

OWNERSHIP: Dheeraj.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy.signal import resample_poly

from models.features import FEATURE_NAMES, FeatureVector, baseline_predict, extract_features

MODEL_PATH = Path(__file__).resolve().parent / "classifier.txt"
CLASSES = ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"]
TARGET_SPS = 8
WINDOW_LEN = 4096
CONFIDENCE_FLOOR = 0.70

_booster: lgb.Booster | None = None


def _get_booster() -> lgb.Booster:
    global _booster
    if _booster is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"{MODEL_PATH} missing -- run python -m models.build_dataset, "
                "python -m models.build_holdout, then python -m models.train"
            )
        _booster = lgb.Booster(model_file=str(MODEL_PATH))
    return _booster


def resample_window(iq: np.ndarray, fs: float, symbol_rate: float,
                     target_sps: int = TARGET_SPS, out_len: int = WINDOW_LEN
                     ) -> np.ndarray | None:
    """A power-normalised, target_sps-resampled window of out_len samples
    from the middle of `iq`, or None if `iq` is too short. Resample ratio
    is derived from S2's OWN symbol-rate estimate (target_sps*symbol_rate
    / fs), not truth -- classification has to work with only what S2 has
    already measured."""
    if not np.isfinite(symbol_rate) or symbol_rate <= 0 or len(iq) < 64:
        return None

    ratio = Fraction(target_sps * symbol_rate / fs).limit_denominator(1000)
    up, down = ratio.numerator, ratio.denominator
    if up <= 0 or down <= 0 or up > 50 or down > 50:
        return None   # native rate absurdly far from target; not worth resampling

    resampled = resample_poly(iq, up, down)
    if resampled.size < out_len:
        return None

    start = (resampled.size - out_len) // 2
    window = resampled[start:start + out_len]
    power = np.sqrt(np.mean(np.abs(window) ** 2))
    return window / (power if power > 0 else 1.0)


def classify(iq: np.ndarray, fs: float, symbol_rate: float, top_k: int = 3
             ) -> dict:
    """Ranked classification hypotheses for live S2. Returns:

        {"hypotheses": [(class_name, prob), ...],   # top_k, descending
         "low_confidence": bool,                     # top prob < 0.70
         "baseline_agrees": bool | None}

    On low confidence, the deterministic baseline's guess is folded into
    the hypothesis list if it isn't already the top pick -- per the ML
    spec's failure-handling design: ranked hypotheses let S3/S4 attempt
    more than one candidate and let the rank test reject the wrong ones,
    which is what makes six classes affordable instead of six times the
    risk. Returns {"hypotheses": [], "low_confidence": True,
    "baseline_agrees": None} if there isn't enough signal to window.
    """
    window = resample_window(iq, fs, symbol_rate)
    if window is None:
        return {"hypotheses": [], "low_confidence": True, "baseline_agrees": None}

    fv = extract_features(window, fs=TARGET_SPS * symbol_rate)
    proba = _get_booster().predict(fv.values.reshape(1, -1))[0]
    order = np.argsort(proba)[::-1][:top_k]
    hypotheses = [(CLASSES[i], float(proba[i])) for i in order]

    low_confidence = hypotheses[0][1] < CONFIDENCE_FLOOR
    baseline_agrees = None
    if low_confidence:
        baseline_guess = baseline_predict(fv)
        baseline_agrees = baseline_guess == hypotheses[0][0]
        if baseline_guess not in dict(hypotheses):
            hypotheses.append((baseline_guess, 0.0))

    return {"hypotheses": hypotheses, "low_confidence": low_confidence,
            "baseline_agrees": baseline_agrees}
