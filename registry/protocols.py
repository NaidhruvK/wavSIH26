"""The three plug-in registries: MODULATIONS, INTERLEAVERS, and CODES.

OWNED BY: Naidhruv.
Frozen on 29 Aug per project specifications.

Protocols:
    MODULATIONS   classify_features(iq), demodulate(iq, params), theoretical_cumulants()
    INTERLEAVERS  candidate_params(n_bits), deinterleave(bits, **params), rank_signature(**params)
    CODES         blind_recover(llrs), decode(llrs, params), validate(bits)

Registration decorators & functions:
    register_modulation(plugin=None, replace=False)
    register_interleaver(plugin=None, replace=False)
    register_code(plugin=None, replace=False)

Introspection:
    describe() -> dict
    clear() -> None
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

__all__ = [
    "MODULATIONS",
    "INTERLEAVERS",
    "CODES",
    "ModulationPlugin",
    "InterleaverPlugin",
    "CodePlugin",
    "RegistryError",
    "register_modulation",
    "register_interleaver",
    "register_code",
    "describe",
    "clear",
]


class RegistryError(RuntimeError):
    """Raised when registration fails protocol validation or name conflicts."""
    pass


@runtime_checkable
class ModulationPlugin(Protocol):
    """Protocol for modulation receiver plug-ins."""
    name: str

    def classify_features(self, iq: Any) -> dict[str, Any]: ...
    def demodulate(self, iq: Any, params: dict[str, Any]) -> Any: ...
    def theoretical_cumulants(self) -> dict[str, Any]: ...


@runtime_checkable
class InterleaverPlugin(Protocol):
    """Protocol for interleaver detection and deinterleaving plug-ins."""
    name: str

    def candidate_params(self, n_bits: int) -> Any: ...
    def deinterleave(self, bits: Any, **params: Any) -> Any: ...
    def rank_signature(self, **params: Any) -> int: ...


@runtime_checkable
class CodePlugin(Protocol):
    """Protocol for channel code recovery and decoding plug-ins."""
    name: str

    def blind_recover(self, llrs: Any) -> Any: ...
    def decode(self, llrs: Any, params: dict[str, Any]) -> Any: ...
    def validate(self, bits: Any) -> dict[str, Any]: ...


MODULATIONS: dict[str, Any] = {}
INTERLEAVERS: dict[str, Any] = {}
CODES: dict[str, Any] = {}

_REQUIRED: dict[str, tuple[str, ...]] = {
    "modulation": ("classify_features", "demodulate", "theoretical_cumulants"),
    "interleaver": ("candidate_params", "deinterleave", "rank_signature"),
    "code": ("blind_recover", "decode", "validate"),
}


def _register(table: dict[str, Any], kind: str, plugin: Any, replace: bool = False) -> Any:
    """Insert a plug-in into the registry table, enforcing its protocol.

    Checks are performed at registration time so that any incomplete plug-in
    fails immediately on module import.
    """
    name = getattr(plugin, "name", None)
    if not name or not isinstance(name, str):
        raise RegistryError(f"{kind} plug-in {plugin!r} has no string `name`")

    missing = [m for m in _REQUIRED[kind] if not callable(getattr(plugin, m, None))]
    if missing:
        raise RegistryError(
            f"{kind} plug-in {name!r} does not satisfy the protocol - missing {', '.join(missing)}"
        )

    existing = table.get(name)
    if existing is not None and not replace:
        def ident(obj: Any) -> tuple[str, str]:
            cls = obj if isinstance(obj, type) else type(obj)
            return (cls.__module__, cls.__qualname__)

        same = existing is plugin or ident(existing) == ident(plugin)
        if not same:
            raise RegistryError(
                f"{kind} plug-in {name!r} is already registered by {type(existing).__name__!r}. "
                "Two plug-ins claiming one name makes behaviour depend on import order; "
                "rename one, or pass replace=True if you mean it."
            )
        return existing

    table[name] = plugin
    return plugin


def _make_registrar(table: dict[str, Any], kind: str) -> Callable[..., Any]:
    """Create a registration function that also functions as a decorator."""
    def registrar(plugin: Any = None, replace: bool = False) -> Any:
        if plugin is None:
            return lambda p: _register(table, kind, p, replace=replace)
        if isinstance(plugin, bool):
            # Handles @register_*(replace=True) positional invocation
            actual_replace = plugin
            return lambda p: _register(table, kind, p, replace=actual_replace)
        return _register(table, kind, plugin, replace=replace)

    registrar.__doc__ = f"Register a {kind} plug-in, or use as a decorator."
    return registrar


register_modulation = _make_registrar(MODULATIONS, "modulation")
register_interleaver = _make_registrar(INTERLEAVERS, "interleaver")
register_code = _make_registrar(CODES, "code")


def describe() -> dict[str, Any]:
    """The payload behind GET /registry.

    Returns the names and modules of all currently registered plug-ins,
    together with count summaries for introspection.
    """
    def entry(plugin: Any) -> dict[str, Any]:
        return {
            "name": plugin.name,
            "detail": getattr(plugin, "detail", ""),
            "module": (
                type(plugin).__module__
                if not isinstance(plugin, type)
                else plugin.__module__
            ),
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
    """Empty every registry. Strictly for testing isolation."""
    MODULATIONS.clear()
    INTERLEAVERS.clear()
    CODES.clear()
