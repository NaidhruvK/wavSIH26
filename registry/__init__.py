"""Plug-in registries. See protocols.py - and note that Naidhruv owns this
directory; the current contents are a strawman written to unblock S4's 31 Aug
gate, and are meant to be replaced.
"""

from .protocols import (  # noqa: F401
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
