# wavSIH26 / Raaya — System Failure Matrix & Isolation Specification

This document specifies the failure modes, isolation boundaries, expected contract responses, and recovery behaviors for the **wavSIH26 (Raaya)** blind RF signal intelligence pipeline.

---

## 1. Core Architectural Failure Principles

1. **Zero Uncaught Exceptions in Production**:
   Pipeline stages and background jobs must never allow unhandled exceptions to crash the FastAPI service or background worker threads. Exceptions must be caught, converted to a structured `StageResult(status=StageStatus.FAILED, reason=...)`, and recorded in SQLite.
2. **Upstream Ingest Gate**:
   If Stage 0 (`s0_ingest`) cannot extract valid baseband IQ samples (e.g. unsupported format, corrupt RIFF header, empty file), downstream signal processing stages cannot run. The pipeline must record `S0` as `failed`, mark subsequent stages (`S1`–`S6`) as aborted with a structured explanation, set `envelope_verdict="failed"`, and persist the final `AnalysisReport`.
3. **Downstream Failure Isolation**:
   If an intermediate stage fails (e.g. S2 frequency offset estimation fails, or S4 rank collapse encounters an unhandled exception), independent downstream stages must continue executing wherever possible. If a subsequent stage depends strictly on prior outputs (e.g. S5 requires S4 code parameters), it handles the missing parameter gracefully rather than crashing.
4. **Per-Stage and Total Timeout Guardrails**:
   Each stage is capped at `config.stage_timeout_seconds` (default: 15s). The entire analysis run is capped at `config.total_timeout_seconds` (default: 90s). When a timeout triggers, the running stage is interrupted via `StageTimeoutError`, recorded as `failed`, and subsequent stages are either isolated or aborted.
5. **JSON Purity**:
   Large binary or floating-point arrays (`iq_samples`, raw symbol buffers) must never be serialized into API JSON responses. They are stored strictly on disk in `artifacts/{run_id}/` and referenced via safe relative paths.

---

## 2. Comprehensive Failure Matrix

| ID | Failure Mode | Trigger / Condition | Affected Stage | Expected HTTP / Contract Status | Downstream Action | Recovery & Persistence Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **F01** | **Unsupported File Format** | User uploads non-RF file (`.pdf`, `.mp3`, `.txt`, `.exe`) | REST API (`POST /analyze`) | HTTP 400 Bad Request | **Reject Immediately** | Request rejected at HTTP boundary; no background job, quarantine file, or SQLite record created. |
| **F02** | **Empty File Upload** | User uploads 0-byte file | REST API (`POST /analyze`) | HTTP 400 Bad Request | **Reject Immediately** | Temporary file deleted immediately; HTTP 400 with "Uploaded file is empty". |
| **F03** | **Oversized Upload** | Upload exceeds `max_upload_size_bytes` (2 GB default) | REST API (`POST /analyze`) | HTTP 413 Payload Too Large | **Reject & Clean** | Stream aborted mid-upload; partial disk file unlinked; no orphan files. |
| **F04** | **Corrupt WAV Header** | WAV file truncated or has < 2 channels (mono) | `s0_ingest` | Contract `StageStatus.FAILED`<br>Report `failed` | **Abort Downstream** | S0 records failure reason; S1–S6 marked with `"Aborted due to upstream failure in S0 ingest"`; report saved to SQLite. |
| **F05** | **Unidentifiable Raw IQ** | Raw `.iq` file where sniffer cannot find plausible dtype | `s0_ingest` | Contract `StageStatus.FAILED`<br>Report `failed` | **Abort Downstream** | S0 records format hypotheses and failure; downstream stages abort cleanly. |
| **F06** | **Missing Run ID** | Client queries `/runs/{id}` with unknown run identifier | REST API (`GET /runs/{id}`) | HTTP 404 Not Found | **N/A** | Clean 404 response with `Run '{run_id}' not found`; no unhandled 500 error. |
| **F07** | **Invalid Stage Parameter** | Client queries `/runs/{id}/stage/99` or `/stage/invalid` | REST API (`GET /runs/...`) | HTTP 400 Bad Request | **N/A** | Clean 400 explaining valid stage range (0–6 or `s0_ingest`..`s6_frame`). |
| **F08** | **Path Traversal Attack** | Client requests artifact `/artifacts/../../etc/passwd` | REST API (`GET /artifacts/...`) | HTTP 400 / 403 Forbidden | **N/A** | `is_safe_artifact_path` detects directory escape; immediately blocked. |
| **F09** | **Missing Artifact** | Client requests artifact not generated for run | REST API (`GET /artifacts/...`) | HTTP 404 Not Found | **N/A** | Clean 404 explaining artifact not found; frontend renders graceful "Unavailable" card. |
| **F10** | **S1 Low SNR / Undetected** | Signal SNR is below threshold (< -5 dB) or empty | `s1_detect` | Contract `StageStatus.OUT_OF_ENVELOPE` or `FAILED` | **Continue** | S1 records low SNR; S2–S6 proceed with best effort or mark `low_confidence`. |
| **F11** | **S2 Missing Implementation** | Primary `s2_estimate` not installed or missing | `s2_estimate` | Contract `StageStatus.OK` (via fallback) | **Continue** | Orchestrator activates `local_s2` fallback; symbol rate & CFO estimated cleanly. |
| **F12** | **Stage Execution Timeout** | Single stage processing exceeds `stage_timeout_seconds` | Any stage (S0–S6) | Contract `StageStatus.FAILED`<br>`reason="Stage timed out..."` | **Isolate & Continue** | Worker caught by `StageTimeoutError`; elapsed time recorded; next stage executed. |
| **F13** | **Total Analysis Timeout** | Cumulative execution exceeds `total_timeout_seconds` | Pipeline Orchestrator | Contract `StageStatus.FAILED`<br>Verdict `failed` | **Abort Remaining** | Remaining stages marked with `"Total timeout exceeded"`; report finalized and persisted. |
| **F14** | **Unhandled Stage Exception** | Teammate code raises unexpected error (e.g. `ZeroDivisionError`) | Any stage (S1–S6) | Contract `StageStatus.FAILED`<br>`reason="Stage failed with..."` | **Isolate & Continue** | Orchestrator wraps call in try/except; logs error; records failure in SQLite; continues pipeline. |
| **F15** | **S3 Carrier Lock Failure** | Costas loop fails to converge; EVM > 25% | `s3_receive` | Contract `StageStatus.LOW_CONFIDENCE` or `OUT_OF_ENVELOPE` | **Continue** | Soft LLRs still generated; S4 attempts blind recovery; report reflects low confidence. |
| **F16** | **S4 No Rank Collapse** | GF(2) null-space reveals no periodic linear dependencies | `s4_recover` | Contract `StageStatus.FAILED` / `LOW_CONFIDENCE` | **Continue** | S4 notes no collapse found; S5 skips Viterbi or attempts fallback uncoded decode. |
| **F17** | **S6 Unprintable Telemetry** | Decoded payload has < 80% printable characters | `s6_frame` | Contract `StageStatus.LOW_CONFIDENCE`<br>`looks_like_text=False` | **Complete** | Payload hex dump saved; `printable_fraction` recorded; report completed cleanly. |
| **F18** | **High Concurrency Load** | Multiple simultaneous analysis submissions | Service / `JobRunner` | HTTP 202 Accepted | **Queue & Concur** | `ThreadPoolExecutor(max_workers=4)` queues excess jobs; SQLite WAL mode prevents database locks. |

---

## 3. Detailed Stage Failure Semantics

### 3.1 Stage 0: Ingest
- **Primary Responsibility**: File normalization to complex 64-bit float baseband IQ array.
- **Critical Failure Condition**: File does not exist, file is not 2-channel WAV or sniffable raw IQ, or sample count is 0.
- **Action**: Immediate halt of pipeline. Downstream stages cannot process without samples. All downstream stages are marked as `FAILED` with explicit upstream abort reasons.

### 3.2 Stage 1: Detect
- **Primary Responsibility**: Welch PSD, noise floor, SNR, and occupied bandwidth.
- **Failure Condition**: Empty array, negative bandwidth calculation, or NaN/Inf in signal power.
- **Action**: Isolate. If S1 fails, S2 still receives the raw IQ array and attempts blind estimation.

### 3.3 Stage 2: Estimate
- **Primary Responsibility**: Symbol rate, samples-per-symbol (SPS), carrier frequency offset (CFO).
- **Failure Condition**: Cyclostationary peak undetectable, spectrum corruption.
- **Fallback**: Automatically delegates to `tests/fixtures/local_s2.py` if `pipeline.s2_estimate` is absent or fails.
- **Action**: Isolate. Defaults (e.g. SPS=4, CFO=0) are passed to S3 to allow demodulation attempt.

### 3.4 Stage 3: Receive
- **Primary Responsibility**: Matched filtering, symbol timing recovery (Gardner), carrier tracking (Costas), constellation generation, LLR output.
- **Failure Condition**: Timing loop divergence, Costas cycle slips.
- **Action**: If carrier lock metric < 0.60, mark `LOW_CONFIDENCE` or `OUT_OF_ENVELOPE`. Hard-sliced bits or soft LLRs are still forwarded to S4.

### 3.5 Stage 4: Recover
- **Primary Responsibility**: Blind deinterleaving via GF(2) matrix rank deficiency sweep.
- **Failure Condition**: No rank collapse detected (deficiency = 0 across all tested periods $L \in [8, 512]$).
- **Action**: Mark S4 `FAILED` or `LOW_CONFIDENCE`. Forward un-deinterleaved bits to S5.

### 3.6 Stage 5: Decode
- **Primary Responsibility**: Viterbi soft trellis decoding or Reed-Solomon algebraic decoding.
- **Failure Condition**: Traceback error ceiling exceeded; re-encoded BER > 0.05.
- **Action**: Record corrected bit count and inferred BER; forward whatever decoded stream is available to S6.

### 3.7 Stage 6: Frame
- **Primary Responsibility**: ASM sync marker search, descrambling, ASCII/UTF-8 payload extraction.
- **Failure Condition**: Sync marker not found; printable ASCII ratio < 0.80.
- **Action**: Mark S6 `LOW_CONFIDENCE`. Store raw hex bytes as `payload_dump.txt` artifact; set `looks_like_text=False`.

---

## 4. Operational Recovery Verification

Every failure condition in this matrix is verified by automated regression tests in:
- `tests/e2e/test_e2e_pipeline.py` (End-to-End API and Orchestration)
- `tests/service/test_orchestrator.py` (Adapter and Failure Isolation)
- `tests/service/test_main.py` (REST Boundary Validation)
- `tests/contract/test_stage_contract.py` (Contract Purity and Invariants)
