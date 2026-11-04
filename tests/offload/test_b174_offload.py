"""B-174 (the lane, ADR-0049 D9): large outputs are offloaded; the model reads slices.

The module (ract.offload) does not exist yet, so these tests fail first. A stored output is whole
under the run's folder. The model gets a labelled stub with a harness summary and a handle. A slice
is read with read_slice: at most 200 lines and 16 KiB, never past the end, never from another session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import offload
from ract.tools import UNTRUSTED_LABEL


def _store(root: Path, session: str = "s1") -> offload.OffloadStore:
    return offload.OffloadStore(root / "artifacts", session_id=session)


def test_a_5_mb_result_reaches_the_model_as_a_bounded_summary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    text = "".join(f"test line {i} with some padding text\n" for i in range(140_000))
    assert len(text.encode("utf-8")) >= 5 * 1024 * 1024
    placed = store.place(text, turn=1, name="pytest_log")
    assert placed.offloaded is True
    assert len(placed.text.encode("utf-8")) <= offload.SUMMARY_CAP + 1024
    assert placed.handle.startswith("artifact:s1/1/pytest_log")
    stored = tmp_path / "artifacts" / "s1" / "1" / "pytest_log.txt"
    assert stored.read_text(encoding="utf-8") == text, "the whole output must be stored"


def test_a_small_output_goes_into_the_context_whole(tmp_path: Path) -> None:
    store = _store(tmp_path)
    placed = store.place("short result\n", turn=1, name="grep")
    assert placed.offloaded is False
    assert placed.handle is None
    assert placed.text == "short result\n"


def test_the_stub_and_the_slices_carry_the_data_label(tmp_path: Path) -> None:
    store = _store(tmp_path)
    placed = store.place("x\n" * 10_000, turn=2, name="log")
    assert placed.text.startswith(UNTRUSTED_LABEL)
    sliced = store.read_slice(placed.handle, start_line=1, count=5)
    assert sliced.text.startswith(UNTRUSTED_LABEL)


def test_read_slice_returns_at_most_200_lines_and_16_kib(tmp_path: Path) -> None:
    store = _store(tmp_path)
    text = "".join(("y" * 100) + f" {i}\n" for i in range(5000))
    placed = store.place(text, turn=1, name="big")
    sliced = store.read_slice(placed.handle, start_line=1, count=5000)
    body = sliced.text[len(UNTRUSTED_LABEL) + 1 :]
    assert body.count("\n") <= offload.SLICE_MAX_LINES
    assert len(sliced.text.encode("utf-8")) <= offload.SLICE_MAX_BYTES + len(UNTRUSTED_LABEL) + 200


def test_a_slice_past_the_end_is_empty_and_says_so(tmp_path: Path) -> None:
    store = _store(tmp_path)
    placed = store.place("a\n" * 6000, turn=1, name="short_end")
    sliced = store.read_slice(placed.handle, start_line=99_999, count=10)
    assert sliced.lines_returned == 0
    assert "past the end" in sliced.note


def test_a_handle_from_another_session_is_refused(tmp_path: Path) -> None:
    first = _store(tmp_path, session="s1")
    second = _store(tmp_path, session="s2")
    placed = first.place("z\n" * 5000, turn=1, name="log")
    with pytest.raises(offload.OffloadError, match="another session"):
        second.read_slice(placed.handle, start_line=1, count=5)


@pytest.mark.parametrize(
    "bad",
    [
        "artifact:s1/../../etc/log",
        "artifact:s1/1/../../x",
        "artifact:s1/1/log/extra",
        "/abs/path/log",
        "artifact:s1/1/.hidden",
    ],
)
def test_a_pointer_cannot_leave_the_run_folder(tmp_path: Path, bad: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(offload.OffloadError):
        store.read_slice(bad, start_line=1, count=5)


def test_a_binary_stored_output_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    folder = tmp_path / "artifacts" / "s1" / "1"
    folder.mkdir(parents=True)
    (folder / "blob.txt").write_bytes(b"\x00\x01binary" + b"\x00" * 64)
    with pytest.raises(offload.OffloadError, match="binary"):
        store.read_slice("artifact:s1/1/blob", start_line=1, count=5)


def test_a_slice_start_below_one_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    placed = store.place("a\n" * 6000, turn=1, name="low")
    with pytest.raises(offload.OffloadError):
        store.read_slice(placed.handle, start_line=0, count=5)
