"""Session events schema version 2 (B-012, docs/EVENTS_SESSION.md).

Covers what version 2 added: streaming redaction, reserved kinds, the text
channel, plan and step events through a real turn, the turn.finished facts,
agent.retry, the turn context, and change detection on a dirty tree.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.executor.worktree import working_tree_status
from ract.redaction import HOLD_BACK_CHARS, StreamingRedactor, redact
from ract.retry_policy import RetryConfig, RetryPolicy
from ract.session_events import (
    EventStream,
    SessionEvent,
    UnknownEventKind,
    plan_event_data,
)
from ract.session_render import PlainRenderer
from ract.session_turn import TurnRequest, run_turn
from tests.test_session_turn import _plan, _repo

KEYS = [
    "sk-proj-" + "A1b2C3d4E5f6G7h8J9k0L1m2N3p4",
    "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "nvapi-" + "Zx9_Yw8-Vu7Ts6Rq5Po4Nm3",
]


def _stream() -> tuple[EventStream, list[SessionEvent]]:
    stream = EventStream(
        session="s-v2", clock=lambda: datetime(2026, 10, 21, tzinfo=timezone.utc)
    )
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    return stream, events


def _leaks(secret: str, text: str, run: int = 8) -> bool:
    return any(secret[i : i + run] in text for i in range(len(secret) - run + 1))


# ---------------------------------------------------------------- redaction


@pytest.mark.parametrize("secret", KEYS)
def test_a_key_split_at_every_offset_never_reaches_an_event(secret: str) -> None:
    text = f"the config says token={secret} and then more prose follows here.\n"
    for cut in range(1, len(text)):
        stream, events = _stream()
        writer = stream.writer(turn=1)
        writer.feed(text[:cut])
        writer.feed(text[cut:])
        writer.close()
        joined = "".join(e.data["text"] for e in events)
        assert not _leaks(secret, joined), (secret, cut)
        assert "[redacted]" in joined
        assert joined.startswith("the config says token=")


def test_a_key_fed_one_character_at_a_time_is_redacted() -> None:
    secret = KEYS[1]
    redactor = StreamingRedactor()
    out = "".join(redactor.feed(ch) for ch in f"x {secret} y") + redactor.close()
    assert out == "x [redacted] y"


PROSE = (
    "The configuration loader reads ract.yaml, merges the provider section "
    "with the defaults and validates the result before the first turn runs.\n"
) * 4


def _feed_in_chunks(text: str, size: int) -> tuple[str, int]:
    redactor = StreamingRedactor()
    out, most_held = "", 0
    for i in range(0, len(text), size):
        out += redactor.feed(text[i : i + size])
        most_held = max(most_held, redactor.held)
    return out + redactor.close(), most_held


def test_prose_lags_by_about_one_word() -> None:
    """G-026: a slow model's text must stay visible as it arrives."""
    out, most_held = _feed_in_chunks(PROSE, 4)
    assert out == PROSE
    assert most_held <= 20
    redactor = StreamingRedactor()
    redactor.feed(PROSE)
    redactor.close()
    assert redactor.held == 0  # a message ends with nothing withheld


def test_a_token_longer_than_the_hold_back_releases_its_head() -> None:
    redactor = StreamingRedactor()
    assert redactor.feed("x" * 300) == "x" * (300 - HOLD_BACK_CHARS)
    assert redactor.held == HOLD_BACK_CHARS


@pytest.mark.parametrize("size", [1, 3, 7, 50, 4096])
def test_a_private_key_block_never_appears_at_any_chunk_size(size: int) -> None:
    body = "MIIEowIBAAKCAQEA1234567890abcdefghij\n" * 120  # longer than 4 KiB
    text = (
        "see:\n-----BEGIN RSA PRIVATE KEY-----\n"
        + body
        + "-----END RSA PRIVATE KEY-----\nafter\n"
    )
    out, _ = _feed_in_chunks(text, size)
    assert out == "see:\n[redacted]\nafter\n"


@pytest.mark.parametrize("size", [1, 2, 5, 9])
def test_bearer_and_authorization_keep_the_token_with_the_keyword(size: int) -> None:
    text = "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123' url\n"
    out, _ = _feed_in_chunks(text, size)
    assert "abcdefghijklmnop" not in out
    assert out.startswith("curl -H 'Authorization: ")


def test_a_certificate_is_not_a_key_and_is_released() -> None:
    text = "-----BEGIN CERTIFICATE-----\nMIIBabc\n-----END CERTIFICATE-----\n"
    assert _feed_in_chunks(text, 3)[0] == text


def test_redact_keeps_url_host_and_ordinary_code() -> None:
    assert (
        redact("git clone https://user:hunter2pass@example.invalid/r.git")
        == "git clone https://[redacted]@example.invalid/r.git"
    )
    code = "def ask(sk_model):\n    return 'sk-' + name  # task-list\n"
    assert redact(code) == code


def test_every_string_field_is_redacted_not_only_text() -> None:
    stream, events = _stream()
    stream.emit("turn.started", {"input": f"use {KEYS[0]}", "queued": False}, turn=1)
    assert not _leaks(KEYS[0], events[0].to_json())


# ---------------------------------------------------------------- schema


def test_reserved_kinds_are_refused_with_a_reason() -> None:
    stream, _ = _stream()
    with pytest.raises(UnknownEventKind, match="reserved"):
        stream.emit("context.compacted", {})


def test_artifact_channel_needs_a_path_and_carries_it() -> None:
    stream, events = _stream()
    with pytest.raises(ValueError, match="path"):
        stream.writer(turn=1, channel="artifact")
    stream.text("x = 1\n", turn=1, channel="artifact", path="src/a.py")
    stream.text("done\n", turn=1)
    assert events[0].data == {
        "text": "x = 1\n",
        "channel": "artifact",
        "path": "src/a.py",
    }
    assert events[1].data == {"text": "done\n", "channel": "answer"}


def test_plan_event_data_shape() -> None:
    class Step:
        def __init__(self, action: str, target: str) -> None:
            self.action, self.expected_artifact = action, target

    class Plan:
        assumption, confidence = "add subtracts", 0.9
        steps = [Step("Fix add", "src/calc.py"), Step("Explain", "")]

    assert plan_event_data(Plan()) == {
        "assumption": "add subtracts",
        "confidence": 0.9,
        "steps": [
            {"n": 1, "action": "Fix add", "target": "src/calc.py"},
            {"n": 2, "action": "Explain", "target": None},
        ],
    }


# ---------------------------------------------------------------- turn context


def test_turn_context_is_a_no_op_when_nothing_is_bound() -> None:
    turn_context.bind(None)
    turn_context.report("step.started", {"n": 1})  # must not raise
    assert turn_context.cancelled() is False


def test_retry_policy_reports_agent_retry_through_the_turn_context() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    turn_context.bind(threading.Event(), lambda k, d: seen.append((k, d)))
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("connection reset")
        return "ok"

    try:
        policy = RetryPolicy(
            RetryConfig(max_retries=3, base_delay=0.25, max_delay=5.0, jitter=False)
        )
        value, error = policy.execute(
            flaky, lambda e: True, sleep=lambda s: None, on_retry=turn_context.on_retry
        )
    finally:
        turn_context.bind(None)
    assert (value, error) == ("ok", None)
    assert [k for k, _ in seen] == ["agent.retry", "agent.retry"]
    assert seen[0][1] == {
        "attempt": 1,
        "max": 3,
        "reason": "ConnectionError: connection reset",
        "wait_ms": 250,
    }


# ---------------------------------------------------------------- real turns


def test_turn_reports_plan_steps_and_artifact_text(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    stream, events = _stream()

    code = run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml", intent="fix add", session_id=None, resume=False
        ),
        turn=1,
        cancel=threading.Event(),
    )

    assert code == 0
    kinds = [e.kind for e in events]
    assert kinds.index("plan.proposed") < kinds.index("step.started")
    assert kinds.index("step.started") < kinds.index("step.finished")
    plan = next(e for e in events if e.kind == "plan.proposed").data
    assert plan["steps"][0]["target"] == "src/calc.py"
    assert 0.0 <= plan["confidence"] <= 1.0
    step = next(e for e in events if e.kind == "step.finished").data
    assert step["n"] == 1 and step["outcome"] == "done"
    assert step["artifact"] == "src/calc.py"
    texts = [e.data for e in events if e.kind == "agent.text.delta"]
    assert texts and all(
        t["channel"] == "artifact" and t["path"] == "src/calc.py" for t in texts
    )
    finished = events[-1].data
    assert finished["verification"] == {"status": "not-run", "runs": [], "claims": []}
    assert finished["provenance"] == {
        "signed": False,
        "unsigned_files": ["src/calc.py"],
    }
    assert finished["workspace"].startswith("1 file changed: src/calc.py")


def test_a_failing_step_is_closed_with_a_hint(
    tmp_path: Path, fake_model_server: Any
) -> None:
    from tests.fixtures.fake_model_server import Scenario

    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": _plan(".ract/x.key")}},
                    {"reply": {"kind": "text", "content": "anything\n"}},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    stream, events = _stream()

    run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml", intent="write it", session_id=None, resume=False
        ),
        turn=1,
        cancel=threading.Event(),
    )

    started = [e for e in events if e.kind == "step.started"]
    finished = [e for e in events if e.kind == "step.finished"]
    assert len(started) == len(finished) == 1
    assert finished[0].data["outcome"] in {"failed", "refused"}
    assert finished[0].data["hint"]


def test_second_edit_to_an_already_modified_file_is_a_change(tmp_path: Path) -> None:
    ws = tmp_path / "r"
    ws.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=d",
            "-c",
            "user.email=d@example.invalid",
            "commit",
            "-q",
            "-m",
            "c",
        ],
        cwd=ws,
        check=True,
    )
    (ws / "a.py").write_text("x = 2\n", encoding="utf-8")  # dirty before the turn
    before = working_tree_status(ws)
    (ws / "a.py").write_text("x = 33\n", encoding="utf-8")  # the turn's edit
    after = working_tree_status(ws)
    assert before is not None and after is not None
    assert before["a.py"] != after["a.py"]


# ---------------------------------------------------------------- renderer


def test_plain_renderer_draws_plan_steps_retry_and_interrupt() -> None:
    out: list[str] = []
    stream, _ = _stream()
    stream.subscribe(PlainRenderer(out.append))
    stream.emit(
        "plan.proposed",
        {
            "assumption": "add subtracts",
            "confidence": 0.9,
            "steps": [{"n": 1, "action": "Fix add", "target": "src/calc.py"}],
        },
        turn=1,
    )
    stream.emit(
        "step.started", {"n": 1, "action": "Fix add", "target": "src/calc.py"}, turn=1
    )
    stream.text(
        "def add(a, b):\n    return a + b\n",
        turn=1,
        channel="artifact",
        path="src/calc.py",
    )
    stream.emit(
        "agent.retry",
        {"attempt": 1, "max": 3, "reason": "connection reset", "wait_ms": 1000},
        turn=1,
    )
    stream.emit(
        "step.finished",
        {
            "n": 1,
            "outcome": "done",
            "artifact": "src/calc.py",
            "confidence": None,
            "duration_ms": 900,
            "hint": None,
        },
        turn=1,
    )
    stream.emit(
        "turn.interrupting",
        {"elapsed_ms": 3, "cancellable": False, "detail": "stopping"},
        turn=1,
    )
    text = "".join(out)
    assert (
        "Plan: 1 step, confidence 0.90\n  assumes: add subtracts\n  1. Fix add -> src/calc.py\n"
        in text
    )
    assert (
        "[step 1] Fix add -> src/calc.py\n--- src/calc.py ---\ndef add(a, b):" in text
    )
    assert "  connection reset; trying again in 1 s (attempt 2 of 4)\n" in text
    assert "[step 1] done src/calc.py (0.9s)" in text
    assert (
        "stopping...\n  the model call is still finishing and will write nothing\n"
        in text
    )
