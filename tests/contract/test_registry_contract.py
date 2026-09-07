"""Tests for registry/protocols.py and registry/__init__.py.

Verifies registration functions, decorators, protocol validation,
introspection via describe(), and registry isolation.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import unittest

from registry import (
    CODES,
    INTERLEAVERS,
    MODULATIONS,
    RegistryError,
    clear,
    describe,
    register_code,
    register_interleaver,
    register_modulation,
)


class DummyModulation:
    name = "dummy_mod"

    def classify_features(self, iq):
        return {"feat": 1.0}

    def demodulate(self, iq, params):
        return [0.0, 1.0]

    def theoretical_cumulants(self):
        return {"c42": -1.0}


class DummyInterleaver:
    name = "dummy_intl"

    def candidate_params(self, n_bits: int):
        return [{"depth": 4, "width": 8}]

    def deinterleave(self, bits, **params):
        return bits

    def rank_signature(self, **params) -> int:
        return 32


class DummyCode:
    name = "dummy_code"

    def blind_recover(self, llrs):
        return {"n": 2, "K": 7}

    def decode(self, llrs, params):
        return [0, 1, 0, 1]

    def validate(self, bits):
        return {"ok": True}


class TestRegistryContract(unittest.TestCase):
    # The registry is process-global and the real plug-ins register at module
    # import time, so a bare clear() in tearDown could never be undone: once
    # pipeline.s3_receive was imported, nothing re-runs its register_*() calls.
    # This class therefore used to leave the registry EMPTY for every test that
    # ran after it in the same process. Measured 7 Sep on main:
    #
    #   tests/contract/test_s3_s4_s5_chain.py alone -> 4 passed
    #   after this class                            -> 4 errors, KeyError 'qpsk'
    #   tests/unit/test_s3_ldpc_junction.py alone   -> 27 passed
    #   after this class                            -> 24 failed
    #
    # 14 of the 41 failures on main were this and nothing else. Snapshot and
    # restore instead, so the isolation these tests need costs no one else.
    def setUp(self):
        self._saved = (dict(MODULATIONS), dict(INTERLEAVERS), dict(CODES))
        clear()

    def tearDown(self):
        clear()
        MODULATIONS.update(self._saved[0])
        INTERLEAVERS.update(self._saved[1])
        CODES.update(self._saved[2])

    def test_direct_registration(self):
        mod = DummyModulation()
        register_modulation(mod)
        self.assertIn("dummy_mod", MODULATIONS)
        self.assertIs(MODULATIONS["dummy_mod"], mod)

        intl = DummyInterleaver()
        register_interleaver(intl)
        self.assertIn("dummy_intl", INTERLEAVERS)
        self.assertIs(INTERLEAVERS["dummy_intl"], intl)

        code = DummyCode()
        register_code(code)
        self.assertIn("dummy_code", CODES)
        self.assertIs(CODES["dummy_code"], code)

    def test_decorator_registration_bare(self):
        @register_code
        class DecoratedCode:
            name = "dec_code"

            def blind_recover(self, llrs):
                return None

            def decode(self, llrs, params):
                return []

            def validate(self, bits):
                return {"ok": True}

        self.assertIn("dec_code", CODES)
        self.assertIs(CODES["dec_code"], DecoratedCode)

    def test_decorator_registration_with_kwargs(self):
        @register_interleaver(replace=True)
        class DecoratedIntl:
            name = "dec_intl"

            def candidate_params(self, n_bits):
                return []

            def deinterleave(self, bits, **params):
                return bits

            def rank_signature(self, **params):
                return 16

        self.assertIn("dec_intl", INTERLEAVERS)
        self.assertIs(INTERLEAVERS["dec_intl"], DecoratedIntl)

    def test_missing_protocol_method_raises_error(self):
        class IncompleteMod:
            name = "incomplete"

            def classify_features(self, iq):
                return {}

            # missing demodulate and theoretical_cumulants

        with self.assertRaises(RegistryError) as ctx:
            register_modulation(IncompleteMod())

        err = str(ctx.exception)
        self.assertIn("demodulate", err)
        self.assertIn("theoretical_cumulants", err)

    def test_nameless_plugin_rejected(self):
        class NamelessCode:
            def blind_recover(self, llrs):
                return None

            def decode(self, llrs, params):
                return []

            def validate(self, bits):
                return {"ok": True}

        with self.assertRaises(RegistryError):
            register_code(NamelessCode())

    def test_name_conflict_raises_import_order_error(self):
        code1 = DummyCode()
        register_code(code1)

        class ImpostorCode:
            name = "dummy_code"

            def blind_recover(self, llrs):
                return None

            def decode(self, llrs, params):
                return []

            def validate(self, bits):
                return {"ok": True}

        with self.assertRaises(RegistryError) as ctx:
            register_code(ImpostorCode())

        self.assertIn("import order", str(ctx.exception))

    def test_describe_manifest_structure(self):
        register_modulation(DummyModulation())
        register_interleaver(DummyInterleaver())
        register_code(DummyCode())

        desc = describe()
        self.assertEqual(desc["counts"]["modulations"], 1)
        self.assertEqual(desc["counts"]["interleavers"], 1)
        self.assertEqual(desc["counts"]["codes"], 1)

        self.assertEqual(desc["modulations"][0]["name"], "dummy_mod")
        self.assertEqual(desc["interleavers"][0]["name"], "dummy_intl")
        self.assertEqual(desc["codes"][0]["name"], "dummy_code")


if __name__ == "__main__":
    unittest.main()
