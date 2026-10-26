"""B-054f: wording and status fixes from the B-054 walkthrough (D9, D10, D11)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ract import cli
from ract.repl import ReplSession
from ract.session_events import EventStream
from ract.session_render import PlainRenderer
from tests.test_repl import _Console


def _render(*events: tuple[str, dict[str, Any]]) -> str:
    out = io.StringIO()
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc),
    )
    renderer = PlainRenderer(out.write, width=80)
    stream.subscribe(renderer)
    for kind, data in events:
        stream.emit(kind, data, turn=1)
    renderer.close()
    return out.getvalue()


def test_the_session_line_names_a_missing_model_and_provider_in_words():
    # D11: a session with no model set printed "RACT session ? via ?".
    line = next(
        ln
        for ln in _render(("session.started", {})).splitlines()
        if ln.startswith("RACT session")
    )
    assert "?" not in line
    assert "no model" in line
    assert "no provider" in line


def test_the_session_line_still_shows_a_configured_model_and_provider():
    line = next(
        ln
        for ln in _render(
            ("session.started", {"model": "fake-coder", "provider": "local"})
        ).splitlines()
        if ln.startswith("RACT session")
    )
    assert line.startswith("RACT session fake-coder via local")


def test_failed_calls_say_the_provider_did_not_report_tokens():
    # D9: "tokens not reported" alone does not say who did not report them.
    out = io.StringIO()
    renderer = PlainRenderer(out.write, width=80)
    renderer._cost = {"requests": 4}
    assert "tokens not reported by the provider" in renderer._cost_line(6.4)


def test_a_missing_config_does_not_tell_the_operator_to_leave():
    # D10: the session does not exit; "Leave" misled.
    console = _Console()
    session = ReplSession(
        Path("no_such_dir/ract.yaml"),
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    session._banner()
    assert "Leave" not in console.text
    assert "Run ract setup in another terminal" in console.text


def test_a_provider_error_shows_its_message_not_the_raw_json_body():
    # D8: the J10 capture printed the whole JSON body after the status.
    text = _render(
        (
            "error.surfaced",
            {
                "message": 'Provider call failed: HTTP 503: {"error":{"message":"fake server error 503","type":"server_error"}}',
                "hint": "run `ract doctor --check-providers` to check the setup, then try again",
            },
        )
    )
    assert "error: Provider call failed: HTTP 503: fake server error 503" in text
    assert "{" not in text


def test_an_error_without_a_json_body_is_unchanged():
    text = _render(
        ("error.surfaced", {"message": "Plan contains no steps.", "hint": "x"})
    )
    assert "error: Plan contains no steps." in text


def test_the_provenance_warning_prints_once_per_session():
    # D7: the warning repeated on every turn. The turn summary still says "unsigned: N".
    notice = {
        "level": "warning",
        "text": "provenance: 1 file(s) written without a Rootknot (a.py).",
    }
    text = _render(("notice", notice), ("notice", notice))
    assert text.count("provenance: 1 file(s)") == 1
