"""Render session events for a person reading a terminal or a log.

LR:: The renderer is the only thing that turns session events into text.
``PlainRenderer`` is the reference implementation: line-oriented, no cursor
movement, no color, ASCII markers. It is what non-terminals, ``TERM=dumb``,
screen-reader mode and pipes get, and it is the fallback when an interactive
renderer cannot run. An interactive renderer (B-030 decides the toolkit)
implements the same ``Renderer`` protocol, so the choice is a swap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ract.session_events import SessionEvent

# The plain renderer prints the first heartbeat after 2 s and then one every
# 10 s. A line every 2 s would be the right sign of life for a person
# watching, but in a log or for a screen reader it is noise; the interactive
# renderer updates a single status row every 2 s instead.
_PLAIN_HEARTBEAT_EVERY_MS = 10_000


class Renderer(Protocol):
    def on_event(self, event: SessionEvent) -> None: ...

    def close(self) -> None: ...


class PlainRenderer:
    """Line-oriented rendering of session events."""

    def __init__(
        self, write: Callable[[str], Any], *, show_reasoning: bool = False
    ) -> None:
        self._write = write
        self._show_reasoning = show_reasoning
        self._mid_line = False
        self._last_heartbeat_ms = -1
        self._reasoning_chars = 0
        # (channel, path) of the text being written, so a file's content is
        # introduced by its name and never runs into answer text (UX-11).
        self._text_target: tuple[str, str | None] | None = None

    # -- helpers

    def _line(self, text: str) -> None:
        if self._mid_line:
            self._write("\n")
            self._mid_line = False
        self._write(text + "\n")

    def __call__(self, event: SessionEvent) -> None:
        self.on_event(event)

    def close(self) -> None:
        if self._mid_line:
            self._write("\n")
            self._mid_line = False

    # -- dispatch

    def on_event(self, event: SessionEvent) -> None:
        handler = getattr(self, "_on_" + event.kind.replace(".", "_"), None)
        if handler is not None:
            handler(event.data)

    def _on_session_started(self, d: dict[str, Any]) -> None:
        branch = f" | {d['branch']}" if d.get("branch") else ""
        self._line(
            f"RACT session {d.get('model', '?')} via {d.get('provider', '?')}{branch} | {d.get('mode', 'default')} | T3 {d.get('tier3', 'off')}"
        )

    def _on_session_resumed(self, d: dict[str, Any]) -> None:
        self._line(
            f"resumed session {d.get('resumed_from', '?')} ({d.get('turns', 0)} earlier turns)"
        )

    def _on_mode_changed(self, d: dict[str, Any]) -> None:
        self._line(f"mode: {d.get('mode')} | T3 {d.get('tier3')}")

    def _on_session_ended(self, d: dict[str, Any]) -> None:
        return  # the prompt disappearing says it; a line here is noise

    def _on_session_rewound(self, d: dict[str, Any]) -> None:
        skipped = d.get("skipped") or []
        self._line(
            f"rewound to turn {d.get('to_turn')} ({d.get('scope')}): "
            f"{d.get('restored', 0)} restored, {len(skipped)} skipped"
        )
        for item in skipped:
            self._line(f"  skipped: {item.get('path')} ({item.get('reason')})")

    def _on_input_queued(self, d: dict[str, Any]) -> None:
        self._line(f"  queued ({d.get('position')}): {d.get('text', '')}")

    def _on_input_withdrawn(self, d: dict[str, Any]) -> None:
        self._line(f"  queued item {d.get('position')} taken back")

    def _on_turn_started(self, d: dict[str, Any]) -> None:
        self._last_heartbeat_ms = -1
        self._reasoning_chars = 0
        self._text_target = None
        if d.get("queued"):
            self._line(f"running queued: {d.get('input', '')}")

    def _on_turn_interrupting(self, d: dict[str, Any]) -> None:
        self._line("stopping...")
        if not d.get("cancellable", True):
            self._line("  the model call is still finishing and will write nothing")

    def _on_plan_proposed(self, d: dict[str, Any]) -> None:
        steps = d.get("steps") or []
        confidence = d.get("confidence")
        conf = (
            f", confidence {confidence:.2f}"
            if isinstance(confidence, (int, float))
            else ""
        )
        self._line(f"Plan: {len(steps)} step{'s' if len(steps) != 1 else ''}{conf}")
        if d.get("assumption"):
            self._line(f"  assumes: {d['assumption']}")
        for step in steps:
            target = f" -> {step['target']}" if step.get("target") else ""
            self._line(f"  {step.get('n')}. {step.get('action', '')}{target}")

    def _on_step_started(self, d: dict[str, Any]) -> None:
        self._text_target = None
        target = f" -> {d['target']}" if d.get("target") else ""
        self._line(f"[step {d.get('n')}] {d.get('action', '')}{target}")

    def _on_step_finished(self, d: dict[str, Any]) -> None:
        self._text_target = None
        seconds = int(d.get("duration_ms", 0)) / 1000
        outcome = d.get("outcome", "?")
        what = f" {d['artifact']}" if d.get("artifact") and outcome == "done" else ""
        self._line(f"[step {d.get('n')}] {outcome}{what} ({seconds:.1f}s)")
        if outcome != "done" and d.get("hint"):
            self._line(f"  hint: {d['hint']}")

    def _on_agent_text_delta(self, d: dict[str, Any]) -> None:
        text = str(d.get("text", ""))
        target = (str(d.get("channel", "answer")), d.get("path"))
        if target != self._text_target:
            if target[0] == "artifact":
                self._line(f"--- {target[1]} ---")
            elif self._text_target is not None:
                self._line("")
            self._text_target = target
        self._write(text)
        self._mid_line = not text.endswith("\n")

    def _on_agent_retry(self, d: dict[str, Any]) -> None:
        wait = int(d.get("wait_ms", 0)) / 1000
        self._line(
            f"  retrying ({d.get('attempt')} of {d.get('max')}) in {wait:.1f}s: "
            f"{d.get('reason', '')}"
        )

    def _on_agent_reasoning_delta(self, d: dict[str, Any]) -> None:
        text = str(d.get("text", ""))
        self._reasoning_chars += len(text)
        if self._show_reasoning:
            self._line("  (thinking) " + text.replace("\n", "\n  (thinking) "))

    def _on_agent_heartbeat(self, d: dict[str, Any]) -> None:
        elapsed = int(d.get("elapsed_ms", 0))
        due = (
            self._last_heartbeat_ms < 0
            or elapsed - self._last_heartbeat_ms >= _PLAIN_HEARTBEAT_EVERY_MS
        )
        if not due:
            return
        self._last_heartbeat_ms = elapsed
        detail = f", {d['detail']}" if d.get("detail") else ""
        thinking = (
            f", {self._reasoning_chars} chars of reasoning so far"
            if self._reasoning_chars
            else ""
        )
        self._line(
            f"  ... waiting on {d.get('waiting_on', '?')} ({elapsed // 1000} s{detail}{thinking})"
        )

    def _on_tool_call_started(self, d: dict[str, Any]) -> None:
        repairs = f"  ({'; '.join(d['repairs'])})" if d.get("repairs") else ""
        self._line(
            f"  > {d.get('summary', d.get('tool', '?'))}  [{d.get('tier', '?')}]{repairs}"
        )

    def _on_tool_call_finished(self, d: dict[str, Any]) -> None:
        status = "ok" if d.get("ok") else "failed"
        cut = "  [truncated]" if d.get("truncated") else ""
        self._line(
            f"    {status} {int(d.get('duration_ms', 0)) / 1000:.1f}s  {d.get('summary', '')}{cut}"
        )
        if not d.get("ok") and d.get("hint"):
            self._line(f"    hint: {d['hint']}")

    def _on_diff_proposed(self, d: dict[str, Any]) -> None:
        self._line(f"--- {d.get('path')} (proposed, {d.get('tier', 'T1')})")
        for hunk in d.get("hunks", []):
            self._line(f"[{hunk.get('id')}] {hunk.get('header', '')}")
            for row in str(hunk.get("text", "")).splitlines():
                self._line(row)

    def _on_diff_reviewed(self, d: dict[str, Any]) -> None:
        self._line(f"    {d.get('path')} hunk {d.get('hunk')}: {d.get('decision')}")

    def _on_change_applied(self, d: dict[str, Any]) -> None:
        paths = ", ".join(d.get("paths", [])) or "nothing"
        self._line(f"  applied: {paths}  (checkpoint {d.get('checkpoint')})")
        for skipped in d.get("skipped", []):
            self._line(f"  left alone: {skipped.get('path')} ({skipped.get('reason')})")

    def _on_approval_requested(self, d: dict[str, Any]) -> None:
        self._line(f"? approval needed [{d.get('tier')}]: {d.get('action')}")
        if d.get("reason"):
            self._line(f"  model's reason: {d['reason']}")
        self._line("  choices: " + ", ".join(d.get("choices", [])))

    def _on_approval_resolved(self, d: dict[str, Any]) -> None:
        self._line(f"  approval {d.get('id')}: {d.get('choice')} ({d.get('by')})")

    def _on_cost_updated(self, d: dict[str, Any]) -> None:
        return  # shown in turn.finished and on request; a line per update is noise

    def _on_error_surfaced(self, d: dict[str, Any]) -> None:
        self._line(f"error: {d.get('message', '')}")
        self._line(f"hint: {d.get('hint', '')}")
        if d.get("workspace"):
            self._line(str(d["workspace"]))
        if d.get("log"):
            self._line(f"details: {d['log']}")

    def _on_notice(self, d: dict[str, Any]) -> None:
        prefix = "note" if d.get("level") == "info" else "warning"
        self._line(f"{prefix}: {d.get('text', '')}")

    def _on_turn_finished(self, d: dict[str, Any]) -> None:
        self._text_target = None
        parts = [d.get("verdict") or d.get("outcome", "")]
        if d.get("workspace"):
            parts.append(str(d["workspace"]))
        elif d.get("changed") is not None:  # None: not a git repository
            changed = d["changed"]
            parts.append(
                f"changed: {', '.join(changed)}" if changed else "no files changed"
            )
        provenance = d.get("provenance") or {}
        if provenance.get("unsigned_files"):
            parts.append(f"unsigned: {len(provenance['unsigned_files'])}")
        if d.get("checkpoint"):
            parts.append(f"checkpoint {d['checkpoint']}, /undo to revert")
        parts.append(f"{int(d.get('duration_ms', 0)) / 1000:.1f}s")
        self._line("  " + " | ".join(str(p) for p in parts if p))
