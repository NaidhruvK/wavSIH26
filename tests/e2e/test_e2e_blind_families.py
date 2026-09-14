"""The two 13 Sep capabilities, through the REAL pipeline from a WAV. No stubs.

Same reason tests/e2e/test_e2e_real_signal.py exists: a capability that passes
its unit tests and is unreachable from `orchestrate()` is not a capability. Both
of these were exactly that at some point on 13 Sep - the LDPC decoder behind a
`CODES.get("conv")` that never asked it, and the QPP family behind a plug-in
module list that did not name it.

  LDPC downlink      QPSK carrying (96,48) Gallager codewords, no interleaver.
                     S5 must identify the code blind, by name, and decode it.
  QPP interleaver    QPSK carrying a rate-1/2 K=7 stream through the LTE K=96
                     QPP interleaver. S4 must invert the permutation.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np

from contracts import StageStatus
from service.config import config
from service.orchestrator import load_plugins, orchestrate

FS, SPS, BETA, SNR_DB = 200_000.0, 4, 0.35, 20.0


def _stage(report, name):
    return next(s for s in report.stages if s.stage == name)


class BlindFamiliesEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_plugins(force=True)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls._orig_artifacts = config.artifact_dir
        object.__setattr__(config, "artifact_dir", cls.tmp / "artifacts")

    @classmethod
    def tearDownClass(cls):
        object.__setattr__(config, "artifact_dir", cls._orig_artifacts)
        cls._tmp.cleanup()

    def _wav(self, bits, name):
        from zoo.rf import RFTruth, through_channel, write_wav_pair
        iq, n_used = through_channel(bits, "qpsk", SPS, BETA, SNR_DB, 0.0, 0.0, 0.0, 7)
        truth = RFTruth(scheme="qpsk", fs=FS, sps=SPS, beta=BETA, snr_db=SNR_DB,
                        cfo_norm=0.0, phase_rad=0.0, timing_offset_sym=0.0, seed=7,
                        n_bits_used=n_used, code=None, interleaver=None,
                        scrambler=None, injected_ber=0.0, error_model="independent")
        write_wav_pair(iq, truth, self.tmp, name)
        return self.tmp / (name + ".wav")

    def test_ldpc_downlink_is_identified_and_decoded_from_upload(self):
        from pipeline.s5_decode.ldpc_catalogue import codewords_from_h, load_catalogue
        entry = next(e for e in load_catalogue() if e.name == "gallager-n96-r1_2-963")
        stream, _ = codewords_from_h(entry.h, 260, seed=17)
        report = orchestrate(str(uuid.uuid4()), self._wav(stream, "ldpc"),
                             fs_hint=FS, db_path=self.tmp / "e2e.db")

        s1 = _stage(report, "s1_detect")
        self.assertIn("waterfall_plot", s1.artifacts)

        s4 = _stage(report, "s4_recover")
        # the LDPC block length collapses at 96; S4 must not call it interleaving
        self.assertNotIn("interleaving is present", s4.reason or "")

        s5 = _stage(report, "s5_decode")
        self.assertEqual(s5.status, StageStatus.OK, s5.reason)
        self.assertEqual(s5.values["code_family"], "ldpc")
        self.assertTrue(s5.values["code_identified_blind"])
        self.assertEqual(s5.values["code_params"]["code_name"], entry.name)
        self.assertEqual(s5.values["blocks_converged"], s5.values["blocks"])
        self.assertGreater(s5.values["decoded_bits_count"], 0)

    def test_qpp_interleaver_is_inverted_from_upload(self):
        import pipeline.s4_recover.pseudorandom as pr
        from pipeline.s5_decode.conv_reference import conv_encode
        coded = conv_encode(np.random.default_rng(5).integers(0, 2, 30_000, dtype=np.uint8))
        report = orchestrate(str(uuid.uuid4()),
                             self._wav(pr.qpp_interleave(coded, 96, 11, 24), "qpp"),
                             fs_hint=FS, db_path=self.tmp / "e2e.db")

        s4 = _stage(report, "s4_recover")
        self.assertEqual(s4.status, StageStatus.OK, s4.reason)
        self.assertEqual(s4.values["interleaver_family"], "qpp")
        self.assertTrue(np.array_equal(pr.qpp_permutation(**s4.values["interleaver_params"]),
                                       pr.qpp_permutation(96, 11, 24)))
        self.assertIs(s4.values["permutation_recovered"], True)
        self.assertEqual(s4.values["K"], 7)

        s5 = _stage(report, "s5_decode")
        self.assertEqual(s5.status, StageStatus.OK, s5.reason)
        self.assertEqual(s5.values["code_family"], "conv")


if __name__ == "__main__":
    unittest.main()
