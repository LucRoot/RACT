"""B-163: every line `ract setup` prints fits the terminal width (80, 60 and 40 columns)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.cells import cell_len

from ract.setup import wizard
from tests.setup.test_wizard import SERVER, _git_init, _io


def _longest(said: list[str]) -> int:
    return max((cell_len(line) for line in said), default=0)


@pytest.mark.parametrize("width", [80, 60, 40])
def test_the_detected_server_path_fits_the_width(tmp_path: Path, width: int) -> None:
    # Not a git repository: the notice MASON measured at 124 characters is printed.
    io, said, _ = _io(["", "n"], [SERVER])
    io.width = lambda: width

    assert wizard.run(tmp_path, interactive=True, io=io) == 0
    assert _longest(said) <= width, [line for line in said if cell_len(line) > width]


@pytest.mark.parametrize("width", [80, 60, 40])
def test_the_no_server_local_path_fits_the_width(tmp_path: Path, width: int) -> None:
    _git_init(tmp_path)
    io, said, _ = _io(["", "l", "", "skip"], [])
    io.width = lambda: width

    assert wizard.run(tmp_path, interactive=True, io=io) == 0
    assert _longest(said) <= width, [line for line in said if cell_len(line) > width]


def test_wrapping_keeps_every_word_and_the_indent() -> None:
    line = "  " + " ".join(f"word{i}" for i in range(30))
    wrapped = wizard.wrap_line(line, 40)
    assert all(cell_len(part) <= 40 for part in wrapped)
    assert " ".join(" ".join(wrapped).split()) == " ".join(line.split())
    assert wrapped[0].startswith("  w") and wrapped[1].startswith("    w")


def test_a_diff_is_printed_unwrapped(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, _, _ = _io([""], [SERVER])
    assert wizard.run(tmp_path, interactive=True, io=io) == 0
    other = wizard.local_probe.Server(
        "llama.cpp server", "http://127.0.0.1:8081/v1", ("m" * 60,)
    )
    io, said, _ = _io(["", "n"], [other])
    io.width = lambda: 40
    answers = wizard.Answers(add_provider=True)
    assert wizard.run(tmp_path, answers=answers, interactive=True, io=io) == 0
    assert any(
        len(line) > 40 and line.startswith("+") for line in "\n".join(said).splitlines()
    )
