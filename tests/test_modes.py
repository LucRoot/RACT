"""B-034: the session's permission modes, shown in the status line."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ract.approval_callback import console_approval_callback
from ract.manager import Step
from tests.test_repl import _session


def test_mode_shows_and_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    session, _, console = _session()

    session.handle("/mode")
    assert "auto-accept: changes are applied without asking" in console.text

    session.handle("/mode plan")
    assert session.permission_mode() == "plan" and session.state.dry_run

    session.handle("/mode ask")  # alias for default
    assert session.permission_mode() == "default"
    assert session.state.auto and not session.state.dry_run

    session.handle("/mode accept-edits")
    assert session.permission_mode() == "auto-accept"


def test_unrestricted_is_refused_with_the_reason() -> None:
    session, _, console = _session()

    session.handle("/mode unrestricted")

    assert "needs the tier-3 policy (B-020)" in console.text
    assert session.permission_mode() == "auto-accept"


def test_default_mode_needs_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    session, _, console = _session()

    session.handle("/mode default")

    assert "needs a terminal" in console.text
    assert session.permission_mode() == "auto-accept"


def test_answer_steps_are_not_asked_about(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "n")

    answer = Step(action="explain add", provider_hint="local", expected_artifact="")
    change = Step(
        action="fix add", provider_hint="local", expected_artifact="src/calc.py"
    )

    assert console_approval_callback(answer) is True
    assert console_approval_callback(change) is False
    assert len(asked) == 1 and "src/calc.py" in asked[0]


def _ract_exe() -> str:
    return str(
        Path(sys.executable).with_name("ract.exe" if os.name == "nt" else "ract")
    )


@pytest.mark.parametrize(
    ("command", "label", "flag"),
    [
        ("/mode plan", "plan", "--dry-run"),
        ("/mode default", "default", "--auto"),
        ("/mode auto-accept", "auto-accept", None),
    ],
)
def test_the_label_and_the_approval_come_from_one_setting(
    monkeypatch: pytest.MonkeyPatch, command: str, label: str, flag: str | None
) -> None:
    # D-023: the status line and the behavior cannot disagree.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    session, _, _ = _session()

    session.handle(command)

    argv = session.build_run_argv("x")
    assert session.permission_mode() == label
    for other in ("--dry-run", "--auto"):
        assert (other in argv) is (other == flag)
