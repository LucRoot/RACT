"""Operator order 2026-11-03 A: the on-ramp to commands.

``/test`` runs the granted test command through the same tier-3 path as a
model-requested command; with no grant it prints the on-ramp and runs
nothing. The setup closing offer asks in a terminal only, default yes, and
reuses the guided grant (no second signing path). The passphrase never
appears in any shown line, log or record.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract import cli
from ract.policy.grant import load_grant
from ract.policy.guided import guided_init
from ract.repl import ReplSession

PASS = "throwaway passphrase for a test"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


class _Console:
    """Records output so tests can assert on what the operator would see."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    info = success = warning = error = print

    def table(self, title, columns, rows) -> None:
        self.lines.append(title)
        for row in rows:
            self.lines.append(" | ".join(str(c) for c in row))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _session(config: Path, inputs=()):
    typed = list(inputs)

    def read_line(prompt):
        if not typed:
            raise EOFError
        return typed.pop(0)

    console = _Console()
    session = ReplSession(
        config,
        dispatch=lambda argv: 0,
        read_line=read_line,
        console=console,
        verbs=cli.CLI_VERBS,
    )
    session._tier3_facts()  # what session start reads: grant state, pin, mode
    return session, console


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8"
    )
    (root / "ract.yaml").write_text("project:\n  name: calc\n", encoding="utf-8")
    return root


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    monkeypatch.setenv("XDG_STATE_HOME", str(folder))
    return folder / "ract"


def _sign_grant(project: Path, monkeypatch) -> None:
    """A signed throwaway grant for the project's pytest, keys in temp state."""
    folder = project.parent / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    monkeypatch.setenv("XDG_STATE_HOME", str(folder))

    def read_passphrase(prompt: str = "", *, confirm: bool = False) -> str:
        return PASS

    code = guided_init(
        project,
        ask=lambda _q: "y",
        show=lambda _line: None,
        read_passphrase=read_passphrase,
        now=NOW,
    )
    assert code == 0
    assert load_grant(project).holds


def test_test_with_no_grant_prints_the_on_ramp_and_runs_nothing(
    project: Path, user_config: Path, capsys: pytest.CaptureFixture
) -> None:
    session, console = _session(project / "ract.yaml", inputs=["/test", "/exit"])
    assert session.handle("/test") is True
    out = console.text + capsys.readouterr().out
    assert "policy init" in out and "--guided" in out
    assert not (project / ".ract" / "commands.jsonl").exists()


def test_test_with_a_grant_runs_the_tests_and_records_the_command(
    project: Path, user_config: Path, monkeypatch, capsys: pytest.CaptureFixture
) -> None:
    _sign_grant(project, monkeypatch)
    session, console = _session(project / "ract.yaml", inputs=["/test", "/exit"])
    assert session.handle("/test") is True
    out = console.text + capsys.readouterr().out
    assert "1 passed" in out
    # The result feeds the next turn so the model can act on a failure.
    assert session._pending_test_fact is not None
    assert "passed" in session._pending_test_fact
    # The command record exists in the user state dir, never the project.
    records = list(user_config.rglob("commands.jsonl"))
    assert records, "the command record was written"
    line = json.loads(records[0].read_text(encoding="utf-8").splitlines()[-1])
    assert line.get("kind") == "tests" or "pytest" in json.dumps(line)


def test_the_passphrase_never_appears_in_any_output_or_record(
    project: Path, user_config: Path, monkeypatch, capsys: pytest.CaptureFixture
) -> None:
    _sign_grant(project, monkeypatch)
    session, console = _session(project / "ract.yaml", inputs=["/test", "/exit"])
    session.handle("/test")
    everywhere = console.text + capsys.readouterr().out
    for record in user_config.rglob("*"):
        if record.is_file():
            everywhere += record.read_text(encoding="utf-8", errors="replace")
    assert PASS not in everywhere


def test_a_refusal_reaches_the_operator_in_plain_words(
    project: Path, user_config: Path, monkeypatch, capsys: pytest.CaptureFixture
) -> None:
    # A grant whose test rule exists, then ask /test for a selector that is
    # not a test path: the refusal prints and nothing runs.
    _sign_grant(project, monkeypatch)
    session, console = _session(
        project / "ract.yaml", inputs=["/test ../outside.py", "/exit"]
    )
    session.handle("/test ../outside.py")
    out = console.text + capsys.readouterr().out
    assert "not run:" in out or "refused" in out.lower()


def test_the_test_result_rides_the_next_intent(
    project: Path, user_config: Path, monkeypatch
) -> None:
    _sign_grant(project, monkeypatch)
    seen: list[list[str]] = []

    def dispatch(argv):
        seen.append(list(argv))
        return 0

    typed = iter(["/test", "fix it please", "/exit"])

    def read_line(prompt):
        return next(typed)

    session = ReplSession(
        project / "ract.yaml",
        dispatch=dispatch,
        read_line=read_line,
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session._tier3_facts()  # noqa: SLF001
    session.handle("/test")
    session.handle("fix it please")
    intents = [a for argv in seen for a in argv if "fix it please" in a]
    assert intents and "tests from /test" in intents[0]

class _Io:
    """The wizard Io shape: say, ask, width."""

    def __init__(self, answers=()):
        self.lines: list[str] = []
        self._answers = list(answers)
        self.asked: list[str] = []

    def say(self, line: object) -> None:
        self.lines.append(str(line))

    def ask(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self._answers.pop(0) if self._answers else ""

    def width(self) -> int:
        return 80


def _offer(project: Path, io: "_Io", monkeypatch) -> None:
    from ract.policy.grant import load_grant
    from ract.setup.wizard import _offer_test_grant

    monkeypatch.setattr(
        "ract.policy.operator_key.read_passphrase",
        lambda prompt="", *, confirm=False: PASS,
    )
    _offer_test_grant(project, io, 0)
    assert load_grant(project).holds is not None


def test_setup_offer_yes_signs_the_grant_and_never_shows_the_passphrase(
    project: Path, user_config: Path, monkeypatch
) -> None:
    io = _Io(answers=["y", "y", "y", "y"])
    _offer(project, io, monkeypatch)
    from ract.policy.grant import load_grant

    assert load_grant(project).holds
    shown = "\n".join(io.lines)
    assert "run your tests" in shown
    assert "ract policy revoke" in shown
    assert PASS not in shown


def test_setup_offer_no_prints_one_line_on_how_to_do_it_later(
    project: Path, user_config: Path, monkeypatch
) -> None:
    io = _Io(answers=["n"])
    _offer(project, io, monkeypatch)
    from ract.policy.grant import load_grant

    assert not load_grant(project).holds
    later = [l for l in io.lines if "guided" in l]
    assert later and "policy init" in later[-1]


def test_setup_offer_bare_enter_is_yes(
    project: Path, user_config: Path, monkeypatch
) -> None:
    io = _Io(answers=["", "y", "y", "y"])
    _offer(project, io, monkeypatch)
    from ract.policy.grant import load_grant

    assert load_grant(project).holds


def test_setup_offer_skipped_when_a_grant_already_holds(
    project: Path, user_config: Path, monkeypatch
) -> None:
    _sign_grant(project, monkeypatch)
    io = _Io(answers=["y", "y", "y", "y"])
    _offer(project, io, monkeypatch)
    assert io.asked == []  # never asked: the grant already holds


def test_setup_offer_with_no_test_runner_names_that(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "empty"
    root.mkdir()
    (root / "ract.yaml").write_text("project:" + chr(10) + "  name: e" + chr(10), encoding="utf-8")
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    monkeypatch.setattr(
        "ract.policy.operator_key.read_passphrase",
        lambda prompt="", *, confirm=False: PASS,
    )
    from ract.setup.wizard import _offer_test_grant

    io = _Io(answers=["y", "y", "y", "y"])
    _offer_test_grant(root, io, 0)
    assert any("no test runner" in line for line in io.lines)

def test_the_test_result_rides_the_next_turn_in_event_mode(
    project: Path, user_config: Path, monkeypatch
) -> None:
    """The reader's blocker: real sessions are event mode (no dispatch), so
    the injection must run before the event branch. This builds the session
    the way run_repl does and captures what _event_turn receives."""
    _sign_grant(project, monkeypatch)
    session = ReplSession(
        project / "ract.yaml",
        dispatch=None,  # production construction: event mode
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session._tier3_facts()  # noqa: SLF001
    session._events = object()  # run_repl sets the real event stream
    seen: list[str] = []
    session._event_turn = lambda intent, dry=False, ask=False: seen.append(intent) or 0  # noqa: SLF001
    session.handle("/test")
    assert session._pending_test_fact is not None
    session._run_intent("fix the failing test")  # noqa: SLF001
    assert seen and "tests from /test" in seen[0]
    assert "fix the failing test" in seen[0]
