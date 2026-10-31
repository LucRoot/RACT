"""Package 2 (B-064a, ADR-0049 D12): whether a plan is approved before its first step.

Pure decisions, no terminal: the REPL asks when ``approval_needed`` is true, and the headless
run refuses when ``headless_refusal`` names a sentence. A step with a file target changes files;
a step with no target is an answer step and writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import cast

from ract.ui.plan_approval_view import Step, parse_answer, plan_hash

ASK_MODES = frozenset({"default"})

# The error of a run whose plan the operator cancelled. A session ends that turn
# with the outcome ``refused`` and exit 0 (D12); nothing ran.
CANCELLED = "Plan cancelled: nothing was run and no file changed."
# How a step the operator skipped is reported in its ``step.finished`` (D12).
SKIPPED_BY_YOU = "skipped by you"

_skipped: ContextVar[frozenset[int]] = ContextVar(
    "ract_plan_skipped", default=frozenset()
)


@contextmanager
def skipping(numbers: frozenset[int]) -> Iterator[None]:
    """The step numbers the operator skipped, for the steps of this run."""
    token = _skipped.set(numbers)
    try:
        yield
    finally:
        _skipped.reset(token)


def is_skipped(n: int) -> bool:
    """True when the operator skipped step *n* of the plan that is running."""
    return n in _skipped.get()


def _changes_files(steps: list[Step]) -> bool:
    return any(step.target for step in steps)


# B-137: the target an agent step shows (the request run as one step): it can
# change any file its tools reach, so it is always shown before it runs.
AGENT_TARGET = "(the files its tools change)"


def approval_needed(steps: list[Step], *, mode: str) -> bool:
    """True when the plan is shown and approved once, before the first step runs."""
    if mode in ASK_MODES and any(s.target == AGENT_TARGET for s in steps):
        return True
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
    # For ``edit``: the step whose new text the caller asks for.
    n: int | None = None
    # The whole plan as the operator approved it, edits included (the run takes this text).
    shown: list[Step] = field(default_factory=list)


_EDIT_LIMIT = 2000


_PATH_SHAPE = re.compile(r"[A-Za-z_][^.\s]*\.[A-Za-z][A-Za-z0-9]{0,7}$")


def _path_candidates(text: str) -> list[str]:
    """File-like tokens in a line of step text: a path with a separator, or a name with an extension.

    Trailing punctuation is stripped first, so "b." at the end of a sentence is not a path.
    """
    out = []
    for token in text.replace(",", " ").split():
        token = token.strip("`'\"()").rstrip(".;:!?")
        if token.startswith("-") or not token:
            continue
        if "/" in token or "\\" in token or _PATH_SHAPE.search(token):
            out.append(token)
    return out


def apply_edit(
    steps: list[Step],
    n: int,
    new_action: str,
    *,
    check_path: Callable[[str], str | None],
) -> tuple[list[Step] | None, str | None]:
    """The plan with step ``n``'s text replaced (one line), or an error sentence.

    A path the new text names must be one the original plan already named, or one the path check
    accepts (``check_path`` returns None for an accepted path, else the refusal sentence). Nothing
    the text says is run; the edited plan is shown again by the caller.
    """
    text = " ".join(new_action.split())
    if not text:
        return None, "an edit needs one line of new text"
    if len(text) > _EDIT_LIMIT:
        return None, f"an edit is limited to {_EDIT_LIMIT} characters"
    original = {s.target for s in steps if s.target}
    for token in _path_candidates(text):
        if token in original:
            continue
        refusal = check_path(token)
        if refusal is not None:
            return (
                None,
                f"the edit names {token}, which the plan did not list and the path check refuses: {refusal}",
            )
    edited = [replace(s, action=text) if s.n == n else s for s in steps]
    return edited, None


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
        skip_n = cast(int, answer.n)  # a skip answer always names its step
        dropped = {skip_n}
        target = next(step.target for step in steps if step.n == skip_n)
        for step in steps:
            if step.n <= skip_n:
                continue
            same_file = bool(target) and step.target == target
            names_target = (
                isinstance(target, str) and bool(target) and target in step.action
            )
            if same_file or names_target:
                dropped.add(step.n)
        kept = [step for step in steps if step.n not in dropped]
        skipped = [step for step in steps if step.n in dropped]
        return Resolution("approved", kept=kept, skipped=skipped)
    # edit n: the caller asks for the new text and shows the plan again (D12).
    return Resolution("edit", n=answer.n)


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
    # The hash is over the plan's own text (approvals and checkpoints compare
    # it); the shown text is made printable, as every event's text is.
    from ract.session_events import safe_text

    return {
        "plan_hash": plan_hash(steps),
        "steps": [
            {
                "n": s.n,
                "action": safe_text(s.action),
                "target": safe_text(s.target) if s.target else None,
            }
            for s in steps
        ],
    }


def answered_payload(
    steps: list[Step], answer: str, outcome: Resolution, *, edited: int | None = None
) -> dict:
    """The data of ``plan.approval_answered`` (ADR-0049 D12). Reasons are ``user`` for the step the
    operator skipped, and ``depends on step <k>`` for the steps that depend on it (k is that step).
    ``edited`` is the number of the step an ``edit`` changed, or None.
    """
    kept = [s.n for s in outcome.kept]
    skipped_numbers = [s.n for s in outcome.skipped]
    typed = next(
        (
            n
            for n in skipped_numbers
            if answer == "skip" and n == _skip_target(outcome, steps)
        ),
        None,
    )
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
        "edited": edited,
    }


def _skip_target(outcome: Resolution, steps: list[Step]) -> int | None:
    """The step the operator typed in ``skip <n>``: the first skipped step (dependents follow it)."""
    return outcome.skipped[0].n if outcome.skipped else None
