"""FastAPI REST API Service for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides REST endpoints for audio/IQ upload, asynchronous pipeline execution,
run status inspection, stage metrics retrieval, artifact delivery, and operating envelope metadata.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import json
import logging
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from contracts import AnalysisReport, StageResult, StageStatus
from registry import describe as describe_registry

from .config import config
from .db import (
    get_all_stage_results,
    get_run,
    get_stage_result,
    initialize_database,
)
from .job_runner import job_runner
from .orchestrator import submit_analysis_job

logger = logging.getLogger("raaya.api")

ALLOWED_EXTENSIONS = {".wav", ".iq", ".bin", ".raw", ".sigmf-data", ".dat"}

STAGE_MAP = {
    0: "s0_ingest", "0": "s0_ingest", "s0": "s0_ingest", "s0_ingest": "s0_ingest",
    1: "s1_detect", "1": "s1_detect", "s1": "s1_detect", "s1_detect": "s1_detect",
    2: "s2_estimate", "2": "s2_estimate", "s2": "s2_estimate", "s2_estimate": "s2_estimate",
    3: "s3_receive", "3": "s3_receive", "s3": "s3_receive", "s3_receive": "s3_receive",
    4: "s4_recover", "4": "s4_recover", "s4": "s4_recover", "s4_recover": "s4_recover",
    5: "s5_decode", "5": "s5_decode", "s5": "s5_decode", "s5_decode": "s5_decode",
    6: "s6_frame", "6": "s6_frame", "s6": "s6_frame", "s6_frame": "s6_frame",
}


# =============================================================================
# FastAPI Imports & Lightweight Fallback Definitions
# =============================================================================

try:
    from fastapi import FastAPI as RealFastAPI, File, Form, HTTPException as RealHTTPException, UploadFile as RealUploadFile, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse as RealFileResponse, JSONResponse as RealJSONResponse
    try:
        from fastapi.testclient import TestClient as RealTestClient
    except ImportError:
        RealTestClient = None
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    RealTestClient = None


class FallbackHTTPException(Exception):
    def __init__(self, status_code: int, detail: Any = None):
        self.status_code = status_code
        self.detail = detail or ""
        super().__init__(str(detail))


class FallbackResponse:
    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        media_type: str = "application/json",
        headers: Optional[dict[str, str]] = None,
    ):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self.content, (dict, list)):
            return self.content
        if isinstance(self.content, (str, bytes)):
            return json.loads(self.content)
        return self.content

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, bytes):
            return self.content.decode("utf-8")
        return json.dumps(self.content)


class FallbackJSONResponse(FallbackResponse):
    def __init__(self, content: Any, status_code: int = 200, headers: Optional[dict[str, str]] = None):
        super().__init__(content=content, status_code=status_code, media_type="application/json", headers=headers)


class FallbackFileResponse(FallbackResponse):
    def __init__(self, path: str, media_type: str = "application/octet-stream", status_code: int = 200, headers: Optional[dict[str, str]] = None):
        super().__init__(status_code=status_code, media_type=media_type, headers=headers)
        self.path = path
        with open(path, "rb") as f:
            self.content = f.read()

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class FallbackUploadFile:
    def __init__(self, filename: str, file: Optional[Any] = None, content_type: str = "application/octet-stream"):
        self.filename = filename
        self.file = file if file is not None else io.BytesIO()
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    async def seek(self, offset: int) -> None:
        self.file.seek(offset)


class FallbackApp:
    """Lightweight application router providing identical route decorators and dispatch."""
    def __init__(self, title: str = "Raaya", version: str = "1.0.0", **kwargs: Any):
        self.title = title
        self.version = version
        self.routes: list[tuple[str, str, Callable[..., Any], int]] = []
        self.middlewares: list[Any] = []

    def add_middleware(self, middleware_cls: Any, **options: Any) -> None:
        self.middlewares.append((middleware_cls, options))

    def get(self, path: str, status_code: int = 200, **kwargs: Any) -> Callable[..., Any]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(("GET", path, fn, status_code))
            return fn
        return decorator

    def post(self, path: str, status_code: int = 200, **kwargs: Any) -> Callable[..., Any]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(("POST", path, fn, status_code))
            return fn
        return decorator


# Select implementation
if HAS_FASTAPI:
    FastAPI = RealFastAPI
    HTTPException = RealHTTPException
    JSONResponse = RealJSONResponse
    FileResponse = RealFileResponse
    UploadFile = RealUploadFile
else:
    FastAPI = FallbackApp  # type: ignore[misc]
    HTTPException = FallbackHTTPException  # type: ignore[misc]
    JSONResponse = FallbackJSONResponse  # type: ignore[misc]
    FileResponse = FallbackFileResponse  # type: ignore[misc]
    UploadFile = FallbackUploadFile  # type: ignore[misc]


# =============================================================================
# Application Setup & CORS Configuration
# =============================================================================

app = FastAPI(
    title="Raaya / wavSIH26 Signal Intelligence Service",
    description="Automated blind RF signal demodulation and telemetry recovery pipeline.",
    version="1.0.0",
)

if HAS_FASTAPI:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        None,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# =============================================================================
# Helper Functions
# =============================================================================

def get_envelope_metadata() -> dict[str, Any]:
    """Expose the declared operating envelope specifications."""
    return {
        "system": "Raaya / wavSIH26",
        "version": "1.0.0",
        "verdict_types": ["in_envelope", "out_of_envelope", "low_confidence", "failed"],
        "timeouts": {
            "stage_timeout_seconds": config.stage_timeout_seconds,
            "total_timeout_seconds": config.total_timeout_seconds,
        },
        "limits": {
            "max_upload_size_bytes": config.max_upload_size_bytes,
            "max_workers": config.max_workers,
        },
        "stages": {
            "s0_ingest": {
                "supported_formats": sorted(list(ALLOWED_EXTENSIONS)),
                "sample_rate_range_hz": [8000.0, 20000000.0],
                "description": "RIFF WAV parse, 2-channel IQ sniffer, format hypotheses",
            },
            "s1_detect": {
                "min_snr_db": -5.0,
                "occupied_bandwidth_min_hz": 1000.0,
                "outputs": ["snr_db", "noise_floor_db", "occupied_bw_hz", "bursts", "psd_plot"],
            },
            "s2_estimate": {
                "sps_range": [2.5, 40.0],
                "cfo_range_hz": [-50000.0, 50000.0],
                "supported_modulations": ["bpsk", "qpsk", "8psk", "16qam", "2fsk", "4fsk"],
                "cyclostationary_estimation": True,
            },
            "s3_receive": {
                "timing_convergence_max_symbols": 2000,
                "zero_error_snr_threshold_db": 8.0,
                "lock_rate_target": 0.90,
                "outputs": ["modulation", "evm_percent", "lock_metric", "llrs", "constellation_plot"],
            },
            "s4_recover": {
                "interleaver_families": ["block", "convolutional", "helical"],
                "ber_ceiling_independent": 0.003,
                "ber_ceiling_burst": 0.05,
                "method": "GF(2) rank collapse",
                "outputs": ["period", "offset", "generators_octal", "rank_profile_plot"],
            },
            "s5_decode": {
                "code_families": ["convolutional", "reed_solomon"],
                "standard_rates": ["1/2", "1/3"],
                "standard_generators": [0o171, 0o133],
                "decision": "soft_viterbi",
                "outputs": ["decoded_bits_count", "inferred_ber"],
            },
            "s6_frame": {
                "printable_fraction_min": 0.80,
                "supported_encodings": ["ascii", "utf-8"],
                "outputs": ["n_bytes", "printable_fraction", "payload_text", "looks_like_text"],
            },
        },
    }


def is_safe_artifact_path(base_dir: Path, target_path: Path) -> bool:
    """Verify target_path is strictly within base_dir to eliminate directory traversal."""
    try:
        return target_path.resolve().is_relative_to(base_dir.resolve())
    except AttributeError:
        # Compatibility fallback for Python < 3.9
        base = str(base_dir.resolve())
        target = str(target_path.resolve())
        return target.startswith(base)


# =============================================================================
# REST Endpoints
# =============================================================================

@app.get("/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint returning service liveness status."""
    return {
        "status": "healthy",
        "service": "raaya",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/registry")
def get_registry() -> dict[str, Any]:
    """Return plugin registry introspection summary and registered component list."""
    return describe_registry()


@app.get("/envelope")
def get_envelope() -> dict[str, Any]:
    """Expose the declared operating envelope specifications and bounds."""
    return get_envelope_metadata()


@app.post("/analyze", status_code=202)
async def analyze_file(
    file: UploadFile = (File(...) if HAS_FASTAPI else None),  # type: ignore[assignment]
    fs_hint: Optional[float] = (Form(None) if HAS_FASTAPI else None),
    mod_scheme_hint: Optional[str] = (Form(None) if HAS_FASTAPI else None),
) -> dict[str, Any]:
    """Accept an uploaded .wav or .iq file, store in quarantine, and launch background pipeline."""
    if not file or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="No file provided")

    raw_filename = file.filename
    clean_filename = os.path.basename(raw_filename)
    suffix = Path(clean_filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix}'. Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    config.ensure_directories()
    initialize_database()

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    safe_disk_filename = f"{run_id}_{clean_filename}"
    upload_path = config.upload_dir / safe_disk_filename

    total_bytes = 0
    chunk_size = 65536
    try:
        with open(upload_path, "wb") as dest:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > config.max_upload_size_bytes:
                    dest.close()
                    if upload_path.exists():
                        upload_path.unlink()
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed upload size of {config.max_upload_size_bytes} bytes",
                    )
                dest.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        if upload_path.exists():
            upload_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to store upload file: {exc}")

    if total_bytes == 0:
        if upload_path.exists():
            upload_path.unlink()
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Launch asynchronous analysis pipeline
    submit_analysis_job(
        run_id=run_id,
        file_path=upload_path,
        fs_hint=float(fs_hint) if fs_hint is not None else None,
        mod_scheme_hint=str(mod_scheme_hint) if mod_scheme_hint is not None else None,
    )

    return {
        "run_id": run_id,
        "status": "queued",
        "message": "Analysis submitted successfully",
        "filename": clean_filename,
        "size_bytes": total_bytes,
    }


@app.get("/runs/{run_id}")
def get_run_report(run_id: str) -> dict[str, Any]:
    """Retrieve complete AnalysisReport for a given run."""
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="Invalid run_id parameter")

    # 1. If active background job has completed, return its result directly
    job = job_runner.get_job(run_id)
    if job and job.status == "completed" and job.result is not None:
        if hasattr(job.result, "model_dump"):
            return job.result.model_dump()
        return dict(job.result)

    # 2. Check SQLite database
    run_record = get_run(run_id)
    if run_record is None and job is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    # 3. Assemble report from database records
    raw_stages = get_all_stage_results(run_id)
    file_meta = {
        "filename": run_record.get("filename", "") if run_record else "",
        "size_bytes": run_record.get("file_size", 0) if run_record else 0,
        "sha256": run_record.get("sha256", "") if run_record else "",
    }

    stages_data = []
    for s in raw_stages:
        stages_data.append({
            "stage": s["stage"],
            "status": s["status"],
            "confidence": s["confidence"],
            "elapsed_ms": s.get("elapsed_ms", 0.0),
            "reason": s.get("reason"),
            "values": s.get("values", {}),
            "hypotheses": s.get("hypotheses", []),
            "artifacts": s.get("artifacts", {}),
        })

    s6_stage = next((s for s in raw_stages if s["stage"] == "s6_frame"), None)
    final = {}
    if s6_stage and "values" in s6_stage:
        v = s6_stage["values"]
        final = {
            "payload_text": v.get("text", v.get("payload_text", "")),
            "printable_fraction": v.get("printable_fraction", 0.0),
            "looks_like_text": v.get("looks_like_text", False),
            "bits_count": v.get("n_bytes", 0) * 8,
        }

    status_val = job.status if job else (run_record.get("status", "completed") if run_record else "unknown")
    verdict_val = run_record.get("envelope_verdict", "pending") if run_record else "pending"

    return {
        "run_id": run_id,
        "status": status_val,
        "file_meta": file_meta,
        "envelope_verdict": verdict_val,
        "stages": stages_data,
        "final": final,
    }


@app.get("/runs/{run_id}/stage/{stage_num}")
def get_stage_result_endpoint(run_id: str, stage_num: str) -> dict[str, Any]:
    """Retrieve single stage execution result for a given run."""
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="Invalid run_id parameter")

    # Validate stage identifier
    stage_key = stage_num.lower().strip()
    if stage_key in STAGE_MAP:
        stage_name = STAGE_MAP[stage_key]
    else:
        try:
            int_key = int(stage_key)
            stage_name = STAGE_MAP.get(int_key)
        except ValueError:
            stage_name = None

    if not stage_name:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage identifier '{stage_num}'. Must be 0-6 or stage name (e.g. s0_ingest..s6_frame)",
        )

    # Check if run exists
    run = get_run(run_id)
    job = job_runner.get_job(run_id)
    if run is None and job is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    res = get_stage_result(run_id, stage_name)
    if res is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stage '{stage_name}' has not completed or does not exist for run '{run_id}'",
        )
    return res


@app.get("/runs/{run_id}/artifacts/{artifact_name}")
def get_artifact(run_id: str, artifact_name: str) -> Any:
    """Safely deliver a stored plot or matrix artifact file while preventing path traversal."""
    decoded_art = urllib.parse.unquote(artifact_name)
    decoded_run = urllib.parse.unquote(run_id)

    # Directory traversal prevention
    if (
        not decoded_run
        or "/" in decoded_run
        or "\\" in decoded_run
        or ".." in decoded_run
    ):
        raise HTTPException(status_code=400, detail="Invalid run_id parameter")

    if (
        not decoded_art
        or "/" in decoded_art
        or "\\" in decoded_art
        or ".." in decoded_art
    ):
        raise HTTPException(status_code=400, detail="Invalid artifact_name parameter")

    run_dir = config.artifact_dir / decoded_run
    candidates = [
        run_dir / f"{decoded_art}.json",
        run_dir / decoded_art,
    ]

    target_path = None
    for cand in candidates:
        if not is_safe_artifact_path(config.artifact_dir, cand):
            raise HTTPException(status_code=403, detail="Forbidden: path traversal detected")
        if cand.is_file():
            target_path = cand
            break

    if target_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{decoded_art}' not found for run '{decoded_run}'",
        )

    if target_path.suffix == ".json":
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return JSONResponse(content=data)
        except Exception:
            return FileResponse(path=str(target_path), media_type="application/json")

    return FileResponse(path=str(target_path))


# =============================================================================
# Universal Test Client
# =============================================================================

class FallbackTestClient:
    """Zero-dependency HTTP test client for testing the REST API in environments without FastAPI/httpx."""
    def __init__(self, target_app: Any):
        self.app = target_app

    def _match_route(self, method: str, url: str) -> tuple[Optional[Callable[..., Any]], dict[str, str], int]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        for r_method, r_pattern, fn, default_status in self.app.routes:
            if r_method != method:
                continue
            # Convert /runs/{run_id}/stage/{stage_num} -> regex
            regex_str = "^" + re.sub(r"\{([^}]+)\}", r"(?P<\1>[^/]+)", r_pattern) + "$"
            match = re.match(regex_str, path)
            if match:
                return fn, match.groupdict(), default_status
        return None, {}, 404

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> FallbackResponse:
        decoded_url = urllib.parse.unquote(url)
        # Check raw url string for traversal attempts
        if "/artifacts/" in decoded_url and (".." in decoded_url.split("/artifacts/")[-1]):
            return FallbackResponse(content={"detail": "Invalid artifact_name parameter"}, status_code=400)

        fn, path_params, default_status = self._match_route("GET", url)
        if fn is None:
            return FallbackResponse(content={"detail": "Not Found"}, status_code=404)

        try:
            res = fn(**path_params)
            if isinstance(res, FallbackResponse):
                return res
            return FallbackResponse(content=res, status_code=default_status)
        except HTTPException as exc:
            return FallbackResponse(content={"detail": exc.detail}, status_code=exc.status_code)
        except Exception as exc:
            return FallbackResponse(content={"detail": str(exc)}, status_code=500)

    def post(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
    ) -> FallbackResponse:
        fn, path_params, default_status = self._match_route("POST", url)
        if fn is None:
            return FallbackResponse(content={"detail": "Not Found"}, status_code=404)

        kwargs: dict[str, Any] = dict(path_params)
        if data:
            kwargs.update(data)

        if files:
            for k, val in files.items():
                if isinstance(val, tuple):
                    # (filename, content, content_type)
                    fname = val[0]
                    content = val[1]
                    ctype = val[2] if len(val) > 2 else "application/octet-stream"
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    stream = io.BytesIO(content)
                    kwargs[k] = FallbackUploadFile(filename=fname, file=stream, content_type=ctype)
                elif isinstance(val, FallbackUploadFile):
                    kwargs[k] = val

        try:
            if inspect.iscoroutinefunction(fn):
                res = asyncio.run(fn(**kwargs))
            else:
                res = fn(**kwargs)

            if isinstance(res, FallbackResponse):
                return res
            return FallbackResponse(content=res, status_code=default_status)
        except HTTPException as exc:
            return FallbackResponse(content={"detail": exc.detail}, status_code=exc.status_code)
        except Exception as exc:
            return FallbackResponse(content={"detail": str(exc)}, status_code=500)


TestClient = RealTestClient if RealTestClient is not None else FallbackTestClient
