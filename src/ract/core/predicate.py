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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Union

from ract.canonical import dumps_jcs

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


PredicateKind = Literal[
    "test",
    "type",
    "property",
    "invariant",
    "artifact",
    "related_file_coverage",
]


# ALM module_01 second-pass fix: when a caller is evaluating held-out
# predicates it sets this context variable so ``AcceptancePredicate.
# evaluate`` emits a redacted ``predicate_id`` in the ``predicate.
# evaluated`` event. The raw id stays inside the sandbox side channel;
# the model-facing trace surface sees only the digest. Substrate
# callers that never touch the flag observe the substrate behaviour
# unchanged.
_REDACT_PREDICATE_ID: ContextVar[bool] = ContextVar(
    "_ract_redact_predicate_id", default=False
)


def _redacted_predicate_id(raw: bytes) -> str:
    """Return an id-shape digest for the trace payload of a held-out predicate.

    SHA-256 of the raw id, first 16 hex chars. Short enough to remain
    stable across the trace but not reversible to the raw id (the
    model cannot enumerate the 2**64 preimages inside a run).
    """
    return "redacted:" + hashlib.sha256(raw).hexdigest()[:16]


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


@dataclass(frozen=True)
class RelatedFileCoverageInvocation:
    """Verify that a coupled file was touched whenever a source file was touched.

    Coupling-map enforcement: when a change lands in a file matching
    ``source_glob``, the same change must also touch at least one file
    matching ``must_also_touch_glob``. The classic instance is
    "arch changes require ARCHITECTURE.md update", but the shape covers
    any docs-when-code-changes / test-when-module-changes coupling the
    project wants to enforce.

    Evaluation reads the workspace's diff (files changed since the
    parent snapshot) from ``ws.metadata['changed_files']``. When no
    ``source_glob`` file is touched, the coupling is vacuously
    satisfied. When the diff channel is missing entirely, the predicate
    resolves to ``ok=False`` — an unrecorded diff cannot be treated as
    a pass.
    """

    source_glob: str
    must_also_touch_glob: str
    rationale: str = ""
    kind: ClassVar[PredicateKind] = "related_file_coverage"

    def to_canonical(self) -> dict[str, Any]:
        return {
            "type": "related_file_coverage",
            "source_glob": self.source_glob,
            "must_also_touch_glob": self.must_also_touch_glob,
            "rationale": self.rationale,
        }


PredicateInvocation = Union[
    PytestInvocation,
    MypyInvocation,
    HypothesisInvocation,
    AssertionInvocation,
    ArtifactInvocation,
    RelatedFileCoverageInvocation,
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

            payload_id: str
            if _REDACT_PREDICATE_ID.get():
                payload_id = _redacted_predicate_id(self.id)
            else:
                payload_id = self.id.hex()
            _emit_event(
                "predicate.evaluated",
                {
                    "predicate_id": payload_id,
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
    """A frozen list of predicates that define the environment's exit gate.

    v0.5.1 module_02 adds an OPTIONAL ``prompt_digest`` field: SHA-256
    of the operator's intent text at compile time. The T8 PROMPT_DRIFT
    check (module_04) reads it at each loop iteration. The field is
    backward-compatible: v0.5.0 suites lack it, and
    :meth:`to_canonical` emits it only when set so digest bytes stay
    identical for legacy suites.
    """

    intent_id: bytes
    predicates: tuple[AcceptancePredicate, ...]
    coverage_gate: float = 0.85
    compiled_from: str = ""
    compiler_version: str = CANONICAL_COMPILER_VERSION
    # v0.5.1 module_02: SHA-256 of the operator's intent text at
    # compile time. Optional (``None``) for backward-compat with
    # v0.5.0 suites; :class:`IntentCompiler` populates it on every
    # v0.5.1 compile. See ``workspace_digest.compute_prompt_digest``
    # for the hasher and ``tests/unit/test_canonical_bytes_v2.py`` for
    # the round-trip tests.
    prompt_digest: bytes | None = None

    def __post_init__(self) -> None:
        if len(self.intent_id) != 16:
            raise ValueError("intent_id must be a 16-byte UUID")
        if not 0.0 <= self.coverage_gate <= 1.0:
            raise ValueError(f"coverage_gate out of [0.0, 1.0]: {self.coverage_gate}")
        if self.compiler_version not in _KNOWN_COMPILER_VERSIONS:
            raise ValueError(
                f"unknown compiler_version {self.compiler_version!r}; "
                "halting per the same policy as ADR-0008 (ract.yaml versioning)."
            )
        if self.prompt_digest is not None and len(self.prompt_digest) != 32:
            raise ValueError(
                "prompt_digest must be a 32-byte SHA-256 digest; "
                f"got {len(self.prompt_digest)} bytes"
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
        payload: dict[str, Any] = {
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
        # v0.5.1 module_02: opt-in prompt_digest. Emitted ONLY when set
        # so v0.5.0 suites hash identically. Alphabetical sort-key
        # placement between "predicates" and (a future) "prompt_source"
        # is a property of ``json.dumps(sort_keys=True)``.
        if self.prompt_digest is not None:
            payload["prompt_digest"] = self.prompt_digest.hex()
        return payload

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical serialization.

        v0.5.1 module_03: canonical bytes are RFC 8785 JCS (strict-JSON,
        NFC-normalised, codepoint-sorted keys). See
        ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``.
        """
        return hashlib.sha256(dumps_jcs(self.to_canonical())).hexdigest()

    # TODO(D10, v0.5.2): document explicitly that ``to_json`` is a
    # non-canonical human-readable form; the signing input is
    # ALWAYS ``digest()`` (which routes through ``dumps_jcs``).
    # ``to_json`` uses ``indent=2`` for display and can diverge from
    # ``digest()`` under non-BMP characters -- the divergence is
    # intentional (JCS has no ``indent=2``) but needs to be
    # documented so a future maintainer does not "unify" them.
    def to_json(self) -> str:
        """Return the canonical JSON form (sorted keys, trailing newline)."""
        return json.dumps(self.to_canonical(), sort_keys=True, indent=2) + "\n"


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
    if kind == "related_file_coverage":
        return RelatedFileCoverageInvocation(
            source_glob=str(data["source_glob"]),
            must_also_touch_glob=str(data["must_also_touch_glob"]),
            rationale=str(data.get("rationale", "")),
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
    # v0.5.1 module_02: prompt_digest is optional; absent for v0.5.0
    # payloads. Parse as bytes when present (32-byte SHA-256).
    prompt_digest_raw = data.get("prompt_digest")
    prompt_digest = (
        bytes.fromhex(str(prompt_digest_raw)) if prompt_digest_raw is not None else None
    )
    return AcceptanceSuite(
        intent_id=bytes.fromhex(str(data["intent_id"])),
        predicates=tuple(
            _predicate_from_canonical(p) for p in data.get("predicates", [])
        ),
        coverage_gate=float(data.get("coverage_gate", 0.85)),
        compiled_from=str(data.get("compiled_from", "")),
        compiler_version=str(version),
        prompt_digest=prompt_digest,
    )


def suite_from_json(text: str) -> AcceptanceSuite:
    """Parse canonical JSON into an ``AcceptanceSuite``."""
    return suite_from_canonical(json.loads(text))


# RACT 0.4.0
