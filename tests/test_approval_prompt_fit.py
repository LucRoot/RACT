"""The approval prompt leaves room for the answer, and Ctrl-C ends its line.

Found by the terminal matrix (package H): at 80 columns the question's last line
filled the width, so the typed answer wrapped onto the next physical line; and a
Ctrl-C at the prompt left the cursor mid-line, so the next output printed onto it.
"""

from __future__ import annotations

import pytest

from ract.approval_callback import console_approval_callback
from ract.manager import Step

STEP = Step(
    action="Fix add() in src/calc.py so it adds",
    provider_hint="local",
    expected_artifact="src/calc.py",
)


@pytest.mark.parametrize("width", [80, 60, 40])
def test_the_prompt_line_leaves_room_for_the_typed_answer(monkeypatch, capsys, width):
    monkeypatch.setenv("COLUMNS", str(width))
    prompts: list[str] = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return "y"

    monkeypatch.setattr("builtins.input", fake_input)
    console_approval_callback(STEP)
    assert prompts, "the question was not asked"
    assert len(prompts[0]) + 2 <= width, (width, prompts[0])


def test_ctrl_c_at_the_prompt_ends_the_line_before_it_propagates(monkeypatch, capsys):
    def interrupted(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    with pytest.raises(KeyboardInterrupt):
        console_approval_callback(STEP)
    assert capsys.readouterr().out.endswith("\n")
