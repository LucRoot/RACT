"""B-146: a step worktree no live process owns is removed when a session starts.

The worktrees are made with WorktreeManager in a temporary repository; the
"killed process" is a child Python process that makes a worktree and is
killed before it can remove it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ract.executor.worktree import WorktreeManager, sweep_orphan_worktrees
from tests.ux import run_baseline as rb

REPO = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    return rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})


def _head(ws: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(ws), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _registered(ws: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(ws), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sum(1 for line in out.splitlines() if line.startswith("worktree "))


def test_a_worktree_whose_owner_ended_is_removed(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    wt = WorktreeManager(ws).create(b"\x01" * 16, _head(ws))
    owner = wt.path.with_name(wt.path.name + ".owner")
    # The process that made it has ended: a pid that is not running.
    owner.write_text(json.dumps({"pid": 2**22 + 7, "created": 1}), encoding="utf-8")
    assert _registered(ws) == 2
    removed = sweep_orphan_worktrees(ws)
    assert removed == [wt.path.name]
    assert _registered(ws) == 1 and not wt.path.exists() and not owner.exists()


def test_a_worktree_this_process_owns_is_kept(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    wt = WorktreeManager(ws).create(b"\x02" * 16, _head(ws))
    assert sweep_orphan_worktrees(ws) == []
    assert wt.path.exists() and _registered(ws) == 2


def test_a_worktree_the_operator_made_is_never_touched(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    mine = tmp_path / "my-tree"
    subprocess.run(
        ["git", "-C", str(ws), "worktree", "add", "-q", str(mine)],
        check=True,
        capture_output=True,
    )
    assert sweep_orphan_worktrees(ws) == []
    assert mine.exists() and _registered(ws) == 2


def test_a_killed_process_leaves_a_worktree_the_next_sweep_removes(
    tmp_path: Path,
) -> None:
    ws = _repo(tmp_path)
    program = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from ract.executor.worktree import WorktreeManager\n"
        "WorktreeManager(Path(sys.argv[1])).create(b'\\x03' * 16, sys.argv[2])\n"
        "print('made', flush=True)\n"
        "time.sleep(60)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(ws), _head(ws)],
        stdout=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "made"
        # While it runs, its worktree is kept.
        assert sweep_orphan_worktrees(ws) == []
    finally:
        child.kill()
        child.wait(timeout=30)
    assert _registered(ws) == 2  # the kill left it, as WRIGHT saw after /exit
    assert sweep_orphan_worktrees(ws) == [(b"\x03" * 16).hex()]
    assert _registered(ws) == 1
