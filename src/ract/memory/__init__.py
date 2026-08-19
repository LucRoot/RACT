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
from ract.memory.cache import (
    RetrievalCache,
    RetrievalCacheError,
)
from ract.memory.chunk import (
    Chunk,
    ChunkFormat,
    chunk_from_chunk_row,
    chunk_from_symbol,
    format_chunk,
)
from ract.memory.chunker import (
    MAX_TOKENS_PER_CHUNK,
    OversizeChunkWarning,
    chunk_symbol,
)
from ract.memory.query_trace import (
    CascadeStep,
    IndexHit,
    QueryTrace,
    to_canonical_json,
)
from ract.memory.retrieve import (
    BoundedContextError,
    GraphDir,
    IndexKind,
    IndexRef,
    MAX_NESTING_DEPTH,
    NestedRetrievalError,
    RetrievalBundle,
    RetrievalQuery,
    RetrievalStrategy,
    SymbolRef,
    bundle_file_paths,
    bundle_symbol_ids,
    bundle_to_cache_payload,
    cache_payload_to_bundle,
    canonical_query_payload,
    query_digest,
    retrieve,
)
from ract.memory.cpu_fallback import (
    LANCEDB_BACKEND_ENV_VAR,
    LanceDbProbeResult,
    probe_lancedb,
)
from ract.memory.embedding import (
    BGE_SMALL_NAME,
    DEFAULT_MODEL_NAME,
    BgeSmallEmbedding,
    EmbeddingError,
    EmbeddingModel,
    EmbeddingModelUnavailableError,
    NOMIC_NAME,
    NomicEmbedTextEmbedding,
    SyntheticHashEmbedding,
    UnknownEmbeddingError,
    load_embedding,
)
from ract.memory.parser import (
    SUPPORTED_EXTENSIONS,
    UnsupportedLanguageError,
    compute_content_hash,
    estimate_tokens,
    parse_file,
)
from ract.memory.semantic_builder import (
    BuildReport as SemanticBuildReport,
    DEFAULT_BATCH_SIZE as SEMANTIC_DEFAULT_BATCH_SIZE,
    UpdateReport as SemanticUpdateReport,
    build_from_files,
    initial_build as semantic_initial_build,
    update_symbol as semantic_update_symbol,
)
from ract.memory.semantic_index import (
    CHUNK_KINDS,
    ChunkRow,
    EmbeddingModelMismatchError,
    LanceDbUnavailableError,
    SemanticIndex,
    SemanticIndexError,
    SemanticStoreCorruptError,
    rebuild_chunk_vectors,
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
    "BGE_SMALL_NAME",
    "BgeSmallEmbedding",
    "BoundedContextError",
    "BudgetAccountant",
    "BudgetDeclaration",
    "BudgetExceededError",
    "BudgetNarrowing",
    "BudgetSection",
    "BuildReport",
    "CHUNK_KINDS",
    "CURRENT_SCHEMA_VERSION",
    "CascadeStep",
    "Chunk",
    "ChunkFormat",
    "ChunkRow",
    "DEFAULT_EXTENSIONS",
    "DEFAULT_MODEL_NAME",
    "EDGE_TYPES",
    "EdgeRow",
    "EmbeddingError",
    "EmbeddingModel",
    "EmbeddingModelMismatchError",
    "EmbeddingModelUnavailableError",
    "EventSink",
    "GraphBuildReport",
    "GraphDir",
    "GraphIndex",
    "GraphIndexError",
    "GraphPopulator",
    "GraphUpdateReport",
    "IndexHit",
    "IndexKind",
    "IndexRef",
    "LANCEDB_BACKEND_ENV_VAR",
    "LSP_ADAPTERS",
    "LanceDbProbeResult",
    "LanceDbUnavailableError",
    "LspClient",
    "LspProbeResult",
    "LspReference",
    "LspUnavailableError",
    "MAX_NESTING_DEPTH",
    "MAX_TOKENS_PER_CHUNK",
    "NEIGHBORHOOD_SOURCES",
    "NOMIC_NAME",
    "NestedRetrievalError",
    "NomicEmbedTextEmbedding",
    "NullEventSink",
    "OversizeChunkWarning",
    "ParseError",
    "QueryTrace",
    "RetrievalBundle",
    "RetrievalCache",
    "RetrievalCacheError",
    "RetrievalQuery",
    "RetrievalStrategy",
    "SEMANTIC_DEFAULT_BATCH_SIZE",
    "SUPPORTED_EXTENSIONS",
    "SemanticBuildReport",
    "SemanticIndex",
    "SemanticIndexError",
    "SemanticStoreCorruptError",
    "SemanticUpdateReport",
    "SqliteMissingFTS5Error",
    "SymbolIndex",
    "SymbolIndexError",
    "SymbolIndexWatcher",
    "SymbolRef",
    "SymbolRow",
    "SyntheticHashEmbedding",
    "TokenEstimator",
    "UnknownEmbeddingError",
    "UnknownFunctionError",
    "UnsupportedLanguageError",
    "WatcherStats",
    "WhitespaceTokenEstimator",
    "WideningRefusedError",
    "apply_composition_override",
    "apply_runtime_narrowing",
    "available_languages",
    "build_from_files",
    "bundle_file_paths",
    "bundle_symbol_ids",
    "bundle_to_cache_payload",
    "cache_payload_to_bundle",
    "canonical_query_payload",
    "chunk_from_chunk_row",
    "chunk_from_symbol",
    "chunk_symbol",
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
    "format_chunk",
    "get",
    "has_symbol_only_edges",
    "initial_build",
    "is_symbol_only",
    "load_defaults",
    "load_embedding",
    "narrow",
    "parse_file",
    "populate_symbol_only",
    "probe_lancedb",
    "probe_lsp",
    "query_digest",
    "rebuild_chunk_vectors",
    "retrieve",
    "semantic_initial_build",
    "semantic_update_symbol",
    "to_canonical_json",
    "walk",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
