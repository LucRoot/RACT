"""Package P: fuzz the REPL line dispatcher and the answer handling.

The UX bar says a user never sees a traceback. Random lines, control bytes, NUL, a lone
escape, a very long line, unknown slash commands with Unicode, a lone "/", trailing spaces
and whitespace-only lines must all return to the prompt without an exception.
The intent path uses a stub dispatch, so nothing reaches a model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ract import cli
from ract.repl import ReplSession
from tests.test_repl import _Console


def _session(tmp_path: Path) -> ReplSession:
    return ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )


LINES = st.text(
    alphabet=st.sampled_from(
        list("abc /-=\t") + ["\x00", "\x1b", "\x07", "é", "日", "🙂", "‮", "\r"]
    ),
    max_size=200,
)


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(LINES)
def test_any_line_returns_to_the_prompt(tmp_path, line):
    session = _session(tmp_path)
    result = session.handle(line)
    assert result in (True, False)


@pytest.mark.parametrize(
    "line",
    [
        "/",
        "/ ",
        "   ",
        "\t",
        "/\x00",
        "\x1b",
        "/\x1b[31m",
        "/日本語",
        "/hlep ✓",
        "/run",
        "/model \x00",
        "/resume ../../etc",
        "x" * 20000,
        "/" + "y" * 20000,
        "trailing spaces   ",
        "‮direction",
    ],
)
def test_the_hard_lines_return_to_the_prompt(tmp_path, line):
    session = _session(tmp_path)
    assert session.handle(line) in (True, False)


def test_a_megabyte_paste_is_one_line_and_returns(tmp_path):
    session = _session(tmp_path)
    assert session.handle("a" * 1_000_000) is True


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=300))
def test_any_approval_answer_is_a_yes_or_a_no(answer):
    from unittest import mock

    from ract.approval_callback import console_approval_callback
    from ract.manager import Step

    step = Step(action="fix", provider_hint="local", expected_artifact="src/calc.py")
    with mock.patch("builtins.input", lambda prompt="": answer):
        result = console_approval_callback(step)
    assert result is (answer.strip().lower() in {"y", "yes"})


@settings(max_examples=100, deadline=None)
@given(st.text(max_size=300))
def test_eof_at_the_approval_question_is_a_no(answer):
    from unittest import mock

    from ract.approval_callback import console_approval_callback
    from ract.manager import Step

    def eof(prompt=""):
        raise EOFError

    step = Step(action="fix", provider_hint="local", expected_artifact="src/calc.py")
    with mock.patch("builtins.input", eof):
        assert console_approval_callback(step) is False


def test_a_second_ctrl_c_while_the_setup_stop_is_printed_does_not_traceback(
    monkeypatch, capsys
):
    # Package P: two Ctrl-C in a row at the setup question. The second one arrived while
    # the "Setup stopped" line was printed, and escaped as a traceback.
    import builtins

    from ract import cli

    def interrupted(prompt=""):
        raise KeyboardInterrupt

    real_print = builtins.print
    calls = {"n": 0}

    def print_then_interrupt(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", print_then_interrupt)
    try:
        result = cli._offer_setup(ask=interrupted)
    except KeyboardInterrupt:
        pytest.fail(
            "a second Ctrl-C escaped _offer_setup as a KeyboardInterrupt (a traceback for the user)"
        )
    assert result is False


def test_a_second_ctrl_c_while_the_prompt_is_cleared_does_not_traceback(tmp_path):
    # Package P: Ctrl-C at the prompt ends the line with print(""); a second Ctrl-C during
    # that print escaped run() as a KeyboardInterrupt traceback.
    class _Interrupting(_Console):
        armed = False

        def print(self, *args, **kwargs):
            if self.armed and args == ("",):
                self.armed = False
                raise KeyboardInterrupt
            super().print(*args, **kwargs)

    console = _Interrupting()
    answers = iter([None, "/exit"])

    def read_line(prompt):
        value = next(answers)
        if value is None:
            console.armed = True
            raise KeyboardInterrupt
        return value

    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=read_line,
        console=console,
        verbs=cli.CLI_VERBS,
    )
    try:
        result = session.run()
    except KeyboardInterrupt:
        pytest.fail(
            "a second Ctrl-C escaped run() as a KeyboardInterrupt (a traceback for the user)"
        )
    assert result == 0
