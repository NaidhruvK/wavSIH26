"""Evaluation metrics and comparison engine for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Defines metrics, scoring logic, and stage-by-stage comparison rules
against ground truth from zoo corpus, reports, or test fixtures.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MetricStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


@dataclass
class MetricResult:
    name: str
    stage: str
    actual: Any
    expected: Any
    status: MetricStatus
    tolerance: Optional[Any] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "actual": self.actual,
            "expected": self.expected,
            "status": self.status.value,
            "tolerance": self.tolerance,
            "message": self.message,
        }


@dataclass
class StageEvaluation:
    stage: str
    status: str  # "pass", "fail", "unavailable"
    score: float  # 0.0 to 1.0
    metrics: list[MetricResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "score": round(self.score, 4),
            "metrics": [m.to_dict() for m in self.metrics],
        }


@dataclass
class EvaluationResult:
    run_id: str
    target_file: str
    overall_verdict: str  # "pass", "partial", "fail", "inconclusive"
    overall_score: float  # 0.0 to 1.0
    stages: dict[str, StageEvaluation] = field(default_factory=dict)
    unavailable_metrics: list[str] = field(default_factory=list)
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_file": self.target_file,
            "overall_verdict": self.overall_verdict,
            "overall_score": round(self.overall_score, 4),
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "unavailable_metrics": self.unavailable_metrics,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _extract_stage_values(stage_data: Any) -> tuple[str, dict[str, Any], list[Any], float]:
    """Normalize StageResult or dict into (status, values, hypotheses, confidence)."""
    if hasattr(stage_data, "status"):
        st = stage_data.status.value if hasattr(stage_data.status, "value") else str(stage_data.status)
        vals = getattr(stage_data, "values", {}) or {}
        hyps = getattr(stage_data, "hypotheses", []) or []
        conf = getattr(stage_data, "confidence", 0.0)
        return st, vals, hyps, conf
    if isinstance(stage_data, dict):
        st = stage_data.get("status", "unknown")
        vals = stage_data.get("values", {}) or {}
        hyps = stage_data.get("hypotheses", []) or []
        conf = stage_data.get("confidence", 0.0)
        return st, vals, hyps, conf
    return "unknown", {}, [], 0.0


# -----------------------------------------------------------------------------
# Stage-Specific Evaluators
# -----------------------------------------------------------------------------

def eval_s0_ingest(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S0 Ingest against format, sampling rate, and IQ availability."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. Format match
    expected_fmt = truth.get("source_format") or truth.get("format")
    actual_fmt = vals.get("source_format")
    if expected_fmt is not None:
        passed = (str(actual_fmt).lower() == str(expected_fmt).lower())
        metrics.append(
            MetricResult(
                name="source_format",
                stage="s0_ingest",
                actual=actual_fmt,
                expected=expected_fmt,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Format {'matched' if passed else 'mismatched'}",
            )
        )
    else:
        # Check if actual format is one of allowed formats
        valid_formats = {"wav", "iq", "raw", "bin", "sigmf-data", "raw_int16", "raw_int8", "raw_float32"}
        passed = str(actual_fmt).lower() in valid_formats
        metrics.append(
            MetricResult(
                name="source_format",
                stage="s0_ingest",
                actual=actual_fmt,
                expected="valid_rf_format",
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message="Format verified as valid RF audio/IQ type",
            )
        )

    # 2. Sample rate match
    expected_fs = truth.get("fs")
    actual_fs = vals.get("sample_rate") or vals.get("fs")
    if expected_fs is not None and actual_fs is not None:
        rel_diff = abs(actual_fs - expected_fs) / expected_fs if expected_fs > 0 else 0.0
        passed = rel_diff <= 0.01  # Within 1%
        metrics.append(
            MetricResult(
                name="sample_rate",
                stage="s0_ingest",
                actual=actual_fs,
                expected=expected_fs,
                tolerance=0.01,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Sample rate diff: {rel_diff * 100:.2f}%",
            )
        )
    elif expected_fs is not None:
        metrics.append(
            MetricResult(
                name="sample_rate",
                stage="s0_ingest",
                actual=None,
                expected=expected_fs,
                status=MetricStatus.FAIL,
                message="Sample rate not reported by S0",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="sample_rate",
                stage="s0_ingest",
                actual=actual_fs,
                expected=None,
                status=MetricStatus.UNAVAILABLE,
                message="No expected sample rate provided in truth reference",
            )
        )

    # 3. Ingest Status
    passed_status = (st == "ok")
    metrics.append(
        MetricResult(
            name="ingest_status",
            stage="s0_ingest",
            actual=st,
            expected="ok",
            status=MetricStatus.PASS if passed_status else MetricStatus.FAIL,
            message=f"Ingest stage status: {st}",
        )
    )

    return _score_stage("s0_ingest", metrics)


def eval_s1_detect(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S1 Detect against SNR, occupied bandwidth, and burst detection."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. SNR estimation
    expected_snr = truth.get("snr_db")
    actual_snr = vals.get("snr_db")
    if expected_snr is not None and actual_snr is not None:
        diff = abs(float(actual_snr) - float(expected_snr))
        tolerance_db = 4.0  # Typical spectral estimation tolerance
        passed = diff <= tolerance_db
        metrics.append(
            MetricResult(
                name="snr_estimation",
                stage="s1_detect",
                actual=round(float(actual_snr), 2),
                expected=float(expected_snr),
                tolerance=tolerance_db,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"SNR error: {diff:.2f} dB (tolerance ±{tolerance_db} dB)",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="snr_estimation",
                stage="s1_detect",
                actual=actual_snr,
                expected=expected_snr,
                status=MetricStatus.UNAVAILABLE,
                message="Reference SNR unavailable in truth reference",
            )
        )

    # 2. Occupied Bandwidth
    expected_bw = truth.get("occupied_bw_hz") or truth.get("bandwidth_hz")
    actual_bw = vals.get("occupied_bw_hz")
    if expected_bw is not None and actual_bw is not None:
        rel_diff = abs(actual_bw - expected_bw) / expected_bw if expected_bw > 0 else 0.0
        passed = rel_diff <= 0.20  # Within 20%
        metrics.append(
            MetricResult(
                name="occupied_bandwidth",
                stage="s1_detect",
                actual=actual_bw,
                expected=expected_bw,
                tolerance=0.20,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Bandwidth error: {rel_diff * 100:.1f}%",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="occupied_bandwidth",
                stage="s1_detect",
                actual=actual_bw,
                expected=expected_bw,
                status=MetricStatus.UNAVAILABLE,
                message="Reference occupied bandwidth unavailable in truth reference",
            )
        )

    # 3. Burst Detection
    expected_bursts = truth.get("bursts")
    actual_bursts = vals.get("bursts") or vals.get("burst_count")
    if expected_bursts is not None:
        passed = bool(actual_bursts) == bool(expected_bursts)
        metrics.append(
            MetricResult(
                name="burst_detection",
                stage="s1_detect",
                actual=actual_bursts,
                expected=expected_bursts,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message="Burst profile checked against reference",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="burst_detection",
                stage="s1_detect",
                actual=actual_bursts,
                expected=None,
                status=MetricStatus.UNAVAILABLE,
                message="No burst reference data present in corpus truth",
            )
        )

    return _score_stage("s1_detect", metrics)


def eval_s2_estimate(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S2 Estimate against symbol rate, carrier frequency offset, and modulation classification."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. Symbol Rate
    # Expected symbol rate can be given directly or as fs / sps
    expected_rate = truth.get("symbol_rate")
    if expected_rate is None and truth.get("fs") and truth.get("sps"):
        expected_rate = float(truth["fs"]) / float(truth["sps"])

    actual_rate = vals.get("symbol_rate")
    if expected_rate is not None and actual_rate is not None:
        rel_diff = abs(actual_rate - expected_rate) / expected_rate if expected_rate > 0 else 0.0
        passed = rel_diff <= 0.05  # Within 5%
        metrics.append(
            MetricResult(
                name="symbol_rate",
                stage="s2_estimate",
                actual=round(float(actual_rate), 1),
                expected=round(float(expected_rate), 1),
                tolerance=0.05,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Symbol rate error: {rel_diff * 100:.2f}%",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="symbol_rate",
                stage="s2_estimate",
                actual=actual_rate,
                expected=expected_rate,
                status=MetricStatus.UNAVAILABLE,
                message="Reference symbol rate unavailable",
            )
        )

    # 2. CFO (Carrier Frequency Offset)
    expected_cfo = truth.get("cfo_hz")
    if expected_cfo is None and truth.get("cfo_norm") is not None and truth.get("fs"):
        expected_cfo = float(truth["cfo_norm"]) * float(truth["fs"])

    actual_cfo = vals.get("cfo_hz")
    if expected_cfo is not None and actual_cfo is not None:
        diff = abs(float(actual_cfo) - float(expected_cfo))
        tolerance_cfo = 150.0  # 150 Hz tolerance
        passed = diff <= tolerance_cfo
        metrics.append(
            MetricResult(
                name="carrier_offset_cfo",
                stage="s2_estimate",
                actual=round(float(actual_cfo), 2),
                expected=round(float(expected_cfo), 2),
                tolerance=tolerance_cfo,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"CFO absolute error: {diff:.2f} Hz",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="carrier_offset_cfo",
                stage="s2_estimate",
                actual=actual_cfo,
                expected=expected_cfo,
                status=MetricStatus.UNAVAILABLE,
                message="Reference CFO unavailable in truth",
            )
        )

    # 3. Modulation Classification Hypothesis
    expected_scheme = truth.get("scheme") or truth.get("modulation")
    # Check top hypothesis from S2
    top_hyp = None
    if hyps:
        first_hyp = hyps[0]
        top_hyp = getattr(first_hyp, "value", None) or (first_hyp.get("value") if isinstance(first_hyp, dict) else str(first_hyp))
    actual_scheme = vals.get("modulation") or top_hyp

    if expected_scheme is not None and actual_scheme is not None:
        passed = str(actual_scheme).lower() == str(expected_scheme).lower()
        metrics.append(
            MetricResult(
                name="modulation_class",
                stage="s2_estimate",
                actual=actual_scheme,
                expected=expected_scheme,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Modulation class {'matched' if passed else 'mismatched'}",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="modulation_class",
                stage="s2_estimate",
                actual=actual_scheme,
                expected=expected_scheme,
                status=MetricStatus.UNAVAILABLE,
                message="Modulation scheme reference not specified",
            )
        )

    return _score_stage("s2_estimate", metrics)


def eval_s3_receive(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S3 Receiver against demodulation scheme, carrier lock, and EVM."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. Demodulation Scheme
    expected_mod = truth.get("scheme") or truth.get("modulation")
    actual_mod = vals.get("modulation")
    if expected_mod and actual_mod:
        passed = str(actual_mod).lower() == str(expected_mod).lower()
        metrics.append(
            MetricResult(
                name="demod_scheme",
                stage="s3_receive",
                actual=actual_mod,
                expected=expected_mod,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Demod scheme: {actual_mod}",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="demod_scheme",
                stage="s3_receive",
                actual=actual_mod,
                expected=expected_mod,
                status=MetricStatus.UNAVAILABLE,
                message="Expected modulation reference unavailable",
            )
        )

    # 2. Carrier Lock / Status
    expected_status = truth.get("status", "ok")
    passed_status = (st == expected_status)
    metrics.append(
        MetricResult(
            name="carrier_lock",
            stage="s3_receive",
            actual=st,
            expected=expected_status,
            status=MetricStatus.PASS if passed_status else MetricStatus.FAIL,
            message=f"Receiver status: {st} (confidence: {conf:.2f})",
        )
    )

    # 3. EVM (Error Vector Magnitude)
    actual_evm = vals.get("evm_percent")
    expected_evm = truth.get("evm_percent")
    if expected_evm is not None and actual_evm is not None:
        diff = abs(float(actual_evm) - float(expected_evm))
        passed = diff <= 5.0  # Within ±5% EVM
        metrics.append(
            MetricResult(
                name="evm_percent",
                stage="s3_receive",
                actual=round(float(actual_evm), 2),
                expected=float(expected_evm),
                tolerance=5.0,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"EVM diff: {diff:.2f}%",
            )
        )
    elif actual_evm is not None:
        # Check reasonable EVM bound (< 30% for locked signal)
        passed = float(actual_evm) < 30.0
        metrics.append(
            MetricResult(
                name="evm_percent",
                stage="s3_receive",
                actual=round(float(actual_evm), 2),
                expected="< 30%",
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Measured EVM: {actual_evm:.2f}%",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="evm_percent",
                stage="s3_receive",
                actual=None,
                expected=expected_evm,
                status=MetricStatus.UNAVAILABLE,
                message="EVM metrics not reported",
            )
        )

    return _score_stage("s3_receive", metrics)


def eval_s4_recover(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S4 Rank Collapse against interleaver dimensions and code generator hypotheses."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # Extract truth interleaver & code specs
    intl_truth = truth.get("interleaver") or {}
    code_truth = truth.get("code") or {}

    # 1. Interleaver Period / Dimensions
    expected_period = intl_truth.get("period")
    if expected_period is None and intl_truth.get("depth") and intl_truth.get("width"):
        expected_period = int(intl_truth["depth"]) * int(intl_truth["width"])

    actual_period = vals.get("period")
    if expected_period is not None and actual_period is not None:
        passed = int(actual_period) == int(expected_period)
        metrics.append(
            MetricResult(
                name="interleaver_period",
                stage="s4_recover",
                actual=actual_period,
                expected=expected_period,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Interleaver period: {actual_period} (expected {expected_period})",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="interleaver_period",
                stage="s4_recover",
                actual=actual_period,
                expected=expected_period,
                status=MetricStatus.UNAVAILABLE,
                message="Reference interleaver period unavailable in truth reference",
            )
        )

    # 2. Interleaver Family
    expected_family = intl_truth.get("family")
    actual_family = vals.get("family") or vals.get("interleaver_family")
    if expected_family and actual_family:
        passed = str(actual_family).lower() == str(expected_family).lower()
        metrics.append(
            MetricResult(
                name="interleaver_family",
                stage="s4_recover",
                actual=actual_family,
                expected=expected_family,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Interleaver family: {actual_family}",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="interleaver_family",
                stage="s4_recover",
                actual=actual_family,
                expected=expected_family,
                status=MetricStatus.UNAVAILABLE,
                message="Interleaver family reference not specified",
            )
        )

    # 3. Code Generators (Octal)
    expected_polys = code_truth.get("polys_octal") or truth.get("polys_octal")
    actual_polys = vals.get("generators_octal")
    if expected_polys is not None and actual_polys is not None:
        try:
            exp_tuple = tuple(int(p) for p in expected_polys)
            act_tuple = tuple(int(p) for p in actual_polys)
            passed = act_tuple == exp_tuple
        except (ValueError, TypeError):
            passed = False

        metrics.append(
            MetricResult(
                name="code_generators",
                stage="s4_recover",
                actual=actual_polys,
                expected=expected_polys,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Generators {'matched' if passed else 'mismatched'}",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="code_generators",
                stage="s4_recover",
                actual=actual_polys,
                expected=expected_polys,
                status=MetricStatus.UNAVAILABLE,
                message="Reference code generators unavailable",
            )
        )

    return _score_stage("s4_recover", metrics)


def eval_s5_decode(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S5 FEC Decoding against decoded bit volume and BER."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. Decoded Bit Count
    expected_bits = truth.get("n_source_bits")
    actual_bits = vals.get("decoded_bits_count") or vals.get("bits_count")
    if actual_bits is not None:
        passed = actual_bits > 0
        metrics.append(
            MetricResult(
                name="decoded_bits_presence",
                stage="s5_decode",
                actual=actual_bits,
                expected="> 0",
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Decoded {actual_bits} bits",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="decoded_bits_presence",
                stage="s5_decode",
                actual=0,
                expected="> 0",
                status=MetricStatus.FAIL,
                message="No decoded bits output by S5",
            )
        )

    # 2. Inferred BER vs Injected BER
    expected_ber = truth.get("injected_ber")
    actual_ber = vals.get("inferred_ber") or vals.get("ber")
    if expected_ber is not None and actual_ber is not None:
        # At zero injected BER, output BER should be 0.0 or near zero (< 0.005)
        passed = float(actual_ber) <= max(float(expected_ber) * 1.5, 0.005)
        metrics.append(
            MetricResult(
                name="bit_error_rate",
                stage="s5_decode",
                actual=actual_ber,
                expected=expected_ber,
                status=MetricStatus.PASS if passed else MetricStatus.FAIL,
                message=f"Inferred BER: {actual_ber} (injected: {expected_ber})",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="bit_error_rate",
                stage="s5_decode",
                actual=actual_ber,
                expected=expected_ber,
                status=MetricStatus.UNAVAILABLE,
                message="Reference BER unavailable",
            )
        )

    return _score_stage("s5_decode", metrics)


def eval_s6_frame(stage_data: Any, truth: dict[str, Any]) -> StageEvaluation:
    """Evaluate S6 Framing / Payload against printable text ratio and content match."""
    st, vals, hyps, conf = _extract_stage_values(stage_data)
    metrics: list[MetricResult] = []

    # 1. Printable Fraction
    actual_fraction = vals.get("printable_fraction", 0.0)
    passed_fraction = float(actual_fraction) >= 0.80
    metrics.append(
        MetricResult(
            name="printable_fraction",
            stage="s6_frame",
            actual=round(float(actual_fraction), 3),
            expected=">= 0.80",
            status=MetricStatus.PASS if passed_fraction else MetricStatus.FAIL,
            message=f"Printable fraction: {actual_fraction:.2f}",
        )
    )

    # 2. Looks Like Text
    looks_like_text = vals.get("looks_like_text", False)
    metrics.append(
        MetricResult(
            name="looks_like_text",
            stage="s6_frame",
            actual=looks_like_text,
            expected=True,
            status=MetricStatus.PASS if looks_like_text else MetricStatus.FAIL,
            message="Payload text structure verification",
        )
    )

    # 3. Payload Text Match
    expected_text = truth.get("payload_text")
    actual_text = vals.get("text") or vals.get("payload_text", "")
    if expected_text:
        # Pass if expected text is contained or closely matches
        passed_text = expected_text.strip() in actual_text or actual_text.strip() in expected_text
        metrics.append(
            MetricResult(
                name="payload_text_match",
                stage="s6_frame",
                actual=actual_text[:50] + ("..." if len(actual_text) > 50 else ""),
                expected=expected_text[:50] + ("..." if len(expected_text) > 50 else ""),
                status=MetricStatus.PASS if passed_text else MetricStatus.FAIL,
                message="Payload text content match",
            )
        )
    else:
        metrics.append(
            MetricResult(
                name="payload_text_match",
                stage="s6_frame",
                actual=actual_text[:50] if actual_text else "",
                expected=None,
                status=MetricStatus.UNAVAILABLE,
                message="Reference payload text unavailable in truth reference",
            )
        )

    return _score_stage("s6_frame", metrics)


# -----------------------------------------------------------------------------
# Scoring Utility
# -----------------------------------------------------------------------------

def _score_stage(stage_name: str, metrics: list[MetricResult]) -> StageEvaluation:
    """Compute score and pass/fail/unavailable status for a stage evaluation."""
    evaluable = [m for m in metrics if m.status != MetricStatus.UNAVAILABLE]
    if not evaluable:
        return StageEvaluation(stage=stage_name, status="unavailable", score=1.0, metrics=metrics)

    passed_count = sum(1 for m in evaluable if m.status == MetricStatus.PASS)
    score = passed_count / len(evaluable)

    has_fail = any(m.status == MetricStatus.FAIL for m in evaluable)
    status = "fail" if has_fail else "pass"

    return StageEvaluation(stage=stage_name, status=status, score=score, metrics=metrics)
