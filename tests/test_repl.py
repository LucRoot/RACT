"""Interactive session: command parsing, settings, dispatch, and survival of errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import cli
from ract.repl import ReplSession


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


def _session(inputs=(), *, codes=None, config=Path("ract.yaml")):
    calls: list[list[str]] = []
    outcomes = list(codes or [])
    typed = list(inputs)

    def dispatch(argv):
        calls.append(argv)
        outcome = outcomes.pop(0) if outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def read_line(prompt):
        if not typed:
            raise EOFError
        return typed.pop(0)

    console = _Console()
    session = ReplSession(
        config,
        dispatch=dispatch,
        read_line=read_line,
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, calls, console


# --- intents ------------------------------------------------------------------


def test_plain_text_runs_as_an_intent():
    session, calls, _ = _session()
    session.handle("add a docstring to hello.py")
    assert calls[0][0] == "run"
    assert calls[0][-2:] == ["--", "add a docstring to hello.py"]
    assert "--config" in calls[0]


def test_intent_equal_to_a_verb_name_stays_an_intent():
    """argv[0] must be 'run' and the text must follow '--', or 'docs' would dispatch the docs verb."""
    session, calls, _ = _session()
    session.handle("docs")
    assert calls[0][0] == "run" and calls[0][-1] == "docs"


def test_intent_starting_with_a_dash_is_not_parsed_as_an_option():
    session, calls, _ = _session()
    session.handle("--help me with this")
    assert calls[0][-2:] == ["--", "--help me with this"]


def test_blank_line_does_nothing():
    session, calls, _ = _session()
    assert session.handle("   ") is True
    assert calls == []


def test_exit_forms_end_the_session():
    for text in ("/exit", "/quit", "exit", "quit"):
        session, _, _ = _session()
        assert session.handle(text) is False


def test_eof_ends_the_loop_cleanly():
    session, _, _ = _session(inputs=[])
    assert session.run() == 0


def test_loop_processes_lines_until_exit():
    session, calls, _ = _session(inputs=["one", "two", "/exit", "never"])
    session.run()
    assert [c[-1] for c in calls] == ["one", "two"]


# --- context carries between turns --------------------------------------------


def test_second_turn_resumes_the_session_started_by_the_first():
    session, calls, _ = _session()
    session.handle("first")
    session.handle("second")
    assert "--resume" not in calls[0]
    assert calls[0][calls[0].index("--session") + 1] == session.state.session_id
    assert "--resume" in calls[1]


def test_failed_first_turn_does_not_resume_a_session_that_was_never_saved():
    session, calls, _ = _session(codes=[1, 0])
    session.handle("first")
    session.handle("second")
    assert "--resume" not in calls[1]


def test_session_new_starts_fresh_and_named_session_resumes():
    session, calls, _ = _session()
    session.handle("first")
    session.handle("/session new")
    session.handle("again")
    assert "--resume" not in calls[1]
    session.handle("/session project-x")
    session.handle("later")
    assert "--resume" in calls[2]
    assert calls[2][calls[2].index("--session") + 1] == "project-x"


# --- plan and loop ------------------------------------------------------------


def test_plan_command_is_a_dry_run_without_a_session():
    session, calls, _ = _session()
    session.handle("/plan refactor the greeter")
    argv = calls[0]
    assert "--dry-run" in argv
    assert "--session" not in argv
    assert session.state.session_started is False


def test_loop_command_uses_loop_flags_and_not_dry_run():
    session, calls, _ = _session()
    session.handle("/set dry-run on")
    session.handle("/loop build it")
    argv = calls[0]
    assert "--loop" in argv and "--dry-run" not in argv
    assert argv[argv.index("--max-iterations") + 1] == "10"


def test_missing_arguments_print_usage_and_dispatch_nothing():
    session, calls, console = _session()
    for cmd in ("/run", "/plan", "/loop"):
        session.handle(cmd)
    assert calls == []
    assert console.text.count("usage:") == 3


# --- settings -----------------------------------------------------------------


def test_set_dry_run_applies_to_plain_intents_and_changes_the_prompt():
    session, calls, _ = _session()
    assert session.prompt() == "ract> "
    session.handle("/set dry-run on")
    assert session.prompt() == "plan> "
    session.handle("do it")
    assert "--dry-run" in calls[0]


def test_set_stream_and_mode_reach_the_dispatcher():
    session, calls, _ = _session()
    session.handle("/set stream on")
    session.handle("/set mode documentation")
    session.handle("go")
    argv = calls[0]
    assert "--stream" in argv
    assert argv[argv.index("--mode") + 1] == "documentation"


def test_set_iterations_validates():
    session, calls, console = _session()
    session.handle("/set iterations 0")
    session.handle("/set iterations lots")
    assert session.state.max_iterations == 10
    session.handle("/set iterations 4")
    assert session.state.max_iterations == 4
    assert console.text.count("whole number") == 2


@pytest.mark.parametrize(
    "line", ["/set", "/set stream", "/set stream maybe", "/set mode wild", "/set nothing on"]
)
def test_bad_set_commands_change_nothing(line):
    session, calls, console = _session()
    before = vars(session.state).copy()
    session.handle(line)
    assert vars(session.state) == before
    assert calls == [] and console.lines


def test_settings_lists_every_setting():
    session, _, console = _session()
    session.handle("/settings")
    for label in ("config", "dry-run", "stream", "mode", "iterations", "session"):
        assert label in console.text


# --- verbs as slash commands --------------------------------------------------


def test_any_cli_verb_works_as_a_slash_command():
    session, calls, _ = _session()
    session.handle("/whisper --intent 'why is this here'")
    assert calls[0] == ["whisper", "--intent", "why is this here"]


def test_doctor_and_report_follow_the_session_config():
    session, calls, _ = _session(config=Path("other.yaml"))
    session.handle("/doctor --check-providers")
    session.handle("/report")
    assert calls[0] == ["doctor", "--check-providers", "--config", "other.yaml"]
    assert calls[1] == ["report", "--last", "--config", "other.yaml"]


def test_explicit_config_argument_is_not_overridden():
    session, calls, _ = _session(config=Path("other.yaml"))
    session.handle("/doctor --config mine.yaml")
    assert calls[0] == ["doctor", "--config", "mine.yaml"]


def test_config_command_validates_the_active_config():
    session, calls, _ = _session(config=Path("x.yaml"))
    session.handle("/config")
    assert calls[0] == ["config", "validate", "--config", "x.yaml"]


def test_unknown_command_is_reported_and_session_continues():
    session, calls, console = _session()
    assert session.handle("/frobnicate now") is True
    assert "unknown command /frobnicate" in console.text
    assert calls == []


def test_unbalanced_quote_is_reported_not_raised():
    session, calls, console = _session()
    assert session.handle("/whisper --intent 'oops") is True
    assert "could not parse" in console.text and calls == []


def test_help_lists_the_main_commands():
    session, _, console = _session()
    session.handle("/help")
    for needle in ("/run", "/plan", "/loop", "/set", "/doctor", "/exit"):
        assert needle in console.text


# --- survival -----------------------------------------------------------------


def test_nonzero_exit_is_reported_and_session_continues():
    session, calls, console = _session(codes=[2, 0])
    session.handle("bad")
    assert "exit code 2" in console.text
    session.handle("good")
    assert len(calls) == 2


def test_argparse_system_exit_does_not_end_the_session():
    session, calls, console = _session(codes=[SystemExit(2)])
    assert session.handle("bad") is True
    assert "exit code 2" in console.text


def test_unexpected_exception_does_not_end_the_session():
    session, calls, console = _session(codes=[RuntimeError("boom [x]")])
    assert session.handle("bad") is True
    assert "RuntimeError" in console.text


def test_ctrl_c_during_a_run_returns_to_the_prompt():
    session, calls, console = _session(codes=[KeyboardInterrupt()])
    assert session.handle("long job") is True
    assert "interrupted" in console.text


def test_ctrl_c_at_the_prompt_abandons_the_line():
    answers = iter([KeyboardInterrupt(), "/exit"])

    def read_line(prompt):
        item = next(answers)
        if isinstance(item, BaseException):
            raise item
        return item

    session = ReplSession(
        Path("ract.yaml"),
        dispatch=lambda argv: 0,
        read_line=read_line,
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    assert session.run() == 0


# --- providers ----------------------------------------------------------------


def test_providers_marks_the_manager(tmp_path):
    cfg = tmp_path / "ract.yaml"
    cfg.write_text(
        "project:\n  name: d\nmanager_provider: bolt\nproviders:\n"
        "  bolt:\n    adapter: local_http\n    model: m1\n    url: http://x/v1\n"
        "  north:\n    adapter: local_http\n    model: m2\n    url: http://x/v1\n",
        encoding="utf-8",
    )
    session, _, console = _session(config=cfg)
    session.handle("/providers")
    bolt = next(line for line in console.lines if line.startswith("bolt"))
    north = next(line for line in console.lines if line.startswith("north"))
    assert "manager" in bolt and "manager" not in north


def test_providers_with_missing_config_explains_the_next_step(tmp_path):
    session, _, console = _session(config=tmp_path / "nope.yaml")
    session.handle("/providers")
    assert "could not read" in console.text


def test_providers_warns_when_manager_is_ambiguous(tmp_path):
    cfg = tmp_path / "ract.yaml"
    cfg.write_text(
        "providers:\n  a:\n    adapter: local_http\n  b:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    session, _, console = _session(config=cfg)
    session.handle("/providers")
    assert "manager_provider" in console.text


# --- entry points -------------------------------------------------------------


def test_repl_is_a_registered_verb():
    assert "repl" in cli.CLI_VERBS


def test_repl_verb_refuses_without_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert cli.main(["repl"]) == 3
    assert "needs a terminal" in capsys.readouterr().err


def test_bare_ract_without_a_terminal_keeps_the_intent_required_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert "intent is required" in capsys.readouterr().err


def test_bare_ract_in_a_terminal_opens_the_session(monkeypatch):
    opened = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    monkeypatch.setattr("ract.repl.run_repl", lambda config=None: opened.append(config) or 0)
    assert cli.main([]) == 0
    assert opened == [Path("ract.yaml")]


def test_repl_verb_passes_the_config_through(monkeypatch):
    opened = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    monkeypatch.setattr("ract.repl.run_repl", lambda config=None: opened.append(config) or 0)
    assert cli.main(["repl", "--config", "my.yaml"]) == 0
    assert opened == [Path("my.yaml")]


def _capture_run_ract(monkeypatch):
    from ract.rooted import Rooted

    seen: dict = {}

    def fake(config, intent, **kwargs):
        seen.update(config=config, intent=intent, **kwargs)
        return Rooted(error="stub", assumption="s", confidence=0.0, provenance=["t"])

    monkeypatch.setattr("ract.cli.run_ract", fake)
    return seen


@pytest.mark.parametrize("intent", ["fix the bug", "docs", "--help me", "report"])
def test_built_argv_reaches_run_ract_with_the_intent_intact(intent, tmp_path, monkeypatch):
    """The argv the session builds must parse in the real CLI, including awkward intents."""
    seen = _capture_run_ract(monkeypatch)
    monkeypatch.chdir(tmp_path)
    session, _, _ = _session(config=Path("c.yaml"))
    session.handle("/set stream on")
    assert cli.main(session.build_run_argv(intent)) == 1  # stub returns an error
    assert seen["intent"] == intent
    assert seen["config"] == Path("c.yaml")
    assert seen["stream"] is True
    assert seen["session_id"] == session.state.session_id
    assert seen["resume"] is False and seen["dry_run"] is False


def test_second_turn_argv_resumes_in_the_real_cli(tmp_path, monkeypatch):
    seen = _capture_run_ract(monkeypatch)
    monkeypatch.chdir(tmp_path)
    session, _, _ = _session()
    session.state.session_started = True
    cli.main(session.build_run_argv("next"))
    assert seen["resume"] is True


def test_plan_argv_reaches_run_ract_as_dry_run(tmp_path, monkeypatch):
    seen = _capture_run_ract(monkeypatch)
    monkeypatch.chdir(tmp_path)
    session, _, _ = _session()
    cli.main(session.build_run_argv("look", dry_run=True))
    assert seen["dry_run"] is True and seen["session_id"] is None
