"""UX gap package C: the journeys a user stops on (J1, J2, J4, J6, J9, J10).

Ctrl-C (J6): a step that fails after a stop was requested was stopped, not failed.
"""

from __future__ import annotations

import io
from pathlib import Path
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


def test_the_resume_offer_does_not_stack_dots_after_a_cut_request(tmp_path):
    # Cold reader: a request cut to 50 characters ends in "..."; the offer printed "....".
    from ract import cli
    from ract.repl import ReplSession
    from ract.session_listing import sessions_dir
    from tests.test_repl import _Console

    folder = sessions_dir(tmp_path / "ract.yaml")
    folder.mkdir(parents=True)
    long_intent = (
        "add a greeting to src/calc.py and two tests for it, then update the docs"
    )
    (folder / "h-0123456789ab.json").write_text(
        '{"intent": "%s"}' % long_intent, encoding="utf-8"
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
    assert "...." not in console.text
    assert "/resume to continue it." in console.text


def test_the_stop_is_announced_before_the_cancel_takes_effect():
    # Error sweep: at the approval prompt a step's "failed" arrived before "stopping...",
    # because the cancel was set before the event was emitted. The announcement comes first.
    import threading

    from ract.repl import ReplSession
    from ract import cli
    from tests.test_repl import _Console

    order: list[str] = []

    class _Events:
        def emit(self, kind, data, turn=None):
            order.append(f"emit:{kind}")

    class _Cancel(threading.Event):
        def set(self):
            order.append("cancel")
            super().set()

    done = threading.Event()
    done.set()
    session = ReplSession(
        Path("ract.yaml"),
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session._events = _Events()
    session._interrupt(done, _Cancel(), 1, 0.0)
    assert order.index("emit:turn.interrupting") < order.index("cancel")


def test_resume_without_an_id_names_the_way_to_find_one(tmp_path):
    # Error sweep: "usage: /resume <id|latest>" alone does not say where the ids are.
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
    session._handle_command("/resume")
    assert "/sessions" in console.text


def test_no_sessions_says_how_one_starts(tmp_path):
    # Error sweep row 18: "no sessions yet" alone has no next action.
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
    session._handle_command("/sessions")
    assert "no sessions yet: a request you type starts one" in console.text


def test_the_missing_config_warning_fits_sixty_columns(tmp_path, monkeypatch):
    # Soak, 60 columns: the warning's "⚠  " prefix made its first line 61 columns.
    from ract import cli
    from ract.repl import ReplSession

    monkeypatch.setenv("COLUMNS", "60")
    shown: list[str] = []

    class _Console:
        def info(self, message):
            shown.append(message)

        def print(self, *args, **kwargs):
            shown.append(" ".join(str(a) for a in args))

        def warning(self, message):
            shown.append("⚠  " + message)

        def error(self, message):
            shown.append(message)

    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session._banner()
    warning_lines = [
        line for line in shown if "ract.yaml not found" in line or line.startswith("  ")
    ]
    assert warning_lines, shown
    assert all(len(line) <= 60 for line in shown if "[ract]" not in line), shown
