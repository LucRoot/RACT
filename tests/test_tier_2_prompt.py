"""B-110 D6: a tier-2 tool call asks the operator at the terminal, showing the change.

Only "y" or "yes" typed at the console runs the call. The change is shown with
secret-shaped values masked and control characters made visible, and no line
runs past the terminal at 40 columns.
"""

from __future__ import annotations

import pytest

from ract.approval_callback import console_tier_2_callback
from ract.tools.write import EditFileArgs, WriteFileArgs

WORKFLOW = WriteFileArgs(
    path=".github/workflows/ci.yml",
    content="on: push\njobs:\n  t:\n    run: echo \x1b[31mred\n",
    create=True,
)


def _answer(
    monkeypatch: pytest.MonkeyPatch, text: str | type[BaseException]
) -> list[str]:
    prompts: list[str] = []

    def read_line(prompt: str) -> str:
        prompts.append(prompt)
        if isinstance(text, type):
            raise text()
        return text

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    return prompts


@pytest.mark.parametrize("typed", ["y", "yes", " Y "])
def test_yes_typed_at_the_terminal_allows_once(monkeypatch, typed: str) -> None:
    prompts = _answer(monkeypatch, typed)
    assert console_tier_2_callback("write_file", WORKFLOW) is True
    assert prompts == ["Allow this change once? [y/N]: "]


@pytest.mark.parametrize("typed", ["", "n", "no", "always", "approved"])
def test_anything_else_refuses(monkeypatch, typed: str) -> None:
    _answer(monkeypatch, typed)
    assert console_tier_2_callback("write_file", WORKFLOW) is False


def test_eof_refuses(monkeypatch) -> None:
    _answer(monkeypatch, EOFError)
    assert console_tier_2_callback("write_file", WORKFLOW) is False


def test_the_change_is_shown_masked_and_escaped(monkeypatch, capsys) -> None:
    _answer(monkeypatch, "n")
    key = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    edit = EditFileArgs(
        path="AGENTS.md",
        old="token: old",
        new=f"token: {key}",
        expected_digest="0" * 64,
    )
    console_tier_2_callback("edit_file", edit)
    console_tier_2_callback("write_file", WORKFLOW)
    out = capsys.readouterr().out
    assert "Tier 2:" in out and "edit_file AGENTS.md" in out
    assert "-token: old" in out
    assert key not in out  # the key never reaches the screen
    assert "\x1b" not in out  # a control character in the change is made visible
    assert "write_file .github/workflows/ci.yml" in out


def test_no_line_runs_past_40_columns(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ract.approval_callback._terminal_width", lambda: 40)
    _answer(monkeypatch, "n")
    long = WriteFileArgs(
        path=".github/workflows/" + "w" * 60 + ".yml",
        content="run: " + "x" * 120 + "\n",
        create=True,
    )
    console_tier_2_callback("write_file", long)
    for line in capsys.readouterr().out.splitlines():
        assert len(line) <= 40, line
