"""B-034: the session's permission modes, shown in the status line."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from ract.approval_callback import console_approval_callback
from ract.manager import Step
from tests.test_repl import _session
from tests.test_session_turn import _repo
from tests.ux.terminal_driver import spawn


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


@pytest.mark.parametrize(("reply", "written"), [("y", True), ("n", False)])
def test_default_mode_asks_before_the_change_in_a_real_session(
    tmp_path: Path, fake_model_server: Any, reply: str, written: bool
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    session = spawn([_ract_exe()], cwd=str(ws), env=env, cols=100, rows=40)
    try:
        # The OPERATOR's start mode: a real session starts in `default` and
        # asks with no /mode command (B-034).
        assert session.expect(r"\| default \|", 30)  # the status line
        session.send_line("fix add")
        assert session.expect(r"Approve step: .*src/calc\.py\? \[y/N\]", 60)
        session.send_line(reply)
        assert session.expect(r"ract> ", 60)
    finally:
        if session.alive():
            session.send_line("/exit")
        session.close(timeout=15)
    after = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    assert (after != before) is written


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
