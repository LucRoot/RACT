from __future__ import annotations


"""Provider adapters for RACT."""

from importlib import import_module
from typing import Any

from ract.providers.base import ProviderAdapter
from ract.providers.fake_provider import FakeProvider
from ract.providers.gate import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_REFUSAL_FIDELITY_THRESHOLD,
    DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD,
    DEFAULT_TOOL_DISCIPLINE_THRESHOLD,
    GateConfig,
    GateOutcome,
    check_provider_gate,
)
from ract.providers.internal_provider import InternalProvider
from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.providers.provider import Provider, ResponseShape
from ract.providers.router import ProviderRouter, register_adapter

# B-087: the conformance suite and the structured-output schema took about
# 120 ms at every start (``ract --version`` included) and are needed only by
# the commands that check a provider. They load on first use (PEP 562); the
# names below stay importable from ``ract.providers`` as before.
_LAZY = {
    "CATEGORY_NAMES": "ract.providers.conformance",
    "CategoryScore": "ract.providers.conformance",
    "ConformanceIntent": "ract.providers.conformance",
    "ConformanceReport": "ract.providers.conformance",
    "load_corpus": "ract.providers.conformance",
    "run_conformance": "ract.providers.conformance",
    "write_report": "ract.providers.conformance",
    "parse_action_dict": "ract.providers.schema",
    "parse_planned_step_dict": "ract.providers.schema",
    "to_anthropic_tool_use": "ract.providers.schema",
    "to_json_schema_fallback": "ract.providers.schema",
    "to_openai_structured_outputs": "ract.providers.schema",
    "ResponseValidator": "ract.providers.validator",
    "ValidationOutcome": "ract.providers.validator",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'ract.providers' has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


__all__ = [
    "CATEGORY_NAMES",
    "CategoryScore",
    "ConformanceIntent",
    "ConformanceReport",
    "DEFAULT_MAX_AGE_DAYS",
    "DEFAULT_REFUSAL_FIDELITY_THRESHOLD",
    "DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD",
    "DEFAULT_TOOL_DISCIPLINE_THRESHOLD",
    "FakeProvider",
    "GateConfig",
    "GateOutcome",
    "InternalProvider",
    "LocalHttpProvider",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderAdapter",
    "ProviderRouter",
    "ResponseShape",
    "ResponseValidator",
    "ValidationOutcome",
    "check_provider_gate",
    "load_corpus",
    "parse_action_dict",
    "parse_planned_step_dict",
    "register_adapter",
    "run_conformance",
    "to_anthropic_tool_use",
    "to_json_schema_fallback",
    "to_openai_structured_outputs",
    "write_report",
]
# RACT 0.1.1 - Trust and tooling
