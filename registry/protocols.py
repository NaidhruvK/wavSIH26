"""The three plug-in registries.

OWNERSHIP: this directory is NAIDHRUV'S. This file is a strawman, written by
Nehal on 31 Aug only because S4 could not otherwise satisfy its own gate
("recovers 171/133 from clean coded data, THROUGH THE REGISTRY") before the
real registry existed. Overwrite it freely - nothing here is precious. What
matters is that the three protocols keep the shapes the Command Center names,
because S4's plug-ins are written against them:

    MODULATIONS   classify_features(), demodulate(iq, params) -> LLRs,
                  theoretical_cumulants()
    INTERLEAVERS  candidate_params(), deinterleave(bits, params),
                  rank_signature()
    CODES         blind_recover(llrs), decode(llrs, params), validate(bits)

Registration is a dict insertion and nothing else. The orchestrator iterates
these dicts and must never name a scheme - that is the whole reason adding
8-PSK or Reed-Solomon is one file and one line rather than a rewrite.

LLR CONVENTION - stated here because it is a cross-stream contract and the
2 Sep gate turns on it:

    llr[i] = log( P(bit i == 0) / P(bit i == 1) )

so a POSITIVE LLR means bit 0 is more likely, and the hard decision is
`bits = (llr < 0)`. Anvith's S3 emits this; S4 and S5 consume it. Note that
commpy's `viterbi_decode(decoding_type="unquantized")` uses the opposite sign
(+1 means bit 1), so the conversion happens inside the code plug-in and nowhere
else. Getting this backwards decodes to noise without raising anything.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MODULATIONS", "INTERLEAVERS", "CODES",
    "ModulationPlugin", "InterleaverPlugin", "CodePlugin",
    "register_modulation", "register_interleaver", "register_code",
    "describe", "clear", "RegistryError",
]


class RegistryError(RuntimeError):
    pass


@runtime_checkable
class ModulationPlugin(Protocol):
    name: str

    def classify_features(self, iq) -> dict: ...
    def demodulate(self, iq, params: dict): ...
    def theoretical_cumulants(self) -> dict: ...


@runtime_checkable
class InterleaverPlugin(Protocol):
    name: str

    def candidate_params(self, n_bits: int): ...
    def deinterleave(self, bits, **params): ...
    def rank_signature(self, **params) -> int: ...


@runtime_checkable
class CodePlugin(Protocol):
    name: str

    def blind_recover(self, llrs): ...
    def decode(self, llrs, params: dict): ...
    def validate(self, bits) -> dict: ...


MODULATIONS: dict[str, Any] = {}
INTERLEAVERS: dict[str, Any] = {}
CODES: dict[str, Any] = {}

_REQUIRED = {
    "modulation": ("classify_features", "demodulate", "theoretical_cumulants"),
    "interleaver": ("candidate_params", "deinterleave", "rank_signature"),
    "code": ("blind_recover", "decode", "validate"),
}


def _register(table: dict, kind: str, plugin: Any, replace: bool) -> Any:
    """Insert a plug-in, refusing anything that does not satisfy its protocol.

    The check is deliberately at registration time rather than at call time. A
    plug-in that is missing a method should fail when the module is imported,
    not three stages into an analysis in front of a judge.
    """
    name = getattr(plugin, "name", None)
    if not name or not isinstance(name, str):
        raise RegistryError("%s plug-in %r has no string `name`" % (kind, plugin))

    missing = [m for m in _REQUIRED[kind] if not callable(getattr(plugin, m, None))]
    if missing:
        raise RegistryError(
            "%s plug-in %r does not satisfy the protocol - missing %s"
            % (kind, name, ", ".join(missing)))

    existing = table.get(name)
    if existing is not None and not replace:
        # Re-registering the identical plug-in is what a second import looks
        # like, and that is harmless. Registering a DIFFERENT object under a
        # name already taken is not: the orchestrator would silently use
        # whichever module imported last, and the run would depend on import
        # order rather than on anything anyone decided.
        # Compare by qualified name, not by class identity. A module reload -
        # or the same module reached under two sys.path entries, which is easy
        # to do in a repo where tests prepend the root - builds a NEW class
        # object for the same source. Identity would call that a clash and
        # refuse a perfectly ordinary second import.
        def ident(obj):
            cls = obj if isinstance(obj, type) else type(obj)
            return (cls.__module__, cls.__qualname__)

        same = existing is plugin or ident(existing) == ident(plugin)
        if not same:
            raise RegistryError(
                "%s plug-in %r is already registered by %r. Two plug-ins "
                "claiming one name makes behaviour depend on import order; "
                "rename one, or pass replace=True if you mean it."
                % (kind, name, type(existing).__name__))
        return existing

    table[name] = plugin
    return plugin


def register_modulation(plugin, replace: bool = False):
    return _register(MODULATIONS, "modulation", plugin, replace)


def register_interleaver(plugin, replace: bool = False):
    return _register(INTERLEAVERS, "interleaver", plugin, replace)


def register_code(plugin, replace: bool = False):
    return _register(CODES, "code", plugin, replace)


def describe() -> dict:
    """The payload behind GET /registry.

    The 31 Aug gate reads this endpoint, so it returns counts as well as names
    - a judge or a teammate should be able to see at a glance what the running
    build actually supports, rather than what the README claims.
    """
    def entry(plugin):
        return {
            "name": plugin.name,
            "detail": getattr(plugin, "detail", ""),
            "module": type(plugin).__module__ if not isinstance(plugin, type)
                      else plugin.__module__,
        }

    return {
        "modulations": [entry(p) for p in MODULATIONS.values()],
        "interleavers": [entry(p) for p in INTERLEAVERS.values()],
        "codes": [entry(p) for p in CODES.values()],
        "counts": {
            "modulations": len(MODULATIONS),
            "interleavers": len(INTERLEAVERS),
            "codes": len(CODES),
        },
    }


def clear() -> None:
    """Empty every registry. Tests only - never call this from the service."""
    MODULATIONS.clear()
    INTERLEAVERS.clear()
    CODES.clear()
