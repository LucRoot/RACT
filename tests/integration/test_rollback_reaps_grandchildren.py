"""Integration -- rollback reaps parent + child + grandchild.

v0.5.1 wiring module_05 (Lens C C-03 closure). The primitive test
(``tests/unit/test_substrate_process_group_kill.py``) locks
``process_group.kill_tree`` in isolation. This one locks the WIRE:
a step_runner that spawns via
``SubstrateLoop.spawn_step_subprocess`` and returns a subprocess
still running when a rollback path fires must have EVERY descendant
reaped by ``SubstrateLoop._reap_active_processes`` (invoked from
``dispose(success=False)`` per module_05).

The parent -> child -> grandchild chain is a python subprocess that
uses ``subprocess.Popen`` twice more (POSIX: fork+exec; Windows:
Popen). The test asserts all three PIDs are dead after rollback.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ract.executor.loop import SubstrateLoop
from ract.executor.worktree import WorktreeManager


_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _chain_script(pid_file: Path) -> str:
    return textwrap.dedent(f"""\
        import os, sys, time, subprocess
        pf = r"{pid_file!s}"
        role = sys.argv[1] if len(sys.argv) > 1 else "parent"
        with open(pf, "a") as f:
            f.write(role + ":" + str(os.getpid()) + "\\n")
            f.flush()
        if role == "parent":
            child = subprocess.Popen([sys.executable, __file__, "child"])
            time.sleep(60)
        elif role == "child":
            grandchild = subprocess.Popen([sys.executable, __file__, "grandchild"])
            time.sleep(60)
        else:
            time.sleep(60)
        """)


def _read_pids(pid_file: Path, expected: int, timeout: float = 15.0) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid_file.exists():
            lines = [
                line.strip()
                for line in pid_file.read_text().splitlines()
                if line.strip()
            ]
            if len(lines) >= expected:
                out: dict[str, int] = {}
                for line in lines[:expected]:
                    role, _, pid_str = line.partition(":")
                    out[role] = int(pid_str)
                return out
        time.sleep(0.1)
    raise TimeoutError(
        f"expected {expected} pids, got "
        f"{pid_file.read_text() if pid_file.exists() else '<missing>'}"
    )


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
    }
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=str(root), check=True, env=env, capture_output=True,
    )
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=str(root), check=True, env=env,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=str(root),
        check=True, env=env, capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root),
        capture_output=True, text=True, check=True, env=env,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(90)
def test_dispose_unsuccessful_reaps_full_tree(tmp_path: Path) -> None:
    """A three-deep tree spawned via spawn_step_subprocess is reaped
    end-to-end by ``dispose(success=False)``.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    pid_file = tmp_path / "pids.txt"
    script_file = tmp_path / "chain.py"
    script_file.write_text(_chain_script(pid_file), encoding="utf-8")

    handle = loop.spawn_step_subprocess(
        [sys.executable, str(script_file), "parent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        pids = _read_pids(pid_file, expected=3, timeout=20.0)
        assert "parent" in pids and "child" in pids and "grandchild" in pids
        for role, pid in pids.items():
            assert _pid_alive(pid), f"{role} pid={pid} not alive before rollback"

        # Trigger rollback via unsuccessful dispose.
        loop.dispose(success=False, reason="test_rollback_reaps")

        # Poll for reap.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if not any(_pid_alive(pid) for pid in pids.values()):
                break
            time.sleep(0.25)

        survivors = {r: p for r, p in pids.items() if _pid_alive(p)}
        assert not survivors, (
            f"rollback failed to reap descendant tree: {survivors}. "
            "This is the Lens C C-03 defect module_05 fixes."
        )
        # And the loop's registry cleared.
        assert loop._active_process_handles == []
    finally:
        # Defensive cleanup.
        from ract.executor.process_group import kill_tree

        if handle.is_running():
            try:
                kill_tree(handle)
            except Exception:  # noqa: BLE001
                pass


@pytest.mark.timeout(60)
def test_run_step_exception_reaps_tree(tmp_path: Path) -> None:
    """An uncaught exception in the step_runner triggers reap."""
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    pid_file = tmp_path / "pids.txt"
    script_file = tmp_path / "chain.py"
    # Two-deep chain (parent + child) for a shorter test.
    script_file.write_text(
        textwrap.dedent(f"""\
            import os, sys, time
            with open(r"{pid_file!s}", "a") as f:
                f.write("child:" + str(os.getpid()) + "\\n")
                f.flush()
            time.sleep(60)
        """),
        encoding="utf-8",
    )

    from ract.executor.loop import SubstrateStepSpec

    def _runner(wt, container):
        loop.spawn_step_subprocess(
            [sys.executable, str(script_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for the child to write its pid.
        _read_pids(pid_file, expected=1, timeout=10.0)
        raise RuntimeError("simulated step_runner failure")

    spec = SubstrateStepSpec()

    try:
        with pytest.raises(RuntimeError, match="simulated"):
            loop.run_step(spec, _runner)
    finally:
        pass

    pids = _read_pids(pid_file, expected=1, timeout=1.0)
    child_pid = pids["child"]

    # Poll for reap (should be near-instant after exception unwind).
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if not _pid_alive(child_pid):
            break
        time.sleep(0.25)

    assert not _pid_alive(child_pid), (
        f"child pid={child_pid} survived run_step exception; the "
        "except-block reaper did not fire."
    )
    assert loop._active_process_handles == []


# ---------------------------------------------------------------------------
# SP Q2 amendment: post-condition-fail and commit-fail rollback reap
# ---------------------------------------------------------------------------


def _spawn_and_wait_pid(loop, tmp_path: Path) -> tuple[Path, int]:
    """Helper: launch a long-sleep child via spawn_step_subprocess and
    return the pid_file path + child pid."""
    pid_file = tmp_path / f"pids_{os.getpid()}_{time.time_ns()}.txt"
    script_file = tmp_path / f"child_{time.time_ns()}.py"
    script_file.write_text(
        textwrap.dedent(f"""\
            import os, time
            with open(r"{pid_file!s}", "a") as f:
                f.write("child:" + str(os.getpid()) + "\\n")
                f.flush()
            time.sleep(60)
        """),
        encoding="utf-8",
    )
    loop.spawn_step_subprocess(
        [sys.executable, str(script_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pids = _read_pids(pid_file, expected=1, timeout=10.0)
    return pid_file, pids["child"]


@pytest.mark.timeout(60)
def test_postcondition_failure_reaps_tree(tmp_path: Path) -> None:
    """A required post-condition returning ok=False triggers rollback
    which MUST reap the tree (Lens C C-03 rollback path).
    """
    from dataclasses import dataclass, field
    from ract.core.loop import WorkspaceSnapshot
    from ract.executor.loop import SubstrateStepSpec

    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    # Failing predicate stub -- matches AcceptancePredicate shape the loop
    # calls: .required (bool) + .evaluate(snapshot) -> object with .ok +
    # .reason.
    @dataclass
    class _Result:
        ok: bool
        reason: str = ""

    @dataclass
    class _AlwaysFail:
        required: bool = True
        _tag: str = "always_fail"

        def evaluate(self, snapshot) -> _Result:
            return _Result(ok=False, reason="test-forced fail")

    child_pid_holder: dict[str, int] = {}

    def _runner(wt, container):
        _, pid = _spawn_and_wait_pid(loop, tmp_path)
        child_pid_holder["pid"] = pid
        return WorkspaceSnapshot(files={})

    spec = SubstrateStepSpec(predicates=(_AlwaysFail(),))
    loop.run_step(spec, _runner)

    child_pid = child_pid_holder["pid"]
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if not _pid_alive(child_pid):
            break
        time.sleep(0.25)

    assert not _pid_alive(child_pid), (
        f"child pid={child_pid} survived post-condition rollback"
    )
    assert loop._active_process_handles == []


@pytest.mark.timeout(60)
def test_commit_failure_reaps_tree(tmp_path: Path) -> None:
    """A commit failure (raised from WorktreeManager.commit) triggers
    rollback which MUST reap the tree.
    """
    from unittest.mock import patch
    from ract.core.loop import WorkspaceSnapshot
    from ract.executor.loop import SubstrateStepSpec

    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    child_pid_holder: dict[str, int] = {}

    def _runner(wt, container):
        _, pid = _spawn_and_wait_pid(loop, tmp_path)
        child_pid_holder["pid"] = pid
        return WorkspaceSnapshot(files={})

    spec = SubstrateStepSpec()

    with patch.object(
        loop.worktrees,
        "commit",
        side_effect=RuntimeError("simulated commit failure"),
    ):
        loop.run_step(spec, _runner)

    child_pid = child_pid_holder["pid"]
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if not _pid_alive(child_pid):
            break
        time.sleep(0.25)

    assert not _pid_alive(child_pid), (
        f"child pid={child_pid} survived commit-failure rollback"
    )
    assert loop._active_process_handles == []


# RACT 0.5.1
