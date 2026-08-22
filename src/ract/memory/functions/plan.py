"""plan function — WorkOrder + ResearchBundle in, ChangePlan out.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §plan.

Contract:

- Input: WorkOrder + ResearchBundle + IndexBundle (for optional mid-
  invocation retrieval calls).
- Retrieval: initial pass reads the research bundle; may issue up to
  three mid-invocation :func:`~ract.memory.retrieve.retrieve` calls
  under 500-token sub-budgets each (bounded by module_05's
  :class:`NestedRetrievalError`).
- Output: :class:`~ract.memory.functions.contracts.ChangePlan`.
- On infeasible request: raise :class:`InfeasiblePlanError`
  (composition escalates).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant
from ract.memory.budget_registry import get as budget_get
from ract.memory.chunk import ChunkFormat
from ract.memory.events import EventSink, NullEventSink, emit_budget_declared
from ract.memory.functions.contracts import (
    ChangePlan,
    Invariant,
    InvariantKind,
    RiskAssessment,
    RiskLevel,
    SymbolRef,
    TargetSymbol,
    VerificationCriterion,
    ResearchBundle,
    WorkOrder,
    to_json,
)
from ract.memory.functions.errors import (
    InfeasiblePlanError,
    ProviderContractError,
)
from ract.memory.functions.provider_adapter import (
    MemoryFunctionProvider,
    assemble_prompt,
    refuse_over_ceiling,
    refuse_over_max,
    seat_prompt_section,
    seat_state_section,
)
from ract.memory.functions.prompts_loader import (
    assert_prompt_shipped,
    load_prompt,
)
from ract.memory.functions.research import IndexBundle
from ract.memory.retrieve import (
    RetrievalBundle,
    RetrievalQuery,
    RetrievalStrategy,
    retrieve,
)


PLAN_FUNCTION_NAME: str = "plan"
PLAN_PROMPT_VERSION: str = "v1"
MID_INVOCATION_RETRIEVE_BUDGET: int = 500
MAX_MID_INVOCATION_RETRIEVES: int = 3

assert_prompt_shipped(PLAN_FUNCTION_NAME, PLAN_PROMPT_VERSION)


def plan(
    work_order: WorkOrder,
    research_bundle: ResearchBundle,
    indexes: IndexBundle,
    provider: MemoryFunctionProvider,
    *,
    accountant: BudgetAccountant | None = None,
    sink: EventSink | None = None,
    mid_invocation_queries: tuple[RetrievalQuery, ...] = (),
) -> ChangePlan:
    """Return a :class:`ChangePlan` for the request.

    ``mid_invocation_queries`` supplies zero to three
    :class:`RetrievalQuery` values plan runs before the model call
    under a scoped 500-token sub-budget each. Cascade nesting depth
    stays at 1 so module_05's :class:`NestedRetrievalError` cannot
    fire from here.
    """
    active_sink = sink or NullEventSink()
    declaration = budget_get(PLAN_FUNCTION_NAME)
    active_accountant = accountant or BudgetAccountant(declaration=declaration)

    if len(mid_invocation_queries) > MAX_MID_INVOCATION_RETRIEVES:
        raise InfeasiblePlanError(
            f"plan received {len(mid_invocation_queries)} mid-invocation queries; "
            f"max is {MAX_MID_INVOCATION_RETRIEVES}",
            function=PLAN_FUNCTION_NAME,
        )
    mid_bundles = tuple(
        retrieve(
            query,
            indexes.to_index_refs(),
            budget=MID_INVOCATION_RETRIEVE_BUDGET,
            format=ChunkFormat.SIGNATURE,
            strategy=RetrievalStrategy.CORE_FIRST,
            sink=active_sink,
            depth=1,
        )
        for query in mid_invocation_queries
    )

    system = load_prompt(PLAN_FUNCTION_NAME, PLAN_PROMPT_VERSION)
    contract_block = _contract_block()
    state_block = _state_block(work_order, research_bundle)
    bundle_block = _bundle_block(tuple(mid_bundles))
    inputs_block = "produce a ChangePlan the edit step can execute."

    for name, content in (
        ("system_prompt", system),
        ("contract", contract_block),
        ("retrieved_bundle", bundle_block),
        ("inputs", inputs_block),
    ):
        seat_prompt_section(
            active_accountant,
            name=name,
            content=content,
            content_hash=_hash(content),
        )
    # v0.5.1 module_02: state seated via seat_state_section which
    # enforces the master spec's 15%-of-input_target cap.
    _state_section, effective_state_block = seat_state_section(
        active_accountant,
        content=state_block,
        content_hash=_hash(state_block),
        sink=active_sink,
    )

    emit_budget_declared(
        active_sink,
        {
            "function": PLAN_FUNCTION_NAME,
            "declaration": _declaration_payload(declaration),
            "narrowing_log": [],
            "source": "default",
        },
    )
    # v0.5.1 module_02: paired input_max + hard_ceiling gates
    # (Lens 1A CRITICAL A-1 wire-in).
    refuse_over_max(active_accountant, sink=active_sink)
    refuse_over_ceiling(active_accountant, sink=active_sink)

    prompt = assemble_prompt(
        system=system,
        contract=contract_block,
        state=effective_state_block,
        bundle=bundle_block,
        inputs=inputs_block,
    )
    response = provider.send(prompt, declaration)
    parsed = _parse_response(response)
    if not parsed.target_symbols:
        raise InfeasiblePlanError(
            "plan returned empty target_symbols — infeasible under the bundle",
            function=PLAN_FUNCTION_NAME,
            payload={"risk_level": parsed.risk_assessment.level.value},
        )
    return parsed


# ---------------------------------------------------------------------------
# Prompt section builders
# ---------------------------------------------------------------------------


def _contract_block() -> str:
    return (
        "Return one JSON object matching the plan schema. Do not wrap in markdown. "
        "Ensure load_manifest covers every symbol edit will read."
    )


def _state_block(work_order: WorkOrder, research_bundle: ResearchBundle) -> str:
    return (
        "work_order:\n"
        + to_json(work_order)
        + "\n\nresearch_bundle:\n"
        + to_json(research_bundle)
    )


def _bundle_block(mid_bundles: tuple[RetrievalBundle, ...]) -> str:
    if not mid_bundles:
        return "(no mid-invocation retrievals)"
    parts: list[str] = []
    for i, bundle in enumerate(mid_bundles):
        parts.append(f"### mid_retrieve[{i}] ({bundle.total_tokens} tokens)")
        for chunk in bundle.chunks:
            parts.append(
                f"- {chunk.file_path}::{chunk.symbol_name}: "
                f"{chunk.signature or chunk.body[:80]}"
            )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(response: str) -> ChangePlan:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ProviderContractError(
            f"plan response is not valid JSON: {exc}",
            function=PLAN_FUNCTION_NAME,
            payload={"response_excerpt": response[:200]},
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderContractError(
            "plan response must be a JSON object",
            function=PLAN_FUNCTION_NAME,
        )
    targets = tuple(
        _rehydrate_target(entry) for entry in payload.get("target_symbols", []) or []
    )
    manifest = tuple(
        _rehydrate_symbol_ref(entry) for entry in payload.get("load_manifest", []) or []
    )
    invariants = tuple(
        _rehydrate_invariant(entry) for entry in payload.get("invariants", []) or []
    )
    criteria = tuple(
        _rehydrate_criterion(entry)
        for entry in payload.get("verification_criteria", []) or []
    )
    risk = _rehydrate_risk(payload.get("risk_assessment") or {})
    iteration_bound_raw = payload.get("iteration_bound", 3)
    try:
        iteration_bound = int(iteration_bound_raw)
    except (TypeError, ValueError) as exc:
        raise ProviderContractError(
            f"plan response.iteration_bound must be an int; got {iteration_bound_raw!r}",
            function=PLAN_FUNCTION_NAME,
        ) from exc
    if iteration_bound < 1 or iteration_bound > 5:
        raise ProviderContractError(
            f"plan response.iteration_bound out of range 1..5: {iteration_bound}",
            function=PLAN_FUNCTION_NAME,
        )
    return ChangePlan(
        target_symbols=targets,
        load_manifest=manifest,
        invariants=invariants,
        verification_criteria=criteria,
        risk_assessment=risk,
        iteration_bound=iteration_bound,
        metadata=(("prompt_version", PLAN_PROMPT_VERSION),),
    )


def _rehydrate_target(entry: dict[str, Any]) -> TargetSymbol:
    return TargetSymbol(
        symbol=_rehydrate_symbol_ref(entry),
        action=str(entry.get("action", "modify")),
        notes=str(entry.get("notes", "")),
    )


def _rehydrate_symbol_ref(entry: dict[str, Any]) -> SymbolRef:
    return SymbolRef(
        name=str(entry.get("name", "")),
        file_path=str(entry.get("file_path", "")),
        symbol_id=int(entry.get("symbol_id", -1)),
        kind=str(entry.get("kind", "")),
    )


def _rehydrate_invariant(entry: dict[str, Any]) -> Invariant:
    try:
        kind = InvariantKind(str(entry.get("kind", "ast_grep")))
    except ValueError as exc:
        raise ProviderContractError(
            f"plan response.invariants.kind invalid: {exc}",
            function=PLAN_FUNCTION_NAME,
        ) from exc
    return Invariant(
        kind=kind,
        expression=str(entry.get("expression", "")),
        description=str(entry.get("description", "")),
    )


def _rehydrate_criterion(entry: dict[str, Any]) -> VerificationCriterion:
    payload_raw = entry.get("payload") or {}
    if not isinstance(payload_raw, dict):
        raise ProviderContractError(
            "plan response.verification_criteria.payload must be an object",
            function=PLAN_FUNCTION_NAME,
        )
    return VerificationCriterion(
        predicate_id=str(entry.get("predicate_id", "")),
        kind=str(entry.get("kind", "")),
        payload=tuple(sorted((str(k), str(v)) for k, v in payload_raw.items())),
    )


def _rehydrate_risk(entry: dict[str, Any]) -> RiskAssessment:
    if not isinstance(entry, dict):
        entry = {}
    try:
        level = RiskLevel(str(entry.get("level", "medium")))
    except ValueError as exc:
        raise ProviderContractError(
            f"plan response.risk_assessment.level invalid: {exc}",
            function=PLAN_FUNCTION_NAME,
        ) from exc
    blast = tuple(
        int(x)
        for x in entry.get("blast_radius_symbol_ids", []) or []
        if isinstance(x, int)
    )
    return RiskAssessment(
        level=level,
        rationale=str(entry.get("rationale", "")),
        blast_radius_symbol_ids=blast,
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
    "MAX_MID_INVOCATION_RETRIEVES",
    "MID_INVOCATION_RETRIEVE_BUDGET",
    "PLAN_FUNCTION_NAME",
    "PLAN_PROMPT_VERSION",
    "plan",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
