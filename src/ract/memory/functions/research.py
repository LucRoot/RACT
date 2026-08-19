"""research function — WorkOrder in, ResearchBundle out.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §research.

Contract:

- Input: WorkOrder plus an :class:`IndexBundle` of live indexes.
- Retrieval: 7-step pattern per master spec (repo map, symbol
  index for named symbols, FTS on docstrings/comments, semantic
  top 10 by signature, graph one-hop signatures, git log grep for
  keywords top 5).
- Output: :class:`~ract.memory.functions.contracts.ResearchBundle`.
- On empty relevant_symbols: raise :class:`EmptyResearchError`.
- On more than 50 relevant_symbols: run one recursive narrowing pass
  with tighter scope hints; if still oversized, raise
  :class:`OversizedResearchError`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant
from ract.memory.budget_registry import get as budget_get
from ract.memory.chunk import ChunkFormat
from ract.memory.events import EventSink, NullEventSink, emit_budget_declared
from ract.memory.functions.contracts import (
    CommitRef,
    ResearchBundle,
    ScopeHints,
    SignatureRow,
    SymbolRef,
    SymbolWithRationale,
    WorkOrder,
    to_json,
)
from ract.memory.functions.errors import (
    EmptyResearchError,
    OversizedResearchError,
    ProviderContractError,
)
from ract.memory.functions.provider_adapter import (
    MemoryFunctionProvider,
    assemble_prompt,
    refuse_over_ceiling,
    seat_prompt_section,
)
from ract.memory.functions.prompts_loader import (
    assert_prompt_shipped,
    load_prompt,
)
from ract.memory.graph_index import GraphIndex
from ract.memory.retrieve import (
    GraphDir,
    IndexKind,
    IndexRef,
    RetrievalBundle,
    RetrievalQuery,
    RetrievalStrategy,
    SymbolRef as RetrieveSymbolRef,
    retrieve,
)
from ract.memory.semantic_index import SemanticIndex
from ract.memory.symbol_index import SymbolIndex


RESEARCH_FUNCTION_NAME: str = "research"
RESEARCH_PROMPT_VERSION: str = "v1"
RELEVANT_SYMBOLS_CAP: int = 50
"""Maximum relevant symbols before the recursive narrowing kicks in."""

assert_prompt_shipped(RESEARCH_FUNCTION_NAME, RESEARCH_PROMPT_VERSION)


@dataclass
class IndexBundle:
    """The three live indexes research composes over.

    A caller supplies whichever indexes are populated; missing ones
    cause the corresponding retrieval branch to no-op with a
    ``candidate_count=0`` trace hit.
    """

    symbol_index: SymbolIndex | None = None
    graph_index: GraphIndex | None = None
    semantic_index: SemanticIndex | None = None

    def to_index_refs(self) -> list[IndexRef]:
        refs: list[IndexRef] = []
        if self.symbol_index is not None:
            refs.append(IndexRef(kind=IndexKind.SYMBOL, index=self.symbol_index))
        if self.graph_index is not None:
            refs.append(IndexRef(kind=IndexKind.GRAPH, index=self.graph_index))
        if self.semantic_index is not None:
            refs.append(IndexRef(kind=IndexKind.SEMANTIC, index=self.semantic_index))
        return refs


def research(
    work_order: WorkOrder,
    indexes: IndexBundle,
    provider: MemoryFunctionProvider,
    *,
    accountant: BudgetAccountant | None = None,
    sink: EventSink | None = None,
) -> ResearchBundle:
    """Return a :class:`ResearchBundle` for ``work_order``.

    Sequence:

    1. Load the research budget from the registry.
    2. Build a :class:`RetrievalQuery` from WorkOrder scope_hints
       (mentioned_symbols → symbol_names; keywords → keywords +
       semantic seed; mentioned_directories + exclude_paths → scope
       filters).
    3. Compose the retrieve pool (SIGNATURE-format so no code bodies
       land in the prompt).
    4. If the retrieval pool exceeds the relevant-symbols cap, re-run
       one recursive narrowing pass with tighter scope.
    5. Seat sections + refuse over ceiling.
    6. Delegate to the provider; parse the response into the bundle.
    """
    active_sink = sink or NullEventSink()
    declaration = budget_get(RESEARCH_FUNCTION_NAME)
    active_accountant = accountant or BudgetAccountant(declaration=declaration)

    # Second Pass Q2 fix: an ambiguous WorkOrder must surface a
    # visible trace event; the composition layer (module_07) is the
    # gate that routes to human clarification, but the signal must
    # be inspectable from the trace even when the composition layer
    # elects to proceed with best-effort scope hints.
    if work_order.ambiguity_flags:
        emit_budget_declared(
            active_sink,
            {
                "function": RESEARCH_FUNCTION_NAME,
                "declaration": _declaration_payload(declaration),
                "narrowing_log": [],
                "source": "default",
                "ambiguity_flags": list(work_order.ambiguity_flags),
            },
        )

    bundle = _run_retrieval(work_order, indexes, sink=active_sink)
    if len(bundle.chunks) > RELEVANT_SYMBOLS_CAP:
        narrowed_hints = _narrow_scope(work_order.scope_hints)
        bundle = _run_retrieval(
            WorkOrder(
                request_type=work_order.request_type,
                scope_hints=narrowed_hints,
                success_criteria=work_order.success_criteria,
                constraints=work_order.constraints,
                priority_markers=work_order.priority_markers,
                ambiguity_flags=work_order.ambiguity_flags,
                metadata=work_order.metadata,
            ),
            indexes,
            sink=active_sink,
        )
        if len(bundle.chunks) > RELEVANT_SYMBOLS_CAP:
            raise OversizedResearchError(
                f"research pool oversized after narrowing "
                f"({len(bundle.chunks)} > {RELEVANT_SYMBOLS_CAP})",
                function=RESEARCH_FUNCTION_NAME,
                payload={"symbol_count": len(bundle.chunks)},
            )

    system = load_prompt(RESEARCH_FUNCTION_NAME, RESEARCH_PROMPT_VERSION)
    contract_block = _contract_block()
    state_block = to_json(work_order)
    bundle_block = _bundle_block(bundle, indexes)
    inputs_block = "run research against the WorkOrder above."

    for name, content in (
        ("system_prompt", system),
        ("contract", contract_block),
        ("state", state_block),
        ("retrieved_bundle", bundle_block),
        ("inputs", inputs_block),
    ):
        seat_prompt_section(
            active_accountant,
            name=name,
            content=content,
            content_hash=_hash(content),
        )

    emit_budget_declared(
        active_sink,
        {
            "function": RESEARCH_FUNCTION_NAME,
            "declaration": _declaration_payload(declaration),
            "narrowing_log": [],
            "source": "default",
        },
    )
    refuse_over_ceiling(active_accountant, sink=active_sink)

    prompt = assemble_prompt(
        system=system,
        contract=contract_block,
        state=state_block,
        bundle=bundle_block,
        inputs=inputs_block,
    )
    response = provider.send(prompt, declaration)
    parsed = _parse_response(response)
    if not parsed.relevant_symbols:
        raise EmptyResearchError(
            "research returned zero relevant symbols",
            function=RESEARCH_FUNCTION_NAME,
            payload={
                "request_type": work_order.request_type.value,
                "mentioned_symbols": list(work_order.scope_hints.mentioned_symbols),
            },
        )
    return parsed


# ---------------------------------------------------------------------------
# Retrieval composition
# ---------------------------------------------------------------------------


def _run_retrieval(
    work_order: WorkOrder,
    indexes: IndexBundle,
    *,
    sink: EventSink,
) -> RetrievalBundle:
    query = RetrievalQuery(
        symbol_names=work_order.scope_hints.mentioned_symbols,
        keywords=work_order.scope_hints.keywords,
        graph_seeds=tuple(
            RetrieveSymbolRef(name=name)
            for name in work_order.scope_hints.mentioned_symbols
        ),
        graph_direction=GraphDir.BOTH,
        graph_hops=1,
        file_scope=(
            work_order.scope_hints.mentioned_directories
            if work_order.scope_hints.mentioned_directories
            else None
        ),
        exclude_paths=work_order.scope_hints.exclude_paths,
    )
    # Research runs at SIGNATURE format — no code bodies.
    return retrieve(
        query,
        indexes.to_index_refs(),
        budget=3000,
        format=ChunkFormat.SIGNATURE,
        strategy=RetrievalStrategy.CORE_FIRST,
        sink=sink,
    )


def _narrow_scope(hints: ScopeHints) -> ScopeHints:
    """Return a tightened :class:`ScopeHints` for the second retrieval pass.

    Keeps only the first three mentioned symbols and the first three
    keywords; excludes any paths already listed. This is a bounded
    narrowing pass — not a general optimiser.
    """
    return ScopeHints(
        mentioned_symbols=hints.mentioned_symbols[:3],
        mentioned_files=hints.mentioned_files,
        mentioned_directories=hints.mentioned_directories,
        keywords=hints.keywords[:3],
        exclude_paths=hints.exclude_paths,
    )


def _bundle_block(bundle: RetrievalBundle, indexes: IndexBundle) -> str:
    """Project the retrieval bundle into a research-prompt block."""
    lines: list[str] = []
    lines.append("### signatures")
    for chunk in bundle.chunks:
        lines.append(
            f"{chunk.file_path}::{chunk.symbol_name} :: "
            f"{chunk.signature or '(no signature)'}"
        )
    if bundle.truncation_notes:
        lines.append("### truncation_notes")
        lines.extend(bundle.truncation_notes)
    if bundle.query_trace.error:
        lines.append(f"### note: {bundle.query_trace.error}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _contract_block() -> str:
    return (
        "Return one JSON object matching the research schema. Do not wrap in markdown."
    )


def _parse_response(response: str) -> ResearchBundle:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ProviderContractError(
            f"research response is not valid JSON: {exc}",
            function=RESEARCH_FUNCTION_NAME,
            payload={"response_excerpt": response[:200]},
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderContractError(
            "research response must be a JSON object",
            function=RESEARCH_FUNCTION_NAME,
        )
    relevant = tuple(
        _rehydrate_relevant(entry) for entry in payload.get("relevant_symbols", [])
    )
    neighborhood = tuple(
        _rehydrate_neighborhood(entry) for entry in payload.get("call_neighborhood", [])
    )
    prior_work = tuple(
        _rehydrate_commit(entry)
        for entry in payload.get("similar_prior_work", []) or []
    )
    risk_zones = tuple(
        _rehydrate_symbol_ref(entry) for entry in payload.get("risk_zones", []) or []
    )
    return ResearchBundle(
        relevant_symbols=relevant,
        call_neighborhood=neighborhood,
        architectural_context=str(payload.get("architectural_context", "")),
        similar_prior_work=prior_work,
        risk_zones=risk_zones,
        metadata=(("prompt_version", RESEARCH_PROMPT_VERSION),),
    )


def _rehydrate_relevant(entry: dict[str, Any]) -> SymbolWithRationale:
    symbol = _rehydrate_symbol_ref(entry)
    rationale = str(entry.get("rationale", ""))
    return SymbolWithRationale(symbol=symbol, rationale=rationale)


def _rehydrate_neighborhood(entry: dict[str, Any]) -> SignatureRow:
    return SignatureRow(
        symbol=_rehydrate_symbol_ref(entry),
        signature=str(entry.get("signature", "")),
        direction=str(entry.get("direction", "callee")),
    )


def _rehydrate_symbol_ref(entry: dict[str, Any]) -> SymbolRef:
    return SymbolRef(
        name=str(entry.get("name", "")),
        file_path=str(entry.get("file_path", "")),
        symbol_id=int(entry.get("symbol_id", -1)),
        kind=str(entry.get("kind", "")),
    )


def _rehydrate_commit(entry: dict[str, Any]) -> CommitRef:
    return CommitRef(
        sha=str(entry.get("sha", "")),
        subject=str(entry.get("subject", "")),
        files_touched=tuple(str(p) for p in entry.get("files_touched", []) or []),
    )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _declaration_payload(declaration: Any) -> dict[str, Any]:
    return {
        "function": declaration.function,
        "input_min": declaration.input_min,
        "input_target": declaration.input_target,
        "input_max": declaration.input_max,
        "output_min": declaration.output_min,
        "output_target": declaration.output_target,
        "output_max": declaration.output_max,
        "reasoning_headroom": declaration.reasoning_headroom,
        "hard_ceiling": declaration.hard_ceiling,
    }


__all__ = [
    "IndexBundle",
    "RELEVANT_SYMBOLS_CAP",
    "RESEARCH_FUNCTION_NAME",
    "RESEARCH_PROMPT_VERSION",
    "research",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
