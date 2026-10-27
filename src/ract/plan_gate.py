"""Package 2 (B-064a, ADR-0049 D12): whether a plan is approved before its first step.

Pure decisions, no terminal: the REPL asks when ``approval_needed`` is true, and the headless
run refuses when ``headless_refusal`` names a sentence. A step with a file target changes files;
a step with no target is an answer step and writes nothing.
"""

from __future__ import annotations

from ract.ui.plan_approval_view import Step

ASK_MODES = frozenset({"default"})


def _changes_files(steps: list[Step]) -> bool:
    return any(step.target for step in steps)


def approval_needed(steps: list[Step], *, mode: str) -> bool:
    """True when the plan is shown and approved once, before the first step runs."""
    return mode in ASK_MODES and len(steps) >= 2 and _changes_files(steps)


def headless_refusal(steps: list[Step], *, mode: str) -> str | None:
    """The refusal sentence for ``ract -p`` with a plan that needs approval, or None.

    Headless has no terminal to ask, so it refuses (exit 3); the hint names --accept-edits, which
    runs the plan without asking.
    """
    if not approval_needed(steps, mode=mode):
        return None
    return (
        "the plan changes files and needs approval, and headless runs cannot ask; "
        "re-run with --accept-edits to run it without asking"
    )
