"""B-238: the offload store writes through the state-path guard and a fresh
temporary file, scans the stub before it can enter a request, and refuses
Windows device names in handles (G-306, the batch 5 review of B-174).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract import offload
from ract.workspace_state import StateDirRefused


def _store(root: Path, session: str = "s1") -> offload.OffloadStore:
    return offload.OffloadStore(root / "artifacts", session_id=session)


def _big_text(marker: str = "padding text that makes the line long enough") -> str:
    return "".join(f"log line {i} {marker}\n" for i in range(400))


def test_place_replaces_a_planted_hard_link_without_writing_through_it(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("original victim bytes\n", encoding="utf-8")
    target = tmp_path / "artifacts" / "s1" / "1" / "pytest_log.txt"
    target.parent.mkdir(parents=True)
    try:
        os.link(victim, target)  # a hard link planted at the file name
    except OSError as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    text = _big_text()
    placed = store.place(text, turn=1, name="pytest_log")
    assert placed.offloaded is True
    # The write went through a fresh temporary file and one rename: the
    # victim keeps its own inode and bytes, and the stored file holds the
    # output.
    assert victim.read_text(encoding="utf-8") == "original victim bytes\n"
    assert target.read_text(encoding="utf-8") == text


def test_place_goes_through_check_state_path(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".ract").mkdir(parents=True)
    link = root / ".ract" / "artifacts"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"links are unavailable here: {exc}")
    store = offload.OffloadStore(link, session_id="s1")
    with pytest.raises(StateDirRefused):
        store.place(_big_text(), turn=1, name="log")


def test_the_stub_is_scanned_before_it_can_reach_a_request(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = "sk-abcdef1234567890abcdef1234567890abcdef12"
    lines = (
        [f"the first line holds the key {key}"]
        + [f"filler {i} padding padding padding padding" for i in range(300)]
        + [f"the last line holds the key {key}"]
    )
    placed = store.place("\n".join(lines) + "\n", turn=1, name="tool_out")
    assert placed.offloaded is True
    assert key not in placed.text
    assert "[redacted]" in placed.text
    # The notice names the pattern and count, never the value.
    assert "OpenAI-style key" in placed.text


@pytest.mark.parametrize("name", ["con", "nul", "COM1", "Lpt3", "con.txt"])
def test_a_windows_device_name_is_refused_as_an_output_name(
    tmp_path: Path, name: str
) -> None:
    store = _store(tmp_path)
    with pytest.raises(offload.OffloadError, match="device name"):
        store.place(_big_text(), turn=1, name=name)
    assert not (tmp_path / "artifacts" / "s1" / "1").exists() or not list(
        (tmp_path / "artifacts" / "s1" / "1").iterdir()
    )


def test_a_windows_device_name_is_refused_in_a_read_handle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(offload.OffloadError, match="device name"):
        store.read_slice("artifact:s1/1/nul", start_line=1, count=10)
