"""UX gap package C: the journeys a user stops on (J1, J2, J4, J6, J9, J10).

Ctrl-C (J6): a step that fails after a stop was requested was stopped, not failed.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from ract.session_events import EventStream
from ract.session_render import PlainRenderer


def _render(*events: tuple[str, dict[str, Any]]) -> str:
    out = io.StringIO()
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 25, 19, 40, tzinfo=timezone.utc),
    )
    renderer = PlainRenderer(out.write, width=80)
    stream.subscribe(renderer)
    for kind, data in events:
        stream.emit(kind, data, turn=1)
    renderer.close()
    return out.getvalue()


PLAN = (
    "plan.proposed",
    {
        "assumption": "",
        "confidence": 0.9,
        "steps": [
            {"n": 1, "action": "fix add", "target": "src/calc.py"},
            {"n": 2, "action": "add notes", "target": "src/notes.py"},
        ],
    },
)


def test_a_step_that_fails_after_ctrl_c_is_skipped_not_failed():
    # J6: "[!] 1. Fix add() ... failed" after the operator stopped the turn.
    text = _render(
        PLAN,
        ("step.started", {"n": 1, "action": "fix add", "target": "src/calc.py"}),
        ("turn.interrupting", {"cancellable": False}),
        (
            "step.finished",
            {"n": 1, "outcome": "failed", "duration_ms": 9400, "hint": None},
        ),
        ("turn.finished", {"outcome": "interrupted", "verdict": "", "changed": []}),
    )
    final = [
        line for line in text.splitlines() if line.startswith("[") and "fix add" in line
    ]
    assert final[-1].startswith("[-] 1. fix add"), final
    assert "failed" not in final[-1]


def test_a_step_that_fails_before_any_stop_is_still_failed():
    text = _render(
        PLAN,
        ("step.started", {"n": 1, "action": "fix add", "target": "src/calc.py"}),
        (
            "step.finished",
            {"n": 1, "outcome": "failed", "duration_ms": 900, "hint": "x"},
        ),
        ("turn.finished", {"outcome": "failed", "verdict": "", "changed": []}),
    )
    final = [
        line for line in text.splitlines() if line.startswith("[") and "fix add" in line
    ]
    assert final[-1].startswith("[!] 1. fix add"), final


def test_the_start_screen_offers_the_last_session(tmp_path):
    # J2: "Resume offers yesterday's session." The offer names the session and the command.
    from ract import cli
    from ract.repl import ReplSession
    from ract.session_listing import sessions_dir
    from tests.test_repl import _Console

    folder = sessions_dir(tmp_path / "ract.yaml")
    folder.mkdir(parents=True)
    (folder / "h-abc123def456.json").write_text(
        '{"intent": "fix the failing test"}', encoding="utf-8"
    )
    console = _Console()
    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    session._resume_offer()
    assert "h-abc123def456" in console.text
    assert "fix the failing test" in console.text
    assert "/resume" in console.text


def test_no_saved_session_means_no_offer(tmp_path):
    from ract import cli
    from ract.repl import ReplSession
    from tests.test_repl import _Console

    console = _Console()
    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    session._resume_offer()
    assert console.text == ""
