"""S-015b: a Rootknot sidecar is not a hunk the operator reviews; it follows its file.

The gate found it (test_git_init_offer): a step now commits the sidecar of
the file it writes, and the per-hunk review asked about it, so the operator's
answers ran out on RACT's own record.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from ract.executor.substrate_adapter import _review_proposed
from ract.executor.worktree import snapshot_working_tree
from tests.ux import run_baseline as rb

SIDECAR = "src/.calc.py.rootknot.json"


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def _step(ws: Path, files: dict[str, str]) -> SimpleNamespace:
    before = snapshot_working_tree(ws)
    side = ws.parent / f"side-{before[:8]}"
    _git(ws, "worktree", "add", "-q", "--detach", str(side), before)
    for rel, body in files.items():
        (side / rel).write_text(body, encoding="utf-8")
    _git(side, "add", "-A")
    _git(
        side,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit",
        "-q",
        "-m",
        "step",
    )
    after = _git(side, "rev-parse", "HEAD")
    _git(ws, "worktree", "remove", "--force", str(side))
    return SimpleNamespace(
        parent_snapshot_before=before, parent_snapshot_after=after, branch="b"
    )


def _blob(ws: Path, commit: str, path: str) -> str | None:
    shown = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=ws,
        capture_output=True,
        text=True,
    )
    return shown.stdout if shown.returncode == 0 else None


def _reviewer(seen: list[str], keep: bool):  # type: ignore[no-untyped-def]
    def review(path: str, before: bytes | None, after: bytes | None):  # type: ignore[no-untyped-def]
        seen.append(path)
        return SimpleNamespace(
            answers={1: "a" if keep else "r"}, content=after if keep else before
        )

    return review


def _setup(tmp_path: Path) -> tuple[Path, SimpleNamespace]:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"src/calc.py": "one\n"})
    record = _step(ws, {"src/calc.py": "two\n", SIDECAR: '{"knot": 1}\n'})
    return ws, record


def test_the_sidecar_is_not_reviewed_and_follows_a_kept_file(tmp_path: Path) -> None:
    ws, record = _setup(tmp_path)
    seen: list[str] = []
    commit = _review_proposed(
        SimpleNamespace(project_dir=ws), _reviewer(seen, keep=True), record, 0
    ).unwrap()
    assert seen == ["src/calc.py"]
    assert _blob(ws, commit, SIDECAR) == '{"knot": 1}\n'


def test_a_rejected_file_leaves_its_sidecar_out(tmp_path: Path) -> None:
    ws, record = _setup(tmp_path)
    seen: list[str] = []
    commit = _review_proposed(
        SimpleNamespace(project_dir=ws), _reviewer(seen, keep=False), record, 0
    ).unwrap()
    assert seen == ["src/calc.py"]
    assert _blob(ws, commit, "src/calc.py") == "one\n"
    assert _blob(ws, commit, SIDECAR) is None  # the knot would not match the file
