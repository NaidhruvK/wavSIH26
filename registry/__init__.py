"""Plug-in registries: MODULATIONS, INTERLEAVERS, CODES.

OWNED BY: Naidhruv.
Frozen on 29 Aug per project specifications.
"""
from __future__ import annotations

from .protocols import (
    MODULATIONS,
    INTERLEAVERS,
    CODES,
    ModulationPlugin,
    InterleaverPlugin,
    CodePlugin,
    RegistryError,
    register_modulation,
    register_interleaver,
    register_code,
    describe,
    clear,
)

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
