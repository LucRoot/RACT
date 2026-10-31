"""B-136: a drive-letter path is refused on POSIX too (it names another machine's root)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.workspace_path import resolve_workspace_path


@pytest.mark.parametrize("raw", ["C:\\Windows\\x.py", "c:/windows/x.py", "D:\\data"])
def test_a_drive_path_is_refused_as_on_windows(tmp_path: Path, raw: str) -> None:
    rooted = resolve_workspace_path(tmp_path, raw, purpose="send", windows=False)
    assert not rooted.is_ok()


def test_an_ordinary_relative_path_still_resolves(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    assert resolve_workspace_path(
        tmp_path, "src/a.py", purpose="send", windows=False
    ).is_ok()
