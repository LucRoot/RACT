"""Integration test -- step_runner spawn consumes sandbox env.

v0.5.1 wiring module_05 (module_04 SP Q5 defer closure). The
enforced Linux + macOS sandbox backends render the filtered env
onto ``BwrapCommand.env`` / ``SeatbeltProfile.env``; module_04's
build closed the render side but left the consumption side open
(the Popen(env=) call at the step_runner spawn site). This test
proves the wire holds: a step_runner that spawns via
``substrate_loop.spawn_step_subprocess`` receives the backend's
filtered env, and credentials the sandbox stripped never reach
the child.

Uses the Windows unenforced stub for cross-platform CI coverage
(the enforced backends are Linux/macOS-only and would require the
respective kernel primitives). The test's discriminator is not
which BACKEND runs but whether the LOOP correctly captures
``_current_sandbox_env`` into ``run_step`` and hands it off to
``spawn_step_subprocess``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.process_group import ProcessGroupHandle
from ract.executor.worktree import WorktreeManager
from ract.security.manifest import CapabilityManifest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _real_manifest() -> CapabilityManifest:
    """A minimal admissible manifest so open_transaction's isinstance
    check passes; the sandbox backend used in this file is a fake that
    ignores manifest content beyond the type gate."""
    return CapabilityManifest(
        run_id="module_05-env-consume-test",
        env={"passthrough": []},
    )


@dataclass
class _FakeSandboxContext:
    """Stand-in for BwrapCommand / SeatbeltProfile with .env set."""

    env: dict[str, str] = field(default_factory=dict)


class _FakeSandboxBackend:
    """A backend whose ``enter`` yields a context with a filtered env."""

    def __init__(self, filtered_env: dict[str, str]) -> None:
        self._filtered_env = filtered_env
        self.enter_call_count = 0

    name = "test-fake"
    enforced = True

    @contextmanager
    def enter(self, manifest, worktree, container=None, *, step_id):
        self.enter_call_count += 1
        yield _FakeSandboxContext(env=dict(self._filtered_env))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _env_git() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=str(root), check=True, env=_env_git(), capture_output=True,
    )
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=str(root), check=True, env=_env_git(),
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=str(root),
        check=True, env=_env_git(), capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True,
        text=True, check=True, env=_env_git(),
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_step_captures_sandbox_env_for_spawn(tmp_path: Path) -> None:
    """Under sandbox entry, ``_current_sandbox_env`` reflects the
    backend's ``.env`` field for the duration of the step_runner call.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    filtered = {"PATH": "/safe/path", "ONLY_SURVIVOR": "yes"}
    backend = _FakeSandboxBackend(filtered_env=filtered)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
        manifest=_real_manifest(),
        sandbox_backend=backend,
    )

    captured_env: dict[str, object] = {}

    from ract.core.loop import WorkspaceSnapshot

    def _runner(wt, container):
        # Assert the loop captured the sandbox env BEFORE step_runner
        # was called.
        captured_env["at_runtime"] = dict(loop._current_sandbox_env or {})
        return WorkspaceSnapshot(files={})

    spec = SubstrateStepSpec()
    loop.run_step(spec, _runner)

    # Backend was entered exactly once.
    assert backend.enter_call_count == 1
    # The env was captured for the runner's duration.
    assert captured_env["at_runtime"] == filtered
    # And reset to None after the context exited.
    assert loop._current_sandbox_env is None


def test_spawn_step_subprocess_inside_step_carries_sandbox_env(
    tmp_path: Path,
) -> None:
    """Full closure: sandbox enter -> _current_sandbox_env set ->
    step_runner calls spawn_step_subprocess -> spawn() gets the env.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    filtered = {"PATH": "/safe", "SAFE_ONLY": "1"}
    backend = _FakeSandboxBackend(filtered_env=filtered)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
        manifest=_real_manifest(),
        sandbox_backend=backend,
    )

    from ract.core.loop import WorkspaceSnapshot

    captured_env: dict[str, object] = {}

    def _fake_spawn(argv, *, env=None, cwd=None, stdin=None, stdout=None, stderr=None):
        captured_env["env"] = env

        class _FakePopen:
            pid = 42

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        return ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=42,
            argv=tuple(argv),
        )

    def _runner(wt, container):
        with patch("ract.executor.loop.spawn", side_effect=_fake_spawn):
            loop.spawn_step_subprocess([sys.executable, "-c", "pass"])
        return WorkspaceSnapshot(files={})

    spec = SubstrateStepSpec()
    loop.run_step(spec, _runner)

    assert captured_env["env"] == filtered, (
        "spawn_step_subprocess did not consume the sandbox env "
        "captured at run_step boundary -- module_04 SP Q5 defer "
        "regression."
    )


def test_windows_stub_shape_no_sandbox_env_falls_through(
    tmp_path: Path,
) -> None:
    """A backend that yields a context with no ``.env`` attribute
    (Windows unenforced stub yields None) leaves
    ``_current_sandbox_env`` unset, and spawn falls through to
    parent-env inherit.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)

    class _StubBackend:
        name = "stub"
        enforced = False

        @contextmanager
        def enter(self, manifest, worktree, container=None, *, step_id):
            yield None  # Windows stub yields None from enter.

    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
        manifest=_real_manifest(),
        sandbox_backend=_StubBackend(),
    )

    from ract.core.loop import WorkspaceSnapshot

    captured_env: dict[str, object] = {}

    def _fake_spawn(argv, *, env=None, **kwargs):
        captured_env["env"] = env

        class _FakePopen:
            pid = 43

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        return ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=43,
            argv=tuple(argv),
        )

    def _runner(wt, container):
        with patch("ract.executor.loop.spawn", side_effect=_fake_spawn):
            loop.spawn_step_subprocess([sys.executable, "-c", "pass"])
        return WorkspaceSnapshot(files={})

    spec = SubstrateStepSpec()
    loop.run_step(spec, _runner)

    # Stub yielded None -> _current_sandbox_env stays None -> env=None
    # to spawn (parent env inherit).
    assert captured_env["env"] is None


# RACT 0.5.1
