"""Package 5 (handoff H5): the changed-files line names a file as the disk spells it.

The plan's name was reported as written, so "Readme.md" was listed for a file that is README.md
on disk (windows_files.md, case-variant case). The helper answers with the on-disk spelling when
the file exists, and the name as given when it does not.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract.session_turn import _on_disk_name


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive lookup is the Windows behaviour")
def test_a_changed_name_uses_the_case_on_disk(tmp_path: Path):
    (tmp_path / "README.md").write_text("old\n", encoding="utf-8")
    assert _on_disk_name(tmp_path, "Readme.md") == "README.md"


def test_a_name_that_does_not_exist_is_reported_as_given(tmp_path: Path):
    assert _on_disk_name(tmp_path, "src/new.py") == "src/new.py"
