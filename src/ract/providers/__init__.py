from __future__ import annotations


"""Provider adapters for RACT."""

from ract.providers.base import ProviderAdapter
from ract.providers.conformance import (
    CATEGORY_NAMES,
    CategoryScore,
    ConformanceIntent,
    ConformanceReport,
    load_corpus,
    run_conformance,
    write_report,
)
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
from ract.providers.schema import (
    parse_action_dict,
    parse_planned_step_dict,
    to_anthropic_tool_use,
    to_json_schema_fallback,
    to_openai_structured_outputs,
)
from ract.providers.validator import ResponseValidator, ValidationOutcome

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
