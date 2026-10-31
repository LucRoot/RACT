"""B-211: a path sent to a model is checked by what it resolves to, not only by its name.

``resolve_workspace_path(purpose="send")`` checked the typed name against the
never-sent list. A junction (Windows) or a symlink a repository ships, such as
``lnk -> .ract``, made ``lnk/sessions/x.json`` pass while the read went to
``.ract/sessions/x.json``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.workspace_path import resolve_workspace_path


def _dir_link(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), else a symlink."""
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(
                f"no junction here: {done.stdout.strip()} {done.stderr.strip()}"
            )
    else:
        link.symlink_to(target, target_is_directory=True)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".ract" / "sessions").mkdir(parents=True)
    (root / ".ract" / "sessions" / "x.json").write_text(
        '{"turns": []}', encoding="utf-8"
    )
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_a_link_into_ract_state_is_refused_for_send(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _dir_link(root / "lnk", root / ".ract")
    sent = resolve_workspace_path(root, "lnk/sessions/x.json", purpose="send")
    assert not sent.is_ok()
    assert "never sent" in (sent.error or "")


def test_a_link_into_git_state_is_refused_for_send(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    _dir_link(root / "g", root / ".git")
    assert not resolve_workspace_path(root, "g/config", purpose="send").is_ok()


def test_a_link_to_ordinary_project_files_still_sends(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _dir_link(root / "code", root / "src")
    sent = resolve_workspace_path(root, "code/app.py", purpose="send")
    assert sent.is_ok()


def test_the_typed_name_check_still_holds(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assert not resolve_workspace_path(
        root, ".ract/sessions/x.json", purpose="send"
    ).is_ok()
