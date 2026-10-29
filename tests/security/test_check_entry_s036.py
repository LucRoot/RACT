"""S-036 (a, b): entries a repository can ship that crashed a write or hid data.

``check_entry`` guards every path read from a manifest or a snapshot key
(undo, rollback, consolidate, session import).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract.undo_backup import check_entry

windows = pytest.mark.skipif(os.name != "nt", reason="Windows file-name rules")
elsewhere = pytest.mark.skipif(os.name == "nt", reason="legal names off Windows")


def test_a_nul_character_is_refused(tmp_path: Path) -> None:
    assert (
        check_entry(tmp_path, tmp_path, "src/a\x00.py") == "a path with a NUL character"
    )


@windows
@pytest.mark.parametrize("entry", ["notes.txt:hidden", "src/a.py:x:$DATA"])
def test_a_stream_suffix_is_refused_on_windows(tmp_path: Path, entry: str) -> None:
    assert check_entry(tmp_path, tmp_path, entry) == "a name with a ':' stream suffix"


@windows
@pytest.mark.parametrize("entry", ["con", "AUX.txt", "src/lpt1.log", "nul .md", "COM9"])
def test_a_device_name_is_refused_on_windows(tmp_path: Path, entry: str) -> None:
    assert check_entry(tmp_path, tmp_path, entry) == "a Windows device name"


@elsewhere
@pytest.mark.parametrize("entry", ["notes:v1.txt", "con.txt"])
def test_those_names_stay_legal_elsewhere(tmp_path: Path, entry: str) -> None:
    assert check_entry(tmp_path, tmp_path, entry) is None


@pytest.mark.parametrize(
    "entry", ["src/console.py", "auxiliary/a.txt", "docs/com10.md"]
)
def test_names_that_only_start_like_a_device_are_kept(
    tmp_path: Path, entry: str
) -> None:
    assert check_entry(tmp_path, tmp_path, entry) is None
