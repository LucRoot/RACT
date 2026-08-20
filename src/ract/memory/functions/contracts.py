"""Shared output contracts for the four v0.5.0 memory-discipline functions.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Function
contracts. Every function in this package returns a frozen dataclass
declared here. Each dataclass round-trips through canonical JSON so
the composition layer can persist it under
``evals/runs/<run_id>/`` between steps.

Design notes:

- Every dataclass is ``frozen=True`` so a downstream reader cannot
  mutate a shared record. A mutation attempt raises
  :class:`dataclasses.FrozenInstanceError`.
- Every field type is either a primitive, an ``enum.Enum``, a nested
  frozen dataclass, or a ``tuple`` of the above. No mutable
  containers on the surface (dicts appear only in
  ``priority_markers`` where the key/value shape is genuinely open;
  serialisation copies the dict on read).
- :func:`to_json` and :func:`from_json` handle canonical
  serialisation. Round-trip is the invariant a caller relies on when
  persisting to disk between :class:`SessionMemory` writes.

Lateral Chain branches folded here:

- Branch A (provider-adapter mismatch): the contracts are transport-
  agnostic. The provider adapter at
  :mod:`ract.memory.functions.provider_adapter` composes each
  contract into the model prompt.
- Branch C (prompt versioning): the contracts do not carry a prompt
  version; the version lives in the function module as a constant
  (``INTAKE_PROMPT_VERSION`` etc.) and appears in the ``metadata``
  block of each contract.
- Branch E (plan-edit recursion bound): :class:`ChangePlan` carries
  ``iteration_bound: int`` with a default of 3; a runner that would
  loop more than that must escalate.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from ract.canonical import dumps_jcs


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------


class RequestType(enum.Enum):
    """Coarse-grained request classification, populated by intake.

    Every playbook (module_07) maps to one or more values here.
    Unknown user intents fall to :attr:`OTHER` and surface with
    ``ambiguity_flags`` set.
    """

    REFACTOR = "refactor"
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    UNIT_TEST = "unit_test"
    DOC = "doc"
    OTHER = "other"


class RiskLevel(enum.Enum):
    """Symbol-level risk classification used inside ChangePlan."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvariantKind(enum.Enum):
    """Invariant category used in ChangePlan.

    Master spec lists two families: ``ast_grep`` and ``test_name``.
    Additional families defer to v0.6.
    """

    AST_GREP = "ast_grep"
    TEST_NAME = "test_name"
    LINT_RULE = "lint_rule"


# ---------------------------------------------------------------------------
# Shared value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeHints:
    """Coarse locators inside a WorkOrder that narrow the research pass.

    ``mentioned_symbols`` — symbol names the user named verbatim.
    ``mentioned_files`` — file paths the user named verbatim.
    ``mentioned_directories`` — directories the user pointed at.
    ``keywords`` — free-form terms extracted from the request.
    ``exclude_paths`` — path prefixes to keep out of research.
    """

    mentioned_symbols: tuple[str, ...] = field(default_factory=tuple)
    mentioned_files: tuple[str, ...] = field(default_factory=tuple)
    mentioned_directories: tuple[str, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    exclude_paths: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SymbolRef:
    """Reference to a symbol by name plus (optionally) resolved id.

    The ``symbol_id`` is populated when research resolved the name
    against the module_02 symbol index. Consumers that only need the
    name treat ``symbol_id == -1`` as "unresolved".
    """

    name: str
    file_path: str = ""
    symbol_id: int = -1
    kind: str = ""


@dataclass(frozen=True)
class SymbolWithRationale:
    """A relevant symbol plus a one-line rationale for its inclusion.

    Research emits these so plan can weight symbols by rationale
    without re-reading the retrieval bundle.
    """

    symbol: SymbolRef
    rationale: str


@dataclass(frozen=True)
class SignatureRow:
    """One neighbor's signature for the call_neighborhood block."""

    symbol: SymbolRef
    signature: str
    direction: str  # "caller" | "callee"


@dataclass(frozen=True)
class CommitRef:
    """A commit referenced by research from git log grep."""

    sha: str
    subject: str
    files_touched: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetSymbol:
    """A symbol the edit function will modify.

    ``action`` is the intended change: ``modify`` / ``add`` / ``remove``
    / ``rename``. Composition layer reads this to route split-plan
    decisions.
    """

    symbol: SymbolRef
    action: str
    notes: str = ""


@dataclass(frozen=True)
class Invariant:
    """A property the edit must preserve.

    ``kind`` is one of :class:`InvariantKind`. ``expression`` carries
    the ast-grep query, test name, or lint rule identifier. The
    module_09 wiring compiles invariants into
    :class:`~ract.core.predicate.AcceptancePredicate` values.
    """

    kind: InvariantKind
    expression: str
    description: str = ""


@dataclass(frozen=True)
class VerificationCriterion:
    """A criterion the plan asks module_09 to compile into an
    :class:`~ract.core.predicate.AcceptancePredicate`.

    ``predicate_id`` is the id downstream code reads. ``kind`` is the
    predicate family (``test_passes`` / ``no_regression`` /
    ``lint_clean`` / ``diff_bounded``). ``payload`` is the family-
    specific data (test name for ``test_passes``; touched-files list
    for ``diff_bounded``).
    """

    predicate_id: str
    kind: str
    payload: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RiskAssessment:
    """Plan-emitted risk summary.

    ``level`` is the coarse classification; ``rationale`` names the
    concrete reason; ``blast_radius_symbol_ids`` lists symbols the
    change is expected to touch beyond the target list.
    """

    level: RiskLevel
    rationale: str
    blast_radius_symbol_ids: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HunkSummary:
    """One hunk in a :class:`CandidateDiff`.

    ``file_path`` is the file the hunk edits. ``start_line`` /
    ``end_line`` name the pre-image range. ``summary`` is a one-line
    human-readable note the edit function generates alongside the
    diff body.
    """

    file_path: str
    start_line: int
    end_line: int
    summary: str


# ---------------------------------------------------------------------------
# The four contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkOrder:
    """Output of :func:`~ract.memory.functions.intake.intake`.

    Master spec §intake. ``request_type`` classifies the intent;
    ``scope_hints`` narrows the research pass; ``success_criteria``
    lists testable conditions from the user text; ``constraints``
    lists what the change must not do; ``priority_markers`` carries
    open key/value pairs (e.g. ``{"urgency": "release_blocker"}``);
    ``ambiguity_flags`` is non-empty when intake could not confidently
    classify — composition routes to human clarification per Second
    Pass Q2.
    """

    request_type: RequestType
    scope_hints: ScopeHints
    success_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    priority_markers: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResearchBundle:
    """Output of :func:`~ract.memory.functions.research.research`.

    Master spec §research. Every relevant symbol carries a one-line
    rationale for its inclusion; the call_neighborhood is one hop of
    callers + callees as signatures; ``architectural_context`` is a
    prose paragraph; ``similar_prior_work`` names commit history
    matches for regression proximity; ``risk_zones`` names symbols
    the plan should treat conservatively (high blast radius, unclear
    ownership, missing tests).
    """

    relevant_symbols: tuple[SymbolWithRationale, ...]
    call_neighborhood: tuple[SignatureRow, ...]
    architectural_context: str
    similar_prior_work: tuple[CommitRef, ...] = field(default_factory=tuple)
    risk_zones: tuple[SymbolRef, ...] = field(default_factory=tuple)
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChangePlan:
    """Output of :func:`~ract.memory.functions.plan.plan`.

    Master spec §plan. ``target_symbols`` is the closed edit set;
    ``load_manifest`` names every symbol edit must read (targets +
    referenced-but-unmodified); ``invariants`` are ast-grep or
    test-name queries the edit must preserve; ``verification_criteria``
    compile into :class:`~ract.core.predicate.AcceptancePredicate`
    values; ``risk_assessment`` is the plan-side risk summary;
    ``iteration_bound`` caps the plan-edit outer loop (default 3,
    Lateral Chain E).
    """

    target_symbols: tuple[TargetSymbol, ...]
    load_manifest: tuple[SymbolRef, ...]
    invariants: tuple[Invariant, ...]
    verification_criteria: tuple[VerificationCriterion, ...]
    risk_assessment: RiskAssessment
    iteration_bound: int = 3
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateDiff:
    """Output of :func:`~ract.memory.functions.edit.edit`.

    Master spec §edit. ``unified_diff`` is the full patch text;
    ``hunks`` is one summary per hunk; ``assembled_input_tokens`` is
    the assembled context cost recorded before the model call;
    ``output_tokens`` is the whitespace-estimated cost of the diff.
    ``validator_notes`` records the diff-validator's observations
    (empty on a first-pass valid diff; carries the retry log on
    accepted-after-retry outputs).
    """

    unified_diff: str
    hunks: tuple[HunkSummary, ...]
    assembled_input_tokens: int
    output_tokens: int
    validator_notes: tuple[str, ...] = field(default_factory=tuple)
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Canonical JSON round-trip
# ---------------------------------------------------------------------------


_CONTRACT_TYPES: dict[str, type] = {
    "WorkOrder": WorkOrder,
    "ResearchBundle": ResearchBundle,
    "ChangePlan": ChangePlan,
    "CandidateDiff": CandidateDiff,
    "ScopeHints": ScopeHints,
    "SymbolRef": SymbolRef,
    "SymbolWithRationale": SymbolWithRationale,
    "SignatureRow": SignatureRow,
    "CommitRef": CommitRef,
    "TargetSymbol": TargetSymbol,
    "Invariant": Invariant,
    "VerificationCriterion": VerificationCriterion,
    "RiskAssessment": RiskAssessment,
    "HunkSummary": HunkSummary,
}

_ENUM_TYPES: dict[str, type[enum.Enum]] = {
    "RequestType": RequestType,
    "RiskLevel": RiskLevel,
    "InvariantKind": InvariantKind,
}


def _to_primitive(value: Any) -> Any:
    """Return a JSON-primitive projection of ``value``.

    Recurses through nested dataclasses, tuples, enums, and dicts.
    """
    if is_dataclass(value) and not isinstance(value, type):
        payload: dict[str, Any] = {"__type__": type(value).__name__}
        for f in fields(value):
            payload[f.name] = _to_primitive(getattr(value, f.name))
        return payload
    if isinstance(value, enum.Enum):
        return {"__enum__": type(value).__name__, "value": value.value}
    if isinstance(value, tuple):
        return [_to_primitive(item) for item in value]
    if isinstance(value, list):
        return [_to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_primitive(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"cannot serialise value of type {type(value).__name__}")


def _from_primitive(value: Any) -> Any:
    """Inverse of :func:`_to_primitive`."""
    if isinstance(value, dict) and "__type__" in value:
        cls = _CONTRACT_TYPES.get(value["__type__"])
        if cls is None:
            raise ValueError(f"unknown contract type {value['__type__']!r}")
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            raw = value.get(f.name)
            kwargs[f.name] = _reconstruct_field(f.type, raw)
        return cls(**kwargs)
    if isinstance(value, dict) and "__enum__" in value:
        enum_cls = _ENUM_TYPES.get(value["__enum__"])
        if enum_cls is None:
            raise ValueError(f"unknown enum type {value['__enum__']!r}")
        return enum_cls(value["value"])
    if isinstance(value, list):
        return tuple(_from_primitive(item) for item in value)
    return value


def _reconstruct_field(type_hint: Any, raw: Any) -> Any:
    """Rebuild ``raw`` as the declared field type.

    We do not resolve the type hint via ``typing.get_type_hints`` here
    (that requires a live globals map); we recurse structurally on
    the primitive form. Tuple-of-tuples stays as tuple, tuple-of-
    dataclass rehydrates each element.
    """
    if isinstance(raw, list):
        return tuple(_from_primitive(item) for item in raw)
    return _from_primitive(raw)


def to_json(contract: Any) -> str:
    """Return a canonical JSON string for ``contract``.

    Keys sorted; no whitespace. Byte-stable across Python versions.
    """
    payload = _to_primitive(contract)
    # v0.5.1 module_03: RFC 8785 JCS canonical bytes.
    return dumps_jcs(payload).decode("utf-8")


def from_json(text: str) -> Any:
    """Rehydrate a contract from :func:`to_json` output."""
    return _from_primitive(json.loads(text))


__all__ = [
    "CandidateDiff",
    "ChangePlan",
    "CommitRef",
    "HunkSummary",
    "Invariant",
    "InvariantKind",
    "RequestType",
    "ResearchBundle",
    "RiskAssessment",
    "RiskLevel",
    "ScopeHints",
    "SignatureRow",
    "SymbolRef",
    "SymbolWithRationale",
    "TargetSymbol",
    "VerificationCriterion",
    "WorkOrder",
    "from_json",
    "to_json",
]


from ract.core.module_identity import _module_knot, register_module_knot  # noqa: E402

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
