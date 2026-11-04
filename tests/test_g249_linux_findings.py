"""G-249: the two Linux findings on the landed tip.

J7: Esc Esc did nothing on a POSIX pty until the next key (the system inputrc's
"\\e\\e[C" makes Esc Esc a prefix, and CPython's readline never times the wait
out). B-146: after a mid-stream Ctrl-C and /exit a step worktree stayed
registered (the Ctrl-C also cut short the step's git, leaving a registration
whose folder is gone, which a remove cannot clear and only a prune does).
The real-pty checks are the (WSL); these pin the pieces on any system.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ract.executor.worktree import (
    WorktreeManager,
    remove_own_worktrees,
    sweep_orphan_worktrees,
)
from ract.repl import _readline_start_inputrc, inputrc_without_esc_esc
from tests.ux import run_baseline as rb

UBUNTU = (
    '"\\e\\e[C": forward-word\n'
    '"\\e\\e[D": backward-word\n'
    '"\\e[1~": beginning-of-line\n'
    "set meta-flag on\n"
)


def test_the_inputrc_drops_only_the_esc_esc_sequences() -> None:
    text = inputrc_without_esc_esc(UBUNTU, None)
    assert '"\\e\\e[' not in text
    assert '"\\e[1~": beginning-of-line' in text and "set meta-flag on" in text


def test_a_home_inputrc_is_read_instead_as_readline_would() -> None:
    assert (
        inputrc_without_esc_esc(UBUNTU, "/home/u/.inputrc")
        == "$include /home/u/.inputrc\n"
    )


def test_an_inputrc_the_operator_set_is_left_alone(monkeypatch) -> None:
    monkeypatch.setenv("INPUTRC", "/somewhere/mine")
    undo = _readline_start_inputrc()
    undo()
    assert os.environ["INPUTRC"] == "/somewhere/mine"


def _repo(tmp_path: Path) -> Path:
    return rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})


def _head(ws: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(ws), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _listed(ws: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(ws), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sum(1 for line in out.splitlines() if line.startswith("worktree "))


def test_the_session_end_removes_its_own_step_worktrees(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    mine = WorktreeManager(ws).create(b"\x01" * 16, _head(ws))
    other = WorktreeManager(ws).create(b"\x02" * 16, _head(ws))
    other.path.with_name(other.path.name + ".owner").write_text(
        json.dumps({"pid": 2**22 + 9, "created": 1}), encoding="utf-8"
    )
    assert remove_own_worktrees(ws) == [mine.path.name]
    assert not mine.path.exists() and other.path.exists()


def test_a_registration_whose_folder_is_gone_is_pruned_by_the_rollback(
    tmp_path: Path,
) -> None:
    ws = _repo(tmp_path)
    manager = WorktreeManager(ws)
    wt = manager.create(b"\x03" * 16, _head(ws))
    shutil.rmtree(wt.path)  # what a git cut short by Ctrl-C can leave
    assert _listed(ws) == 2
    manager.rollback(wt)
    assert _listed(ws) == 1


def test_the_sweep_prunes_a_registration_whose_folder_is_gone(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    wt = WorktreeManager(ws).create(b"\x04" * 16, _head(ws))
    wt.path.with_name(wt.path.name + ".owner").write_text(
        json.dumps({"pid": 2**22 + 11, "created": 1}), encoding="utf-8"
    )
    shutil.rmtree(wt.path)
    assert sweep_orphan_worktrees(ws) == [wt.path.name]
    assert _listed(ws) == 1


def test_the_cancel_abort_ends_a_read_blocked_on_a_stalled_stream() -> None:
    import socket
    import threading
    import time

    import httpx

    from ract.providers.openai_provider import _aborter

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    release = threading.Event()

    def serve() -> None:
        conn, _ = server.accept()
        conn.recv(65536)
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\none\r\n"
        )
        release.wait(30)  # the stall: no more bytes until the test ends
        conn.close()

    class Wrapping(httpx.BaseTransport):  # as the egress ledger wraps httpx's
        def __init__(self) -> None:
            self._inner = httpx.HTTPTransport()

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return self._inner.handle_request(request)

    threading.Thread(target=serve, daemon=True).start()
    client = httpx.Client(transport=Wrapping(), timeout=60)
    ended = threading.Event()

    def read() -> None:
        try:
            with client.stream(
                "GET", f"http://127.0.0.1:{server.getsockname()[1]}/"
            ) as r:
                for _ in r.iter_raw():
                    pass
        except Exception:  # noqa: BLE001 - any end of the read is the point
            ended.set()
            return
        ended.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    time.sleep(0.5)
    started = time.monotonic()
    _aborter(client)()
    try:
        assert ended.wait(5) and time.monotonic() - started < 5
    finally:
        release.set()
        server.close()
