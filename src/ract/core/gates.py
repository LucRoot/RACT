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

import fnmatch
import importlib
import importlib.util
import shutil
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
    RelatedFileCoverageInvocation,
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


def evaluate_related_file_coverage(
    invocation: RelatedFileCoverageInvocation, ws: "WorkspaceSnapshot"
) -> PredicateResult:
    """Verify a coupling-map link between two file globs against the diff.

    Reads ``ws.metadata['changed_files']`` — an iterable of forward-slash
    POSIX paths modified since the parent snapshot. When any file
    matching ``source_glob`` was touched, at least one file matching
    ``must_also_touch_glob`` must also be present. When no source file
    was touched, the coupling is vacuously satisfied. When the diff
    channel is missing, the predicate resolves to ``ok=False``.
    """
    started = time.perf_counter_ns()
    metadata = getattr(ws, "metadata", None) or {}
    if "changed_files" not in metadata:
        return PredicateResult(
            ok=False,
            reason=(
                "no ws.metadata['changed_files'] channel; cannot evaluate "
                "related_file_coverage"
            ),
            evidence={
                "source_glob": invocation.source_glob,
                "must_also_touch_glob": invocation.must_also_touch_glob,
            },
            duration_ns=time.perf_counter_ns() - started,
        )
    raw = metadata.get("changed_files") or ()
    changed = [str(p).replace("\\", "/") for p in raw]

    source_hits = _fnmatch_hits(changed, invocation.source_glob)
    if not source_hits:
        return PredicateResult(
            ok=True,
            reason=(
                f"no changes matching source_glob {invocation.source_glob!r}; "
                "coupling vacuously satisfied"
            ),
            evidence={
                "source_glob": invocation.source_glob,
                "must_also_touch_glob": invocation.must_also_touch_glob,
                "source_hits": [],
                "target_hits": [],
            },
            duration_ns=time.perf_counter_ns() - started,
        )

    target_hits = _fnmatch_hits(changed, invocation.must_also_touch_glob)
    if not target_hits:
        return PredicateResult(
            ok=False,
            reason=(
                f"modified {source_hits!r} but not {invocation.must_also_touch_glob!r}"
            ),
            evidence={
                "source_glob": invocation.source_glob,
                "must_also_touch_glob": invocation.must_also_touch_glob,
                "source_hits": source_hits,
                "target_hits": [],
                "rationale": invocation.rationale,
            },
            duration_ns=time.perf_counter_ns() - started,
        )

    return PredicateResult(
        ok=True,
        reason=(f"coupling satisfied: touched {source_hits!r} and {target_hits!r}"),
        evidence={
            "source_glob": invocation.source_glob,
            "must_also_touch_glob": invocation.must_also_touch_glob,
            "source_hits": source_hits,
            "target_hits": target_hits,
            "rationale": invocation.rationale,
        },
        duration_ns=time.perf_counter_ns() - started,
    )


def check_invocation_available(
    invocation: PredicateInvocation,
) -> tuple[bool, str]:
    """Return ``(is_available, reason)`` for one invocation's verifier.

    v0.5.1 spec-completeness module_07 (Lens 2 Delta 2). Called from
    :meth:`ract.core.predicate.AcceptancePredicate.available` and,
    transitively, from :func:`ract.core.loop.build_loop_state` BEFORE
    the loop enters step one so a missing verifier surfaces as
    :class:`~ract.core.predicate.VerifierUnavailable` at construction
    rather than as a stream of ``ok=False`` at evaluation time.

    Dispatch:

    - :class:`PytestInvocation`: ``pytest`` binary present on
      ``PATH`` (``shutil.which``). Even though the built-in
      :func:`evaluate_pytest` reads from
      ``ws.metadata['pytest']`` and never invokes pytest itself,
      the source-of-truth for a *fresh* run in production is a
      pytest execution that populates that channel; a runtime
      lacking pytest cannot ever populate the channel.
    - :class:`MypyInvocation`: ``mypy`` binary present on
      ``PATH``. Same reasoning as pytest.
    - :class:`HypothesisInvocation`: ``hypothesis`` importable
      (``importlib.util.find_spec``). Hypothesis is a library, not
      a binary; ``find_spec`` is the module-level analogue of
      ``shutil.which``.
    - :class:`AssertionInvocation`: ``callable_ref`` resolves
      (:func:`_resolve_callable`). A ``ModuleNotFoundError`` or
      ``AttributeError`` at loop-entry time is the sharpest
      possible signal that this predicate would fail every
      iteration until T5.
    - :class:`ArtifactInvocation`: always available (the check is
      "does the file exist in the snapshot?", which is intrinsic
      to the snapshot and has no external dependency).
    - :class:`RelatedFileCoverageInvocation`: always available
      (the check is "did the diff touch a coupled glob?", which
      reads ``ws.metadata['changed_files']`` and has no external
      dependency).

    The check is INTENTIONALLY conservative on the binary-based
    dispatches: a runtime with the binary installed still may
    fail to run the verifier for other reasons (permissions,
    corrupted install). The pre-check catches the missing-binary
    class of failure; it does not attempt to validate the
    binary's operational health.
    """
    if isinstance(invocation, PytestInvocation):
        if shutil.which("pytest") is None:
            return False, "binary 'pytest' not on PATH"
        return True, ""
    if isinstance(invocation, MypyInvocation):
        if shutil.which("mypy") is None:
            return False, "binary 'mypy' not on PATH"
        return True, ""
    if isinstance(invocation, HypothesisInvocation):
        try:
            spec = importlib.util.find_spec("hypothesis")
        except (ImportError, ValueError) as exc:
            return False, f"hypothesis package not importable: {exc}"
        if spec is None:
            return False, "hypothesis package not installed"
        return True, ""
    if isinstance(invocation, AssertionInvocation):
        try:
            _resolve_callable(invocation.callable_ref)
        except (ImportError, AttributeError, ValueError) as exc:
            return (
                False,
                (
                    f"callable_ref {invocation.callable_ref!r} did not resolve: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        return True, ""
    if isinstance(invocation, ArtifactInvocation):
        return True, ""
    if isinstance(invocation, RelatedFileCoverageInvocation):
        return True, ""
    # Unreachable when the invocation union stays closed. Report
    # unavailable + name the shape so a future new-invocation-kind
    # author sees the gap loudly.
    return False, f"no availability check registered for {type(invocation).__name__}"


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
    if isinstance(invocation, RelatedFileCoverageInvocation):
        return evaluate_related_file_coverage(invocation, ws)
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


def _fnmatch_hits(paths: list[str], glob: str) -> list[str]:
    """Return the sorted subset of ``paths`` matching ``glob``.

    Handles brace groups ``{a,b}`` via :func:`_expand_braces` and the
    globstar ``**/`` via a simple rewrite: ``**/`` is dropped so the
    pattern still matches when zero intermediate segments are present,
    and fnmatch's plain ``*`` (which also matches ``/``) covers the
    remainder — including intermediate-segment cases.
    """
    expanded = _expand_braces(glob)
    hits: set[str] = set()
    for pattern in expanded:
        candidates = _globstar_variants(pattern)
        for path in paths:
            if any(fnmatch.fnmatchcase(path, cand) for cand in candidates):
                hits.add(path)
    return sorted(hits)


def _globstar_variants(pattern: str) -> list[str]:
    """Return fnmatch-safe variants of ``pattern`` covering ``**/`` globstar.

    fnmatch has no globstar. Two variants cover the zero-or-many-segment
    semantics of ``**/``: one with ``**/`` dropped (zero segments) and
    one with ``**/`` rewritten to ``*/`` (one-or-many segments; fnmatch
    ``*`` matches ``/``).
    """
    if "**/" not in pattern:
        return [pattern]
    return [pattern.replace("**/", ""), pattern.replace("**/", "*/")]


def _expand_braces(pattern: str) -> list[str]:
    """Expand a single ``{a,b,c}`` group in ``pattern``; return the branches."""
    open_i = pattern.find("{")
    if open_i == -1:
        return [pattern]
    close_i = pattern.find("}", open_i)
    if close_i == -1:
        return [pattern]
    prefix = pattern[:open_i]
    suffix = pattern[close_i + 1 :]
    branches = pattern[open_i + 1 : close_i].split(",")
    result: list[str] = []
    for branch in branches:
        for expanded in _expand_braces(prefix + branch.strip() + suffix):
            result.append(expanded)
    return result


def _sidecar_path(path: str) -> str:
    """Return the canonical rootknot sidecar path for an artifact."""
    if "/" in path:
        head, _, name = path.rpartition("/")
        return f"{head}/.{name}.rootknot.json"
    return f".{path}.rootknot.json"


# RACT 0.4.0
