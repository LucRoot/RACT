"""Test helpers for the four v0.5.0 memory-discipline functions.

The :class:`~ract.memory.functions.testing.mock_provider.MockProvider`
is the canned-response provider tests supply where a real
:class:`~ract.providers.base.ProviderAdapter` would live in
production.
"""

from __future__ import annotations

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.functions.testing.mock_provider import MockProvider


__all__ = ["MockProvider"]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
