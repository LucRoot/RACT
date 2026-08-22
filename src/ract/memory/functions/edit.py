"""edit function — ChangePlan in, CandidateDiff out.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §edit.

Contract:

- Input: ChangePlan + IndexBundle.
- Retrieval: load actual code for symbols in ``plan.load_manifest``.
  FULL for ``target_symbols``. BODY_ONLY for symbols called by
  targets. SIGNATURE for wider neighborhood. Cascade downgrades on
  budget pressure; if targets alone exceed budget, raise
  :class:`BoundedContextError`.
- Output: :class:`~ract.memory.functions.contracts.CandidateDiff`
  under the v0.5.0 output discipline (unified diff format, AST +
  lazy-token validator, retry-on-parse-error up to twice).

Structured generation: v0.5.0 ships the post-generation validator
option (b). Grammar-constrained generation via Outlines defers to
v0.6 per master spec §Bounded scope.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant, WhitespaceTokenEstimator
from ract.memory.budget_registry import get as budget_get
from ract.memory.chunk import ChunkFormat, format_chunk
from ract.memory.events import EventSink, NullEventSink, emit_budget_declared
from ract.memory.functions.contracts import (
    CandidateDiff,
    ChangePlan,
    HunkSummary,
    to_json,
)
from ract.memory.functions.errors import (
    BoundedContextError,
    InvalidSyntaxError,
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
    RetrievalQuery,
    RetrievalStrategy,
    SymbolRef as RetrieveSymbolRef,
    retrieve,
)


EDIT_FUNCTION_NAME: str = "edit"
EDIT_PROMPT_VERSION: str = "v1"
MAX_PARSE_RETRIES: int = 2
"""Master spec §edit output discipline: retry-on-parse-error up to twice."""

# Forbidden tokens the lazy-content validator refuses. Master spec
# §edit output discipline: no TODO, no ellipsis bodies, no
# "leave X unchanged" prose.
_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "TODO",
    "FIXME",
    "XXX",
    "pass  # implement",
    "pass # implement",
    "raise NotImplementedError",
)

_ELLIPSIS_STATEMENT_RE = re.compile(r"^[+\- ]?\s*\.\.\.\s*$", re.MULTILINE)
_LAZY_PROSE_RE = re.compile(
    r"leave\s+\w+\s+unchanged|unchanged\s+region|rest\s+omitted|elided\s+for\s+brevity",
    re.IGNORECASE,
)

assert_prompt_shipped(EDIT_FUNCTION_NAME, EDIT_PROMPT_VERSION)


@dataclass
class EditValidationReport:
    """Result of the lazy-token + diff-shape validator.

    Populated on every :func:`edit` invocation; carried on the returned
    :class:`CandidateDiff.validator_notes` even when the diff passes,
    so a downstream reader can inspect how many retries were needed.
    """

    valid: bool
    reasons: tuple[str, ...]

    def to_notes(self) -> tuple[str, ...]:
        if self.valid:
            return ("diff passed validator",)
        return tuple(f"validator: {reason}" for reason in self.reasons)


def edit(
    change_plan: ChangePlan,
    indexes: IndexBundle,
    provider: MemoryFunctionProvider,
    *,
    accountant: BudgetAccountant | None = None,
    sink: EventSink | None = None,
) -> CandidateDiff:
    """Return a :class:`CandidateDiff` implementing ``change_plan``.

    Cascade:

    1. Load FULL for ``target_symbols``. If under budget, keep.
    2. If over budget, downgrade non-target load_manifest entries to
       SIGNATURE.
    3. If still over budget, downgrade non-target entries to
       BODY_ONLY (removes signatures, keeps bodies).
    4. If targets themselves exceed budget, raise
       :class:`BoundedContextError` (composition splits plan or
       escalates).
    """
    active_sink = sink or NullEventSink()
    declaration = budget_get(EDIT_FUNCTION_NAME)
    active_accountant = accountant or BudgetAccountant(declaration=declaration)

    load_block, assembled_tokens = _assemble_load_block(
        change_plan, indexes, declaration.input_target, sink=active_sink
    )

    system = load_prompt(EDIT_FUNCTION_NAME, EDIT_PROMPT_VERSION)
    contract_block = _contract_block()
    state_block = to_json(change_plan)
    inputs_block = "produce a unified diff implementing the ChangePlan."

    for name, content in (
        ("system_prompt", system),
        ("contract", contract_block),
        ("retrieved_bundle", load_block),
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
            "function": EDIT_FUNCTION_NAME,
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
        bundle=load_block,
        inputs=inputs_block,
    )

    validator_log: list[str] = []
    last_error: str = ""
    diff_text: str = ""
    hunks: tuple[HunkSummary, ...] = ()
    for attempt in range(MAX_PARSE_RETRIES + 1):
        response = provider.send(_retry_prompt(prompt, last_error), declaration)
        try:
            diff_text, hunks = _parse_response(response)
        except ProviderContractError as exc:
            last_error = str(exc)
            validator_log.append(f"attempt {attempt}: {last_error}")
            continue
        report = _validate_diff(diff_text)
        validator_log.append(f"attempt {attempt}: valid={report.valid}")
        validator_log.extend(f"attempt {attempt}: {r}" for r in report.reasons)
        if report.valid:
            return CandidateDiff(
                unified_diff=diff_text,
                hunks=hunks,
                assembled_input_tokens=assembled_tokens,
                output_tokens=WhitespaceTokenEstimator().estimate(diff_text),
                validator_notes=tuple(validator_log),
                metadata=(("prompt_version", EDIT_PROMPT_VERSION),),
            )
        last_error = "; ".join(report.reasons)
    raise InvalidSyntaxError(
        f"edit exhausted {MAX_PARSE_RETRIES + 1} attempts; last error: {last_error}",
        function=EDIT_FUNCTION_NAME,
        payload={"parse_error": last_error, "attempts": MAX_PARSE_RETRIES + 1},
    )


# ---------------------------------------------------------------------------
# Load cascade
# ---------------------------------------------------------------------------


def _assemble_load_block(
    change_plan: ChangePlan,
    indexes: IndexBundle,
    input_target: int,
    *,
    sink: EventSink,
) -> tuple[str, int]:
    """Return ``(load_block_text, assembled_token_count)`` for the edit prompt.

    Runs three cascade tiers:

    1. FULL for every load_manifest entry.
    2. SIGNATURE for non-target entries if step 1 busts budget.
    3. BODY_ONLY for non-target entries if step 2 still busts budget.

    Raises :class:`BoundedContextError` if the target-only set alone
    exceeds ``input_target``.
    """
    target_names = {t.symbol.name for t in change_plan.target_symbols}
    manifest_names = tuple(sorted({s.name for s in change_plan.load_manifest}))
    if not manifest_names:
        manifest_names = tuple(sorted(target_names))

    query = RetrievalQuery(
        symbol_names=manifest_names,
        keywords=(),
        graph_seeds=tuple(RetrieveSymbolRef(name=n) for n in target_names),
    )
    refs = indexes.to_index_refs()
    if not refs:
        # No indexes wired — return an empty load block and zero cost.
        return "(no indexes wired; edit runs against plan-only context)", 0

    estimator = WhitespaceTokenEstimator()

    def _render_at(
        default_format: ChunkFormat, non_target_format: ChunkFormat
    ) -> tuple[str, int]:
        bundle = retrieve(
            query,
            refs,
            budget=input_target,
            format=default_format,
            strategy=RetrievalStrategy.CORE_FIRST,
            sink=sink,
        )
        lines: list[str] = []
        total = 0
        for chunk in bundle.chunks:
            if chunk.symbol_name in target_names:
                rendered = chunk
            else:
                rendered = format_chunk(chunk, non_target_format)
            line = f"### {chunk.file_path}::{rendered.symbol_name}\n{rendered.body}"
            lines.append(line)
            total += estimator.estimate(line)
        return "\n\n".join(lines), total

    # Tier 1: FULL for everyone.
    text, cost = _render_at(ChunkFormat.FULL, ChunkFormat.FULL)
    if cost <= input_target:
        return text, cost

    # Tier 2: FULL for targets, SIGNATURE for non-targets.
    text, cost = _render_at(ChunkFormat.FULL, ChunkFormat.SIGNATURE)
    if cost <= input_target:
        return text, cost

    # Tier 3: FULL for targets, BODY_ONLY for non-targets.
    text, cost = _render_at(ChunkFormat.FULL, ChunkFormat.BODY_ONLY)
    if cost <= input_target:
        return text, cost

    # Tier 4: targets alone. If even targets bust budget, raise.
    target_only_query = RetrievalQuery(
        symbol_names=tuple(sorted(target_names)),
    )
    target_bundle = retrieve(
        target_only_query,
        refs,
        budget=input_target,
        format=ChunkFormat.FULL,
        strategy=RetrievalStrategy.CORE_FIRST,
        sink=sink,
    )
    target_cost = sum(estimator.estimate(c.body) for c in target_bundle.chunks)
    if target_cost > input_target:
        raise BoundedContextError(
            f"edit target symbols alone exceed input_target "
            f"({target_cost} > {input_target})",
            function=EDIT_FUNCTION_NAME,
            payload={
                "target_names": sorted(target_names),
                "target_cost": target_cost,
                "input_target": input_target,
            },
        )
    text_lines = [
        f"### {c.file_path}::{c.symbol_name}\n{c.body}" for c in target_bundle.chunks
    ]
    return "\n\n".join(text_lines), target_cost


# ---------------------------------------------------------------------------
# Retry prompt shaping
# ---------------------------------------------------------------------------


def _retry_prompt(base_prompt: str, last_error: str) -> str:
    if not last_error:
        return base_prompt
    retry_note = (
        "\n\n## Retry\nPrevious response failed validation: "
        f"{last_error}. Return a corrected JSON object matching the schema."
    )
    return base_prompt + retry_note


# ---------------------------------------------------------------------------
# Prompt section builders
# ---------------------------------------------------------------------------


def _contract_block() -> str:
    return (
        "Return one JSON object with keys unified_diff (string) and hunks "
        "(array). unified_diff must be a valid unified diff. Do not wrap "
        "in markdown."
    )


# ---------------------------------------------------------------------------
# Response parsing + validation
# ---------------------------------------------------------------------------


def _parse_response(response: str) -> tuple[str, tuple[HunkSummary, ...]]:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ProviderContractError(
            f"edit response is not valid JSON: {exc}",
            function=EDIT_FUNCTION_NAME,
            payload={"response_excerpt": response[:200]},
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderContractError(
            "edit response must be a JSON object",
            function=EDIT_FUNCTION_NAME,
        )
    diff_text = payload.get("unified_diff")
    if not isinstance(diff_text, str):
        raise ProviderContractError(
            "edit response.unified_diff must be a string",
            function=EDIT_FUNCTION_NAME,
        )
    hunks_raw = payload.get("hunks") or []
    if not isinstance(hunks_raw, list):
        raise ProviderContractError(
            "edit response.hunks must be a list",
            function=EDIT_FUNCTION_NAME,
        )
    hunks = tuple(_rehydrate_hunk(entry) for entry in hunks_raw)
    return diff_text, hunks


def _rehydrate_hunk(entry: dict[str, Any]) -> HunkSummary:
    if not isinstance(entry, dict):
        raise ProviderContractError(
            "edit response.hunks entry must be an object",
            function=EDIT_FUNCTION_NAME,
        )
    return HunkSummary(
        file_path=str(entry.get("file_path", "")),
        start_line=int(entry.get("start_line", 0)),
        end_line=int(entry.get("end_line", 0)),
        summary=str(entry.get("summary", "")),
    )


def _validate_diff(diff_text: str) -> EditValidationReport:
    """Validate ``diff_text`` against the v0.5.0 output discipline.

    Checks:

    1. Non-empty text.
    2. Has at least one hunk header (``@@``) unless the diff is a
       new-file / delete-file body (headed by ``+++`` / ``---``).
    3. No forbidden tokens (TODO / FIXME / etc.).
    4. No ellipsis-only statement lines.
    5. No lazy-prose sentences.
    """
    reasons: list[str] = []
    if not diff_text.strip():
        reasons.append("diff is empty")
    else:
        if "@@" not in diff_text and not any(
            marker in diff_text for marker in ("+++ ", "--- ")
        ):
            reasons.append("no hunk header (@@) or file marker present")
        for token in _FORBIDDEN_TOKENS:
            if token in diff_text:
                reasons.append(f"contains forbidden token {token!r}")
        if _ELLIPSIS_STATEMENT_RE.search(diff_text):
            reasons.append("contains standalone ... statement body")
        if _LAZY_PROSE_RE.search(diff_text):
            reasons.append("contains lazy-prose placeholder")
    return EditValidationReport(valid=not reasons, reasons=tuple(reasons))


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
    "EDIT_FUNCTION_NAME",
    "EDIT_PROMPT_VERSION",
    "EditValidationReport",
    "MAX_PARSE_RETRIES",
    "edit",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
