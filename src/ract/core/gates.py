"""Built-in evaluators for compiled acceptance predicates.

Each evaluator is pure over ``(invocation, WorkspaceSnapshot)``: given the
same snapshot metadata and invocation, it returns the same
``PredicateResult`` byte-for-byte. Verifiers that would otherwise mutate
state (e.g., a live ``pytest`` run) read pre-computed results from
``WorkspaceSnapshot.metadata``. That indirection is what lets T1 read the
suite off a snapshot that was captured before evaluation.

Coupling with module_02 (transactional execution): when evaluators need to
execute a verifier live, they must do so against a scratch copy of the
snapshot — never the live workspace. The scratch-copy discipline lives in
module_02's worktree substrate; this module documents the coupling and
defers enforcement.

See ``docs/ADRs/ADR-0010-acceptance-predicates.md`` for design rationale.
"""

from __future__ import annotations

import importlib
import time
from typing import TYPE_CHECKING, Any

from ract.core.predicate import (
    ArtifactInvocation,
    AssertionInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PredicateInvocation,
    PredicateResult,
    PytestInvocation,
)

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


# Metadata channel keys the compiler and executor write for evaluators to
# read. Keeping the vocabulary here means the reader/writer contract is
# discoverable in one place.
_META_PYTEST = "pytest"
_META_MYPY = "mypy"
_META_HYPOTHESIS = "hypothesis"


def evaluate_pytest(
    invocation: PytestInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Evaluate a pytest selector against the snapshot's recorded results.

    Reads ``ws.metadata['pytest'][selector]``. The value is a dict with
    ``ok: bool`` and optional ``reason: str`` / ``evidence: dict``. If no
    entry exists for the selector, the predicate is treated as unresolved
    (ok=False) — the environment must record what happened; silence is
    not a pass.
    """
    started = time.perf_counter_ns()
    entry = _meta(ws, _META_PYTEST).get(invocation.selector)
    if entry is None:
        return PredicateResult(
            ok=False,
            reason=f"no pytest record for selector {invocation.selector!r}",
            evidence={"selector": invocation.selector},
            duration_ns=time.perf_counter_ns() - started,
        )
    return PredicateResult(
        ok=bool(entry.get("ok", False)),
        reason=str(entry.get("reason", "")),
        evidence={"selector": invocation.selector, **entry.get("evidence", {})},
        duration_ns=time.perf_counter_ns() - started,
    )


def evaluate_mypy(
    invocation: MypyInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Evaluate mypy strictness against the snapshot's recorded results.

    Reads ``ws.metadata['mypy'][target]`` and expects the same
    ``{ok, reason, evidence}`` shape as pytest.
    """
    started = time.perf_counter_ns()
    entry = _meta(ws, _META_MYPY).get(invocation.target)
    if entry is None:
        return PredicateResult(
            ok=False,
            reason=f"no mypy record for target {invocation.target!r}",
            evidence={"target": invocation.target, "strict": invocation.strict},
            duration_ns=time.perf_counter_ns() - started,
        )
    return PredicateResult(
        ok=bool(entry.get("ok", False)),
        reason=str(entry.get("reason", "")),
        evidence={"target": invocation.target, **entry.get("evidence", {})},
        duration_ns=time.perf_counter_ns() - started,
    )


def evaluate_hypothesis(
    invocation: HypothesisInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Evaluate a Hypothesis property check against the snapshot's records."""
    started = time.perf_counter_ns()
    entry = _meta(ws, _META_HYPOTHESIS).get(invocation.target)
    if entry is None:
        return PredicateResult(
            ok=False,
            reason=f"no hypothesis record for target {invocation.target!r}",
            evidence={
                "target": invocation.target,
                "max_examples": invocation.max_examples,
            },
            duration_ns=time.perf_counter_ns() - started,
        )
    return PredicateResult(
        ok=bool(entry.get("ok", False)),
        reason=str(entry.get("reason", "")),
        evidence={"target": invocation.target, **entry.get("evidence", {})},
        duration_ns=time.perf_counter_ns() - started,
    )


def evaluate_assertion(
    invocation: AssertionInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Resolve ``callable_ref`` and invoke it against the snapshot.

    ``callable_ref`` accepts either ``pkg.mod:name`` or ``pkg.mod.name``.
    """
    started = time.perf_counter_ns()
    try:
        target = _resolve_callable(invocation.callable_ref)
    except (ImportError, AttributeError, ValueError) as exc:
        return PredicateResult(
            ok=False,
            reason=f"could not resolve callable {invocation.callable_ref!r}: {exc}",
            evidence={"callable_ref": invocation.callable_ref},
            duration_ns=time.perf_counter_ns() - started,
        )
    try:
        outcome = bool(target(ws))
    except Exception as exc:  # noqa: BLE001 — the invariant callable is untrusted.
        return PredicateResult(
            ok=False,
            reason=f"invariant callable raised: {exc}",
            evidence={"callable_ref": invocation.callable_ref},
            duration_ns=time.perf_counter_ns() - started,
        )
    return PredicateResult(
        ok=outcome,
        reason=(
            "invariant callable returned True"
            if outcome
            else "invariant callable returned False"
        ),
        evidence={"callable_ref": invocation.callable_ref},
        duration_ns=time.perf_counter_ns() - started,
    )


def evaluate_artifact(
    invocation: ArtifactInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Check that the artifact path is present in the snapshot's file map."""
    started = time.perf_counter_ns()
    files = ws.files
    if invocation.path not in files:
        return PredicateResult(
            ok=False,
            reason=f"artifact {invocation.path!r} not present in snapshot",
            evidence={"path": invocation.path},
            duration_ns=time.perf_counter_ns() - started,
        )
    if invocation.must_have_rootknot:
        sidecar = _sidecar_path(invocation.path)
        if sidecar not in files:
            return PredicateResult(
                ok=False,
                reason=(
                    f"rootknot sidecar {sidecar!r} missing for artifact "
                    f"{invocation.path!r}"
                ),
                evidence={"path": invocation.path, "sidecar": sidecar},
                duration_ns=time.perf_counter_ns() - started,
            )
    return PredicateResult(
        ok=True,
        reason=f"artifact {invocation.path!r} present",
        evidence={
            "path": invocation.path,
            "must_have_rootknot": invocation.must_have_rootknot,
        },
        duration_ns=time.perf_counter_ns() - started,
    )


def evaluate_invocation(
    invocation: PredicateInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Dispatch to the built-in evaluator for ``invocation``'s kind."""
    if isinstance(invocation, PytestInvocation):
        return evaluate_pytest(invocation, ws)
    if isinstance(invocation, MypyInvocation):
        return evaluate_mypy(invocation, ws)
    if isinstance(invocation, HypothesisInvocation):
        return evaluate_hypothesis(invocation, ws)
    if isinstance(invocation, AssertionInvocation):
        return evaluate_assertion(invocation, ws)
    if isinstance(invocation, ArtifactInvocation):
        return evaluate_artifact(invocation, ws)
    # Unreachable when the invocation union stays closed.
    raise TypeError(f"unknown invocation type: {type(invocation).__name__}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _meta(ws: "WorkspaceSnapshot", channel: str) -> dict[str, Any]:
    """Return the sub-dict of ``ws.metadata`` for a given evaluator channel."""
    metadata = getattr(ws, "metadata", None) or {}
    value = metadata.get(channel, {})
    if not isinstance(value, dict):
        return {}
    return value


def _resolve_callable(ref: str) -> Any:
    """Resolve ``pkg.mod:name`` or ``pkg.mod.name`` to a callable."""
    if ":" in ref:
        module_path, _, attr = ref.partition(":")
    else:
        if "." not in ref:
            raise ValueError(f"callable_ref must be dotted: {ref!r}")
        module_path, _, attr = ref.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _sidecar_path(path: str) -> str:
    """Return the canonical rootknot sidecar path for an artifact."""
    if "/" in path:
        head, _, name = path.rpartition("/")
        return f"{head}/.{name}.rootknot.json"
    return f".{path}.rootknot.json"


# RACT 0.4.0
