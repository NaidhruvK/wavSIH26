"""The seams that decide whether the 13 Sep capabilities reach the upload path.

Each capability here existed, or could have existed, while being invisible from
the service: a spectrogram computed and never written, an LDPC decoder no route
called, a verdict that lived only in prose, an fs invented without a label.
These tests pin the adapters, not the science - the science is in
tests/unit/test_pseudorandom.py and tests/unit/test_ldpc_blind.py.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from contracts import StageStatus
from service.config import config
from service.orchestrator import (REQUIRED_PLUGIN_MODULES, _summarise_code_params,
                                  adapt_s0, adapt_s1, adapt_s4, adapt_s5)


class _ArtifactDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = config.artifact_dir
        object.__setattr__(config, "artifact_dir", Path(self._tmp.name) / "artifacts")
        config.artifact_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        object.__setattr__(config, "artifact_dir", self._orig)
        self._tmp.cleanup()


class WaterfallArtifact(_ArtifactDir):
    def _s1(self, n_f=1024, n_t=700):
        return SimpleNamespace(
            status="ok", fs=200_000.0, snr_db=20.0, noise_floor_db=-60.0,
            occupied_bw_hz=58_000.0, bursts=[], psd_freqs=np.linspace(-1, 1, 64),
            psd_db=np.zeros(64), spec_freqs=np.linspace(-1e5, 1e5, n_f),
            spec_times=np.linspace(0, 1, n_t),
            spec_db=np.arange(n_f * n_t, dtype=float).reshape(n_f, n_t),
            snr_method="spectral", snr_db_spectral=20.0, snr_db_moment=None,
            sampling_check={"occupied_fraction": 0.29, "oversampling": 3.42,
                            "fs_observable": False})

    def test_waterfall_is_written_transposed_and_decimated(self):
        res = adapt_s1(self._s1(), 1.0, "run-wf")
        self.assertIn("waterfall_plot", res.artifacts)
        path = Path(res.artifacts["waterfall_plot"])
        if not path.is_absolute():
            path = config.repo_root / path
        data = json.loads(path.read_text())
        power = data["power"]
        # rows are time, columns are frequency (Plotly indexes z[y][x])
        self.assertEqual(len(power), len(data["time"]))
        self.assertEqual(len(power[0]), len(data["freqs"]))
        self.assertLessEqual(len(data["freqs"]), 512)
        self.assertLessEqual(len(data["time"]), 512)

    def test_sampling_ratios_are_surfaced(self):
        values = adapt_s1(self._s1(8, 8), 1.0, "run-wf2").values
        self.assertEqual(values["oversampling"], 3.42)
        self.assertEqual(values["occupied_fraction"], 0.29)


class FsProvenance(unittest.TestCase):
    def test_fs_source_follows_fs(self):
        raw = SimpleNamespace(status="ok", iq=np.zeros(10), fs=200_000.0,
                              source_format="raw_int16", hypotheses=[],
                              reason="assumed", file_path="x.iq",
                              fs_source="assumed_default")
        keys = list(adapt_s0(raw, 1.0).values)
        self.assertEqual(keys[keys.index("fs") + 1], "fs_source")

    def test_raw_iq_without_hint_is_labelled_assumed(self):
        from pipeline.s0_ingest import ingest
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cap.iq"
            rng = np.random.default_rng(0)
            iq = (rng.normal(size=20_000) + 1j * rng.normal(size=20_000)) * 3000
            inter = np.empty(40_000, dtype="<i2")
            inter[0::2], inter[1::2] = iq.real, iq.imag
            inter.tofile(p)
            unhinted, hinted = ingest(p), ingest(p, fs_hint=48_000.0)
        self.assertEqual(unhinted.fs_source, "assumed_default")
        self.assertIn("ASSUMED", unhinted.reason)
        self.assertEqual(hinted.fs_source, "caller_hint")
        self.assertEqual(hinted.fs, 48_000.0)


class S4Verdict(unittest.TestCase):
    def _raw(self, **kw):
        base = dict(status="low_confidence", confidence=0.35, period=96, offset=0,
                    generators_octal=None, method="exact", inferred_ber=None,
                    interleaver=None, code=None, hypotheses=[], profile=None,
                    reason="period-96 structure", interleaver_verdict=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_period_only_verdict_is_queryable(self):
        v = {"verdict": "period-only", "period_structure": True,
             "permutation_recovered": False, "key_space_bits": 498.3,
             "candidates_tried": 612}
        values = adapt_s4(self._raw(interleaver_verdict=v), 1.0, "r").values
        self.assertEqual(values["interleaver_verdict"], "period-only")
        self.assertIs(values["permutation_recovered"], False)
        self.assertEqual(values["key_space_bits"], 498.3)

    def test_a_recovery_says_inverted(self):
        intl = SimpleNamespace(family="qpp", params={"period": 96, "f1": 11, "f2": 24})
        values = adapt_s4(self._raw(status="ok", interleaver=intl), 1.0, "r").values
        self.assertEqual(values["interleaver_family"], "qpp")
        self.assertEqual(values["interleaver_verdict"], "inverted")
        self.assertIs(values["permutation_recovered"], True)


class S5Labelling(unittest.TestCase):
    def test_ldpc_decode_is_not_described_as_viterbi(self):
        detail = {"code_family": "ldpc", "code_identified_blind": True,
                  "blocks_converged": 235, "blocks": 235,
                  "code_params": {"code_name": "gallager-n96-r1_2-963"}}
        res = adapt_s5(np.zeros(100, dtype=np.uint8), 1.0, detail)
        self.assertEqual(res.status, StageStatus.OK)
        self.assertEqual(res.hypotheses[0].value, "ldpc_decoded")
        self.assertIn("belief propagation", res.hypotheses[0].evidence)
        self.assertIn("gallager-n96-r1_2-963", res.hypotheses[0].evidence)
        self.assertNotIn("trellis", res.hypotheses[0].evidence)

    def test_conv_decode_keeps_its_label(self):
        res = adapt_s5(np.zeros(10, dtype=np.uint8), 1.0, {"code_family": "conv"})
        self.assertEqual(res.hypotheses[0].value, "viterbi_decoded")

    def test_matrices_never_reach_the_report(self):
        out = _summarise_code_params({"H": np.zeros((720, 1440), dtype=np.uint8),
                                      "offset": 5, "code_name": "wimax",
                                      "taps": [1, 0, 1]})
        self.assertEqual(out["H"], "uint8 array 720x1440")
        self.assertEqual(out["offset"], 5)
        self.assertEqual(out["taps"], [1, 0, 1])
        json.dumps(out)


class PluginModules(unittest.TestCase):
    def test_new_families_are_loaded_by_the_service(self):
        self.assertIn("pipeline.s4_recover.pseudorandom", REQUIRED_PLUGIN_MODULES)
        self.assertIn("pipeline.s5_decode.ldpc_code", REQUIRED_PLUGIN_MODULES)


if __name__ == "__main__":
    unittest.main()
