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
from typing import TYPE_CHECKING, Any

from ract.core.predicate import (
    CANONICAL_COMPILER_VERSION,
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    AssertionInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PytestInvocation,
    RelatedFileCoverageInvocation,
    new_intent_id,
    new_predicate_id,
)

if TYPE_CHECKING:
    from ract.antilazy.holdout import DualAcceptanceSuite, HoldoutComposer
    from ract.core.loop import WorkspaceSnapshot
    from ract.handshake_registry import HandshakeRegistry


# Handshake ids used by the compiler when it needs approval for a batch of
# proposed predicates (lateral chain branch A). Grouping is by predicate
# kind so the operator resolves one handshake per group.
_HANDSHAKE_GROUP_PREFIX: str = "acceptance.compiler.group."


@dataclass(frozen=True)
class CouplingMap:
    """One coupling-map entry — source glob paired to a must-also-touch glob."""

    source_glob: str
    must_also_touch_glob: str
    rationale: str = ""


# Default coupling maps injected by the compiler when the corresponding
# source area is present in the workspace. Each entry becomes a
# ``RelatedFileCoverageInvocation`` in the compiled suite. Callers may
# supply additional entries through ``CompilerInputs.coupling_maps``;
# ``ract.yaml``'s optional ``[coupling_maps]`` section can also feed
# entries in via the CLI layer (schema is optional — omit for no gate).
_DEFAULT_COUPLING_MAPS: tuple[CouplingMap, ...] = (
    CouplingMap(
        source_glob="src/ract/{core,executor}/**/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
        rationale="arch changes require ARCHITECTURE.md update",
    ),
)


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
    coupling_maps: tuple[CouplingMap, ...] = ()
    include_default_coupling_maps: bool = True
    # Cluster 2 finding 3: optional plan to analyse for the
    # ``plan.risk_assessed`` advisory. Substrate callers that don't
    # want the advisory omit both fields; the risk pass then skips.
    plan_for_risk: Any = None
    manifest_for_risk: Any = None


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
                CompiledPreview(kind="property", items=tuple(inputs.property_targets))
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
    def _group_is_approved(approvals: "HandshakeRegistry | None", kind: str) -> bool:
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
        companion: "HoldoutComposer | None" = None,
    ) -> "AcceptanceSuite | DualAcceptanceSuite":
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
            preview = CompiledPreview(kind="test", items=tuple(cfg.proposed_new_tests))
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
            if (
                self._group_is_approved(approvals, "artifact")
                or len(cfg.artifact_requirements) <= 1
            ):
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

        # 7) Coupling maps — RelatedFileCoverageInvocation entries.
        # Explicit ``coupling_maps`` from the caller are always
        # attached. The default coupling map (arch changes require
        # ARCHITECTURE.md update) is attached only when the intent's
        # touched_surface actually intersects the source_glob's area,
        # so intents unrelated to core/executor pay no evaluation cost.
        maps: list[CouplingMap] = list(cfg.coupling_maps)
        if cfg.include_default_coupling_maps:
            for entry in _DEFAULT_COUPLING_MAPS:
                if _touched_surface_matches(cfg.touched_surface, entry.source_glob):
                    if entry not in maps:
                        maps.append(entry)
        for entry in maps:
            predicates.append(
                AcceptancePredicate(
                    id=new_predicate_id(),
                    kind="related_file_coverage",
                    invocation=RelatedFileCoverageInvocation(
                        source_glob=entry.source_glob,
                        must_also_touch_glob=entry.must_also_touch_glob,
                        rationale=entry.rationale,
                    ),
                    required=True,
                )
            )

        coverage = float(cfg.coverage_gate or self.coverage_gate_default)
        # v0.5.1 module_02: bind the compiled suite to the raw intent
        # text via SHA-256 (module_04 wires the runtime PROMPT_DRIFT
        # check on top of this field). Uses the raw ``intent_text``
        # bytes, not the ``.strip()``-ed form that ``compiled_from``
        # stores, so an injected prompt with only whitespace
        # differences still trips the drift check.
        from ract.core.workspace_digest import compute_prompt_digest

        prompt_digest_bytes = bytes(compute_prompt_digest(intent_text))
        suite = AcceptanceSuite(
            intent_id=new_intent_id(),
            predicates=tuple(predicates),
            coverage_gate=coverage,
            compiled_from=intent_text.strip(),
            compiler_version=self.version,
            prompt_digest=prompt_digest_bytes,
        )
        # ALM module_01 hook: when a HoldoutComposer companion is
        # supplied, wrap the substrate suite in a DualAcceptanceSuite
        # whose held-out half is composed by the companion and sealed
        # under the run's SandboxKey. The seal is a caller concern —
        # the compiler produces the plaintext dual suite; the caller
        # invokes ``ract.antilazy.holdout.seal_held_out`` with its own
        # SandboxKey. Substrate callers pass ``companion=None`` and
        # continue to get back an ``AcceptanceSuite``.
        if companion is not None:
            # Local import breaks the substrate -> antilazy import
            # cycle at core load time; only the compile call site
            # pays the import cost.
            from ract.antilazy.holdout import (
                DualAcceptanceSuite,
                compose_held_out,
            )

            held_out_suite, kind = compose_held_out(
                suite, ws, companion, touched=tuple(cfg.touched_surface)
            )
            dual: DualAcceptanceSuite = DualAcceptanceSuite(
                visible=suite,
                held_out=held_out_suite,
                held_out_digest=held_out_suite.digest(),
                # Seal deliberately empty at compile time; the loop /
                # sandbox layer seals with its own SandboxKey via
                # ``seal_held_out`` before writing the on-disk snapshot.
                held_out_seal=b"",
                holdout_kind=kind,
            )
            return dual
        # module_05 (SUBSTRATE §6.3): the compiled suite is the first
        # legible artifact of a run; emit ``run.started`` at the site
        # that produces it. A run with no registered writer drops the
        # event (null sink); the emit shape stays load-bearing so the
        # replay/reporter paths always have a stable start marker.
        try:  # local import breaks the trace→core cycle at import time
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "run.started",
                {
                    "intent_id": suite.intent_id.hex(),
                    "suite_digest": suite.digest(),
                    "compiler_version": suite.compiler_version,
                    "predicate_count": len(suite.predicates),
                    "required_count": len(suite.required()),
                    "coverage_gate": suite.coverage_gate,
                },
            )
        except Exception:  # noqa: BLE001 — never fail compile on trace error
            pass

        # Cluster 2 finding 3: emit a plan.risk_assessed advisory when
        # ``inputs.plan_for_risk`` is supplied. Substrate callers that
        # only supply an intent skip this — the report needs a plan to
        # analyse and the compile pass does not construct one itself.
        plan_for_risk = getattr(cfg, "plan_for_risk", None)
        if plan_for_risk is not None:
            try:
                from ract.core.plan_risk import analyze_plan
                from ract.trace.sink import emit as _emit_event

                report = analyze_plan(
                    plan_for_risk,
                    manifest=getattr(cfg, "manifest_for_risk", None),
                    plan_id=suite.intent_id,
                )
                _emit_event("plan.risk_assessed", report.to_payload())
            except Exception:  # noqa: BLE001 — never fail compile on trace error
                pass
        return suite

    def compile_and_detect_rule_like(
        self,
        intent_text: str,
        ws: "WorkspaceSnapshot",
        approvals: "HandshakeRegistry | None" = None,
        *,
        inputs: CompilerInputs | None = None,
        companion: "HoldoutComposer | None" = None,
    ) -> "tuple[AcceptanceSuite | DualAcceptanceSuite, bool]":
        """Compile ``intent_text`` and additionally return the rule-like flag.

        ALM module_06 hook. The rule-like flag drives whether the
        isomorphic-perturbation gate fires at the completion path;
        loop wiring keyed on this attribute (rather than a global
        detector call) keeps the substrate compile pass free of ALM
        imports.

        Returns ``(compile_result, is_rule_like)``. The compile result
        keeps its existing shape (``AcceptanceSuite`` or, when
        ``companion`` is provided, ``DualAcceptanceSuite``).
        """
        # Local import breaks the substrate -> antilazy cycle at core
        # load time; only the site that wants the rule-like flag pays
        # the import cost.
        from ract.antilazy.iso_perturb import detect_rule_like_intent

        result = self.compile(
            intent_text, ws, approvals, inputs=inputs, companion=companion
        )
        detection = detect_rule_like_intent(intent_text)
        return result, detection.is_rule_like

    def compile_with_holdout(
        self,
        intent_text: str,
        ws: "WorkspaceSnapshot",
        approvals: "HandshakeRegistry | None" = None,
        *,
        inputs: CompilerInputs | None = None,
        companion: "HoldoutComposer",
    ) -> "DualAcceptanceSuite":
        """Return a ``DualAcceptanceSuite`` — the caller wants both halves.

        Convenience over ``compile(..., companion=...)`` for callers
        that know they want the dual return; narrows the return type
        so downstream code does not need an ``isinstance`` check.
        """
        result = self.compile(
            intent_text, ws, approvals, inputs=inputs, companion=companion
        )
        # Local import matches the guard used inside ``compile``.
        from ract.antilazy.holdout import DualAcceptanceSuite

        if not isinstance(result, DualAcceptanceSuite):  # pragma: no cover
            raise RuntimeError(
                "compile_with_holdout received a companion but compile "
                "returned an AcceptanceSuite; this indicates a substrate "
                "regression."
            )
        return result


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


def _touched_surface_matches(paths: tuple[str, ...], glob: str) -> bool:
    """Return True iff any normalized path in ``paths`` matches ``glob``."""
    from ract.core.gates import _fnmatch_hits  # local import breaks cycle

    canonical = list(_canonical_touched(paths))
    return bool(_fnmatch_hits(canonical, glob))


# RACT 0.4.0
