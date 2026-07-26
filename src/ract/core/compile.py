"""IntentCompiler — turn an operator intent into a frozen ``AcceptanceSuite``.

SUBSTRATE spec §2.4 lists the sources: existing tests, new tests the compiler
proposes as reproducers, strict ``mypy`` on the touched surface, Hypothesis
property checks against invariants declared in ADRs, artifact predicates, and
a coverage gate. Only predicates the operator approves enter the suite; once
compiled, the suite is frozen for that run.

Lateral chain branch A: proposed predicates are **grouped by kind** so a
handshake covers all tests together, all properties together, all artifact
checks together — one handshake per group with a diff-shaped preview,
never one per predicate.

Lateral chain branch B is enforced by ``LoopState`` construction: a suite
with zero required predicates is refused; the trivial-empty-suite escape
hatch is closed at the loop constructor, not here.

The compiler is a Manager-side artifact; it emits the suite that the
environment then verifies. That workflow-plus-activities split follows
the Temporal durable-execution model
(``https://docs.temporal.io/``): here the compiler is the workflow that
describes what "done" means, and the evaluators in ``gates`` are the
activities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ract.core.predicate import (
    CANONICAL_COMPILER_VERSION,
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    AssertionInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PytestInvocation,
    new_intent_id,
    new_predicate_id,
)

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot
    from ract.handshake_registry import HandshakeRegistry


# Handshake ids used by the compiler when it needs approval for a batch of
# proposed predicates (lateral chain branch A). Grouping is by predicate
# kind so the operator resolves one handshake per group.
_HANDSHAKE_GROUP_PREFIX: str = "acceptance.compiler.group."


@dataclass(frozen=True)
class CompilerInputs:
    """Optional inputs beyond the intent text.

    Keeping these as an explicit dataclass makes the call sites (tests, the
    eval-task fixture script, future loop wiring) self-documenting and lets
    the compiler stay pure over its inputs.
    """

    proposed_new_tests: tuple[str, ...] = ()
    touched_surface: tuple[str, ...] = ()
    artifact_requirements: tuple[str, ...] = ()
    invariant_callables: tuple[str, ...] = ()
    property_targets: tuple[str, ...] = ()
    coverage_gate: float = 0.85
    tests_root: str = "tests"


@dataclass(frozen=True)
class CompiledPreview:
    """A grouped preview of proposed predicates, one entry per predicate kind.

    Emitted for lateral chain branch A: the operator sees the whole group in
    one handshake with a diff-shaped body, not one handshake per predicate.
    """

    kind: str
    items: tuple[str, ...] = field(default_factory=tuple)

    def as_diff(self) -> str:
        """Return the group as a ``+``-prefixed diff-shaped block."""
        header = f"+++ acceptance/{self.kind}\n"
        body = "".join(f"+ {item}\n" for item in self.items)
        return header + body


class IntentCompiler:
    """Compile an intent into a frozen ``AcceptanceSuite``.

    The compiler is deterministic given the same inputs; identifiers are the
    only source of nondeterminism and are drawn from ``uuid.uuid4()`` — the
    canonical serialization sorts by explicit key order rather than id order,
    so digests remain stable under id churn (the digest changes when the
    suite's *content* changes).
    """

    #: Version stamped into every emitted suite. Bumping this string is a
    #: breaking change; the reader in ``predicate.suite_from_canonical``
    #: refuses to reinterpret older versions and points at a migration.
    version: str = CANONICAL_COMPILER_VERSION

    def __init__(self, *, coverage_gate_default: float = 0.85) -> None:
        self.coverage_gate_default = coverage_gate_default

    # ------------------------------------------------------------------
    # Grouping (lateral chain branch A)
    # ------------------------------------------------------------------

    @staticmethod
    def group_previews(inputs: CompilerInputs) -> list[CompiledPreview]:
        """Group proposed predicates by kind for the operator handshake.

        Returns a list of ``CompiledPreview`` entries — one per non-empty
        group — so the operator resolves one handshake per group with a
        diff-shaped preview.
        """
        previews: list[CompiledPreview] = []
        if inputs.proposed_new_tests:
            previews.append(
                CompiledPreview(kind="test", items=tuple(inputs.proposed_new_tests))
            )
        if inputs.property_targets:
            previews.append(
                CompiledPreview(
                    kind="property", items=tuple(inputs.property_targets)
                )
            )
        if inputs.artifact_requirements:
            previews.append(
                CompiledPreview(
                    kind="artifact", items=tuple(inputs.artifact_requirements)
                )
            )
        if inputs.invariant_callables:
            previews.append(
                CompiledPreview(
                    kind="invariant", items=tuple(inputs.invariant_callables)
                )
            )
        return previews

    @staticmethod
    def _group_id(kind: str) -> str:
        return f"{_HANDSHAKE_GROUP_PREFIX}{kind}"

    @staticmethod
    def _group_is_approved(
        approvals: "HandshakeRegistry | None", kind: str
    ) -> bool:
        if approvals is None:
            return False
        group_id = IntentCompiler._group_id(kind)
        for item in approvals.entries():
            if item.id == group_id and item.status == "approved":
                return True
        return False

    @staticmethod
    def _request_group_handshake(
        approvals: "HandshakeRegistry | None",
        preview: CompiledPreview,
    ) -> None:
        if approvals is None:
            return
        group_id = IntentCompiler._group_id(preview.kind)
        # Skip if a handshake for this group already exists in any status;
        # add() would append a duplicate entry.
        for item in approvals.entries():
            if item.id == group_id:
                return
        approvals.add(
            milestone_id=group_id,
            description=(
                f"IntentCompiler proposes {len(preview.items)} new "
                f"{preview.kind} predicate(s)."
            ),
            acceptance=preview.as_diff(),
            metadata={
                "compiler_version": IntentCompiler.version,
                "kind": preview.kind,
                "items": list(preview.items),
            },
        )

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def compile(
        self,
        intent_text: str,
        ws: "WorkspaceSnapshot",
        approvals: "HandshakeRegistry | None" = None,
        *,
        inputs: CompilerInputs | None = None,
    ) -> AcceptanceSuite:
        """Return the frozen ``AcceptanceSuite`` for ``intent_text``.

        Sources (SUBSTRATE §2.4):

        - Existing tests in the workspace that must continue to pass
          (auto-discovered from ``ws.files`` under ``inputs.tests_root``).
        - New tests the compiler proposes — added only if a handshake
          approving the ``test`` group is already resolved.
        - Strict mypy on the touched surface.
        - Hypothesis property checks against declared invariants.
        - Assertion invariants over the snapshot.
        - Artifact predicates (files that must exist, optionally with a
          rootknot sidecar).
        - Coverage gate on the touched surface (lateral chain branch D:
          required, so a coverage drop terminates the loop with
          ``PROVENANCE_FAILURE``/``BUDGET_EXHAUSTED`` rather than passing).
        """
        cfg = inputs or CompilerInputs(coverage_gate=self.coverage_gate_default)
        predicates: list[AcceptancePredicate] = []

        # 1) Existing tests — auto-discovered from the snapshot. A file is
        # considered a test file if its path lies under `tests_root` and its
        # basename starts with `test_`.
        for test_file in _discover_test_files(ws, cfg.tests_root):
            predicates.append(
                AcceptancePredicate(
                    id=new_predicate_id(),
                    kind="test",
                    invocation=PytestInvocation(selector=test_file),
                    required=True,
                )
            )

        # 2) Proposed new tests — grouped handshake per lateral branch A.
        if cfg.proposed_new_tests:
            preview = CompiledPreview(
                kind="test", items=tuple(cfg.proposed_new_tests)
            )
            if self._group_is_approved(approvals, "test"):
                for selector in cfg.proposed_new_tests:
                    predicates.append(
                        AcceptancePredicate(
                            id=new_predicate_id(),
                            kind="test",
                            invocation=PytestInvocation(selector=selector),
                            required=True,
                        )
                    )
            else:
                self._request_group_handshake(approvals, preview)

        # 3) Strict mypy on the touched surface.
        for target in cfg.touched_surface:
            predicates.append(
                AcceptancePredicate(
                    id=new_predicate_id(),
                    kind="type",
                    invocation=MypyInvocation(target=target, strict=True),
                    required=True,
                )
            )

        # 4) Hypothesis property checks — group-gated.
        if cfg.property_targets:
            preview = CompiledPreview(
                kind="property", items=tuple(cfg.property_targets)
            )
            if self._group_is_approved(approvals, "property"):
                for target in cfg.property_targets:
                    predicates.append(
                        AcceptancePredicate(
                            id=new_predicate_id(),
                            kind="property",
                            invocation=HypothesisInvocation(target=target),
                            required=True,
                        )
                    )
            else:
                self._request_group_handshake(approvals, preview)

        # 5) Assertion invariants over the snapshot.
        for callable_ref in cfg.invariant_callables:
            predicates.append(
                AcceptancePredicate(
                    id=new_predicate_id(),
                    kind="invariant",
                    invocation=AssertionInvocation(callable_ref=callable_ref),
                    required=True,
                )
            )

        # 6) Artifact predicates — group-gated when many are proposed.
        if cfg.artifact_requirements:
            preview = CompiledPreview(
                kind="artifact", items=tuple(cfg.artifact_requirements)
            )
            if self._group_is_approved(approvals, "artifact") or len(
                cfg.artifact_requirements
            ) <= 1:
                for path in cfg.artifact_requirements:
                    predicates.append(
                        AcceptancePredicate(
                            id=new_predicate_id(),
                            kind="artifact",
                            invocation=ArtifactInvocation(
                                path=path, must_have_rootknot=False
                            ),
                            required=True,
                        )
                    )
            else:
                self._request_group_handshake(approvals, preview)

        coverage = float(cfg.coverage_gate or self.coverage_gate_default)
        return AcceptanceSuite(
            intent_id=new_intent_id(),
            predicates=tuple(predicates),
            coverage_gate=coverage,
            compiled_from=intent_text.strip(),
            compiler_version=self.version,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _discover_test_files(ws: "WorkspaceSnapshot", tests_root: str) -> list[str]:
    """Return the test-file paths in the snapshot, sorted for determinism."""
    root = tests_root.rstrip("/")
    prefix = f"{root}/" if root else ""
    pattern = re.compile(r"(^|/)test_[^/]+\.py$")
    result: list[str] = []
    for path in ws.files:
        norm = path.replace("\\", "/")
        if root and not norm.startswith(prefix):
            continue
        if pattern.search(norm):
            result.append(norm)
    result.sort()
    return result


def _canonical_touched(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Return ``paths`` normalized to forward-slash form and sorted."""
    return tuple(sorted(p.replace("\\", "/") for p in paths))


# RACT 0.4.0
