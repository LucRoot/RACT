# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."

_ROOT_KNOT = object()

"""Provider adapters for RootAct."""

from rootact.providers.base import ProviderAdapter
from rootact.providers.local_http_provider import LocalHttpProvider
from rootact.providers.openai_provider import OpenAICompatibleProvider
from rootact.providers.router import ProviderRouter, register_adapter

__all__ = [
    "ProviderAdapter",
    "OpenAICompatibleProvider",
    "LocalHttpProvider",
    "ProviderRouter",
    "register_adapter",
]
# RACT 0.1.1 - Trust and Tooling
