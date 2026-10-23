"""B-032b: /context reports what is known, labels what is not, and makes no request.

The numbers come from the egress ledger and the probe result (L-141). A
number that is not reported is shown as "not reported"; a window that is not
known is shown as "unknown". No character-based estimate is shown.
"""

from __future__ import annotations

from pathlib import Path

from ract import cli
from ract.context_view import context_lines
from ract.repl import ReplSession


def _record(**fields):
    base = {
        "t": "2026-10-23T10:00:00Z",
        "pid": 1,
        "purpose": "plan",
        "kind": "chat",
        "host": "127.0.0.1",
        "port": 8010,
        "status": 200,
        "ms": 12,
        "bytes_out": 100,
        "bytes_in": 200,
        "tokens_in": None,
        "tokens_out": None,
    }
    base.update(fields)
    return base


def test_with_no_request_yet_it_says_so_and_the_window_is_unknown():
    lines = context_lines([], None)
    assert any("no model request" in line for line in lines)
    assert any(line.startswith("window: unknown") for line in lines)
    assert any("not stored" in line for line in lines)


def test_a_reported_last_request_shows_its_tokens_and_its_host():
    lines = context_lines(
        [_record(tokens_in=1200, tokens_out=80, host="127.0.0.1")], None
    )
    text = "\n".join(lines)
    assert "1200" in text and "80" in text
    assert "127.0.0.1" in text


def test_a_request_without_usage_says_not_reported_and_never_estimates():
    text = "\n".join(context_lines([_record()], None))
    assert "not reported" in text
    assert "estimate" not in text


def test_a_known_window_is_shown_from_the_server():
    text = "\n".join(context_lines([], 32768))
    assert "window is 32768 tokens (from the server)" in text


def test_the_line_about_what_it_cannot_see_is_present():
    text = "\n".join(context_lines([], None))
    assert "built per step" in text


def test_hostile_host_text_is_shown_through_safe_text():
    lines = context_lines(
        [_record(host="evil\x1b[2J.example", tokens_in=1, tokens_out=1)], None
    )
    text = "\n".join(lines)
    assert "\x1b" not in text


def test_every_line_fits_sixty_and_forty_columns():
    records = [_record(tokens_in=1200, tokens_out=80, host="127.0.0.1")]
    for width in (60, 40):
        for line in context_lines(records, None, width=width):
            assert len(line) <= width, (width, line)


def test_slash_context_is_in_the_help_and_makes_no_model_call(
    tmp_path: Path, monkeypatch
):
    calls: list = []

    def dispatch(argv):
        calls.append(argv)
        return 0

    lines: list[str] = []

    class _Console:
        def print(self, *args, **kwargs):
            lines.append(" ".join(str(a) for a in args))

        info = success = warning = error = print

        def table(self, title, columns, rows):
            lines.append(title)
            for row in rows:
                lines.append(" | ".join(str(c) for c in row))

    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=dispatch,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session.handle("/context")
    assert calls == []
    assert "window" in "\n".join(lines)
    session.handle("/help")
    assert "/context" in "\n".join(lines)
