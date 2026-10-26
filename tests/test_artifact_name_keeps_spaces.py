"""Package 5 (handoff 2, H2): a trailing space in a planned file name survives to the path check.

manager.py stripped the planner's expected_artifact, so "notes " was written as "notes" with no
refusal (windows_files.md, trailing space case). Only line endings are removed now; the path
check then refuses the name with its sentence.
"""

from __future__ import annotations

from ract.manager import _artifact_name


def test_a_trailing_space_is_kept_for_the_path_check():
    assert _artifact_name("notes ") == "notes "


def test_line_endings_are_removed():
    assert _artifact_name("src/a.py\n") == "src/a.py"
    assert _artifact_name("src/a.py\r\n") == "src/a.py"


def test_an_empty_name_stays_empty():
    assert _artifact_name("") == ""
    assert _artifact_name(None) == ""
