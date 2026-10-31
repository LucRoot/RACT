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


@pytest.mark.parametrize("width", [60, 40])
def test_the_questions_fit_the_width(tmp_path: Path, width: int) -> None:
    # B-164: MASON measured the address question at 87 and [L/c] at 64.
    _git_init(tmp_path)
    io, said, asked = _io(["", "l", "", "skip"], [])
    io.width = lambda: width

    assert wizard.run(tmp_path, interactive=True, io=io) == 0
    assert asked and all(cell_len(p.rstrip()) <= width for p in asked), asked
    assert all(p.endswith(" ") for p in asked)  # the cursor stays after a space
    text = " ".join(" ".join(said + asked).split())
    assert "Address of your model server" in text and "[L/c]" in text


def test_the_withheld_key_note_wraps(monkeypatch, capsys) -> None:
    # B-164: MASON's preset walk printed it as one line of 227 characters.
    from ract.providers.openai_provider import OpenAICompatibleProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-throwaway-" + "W" * 32)
    monkeypatch.delenv("RACT_KEY_HOSTS", raising=False)
    monkeypatch.setattr("ract.tui.terminal_width", lambda: 60)
    provider = OpenAICompatibleProvider({"url": "http://192.0.2.1:9/v1"})
    provider._notify_withheld_key()
    err = capsys.readouterr().err
    assert err.startswith("note: OPENAI_API_KEY was not sent")
    assert all(cell_len(line) <= 60 for line in err.splitlines()), err
    assert "W" * 32 not in err


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
