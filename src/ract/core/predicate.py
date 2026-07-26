"""Compiled acceptance predicates — the environment's exit condition.

SUBSTRATE spec §2 (Substrate Layer 1: Compiled Acceptance Predicates) and
§11 signals 1 and 2: an intent compiles to an ``AcceptanceSuite`` before the
loop enters step one. T1 (Completion) reads the suite; no model opinion
terminates the loop.

The design borrows the workflow-plus-activities split from the Temporal
durable-execution model: workflow code describes what "done" means; activities
are recorded facts. See ``https://docs.temporal.io/``. Canonical serialization
follows JSON Schema Draft 2020-12 conventions (``https://json-schema.org/``).

See ``docs/ADRs/ADR-0010-acceptance-predicates.md`` for the design rationale
and rejected alternatives.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Union

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


PredicateKind = Literal["test", "type", "property", "invariant", "artifact"]

# Canonical form for the compiled suite. Reader dispatches on this value; an
# unknown value halts, per the same policy as ADR-0008 (`ract.yaml`
# versioning).
CANONICAL_COMPILER_VERSION: str = "0.4.0"
_KNOWN_COMPILER_VERSIONS: frozenset[str] = frozenset({"0.4.0"})


# ---------------------------------------------------------------------------
# Invocations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PytestInvocation:
    """Verify by running a pytest selector against a snapshot."""

    selector: str
    timeout_seconds: int = 60
    kind: ClassVar[PredicateKind] = "test"

    def to_canonical(self) -> dict[str, Any]:
        return {
            "type": "pytest",
            "selector": self.selector,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class MypyInvocation:
    """Verify by running mypy against a target."""

    target: str
    strict: bool = True
    kind: ClassVar[PredicateKind] = "type"

    def to_canonical(self) -> dict[str, Any]:
        return {"type": "mypy", "target": self.target, "strict": self.strict}


@dataclass(frozen=True)
class HypothesisInvocation:
    """Verify via a Hypothesis property check."""

    target: str
    max_examples: int = 100
    kind: ClassVar[PredicateKind] = "property"

    def to_canonical(self) -> dict[str, Any]:
        return {
            "type": "hypothesis",
            "target": self.target,
            "max_examples": self.max_examples,
        }


@dataclass(frozen=True)
class AssertionInvocation:
    """Verify by invoking a callable that inspects a ``WorkspaceSnapshot``.

    ``callable_ref`` is a dotted import path (``package.module:function``
    or ``package.module.function``). The callable takes a snapshot and
    returns a ``bool``.
    """

    callable_ref: str
    kind: ClassVar[PredicateKind] = "invariant"

    def to_canonical(self) -> dict[str, Any]:
        return {"type": "assertion", "callable_ref": self.callable_ref}


@dataclass(frozen=True)
class ArtifactInvocation:
    """Verify by checking that a file exists (optionally with a Rootknot sidecar)."""

    path: str
    must_have_rootknot: bool = False
    kind: ClassVar[PredicateKind] = "artifact"

    def to_canonical(self) -> dict[str, Any]:
        return {
            "type": "artifact",
            "path": self.path,
            "must_have_rootknot": self.must_have_rootknot,
        }


PredicateInvocation = Union[
    PytestInvocation,
    MypyInvocation,
    HypothesisInvocation,
    AssertionInvocation,
    ArtifactInvocation,
]


# ---------------------------------------------------------------------------
# Results & predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PredicateResult:
    """Outcome of evaluating one predicate against a snapshot."""

    ok: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    duration_ns: int = 0


def new_predicate_id() -> bytes:
    """Return a fresh 16-byte identifier for a predicate."""
    return uuid.uuid4().bytes


def new_intent_id() -> bytes:
    """Return a fresh 16-byte identifier for an intent."""
    return uuid.uuid4().bytes


@dataclass(frozen=True)
class AcceptancePredicate:
    """A single externally-verifiable claim about a workspace snapshot."""

    id: bytes
    kind: PredicateKind
    invocation: PredicateInvocation
    required: bool = True
    depends_on: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        if len(self.id) != 16:
            raise ValueError("predicate id must be a 16-byte UUID")
        for dep in self.depends_on:
            if len(dep) != 16:
                raise ValueError("each dependency id must be a 16-byte UUID")
        if self.kind != self.invocation.kind:
            raise ValueError(
                "predicate.kind and invocation.kind disagree: "
                f"{self.kind!r} vs {self.invocation.kind!r}"
            )

    def evaluate(self, ws: "WorkspaceSnapshot") -> PredicateResult:
        """Return the ``PredicateResult`` for this predicate against ``ws``.

        Delegates to ``ract.core.gates.evaluate_invocation``; the import is
        local to avoid a cycle between ``predicate`` and ``gates`` at
        module load time.
        """
        # Local import: gates depends on predicate types.
        from ract.core.gates import evaluate_invocation

        result = evaluate_invocation(self.invocation, ws)
        # module_05 (SUBSTRATE §6.3): every predicate evaluation lands
        # in the event log so the reporter's pass/fail counts derive
        # from durable state, not in-memory tallies.
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "predicate.evaluated",
                {
                    "predicate_id": self.id.hex(),
                    "kind": self.kind,
                    "required": self.required,
                    "ok": result.ok,
                    "reason": result.reason,
                    "duration_ns": result.duration_ns,
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return result


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceSuite:
    """A frozen list of predicates that define the environment's exit gate."""

    intent_id: bytes
    predicates: tuple[AcceptancePredicate, ...]
    coverage_gate: float = 0.85
    compiled_from: str = ""
    compiler_version: str = CANONICAL_COMPILER_VERSION

    def __post_init__(self) -> None:
        if len(self.intent_id) != 16:
            raise ValueError("intent_id must be a 16-byte UUID")
        if not 0.0 <= self.coverage_gate <= 1.0:
            raise ValueError(
                f"coverage_gate out of [0.0, 1.0]: {self.coverage_gate}"
            )
        if self.compiler_version not in _KNOWN_COMPILER_VERSIONS:
            raise ValueError(
                f"unknown compiler_version {self.compiler_version!r}; "
                "halting per the same policy as ADR-0008 (ract.yaml versioning)."
            )
        # Detect duplicate ids so digest() is well-defined and the reader can
        # deserialize without ambiguity.
        seen: set[bytes] = set()
        for p in self.predicates:
            if p.id in seen:
                raise ValueError(f"duplicate predicate id: {p.id.hex()}")
            seen.add(p.id)

    def required(self) -> tuple[AcceptancePredicate, ...]:
        """Return the tuple of required predicates."""
        return tuple(p for p in self.predicates if p.required)

    def to_canonical(self) -> dict[str, Any]:
        """Return the canonical dict form used for JSON serialization and hashing."""
        return {
            "compiler_version": self.compiler_version,
            "compiled_from": self.compiled_from,
            "coverage_gate": self.coverage_gate,
            "intent_id": self.intent_id.hex(),
            "predicates": [
                {
                    "id": p.id.hex(),
                    "kind": p.kind,
                    "required": p.required,
                    "depends_on": [d.hex() for d in p.depends_on],
                    "invocation": p.invocation.to_canonical(),
                }
                for p in self.predicates
            ],
        }

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical serialization."""
        payload = json.dumps(
            self.to_canonical(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        """Return the canonical JSON form (sorted keys, trailing newline)."""
        return (
            json.dumps(self.to_canonical(), sort_keys=True, indent=2) + "\n"
        )


# ---------------------------------------------------------------------------
# Reader (version-dispatched)
# ---------------------------------------------------------------------------


def _invocation_from_canonical(data: dict[str, Any]) -> PredicateInvocation:
    kind = data.get("type")
    if kind == "pytest":
        return PytestInvocation(
            selector=str(data["selector"]),
            timeout_seconds=int(data.get("timeout_seconds", 60)),
        )
    if kind == "mypy":
        return MypyInvocation(
            target=str(data["target"]), strict=bool(data.get("strict", True))
        )
    if kind == "hypothesis":
        return HypothesisInvocation(
            target=str(data["target"]),
            max_examples=int(data.get("max_examples", 100)),
        )
    if kind == "assertion":
        return AssertionInvocation(callable_ref=str(data["callable_ref"]))
    if kind == "artifact":
        return ArtifactInvocation(
            path=str(data["path"]),
            must_have_rootknot=bool(data.get("must_have_rootknot", False)),
        )
    raise ValueError(f"unknown invocation type: {kind!r}")


def _predicate_from_canonical(data: dict[str, Any]) -> AcceptancePredicate:
    return AcceptancePredicate(
        id=bytes.fromhex(str(data["id"])),
        kind=data["kind"],
        invocation=_invocation_from_canonical(data["invocation"]),
        required=bool(data.get("required", True)),
        depends_on=tuple(bytes.fromhex(str(d)) for d in data.get("depends_on", [])),
    )


def suite_from_canonical(data: dict[str, Any]) -> AcceptanceSuite:
    """Deserialize a canonical dict into an ``AcceptanceSuite``.

    The reader dispatches on ``compiler_version`` (lateral chain branch E).
    An unknown version raises, per the same policy as ADR-0008.
    """
    version = data.get("compiler_version")
    if version not in _KNOWN_COMPILER_VERSIONS:
        raise ValueError(
            f"unknown compiler_version {version!r}; refuse to reinterpret."
        )
    return AcceptanceSuite(
        intent_id=bytes.fromhex(str(data["intent_id"])),
        predicates=tuple(
            _predicate_from_canonical(p) for p in data.get("predicates", [])
        ),
        coverage_gate=float(data.get("coverage_gate", 0.85)),
        compiled_from=str(data.get("compiled_from", "")),
        compiler_version=str(version),
    )


def suite_from_json(text: str) -> AcceptanceSuite:
    """Parse canonical JSON into an ``AcceptanceSuite``."""
    return suite_from_canonical(json.loads(text))


# RACT 0.4.0
