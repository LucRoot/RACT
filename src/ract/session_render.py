"""Render session events for a person reading a terminal or a log.

LR:: The renderer is the only thing that turns session events into text.
``PlainRenderer`` is the reference implementation: line-oriented, no cursor
movement, no color, ASCII markers. It is what non-terminals, ``TERM=dumb``,
screen-reader mode and pipes get, and it is the fallback when an interactive
renderer cannot run. An interactive renderer (B-030 decides the toolkit)
implements the same ``Renderer`` protocol, so the choice is a swap.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from rich.cells import cell_len

from ract import question_gate
from ract.cell_wrap import wrap_cells
from ract.diff_render import draw_turn_diff
from ract.session_events import SessionEvent, safe_text
from ract.turn_summary import describe_change
from ract.undo_backup import previous_version, require_name, turns_dir

# The turn summary draws at most this many files' diffs (B-014b).
_DIFF_FILES = 20
# A file over this many bytes is named, not read (G-146).
_MAX_DIFF_BYTES = 8 * 1024 * 1024

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
        wrap: bool = False,
        labels: bool = False,
        project: Path | None = None,
    ) -> None:
        self._write = write
        self._show_reasoning = show_reasoning
        self._width = width
        # Opt-in: the REPL wraps to the terminal; headless output is unchanged (B-041c).
        self._wrap = wrap
        # The project folder the turn changed: the diff block reads its files
        # from here, and only from here (B-014b). None draws no diff block.
        self._project = project
        # Plain mode (B-041b): the answer block starts with "ract: " and its
        # continuation lines are indented by two spaces.
        self._labels = labels
        self._label_due = False
        self._indent_due = False
        # Step records for the checklist, keyed by step number; None for a
        # one-step plan, which keeps the short lines.
        self._checklist: dict[Any, dict[str, Any]] | None = None
        self._stop_requested = False
        # The provenance warning is printed once per session (D7); the turn summary still counts.
        self._provenance_shown = False
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
        # Package I: an escape byte in any line is replaced here too, not only at the event sources.
        text = safe_text(text)
        if self._mid_line:
            self._write("\n")
            self._mid_line = False
        for piece in self._fit(text) if self._wrap else [text]:
            self._write(piece + "\n")

    def _fit(self, text: str) -> list[str]:
        """The text as lines no wider than the renderer's width (B-041c).

        A longer line wraps at a word boundary. Continuation lines keep the
        line's own indent and add two spaces, so the wrapped text reads as one item.
        """
        if cell_len(text) <= self._width:
            return [text]
        indent = len(text) - len(text.lstrip(" "))
        pad = " " * indent
        # Columns, not characters: a wide character is two columns (package I).
        pieces = wrap_cells(
            text.strip(" "),
            self._width,
            initial_indent=pad,
            subsequent_indent=pad + "  ",
        )
        return pieces or [text]

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
        # None is the event's value for a model or provider no config named (D11).
        model = d.get("model") or "no model"
        provider = d.get("provider") or "no provider"
        branch = f" | {d['branch']}" if d.get("branch") else ""
        self._line(
            f"RACT session {model} via {provider}{branch} | {d.get('mode', 'default')} | T3 {d.get('tier3', 'off')}"
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
        self._stop_requested = False
        self._wrote_file = False
        self._labelled_summary = False
        if d.get("queued"):
            self._line(f"running queued: {d.get('input', '')}")

    def _on_turn_interrupting(self, d: dict[str, Any]) -> None:
        self._stop_requested = True
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
        if self._stop_requested and outcome == "failed":
            # J6: the step ended after the operator stopped the turn; it was stopped, not failed.
            outcome = "skipped"
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
            self._label_due = self._labels
        if target != self._text_target:
            if target[0] == "artifact":
                self._line(f"--- {target[1]} ---")
            elif self._text_target is not None:
                self._line("")
            self._text_target = target
            if self._labels and target[0] == "answer":
                self._label_due = True
                self._indent_due = False
        if self._labels and target[0] == "answer":
            text = self._label_answer(text)
        self._write(text)
        self._mid_line = not text.endswith("\n")

    def _label_answer(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            if self._label_due:
                out.append("ract: ")
                self._label_due = False
            elif self._indent_due and char != "\n":
                out.append("  ")
            self._indent_due = char == "\n"
            out.append(char)
        return "".join(out)

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
        # Adjudication row 5: no tick lands on an open approval question.
        if question_gate.question_open():
            return
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
        self._line(f"error: {_readable_error(str(d.get('message', '')))}")
        self._line(f"hint: {d.get('hint', '')}")
        if d.get("workspace"):
            self._line(str(d["workspace"]))
        if d.get("log"):
            self._line(f"details: {d['log']}")

    def _on_notice(self, d: dict[str, Any]) -> None:
        text = str(d.get("text", ""))
        if text.startswith("provenance: "):
            if self._provenance_shown:
                return
            self._provenance_shown = True
        prefix = "note" if d.get("level") == "info" else "warning"
        self._line(f"{prefix}: {d.get('text', '')}")

    def _citation_lines(self, citations: dict[str, Any]) -> None:
        """One line of counts, then each citation that is not verified (B-037b)."""
        counts = {
            k: int(citations.get(k) or 0)
            for k in ("verified", "unverified", "not_checked")
        }
        if not any(counts.values()):
            return
        parts = [f"{counts['verified']} verified", f"{counts['unverified']} unverified"]
        if counts["not_checked"]:
            parts.append(f"{counts['not_checked']} not checked")
        self._line("  citations: " + ", ".join(parts))
        for item in citations.get("items") or []:
            if item.get("status") == "verified":
                continue
            self._line(
                f"    {safe_text(str(item.get('path')))}:{safe_text(str(item.get('lines')))}: "
                f"{safe_text(str(item.get('reason')))}"
            )

    def _on_review_finished(self, d: dict[str, Any]) -> None:
        """The REVIEWER's findings for one step, labeled as its advice (B-061c)."""
        who = safe_text(str(d.get("reviewer") or "the reviewer"))
        n = d.get("n")
        if d.get("status") != "done":
            note = safe_text(str(d.get("note") or "review not completed"))
            self._line(f"  review of step {n}: {note}")
            return
        findings = d.get("findings") or []
        dropped = sum((d.get("dropped") or {}).values())
        tail = f", {dropped} dropped as unchecked" if dropped else ""
        self._line(
            f"  review of step {n} ({who}, advice only): {len(findings)} finding"
            f"{'' if len(findings) == 1 else 's'}{tail}"
        )
        for f in findings:
            self._line(
                f"    {safe_text(str(f.get('path')))}:{f.get('line')} "
                f"{safe_text(str(f.get('severity')))}: {safe_text(str(f.get('claim')))}"
            )

    def _on_turn_finished(self, d: dict[str, Any]) -> None:
        """The harness's account of the turn (B-038), never the model's.

        Every line is something RACT observed: what changed and by how
        much, the way back, whether RACT ran a verifier, what the plan
        assumed, and what the turn cost.
        """
        self._text_target = None
        seconds = int(d.get("duration_ms", 0)) / 1000
        if self._checklist is not None:
            # A step that did not end (the turn stopped first) was not run to its
            # end, so it is skipped, not left looking like it is still to come (D1).
            for step in self._checklist.values():
                if step["state"] in ("pending", "running"):
                    step["state"] = "skipped"
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
        for line in self._turn_diff(d):
            self._line("  " + line)
        if d.get("undo"):
            # The folder is in the user state directory (S-028); the
            # command is what the user needs, the path is in the event.
            # B-014c: /review takes the change back hunk by hunk.
            self._line("  way back: /undo, or /review per hunk")
        if d.get("checkpoint"):
            self._line(f"  checkpoint {d['checkpoint']}, /undo to revert")
        verification = d.get("verification") or {}
        if verification.get("status") in (None, "not-run"):
            self._line("  verified: RACT ran no tests this turn")
        else:
            self._line(f"  verified: {verification.get('status')}")
        for claim in verification.get("claims") or []:
            self._line(f'  the reply says "{claim}"; nothing in this turn checked that')
        self._citation_lines(d.get("citations") or {})
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

    def _turn_diff(self, d: dict[str, Any]) -> list[str]:
        """The turn's diff lines, drawn from its backup and the project (B-014b).

        The before text is read with ``previous_version`` from the backup
        named by ``backup_id``. The after text is read only for a path that
        resolves inside the project. A path or id that is refused says so.
        """
        changed = d.get("changed")
        backup_id = d.get("backup_id")
        if self._project is None or not changed or not backup_id:
            return []
        paths = [str(path) for path in changed]
        try:
            # The id is checked as a name before it is joined to any folder (G-159).
            require_name(backup_id, "backup id")
        except ValueError:
            return [
                f"diff not available for {safe_text(path)}"
                for path in paths[:_DIFF_FILES]
            ]
        folder = turns_dir(self._project) / backup_id
        if not folder.is_dir():
            # A folder that is not there cannot say what the files were before.
            return [
                f"diff not available for {safe_text(path)}"
                for path in paths[:_DIFF_FILES]
            ]
        changes: list[tuple[str, str | None, str | None]] = []
        lines: list[str] = []
        for path in paths[:_DIFF_FILES]:
            name = safe_text(path)
            if (self._project / path).is_symlink():
                lines.append(f"diff not available for {name}")
                continue
            try:
                saved = previous_version(self._project, backup_id, path)
            except ValueError:
                lines.append(f"diff not available for {name}")
                continue
            current = _project_text(self._project, path)
            too_big = (saved is not None and len(saved) > _MAX_DIFF_BYTES) or (
                _too_large(self._project, path)
            )
            if too_big:
                lines.append(f"{name}: too large to draw a diff")
                continue
            before = None if saved is None else saved.decode("utf-8", "replace")
            changes.append((path, before, current))
        lines += draw_turn_diff(changes, width=self._width)
        if len(paths) > _DIFF_FILES:
            lines.append(f"... and {len(paths) - _DIFF_FILES} more files")
        return lines

    def _cost_line(self, seconds: float) -> str:
        requests = self._cost.get("requests")
        parts = []
        if isinstance(requests, int):
            parts.append(f"{requests} model request{'s' if requests != 1 else ''}")
        parts.append(f"{seconds:.1f} s")
        if self._cost:
            tin, tout = self._cost.get("tokens_in"), self._cost.get("tokens_out")
            parts.append(
                "tokens not reported by the provider"
                if tin is None and tout is None
                else f"{tin or 0} tokens in / {tout or 0} out"
            )
        return ", ".join(parts)


def _readable_error(message: str) -> str:
    """The provider's own message in place of its raw JSON body (D8).

    ``HTTP 503: {"error": {"message": "busy"}}`` reads as ``HTTP 503: busy``.
    Text with no JSON body, or a body without an error message, is returned as is.
    """
    start = message.find("{")
    if start < 0:
        return message
    try:
        body = json.loads(message[start:])
    except ValueError:
        return message
    error = body.get("error") if isinstance(body, dict) else None
    text = error.get("message") if isinstance(error, dict) else None
    if not isinstance(text, str) or not text:
        return message
    return f"{message[:start]}{text}"


def _too_large(project: Path, path: str) -> bool:
    """True when the project file is over the cap; its size is read from disk, not loaded."""
    full = project.resolve() / path
    return full.is_file() and full.stat().st_size > _MAX_DIFF_BYTES


def _project_text(project: Path, path: str) -> str | None:
    """The file's text now, or None when it is gone or outside the project (B-014b)."""
    root = project.resolve()
    full = (root / path).resolve()
    if not full.is_relative_to(root) or not full.is_file():
        return None
    if full.stat().st_size > _MAX_DIFF_BYTES:
        return None
    return full.read_bytes().decode("utf-8", "replace")
