"""Deterministic mock data for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides reproducible StageResult and AnalysisReport mocks for offline development,
progressive reveal testing, and integration verification.
"""
from __future__ import annotations

from typing import Any

from contracts import AnalysisReport, Hypothesis, StageResult, StageStatus

_STAGE_CONFIGS: dict[str, dict[str, Any]] = {
    "s0_ingest": {
        "status": StageStatus.OK,
        "confidence": 1.0,
        "values": {
            "source_format": "wav",
            "fs": 200000.0,
            "channels": 2,
            "sample_count": 80000,
            "duration_seconds": 0.4,
        },
        "hypotheses": [
            Hypothesis(value="wav", score=1.0, evidence="Valid RIFF header with 2-channel float/int samples")
        ],
        "artifacts": {
            "raw_iq_path": "uploads/mock_capture.wav",
        },
        "elapsed_ms": 12.5,
        "reason": None,
    },
    "s1_detect": {
        "status": StageStatus.OK,
        "confidence": 0.98,
        "values": {
            "snr_db": 15.2,
            "noise_floor_db": -62.4,
            "occupied_bw_hz": 50000.0,
            "center_freq_hz": 0.0,
            "burst_count": 1,
        },
        "hypotheses": [
            Hypothesis(value="continuous", score=0.95, evidence="Continuous single-carrier transmission"),
            Hypothesis(value="bursty", score=0.05, evidence="No significant duty-cycle interruption"),
        ],
        "artifacts": {
            "psd_plot": "reports/artifacts/mock_psd.png",
            "waterfall_plot": "reports/artifacts/mock_waterfall.png",
        },
        "elapsed_ms": 45.1,
        "reason": None,
    },
    "s2_estimate": {
        "status": StageStatus.OK,
        "confidence": 0.96,
        "values": {
            "symbol_rate": 25000.0,
            "sps": 8.0,
            "cfo_hz": 120.5,
            "rolloff": 0.35,
            "modulation_family": "qpsk",
        },
        "hypotheses": [
            Hypothesis(value="qpsk", score=0.92, evidence="Distinct 4th-power spectral peak at 4*cfo"),
            Hypothesis(value="8psk", score=0.06, evidence="Low 8th-power cyclostationary response"),
            Hypothesis(value="bpsk", score=0.02, evidence="Squared-spectrum residual"),
        ],
        "artifacts": {
            "cyclostationary_plot": "reports/artifacts/mock_cyclostationary.png",
        },
        "elapsed_ms": 82.0,
        "reason": None,
    },
    "s3_receive": {
        "status": StageStatus.OK,
        "confidence": 0.95,
        "values": {
            "modulation": "qpsk",
            "evm_percent": 5.4,
            "lock_status": "locked",
            "timing_converged_sym": 840,
            "phase_rotations_count": 4,
            "estimated_ber": 0.0002,
        },
        "hypotheses": [
            Hypothesis(value="qpsk_rot0", score=0.90, evidence="Tight 4-centroid cluster, EVM 5.4%"),
            Hypothesis(value="qpsk_rot90", score=0.03, evidence="Alternative orthogonal phase candidate"),
        ],
        "artifacts": {
            "constellation_plot": "reports/artifacts/mock_constellation.png",
            "eye_diagram": "reports/artifacts/mock_eye.png",
        },
        "elapsed_ms": 134.2,
        "reason": None,
    },
    "s4_recover": {
        "status": StageStatus.OK,
        "confidence": 0.99,
        "values": {
            "interleaver_family": "block",
            "interleaver_depth": 8,
            "interleaver_width": 12,
            "period": 96,
            "code_rate": "1/2",
            "constraint_length": 7,
            "generators_octal": [121, 91],  # 0o171, 0o133 in decimal
        },
        "hypotheses": [
            Hypothesis(value="block_8x12", score=0.99, evidence="GF(2) matrix rank deficiency 36 at L=96"),
            Hypothesis(value="diagonal_8x12", score=0.01, evidence="Functionally rejected deinterleave"),
        ],
        "artifacts": {
            "rank_profile_plot": "reports/artifacts/mock_rank_collapse.png",
        },
        "elapsed_ms": 310.5,
        "reason": None,
    },
    "s5_decode": {
        "status": StageStatus.OK,
        "confidence": 1.0,
        "values": {
            "decoder": "viterbi_soft",
            "decoded_bits_count": 10000,
            "corrected_errors": 2,
            "reencode_ber": 0.0,
        },
        "hypotheses": [
            Hypothesis(value="conv_k7_r12", score=1.0, evidence="Zero traceback errors in Viterbi trellis")
        ],
        "artifacts": {
            "trellis_trace": "reports/artifacts/mock_trellis.png",
        },
        "elapsed_ms": 180.0,
        "reason": None,
    },
    "s6_frame": {
        "status": StageStatus.OK,
        "confidence": 1.0,
        "values": {
            "scrambler_detected": False,
            "frame_sync_marker": "1ACFFC1D",
            "printable_fraction": 0.98,
            "looks_like_text": True,
        },
        "hypotheses": [
            Hypothesis(
                value="ccsds_telemetry",
                score=0.99,
                evidence="Valid ASM sync word (0x1ACFFC1D) and 98% printable ASCII payload",
            )
        ],
        "artifacts": {
            "payload_dump": "reports/artifacts/mock_payload.txt",
        },
        "elapsed_ms": 28.4,
        "reason": None,
    },
}

ALL_STAGES = [
    "s0_ingest",
    "s1_detect",
    "s2_estimate",
    "s3_receive",
    "s4_recover",
    "s5_decode",
    "s6_frame",
]


def make_mock_stage_result(stage: str) -> StageResult:
    """Generate deterministic StageResult for a specified stage name."""
    if stage not in _STAGE_CONFIGS:
        raise ValueError(f"Unknown stage: {stage!r}. Expected one of {ALL_STAGES}")

    cfg = _STAGE_CONFIGS[stage]
    return StageResult(
        stage=stage,
        status=cfg["status"],
        confidence=cfg["confidence"],
        values=dict(cfg["values"]),
        hypotheses=list(cfg["hypotheses"]),
        artifacts=dict(cfg["artifacts"]),
        elapsed_ms=cfg["elapsed_ms"],
        reason=cfg["reason"],
    )


def make_mock_report(run_id: str = "mock-run") -> AnalysisReport:
    """Generate a full, deterministic AnalysisReport with all seven stages."""
    stages = [make_mock_stage_result(s) for s in ALL_STAGES]
    return AnalysisReport(
        run_id=run_id,
        file_meta={
            "filename": "qpsk_20db_run.wav",
            "size_bytes": 640044,
            "format": "wav",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        envelope_verdict="in_envelope",
        stages=stages,
        final={
            "payload_text": "RAAYA-SIH26: TELEMETRY FRAME #042 - ALL SYSTEMS NOMINAL - SIGNAL LOCK CONFIRMED",
            "printable_fraction": 0.98,
            "looks_like_text": True,
            "bits_count": 10000,
        },
    )
