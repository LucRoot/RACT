"""Memory discipline package (v0.5.0).

Public surface for the token budget system and (in later modules) the
three indexes, retrieve primitive, function contracts, playbooks, and
self-adjustment probes. Module_01 lands only the budget subsystem; the
rest of the package is scaffolded by later modules.

See ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` for the full design
and ``docs/ADRs/ADR-0031-budget-accountant-hard-ceiling.md`` for the
enforcement rationale.
"""

from __future__ import annotations

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetExceededError,
    BudgetNarrowing,
    BudgetSection,
    TokenEstimator,
    WhitespaceTokenEstimator,
    WideningRefusedError,
    narrow,
)
from ract.memory.budget_registry import (
    UnknownFunctionError,
    get,
    load_defaults,
)
from ract.memory.composition import (
    apply_composition_override,
    apply_runtime_narrowing,
)
from ract.memory.events import (
    EventSink,
    NullEventSink,
    emit_budget_declared,
    emit_budget_exceeded,
    emit_probe_evaluated,
    emit_retrieval_cascaded,
    emit_retrieval_refused,
    emit_retrieval_requested,
    emit_retrieval_satisfied,
)
from ract.memory.graph_index import (
    EDGE_TYPES,
    EdgeRow,
    GraphIndex,
    GraphIndexError,
    NEIGHBORHOOD_SOURCES,
)
from ract.memory.graph_populator import (
    BuildReport as GraphBuildReport,
    GraphPopulator,
    UpdateReport as GraphUpdateReport,
)
from ract.memory.lsp import (
    LSP_ADAPTERS,
    LspClient,
    LspProbeResult,
    LspReference,
    LspUnavailableError,
    available_languages,
    probe_lsp,
)
from ract.memory.lsp_fallback import (
    clear_symbol_only_edges,
    has_symbol_only_edges,
    is_symbol_only,
    populate_symbol_only,
)
from ract.memory.parser import (
    SUPPORTED_EXTENSIONS,
    UnsupportedLanguageError,
    compute_content_hash,
    estimate_tokens,
    parse_file,
)
from ract.memory.symbol_index import (
    CURRENT_SCHEMA_VERSION,
    SqliteMissingFTS5Error,
    SymbolIndex,
    SymbolIndexError,
    SymbolRow,
)
from ract.memory.walker import (
    BuildReport,
    DEFAULT_EXTENSIONS,
    ParseError,
    initial_build,
    walk,
)
from ract.memory.watcher import SymbolIndexWatcher, WatcherStats


__all__ = [
    "BudgetAccountant",
    "BudgetDeclaration",
    "BudgetExceededError",
    "BudgetNarrowing",
    "BudgetSection",
    "BuildReport",
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_EXTENSIONS",
    "EDGE_TYPES",
    "EdgeRow",
    "EventSink",
    "GraphBuildReport",
    "GraphIndex",
    "GraphIndexError",
    "GraphPopulator",
    "GraphUpdateReport",
    "LSP_ADAPTERS",
    "LspClient",
    "LspProbeResult",
    "LspReference",
    "LspUnavailableError",
    "NEIGHBORHOOD_SOURCES",
    "NullEventSink",
    "ParseError",
    "SUPPORTED_EXTENSIONS",
    "SqliteMissingFTS5Error",
    "SymbolIndex",
    "SymbolIndexError",
    "SymbolIndexWatcher",
    "SymbolRow",
    "TokenEstimator",
    "UnknownFunctionError",
    "UnsupportedLanguageError",
    "WatcherStats",
    "WhitespaceTokenEstimator",
    "WideningRefusedError",
    "apply_composition_override",
    "apply_runtime_narrowing",
    "available_languages",
    "clear_symbol_only_edges",
    "compute_content_hash",
    "emit_budget_declared",
    "emit_budget_exceeded",
    "emit_probe_evaluated",
    "emit_retrieval_cascaded",
    "emit_retrieval_refused",
    "emit_retrieval_requested",
    "emit_retrieval_satisfied",
    "estimate_tokens",
    "get",
    "has_symbol_only_edges",
    "initial_build",
    "is_symbol_only",
    "load_defaults",
    "narrow",
    "parse_file",
    "populate_symbol_only",
    "probe_lsp",
    "walk",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
