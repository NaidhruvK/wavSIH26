"""The 31 Aug gate: plug-ins reached through the registry, not by import.

> Recovers 171/133 octal from clean coded data, through the registry.

"Through the registry" is the part that matters. Calling `recover_generators`
directly proves the algorithm works; going through `CODES["conv"]` proves the
orchestrator can do it without knowing that convolutional codes exist. That is
the property the whole plug-in architecture is for, and it is the one that
makes adding Reed-Solomon on 2 Sep a file and a line instead of a rewrite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import registry
from registry import CODES, INTERLEAVERS, RegistryError

# importing the plug-in modules is what registers them
import pipeline.s4_recover.interleavers  # noqa: F401
import pipeline.s5_decode.conv_code  # noqa: F401

from pipeline.s4_recover.interleavers import block_interleave
from tests.fixtures.local_zoo import make_stream


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def test_code_plugin_recovers_generators_through_the_registry():
    """The 19:15 verify line, literally."""
    plugin = CODES["conv"]                      # by name, not by import
    bits, truth = make_stream(60_000, None, None, seed=1)

    params = plugin.blind_recover(bits)

    assert params is not None, "registry plug-in recovered nothing on clean data"
    assert tuple(params.generators_octal) == tuple(truth.polys_octal)
    assert params.K == truth.K
    assert params.n == 2


@pytest.mark.parametrize("polys,K", [
    ((0o171, 0o133), 7),      # NASA/Voyager, the one the plan names
    ((0o133, 0o171), 7),      # same pair, swapped - must not be order-blind
    ((0o23, 0o35), 5),
    ((0o5, 0o7), 3),
    ((0o561, 0o753), 9),
])
def test_recovery_follows_the_zoo_configuration_not_a_constant(polys, K):
    """Asserting against a hardcoded (171, 133) would pass even if recovery
    were hardwired to return it. Configuring the zoo differently and demanding
    the answer follow is the test that actually has content."""
    plugin = CODES["conv"]
    bits, truth = make_stream(60_000, None, None, polys=polys, K=K, seed=2)

    params = plugin.blind_recover(bits)

    assert params is not None, "no recovery for K=%d %s" % (K, polys)
    assert tuple(params.generators_octal) == tuple(truth.polys_octal)
    assert params.K == truth.K == K


def test_decode_through_the_registry_returns_the_source_bits():
    plugin = CODES["conv"]
    bits, truth = make_stream(9_000, None, None, seed=1)

    params = plugin.blind_recover(bits)
    decoded = plugin.decode(bits, params)

    source = np.random.default_rng(truth.seed).integers(
        0, 2, truth.n_source_bits, dtype=np.uint8)
    n = min(len(decoded), len(source))
    assert n > 0
    assert np.array_equal(decoded[:n], source[:n])


def test_soft_and_hard_decode_agree_on_a_clean_stream():
    """The LLR path and the hard path must not disagree when there is no noise
    to disagree about - if they do, a sign convention is wrong somewhere."""
    plugin = CODES["conv"]
    bits, _ = make_stream(9_000, None, None, seed=3)
    params = plugin.blind_recover(bits)

    llrs = (1.0 - 2.0 * bits.astype(float)) * 8.0     # +ve == bit 0
    assert np.array_equal(plugin.decode(bits, params), plugin.decode(llrs, params))


def test_validate_and_validate_against():
    plugin = CODES["conv"]
    bits, _ = make_stream(9_000, None, None, seed=4)
    params = plugin.blind_recover(bits)
    decoded = plugin.decode(bits, params)

    report = plugin.validate(decoded)
    assert report["ok"]
    assert report["entropy_bits_per_symbol"] > 0.99

    against = plugin.validate_against(decoded, bits, params)
    assert against["ok"]
    assert against["reencode_ber"] == 0.0


def test_validate_rejects_degenerate_output():
    plugin = CODES["conv"]
    assert not plugin.validate(np.zeros(5000, dtype=np.uint8))["ok"]
    assert not plugin.validate(np.ones(5000, dtype=np.uint8))["ok"]
    assert not plugin.validate(np.zeros(0, dtype=np.uint8))["ok"]


def test_validate_against_catches_a_wrong_decode():
    """A decode that looks like plausible data but is not consistent with the
    received stream. `validate` cannot see this; `validate_against` must."""
    plugin = CODES["conv"]
    bits, _ = make_stream(9_000, None, None, seed=5)
    params = plugin.blind_recover(bits)

    rubbish = np.random.default_rng(0).integers(0, 2, 9_000, dtype=np.uint8)
    assert plugin.validate(rubbish)["ok"], "fixture should look plausible on its own"
    against = plugin.validate_against(rubbish, bits, params)
    assert not against["ok"]
    assert against["reencode_ber"] > 0.3


def test_code_plugin_refuses_uncoded_data():
    plugin = CODES["conv"]
    noise = np.random.default_rng(9).integers(0, 2, 80_000, dtype=np.uint8)
    assert plugin.blind_recover(noise) is None


def test_code_plugin_refuses_a_short_stream():
    plugin = CODES["conv"]
    assert plugin.blind_recover(np.zeros(100, dtype=np.uint8)) is None


# --------------------------------------------------------------------------
# the interleaver side
# --------------------------------------------------------------------------

def test_interleaver_plugin_round_trips_through_the_registry():
    plugin = INTERLEAVERS["block"]
    bits, _ = make_stream(20_000, None, None, seed=6)
    woven = block_interleave(bits, 8, 12)
    back = plugin.deinterleave(woven, depth=8, width=12)
    assert np.array_equal(back, bits[:len(back)])


def test_interleaver_rank_signature_is_the_period():
    plugin = INTERLEAVERS["block"]
    assert plugin.rank_signature(depth=8, width=12) == 96


def test_interleaver_candidate_params_are_bounded():
    """Risk #5 - the sweep is content-influenced and must not run away."""
    plugin = INTERLEAVERS["block"]
    cands = list(plugin.candidate_params(10_000_000))
    assert len(cands) < 20_000, "candidate list is unbounded: %d" % len(cands)
    for c in cands:
        assert c["depth"] * c["width"] <= 512
        assert c["depth"] >= 2 and c["width"] >= 1


# --------------------------------------------------------------------------
# the registry itself
# --------------------------------------------------------------------------

def test_describe_reports_what_is_actually_registered():
    d = registry.describe()
    assert d["counts"]["codes"] >= 1
    assert d["counts"]["interleavers"] >= 1
    assert "conv" in [c["name"] for c in d["codes"]]
    assert "block" in [i["name"] for i in d["interleavers"]]
    # a judge should be able to see where a plug-in came from
    assert all(e["module"] for e in d["codes"])


def test_protocol_is_enforced_at_registration_time():
    """A plug-in missing a method must fail on import, not three stages into an
    analysis in front of a judge."""
    class Incomplete:
        name = "incomplete"

        def blind_recover(self, llrs):
            return None

    with pytest.raises(RegistryError) as exc:
        registry.register_code(Incomplete())
    assert "decode" in str(exc.value) and "validate" in str(exc.value)


def test_nameless_plugin_is_rejected():
    class Nameless:
        def blind_recover(self, llrs): ...
        def decode(self, llrs, params): ...
        def validate(self, bits): ...

    with pytest.raises(RegistryError):
        registry.register_code(Nameless())


def test_reimport_is_idempotent_but_a_name_clash_is_not():
    import importlib
    import pipeline.s5_decode.conv_code as mod

    before = len(CODES)
    importlib.reload(mod)                       # a second import must be safe
    assert len(CODES) == before

    class Impostor:
        name = "conv"

        def blind_recover(self, llrs): ...
        def decode(self, llrs, params): ...
        def validate(self, bits): ...

    with pytest.raises(RegistryError) as exc:
        registry.register_code(Impostor())
    assert "import order" in str(exc.value)


def test_orchestrator_can_iterate_without_naming_a_scheme():
    """The architectural claim, as a test: recovery driven purely by iterating
    the registry. Nothing below mentions 'conv' or 'block'."""
    bits, truth = make_stream(60_000, None, None, seed=7)

    recovered = []
    for name, plugin in CODES.items():
        params = plugin.blind_recover(bits)
        if params is not None:
            recovered.append((name, params))

    assert len(recovered) == 1
    _, params = recovered[0]
    assert tuple(params.generators_octal) == tuple(truth.polys_octal)
