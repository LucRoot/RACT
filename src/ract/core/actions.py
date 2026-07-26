"""Typed action union — the closed vocabulary the model may propose.

SUBSTRATE spec §5 (Substrate Layer 4: Model Conformance) and §11 signals
7 and 8. In v0.3 the plan schema was validated at the plan-schema level
only; the *actions* a model could propose were open-typed. This module
closes that surface: every action is a member of a **closed Pydantic
discriminated union**. Adding a new action kind requires an ADR
(ADR-0014). The friction is the feature.

Reference sources:

- Pydantic v2 discriminated unions:
  ``https://docs.pydantic.dev/latest/concepts/unions/``.
- OpenAI Structured Outputs public documentation (the response-shape API
  the schema converter serialises into).
- Anthropic tool-use public documentation (the tool-shape API the schema
  converter serialises into).
- Aider Polyglot and OpenHands V1 SDK — the eval-first shape (SUBSTRATE
  §5.2) that motivates the closed union: behavioural variance is only
  observable when the vocabulary is invariant.

The union is deliberately narrow. Every action's payload is
constructible from a plain JSON dict; every discriminator is a
``Literal[str]`` on the ``kind`` field. ``model_config = ConfigDict(
extra="forbid", frozen=True)`` so a stray field never grants an
unmeant capability.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Strict base
# ---------------------------------------------------------------------------


class _ActionBase(BaseModel):
    """Common config for every action payload.

    ``extra="forbid"`` refuses unknown fields at construction; ``frozen``
    prevents post-hoc mutation so a validated action cannot be widened
    after it has crossed the validator.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Path-traversal guard (shared)
# ---------------------------------------------------------------------------


_TRAVERSAL_MARKERS: tuple[str, ...] = (
    "..",
    "\x00",
)


def _reject_path_traversal(path: str) -> str:
    """Refuse absolute paths and path-traversal fragments.

    The workspace-root guarantee is that every write path is *relative
    to the workspace root*. Absolute paths are refused because they
    escape the workspace at construction; ``..`` and NUL are refused
    because they escape at resolution time. This is a construction-time
    guard; the sandbox (module_03) is the runtime belt.
    """
    if not path:
        raise ValueError("path must be a non-empty string")
    # Windows-style drive letters (``C:``) as well as posix ``/``.
    if path.startswith(("/", "\\")):
        raise ValueError(
            f"path {path!r} is absolute; workspace-relative paths only"
        )
    if len(path) >= 2 and path[1] == ":":
        raise ValueError(
            f"path {path!r} carries a drive letter; workspace-relative paths only"
        )
    for marker in _TRAVERSAL_MARKERS:
        if marker in path:
            raise ValueError(
                f"path {path!r} contains traversal marker {marker!r}"
            )
    return path


# ---------------------------------------------------------------------------
# Individual actions
# ---------------------------------------------------------------------------


class WriteFileAction(_ActionBase):
    """Write ``content`` to the workspace-relative ``path``.

    ``rationale`` names the assumption id (from module_01's
    ``AssumptionRegistry``) that this write discharges; the model is
    obliged to state, in the action, what claim about the environment
    this write is meant to make true.
    """

    kind: Literal["write_file"] = "write_file"
    path: str
    content: str
    rationale: str
    parent_rootknots: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _reject_path_traversal(value)


class RunTestsAction(_ActionBase):
    """Run tests against the current worktree.

    ``selector`` is a pytest ``-k`` expression or a path fragment;
    ``timeout_seconds`` is capped at 600 so a runaway selector cannot
    burn the run's wall-time budget.
    """

    kind: Literal["run_tests"] = "run_tests"
    selector: str
    timeout_seconds: int = Field(default=120, ge=1, le=600)


class ReadFileAction(_ActionBase):
    """Read a workspace-relative file into the loop's context."""

    kind: Literal["read_file"] = "read_file"
    path: str
    rationale: str = ""

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _reject_path_traversal(value)


class SearchWorkspaceAction(_ActionBase):
    """Search the workspace with a query and optional glob."""

    kind: Literal["search_workspace"] = "search_workspace"
    query: str
    glob: str = ""
    max_matches: int = Field(default=50, ge=1, le=1000)


class ProposePredicateAction(_ActionBase):
    """Propose an ``AcceptancePredicate`` to add to the frozen suite.

    Adding to the suite mid-run is a handshake-gated operation
    (module_01 + module_02). The action carries the predicate spec plus
    the rationale for the addition; the handshake registry decides
    whether the operator accepts.
    """

    kind: Literal["propose_predicate"] = "propose_predicate"
    predicate_kind: Literal["test", "type", "property", "invariant", "artifact"]
    invocation: dict[str, str | int | float | bool]
    rationale: str
    required: bool = True


class DeleteFileAction(_ActionBase):
    """Delete a workspace-relative path.

    Routed through module_06's Fence pre-delete gate. The action itself
    is only a *proposal*; the Fence decides whether the delete lands
    (a chestertons-fence audit runs before the sandbox tears the file
    down).
    """

    kind: Literal["delete_file"] = "delete_file"
    path: str
    rationale: str

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _reject_path_traversal(value)


class RequestHandshakeAction(_ActionBase):
    """Ask the operator to widen the manifest or approve a blocked step.

    ``handshake_kind`` names which widen the model wants (``yolo``,
    ``tier2_network``, ``suite_extension``). ``payload`` is a
    handshake-shape-specific dict the ``HandshakeRegistry`` interprets.
    """

    kind: Literal["request_handshake"] = "request_handshake"
    handshake_kind: str
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    rationale: str = ""


class EmitEventAction(_ActionBase):
    """Emit a structured event through the event log (module_05).

    Until module_05 wires the log, the event goes to a null sink (same
    pattern as ``ract.security.sandbox.emit``). The action still
    validates and still crosses the validator boundary; only the
    downstream sink is deferred.

    ``event_kind`` names the event; ``payload`` is a small JSON dict
    the log interprets. ``manifest_digest_hex`` is optional; when set,
    the event carries the manifest hex-digest so module_05's log joins
    events to the run's ``CapabilityManifest`` (see
    ``ract.security.manifest.ManifestDigest``).
    """

    kind: Literal["emit_event"] = "emit_event"
    event_kind: str
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    manifest_digest_hex: str = ""


# ---------------------------------------------------------------------------
# Closed union — discriminated by ``kind``
# ---------------------------------------------------------------------------


ActionKind = Literal[
    "write_file",
    "run_tests",
    "read_file",
    "search_workspace",
    "propose_predicate",
    "delete_file",
    "request_handshake",
    "emit_event",
]

# Every legal action kind; used by tests and by the schema converters
# to enumerate the union without reflecting into Pydantic internals.
LEGAL_ACTION_KINDS: frozenset[str] = frozenset(
    (
        "write_file",
        "run_tests",
        "read_file",
        "search_workspace",
        "propose_predicate",
        "delete_file",
        "request_handshake",
        "emit_event",
    )
)


# Order matters here only for the schema converters' anyOf ordering; the
# discriminator makes the parse deterministic regardless.
Action = Annotated[
    Union[
        WriteFileAction,
        RunTestsAction,
        ReadFileAction,
        SearchWorkspaceAction,
        ProposePredicateAction,
        DeleteFileAction,
        RequestHandshakeAction,
        EmitEventAction,
    ],
    Field(discriminator="kind"),
]


# Concrete tuple form used by ``providers/schema.py`` and tests that need
# to iterate the union members without touching Pydantic internals.
ACTION_MEMBERS: tuple[type[_ActionBase], ...] = (
    WriteFileAction,
    RunTestsAction,
    ReadFileAction,
    SearchWorkspaceAction,
    ProposePredicateAction,
    DeleteFileAction,
    RequestHandshakeAction,
    EmitEventAction,
)


# ---------------------------------------------------------------------------
# PlannedStep
# ---------------------------------------------------------------------------


class PlannedStep(BaseModel):
    """One planned step: a step id, a typed action, and its dependencies.

    ``postconditions`` are references (by hex string) to
    ``AcceptancePredicate.id`` values from module_01; the step claims
    that after it commits, those predicates will evaluate ``ok=True``.
    Validation of the reference happens at the loop layer (the ids must
    exist in the frozen ``AcceptanceSuite``) — not here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    action: Action
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    postconditions: tuple[str, ...] = Field(default_factory=tuple)


__all__ = [
    "ACTION_MEMBERS",
    "Action",
    "ActionKind",
    "DeleteFileAction",
    "EmitEventAction",
    "LEGAL_ACTION_KINDS",
    "PlannedStep",
    "ProposePredicateAction",
    "ReadFileAction",
    "RequestHandshakeAction",
    "RunTestsAction",
    "SearchWorkspaceAction",
    "WriteFileAction",
]


# RACT 0.4.0
