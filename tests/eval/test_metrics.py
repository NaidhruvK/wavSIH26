"""Tests for eval/metrics.py stage evaluators and metrics scoring.

OWNED BY: Naidhruv.
"""
from __future__ import annotations

import unittest

from eval.metrics import (
    MetricResult,
    MetricStatus,
    StageEvaluation,
    eval_s0_ingest,
    eval_s1_detect,
    eval_s2_estimate,
    eval_s3_receive,
    eval_s4_recover,
    eval_s5_decode,
    eval_s6_frame,
)


class TestEvalMetrics(unittest.TestCase):
    def test_eval_s0_ingest_pass(self):
        stage_data = {
            "status": "ok",
            "values": {"source_format": "wav", "sample_rate": 200000.0, "samples_count": 50000},
        }
        truth = {"source_format": "wav", "fs": 200000.0}
        res = eval_s0_ingest(stage_data, truth)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 1.0)
        self.assertEqual(len(res.metrics), 3)

    def test_eval_s0_ingest_sample_rate_mismatch(self):
        stage_data = {
            "status": "ok",
            "values": {"source_format": "wav", "sample_rate": 48000.0},
        }
        truth = {"source_format": "wav", "fs": 200000.0}
        res = eval_s0_ingest(stage_data, truth)
        self.assertEqual(res.status, "fail")
        sr_metric = next(m for m in res.metrics if m.name == "sample_rate")
        self.assertEqual(sr_metric.status, MetricStatus.FAIL)

    def test_eval_s1_detect_snr_tolerance(self):
        stage_data = {
            "status": "ok",
            "values": {"snr_db": 18.5, "noise_floor_db": -60.0},
        }
        # Expected SNR is 20.0, actual is 18.5 -> difference 1.5 dB (within ±4.0 dB)
        truth = {"snr_db": 20.0}
        res = eval_s1_detect(stage_data, truth)
        self.assertEqual(res.status, "pass")
        snr_metric = next(m for m in res.metrics if m.name == "snr_estimation")
        self.assertEqual(snr_metric.status, MetricStatus.PASS)

        # Missing burst and bandwidth should be marked unavailable
        bw_metric = next(m for m in res.metrics if m.name == "occupied_bandwidth")
        self.assertEqual(bw_metric.status, MetricStatus.UNAVAILABLE)

    def test_eval_s1_detect_snr_out_of_tolerance(self):
        stage_data = {
            "status": "ok",
            "values": {"snr_db": 5.0},
        }
        truth = {"snr_db": 20.0}
        res = eval_s1_detect(stage_data, truth)
        self.assertEqual(res.status, "fail")

    def test_eval_s2_estimate_matches(self):
        stage_data = {
            "status": "ok",
            "values": {"symbol_rate": 50100.0, "cfo_hz": 25.0, "modulation": "qpsk"},
            "hypotheses": [{"value": "qpsk", "score": 0.95}],
        }
        truth = {"fs": 200000.0, "sps": 4, "cfo_norm": 0.0, "scheme": "qpsk"}
        res = eval_s2_estimate(stage_data, truth)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 1.0)

    def test_eval_s3_receive_carrier_lock_and_scheme(self):
        stage_data = {
            "status": "ok",
            "confidence": 0.96,
            "values": {"modulation": "16qam", "evm_percent": 6.5},
        }
        truth = {"scheme": "16qam", "evm_percent": 6.28, "status": "ok"}
        res = eval_s3_receive(stage_data, truth)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 1.0)

    def test_eval_s4_recover_interleaver_and_code(self):
        stage_data = {
            "status": "ok",
            "values": {
                "period": 96,
                "family": "block",
                "generators_octal": [121, 91],
            },
        }
        truth = {
            "interleaver": {"family": "block", "depth": 8, "width": 12, "period": 96},
            "code": {"polys_octal": [121, 91]},
        }
        res = eval_s4_recover(stage_data, truth)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 1.0)

    def test_eval_s5_decode_bits_and_ber(self):
        stage_data = {
            "status": "ok",
            "values": {"decoded_bits_count": 20000, "inferred_ber": 0.0001},
        }
        truth = {"n_source_bits": 20000, "injected_ber": 0.0}
        res = eval_s5_decode(stage_data, truth)
        self.assertEqual(res.status, "pass")

    def test_eval_s6_frame_text_and_printable(self):
        stage_data = {
            "status": "ok",
            "values": {
                "printable_fraction": 0.99,
                "looks_like_text": True,
                "text": "RAAYA TELEMETRY LOCK CONFIRMED",
            },
        }
        truth = {"payload_text": "RAAYA TELEMETRY LOCK"}
        res = eval_s6_frame(stage_data, truth)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 1.0)


if __name__ == "__main__":
    unittest.main()
