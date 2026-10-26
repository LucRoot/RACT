"""H1 (package 4): a path over 260 characters is refused on Windows rules.

Before this change the step reported "done" and wrote nothing (docs/ux/windows_files.md, case
"long path over 260"). The refusal names the limit in one sentence.
"""

from __future__ import annotations

from ract.workspace_path import resolve_workspace_path


def test_a_path_over_260_characters_is_refused_on_windows_rules(tmp_path):
    long_name = "/".join(["d" * 60] * 4) + "/" + "f" * 80 + ".py"
    assert len(long_name) > 260
    result = resolve_workspace_path(tmp_path, long_name, purpose="write", windows=True)
    assert not result.is_ok()
    assert "260" in result.error
    assert "Windows" in result.error


def test_a_path_under_260_characters_is_not_refused_for_length(tmp_path):
    result = resolve_workspace_path(tmp_path, "src/" + "f" * 40 + ".py", purpose="write", windows=True)
    assert result.is_ok(), result.error
