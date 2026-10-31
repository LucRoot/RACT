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


# G-289: the callers that send what they read, each through a link to .ract
# and one to .git. The planted value is secret-shaped, so a read that got
# through would show it.
PLANTED = "OPENAI_API_KEY=sk-" + "b211" * 10


def _linked(tmp_path: Path, into: str) -> tuple[Path, str]:
    root = _project(tmp_path)
    if into == ".ract":
        (root / ".ract" / "sessions" / "x.json").write_text(PLANTED, encoding="utf-8")
        _dir_link(root / "lnk", root / ".ract")
        return root, "lnk/sessions/x.json"
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(PLANTED, encoding="utf-8")
    _dir_link(root / "g", root / ".git")
    return root, "g/config"


@pytest.mark.parametrize("into", [".ract", ".git"])
def test_the_fence_does_not_send_a_linked_state_file(tmp_path: Path, into: str) -> None:
    from unittest.mock import MagicMock

    from ract.chestertons_fence import ChestertonsFence

    root, rel = _linked(tmp_path, into)
    provider = MagicMock()
    result = ChestertonsFence(root, provider).inspect(rel)
    assert result.value == "" and not provider.method_calls


@pytest.mark.parametrize("into", [".ract", ".git"])
def test_a_citation_into_linked_state_is_not_checked(tmp_path: Path, into: str) -> None:
    from ract.citations import Citation, _check_one

    root, rel = _linked(tmp_path, into)
    result = _check_one(root, Citation(rel, 1, 1, None, 0))
    assert result.status == "not checked"


@pytest.mark.parametrize("into", [".ract", ".git"])
def test_the_executor_reads_nothing_through_a_link_to_state(
    tmp_path: Path, into: str
) -> None:
    from ract.executor.steps import Executor
    from ract.providers.router import ProviderRouter

    root, rel = _linked(tmp_path, into)
    executor = Executor(router=ProviderRouter({}), project_dir=root)
    block, _ = executor._target_file_block(rel, None)
    assert PLANTED not in block
    assert executor._target_secrets(rel) == {}
    assert executor._current_text(rel) is None
