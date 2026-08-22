"""Integration -- SubagentHandle cascade fires on FORCED loop failure.

v0.5.1 spec-completeness module_07 (Lens 2 Delta 3 closure). Ox
Alpha §2 mandatory gate: unit tests of the cascade in isolation are
NOT sufficient. This test spawns a REAL subprocess-backed subagent,
FORCES a non-T1 loop halt end-to-end (via `dispose(success=False)`
AND via `run_step` exception unwind AND via a post-condition
failure), and asserts:

- The subagent's underlying subprocess is reaped end-to-end (PID
  no longer alive after cascade completes).
- The `SubagentHandle.dispose` is invoked with a non-empty reason
  string that identifies the halt cause.
- The trace log records a `subagent.disposed` event with the
  handle's descriptor + reason + outcome.
- The loop's registry is CLEARED after cascade (no leaked handle
  survives into a subsequent run of the reusable loop instance).

Cross-references:

- Ox Alpha pipeline critique §2 (forced-failure integration test
  required for compensator/cascade).
- `_BUILD/audit_2026-08-21c/lens_2_v02_primitive_vs_kairos_wall.md`
  Delta 3 (SubagentHandle cascade — the source-doc audit item this
  module closes).
- Companion primitive locked in isolation:
  `tests/unit/test_subagent_handle_dispatch.py`.
- Sibling wire test for the process-group tree-kill:
  `tests/integration/test_rollback_reaps_grandchildren.py`
  (module_05 Lens C C-03).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.subagent_handle import (
    InlineSubagentHandle,
    SubprocessSubagentHandle,
)
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
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _sleep_subprocess_script(pid_file: Path) -> str:
    return textwrap.dedent(
        f"""\
        import os, sys, time
        with open(r"{pid_file!s}", "a") as f:
            f.write(str(os.getpid()) + "\\n")
            f.flush()
        time.sleep(60)
        """
    )


def _spawn_sleeper(tmp_path: Path, label: str) -> tuple[subprocess.Popen, int]:
    """Spawn a python subprocess that writes its PID and sleeps 60s.

    Returns (popen, pid). The caller wraps the popen in a
    SubprocessSubagentHandle and registers with the loop.
    """
    pid_file = tmp_path / f"pids_{label}_{time.time_ns()}.txt"
    script_file = tmp_path / f"sleeper_{label}_{time.time_ns()}.py"
    script_file.write_text(_sleep_subprocess_script(pid_file), encoding="utf-8")
    popen = subprocess.Popen(
        [sys.executable, str(script_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the child to have started + written its PID.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if pid_file.exists():
            text = pid_file.read_text().strip()
            if text:
                return popen, int(text.splitlines()[0])
        time.sleep(0.05)
    raise TimeoutError(f"sleeper {label} did not write PID within 10s")


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
        cwd=str(root),
        check=True,
        env=env,
        capture_output=True,
    )
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(root),
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"],
        cwd=str(root),
        check=True,
        env=env,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Tests: forced-failure cascade
# ---------------------------------------------------------------------------


@pytest.mark.timeout(90)
def test_dispose_unsuccessful_reaps_subagent_subprocess(tmp_path: Path) -> None:
    """dispose(success=False) cascades SubagentHandle disposal.

    The Ox Alpha §2 forced-failure gate. A real subprocess-backed
    subagent is registered with the loop; the loop is disposed
    UNSUCCESSFULLY (simulating T2/T3/T4/T5/T6/T7/T8/T9); the
    subagent's underlying PID must be dead by the time the cascade
    settles.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    popen, subagent_pid = _spawn_sleeper(tmp_path, "cascade_dispose")
    handle = SubprocessSubagentHandle(
        popen=popen,
        descriptor={"role": "test_whisperer", "label": "forced_failure"},
        kind="subprocess",
    )
    loop.register_subagent_handle(handle)

    assert _pid_alive(subagent_pid), (
        f"subagent PID {subagent_pid} must be alive before cascade"
    )
    assert loop._active_subagent_handles == [handle], (
        "handle must be registered on the loop's cascade list"
    )

    # Force the failure.
    loop.dispose(success=False, reason="test_forced_failure")

    # Poll for reap.
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if not _pid_alive(subagent_pid):
            break
        time.sleep(0.1)

    assert not _pid_alive(subagent_pid), (
        f"subagent PID {subagent_pid} survived dispose(success=False). "
        "The Ox Alpha §2 forced-failure cascade gate is unmet -- the "
        "compensator is dead code."
    )
    # And the registry cleared so a reusable loop instance does not
    # carry the stale handle into the next run.
    assert loop._active_subagent_handles == [], (
        "cascade should clear the registered-handles list"
    )
    # The concrete handle is idempotent-disposed.
    assert not handle.is_alive(), "handle should be marked disposed"


@pytest.mark.timeout(90)
def test_dispose_successful_does_not_reap_subagent(tmp_path: Path) -> None:
    """dispose(success=True) DISCARDS the cascade list without disposal.

    T1 success is not a rollback. The caller's natural cleanup path
    owns subagent teardown on success. The cascade list must be
    cleared (foot-gun prevention for reusable loop instances) but
    the underlying subprocess must NOT be killed by the loop.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    popen, subagent_pid = _spawn_sleeper(tmp_path, "cascade_success")
    handle = SubprocessSubagentHandle(
        popen=popen,
        descriptor={"role": "test_whisperer", "label": "t1_success"},
        kind="subprocess",
    )
    loop.register_subagent_handle(handle)

    try:
        loop.dispose(success=True, reason="T1_SUCCESS")

        # Grace period: the subprocess must still be alive AFTER the
        # cascade because dispose(success=True) discards without
        # calling handle.dispose.
        time.sleep(0.5)
        assert _pid_alive(subagent_pid), (
            f"subagent PID {subagent_pid} should still be alive after "
            "dispose(success=True) -- T1 must not cascade"
        )
        assert loop._active_subagent_handles == [], (
            "T1 dispose must clear the list (foot-gun prevention)"
        )
        assert handle.is_alive(), (
            "handle must remain live on T1 -- caller's natural "
            "cleanup owns teardown on success"
        )
    finally:
        # Test cleanup (loop did NOT dispose the subprocess).
        try:
            popen.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            popen.wait(timeout=5.0)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(60)
def test_run_step_exception_reaps_subagent(tmp_path: Path) -> None:
    """An uncaught exception in the step_runner cascades SubagentHandle.

    Sibling of ``test_rollback_reaps_grandchildren::
    test_run_step_exception_reaps_tree`` -- process handles get
    reaped, AND subagent handles get cascaded on the same exception
    unwind. The forced failure here is a step_runner that raises
    RuntimeError mid-flight AFTER registering a subagent.
    """

    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    popen, subagent_pid = _spawn_sleeper(tmp_path, "cascade_exc")
    handle = SubprocessSubagentHandle(
        popen=popen,
        descriptor={"role": "test_fence", "label": "step_runner_raise"},
        kind="subprocess",
    )

    def _runner(wt, container):
        loop.register_subagent_handle(handle)
        raise RuntimeError("simulated step_runner failure")

    with pytest.raises(RuntimeError, match="simulated"):
        loop.run_step(SubstrateStepSpec(), _runner)

    # Poll for reap.
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if not _pid_alive(subagent_pid):
            break
        time.sleep(0.1)

    assert not _pid_alive(subagent_pid), (
        f"subagent PID {subagent_pid} survived run_step exception. "
        "The exception-path cascade did not fire."
    )
    assert loop._active_subagent_handles == []


@pytest.mark.timeout(60)
def test_inline_subagent_cascades_on_forced_failure(tmp_path: Path) -> None:
    """A NON-subprocess subagent (InlineSubagentHandle) also cascades.

    Guards against the SubprocessSubagentHandle path being the only
    covered shape. A caller with an in-process resource (embedding
    model, thread pool, open network connection) writes a thin
    InlineSubagentHandle adapter and gets the same cascade
    guarantee.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    disposed: list[str] = []

    def _teardown() -> bool:
        disposed.append("cascaded")
        return True

    handle = InlineSubagentHandle(
        teardown=_teardown,
        descriptor={"role": "embedding_sidecar", "label": "cascade_inline"},
        kind="inline",
    )
    loop.register_subagent_handle(handle)

    loop.dispose(success=False, reason="test_forced_inline")

    assert disposed == ["cascaded"], (
        "InlineSubagentHandle.teardown was not invoked during cascade"
    )
    assert loop._active_subagent_handles == []
    assert not handle.is_alive()


@pytest.mark.timeout(90)
def test_cascade_lifo_ordering(tmp_path: Path) -> None:
    """Cascade drains LIFO -- most-recently-registered disposes first.

    Mirrors the CompensatorStack shape. Two InlineSubagentHandles
    register in order (h1, h2); dispose(success=False) invokes
    h2.dispose() BEFORE h1.dispose().
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    order: list[str] = []

    def _mk_teardown(name: str):
        def _tear() -> bool:
            order.append(name)
            return True

        return _tear

    h1 = InlineSubagentHandle(
        teardown=_mk_teardown("h1"),
        descriptor={"role": "first"},
    )
    h2 = InlineSubagentHandle(
        teardown=_mk_teardown("h2"),
        descriptor={"role": "second"},
    )
    loop.register_subagent_handle(h1)
    loop.register_subagent_handle(h2)

    loop.dispose(success=False, reason="lifo_test")
    assert order == ["h2", "h1"], f"cascade must drain LIFO; got {order}"


@pytest.mark.timeout(60)
def test_cascade_survives_individual_dispose_failure(tmp_path: Path) -> None:
    """One handle raising in dispose() does NOT skip the remaining handles.

    Best-effort semantics: a raise is caught, logged, ``ok=False``
    lands in the trace, and the loop continues to the next
    (LIFO-earlier) handle. Guards against a broken subagent adapter
    silently orphaning every subagent below it in the stack.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    invoked: list[str] = []

    def _ok_teardown() -> bool:
        invoked.append("ok")
        return True

    def _raising_teardown() -> bool:
        invoked.append("raise")
        raise RuntimeError("simulated bad subagent")

    h_ok = InlineSubagentHandle(
        teardown=_ok_teardown,
        descriptor={"role": "ok"},
    )
    h_raise = InlineSubagentHandle(
        teardown=_raising_teardown,
        descriptor={"role": "bad"},
    )
    loop.register_subagent_handle(h_ok)
    loop.register_subagent_handle(h_raise)  # LIFO: this disposes first

    loop.dispose(success=False, reason="survive_bad_subagent")

    assert invoked == ["raise", "ok"], (
        f"cascade must continue past a raising handle; got {invoked}"
    )
    assert loop._active_subagent_handles == []


# ---------------------------------------------------------------------------
# SP amendment coverage
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_dispose_no_ops_when_popen_already_exited(tmp_path: Path) -> None:
    """SP amendment (Ox Alpha + cross-family second reviewer D2): dispose short-circuits
    with ``ok=True`` when the underlying Popen is already dead.

    Prior behavior: dispose unconditionally built a ProcessGroupHandle
    and called ``kill_tree`` on a dead PID -- best case a wasted
    syscall + misleading warning; worst case an ok=False event
    misrepresenting a successful teardown. The short-circuit uses
    ``popen.poll() is not None`` as the "already exited" signal.

    Simulates the double-covered case: a Popen registered in both
    the process-handle list AND the subagent-handle list would be
    reaped first by ``_reap_active_processes`` (setting poll() to
    an exit code), then cascaded here -- dispose must return True
    without invoking kill_tree.
    """
    # Start-and-immediately-exit subprocess so poll() has a value.
    popen = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    popen.wait(timeout=10.0)
    assert popen.poll() is not None, "subprocess must have exited"

    handle = SubprocessSubagentHandle(
        popen=popen,
        descriptor={"role": "already_dead", "label": "d2_amendment"},
        kind="subprocess",
    )

    # Direct dispose (not via loop cascade) -- must return True
    # without invoking kill_tree on the dead PID.
    ok = handle.dispose(reason="already_exited")
    assert ok is True, "dispose must return True when the Popen is already dead"
    assert handle._disposed is True


@pytest.mark.timeout(60)
def test_cascade_survives_bad_descriptor_in_event(tmp_path: Path) -> None:
    """SP amendment (Ox Alpha finding): a handle whose descriptor
    causes the ``subagent.disposed`` emit to raise MUST NOT abort
    the cascade -- remaining handles still dispose.

    Belt-and-suspenders test: the emit is already best-effort inside
    :func:`emit_subagent_disposed_event`, but the cascade loop wraps
    the emit call in its OWN try/except so a hypothetical future
    refactor that promotes emit to raise-propagate cannot silently
    break cascade completeness.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    disposed_order: list[str] = []

    class _BadDescriptorTeardown:
        """Object that raises when JSON-serialised (used inside
        descriptor to force emit to raise). Not JSON-encodable."""

        def __repr__(self) -> str:
            return "<bad-descriptor>"

    # Two live handles + one middle handle whose emit will raise
    # if the trace sink JSON-encodes the descriptor.
    def _teardown_ok(name: str):
        def _tear() -> bool:
            disposed_order.append(name)
            return True

        return _tear

    h_last = InlineSubagentHandle(
        teardown=_teardown_ok("last"),
        descriptor={"role": "ok_last"},
    )
    h_middle = InlineSubagentHandle(
        teardown=_teardown_ok("middle"),
        descriptor={"role": "middle", "bad": _BadDescriptorTeardown()},
    )
    h_first = InlineSubagentHandle(
        teardown=_teardown_ok("first"),
        descriptor={"role": "first"},
    )
    loop.register_subagent_handle(h_first)
    loop.register_subagent_handle(h_middle)
    loop.register_subagent_handle(h_last)

    # LIFO: h_last, h_middle, h_first. Even if h_middle's emit path
    # raised (best-effort swallow + belt-and-suspenders cascade
    # wrapper), all three teardown callables must fire.
    loop.dispose(success=False, reason="cascade_survives_bad_descriptor")
    assert disposed_order == ["last", "middle", "first"], (
        f"cascade must survive emit failure; got {disposed_order}"
    )
    assert loop._active_subagent_handles == []


@pytest.mark.timeout(60)
def test_register_dedupes_by_identity_not_equality(tmp_path: Path) -> None:
    """SP amendment (Ox Alpha finding): dedup uses IDENTITY (``is``),
    not value equality (``in``).

    Two dataclass handles with identical field values compare equal
    under ``==`` (dataclass default). The prior ``handle in list``
    dedup would silently drop the second registration. Identity
    dedup correctly rejects only "same object twice" and admits
    two distinct-but-equal handles.
    """
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )

    disposed_names: list[str] = []

    def _mk_teardown(name: str):
        def _tear() -> bool:
            disposed_names.append(name)
            return True

        return _tear

    # Two DISTINCT handle objects; if dataclass __eq__ compared
    # descriptor+kind+_disposed all equal, they'd dedup under
    # ``in``. With identity dedup, both register.
    h1 = InlineSubagentHandle(
        teardown=_mk_teardown("h1"),
        descriptor={"role": "twins"},
        kind="inline",
    )
    h2 = InlineSubagentHandle(
        teardown=_mk_teardown("h2"),
        descriptor={"role": "twins"},
        kind="inline",
    )
    loop.register_subagent_handle(h1)
    loop.register_subagent_handle(h2)
    assert len(loop._active_subagent_handles) == 2, (
        "distinct-but-equal handles must both register"
    )

    # Same object registered twice must dedup.
    loop.register_subagent_handle(h1)
    assert len(loop._active_subagent_handles) == 2, (
        "same object registered twice must dedup"
    )

    loop.dispose(success=False, reason="identity_dedup")
    # LIFO: h2 then h1.
    assert disposed_names == ["h2", "h1"], (
        f"both distinct handles must dispose; got {disposed_names}"
    )


# RACT 0.5.1
