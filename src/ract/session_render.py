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

from ract.session_events import SessionEvent, safe_text
from ract.turn_summary import describe_change

# B-053a: a plan of this many steps or more prints the checklist block.
CHECKLIST_MIN_STEPS = 2
_MARKS = {
    "pending": "[ ]",
    "running": "[>]",
    "done": "[x]",
    "failed": "[!]",
    "refused": "[!]",
    "skipped": "[-]",
}
# The harness's word for each outcome. An outcome outside this map is shown as is.
_VERDICTS = {
    "done": "passed",
    "failed": "failed",
    "refused": "refused",
    "skipped": "skipped",
}
_MAX_FILE_CHARS = 40

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
        self,
        write: Callable[[str], Any],
        *,
        show_reasoning: bool = False,
        width: int = 80,
    ) -> None:
        self._write = write
        self._show_reasoning = show_reasoning
        self._width = width
        # Step records for the checklist, keyed by step number; None for a
        # one-step plan, which keeps the short lines.
        self._checklist: dict[Any, dict[str, Any]] | None = None
        self._mid_line = False
        self._last_heartbeat_ms = -1
        self._reasoning_chars = 0
        # (channel, path) of the text being written, so a file's content is
        # introduced by its name and never runs into answer text (UX-11).
        self._text_target: tuple[str, str | None] | None = None
        # Facts gathered during the turn for its summary (B-038).
        self._plan: dict[str, Any] = {}
        self._cost: dict[str, Any] = {}
        self._wrote_file = False
        self._labelled_summary = False

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
        self._plan = {}
        self._cost = {}
        self._checklist = None
        self._wrote_file = False
        self._labelled_summary = False
        if d.get("queued"):
            self._line(f"running queued: {d.get('input', '')}")

    def _on_turn_interrupting(self, d: dict[str, Any]) -> None:
        self._line("stopping...")
        if not d.get("cancellable", True):
            self._line("  the model call is still finishing and will write nothing")

    def _on_plan_proposed(self, d: dict[str, Any]) -> None:
        self._plan = dict(d)
        steps = d.get("steps") or []
        if len(steps) >= CHECKLIST_MIN_STEPS:
            self._start_checklist(d, steps)
            return
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

    def _start_checklist(self, d: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        self._checklist = {
            step.get("n"): {
                "action": step.get("action", ""),
                "target": step.get("target"),
                "file": step.get("target"),
                "state": "pending",
                "seconds": 0.0,
                "hint": "",
            }
            for step in steps
        }
        self._line(f"Plan ({len(steps)} steps):")
        if d.get("assumption"):
            self._line(f"  assumes: {d['assumption']}")
        for n in self._checklist:
            self._line(self._checklist_line(n))

    def _checklist_line(self, n: Any) -> str:
        """One step as ``[mark] n. action -> file (seconds) verdict``, within the width."""
        step = self._checklist[n]
        state = step["state"]
        mark = _MARKS.get(state, "[?]")
        where = safe_text(str(step["file"] or "answer"))
        if len(where) > _MAX_FILE_CHARS:
            where = where[: _MAX_FILE_CHARS - 3] + "..."
        tail = ""
        if state in _VERDICTS:
            tail = f" ({step['seconds']:.1f}s) {_VERDICTS[state]}"
        head = f"{mark} {n}. "
        rest = f" -> {where}{tail}"
        action = safe_text(str(step["action"]))
        room = self._width - len(head) - len(rest)
        if len(action) > room:
            action = action[: max(room - 3, 0)] + "..."
        line = head + action + rest
        if len(line) > self._width:
            line = line[: self._width - 3] + "..."
        return line

    def _on_step_started(self, d: dict[str, Any]) -> None:
        self._text_target = None
        if self._checklist is not None and d.get("n") in self._checklist:
            self._checklist[d["n"]]["state"] = "running"
            self._line(self._checklist_line(d["n"]))
            return
        target = f" -> {d['target']}" if d.get("target") else ""
        self._line(f"[step {d.get('n')}] {d.get('action', '')}{target}")

    def _on_step_finished(self, d: dict[str, Any]) -> None:
        self._text_target = None
        seconds = int(d.get("duration_ms", 0)) / 1000
        outcome = d.get("outcome", "?")
        if d.get("artifact") and outcome == "done":
            self._wrote_file = True
        if self._checklist is not None and d.get("n") in self._checklist:
            step = self._checklist[d["n"]]
            step.update(
                state=outcome,
                seconds=seconds,
                file=d.get("artifact") or step["target"],
                hint=d.get("hint") or "",
            )
            self._line(self._checklist_line(d["n"]))
            if outcome != "done" and step["hint"]:
                self._line(f"  hint: {safe_text(str(step['hint']))}")
            return
        what = f" {d['artifact']}" if d.get("artifact") and outcome == "done" else ""
        self._line(f"[step {d.get('n')}] {outcome}{what} ({seconds:.1f}s)")
        if outcome != "done" and d.get("hint"):
            self._line(f"  hint: {d['hint']}")

    def _on_agent_text_delta(self, d: dict[str, Any]) -> None:
        text = str(d.get("text", ""))
        target = (str(d.get("channel", "answer")), d.get("path"))
        if target[0] == "answer" and self._wrote_file and not self._labelled_summary:
            # Prose after the turn changed files is the model's account of
            # what it did, a claim; the harness summary follows (R-113).
            self._line("model summary:")
            self._labelled_summary = True
            self._text_target = target
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
        if d.get("max") == 1:
            self._line(f"  trying once more in {wait:.1f} s: {d.get('reason', '')}")
            return
        # attempt counts retries; the user is told the attempt about to start.
        attempt = int(d.get("attempt", 1)) + 1
        total = int(d.get("max", 1)) + 1
        self._line(
            f"  {d.get('reason', '')}; trying again in {wait:g} s "
            f"(attempt {attempt} of {total})"
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
        if d.get("waiting_on") == "connection":
            self._line(f"  ... connecting to {d.get('detail')} ({elapsed // 1000} s)")
            return
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
        # Shown once in the turn summary; a line per update is noise.
        self._cost = dict(d)

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
        """The harness's account of the turn (B-038), never the model's.

        Every line is something RACT observed: what changed and by how
        much, the way back, whether RACT ran a verifier, what the plan
        assumed, and what the turn cost.
        """
        self._text_target = None
        seconds = int(d.get("duration_ms", 0)) / 1000
        if self._checklist is not None:
            # A step that never ended (an interrupted turn) stays unchecked.
            for step in self._checklist.values():
                if step["state"] == "running":
                    step["state"] = "pending"
            self._line(f"Plan ({len(self._checklist)} steps), final:")
            for n in self._checklist:
                self._line(self._checklist_line(n))
        self._line(f"  {d.get('verdict') or d.get('outcome', '')}")
        changed = d.get("changed")
        if changed is None:
            self._line("  changed: not tracked here (not a git repository)")
        elif changed:
            stats = d.get("diffstat") or {}
            shown = [describe_change(p, stats.get(p)) for p in changed[:10]]
            more = f" and {len(changed) - 10} more" if len(changed) > 10 else ""
            self._line(
                f"  changed: {', '.join(shown)}{more}; unstaged, review with git diff"
            )
        else:
            self._line("  changed: nothing")
        if d.get("undo"):
            # The folder is in the user state directory (S-028); the
            # command is what the user needs, the path is in the event.
            self._line("  way back: /undo")
        if d.get("checkpoint"):
            self._line(f"  checkpoint {d['checkpoint']}, /undo to revert")
        verification = d.get("verification") or {}
        if verification.get("status") in (None, "not-run"):
            self._line("  verified: RACT ran no tests this turn")
        else:
            self._line(f"  verified: {verification.get('status')}")
        for claim in verification.get("claims") or []:
            self._line(f'  the reply says "{claim}"; nothing in this turn checked that')
        if self._plan.get("assumption") and changed:
            confidence = self._plan.get("confidence")
            conf = (
                f"planner confidence {confidence:.2f}, "
                if isinstance(confidence, (int, float))
                else ""
            )
            self._line(f"  assumed: {self._plan['assumption']} ({conf}not checked)")
        unsigned = (d.get("provenance") or {}).get("unsigned_files") or []
        if unsigned:
            self._line(
                f"  unsigned: {len(unsigned)} file{'s' if len(unsigned) != 1 else ''}"
            )
        self._line("  " + self._cost_line(seconds))

    def _cost_line(self, seconds: float) -> str:
        requests = self._cost.get("requests")
        parts = []
        if isinstance(requests, int):
            parts.append(f"{requests} model request{'s' if requests != 1 else ''}")
        parts.append(f"{seconds:.1f} s")
        if self._cost:
            tin, tout = self._cost.get("tokens_in"), self._cost.get("tokens_out")
            parts.append(
                "tokens not reported"
                if tin is None and tout is None
                else f"{tin or 0} tokens in / {tout or 0} out"
            )
        return ", ".join(parts)
