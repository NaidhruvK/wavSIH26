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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus
from registry import CODES, MODULATIONS

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
# Dynamic / Fallback Pipeline Resolvers
# -----------------------------------------------------------------------------

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
    # Primary: check pipeline/s2_estimate.py
    try:
        from pipeline import s2_estimate
        if hasattr(s2_estimate, "estimate_blind"):
            return s2_estimate.estimate_blind
        if hasattr(s2_estimate, "estimate"):
            return s2_estimate.estimate
    except (ImportError, AttributeError):
        pass

    # Fallback: check tests/fixtures/local_s2.py
    try:
        from tests.fixtures import local_s2
        if hasattr(local_s2, "estimate_blind"):
            return local_s2.estimate_blind
    except (ImportError, AttributeError):
        pass

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

    status = StageStatus.OK if getattr(raw, "status", None) == "ok" else StageStatus.FAILED
    bursts = getattr(raw, "bursts", [])
    values = {
        "snr_db": getattr(raw, "snr_db", None),
        "noise_floor_db": getattr(raw, "noise_floor_db", None),
        "occupied_bw_hz": getattr(raw, "occupied_bw_hz", None),
        "burst_count": len(bursts) if bursts is not None else 0,
        "fs": getattr(raw, "fs", None),
    }

    artifacts = {}
    psd_db = getattr(raw, "psd_db", None)
    psd_freqs = getattr(raw, "psd_freqs", None)
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
        confidence=0.98 if status == StageStatus.OK else 0.0,
        values=values,
        hypotheses=[
            Hypothesis(
                value="bursty" if values["burst_count"] > 0 else "continuous",
                score=0.95,
                evidence=f"{values['burst_count']} bursts detected",
            )
        ],
        artifacts=artifacts,
        elapsed_ms=elapsed_ms,
        reason=getattr(raw, "reason", None),
    )


def adapt_s2(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    rate = getattr(raw, "symbol_rate", 0.0)
    fs = getattr(raw, "fs", 1.0)
    values = {
        "symbol_rate": rate,
        "sps": (fs / rate) if rate > 0 else 0.0,
        "cfo_hz": getattr(raw, "cfo_hz", 0.0),
        "order_hint": getattr(raw, "order_hint", 0),
        "symbol_rate_score": getattr(raw, "symbol_rate_score", 0.0),
    }

    status = StageStatus.OK if rate > 0 else StageStatus.LOW_CONFIDENCE
    confidence = min(1.0, max(0.1, values["symbol_rate_score"] / 10.0)) if values["symbol_rate_score"] else 0.9

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
        reason=None,
    )


def adapt_s3(raw: Any, elapsed_ms: float, run_id: str) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

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

        return StageResult(
            stage="s3_receive",
            status=StageStatus(base_dict.get("status", "ok")),
            confidence=float(base_dict.get("confidence", 0.95)),
            values=base_dict.get("values", {}),
            hypotheses=[
                Hypothesis(value=h["value"], score=h["score"], evidence=h.get("evidence", ""))
                for h in base_dict.get("hypotheses", [])
            ],
            artifacts=artifacts,
            elapsed_ms=elapsed_ms,
            reason=base_dict.get("reason"),
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


def adapt_s5(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    bit_count = len(raw) if raw is not None else 0
    status = StageStatus.OK if bit_count > 0 else StageStatus.FAILED
    return StageResult(
        stage="s5_decode",
        status=status,
        confidence=1.0 if status == StageStatus.OK else 0.0,
        values={"decoded_bits_count": bit_count},
        hypotheses=[Hypothesis(value="viterbi_decoded", score=1.0, evidence="trellis traceback complete")],
        artifacts={},
        elapsed_ms=elapsed_ms,
        reason=None if status == StageStatus.OK else "No bits decoded",
    )


def adapt_s6(raw: Any, elapsed_ms: float) -> StageResult:
    if isinstance(raw, StageResult):
        raw.elapsed_ms = elapsed_ms
        return raw

    printable = float(getattr(raw, "printable_fraction", 0.0))
    looks_like_text = bool(getattr(raw, "looks_like_text", False))
    return StageResult(
        stage="s6_frame",
        status=StageStatus.OK,
        confidence=printable,
        values={
            "n_bytes": getattr(raw, "n_bytes", 0),
            "printable_fraction": printable,
            "looks_like_text": looks_like_text,
        },
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

    # -------------------------------------------------------------------------
    # S2: Estimate (Supports local_s2 fixture fallback)
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

    # Resolve S2 parameters for receiver
    symbol_rate = getattr(s2_raw, "symbol_rate", 0.0) or s2_res.values.get("symbol_rate", 25000.0)
    cfo_hz = getattr(s2_raw, "cfo_hz", 0.0) or s2_res.values.get("cfo_hz", 0.0)
    s2_params = {"fs": sample_rate, "symbol_rate": symbol_rate, "cfo_hz": cfo_hz}

    # Thread hypotheses: determine modulation scheme
    chosen_scheme = mod_scheme_hint
    if not chosen_scheme and s2_res.hypotheses:
        chosen_scheme = str(s2_res.hypotheses[0].value).lower()
    if not chosen_scheme:
        chosen_scheme = "qpsk"

    # -------------------------------------------------------------------------
    # S3: Receive (Modulation demodulator)
    # -------------------------------------------------------------------------
    s3_fn = overrides.get("s3_receive")

    def _run_s3() -> Any:
        if s3_fn:
            return s3_fn(iq_samples, s2_params)
        plugin = MODULATIONS.get(chosen_scheme)
        if plugin:
            if hasattr(plugin, "receive"):
                return plugin.receive(iq_samples, s2_params)
            if hasattr(plugin, "demodulate"):
                return plugin.demodulate(iq_samples, s2_params)
        return None

    s3_res, s3_raw = _execute_stage(
        "s3_receive",
        _run_s3,
        lambda raw, ms: adapt_s3(raw, ms, run_id),
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

    def _run_s5() -> Any:
        if s5_fn:
            return s5_fn(llrs, s4_res.values)
        conv_plugin = CODES.get("conv")
        if conv_plugin and hasattr(conv_plugin, "decode") and llrs is not None:
            # Recovered generators
            code_params = s4_raw.code if hasattr(s4_raw, "code") else None
            return conv_plugin.decode(llrs, code_params or s4_res.values)
        return None

    s5_res, s5_raw = _execute_stage(
        "s5_decode",
        _run_s5,
        adapt_s5,
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

    final_payload = {
        "payload_text": getattr(s6_raw, "text", ""),
        "printable_fraction": getattr(s6_raw, "printable_fraction", 0.0),
        "looks_like_text": getattr(s6_raw, "looks_like_text", False),
        "bits_count": len(decoded_bits) if decoded_bits is not None else 0,
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
        stage_overrides=stage_overrides,
        db_path=db_path,
    )
