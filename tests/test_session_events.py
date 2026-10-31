"""Session event stream and plain renderer (B-012, docs/EVENTS_SESSION.md)."""

from __future__ import annotations

import ast
import io
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract.session_events import (
    KINDS,
    RESERVED_KINDS,
    SCHEMA_VERSION,
    EventStream,
    Heartbeat,
    JsonlSink,
    UnknownEventKind,
    safe_text,
    split_text,
)
from ract.session_render import PlainRenderer

REPO = Path(__file__).resolve().parent.parent
FIXED = datetime(2026, 10, 21, 18, 2, 11, 482000, tzinfo=timezone.utc)


def _stream() -> EventStream:
    return EventStream(session="s-1", clock=lambda: FIXED)


# ---------------------------------------------------------------- contract with the doc


def _kind_rows(section: str) -> set[str]:
    """Backticked names in the first column of tables headed ``| Kind |``."""
    names: set[str] = set()
    in_kind_table = False
    for line in section.splitlines():
        if line.startswith("| Kind |"):
            in_kind_table = True
            continue
        if not line.startswith("|"):
            in_kind_table = False
            continue
        if in_kind_table:
            match = re.match(r"^\| `([a-z_.]+)`", line)
            if match:
                names.add(match.group(1))
    return names


def test_kinds_match_the_schema_document() -> None:
    doc = (REPO / "docs" / "EVENTS_SESSION.md").read_text(encoding="utf-8")
    kinds_section = doc[doc.index("## Kinds") : doc.index("### Reserved names")]
    reserved_section = doc[
        doc.index("### Reserved names") : doc.index("## Headless mode")
    ]
    documented = _kind_rows(kinds_section)
    # A reserved row may name two kinds: "| `a.started`, `a.finished` |".
    reserved = _kind_rows(reserved_section) | set(
        re.findall(r"^\| `[a-z_.]+`, `([a-z_.]+)` \|", reserved_section, flags=re.M)
    )
    assert documented == set(KINDS)
    assert reserved == set(RESERVED_KINDS)
    assert f"session_events_version: {SCHEMA_VERSION}" in doc.split("---")[1]


def test_envelope_shape_and_order() -> None:
    stream = _stream()
    seen: list[dict] = []
    stream.subscribe(lambda e: seen.append(json.loads(e.to_json())))
    stream.emit("turn.started", {"input": "hi", "queued": False}, turn=1)
    stream.emit("notice", {"level": "info", "text": "x"}, turn=1)
    assert [e["seq"] for e in seen] == [1, 2]
    assert seen[0] == {
        "v": 2,
        "seq": 1,
        "t": "2026-10-21T18:02:11.482Z",
        "session": "s-1",
        "turn": 1,
        "kind": "turn.started",
        "data": {"input": "hi", "queued": False},
    }


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(UnknownEventKind):
        _stream().emit("shell_exec", {})


def test_data_must_be_json_values() -> None:
    with pytest.raises(TypeError):
        _stream().emit("notice", {"level": "info", "text": object()})


def test_text_is_made_print_safe() -> None:
    # A carriage return is dropped (B-045): it can no longer return the cursor
    # to overwrite "ok", and CRLF text shows no replacement character.
    assert safe_text("ok\x1b[2J\rhidden\tand\nkept") == "ok�[2Jhidden\tand\nkept"
    stream = _stream()
    seen: list = []
    stream.subscribe(seen.append)
    stream.emit("agent.text.delta", {"text": "a\x1b]0;title\x07b"})
    assert "\x1b" not in seen[0].data["text"]


def test_split_text_respects_byte_limit_and_characters() -> None:
    text = "é" * 3000  # 2 bytes each
    pieces = split_text(text, limit=4096)
    assert "".join(pieces) == text
    assert all(len(p.encode("utf-8")) <= 4096 for p in pieces)


def test_error_needs_a_hint() -> None:
    with pytest.raises(ValueError, match="hint"):
        _stream().error("boom", hint=" ", workspace="no files were changed")


def test_a_failing_consumer_is_detached_and_reported() -> None:
    stream = _stream()
    seen: list = []

    def broken(_event) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("bad renderer")

    stream.subscribe(broken)
    stream.subscribe(seen.append)
    stream.emit("notice", {"level": "info", "text": "first"})
    stream.emit("notice", {"level": "info", "text": "second"})
    kinds_texts = [(e.kind, e.data.get("text")) for e in seen]
    assert ("notice", "first") in kinds_texts
    assert any("detached" in (t or "") for _, t in kinds_texts)
    assert ("notice", "second") in kinds_texts


def test_order_holds_across_threads() -> None:
    stream = _stream()
    seqs: list[int] = []
    stream.subscribe(lambda e: seqs.append(e.seq))
    threads = [
        threading.Thread(
            target=lambda: [
                stream.emit("notice", {"level": "info", "text": "x"})
                for _ in range(200)
            ]
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seqs == list(range(1, 801))


def test_jsonl_sink_writes_one_object_per_line() -> None:
    out = io.StringIO()
    stream = _stream()
    stream.subscribe(JsonlSink(out.write))
    stream.emit("turn.started", {"input": "x", "queued": False}, turn=1)
    stream.text("hello", turn=1)
    lines = out.getvalue().splitlines()
    assert [json.loads(line)["kind"] for line in lines] == [
        "turn.started",
        "agent.text.delta",
    ]


def test_heartbeat_ticks_from_a_timer() -> None:
    stream = _stream()
    beats: list = []
    stream.subscribe(lambda e: beats.append(e) if e.kind == "agent.heartbeat" else None)
    # The production timer, smoke only: the exact tick counts are checked with an
    # injected pace in test_heartbeat_counts_injected_ticks_not_wall_time (B-071).
    with Heartbeat(stream, turn=1, waiting_on="model", interval=0.05):
        time.sleep(0.3)
    assert len(beats) >= 1
    assert all(b.data["waiting_on"] == "model" for b in beats)
    elapsed = [b.data["elapsed_ms"] for b in beats]
    assert elapsed == sorted(elapsed)


def test_session_events_module_prints_nothing() -> None:
    for name in ("session_events.py",):
        tree = ast.parse((REPO / "src" / "ract" / name).read_text(encoding="utf-8"))
        calls = [
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        assert "print" not in calls
        assert "sys.stdout" not in (REPO / "src" / "ract" / name).read_text(
            encoding="utf-8"
        )


# ---------------------------------------------------------------- plain renderer


def _render(*events: tuple[str, dict]) -> str:
    out = io.StringIO()
    stream = _stream()
    renderer = PlainRenderer(out.write)
    stream.subscribe(renderer)
    for kind, data in events:
        stream.emit(kind, data, turn=1)
    renderer.close()
    return out.getvalue()


def test_plain_renderer_streams_text_then_finishes_on_its_own_line() -> None:
    text = _render(
        ("turn.started", {"input": "q", "queued": False}),
        ("agent.text.delta", {"text": "The loader "}),
        ("agent.text.delta", {"text": "is in config.py:12."}),
        (
            "turn.finished",
            {
                "outcome": "done",
                "duration_ms": 2100,
                "verdict": "Answered.",
                "changed": [],
                "checkpoint": None,
            },
        ),
    )
    assert "The loader is in config.py:12.\n" in text
    # B-038: the summary is one fact per line, assembled by the harness; the
    # verdict line carries its label (MASON's verdict screen).
    assert text.rstrip().endswith(
        "  verdict: Answered.\n  changed: nothing\n"
        "  verified: RACT ran no tests this turn\n  2.1 s"
    )


def test_plain_renderer_heartbeat_first_at_2s_then_every_10s() -> None:
    beats = [
        ("agent.heartbeat", {"waiting_on": "model", "elapsed_ms": ms, "detail": ""})
        for ms in (2000, 4000, 6000, 12000, 14000)
    ]
    text = _render(("turn.started", {"input": "q", "queued": False}), *beats)
    lines = [line for line in text.splitlines() if "waiting on model" in line]
    assert lines == ["  ... waiting on model (2 s)", "  ... waiting on model (12 s)"]


def test_plain_renderer_error_has_hint_and_workspace_state() -> None:
    text = _render(
        (
            "error.surfaced",
            {
                "message": "cannot reach the model at http://127.0.0.1:8080/v1 (connection refused)",
                "hint": "start your server, or run /model to pick another",
                "workspace": "no files were changed",
                "log": None,
            },
        )
    )
    assert text.splitlines() == [
        "error: cannot reach the model at http://127.0.0.1:8080/v1 (connection refused)",
        "hint: start your server, or run /model to pick another",
        "no files were changed",
    ]


def test_plain_renderer_hides_reasoning_unless_asked() -> None:
    hidden = _render(("agent.reasoning.delta", {"text": "secret plan"}))
    assert "secret plan" not in hidden


def test_plain_renderer_output_is_ascii_safe_and_fits_80_columns_for_fixed_lines() -> (
    None
):
    text = _render(
        (
            "tool.call.started",
            {
                "id": "1",
                "tool": "read_file",
                "tier": "T0",
                "summary": "read_file src/app.py:1-60",
                "repairs": [],
                "rung": "native",
            },
        ),
        (
            "tool.call.finished",
            {
                "id": "1",
                "ok": False,
                "duration_ms": 20,
                "summary": "not found",
                "truncated": False,
                "hint": "check the path",
            },
        ),
    )
    assert "  > read_file src/app.py:1-60  [T0]" in text
    assert "    hint: check the path" in text
    assert all(len(line) <= 80 for line in text.splitlines())
    assert text.isascii()


def test_heartbeat_stops_when_the_turn_is_cancelled() -> None:
    stream = _stream()
    beats: list = []
    stream.subscribe(lambda e: beats.append(e) if e.kind == "agent.heartbeat" else None)
    cancel = threading.Event()
    with Heartbeat(stream, turn=1, waiting_on="model", interval=0.05, cancel=cancel):
        time.sleep(0.2)
        cancel.set()
        count = len(beats)
        time.sleep(0.3)
    assert count >= 1
    assert len(beats) <= count + 1


@pytest.mark.parametrize("size", range(1, 41))
def test_crlf_artifact_text_renders_without_replacement_characters(size: int) -> None:
    # B-045: a reply with CRLF line endings showed U+FFFD before every break.
    from ract.session_events import EventStream
    from ract.session_render import PlainRenderer

    content = "def add(a, b):\r\n    return a + b\r\n\r\n\r\ndef sub(a, b):\r\n    return a - b\r\n"
    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    writer = stream.writer(turn=1, channel="artifact", path="src/calc.py")
    for i in range(0, len(content), size):
        writer.feed(content[i : i + size])
    writer.close()

    shown = "".join(out).split("--- src/calc.py ---\n", 1)[1]
    assert shown == content.replace("\r\n", "\n")


class _Ticks:
    """A pace for Heartbeat: each call waits for the test to release one tick.

    A released tick advances the fake clock by one interval, so the beat's
    elapsed time is exact and no sleep is involved.
    """

    def __init__(self, now: list[float]) -> None:
        self.now = now
        self.release = threading.Semaphore(0)
        self.calls = 0
        self.stopped = False

    def __call__(self, seconds: float) -> bool:
        self.release.acquire()
        self.calls += 1
        if self.stopped:
            return True
        self.now[0] += seconds
        return False


def test_heartbeat_counts_injected_ticks_not_wall_time() -> None:
    stream = _stream()
    beats: list = []
    beat_seen = threading.Semaphore(0)

    def record(event: object) -> None:
        if event.kind == "agent.heartbeat":
            beats.append(event)
            beat_seen.release()

    stream.subscribe(record)
    # Both clocks start at zero. From time.monotonic() after days of uptime,
    # (t + 0.05) - t is a hair under 0.05, the quiet-while-active check skips
    # the beat and the elapsed time reads 49 ms; the arithmetic is exact here.
    stream.last_activity = 0.0
    now = [0.0]
    ticks = _Ticks(now)
    with Heartbeat(
        stream,
        turn=1,
        waiting_on="model",
        interval=0.05,
        clock=lambda: now[0],
        pace=ticks,
    ):
        for expected in (1, 2, 3):
            ticks.release.release()
            assert beat_seen.acquire(timeout=5), f"no beat for tick {expected}"
    ticks.stopped = True
    ticks.release.release()
    assert len(beats) == 3
    assert [b.data["elapsed_ms"] for b in beats] == [50, 100, 150]
    assert all(b.data["waiting_on"] == "model" for b in beats)


def test_a_stalled_clock_gives_no_beats() -> None:
    stream = _stream()
    beats: list = []
    stream.subscribe(lambda e: beats.append(e) if e.kind == "agent.heartbeat" else None)
    now = [time.monotonic()]
    calls: list[float] = []

    def pace(seconds: float) -> bool:
        # Three ticks pass and the clock never moves; the fourth ends the loop.
        calls.append(seconds)
        return len(calls) > 3

    with Heartbeat(
        stream,
        turn=1,
        waiting_on="model",
        interval=0.05,
        clock=lambda: now[0],
        pace=pace,
    ):
        pass  # __exit__ waits for the loop to finish
    assert len(calls) == 4
    assert beats == []
