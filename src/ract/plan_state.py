"""The plan's step states, from the events a run emits (B-053b).

One reducer for the plan. The headless result builds its ``plan`` array from it;
the live checklist reads the same words and verdicts. It reads existing events
only (plan.proposed, step.started, step.finished, turn.finished) and changes
nothing about how steps run. Text from the model passes through safe_text.
"""

from __future__ import annotations

from typing import Any

from ract.session_events import SessionEvent, safe_text

# The checklist state words (B-053a), and the harness verdict word for each.
STATES = ("pending", "running", "done", "failed", "refused", "skipped")
VERDICTS = {
    "done": "passed",
    "failed": "failed",
    "refused": "refused",
    "skipped": "skipped",
}


class PlanState:
    """The plan's steps, updated one event at a time."""

    def __init__(self) -> None:
        self._steps: dict[Any, dict[str, Any]] = {}

    def observe(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "plan.proposed":
            self._steps = {}
            for index, step in enumerate(data.get("steps") or [], start=1):
                number = step.get("n") if isinstance(step.get("n"), int) else index
                self._steps[number] = {
                    "title": step.get("action", ""),
                    "target": step.get("target"),
                    "file": step.get("target"),
                    "state": "pending",
                }
        elif kind == "step.started" and data.get("n") in self._steps:
            # A step that already ended is not started again: no step moves back (package O).
            if self._steps[data["n"]]["state"] == "pending":
                self._steps[data["n"]]["state"] = "running"
        elif kind == "step.finished" and data.get("n") in self._steps:
            step = self._steps[data["n"]]
            step["state"] = str(data.get("outcome", "?"))
            step["file"] = data.get("artifact") or step["target"]
        elif kind == "turn.finished":
            # A step that did not end when the turn ended was not run to its end: skipped,
            # the same rule the interactive checklist applies (B-054f, D1).
            for step in self._steps.values():
                if step["state"] in ("pending", "running"):
                    step["state"] = "skipped"

    def items(self) -> list[dict[str, Any]]:
        """The ``plan`` array: step, title, state, file and verdict, nothing else."""
        out = []
        for number, step in self._steps.items():
            state = step["state"]
            file = step["file"]
            out.append(
                {
                    "step": number,
                    "title": safe_text(str(step["title"])),
                    "state": state,
                    "file": None if file is None else safe_text(str(file)),
                    "verdict": VERDICTS.get(state),
                }
            )
        return out


def plan_items(events: list[SessionEvent]) -> list[dict[str, Any]]:
    """The plan array for a whole run, from its events in order."""
    plan = PlanState()
    for event in events:
        plan.observe(event.kind, event.data)
    return plan.items()
