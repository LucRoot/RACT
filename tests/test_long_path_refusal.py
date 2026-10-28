"""H1 (package 4): a path over 260 characters is refused on Windows rules.

Before this change the step reported "done" and wrote nothing (docs/ux/windows_files.md, case
"long path over 260"). The refusal names the limit in one sentence.
"""

from __future__ import annotations

import os
from pathlib import Path

from ract.workspace_path import resolve_workspace_path


def test_a_path_over_260_characters_is_refused_on_windows_rules(tmp_path):
    long_name = "/".join(["d" * 60] * 4) + "/" + "f" * 80 + ".py"
    assert len(long_name) > 260
    result = resolve_workspace_path(tmp_path, long_name, purpose="write", windows=True)
    assert not result.is_ok()
    assert "260" in result.error
    assert "Windows" in result.error


def test_a_path_under_260_characters_is_not_refused_for_length(tmp_path):
    result = resolve_workspace_path(
        tmp_path, "src/" + "f" * 40 + ".py", purpose="write", windows=True
    )
    assert result.is_ok(), result.error


def _relative_of_length(n: int) -> str:
    """A relative path of exactly *n* characters: 49-character folders, then a file."""
    folders = (n - 10) // 50
    name_length = n - 50 * folders
    rel = "d" * 49 + "/"
    return rel * folders + "f" * (name_length - 3) + ".py"


def _full_length(root: Path, rel: str) -> int:
    return len(os.path.realpath(root)) + 1 + len(rel)


def test_the_project_folder_counts_toward_the_windows_limit(tmp_path):
    # Windows measures the whole path, so a relative path well under 260
    # characters still fails in a deep project folder (BUILDER review of H1).
    rel = _relative_of_length(260 - len(os.path.realpath(tmp_path)) - 1)
    assert len(rel) < 260 and _full_length(tmp_path, rel) == 260
    result = resolve_workspace_path(tmp_path, rel, purpose="write", windows=True)
    assert not result.is_ok()
    assert "260" in result.error


def test_a_full_path_of_259_characters_is_allowed(tmp_path):
    # MAX_PATH is 260 including the terminating NUL: 259 characters is the longest.
    rel = _relative_of_length(259 - len(os.path.realpath(tmp_path)) - 1)
    assert _full_length(tmp_path, rel) == 259
    result = resolve_workspace_path(tmp_path, rel, purpose="write", windows=True)
    assert result.is_ok(), result.error


def test_the_length_rule_is_for_windows_rules_only(tmp_path):
    rel = _relative_of_length(300)
    result = resolve_workspace_path(tmp_path, rel, purpose="write", windows=False)
    assert result.is_ok(), result.error
