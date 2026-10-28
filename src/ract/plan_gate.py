"""Package 2 (B-064a, ADR-0049 D12): whether a plan is approved before its first step.

Pure decisions, no terminal: the REPL asks when ``approval_needed`` is true, and the headless
run refuses when ``headless_refusal`` names a sentence. A step with a file target changes files;
a step with no target is an answer step and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.ui.plan_approval_view import Step, parse_answer, plan_hash

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


@dataclass(frozen=True)
class Resolution:
    """What an answer does to the plan: ``approved`` (run ``kept``), ``refused`` (cancel), or ``ask_again``."""

    kind: str
    kept: list[Step] = field(default_factory=list)
    skipped: list[Step] = field(default_factory=list)
    error: str | None = None


def resolve_answer(steps: list[Step], line: str) -> Resolution:
    """Apply one operator answer to the plan (ADR-0049 D12, card B-064a point 2).

    ``approve`` keeps every step. ``skip <n>`` drops step ``n`` and every later step whose file
    target is the same file (it depends on the skipped step's output). ``cancel`` keeps nothing.
    An answer that is not understood asks again; nothing is ever run from the text itself.
    """
    answer = parse_answer(line, len(steps))
    if answer.kind == "error":
        return Resolution("ask_again", error=answer.error)
    if answer.kind == "approve":
        return Resolution("approved", kept=list(steps))
    if answer.kind == "cancel":
        return Resolution("refused")
    if answer.kind == "skip":
        dropped = {answer.n}
        target = next(step.target for step in steps if step.n == answer.n)
        for step in steps:
            if step.n <= answer.n:
                continue
            same_file = bool(target) and step.target == target
            names_target = bool(target) and target in step.action
            if same_file or names_target:
                dropped.add(step.n)
        kept = [step for step in steps if step.n not in dropped]
        skipped = [step for step in steps if step.n in dropped]
        return Resolution("approved", kept=kept, skipped=skipped)
    # edit is a later step of the card; until it is built, an edit asks again
    return Resolution("ask_again", error="edit is not available yet; approve, skip <n> or cancel")


class ApprovalMemory:
    """The plans approved in this session, by plan hash, so a resumed session does not ask twice.

    A changed plan has a new hash and asks again (ADR-0049 D12). ``hashes()`` is saved with the
    session and passed back as ``saved`` on resume.
    """

    def __init__(self, saved: list[str] | None = None) -> None:
        self._approved: set[str] = set(saved or [])

    def needs_approval(self, steps: list[Step], *, mode: str) -> bool:
        if not approval_needed(steps, mode=mode):
            return False
        return plan_hash(steps) not in self._approved

    def record(self, steps: list[Step]) -> None:
        self._approved.add(plan_hash(steps))

    def hashes(self) -> list[str]:
        return sorted(self._approved)


def approval_requested_payload(steps: list[Step]) -> dict:
    """The data of ``plan.approval_requested`` (ADR-0049 D12): the hash and the steps as in plan.proposed."""
    return {
        "plan_hash": plan_hash(steps),
        "steps": [{"n": s.n, "action": s.action, "target": s.target} for s in steps],
    }


def answered_payload(steps: list[Step], answer: str, outcome: Resolution) -> dict:
    """The data of ``plan.approval_answered`` (ADR-0049 D12). Reasons are ``user`` for the step the
    operator skipped, and ``depends on step <k>`` for the steps that depend on it (k is that step).
    """
    kept = [s.n for s in outcome.kept]
    skipped_numbers = [s.n for s in outcome.skipped]
    typed = next((n for n in skipped_numbers if answer == "skip" and n == _skip_target(outcome, steps)), None)
    skipped = []
    for n in skipped_numbers:
        if answer == "skip" and n == typed:
            skipped.append({"n": n, "reason": "user"})
        else:
            skipped.append({"n": n, "reason": f"depends on step {typed}"})
    return {
        "plan_hash": plan_hash(steps),
        "answer": answer,
        "kept": kept,
        "skipped": skipped,
        "edited": False,
    }


def _skip_target(outcome: Resolution, steps: list[Step]) -> int | None:
    """The step the operator typed in ``skip <n>``: the first skipped step (dependents follow it)."""
    return outcome.skipped[0].n if outcome.skipped else None
