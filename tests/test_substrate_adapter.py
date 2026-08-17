"""Tests for the module_08 (Path (d)) executor → SubstrateLoop adapter.

SUBSTRATE §3 (Transactional Execution). The shim wraps
``Executor.execute`` at the plan boundary so per-plan-step writes land
inside a worktree-per-step ``StepTransaction``; ``Executor.execute``
internals are unchanged and ``tests/test_executor.py`` remains
authoritative for the executor's per-step behavior.

These tests exercise the shim itself (three tests) and the ``Harness.run``
routing branch that dispatches to it (four tests).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ract.executor import ExecutionReport
from ract.executor.substrate_adapter import run_via_substrate
from ract.harness import Harness
from ract.manager import Plan, Step
from ract.rooted import Rooted


# ---------------------------------------------------------------------------
# Test doubles (mirror tests/test_executor.py's FakeAdapter / FakeRouter)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, response_content: str = "hello world\n") -> None:
        self._response_content = response_content

    @property
    def name(self) -> str:
        return "fake"

    def capabilities(self) -> set[str]:
        return {"chat"}

    def input_cost_per_1k(self) -> float | None:
        return None

    def output_cost_per_1k(self) -> float | None:
        return None

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        return Rooted(
            value={"choices": [{"message": {"content": self._response_content}}]},
            assumption="fake adapter responds",
            confidence=1.0,
            provenance=["fake_adapter.complete"],
        )


class _FakeRouter:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self._adapter = adapter

    def select_for_hint(self, hint: str) -> Rooted[Any]:
        return Rooted(
            value=self._adapter,
            assumption="fake router has an adapter",
            confidence=1.0,
            provenance=["fake_router.select_for_hint"],
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted[Any]]:
        return []

    def health_check(self, slot_id: str) -> Rooted[bool]:
        return Rooted(
            value=True,
            assumption="fake router always reports healthy",
            confidence=1.0,
            provenance=["fake_router.health_check"],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    """Init ``root`` as a git repo with one seed commit so the substrate
    loop's git preconditions are satisfied."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True, env=env)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=root, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


def _write_config(root: Path, extra: dict[str, Any] | None = None) -> Path:
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "manager.txt").write_text("You are the manager.", encoding="utf-8")
    cfg: dict[str, Any] = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "local-model",
            },
        },
        "prompts_dir": "prompts",
    }
    if extra:
        cfg.update(extra)
    path = root / "ract.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _plan_writing(artifact: str = "hello.txt") -> Plan:
    return Plan(
        assumption="test",
        confidence=0.9,
        steps=[
            Step(
                action="write hello",
                provider_hint="chat",
                expected_artifact=artifact,
            )
        ],
    )


def _build_harness(root: Path, cfg_extra: dict[str, Any] | None = None) -> Harness:
    cfg_path = _write_config(root, cfg_extra)
    h_rooted = Harness.from_config_path(cfg_path)
    assert h_rooted.is_ok(), h_rooted.error
    h = h_rooted.unwrap()
    # Give the harness a deterministic fake adapter through its router.
    h.executor.router = _FakeRouter(_FakeAdapter(response_content="hello!\n"))
    return h


# ---------------------------------------------------------------------------
# Shim tests
# ---------------------------------------------------------------------------


def test_substrate_adapter_runs_step_inside_worktree(tmp_path):
    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path)

    captured_dirs: list[Path] = []
    original_write = harness.executor._write_artifact

    def spy_write(expected_artifact: str, content: str) -> None:
        captured_dirs.append(Path(harness.executor.project_dir))
        original_write(expected_artifact, content)

    harness.executor._write_artifact = spy_write  # type: ignore[assignment]

    plan = _plan_writing("hello.txt")
    result = run_via_substrate(harness, "write hello", plan)
    assert result.is_ok(), result.error

    # During the closure the executor was pointed at a worktree, not the repo root.
    assert captured_dirs, "spy did not record any writes"
    for d in captured_dirs:
        assert d != tmp_path, "write landed in project root, not worktree"
        # SubstrateLoop's default worktree root is <repo>/.git/ract-worktrees/<hex>.
        assert ".git" in d.parts and "ract-worktrees" in d.parts

    # After the transaction commits, the write is visible on the step branch.
    branches = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "branch", "--list", "rootact/step/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert branches, "expected at least one rootact/step/* branch after commit"


def test_substrate_adapter_project_dir_restored_after_closure(tmp_path):
    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path)
    original_project_dir = harness.executor.project_dir

    def blow_up(expected_artifact: str, content: str) -> None:
        raise RuntimeError("boom inside closure")

    harness.executor._write_artifact = blow_up  # type: ignore[assignment]

    plan = _plan_writing("bomb.txt")
    # The Executor propagates the underlying RuntimeError; the shim's
    # ``_rebind_project_dir`` context manager MUST still restore
    # ``project_dir`` on the way out. The exception is the test's oracle;
    # what we care about is the finally-block invariant.
    with pytest.raises(RuntimeError, match="boom inside closure"):
        run_via_substrate(harness, "trigger a raise", plan)
    assert harness.executor.project_dir == original_project_dir


def test_substrate_adapter_rebinds_every_captured_helper(tmp_path):
    """Every executor-held helper that carries a ``project_dir`` attribute
    must be rebound to the worktree for the duration of the closure and
    restored afterward. Retroactive audit D6 (2026-07-27) surfaced
    ``LoadBearingGuard`` as an uncovered case; this test pins the full
    enumeration so a future helper is a visible test failure rather than
    a silent invariant break.
    """
    from ract.duplication_guard import DuplicationGuard
    from ract.novelty_budget import NoveltyBudget
    from ract.compression_novelty_detector import CompressionNoveltyDetector

    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path)
    # Give the executor the full complement of helpers the shim claims
    # to rebind. Each helper captures project_dir at construction time,
    # so an uncovered rebind would leave the captured path pointing at
    # tmp_path (the parent) while the executor writes to the worktree.
    harness.executor.duplication_guard = DuplicationGuard(project_dir=tmp_path)
    harness.executor.novelty_budget = NoveltyBudget(project_dir=tmp_path)
    harness.executor.compression_novelty_detector = CompressionNoveltyDetector(
        project_dir=tmp_path
    )

    originals: dict[str, Path] = {
        "executor": Path(harness.executor.project_dir),
        "diff_applier": Path(harness.executor.diff_applier.project_dir),
        "load_bearing_guard": Path(harness.executor.load_bearing_guard.project_dir),
        "duplication_guard": Path(harness.executor.duplication_guard.project_dir),
        "novelty_budget": Path(harness.executor.novelty_budget.project_dir),
        "compression_novelty_detector": Path(
            harness.executor.compression_novelty_detector.project_dir
        ),
    }

    seen_during_closure: dict[str, Path] = {}
    original_write = harness.executor._write_artifact

    def spy_write(expected_artifact: str, content: str) -> None:
        seen_during_closure["executor"] = Path(harness.executor.project_dir)
        seen_during_closure["diff_applier"] = Path(
            harness.executor.diff_applier.project_dir
        )
        seen_during_closure["load_bearing_guard"] = Path(
            harness.executor.load_bearing_guard.project_dir
        )
        seen_during_closure["duplication_guard"] = Path(
            harness.executor.duplication_guard.project_dir
        )
        seen_during_closure["novelty_budget"] = Path(
            harness.executor.novelty_budget.project_dir
        )
        seen_during_closure["compression_novelty_detector"] = Path(
            harness.executor.compression_novelty_detector.project_dir
        )
        original_write(expected_artifact, content)

    harness.executor._write_artifact = spy_write  # type: ignore[assignment]

    plan = _plan_writing("cover.txt")
    result = run_via_substrate(harness, "cover every helper", plan)
    assert result.is_ok(), result.error

    # During the closure every helper's project_dir pointed at the
    # worktree (not tmp_path). Each helper was rebound in lockstep.
    for name, seen in seen_during_closure.items():
        assert seen != originals[name], (
            f"{name}.project_dir was NOT rebound; still pointed at parent tree "
            f"{originals[name]} during the executor closure. This is the D6 gap."
        )
        assert ".git" in seen.parts and "ract-worktrees" in seen.parts, (
            f"{name}.project_dir was rebound to {seen}, not into the worktree tree"
        )

    # After the transaction commits, every helper's project_dir is restored.
    assert Path(harness.executor.project_dir) == originals["executor"]
    assert Path(harness.executor.diff_applier.project_dir) == originals["diff_applier"]
    assert (
        Path(harness.executor.load_bearing_guard.project_dir)
        == originals["load_bearing_guard"]
    )
    assert (
        Path(harness.executor.duplication_guard.project_dir)
        == originals["duplication_guard"]
    )
    assert (
        Path(harness.executor.novelty_budget.project_dir) == originals["novelty_budget"]
    )
    assert (
        Path(harness.executor.compression_novelty_detector.project_dir)
        == originals["compression_novelty_detector"]
    )


def test_substrate_adapter_rollback_on_postcondition_failure(tmp_path, monkeypatch):
    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path)

    # Force the loop's post-condition evaluator to fail so _finalize
    # rolls back even though the executor closure succeeded.
    from ract.core.predicate import PredicateResult
    from ract.executor.substrate_adapter import SubstrateStepSpec

    class _FailingPredicate:
        required = True

        def evaluate(self, snapshot):  # noqa: ARG002
            return PredicateResult(
                ok=False,
                reason="synthetic post-condition failure",
                duration_ns=0,
            )

    # Patch SubstrateStepSpec at construction time inside the shim so
    # every spec built by run_via_substrate carries the failing
    # predicate. We wrap the real class to preserve every other field.
    real_spec_cls = SubstrateStepSpec

    def _wrap_spec(**kwargs):
        kwargs["predicates"] = (_FailingPredicate(),)
        return real_spec_cls(**kwargs)

    monkeypatch.setattr("ract.executor.substrate_adapter.SubstrateStepSpec", _wrap_spec)

    parent_before = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    plan = _plan_writing("rollme.txt")
    result = run_via_substrate(harness, "test rollback", plan)
    assert not result.is_ok()
    assert "rolled back" in (result.error or "").lower()

    # parent_snapshot on main is unchanged after rollback.
    parent_after = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert parent_after == parent_before


# ---------------------------------------------------------------------------
# Harness.run routing branch
# ---------------------------------------------------------------------------


def _stub_manager_and_executor(
    harness: Harness, plan_json: str, step_content: str
) -> None:
    """Stub the manager provider so ``Harness.run`` gets a plan, and keep
    the executor's FakeRouter (set by _build_harness)."""
    plan_response = {"choices": [{"message": {"content": plan_json}}]}
    harness.manager.provider.complete = MagicMock(
        return_value=Rooted(value=plan_response, assumption="ok", confidence=1.0)
    )
    # Replace the executor's adapter with one that returns step_content.
    harness.executor.router = _FakeRouter(_FakeAdapter(response_content=step_content))


_PLAN_JSON = (
    '{"assumption": "t", "confidence": 0.95, '
    '"steps": [{"action": "write x", "provider_hint": "chat", '
    '"expected_artifact": "out.txt"}]}'
)


def test_harness_run_uses_substrate_loop_when_flag_true(tmp_path):
    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path, cfg_extra={"substrate_loop": True})
    _stub_manager_and_executor(harness, _PLAN_JSON, "content\n")

    fake_report = Rooted(
        value=ExecutionReport(
            intent="w",
            step_results=[],
            assumptions=["t"],
        ),
        assumption="stub",
        confidence=1.0,
        provenance=["stub"],
    )
    with patch(
        "ract.executor.substrate_adapter.run_via_substrate",
        return_value=fake_report,
    ) as mock_adapter:
        harness.run("w")
    assert mock_adapter.called, "substrate adapter should route when flag is True"


def test_harness_run_falls_back_to_legacy_when_flag_false(tmp_path):
    _init_git_repo(tmp_path)
    harness = _build_harness(tmp_path, cfg_extra={"substrate_loop": False})
    _stub_manager_and_executor(harness, _PLAN_JSON, "content\n")

    executor_execute = MagicMock(
        return_value=Rooted(
            value=ExecutionReport(intent="w", step_results=[], assumptions=["t"]),
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
        )
    )
    harness.executor.execute = executor_execute  # type: ignore[assignment]
    with patch("ract.executor.substrate_adapter.run_via_substrate") as mock_adapter:
        harness.run("w")
    assert not mock_adapter.called, "adapter should NOT run when flag is False"
    assert executor_execute.called, "legacy executor should run when flag is False"


def test_harness_run_falls_back_to_legacy_when_workspace_not_git(tmp_path):
    # No git init.
    harness = _build_harness(tmp_path, cfg_extra={"substrate_loop": True})
    _stub_manager_and_executor(harness, _PLAN_JSON, "content\n")

    executor_execute = MagicMock(
        return_value=Rooted(
            value=ExecutionReport(intent="w", step_results=[], assumptions=["t"]),
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
        )
    )
    harness.executor.execute = executor_execute  # type: ignore[assignment]
    with patch("ract.executor.substrate_adapter.run_via_substrate") as mock_adapter:
        harness.run("w")
    assert not mock_adapter.called, "adapter should NOT run on non-git workspace"
    assert executor_execute.called, "legacy executor should run on non-git workspace"


def test_harness_run_falls_back_to_legacy_when_tree_dirty(tmp_path):
    _init_git_repo(tmp_path)
    # Dirty a tracked file.
    (tmp_path / "seed.txt").write_text("dirty\n", encoding="utf-8")

    harness = _build_harness(tmp_path, cfg_extra={"substrate_loop": True})
    _stub_manager_and_executor(harness, _PLAN_JSON, "content\n")

    executor_execute = MagicMock(
        return_value=Rooted(
            value=ExecutionReport(intent="w", step_results=[], assumptions=["t"]),
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
        )
    )
    harness.executor.execute = executor_execute  # type: ignore[assignment]
    with patch("ract.executor.substrate_adapter.run_via_substrate") as mock_adapter:
        harness.run("w")
    assert not mock_adapter.called, "adapter should NOT run on dirty tree"
    assert executor_execute.called, "legacy executor should run on dirty tree"


# RACT 0.4.0
