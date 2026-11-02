"""B-8repl (audit round 2, P1): ``/todo`` and ``/spec`` do not end the session.

``ReplSession.run`` treats a falsy ``handle()`` result as the end of the
session, so an informational command that returns False prints its output and
then terminates the loop. ``/diff``, ``/review``, ``/checkpoint`` and
``/settings`` all return True; ``/todo`` and ``/spec`` must too.
"""

from __future__ import annotations

from pathlib import Path

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


def _session(inputs=()):
    typed = list(inputs)

    def read_line(prompt):
        if not typed:
            raise EOFError
        return typed.pop(0)

    console = _Console()
    session = ReplSession(
        Path("ract.yaml"),
        dispatch=lambda argv: 0,
        read_line=read_line,
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, console


def _handled_lines(session: ReplSession) -> list[tuple[str, bool]]:
    """Wrap handle() so run() can be driven with faked input and every line
    and its verdict recorded."""
    seen: list[tuple[str, bool]] = []
    real_handle = session.handle

    def recording(line):
        result = real_handle(line)
        seen.append((line, result))
        return result

    session.handle = recording
    return seen


def test_todo_does_not_end_the_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    session, _ = _session(inputs=["/todo", "/help", "/exit"])
    seen = _handled_lines(session)
    assert session.run() == 0
    # /help ran after /todo, so the session did not end at /todo; only /exit ends it.
    assert [line for line, _ in seen] == ["/todo", "/help", "/exit"]
    assert seen[0][1] is True
    assert seen[-1][1] is False


def test_spec_does_not_end_the_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ract.spec_guide.walk", lambda *a, **k: None)
    session, _ = _session(inputs=["/spec", "/help", "/exit"])
    seen = _handled_lines(session)
    assert session.run() == 0
    assert [line for line, _ in seen] == ["/spec", "/help", "/exit"]
    assert seen[0][1] is True


def test_todo_and_spec_return_true_only_exit_returns_false(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ract.spec_guide.walk", lambda *a, **k: None)
    session, _ = _session()
    assert session._handle_command("/todo") is True
    assert session._handle_command("/spec") is True
    assert session._handle_command("/exit") is False
