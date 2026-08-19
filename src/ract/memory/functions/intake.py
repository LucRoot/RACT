"""intake function — user request in, WorkOrder out.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §intake.

Contract:

- Input: user request text plus optional repo context.
- Retrieval: last 10 commits (``git log --oneline -n 10``), README
  top section, any explicitly mentioned files' signatures via the
  symbol index.
- No code bodies. Budget ceiling 4k (see budget_defaults.yaml).
- Output: a :class:`~ract.memory.functions.contracts.WorkOrder`.

The function is transport-agnostic: it composes the assembled
prompt, refuses over-ceiling, and delegates the model call to a
:class:`~ract.memory.functions.provider_adapter.MemoryFunctionProvider`.
Tests supply a mock; module_09 wires the real provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant
from ract.memory.budget_registry import get as budget_get
from ract.memory.events import EventSink, NullEventSink, emit_budget_declared
from ract.memory.functions.contracts import (
    RequestType,
    ScopeHints,
    WorkOrder,
)
from ract.memory.functions.errors import ProviderContractError
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
from ract.memory.symbol_index import SymbolIndex


INTAKE_FUNCTION_NAME: str = "intake"
INTAKE_PROMPT_VERSION: str = "v1"

# Fail-fast on missing prompt file at import time (Second Pass Q4).
assert_prompt_shipped(INTAKE_FUNCTION_NAME, INTAKE_PROMPT_VERSION)


@dataclass
class IntakeContext:
    """Optional context supplied alongside the user request.

    Fields:

    - ``repo_root`` — repository root; used for git log + README
      reads.
    - ``symbol_index`` — module_02 index; used to fetch signatures
      for symbols the user named.
    - ``current_branch`` — the git branch under work; passed to the
      prompt for context.
    - ``open_file`` — file the user has open in an editor, if any.
    - ``selected_code`` — highlighted code block in the editor.
    """

    repo_root: Path
    symbol_index: SymbolIndex | None = None
    current_branch: str = ""
    open_file: str = ""
    selected_code: str = ""


def intake(
    request: str,
    context: IntakeContext,
    provider: MemoryFunctionProvider,
    *,
    accountant: BudgetAccountant | None = None,
    sink: EventSink | None = None,
) -> WorkOrder:
    """Normalise ``request`` into a :class:`WorkOrder`.

    Sequence:

    1. Load the intake budget from :func:`ract.memory.budget_registry.get`.
    2. Collect the recent-commits summary, README top section, and
       explicit-symbol signatures. No code bodies.
    3. Assemble the five-section prompt via
       :func:`~ract.memory.functions.provider_adapter.assemble_prompt`.
    4. Seat every section on a :class:`BudgetAccountant`; refuse if
       the total exceeds ``hard_ceiling``.
    5. Delegate the model call to ``provider.send(prompt, declaration)``.
    6. Parse the response as the JSON contract in
       ``prompts/intake_v1.md``.

    On ambiguity the returned WorkOrder carries a non-empty
    ``ambiguity_flags`` tuple; the caller (composition layer) routes
    to human clarification per Second Pass Q2.
    """
    active_sink = sink or NullEventSink()
    declaration = budget_get(INTAKE_FUNCTION_NAME)
    active_accountant = accountant or BudgetAccountant(declaration=declaration)

    system = load_prompt(INTAKE_FUNCTION_NAME, INTAKE_PROMPT_VERSION)
    contract_block = _intake_contract_block()
    state_block = _intake_state_block(context)
    bundle_block = _intake_bundle_block(request, context)
    inputs_block = _intake_inputs_block(request)

    seat_prompt_section(
        active_accountant,
        name="system_prompt",
        content=system,
        content_hash=_hash(system),
    )
    seat_prompt_section(
        active_accountant,
        name="contract",
        content=contract_block,
        content_hash=_hash(contract_block),
    )
    seat_prompt_section(
        active_accountant,
        name="state",
        content=state_block,
        content_hash=_hash(state_block),
    )
    seat_prompt_section(
        active_accountant,
        name="retrieved_bundle",
        content=bundle_block,
        content_hash=_hash(bundle_block),
    )
    seat_prompt_section(
        active_accountant,
        name="inputs",
        content=inputs_block,
        content_hash=_hash(inputs_block),
    )

    emit_budget_declared(
        active_sink,
        {
            "function": INTAKE_FUNCTION_NAME,
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
    return _parse_response(response)


# ---------------------------------------------------------------------------
# Prompt section builders
# ---------------------------------------------------------------------------


def _intake_contract_block() -> str:
    return (
        "Return one JSON object matching the schema in the system prompt. "
        "Do not wrap in markdown."
    )


def _intake_state_block(context: IntakeContext) -> str:
    lines = [f"repo_root: {context.repo_root}"]
    if context.current_branch:
        lines.append(f"current_branch: {context.current_branch}")
    if context.open_file:
        lines.append(f"open_file: {context.open_file}")
    if context.selected_code:
        lines.append("selected_code: (present, kept out of the assembled prompt)")
    return "\n".join(lines) if lines else "(no session state)"


def _intake_bundle_block(request: str, context: IntakeContext) -> str:
    parts: list[str] = []
    commits = _git_recent_commits(context.repo_root)
    if commits:
        parts.append("### recent_commits\n" + "\n".join(commits))
    readme = _readme_top(context.repo_root)
    if readme:
        parts.append("### readme_head\n" + readme)
    signatures = _mentioned_signatures(request, context)
    if signatures:
        parts.append("### mentioned_signatures\n" + "\n".join(signatures))
    return "\n\n".join(parts) if parts else "(no retrieval material)"


def _intake_inputs_block(request: str) -> str:
    return f"request: {request}"


# ---------------------------------------------------------------------------
# Retrieval helpers (no code bodies)
# ---------------------------------------------------------------------------


def _git_recent_commits(repo_root: Path) -> list[str]:
    """Return the last 10 commits as one-line summaries, or []."""
    if not repo_root.is_dir():
        return []
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "log", "--oneline", "-n", "10"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _readme_top(repo_root: Path, max_chars: int = 800) -> str:
    """Return the head of ``README.md`` (or ``README``) up to ``max_chars``."""
    for name in ("README.md", "README.MD", "README", "README.rst"):
        candidate = repo_root / name
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
            return text[:max_chars]
    return ""


_SYMBOL_MENTION_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9_]{2,})\b|\b([a-z_][a-z0-9_]{2,})\b"
)


def _mentioned_signatures(request: str, context: IntakeContext) -> list[str]:
    """Return signatures for symbols the user named explicitly.

    Explicit-mention heuristic: any word that looks like an identifier
    (matches ``_SYMBOL_MENTION_RE``) is looked up in the symbol
    index. Missing names silently skip; found names emit
    ``"file_path::signature"``. No bodies are read.
    """
    if context.symbol_index is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _SYMBOL_MENTION_RE.finditer(request):
        name = match.group(1) or match.group(2)
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            rows = context.symbol_index.find_by_name(name)
        except Exception:
            continue
        for row in rows[:3]:
            signature = row.signature or f"(no signature: {name})"
            out.append(f"{row.file_path}::{signature}")
        if len(out) >= 20:
            break
    return out


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(response: str) -> WorkOrder:
    """Parse ``response`` as the intake JSON contract into a WorkOrder."""
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ProviderContractError(
            f"intake response is not valid JSON: {exc}",
            function=INTAKE_FUNCTION_NAME,
            payload={"response_excerpt": response[:200]},
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderContractError(
            f"intake response must be a JSON object; got {type(payload).__name__}",
            function=INTAKE_FUNCTION_NAME,
        )
    try:
        request_type = RequestType(payload.get("request_type", "other"))
    except ValueError as exc:
        raise ProviderContractError(
            f"intake response.request_type invalid: {exc}",
            function=INTAKE_FUNCTION_NAME,
        ) from exc
    hints_raw = payload.get("scope_hints") or {}
    if not isinstance(hints_raw, dict):
        raise ProviderContractError(
            "intake response.scope_hints must be an object",
            function=INTAKE_FUNCTION_NAME,
        )
    scope = ScopeHints(
        mentioned_symbols=_as_tuple(hints_raw.get("mentioned_symbols")),
        mentioned_files=_as_tuple(hints_raw.get("mentioned_files")),
        mentioned_directories=_as_tuple(hints_raw.get("mentioned_directories")),
        keywords=_as_tuple(hints_raw.get("keywords")),
        exclude_paths=_as_tuple(hints_raw.get("exclude_paths")),
    )
    priority_raw = payload.get("priority_markers") or {}
    if not isinstance(priority_raw, dict):
        raise ProviderContractError(
            "intake response.priority_markers must be an object",
            function=INTAKE_FUNCTION_NAME,
        )
    return WorkOrder(
        request_type=request_type,
        scope_hints=scope,
        success_criteria=_as_tuple(payload.get("success_criteria")),
        constraints=_as_tuple(payload.get("constraints")),
        priority_markers=tuple(
            sorted((str(k), str(v)) for k, v in priority_raw.items())
        ),
        ambiguity_flags=_as_tuple(payload.get("ambiguity_flags")),
        metadata=(("prompt_version", INTAKE_PROMPT_VERSION),),
    )


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProviderContractError(
            f"expected list, got {type(value).__name__}",
            function=INTAKE_FUNCTION_NAME,
        )
    return tuple(str(item) for item in value)


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
    "INTAKE_FUNCTION_NAME",
    "INTAKE_PROMPT_VERSION",
    "IntakeContext",
    "intake",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
