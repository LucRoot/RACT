"""SubstrateLoop.spawn_step_subprocess + _reap_active_processes -- unit tests.

v0.5.1 wiring module_05 (Lens C C-03 closure). Locks:

- ``spawn_step_subprocess`` registers the handle into
  ``_active_process_handles`` so a rollback path can find + reap it.
- ``spawn_step_subprocess`` auto-consumes ``_current_sandbox_env`` when
  the caller passes ``env=None`` (module_04 SP Q5 defer closure).
- Explicit ``env=<dict>`` overrides the sandbox env.
- ``_reap_active_processes`` calls ``kill_tree`` on every handle and
  clears the list.
- ``dispose(success=False)`` invokes ``_reap_active_processes``.
- ``dispose(success=True)`` clears the list without kill.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


from ract.executor.loop import SubstrateLoop
from ract.executor.process_group import ProcessGroupHandle
from ract.executor.worktree import WorktreeManager


_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": __import__("os").environ.get("PATH", ""),
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


def _loop(tmp_path: Path) -> SubstrateLoop:
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    return SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )


# ---------------------------------------------------------------------------
# Handle registration
# ---------------------------------------------------------------------------


def test_spawn_step_subprocess_registers_handle(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._active_process_handles == []
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    handle = loop.spawn_step_subprocess(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert isinstance(handle, ProcessGroupHandle)
        assert handle in loop._active_process_handles
        assert len(loop._active_process_handles) == 1
    finally:
        loop._reap_active_processes(reason="test_cleanup")


def test_spawn_step_subprocess_returns_handle_shape(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    handle = loop.spawn_step_subprocess(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert handle.popen is not None
        assert handle.argv[0] == sys.executable
        if _IS_WINDOWS:
            assert handle.pgid is None
        else:
            # POSIX: pgid == pid post-setsid.
            assert handle.pgid == handle.popen.pid
    finally:
        loop._reap_active_processes(reason="test_cleanup")


def test_deregister_process_handle_removes_from_list(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    handle = loop.spawn_step_subprocess(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle.popen.wait(timeout=5)
    assert handle in loop._active_process_handles
    loop._deregister_process_handle(handle)
    assert handle not in loop._active_process_handles


def test_deregister_missing_handle_is_noop(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    handle = loop.spawn_step_subprocess(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle.popen.wait(timeout=5)
    loop._deregister_process_handle(handle)
    # Second deregister must not raise.
    loop._deregister_process_handle(handle)


# ---------------------------------------------------------------------------
# Env consumption -- module_04 SP Q5 defer closure
# ---------------------------------------------------------------------------


def test_spawn_consumes_current_sandbox_env(tmp_path: Path) -> None:
    """When ``_current_sandbox_env`` is set and caller passes env=None,
    the sandbox env reaches ``process_group.spawn(env=...)``."""
    loop = _loop(tmp_path)
    filtered = {"PATH": "/nowhere", "SAFE_VAR": "yes"}
    loop._current_sandbox_env = dict(filtered)

    captured: dict[str, object] = {}

    def _fake_spawn(argv, *, env=None, cwd=None, stdin=None, stdout=None, stderr=None):
        captured["env"] = env

        # Return a lightweight object with the same attribute surface
        # `_reap_active_processes` and this test read.
        class _FakePopen:
            pid = 99999

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        return ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=99999,
            argv=tuple(argv),
        )

    with patch("ract.executor.loop.spawn", side_effect=_fake_spawn):
        loop.spawn_step_subprocess([sys.executable, "-c", "pass"])

    assert captured["env"] == filtered, (
        f"expected sandbox env to reach spawn(), got {captured['env']!r}"
    )


def test_explicit_env_overrides_sandbox_env(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._current_sandbox_env = {"PATH": "/sandbox"}
    explicit = {"PATH": "/explicit", "EXTRA": "yes"}

    captured: dict[str, object] = {}

    def _fake_spawn(argv, *, env=None, **kwargs):
        captured["env"] = env

        class _FakePopen:
            pid = 88888

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        return ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=88888,
            argv=tuple(argv),
        )

    with patch("ract.executor.loop.spawn", side_effect=_fake_spawn):
        loop.spawn_step_subprocess([sys.executable, "-c", "pass"], env=explicit)
    assert captured["env"] == explicit


def test_no_sandbox_env_falls_through_to_parent_env(tmp_path: Path) -> None:
    """Windows unenforced stub yields no sandbox env; spawn used to
    get env=None (child inherits parent os.environ wholesale).

    v0.5.2 module_04 SP amendment (Ox Alpha B Q3 supplemental S1
    DEFECT): env=None no longer falls through unchanged. The
    substrate strips RACT_* keys from a copy of os.environ (so
    an attacker's parent-shell RACT_RUN_ID cannot poison the
    child's ambient) before passing the cleaned env to Popen.
    Non-RACT parent env variables still pass through, preserving
    the pre-amendment behavior for PATH / HOME / etc.
    """
    loop = _loop(tmp_path)
    assert loop._current_sandbox_env is None

    captured: dict[str, object] = {}

    def _fake_spawn(argv, *, env=None, **kwargs):
        captured["env"] = env

        class _FakePopen:
            pid = 77777

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        return ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=77777,
            argv=tuple(argv),
        )

    with patch("ract.executor.loop.spawn", side_effect=_fake_spawn):
        loop.spawn_step_subprocess([sys.executable, "-c", "pass"])

    # Post-amendment: env is a stripped copy of os.environ (not
    # None). Non-RACT keys survive; RACT_* keys have been stripped.
    env_out = captured["env"]
    assert env_out is not None
    assert isinstance(env_out, dict)
    for key in env_out:
        assert not key.upper().startswith("RACT_"), (
            f"RACT_* key {key!r} leaked through env=None path"
        )


# ---------------------------------------------------------------------------
# Reap
# ---------------------------------------------------------------------------


def test_reap_active_processes_kills_all_and_clears(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    killed: list[int] = []

    class _FakePopen:
        def __init__(self, pid):
            self.pid = pid
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def wait(self, timeout=None):
            self._alive = False
            return 0

        def kill(self):
            self._alive = False

    handles = [
        ProcessGroupHandle(
            popen=_FakePopen(100 + i),  # type: ignore[arg-type]
            pgid=100 + i,
            argv=("cmd",),
        )
        for i in range(3)
    ]
    loop._active_process_handles.extend(handles)

    def _fake_kill(handle, **kwargs):
        killed.append(handle.pid)

    with patch("ract.executor.loop.kill_tree", side_effect=_fake_kill):
        reaped = loop._reap_active_processes(reason="unit_test")

    assert reaped == 3
    assert sorted(killed) == [100, 101, 102]
    assert loop._active_process_handles == []


def test_reap_empty_list_returns_zero(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._reap_active_processes(reason="empty") == 0


def test_reap_swallows_kill_tree_error(tmp_path: Path) -> None:
    """A single failing kill must not abort the sweep."""
    loop = _loop(tmp_path)

    class _FakePopen:
        pid = 1

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    loop._active_process_handles.append(
        ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=1,
            argv=("cmd",),
        )
    )

    with patch(
        "ract.executor.loop.kill_tree",
        side_effect=RuntimeError("simulated"),
    ):
        # Must not raise.
        loop._reap_active_processes(reason="reap_error")

    # List still cleared even on failure.
    assert loop._active_process_handles == []


# ---------------------------------------------------------------------------
# Dispose wire-in
# ---------------------------------------------------------------------------


def test_dispose_unsuccessful_reaps_before_drain(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    class _FakePopen:
        pid = 5555

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    loop._active_process_handles.append(
        ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=5555,
            argv=("cmd",),
        )
    )

    killed: list[int] = []
    with patch(
        "ract.executor.loop.kill_tree",
        side_effect=lambda h, **kw: killed.append(h.pid),
    ):
        loop.dispose(success=False, reason="T2_test")

    assert killed == [5555]
    assert loop._active_process_handles == []


def test_dispose_success_clears_handles_without_kill(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    class _FakePopen:
        pid = 6666

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    loop._active_process_handles.append(
        ProcessGroupHandle(
            popen=_FakePopen(),  # type: ignore[arg-type]
            pgid=6666,
            argv=("cmd",),
        )
    )

    killed: list[int] = []
    with patch(
        "ract.executor.loop.kill_tree",
        side_effect=lambda h, **kw: killed.append(h.pid),
    ):
        loop.dispose(success=True, reason="T1_SUCCESS")

    # Natural exit: no forced kill on T1.
    assert killed == []
    assert loop._active_process_handles == []


# RACT 0.5.1
