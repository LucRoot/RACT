"""Aider Polyglot subset runner — module_07 (v0.4.0).

SUBSTRATE §9 (Eval-First). One problem per invocation. Every attempt
opens a fresh ``StepTransaction`` (module_02) with a
``CapabilityManifest`` (module_03) attached. The output is a unified
diff (Aider Polyglot canonical shape); passing requires the hidden
test suite to be green after at most two attempts with test-feedback
between them (module_07 plan text; SUBSTRATE §2.2).

Reference sources:

- Aider Polyglot public repository:
  ``https://github.com/Aider-AI/aider`` (benchmark subdirectory).
- Aider Polyglot leaderboard:
  ``https://aider.chat/docs/leaderboards/``.
- OpenHands SDK per-instance execution:
  ``https://github.com/All-Hands-AI/OpenHands`` (the container-per-
  instance pattern reused here for the SWE-bench Lite runner).

The runner ships two dispatch paths:

- ``provider="fake"`` (default in CI): loads a canned event stream
  from ``evals/fixtures/providers/aider_polyglot/<problem_id>.jsonl``
  and produces a deterministic outcome. This proves the harness
  parses, dispatches, and reports correctly without live-provider
  cost (Lateral Chain branch B, module_07).

- ``provider=<live-name>`` (nightly, gated by ``RACT_EVAL_ENABLED``
  per Lateral Chain branch B, module_07): clones the upstream
  reference repository into ``.tmp/polyglot/<problem_id>/`` and hands
  the problem statement to the RACT loop. The live path is
  operator-triggered work; module_07's DoD only requires that this
  path exists and returns a ``SKIPPED`` result with a specific reason
  when the upstream registry is unreachable (Lateral Chain branch A).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ract.core.transaction import (
    ResourceBudget,
    StepTransaction,
    new_step_id,
    open_transaction,
)


PolyglotOutcome = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True)
class PolyglotAttempt:
    """One attempt at a Polyglot problem."""

    attempt_index: int  # 1 or 2
    unified_diff: str
    hidden_tests_passed: bool
    feedback: str = ""


@dataclass(frozen=True)
class PolyglotResult:
    """Terminal outcome of a Polyglot problem invocation."""

    problem_id: str
    provider: str
    outcome: PolyglotOutcome
    attempts: tuple[PolyglotAttempt, ...] = ()
    skip_reason: str = ""
    transaction_step_ids_hex: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"


@dataclass(frozen=True)
class FixtureEventStream:
    """A replayed event stream from ``evals/fixtures/providers/…``.

    Schema version 2 per ``docs/EVENTS.md`` (module_06 bumped 1 → 2).
    Every event dict on load has at minimum a ``kind`` and a
    ``payload``; the stream's leading record carries a
    ``schema_version`` marker so drift is detected.
    """

    schema_version: str
    events: tuple[dict[str, Any], ...]

    @classmethod
    def load(cls, path: Path) -> "FixtureEventStream":
        raw: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw.append(json.loads(line))
        if not raw:
            raise ValueError(f"fixture stream {path} is empty")
        header = raw[0]
        schema_version = str(header.get("schema_version", "1"))
        events = tuple(raw[1:]) if header.get("kind") is None else tuple(raw)
        return cls(schema_version=schema_version, events=events)


# ---------------------------------------------------------------------------
# Fixture-provider dispatch
# ---------------------------------------------------------------------------


def _extract_diff_from_stream(stream: FixtureEventStream, attempt_index: int) -> str:
    """Return the recorded unified diff for the given attempt.

    A fixture stream encodes each attempt as a ``response.received``
    event whose payload carries ``attempt_index`` and ``unified_diff``.
    If the stream carries no matching event, the empty diff is
    returned (which the caller then reports as ``failed``).
    """
    for event in stream.events:
        if event.get("kind") != "response.received":
            continue
        payload = event.get("payload") or {}
        if int(payload.get("attempt_index", 0)) == attempt_index:
            return str(payload.get("unified_diff", ""))
    return ""


def _hidden_tests_passed_from_stream(
    stream: FixtureEventStream, attempt_index: int
) -> bool:
    """Return the recorded hidden-test-suite outcome for the attempt."""
    for event in stream.events:
        if event.get("kind") != "tool.result":
            continue
        payload = event.get("payload") or {}
        if int(payload.get("attempt_index", 0)) != attempt_index:
            continue
        if payload.get("tool") != "hidden_test_suite":
            continue
        return bool(payload.get("passed", False))
    return False


def _feedback_from_stream(stream: FixtureEventStream, attempt_index: int) -> str:
    """Return the recorded test-feedback string handed to the next attempt."""
    for event in stream.events:
        if event.get("kind") != "tool.result":
            continue
        payload = event.get("payload") or {}
        if int(payload.get("attempt_index", 0)) != attempt_index:
            continue
        return str(payload.get("stdout", ""))
    return ""


# ---------------------------------------------------------------------------
# Live-provider dispatch (deferred; returns SKIPPED without registry access)
# ---------------------------------------------------------------------------


def _try_clone_upstream(problem_id: str, workspace: Path) -> tuple[bool, str]:
    """Attempt to shallow-clone the Aider Polyglot reference repository.

    Returns ``(ok, reason)``. On any failure — offline, permission,
    upstream 404 — returns ``(False, "<why>")`` and the caller reports
    ``SKIPPED``. Lateral Chain branch A (module_07): unreachable
    upstream is counted, never silently green.
    """
    target = workspace / ".tmp" / "polyglot" / problem_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return True, "already-cloned"
    result = subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            "--filter=blob:none",
            "https://github.com/Aider-AI/aider.git",
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"git-clone-failed: {result.stderr.strip()[:200]}"
    return True, "cloned"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class RunConfig:
    """Runner configuration."""

    workspace: Path
    subset_path: Path
    provider: str = "fake"
    fixtures_root: Path | None = None
    parent_snapshot: str = "0" * 40  # placeholder for unversioned callers
    manifest: object | None = None


def run_problem(problem_id: str, config: RunConfig) -> PolyglotResult:
    """Run one Polyglot problem end-to-end and return a ``PolyglotResult``."""
    step_ids: list[str] = []

    if config.provider == "fake":
        fixture_root = (
            config.fixtures_root
            if config.fixtures_root is not None
            else Path("evals/fixtures/providers/aider_polyglot")
        )
        fixture_path = fixture_root / f"{problem_id}.jsonl"
        if not fixture_path.is_file():
            return PolyglotResult(
                problem_id=problem_id,
                provider="fake",
                outcome="skipped",
                skip_reason=f"fixture-not-found: {fixture_path}",
            )
        stream = FixtureEventStream.load(fixture_path)
        attempts: list[PolyglotAttempt] = []
        for attempt_index in (1, 2):
            step_id = new_step_id()
            step_ids.append(step_id.hex())
            _txn = open_transaction(
                step_id=step_id,
                parent_snapshot=config.parent_snapshot,
                worktree_path=config.workspace,
                postconditions=(),
                timeout_seconds=120,
                budget=ResourceBudget(cpu=1.0, memory_mb=1024, wall_seconds=120),
                manifest=config.manifest,
            )
            assert isinstance(_txn, StepTransaction)
            diff = _extract_diff_from_stream(stream, attempt_index)
            passed = _hidden_tests_passed_from_stream(stream, attempt_index)
            feedback = (
                _feedback_from_stream(stream, attempt_index) if not passed else ""
            )
            attempts.append(
                PolyglotAttempt(
                    attempt_index=attempt_index,
                    unified_diff=diff,
                    hidden_tests_passed=passed,
                    feedback=feedback,
                )
            )
            if passed:
                break
        outcome: PolyglotOutcome = (
            "passed" if any(a.hidden_tests_passed for a in attempts) else "failed"
        )
        return PolyglotResult(
            problem_id=problem_id,
            provider="fake",
            outcome=outcome,
            attempts=tuple(attempts),
            transaction_step_ids_hex=tuple(step_ids),
        )

    # Live-provider path: gated at CI wiring (Lateral B). Without live
    # keys or upstream reachability, the runner returns SKIPPED with a
    # specific reason so the CI summary counts it (Lateral A).
    ok, reason = _try_clone_upstream(problem_id, config.workspace)
    if not ok:
        return PolyglotResult(
            problem_id=problem_id,
            provider=config.provider,
            outcome="skipped",
            skip_reason=reason,
        )
    return PolyglotResult(
        problem_id=problem_id,
        provider=config.provider,
        outcome="skipped",
        skip_reason="live-provider-not-wired-in-module_07",
    )


def load_subset(subset_path: Path) -> list[dict[str, Any]]:
    """Load and return the pinned problem list."""
    data = json.loads(subset_path.read_text(encoding="utf-8"))
    problems = data.get("problems", [])
    if not isinstance(problems, list):
        raise ValueError("subset.json 'problems' must be a list")
    return problems


def run_subset(config: RunConfig) -> list[PolyglotResult]:
    """Run every pinned problem and return the list of results."""
    problems = load_subset(config.subset_path)
    return [run_problem(p["id"], config) for p in problems]


# RACT 0.4.0
