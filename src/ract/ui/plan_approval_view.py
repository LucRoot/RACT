"""The plan approval screen as data and text (B-064b, PREPARED and unwired).

Pure: no import from the event layer, no input read, no event emitted. The screen
shows the plan as checklist lines with one question under them; the answer parser
reads one short line (`a`, `s <n>`, `e <n>`, `c`, with plain-words aliases); the
edited plan is plain data. The BUILDER wires the prompt and the events (ADR-0049 D12).

Shape assumed beside this module (see the note in docs/ux/plan_approval_shape.md):
  plan.approval_requested  {plan_hash, steps}
  plan.approval_answered   {plan_hash, answer, kept, skipped: [{n, reason}], edited}
  cancel ends the turn with the existing outcome "refused".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from ract.cell_wrap import wrap_cells

QUESTION = "Run it? [a]pprove  [s]kip <n>  [e]dit <n>  [c]ancel"
CHOICES = "type a, s <n>, e <n> or c"
_APPROVE = {"a", "approve", "run", "yes"}
_CANCEL = {"c", "cancel", "stop", "no"}
_SKIP = {"s", "skip"}
_EDIT = {"e", "edit"}


@dataclass(frozen=True)
class Step:
    """A plan step as the checklist shows it: a number, what it does, and the file it touches."""

    n: int
    action: str
    target: str | None = None
    state: str = "pending"  # pending or skipped


@dataclass(frozen=True)
class Answer:
    """One parsed answer. ``error`` is set when the line was not an answer; ask again."""

    kind: str  # approve, skip, edit, cancel or error
    n: int | None = None
    error: str | None = None


def screen_lines(steps: list[Step], width: int, *, rich: bool = False) -> list[str]:
    """The checklist lines and the question, folded to ``width`` columns."""
    lines = [f"Plan: {len(steps)} step{'s' if len(steps) != 1 else ''}"]
    for step in steps:
        mark = "[-]" if step.state == "skipped" else "[ ]"
        target = f" -> {step.target}" if step.target else ""
        text = f"{mark} {step.n}. {step.action}{target}"
        if rich and step.state == "skipped":
            text = f"[dim]{text}[/dim]"
        lines.extend(wrap_cells(text, width, subsequent_indent="      "))
    lines.extend(wrap_cells(QUESTION, width))
    return lines


def parse_answer(line: str, step_count: int) -> Answer:
    """One line from the operator. Anything not understood is an error, never an approval."""
    words = line.strip().lower().split()
    if not words:
        return Answer("error", error=f"no answer; {CHOICES}")
    word = words[0]
    rest = words[1:]
    if word in _APPROVE and not rest:
        return Answer("approve")
    if word in _CANCEL and not rest:
        return Answer("cancel")
    if word in _SKIP or word in _EDIT:
        kind = "skip" if word in _SKIP else "edit"
        if len(rest) != 1:
            return Answer(
                "error", error=f"{word} needs a step number, as in '{word} 2'"
            )
        try:
            n = int(rest[0])
        except ValueError:
            return Answer("error", error=f"'{rest[0]}' is not a step number; {CHOICES}")
        if not 1 <= n <= step_count:
            return Answer(
                "error", error=f"no step {n}; the plan has {step_count} steps"
            )
        return Answer(kind, n=n)
    return Answer("error", error=f"'{line.strip()}' is not an answer; {CHOICES}")


def skip(steps: list[Step], n: int) -> list[Step]:
    """The plan with step ``n`` marked skipped; the others unchanged."""
    return [replace(step, state="skipped") if step.n == n else step for step in steps]


def edit(steps: list[Step], n: int, new_action: str) -> list[Step]:
    """The plan with step ``n``'s action replaced by one line of new text."""
    text = new_action.strip()
    if not text:
        raise ValueError("an edit needs one line of new text")
    return [replace(step, action=text) if step.n == n else step for step in steps]


def plan_hash(steps: list[Step]) -> str:
    """sha256 of the canonical JSON of each step's ``n``, ``action`` and ``target`` (D12).

    Confidence and the assumption are not in the hash, so a re-planned identical plan
    does not ask twice.
    """
    canonical = json.dumps(
        [{"action": s.action, "n": s.n, "target": s.target} for s in steps],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def answer_record(steps: list[Step], answer: str, edited: bool) -> dict:
    """The data of ``plan.approval_answered``, built and not emitted here."""
    skipped = [
        {"n": s.n, "reason": "skipped by the operator"}
        for s in steps
        if s.state == "skipped"
    ]
    kept = [s.n for s in steps if s.state != "skipped"]
    return {
        "plan_hash": plan_hash(steps),
        "answer": answer,
        "kept": kept,
        "skipped": skipped,
        "edited": edited,
    }
