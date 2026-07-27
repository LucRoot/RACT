"""SWE-bench Lite instance runner — module_07 (v0.4.0).

SUBSTRATE §9 (Eval-First). One instance per invocation. Every attempt
opens a fresh ``StepTransaction`` (module_02) with a
``CapabilityManifest`` (module_03) attached. The output is a git patch
(SWE-bench canonical shape); passing requires the instance's
``FAIL_TO_PASS`` and ``PASS_TO_PASS`` test sets both green after
applying the patch (module_07 plan text; SUBSTRATE §5.2).

Reference sources:

- SWE-bench public site: ``https://www.swebench.com/``.
- SWE-bench repository: ``https://github.com/SWE-bench/SWE-bench``.
- OpenHands V1 SDK per-instance container execution:
  ``https://github.com/All-Hands-AI/OpenHands`` (baseline architecture
  the SWE-bench harness borrows from).

The runner ships two dispatch paths (see ``polyglot/runner.py`` for
the same shape and Lateral Chain rationale).
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


SweBenchOutcome = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True)
class SweBenchAttempt:
    """One attempt at an SWE-bench Lite instance."""

    git_patch: str
    fail_to_pass_ok: bool
    pass_to_pass_ok: bool


@dataclass(frozen=True)
class SweBenchResult:
    """Terminal outcome of an SWE-bench Lite instance invocation."""

    instance_id: str
    provider: str
    outcome: SweBenchOutcome
    attempt: SweBenchAttempt | None = None
    skip_reason: str = ""
    transaction_step_id_hex: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"


@dataclass(frozen=True)
class FixtureEventStream:
    """A replayed event stream from ``evals/fixtures/providers/…``.

    Schema version 2 per ``docs/EVENTS.md`` (module_06 bumped 1 → 2).
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


def _extract_patch(stream: FixtureEventStream) -> str:
    """Return the recorded git patch from the stream."""
    for event in stream.events:
        if event.get("kind") != "response.received":
            continue
        payload = event.get("payload") or {}
        if payload.get("output_shape") == "git_patch":
            return str(payload.get("git_patch", ""))
    return ""


def _extract_test_outcomes(stream: FixtureEventStream) -> tuple[bool, bool]:
    """Return ``(fail_to_pass_ok, pass_to_pass_ok)`` from the stream."""
    fail_to_pass_ok = False
    pass_to_pass_ok = False
    for event in stream.events:
        if event.get("kind") != "tool.result":
            continue
        payload = event.get("payload") or {}
        tool = payload.get("tool")
        if tool == "fail_to_pass":
            fail_to_pass_ok = bool(payload.get("passed", False))
        elif tool == "pass_to_pass":
            pass_to_pass_ok = bool(payload.get("passed", False))
    return fail_to_pass_ok, pass_to_pass_ok


# ---------------------------------------------------------------------------
# Live-provider dispatch (deferred; returns SKIPPED without image access)
# ---------------------------------------------------------------------------


def _try_pull_image(image: str) -> tuple[bool, str]:
    """Attempt to ``docker pull`` the instance image.

    Returns ``(ok, reason)``. On any failure — docker missing,
    registry unreachable, image not found — returns ``(False, "<why>")``
    and the caller reports ``SKIPPED``. Lateral Chain branch A: the
    unreachable image is counted rather than silently green.
    """
    docker = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    if docker.returncode != 0:
        return False, "docker-not-installed"
    pull = subprocess.run(["docker", "pull", image], capture_output=True, text=True)
    if pull.returncode != 0:
        return False, f"docker-pull-failed: {pull.stderr.strip()[:200]}"
    return True, "pulled"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class RunConfig:
    """Runner configuration."""

    workspace: Path
    instances_path: Path
    provider: str = "fake"
    fixtures_root: Path | None = None
    parent_snapshot: str = "0" * 40
    manifest: object | None = None


def run_instance(instance_record: dict[str, Any], config: RunConfig) -> SweBenchResult:
    """Run one SWE-bench Lite instance end-to-end."""
    instance_id = str(instance_record["instance_id"])

    if config.provider == "fake":
        fixture_root = (
            config.fixtures_root
            if config.fixtures_root is not None
            else Path("evals/fixtures/providers/swebench_lite")
        )
        fixture_path = fixture_root / f"{instance_id}.jsonl"
        if not fixture_path.is_file():
            return SweBenchResult(
                instance_id=instance_id,
                provider="fake",
                outcome="skipped",
                skip_reason=f"fixture-not-found: {fixture_path}",
            )
        stream = FixtureEventStream.load(fixture_path)
        step_id = new_step_id()
        _txn = open_transaction(
            step_id=step_id,
            parent_snapshot=config.parent_snapshot,
            worktree_path=config.workspace,
            postconditions=(),
            timeout_seconds=600,
            budget=ResourceBudget(cpu=2.0, memory_mb=4096, wall_seconds=600),
            manifest=config.manifest,
        )
        assert isinstance(_txn, StepTransaction)
        patch = _extract_patch(stream)
        f2p_ok, p2p_ok = _extract_test_outcomes(stream)
        attempt = SweBenchAttempt(
            git_patch=patch,
            fail_to_pass_ok=f2p_ok,
            pass_to_pass_ok=p2p_ok,
        )
        outcome: SweBenchOutcome = "passed" if (f2p_ok and p2p_ok) else "failed"
        return SweBenchResult(
            instance_id=instance_id,
            provider="fake",
            outcome=outcome,
            attempt=attempt,
            transaction_step_id_hex=step_id.hex(),
        )

    image = str(instance_record.get("docker_image", ""))
    if not image:
        return SweBenchResult(
            instance_id=instance_id,
            provider=config.provider,
            outcome="skipped",
            skip_reason="no-docker-image-in-instance-record",
        )
    ok, reason = _try_pull_image(image)
    if not ok:
        return SweBenchResult(
            instance_id=instance_id,
            provider=config.provider,
            outcome="skipped",
            skip_reason=reason,
        )
    return SweBenchResult(
        instance_id=instance_id,
        provider=config.provider,
        outcome="skipped",
        skip_reason="live-provider-not-wired-in-module_07",
    )


def load_instances(instances_path: Path) -> list[dict[str, Any]]:
    """Load and return the pinned instance list."""
    data = json.loads(instances_path.read_text(encoding="utf-8"))
    instances = data.get("instances", [])
    if not isinstance(instances, list):
        raise ValueError("instances.json 'instances' must be a list")
    return instances


def run_instances(config: RunConfig) -> list[SweBenchResult]:
    """Run every pinned instance and return the list of results."""
    instances = load_instances(config.instances_path)
    return [run_instance(inst, config) for inst in instances]


# RACT 0.4.0
