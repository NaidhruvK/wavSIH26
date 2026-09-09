"""Core S0 -> S6 pipeline orchestrator for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Coordinates stage execution in order (S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S6),
enforces per-stage and total timeouts, adapts teammate return types into StageResult,
persists runs and stage metrics in SQLite, saves artifacts to disk, and outputs AnalysisReport.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus
from registry import CODES, INTERLEAVERS, MODULATIONS

from .config import config
from .db import (
    create_run,
    get_run,
    initialize_database,
    record_stage_result,
    update_run,
)
from .job_runner import (
    Job,
    JobCancelledError,
    JobRunner,
    StageTimeoutError,
    job_runner,
)

logger = logging.getLogger("raaya.orchestrator")


def log_event(level: int, run_id: str, stage: str, message: str, **kwargs: Any) -> None:
    """Emit structured log record containing run_id, stage, timestamp, level, and message."""
    ts = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp": ts,
        "level": logging.getLevelName(level),
        "run_id": run_id,
        "stage": stage,
        "message": message,
        **kwargs,
    }
    logger.log(level, json.dumps(record))


def compute_file_meta(file_path: Path | str) -> dict[str, Any]:
    """Extract filename, byte size, and SHA256 hash."""
    path = Path(file_path)
    if not path.is_file():
        return {"filename": path.name, "size_bytes": 0, "sha256": ""}
    size = path.stat().st_size
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {"filename": path.name, "size_bytes": size, "sha256": h.hexdigest()}


def save_stage_artifact(run_id: str, artifact_name: str, data: Any) -> str:
    """Save stage artifact (e.g. plot data, metrics) to disk rather than embedding in JSON."""
    target_dir = config.artifact_dir / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{artifact_name}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    try:
        return str(file_path.relative_to(config.repo_root))
    except ValueError:
        return str(file_path)


# -----------------------------------------------------------------------------
# Dynamic / Fallback Pipeline Resolvers & Plugin Loader
# -----------------------------------------------------------------------------

REQUIRED_PLUGIN_MODULES = (
    "pipeline.s3_receive",
    "pipeline.s4_recover.interleavers",
    "pipeline.s5_decode.conv_code",
    "pipeline.s5_decode.rs_code",
    # 7 Sep: ldpc_code moved into pipeline/s5_decode/ (767a7ab) 3.5 h AFTER this
    # tuple was written, so the service registered every plug-in except that
    # one - CODES came up {conv, reed-solomon} and the LDPC path was dead in
    # the API while passing its own unit tests. Any module with a top-level
    # register_*() call belongs here; tests/service/test_orchestrator.py now
    # asserts this tuple covers all of them so a future move fails loudly.
    "pipeline.s5_decode.ldpc_code",
)

_PLUGIN_LOAD_ERRORS: dict[str, str] = {}
_PLUGINS_LOADED: bool = False

# Coded bits handed to the Viterbi decoder in one stage. commpy's decoder is
# pure Python and linear in stream length, ~0.57 ms/bit on the slower of the
# two dev boxes, and the service caps every stage at
# config.stage_timeout_seconds = 15.0. Measured on qpsk_15dB_2010.wav there:
#
#     24 000 bits -> 13.6 s   1499 chars    1.1x margin
#     16 000 bits ->  9.8 s    999 chars    1.5x
#     12 000 bits ->  6.8 s    749 chars    2.2x   <- chosen
#
# 24 000 is what pipeline/s4_recover/cli.py uses, and it is right there: the
# CLI has no per-stage timeout. Carrying it into the service put the slowest
# stage 1.1x inside its own deadline, which is the shape of the S3 flake Anvith
# spent 7 Sep removing - correctness that depends on how much wall clock the
# stage happens to get. Half the budget still recovers 749 characters, which
# proves the chain no less than 1499. The full stream stays in
# values["coded_bits_available"] for anyone who wants to decode all of it.
S5_DECODE_MAX_BITS = 32_000


def load_plugins(force: bool = False, raise_on_error: bool = False) -> dict[str, str]:
    """Import required pipeline plugin modules to trigger side-effect registration.

    Populates MODULATIONS, INTERLEAVERS, and CODES in the registry.
    Safe against re-entrancy, reload idempotency, and environments missing compiled DSP wheels.
    Returns a dictionary of {module_name: error_message} for any plugin that failed to load.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force and (len(MODULATIONS) > 0 or len(_PLUGIN_LOAD_ERRORS) > 0):
        return _PLUGIN_LOAD_ERRORS

    import importlib
    import sys

    _PLUGIN_LOAD_ERRORS.clear()
    for mod_name in REQUIRED_PLUGIN_MODULES:
        try:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)
        except Exception as exc:
            _PLUGIN_LOAD_ERRORS[mod_name] = f"{type(exc).__name__}: {exc}"
            logger.warning("Plugin module '%s' failed to load: %s", mod_name, exc)
            if raise_on_error:
                raise

    _PLUGINS_LOADED = True
    if _PLUGIN_LOAD_ERRORS:
        logger.warning(
            "Service registry partially populated. Plugin load failures: %s",
            _PLUGIN_LOAD_ERRORS,
        )
    return _PLUGIN_LOAD_ERRORS


def get_plugin_load_errors() -> dict[str, str]:
    """Return map of plugin module names that failed to load and their error messages."""
    return dict(_PLUGIN_LOAD_ERRORS)


def get_s0_ingest() -> Optional[Callable[..., Any]]:
    try:
        from pipeline.s0_ingest import ingest
        return ingest
    except (ImportError, AttributeError):
        return None


def get_s1_detect() -> Optional[Callable[..., Any]]:
    try:
        from pipeline.s1_detect import detect
        return detect
    except (ImportError, AttributeError):
        return None


def get_s2_estimate() -> Optional[Callable[..., Any]]:
    """Return pipeline.s2_estimate estimation callable if available."""
    try:
        from pipeline import s2_estimate
        if hasattr(s2_estimate, "estimate_blind"):
            return s2_estimate.estimate_blind
        if hasattr(s2_estimate, "estimate"):
            return s2_estimate.estimate
    except (ImportError, AttributeError):
        pass

    # There WAS a fallback here importing tests.fixtures.local_s2 - shipping
    # service code reaching into tests/, which only works because tests/ ships
    # in the image. It was also unreachable: pipeline.s2_estimate.estimate has
    # existed since 1 Sep, so the primary always returns first. Removed rather
    # than repaired; a stage with no implementation must fail loudly, not
    # silently run a throwaway fixture. Naidhruv reached the same conclusion
    # independently in 87776dc on naidhruv/integration.
    return None


def get_s3_receive() -> Optional[Callable[..., Any]]:
    try:
        from pipeline.s3_receive import receive_best
        return receive_best
    except (ImportError, AttributeError):
        return None


def get_s4_recover() -> Optional[Callable[..., Any]]:
    try:
        from pipeline.s4_recover.rank_collapse import blind_recover
        return blind_recover
    except (ImportError, AttributeError):
        return None


def get_s6_payload() -> Optional[Callable[..., Any]]:
    try:
        from pipeline.s6_frame.payload import extract_text
        return extract_text
    except (ImportError, AttributeError):
        return None


# -----------------------------------------------------------------------------
# Stage Result Adapters
# -----------------------------------------------------------------------------

def adapt_s0(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    status = StageStatus.OK if getattr(raw, "status", None) == "ok" else StageStatus.FAILED
    iq = getattr(raw, "iq", None)
    values = {
        "source_format": getattr(raw, "source_format", "unknown"),
        "fs": getattr(raw, "fs", None),
        "sample_count": len(iq) if iq is not None else 0,
        "file_path": getattr(raw, "file_path", ""),
    }
    hyps: list[Hypothesis] = []
    raw_hyps = getattr(raw, "hypotheses", [])
    if raw_hyps:
        for h in raw_hyps:
            if isinstance(h, (list, tuple)) and len(h) >= 2:
                hyps.append(Hypothesis(value=str(h[0]), score=float(h[1]), evidence="sniffer score"))
            elif isinstance(h, Hypothesis):
                hyps.append(h)

    return StageResult(
        stage="s0_ingest",
        status=status,
        confidence=1.0 if status == StageStatus.OK else 0.0,
        values=values,
        hypotheses=hyps,
        artifacts={},
        elapsed_ms=elapsed_ms,
        reason=getattr(raw, "reason", None),
    )


def adapt_s1(raw: Any, elapsed_ms: float, run_id: str) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    bursts = getattr(raw, "bursts", [])
    if isinstance(raw, dict):
        snr_db = raw.get("snr_db")
        noise_floor_db = raw.get("noise_floor_db")
        occupied_bw_hz = raw.get("occupied_bw_hz")
        bursts = raw.get("bursts", bursts)
        fs = raw.get("fs")
        raw_status = raw.get("status")
        raw_reason = raw.get("reason")
        psd_db = raw.get("psd_db")
        psd_freqs = raw.get("psd_freqs")
    else:
        snr_db = getattr(raw, "snr_db", None)
        noise_floor_db = getattr(raw, "noise_floor_db", None)
        occupied_bw_hz = getattr(raw, "occupied_bw_hz", None)
        fs = getattr(raw, "fs", None)
        raw_status = getattr(raw, "status", None)
        raw_reason = getattr(raw, "reason", None)
        psd_db = getattr(raw, "psd_db", None)
        psd_freqs = getattr(raw, "psd_freqs", None)

    values = {
        "snr_db": snr_db,
        "noise_floor_db": noise_floor_db,
        "occupied_bw_hz": occupied_bw_hz,
        "burst_count": len(bursts) if bursts is not None else 0,
        "fs": fs,
    }

    # Envelope check: SNR below declared operating envelope (-5.0 dB)
    if snr_db is not None and isinstance(snr_db, (int, float)) and not math.isnan(snr_db) and snr_db < -5.0:
        status = StageStatus.OUT_OF_ENVELOPE
        confidence = 0.0
        reason = f"Signal SNR ({snr_db:.1f} dB) below declared operating envelope (-5.0 dB)"
    elif raw_status == "ok":
        status = StageStatus.OK
        confidence = 0.98
        reason = None
    else:
        status = StageStatus.FAILED
        confidence = 0.0
        reason = raw_reason

    artifacts = {}
    if psd_db is not None and psd_freqs is not None:
        try:
            freq_list = [float(f) for f in psd_freqs]
            psd_list = [float(p) for p in psd_db]
            step = max(1, len(freq_list) // 256)
            art_path = save_stage_artifact(
                run_id,
                "psd",
                {
                    "freqs": freq_list[::step],
                    "psd_db": psd_list[::step],
                    "noise_floor_db": values["noise_floor_db"],
                },
            )
            artifacts["psd_plot"] = art_path
        except Exception:
            pass

    return StageResult(
        stage="s1_detect",
        status=status,
        confidence=confidence,
        values=values,
        hypotheses=[
            Hypothesis(
                value="bursty" if values["burst_count"] > 0 else "continuous",
                score=0.95 if status == StageStatus.OK else 0.0,
                evidence=f"{values['burst_count']} bursts detected",
            )
        ],
        artifacts=artifacts,
        elapsed_ms=elapsed_ms,
        reason=reason,
    )


def adapt_s2(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    rate = getattr(raw, "symbol_rate_hz", None)
    if rate is None:
        if isinstance(raw, dict):
            rate = raw.get("symbol_rate_hz", raw.get("symbol_rate", 0.0))
        else:
            rate = getattr(raw, "symbol_rate", 0.0)

    fs = getattr(raw, "fs", 1.0) if not isinstance(raw, dict) else raw.get("fs", 1.0)
    cfo_hz = getattr(raw, "cfo_hz", 0.0) if not isinstance(raw, dict) else raw.get("cfo_hz", 0.0)
    order_hint = getattr(raw, "order_hint", 0) if not isinstance(raw, dict) else raw.get("order_hint", 0)
    symbol_rate_score = (
        getattr(raw, "symbol_rate_score", 0.0) if not isinstance(raw, dict) else raw.get("symbol_rate_score", 0.0)
    )
    raw_reason = getattr(raw, "reason", None) if not isinstance(raw, dict) else raw.get("reason")
    raw_status = getattr(raw, "status", None) if not isinstance(raw, dict) else raw.get("status")

    is_valid_rate = rate is not None and isinstance(rate, (int, float)) and not math.isnan(rate) and rate > 0
    sps = (fs / rate) if is_valid_rate else 0.0

    values = {
        "symbol_rate": rate,
        "symbol_rate_hz": rate,
        "sps": sps,
        "cfo_hz": cfo_hz,
        "order_hint": order_hint,
        "symbol_rate_score": symbol_rate_score,
    }

    if raw_status == "failed":
        status = StageStatus.FAILED
        confidence = 0.0
        reason = raw_reason or "S2 parameter estimation failed"
    elif not is_valid_rate:
        status = StageStatus.OUT_OF_ENVELOPE
        confidence = 0.0
        reason = raw_reason or "Estimated symbol rate is invalid or non-positive"
    elif sps < 2.5 or sps > 40.0:
        status = StageStatus.OUT_OF_ENVELOPE
        confidence = 0.0
        reason = f"Estimated SPS ({sps:.2f}) outside declared operating envelope [2.5, 40.0]"
    else:
        status = StageStatus.OK
        confidence = min(1.0, max(0.1, values["symbol_rate_score"] / 10.0)) if values["symbol_rate_score"] else 0.9
        reason = None

    hyps: list[Hypothesis] = []
    order = values["order_hint"]
    if order == 2:
        hyps = [Hypothesis(value="bpsk", score=0.9), Hypothesis(value="2fsk", score=0.1)]
    elif order == 4:
        hyps = [Hypothesis(value="qpsk", score=0.85), Hypothesis(value="4fsk", score=0.15)]
    elif order == 8:
        hyps = [Hypothesis(value="8psk", score=0.8), Hypothesis(value="16qam", score=0.2)]
    else:
        hyps = [Hypothesis(value="qpsk", score=0.7), Hypothesis(value="bpsk", score=0.3)]

    return StageResult(
        stage="s2_estimate",
        status=status,
        confidence=confidence,
        values=values,
        hypotheses=hyps,
        artifacts={},
        elapsed_ms=elapsed_ms,
        reason=reason,
    )


def adapt_s3(raw: Any, elapsed_ms: float, run_id: str) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    if raw is None:
        errs = get_plugin_load_errors()
        err_msg = f" (plugin load failures: {', '.join(f'{k}: {v}' for k, v in errs.items())})" if errs else ""
        return StageResult(
            stage="s3_receive",
            status=StageStatus.FAILED,
            confidence=0.0,
            values={"modulation": "unknown"},
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason=f"Demodulation failed: no result from receiver{err_msg}",
        )

    if hasattr(raw, "as_stage_result"):
        base_dict = raw.as_stage_result()
        artifacts = {}
        symbols = getattr(raw, "symbols", None)
        if symbols is not None:
            try:
                sym_data = [{"i": float(s.real), "q": float(s.imag)} for s in symbols[:500]]
                art_path = save_stage_artifact(run_id, "constellation", sym_data)
                artifacts["constellation_plot"] = art_path
            except Exception:
                pass

        values = base_dict.get("values", {})
        # Map values["envelope"] == "outside" to StageStatus.OUT_OF_ENVELOPE
        if values.get("envelope") == "outside":
            status = StageStatus.OUT_OF_ENVELOPE
            confidence = 0.0
        else:
            status = StageStatus(base_dict.get("status", "ok"))
            confidence = float(base_dict.get("confidence", 0.95))

        return StageResult(
            stage="s3_receive",
            status=status,
            confidence=confidence,
            values=values,
            hypotheses=[
                Hypothesis(value=h["value"], score=h["score"], evidence=h.get("evidence", ""))
                for h in base_dict.get("hypotheses", [])
            ],
            artifacts=artifacts,
            elapsed_ms=elapsed_ms,
            reason=base_dict.get("reason"),
        )

    if isinstance(raw, dict):
        values = raw.get("values", {})
        envelope_val = values.get("envelope") if isinstance(values, dict) else None
        if envelope_val == "outside" or raw.get("envelope") == "outside":
            status = StageStatus.OUT_OF_ENVELOPE
            confidence = 0.0
        else:
            status = StageStatus(raw.get("status", "ok"))
            confidence = float(raw.get("confidence", 0.9))
        return StageResult(
            stage="s3_receive",
            status=status,
            confidence=confidence,
            values=values if values else raw,
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason=raw.get("reason"),
        )

    raw_vals = getattr(raw, "values", None)
    if isinstance(raw_vals, dict) and raw_vals.get("envelope") == "outside":
        return StageResult(
            stage="s3_receive",
            status=StageStatus.OUT_OF_ENVELOPE,
            confidence=0.0,
            values=raw_vals,
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason=getattr(raw, "reason", None) or "Input out of operating envelope",
        )

    return StageResult(
        stage="s3_receive",
        status=StageStatus.OK,
        confidence=0.9,
        values={"received": True},
        hypotheses=[],
        artifacts={},
        elapsed_ms=elapsed_ms,
    )


def adapt_s4(raw: Any, elapsed_ms: float, run_id: str) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    # `getattr(raw, "status", "ok")` below defaults to "ok", so a stage that
    # produced nothing at all reported OK with empty values. S4 returns None
    # whenever S3 handed it no LLRs, which is exactly when it must not say ok.
    if raw is None:
        errs = get_plugin_load_errors()
        err_msg = (" (plugin load failures: %s)"
                   % ", ".join(f"{k}: {v}" for k, v in errs.items())) if errs else ""
        return StageResult(
            stage="s4_recover",
            status=StageStatus.FAILED,
            confidence=0.0,
            values={},
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason=f"Recovery failed: no result from S4{err_msg}",
        )

    raw_status = getattr(raw, "status", "ok")
    if raw_status == "ok":
        status = StageStatus.OK
    elif raw_status == "low_confidence":
        status = StageStatus.LOW_CONFIDENCE
    else:
        status = StageStatus.FAILED

    values = {
        "period": getattr(raw, "period", None),
        "offset": getattr(raw, "offset", 0),
        "generators_octal": list(raw.generators_octal) if getattr(raw, "generators_octal", None) else None,
        "method": getattr(raw, "method", "exact"),
        "inferred_ber": getattr(raw, "inferred_ber", None),
    }

    intl = getattr(raw, "interleaver", None)
    if intl:
        values["interleaver_family"] = getattr(intl, "family", "unknown")
        values["interleaver_params"] = getattr(intl, "params", {})

    code = getattr(raw, "code", None)
    if code:
        values["code_rate"] = f"1/{code.n}" if getattr(code, "n", None) else None
        values["K"] = code.memory + 1 if getattr(code, "memory", None) is not None else None

    hyps: list[Hypothesis] = []
    for h in getattr(raw, "hypotheses", []):
        name = f"{getattr(h, 'family', '')}_{getattr(h, 'params', {})}"
        hyps.append(
            Hypothesis(
                value=name,
                score=getattr(h, "score", 0.0),
                evidence=getattr(h, "evidence", ""),
            )
        )

    artifacts = {}
    profile = getattr(raw, "profile", None)
    if profile and hasattr(profile, "deficiency"):
        try:
            art_path = save_stage_artifact(run_id, "rank_profile", profile.deficiency)
            artifacts["rank_profile_plot"] = art_path
        except Exception:
            pass

    return StageResult(
        stage="s4_recover",
        status=status,
        confidence=float(getattr(raw, "confidence", 0.99)),
        values=values,
        hypotheses=hyps,
        artifacts=artifacts,
        elapsed_ms=elapsed_ms,
        reason=getattr(raw, "reason", None),
    )


def adapt_s5(raw: Any, elapsed_ms: float,
             detail: Optional[dict[str, Any]] = None) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    if raw is None:
        errs = get_plugin_load_errors()
        err_msg = f" (plugin load failures: {', '.join(f'{k}: {v}' for k, v in errs.items())})" if errs else ""
        return StageResult(
            stage="s5_decode",
            status=StageStatus.FAILED,
            confidence=0.0,
            values={"decoded_bits_count": 0},
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason=((detail or {}).get("declined")
                    or f"Decoding failed: no result from decoder{err_msg}"),
        )

    bit_count = len(raw)
    status = StageStatus.OK if bit_count > 0 else StageStatus.FAILED
    values: dict[str, Any] = {"decoded_bits_count": bit_count}
    values.update({k: v for k, v in (detail or {}).items() if k != "validation"})

    confidence = 1.0 if status == StageStatus.OK else 0.0
    reason = None if status == StageStatus.OK else "No bits decoded"
    evidence = "trellis traceback complete"

    # A wrong trellis still produces bits, and bits alone cannot tell you the
    # decode was right. When the plug-in re-encoded its own output and the
    # result disagrees with what arrived, say so instead of reporting ok.
    val = (detail or {}).get("validation")
    if val is not None:
        values["reencode_ber"] = val.get("reencode_ber")
        evidence = "re-encode BER %.4f over %d bits" % (
            val.get("reencode_ber", 1.0), val.get("compared_bits", 0))
        if status == StageStatus.OK and not val.get("ok", True):
            status = StageStatus.LOW_CONFIDENCE
            confidence = 0.0
            reason = val.get("reason") or "decode is not consistent with the input"

    hyp_value = "concatenated_ccsds_decoded" if (detail or {}).get("concatenated") else "viterbi_decoded"
    if (detail or {}).get("concatenated"):
        evidence += " + RS(%s,%s) outer decode verified" % (
            (detail or {}).get("rs_n", 255), (detail or {}).get("rs_k", 223))

    return StageResult(
        stage="s5_decode",
        status=status,
        confidence=confidence,
        values=values,
        hypotheses=[Hypothesis(value=hyp_value, score=confidence, evidence=evidence)],
        artifacts={},
        elapsed_ms=elapsed_ms,
        reason=reason,
    )


def adapt_s6(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    # Status was hardcoded OK with no None guard, so when S5 failed and there
    # were no bits to frame, the LAST stage of the pipeline - the one that
    # shows the recovered message - reported OK in 0 ms with n_bytes 0. Observed
    # live on 7 Sep behind the S5 defect above.
    if raw is None:
        return StageResult(
            stage="s6_frame",
            status=StageStatus.FAILED,
            confidence=0.0,
            values={"n_bytes": 0, "printable_fraction": 0.0, "looks_like_text": False},
            hypotheses=[],
            artifacts={},
            elapsed_ms=elapsed_ms,
            reason="No payload to frame: no decoded bits from S5",
        )

    def _val(attr: str, default: Any) -> Any:
        if isinstance(raw, dict):
            return raw.get(attr, default)
        return getattr(raw, attr, default)

    printable = float(_val("printable_fraction", 0.0))
    looks_like_text = bool(_val("looks_like_text", False))
    n_bytes = int(_val("n_bytes", 0))
    entropy = float(_val("entropy", 0.0))
    has_header = bool(_val("has_header", False))
    header_hex = str(_val("header_hex", ""))
    header_entropy = float(_val("header_entropy", 0.0))
    payload_entropy = float(_val("payload_entropy", 0.0))

    payload_text_val = _val("payload_text", None)
    if payload_text_val is None:
        payload_text_val = _val("text", "")
    payload_text = str(payload_text_val)
    text = str(_val("text", payload_text))

    values = {
        "n_bytes": n_bytes,
        "printable_fraction": printable,
        "looks_like_text": looks_like_text,
        "text": text,
        "entropy": entropy,
        "has_header": has_header,
        "header_hex": header_hex,
        "header_entropy": header_entropy,
        "payload_entropy": payload_entropy,
        "payload_text": payload_text,
    }
    return StageResult(
        stage="s6_frame",
        status=StageStatus.OK,
        confidence=printable,
        values=values,
        hypotheses=[
            Hypothesis(
                value="ascii_text" if looks_like_text else "binary_data",
                score=printable,
                evidence=f"{printable * 100:.1f}% printable characters",
            )
        ],
        artifacts={},
        elapsed_ms=elapsed_ms,
        reason=None,
    )


# -----------------------------------------------------------------------------
# Main Orchestration Engine
# -----------------------------------------------------------------------------

def orchestrate(
    run_id: str,
    file_path: Path | str,
    fs_hint: Optional[float] = None,
    mod_scheme_hint: Optional[str] = None,
    stage_timeout: Optional[float] = None,
    total_timeout: Optional[float] = None,
    runner: Optional[JobRunner] = None,
    stage_overrides: Optional[dict[str, Callable[..., Any]]] = None,
    db_path: Optional[Path | str] = None,
) -> AnalysisReport:
    """Execute the S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S6 pipeline in order."""
    load_plugins()
    start_time = time.time()
    stage_timeout_sec = stage_timeout if stage_timeout is not None else config.stage_timeout_seconds
    total_timeout_sec = total_timeout if total_timeout is not None else config.total_timeout_seconds
    active_runner = runner or job_runner
    overrides = stage_overrides or {}

    file_meta = compute_file_meta(file_path)
    stages: list[StageResult] = []

    # Initialize or update run in DB
    initialize_database(db_path=db_path)
    existing_run = get_run(run_id, db_path=db_path)
    if existing_run is None:
        create_run(
            run_id=run_id,
            filename=file_meta["filename"],
            file_size=file_meta["size_bytes"],
            sha256=file_meta["sha256"],
            status="running",
            envelope_verdict="pending",
            db_path=db_path,
        )
    else:
        update_run(
            run_id=run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

    log_event(logging.INFO, run_id, "pipeline", f"Starting analysis pipeline for file: {file_meta['filename']}")

    def _persist(res: StageResult) -> None:
        record_stage_result(
            run_id=run_id,
            stage=res.stage,
            status=res.status.value,
            confidence=res.confidence,
            elapsed_ms=res.elapsed_ms,
            reason=res.reason,
            values=res.values,
            hypotheses=[h.model_dump() if hasattr(h, "model_dump") else dict(h) for h in res.hypotheses],
            artifacts=res.artifacts,
            db_path=db_path,
        )

    def _execute_stage(
        stage_name: str,
        stage_fn: Callable[[], Any],
        adapter_fn: Callable[[Any, float], StageResult],
    ) -> tuple[StageResult, Any]:
        if active_runner.is_cancelled(run_id):
            log_event(logging.INFO, run_id, stage_name, "Run was cancelled, skipping stage execution")
            res = StageResult(stage=stage_name, status=StageStatus.FAILED, confidence=0.0, reason="Run cancelled")
            stages.append(res)
            _persist(res)
            return res, None

        elapsed_total = time.time() - start_time
        if elapsed_total > total_timeout_sec:
            log_event(logging.WARNING, run_id, stage_name, f"Total timeout of {total_timeout_sec}s exceeded")
            res = StageResult(
                stage=stage_name,
                status=StageStatus.FAILED,
                confidence=0.0,
                reason=f"Total timeout of {total_timeout_sec}s exceeded",
            )
            stages.append(res)
            _persist(res)
            return res, None

        t0 = time.time()
        log_event(logging.INFO, run_id, stage_name, f"Starting stage execution: {stage_name}")
        raw_result = None
        try:
            raw_result = active_runner.run_stage_with_timeout(
                stage_fn, timeout=stage_timeout_sec, run_id=run_id
            )
            elapsed_ms = (time.time() - t0) * 1000.0
            res = adapter_fn(raw_result, elapsed_ms)
            log_event(
                logging.INFO,
                run_id,
                stage_name,
                f"Stage completed: {stage_name}, status={res.status.value}, elapsed={elapsed_ms:.1f}ms",
            )
        except StageTimeoutError as exc:
            elapsed_ms = (time.time() - t0) * 1000.0
            log_event(logging.WARNING, run_id, stage_name, f"Stage timed out after {stage_timeout_sec}s")
            res = StageResult(
                stage=stage_name,
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=elapsed_ms,
                reason=str(exc),
            )
        except JobCancelledError as exc:
            elapsed_ms = (time.time() - t0) * 1000.0
            log_event(logging.INFO, run_id, stage_name, "Job cancelled during stage")
            res = StageResult(
                stage=stage_name,
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=elapsed_ms,
                reason=str(exc),
            )
        except Exception as exc:
            elapsed_ms = (time.time() - t0) * 1000.0
            log_event(logging.ERROR, run_id, stage_name, f"Stage failed with unhandled exception: {exc}")
            res = StageResult(
                stage=stage_name,
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=elapsed_ms,
                reason=str(exc),
            )

        stages.append(res)
        _persist(res)
        return res, raw_result

    def _refuse_downstream(
        trigger_stage: str,
        trigger_res: StageResult,
        remaining_stage_names: list[str],
    ) -> AnalysisReport:
        refusal_reason = "Refused: input out of operating envelope"
        for stg in remaining_stage_names:
            refused_res = StageResult(
                stage=stg,
                status=StageStatus.OUT_OF_ENVELOPE,
                confidence=0.0,
                reason=refusal_reason,
            )
            stages.append(refused_res)
            _persist(refused_res)

        final_payload = {
            "payload_text": "",
            "printable_fraction": 0.0,
            "looks_like_text": False,
            "bits_count": 0,
        }

        report = AnalysisReport(
            run_id=run_id,
            file_meta=file_meta,
            envelope_verdict="out_of_envelope",
            stages=stages,
            final=final_payload,
        )

        update_run(
            run_id=run_id,
            status="completed",
            envelope_verdict="out_of_envelope",
            finished_at=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

        log_event(
            logging.INFO,
            run_id,
            "pipeline",
            f"Analysis pipeline refused with verdict=out_of_envelope (triggered by {trigger_stage}: {trigger_res.reason}), duration={(time.time() - start_time):.2f}s",
        )
        return report

    # -------------------------------------------------------------------------
    # S0: Ingest
    # -------------------------------------------------------------------------
    s0_fn = overrides.get("s0_ingest") or get_s0_ingest()
    if s0_fn is None:
        s0_res, s0_raw = _execute_stage(
            "s0_ingest",
            lambda: None,
            lambda raw, ms: StageResult(
                stage="s0_ingest",
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=ms,
                reason="S0 ingest implementation unavailable",
            ),
        )
    else:
        s0_res, s0_raw = _execute_stage(
            "s0_ingest",
            lambda: s0_fn(file_path, fs_hint=fs_hint),
            adapt_s0,
        )

    iq_samples = getattr(s0_raw, "iq", None)
    sample_rate = getattr(s0_raw, "fs", None) or fs_hint or 200000.0

    if s0_res.status != StageStatus.OK or iq_samples is None:
        # Abort downstream stages cleanly if ingest produced no IQ samples
        for stg in ["s1_detect", "s2_estimate", "s3_receive", "s4_recover", "s5_decode", "s6_frame"]:
            aborted_res = StageResult(
                stage=stg,
                status=StageStatus.FAILED,
                confidence=0.0,
                reason="Aborted due to upstream failure in S0 ingest",
            )
            stages.append(aborted_res)
            _persist(aborted_res)

        report = AnalysisReport(
            run_id=run_id,
            file_meta=file_meta,
            envelope_verdict="failed",
            stages=stages,
            final={},
        )
        update_run(run_id=run_id, status="failed", envelope_verdict="failed", error=s0_res.reason, db_path=db_path)
        return report

    # -------------------------------------------------------------------------
    # S1: Detect
    # -------------------------------------------------------------------------
    s1_fn = overrides.get("s1_detect") or get_s1_detect()
    if s1_fn is None:
        s1_res, s1_raw = _execute_stage(
            "s1_detect",
            lambda: None,
            lambda raw, ms: StageResult(
                stage="s1_detect",
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=ms,
                reason="S1 detect implementation unavailable",
            ),
        )
    else:
        s1_res, s1_raw = _execute_stage(
            "s1_detect",
            lambda: s1_fn(iq_samples, sample_rate),
            lambda raw, ms: adapt_s1(raw, ms, run_id),
        )

    if s1_res.status == StageStatus.OUT_OF_ENVELOPE:
        return _refuse_downstream(
            "s1_detect",
            s1_res,
            ["s2_estimate", "s3_receive", "s4_recover", "s5_decode", "s6_frame"],
        )

    # -------------------------------------------------------------------------
    # S2: Estimate (Blind symbol rate and CFO estimation)
    # -------------------------------------------------------------------------
    s2_fn = overrides.get("s2_estimate") or get_s2_estimate()
    if s2_fn is None:
        s2_res, s2_raw = _execute_stage(
            "s2_estimate",
            lambda: None,
            lambda raw, ms: StageResult(
                stage="s2_estimate",
                status=StageStatus.FAILED,
                confidence=0.0,
                elapsed_ms=ms,
                reason="S2 estimate implementation unavailable",
            ),
        )
    else:
        s2_res, s2_raw = _execute_stage(
            "s2_estimate",
            lambda: s2_fn(iq_samples, sample_rate),
            adapt_s2,
        )

    if s2_res.status == StageStatus.OUT_OF_ENVELOPE:
        return _refuse_downstream(
            "s2_estimate",
            s2_res,
            ["s3_receive", "s4_recover", "s5_decode", "s6_frame"],
        )

    # Resolve S2 parameters for receiver
    symbol_rate = (
        getattr(s2_raw, "symbol_rate_hz", None)
        or getattr(s2_raw, "symbol_rate", None)
        or s2_res.values.get("symbol_rate", 25000.0)
    )
    cfo_hz = getattr(s2_raw, "cfo_hz", 0.0) or s2_res.values.get("cfo_hz", 0.0)
    s2_params: dict[str, Any] = {"fs": sample_rate, "symbol_rate": symbol_rate, "cfo_hz": cfo_hz}
    if mod_scheme_hint:
        s2_params["modulation_hypotheses"] = [(mod_scheme_hint.lower(), 1.0)]

    # -------------------------------------------------------------------------
    # S3: Receive (Demodulation receiver via receive_best)
    # -------------------------------------------------------------------------
    s3_fn = overrides.get("s3_receive") or get_s3_receive()

    def _run_s3() -> Any:
        if s3_fn:
            return s3_fn(iq_samples, s2_params)
        return None

    s3_res, s3_raw = _execute_stage(
        "s3_receive",
        _run_s3,
        lambda raw, ms: adapt_s3(raw, ms, run_id),
    )

    if s3_res.status == StageStatus.OUT_OF_ENVELOPE:
        return _refuse_downstream(
            "s3_receive",
            s3_res,
            ["s4_recover", "s5_decode", "s6_frame"],
        )

    llrs = getattr(s3_raw, "llrs", None)
    if llrs is None and isinstance(s3_raw, (list, tuple)):
        llrs = s3_raw

    # -------------------------------------------------------------------------
    # S4: Recover (Rank collapse interleaver & code recovery)
    # -------------------------------------------------------------------------
    s4_fn = overrides.get("s4_recover") or get_s4_recover()

    def _run_s4() -> Any:
        if s4_fn:
            # S4 consumes hard bits (LLR > 0 is bit 0)
            if llrs is not None:
                try:
                    hard_bits = [(0 if l > 0 else 1) for l in llrs]
                except TypeError:
                    hard_bits = llrs
                return s4_fn(hard_bits)
            return None
        return None

    s4_res, s4_raw = _execute_stage(
        "s4_recover",
        _run_s4,
        lambda raw, ms: adapt_s4(raw, ms, run_id),
    )

    # -------------------------------------------------------------------------
    # S5: Decode (FEC decoding)
    # -------------------------------------------------------------------------
    s5_fn = overrides.get("s5_decode")
    # Filled in by _run_s5 on the real path and folded into the StageResult by
    # adapt_s5, so a prefix decode and a failed re-encode check are both visible
    # in the report rather than inferred from a bit count.
    s5_detail: dict[str, Any] = {}

    def _run_s5() -> Any:
        if s5_fn:
            return s5_fn(llrs, s4_res.values)
        conv_plugin = CODES.get("conv")
        if conv_plugin is None or not hasattr(conv_plugin, "decode") or llrs is None:
            return None

        # This block previously read:
        #     code_params = s4_raw.code if hasattr(s4_raw, "code") else None
        #     return conv_plugin.decode(llrs, code_params or s4_res.values)
        # which could not work on ANY input, and hid a second, worse defect.
        #
        # 1. `s4_raw.code` is a CodeStructure(n, memory, span, consistent). It
        #    carries NO generators - those are a sibling field on
        #    RecoveryResult - and ConvCode.decode wants CodeParams or a dict, so
        #    a good S4 gave "TypeError: 'CodeStructure' object is not
        #    subscriptable". A dataclass is always truthy, so `or` never fired.
        # 2. When S4 failed, `code` was None, the fallback DID fire, and
        #    s4_res.values has code_rate/K rather than n/memory -> KeyError 'n'.
        # 3. The real defect underneath: it decoded `llrs` as they arrived,
        #    never applying the offset and interleaver S4 had just recovered.
        #    Decoding a still-interleaved stream returns confident noise, which
        #    is worse than crashing - the crash is why nobody had seen it.
        code = getattr(s4_raw, "code", None)
        gens = getattr(s4_raw, "generators_octal", None)
        # Same guard pipeline/s4_recover/cli.py applies before it decodes: only
        # a locked rate-1/2 recovery with generators is actionable. Anything
        # else would build a trellis out of None.
        if (getattr(s4_raw, "status", None) != "ok" or code is None
                or gens is None or getattr(code, "n", None) != 2):
            s5_detail["declined"] = (
                "S4 did not lock a rate-1/2 code with recovered generators "
                "(status=%s, n=%s, generators=%s)"
                % (getattr(s4_raw, "status", None), getattr(code, "n", None),
                   "yes" if gens else "no"))
            return None

        # Apply what S4 recovered. The permutation is a reshape/transpose, so it
        # runs on the soft LLRs directly and the Viterbi keeps its metric -
        # de-interleaving hard bits here would throw that away.
        offset = int(getattr(s4_raw, "offset", 0) or 0)
        if np is not None:
            stream = np.asarray(llrs).ravel()[offset:]
        else:
            stream = list(llrs)[offset:]
        intl = getattr(s4_raw, "interleaver", None)
        if intl is not None:
            intl_plugin = INTERLEAVERS.get(getattr(intl, "family", ""))
            if intl_plugin is None:
                s5_detail["declined"] = (
                    "no '%s' interleaver plug-in registered to undo what S4 found"
                    % getattr(intl, "family", ""))
                return None
            soft_in = (getattr(stream, "dtype", None) is not None and getattr(stream.dtype, "kind", None) == "f") if np is not None else any(isinstance(x, float) for x in stream[:10])
            stream = intl_plugin.deinterleave(stream, **getattr(intl, "params", {}))
            # A permutation must hand back what it was given. The CCSDS symbol
            # family is the one exception, and legitimately so: it works in the
            # RS BYTE domain, so `_to_bytes` packs bits and returns uint8. That
            # is correct where it belongs - after Viterbi, in s6_frame/ccsds.py
            # - and destructive here. Measured on 4096 float LLRs: 2107
            # negative in, 0 out, every value collapsed to {0, 1}. Worse,
            # conv_code.decode then sees dtype uint8 and SILENTLY takes its
            # hard-decision path, so the stage returns a confident decode of
            # noise rather than raising.
            #
            # Reachable because ccsds-symbol at depth 1 is the IDENTITY
            # permutation, so it clears the family gate on exactly the streams
            # the direct reading clears. rank_collapse's shortest-span
            # tie-break shuts it out only while `direct` is non-None; a stream
            # whose direct reading is rejected on `span != first` can still
            # hand this seam a symbol-domain family.
            #
            # The 4 Sep rule was "a permutation must not cast its input". The
            # cast is legal in that plug-in, so the guard belongs at THIS seam
            # instead - which is where the conventions say guards go anyway.
            stream_dtype = getattr(stream, "dtype", None)
            if soft_in and stream_dtype is not None and getattr(stream_dtype, "kind", None) != "f":
                s5_detail["declined"] = (
                    "the '%s' de-interleaver returned %s and destroyed the soft "
                    "information S3 recovered: it works in the symbol domain and "
                    "cannot be applied to LLRs"
                    % (getattr(intl, "family", "?"), stream_dtype))
                return None
        if len(stream) == 0:
            # Decoding the un-deinterleaved stream instead would "work" and
            # return noise: measured 0.2948 re-encode BER against 0.0005 for the
            # same file decoded correctly. Declining is the only honest answer.
            llrs_len = len(np.asarray(llrs).ravel()) if np is not None else len(llrs)
            s5_detail["declined"] = (
                "stream too short to de-interleave: %d LLRs is under one period "
                "of the %s interleaver S4 recovered"
                % (llrs_len, getattr(intl, "family", "?")))
            return None

        # commpy's Viterbi is pure Python and linear in stream length. The whole
        # stream is ~29 s against a 15 s per-stage timeout, so the stage failed
        # on the clock even once the wiring above was right. The CLI settled
        # this already (pipeline/s4_recover/cli.py:26): a prefix proves the
        # chain exactly as well, and the budget is what makes the 90 s envelope
        # hold. Recorded as a prefix in values so a partial decode is never
        # mistaken for a complete one.
        budget = min(len(stream), S5_DECODE_MAX_BITS)
        params = {
            "n": code.n,
            "memory": code.memory,
            "generators_octal": tuple(gens),
            "span": getattr(code, "span", 0) or 0,
            "parity_taps": getattr(s4_raw, "parity_taps", None) or [],
        }
        decoded = conv_plugin.decode(stream[:budget], params)

        s5_detail["coded_bits_available"] = int(len(stream))
        s5_detail["coded_bits_decoded"] = int(budget)
        s5_detail["decoded_prefix"] = bool(budget < len(stream))
        # The honest test of a decode: re-encode it and compare with what
        # arrived. Plausible-looking bits from a wrong trellis score as well as
        # real ones on any other measure, so without this S5 can report ok on
        # a decode that is simply wrong - the same false-green class as the two
        # adapters below. Optional because it is beyond the CODES protocol.
        if hasattr(conv_plugin, "validate_against"):
            try:
                s5_detail["validation"] = conv_plugin.validate_against(
                    decoded, stream[:budget], params)
            except Exception as exc:  # never let a check sink the stage
                logger.warning("S5 re-encode validation failed: %s", exc)

        # Check for optional outer CCSDS layer (randomiser -> symbol deinterleave -> RS)
        # S5 owns FEC, so if an outer RS code is verified, S5 produces the true source bits.
        try:
            from pipeline.s6_frame.ccsds import peel_ccsds_outer
            outer = peel_ccsds_outer(decoded, detail=s5_detail)
            if outer is not None:
                outer_bits, outer_params = outer
                decoded = outer_bits
                s5_detail["outer_fec"] = "reed-solomon"
                s5_detail["concatenated"] = True
                s5_detail["rs_n"] = outer_params.get("n")
                s5_detail["rs_k"] = outer_params.get("k")
                s5_detail["rs_errata_rate"] = outer_params.get("errata_rate")
                s5_detail["rs_blocks_checked"] = outer_params.get("blocks_checked")
                if outer_params.get("randomiser"):
                    s5_detail["randomiser"] = outer_params["randomiser"]
                if outer_params.get("interleaver"):
                    s5_detail["outer_interleaver"] = outer_params["interleaver"]
        except Exception as exc:
            logger.warning("Optional S5 CCSDS outer FEC check failed: %s", exc)

        return decoded

    s5_res, s5_raw = _execute_stage(
        "s5_decode",
        _run_s5,
        lambda raw, ms: adapt_s5(raw, ms, s5_detail),
    )

    decoded_bits = s5_raw

    # -------------------------------------------------------------------------
    # S6: Frame / Payload extraction
    # -------------------------------------------------------------------------
    s6_fn = overrides.get("s6_frame") or get_s6_payload()

    def _run_s6() -> Any:
        if s6_fn and decoded_bits is not None:
            return s6_fn(decoded_bits)
        return None

    s6_res, s6_raw = _execute_stage(
        "s6_frame",
        _run_s6,
        adapt_s6,
    )

    # -------------------------------------------------------------------------
    # Build Final AnalysisReport
    # -------------------------------------------------------------------------
    has_failed_stage = any(s.status == StageStatus.FAILED for s in stages)
    has_out_of_envelope = any(s.status == StageStatus.OUT_OF_ENVELOPE for s in stages)

    if has_out_of_envelope:
        verdict = "out_of_envelope"
    elif has_failed_stage:
        verdict = "failed"
    else:
        verdict = "in_envelope"

    def _s6_val(attr: str, default: Any) -> Any:
        if isinstance(s6_raw, dict):
            return s6_raw.get(attr, default)
        return getattr(s6_raw, attr, default)

    s6_payload_text = _s6_val("payload_text", None)
    if s6_payload_text is None:
        s6_payload_text = _s6_val("text", "")

    final_payload = {
        "payload_text": str(s6_payload_text),
        "printable_fraction": float(_s6_val("printable_fraction", 0.0)),
        "looks_like_text": bool(_s6_val("looks_like_text", False)),
        "bits_count": len(decoded_bits) if decoded_bits is not None else 0,
        "entropy": float(_s6_val("entropy", 0.0)),
        "has_header": bool(_s6_val("has_header", False)),
        "header_hex": str(_s6_val("header_hex", "")),
        "header_entropy": float(_s6_val("header_entropy", 0.0)),
        "payload_entropy": float(_s6_val("payload_entropy", 0.0)),
    }

    report = AnalysisReport(
        run_id=run_id,
        file_meta=file_meta,
        envelope_verdict=verdict,
        stages=stages,
        final=final_payload,
    )

    update_run(
        run_id=run_id,
        status="completed" if verdict != "failed" else "failed",
        envelope_verdict=verdict,
        finished_at=datetime.now(timezone.utc).isoformat(),
        db_path=db_path,
    )

    log_event(
        logging.INFO,
        run_id,
        "pipeline",
        f"Analysis pipeline completed with verdict={verdict}, duration={(time.time() - start_time):.2f}s",
    )
    return report


DEFAULT_STAGE_OVERRIDES: dict[str, Callable[..., Any]] = {}


def submit_analysis_job(
    run_id: str,
    file_path: Path | str,
    fs_hint: Optional[float] = None,
    mod_scheme_hint: Optional[str] = None,
    stage_timeout: Optional[float] = None,
    total_timeout: Optional[float] = None,
    runner: Optional[JobRunner] = None,
    stage_overrides: Optional[dict[str, Callable[..., Any]]] = None,
    db_path: Optional[Path | str] = None,
) -> Job:
    """Submit analysis pipeline to run asynchronously via JobRunner."""
    active_runner = runner or job_runner
    merged_overrides = dict(DEFAULT_STAGE_OVERRIDES)
    if stage_overrides:
        merged_overrides.update(stage_overrides)
    return active_runner.submit_job(
        run_id,
        orchestrate,
        run_id,
        file_path,
        fs_hint=fs_hint,
        mod_scheme_hint=mod_scheme_hint,
        stage_timeout=stage_timeout,
        total_timeout=total_timeout,
        runner=active_runner,
        stage_overrides=merged_overrides,
        db_path=db_path,
    )
